using System.Collections.Concurrent;
using System.Buffers.Binary;
using System.Text.Json;
using Findie.Api.Infrastructure;
using Findie.Api.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;

static class BrokerChecks
{
    public static async Task RunAsync(IServiceScopeFactory scopes)
    {
        var uri = Environment.GetEnvironmentVariable("FINDIE_TEST_BROKER_URI")
            ?? throw new InvalidOperationException("Use integration.py to provide a disposable RabbitMQ broker.");
        if (!new Uri(uri).IsLoopback) throw new InvalidOperationException("Broker tests require loopback.");
        var prefix = "findie-test-" + Guid.NewGuid().ToString("N");
        var settings = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["RabbitMq:Uri"] = uri, ["RabbitMq:IndexQueue"] = prefix + "-index",
            ["RabbitMq:ImageQueue"] = prefix + "-image", ["RabbitMq:QueryQueue"] = prefix + "-query",
            ["RabbitMq:ResultQueue"] = prefix + "-results", ["RabbitMq:MaterialsQueue"] = prefix + "-materials",
            ["RabbitMq:MaterialsReplyQueue"] = prefix + "-materials-results"
        }).Build();
        var connectionFactory = new ConnectionFactory { Uri = new Uri(uri) };
        await using var connection = await connectionFactory.CreateConnectionAsync();
        await using var worker = await connection.CreateChannelAsync(new CreateChannelOptions(true, true));
        foreach (var suffix in new[] { "index", "image", "query", "results" })
            await worker.QueueDeclareAsync(prefix + "-" + suffix, suffix is "index" or "results", suffix is "image" or "query", suffix is "image" or "query",
                new Dictionary<string, object?> { ["x-message-ttl"] = suffix == "image" ? 955000 : 45000, ["x-max-length"] = 64 });
        var errors = new ConcurrentQueue<Exception>();
        var transientQueues = new ConcurrentBag<string>();
        var imageSeen = false;
        var batchSeen = false;
        var indexSeen = false;
        var materialsSeen = false;
        var materialsComplete = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        await using var materialReplies = await connection.CreateChannelAsync();
        await materialReplies.QueueDeclareAsync(prefix + "-materials-results", durable: false, exclusive: true, autoDelete: true,
            new Dictionary<string, object?> { ["x-message-ttl"] = 15000, ["x-max-length"] = 4, ["x-max-length-bytes"] = 32 * 1024 * 1024, ["x-overflow"] = "reject-publish" });
        var materialConsumer = new AsyncEventingBasicConsumer(materialReplies);
        materialConsumer.ReceivedAsync += async (_, response) =>
        {
            try
            {
                Check(!response.BasicProperties.Persistent && response.BasicProperties.Expiration == "15000", "material replies are transient with a bounded TTL");
                using var metadata = JsonDocument.Parse((byte[])response.BasicProperties.Headers!["metadata"]!);
                if (metadata.RootElement.GetProperty("complete").GetBoolean())
                {
                    using var manifest = JsonDocument.Parse(response.Body);
                    Check(manifest.RootElement.GetProperty("count").GetInt32() == 1 && materialsSeen, "material batch finishes only after each candidate response");
                    materialsComplete.TrySetResult(true);
                }
                else
                {
                    var size = BinaryPrimitives.ReadInt32BigEndian(response.Body.Span);
                    using var manifest = JsonDocument.Parse(response.Body.Slice(4, size));
                    Check(manifest.RootElement.GetProperty("status").GetString() == "stale" && response.Body.Length == size + 4,
                        "missing material sources return a bounded status packet without image bytes");
                    materialsSeen = true;
                }
            }
            catch (Exception error) { errors.Enqueue(error); materialsComplete.TrySetException(error); }
            finally { await materialReplies.BasicAckAsync(response.DeliveryTag, false); }
        };
        await materialReplies.BasicConsumeAsync(prefix + "-materials-results", false, materialConsumer);
        var consumer = new AsyncEventingBasicConsumer(worker);
        consumer.ReceivedAsync += async (_, command) =>
        {
            try
            {
                var metadata = JsonDocument.Parse((byte[])command.BasicProperties.Headers!["metadata"]!).RootElement.Clone();
                if (command.BasicProperties.Type is "image.embed" or "image.redact" or "search.hybrid.image")
                {
                    Check(!command.BasicProperties.Persistent && command.Body.Span.SequenceEqual("private raw input"u8), "raw image is binary and nonpersistent");
                    Check(command.BasicProperties.Expiration == (command.BasicProperties.Type == "search.hybrid.image" ? "315000" : "300000"),
                        "search adds the quality budget while image OCR, embedding and redaction keep their five-minute TTL");
                    imageSeen = true;
                }
                else if (command.BasicProperties.Type == "search.hybrid.images")
                {
                    Check(!command.BasicProperties.Persistent && command.BasicProperties.ContentType == "application/octet-stream"
                        && command.RoutingKey == prefix + "-image" && command.Body.Length == 3 * BoundedImage.MaxBytes,
                        "a complete 30 MiB raw image batch reaches the image queue through transient transport");
                    Check(command.BasicProperties.Expiration == "955000", "multimodal fusion includes the fifteen-second quality budget");
                    batchSeen = true;
                }
                else Check(command.BasicProperties.Expiration == (command.BasicProperties.Type == "search.hybrid" ? "45000" : "30000"),
                    "text search adds the quality budget while other AI requests keep their thirty-second TTL");
                if (command.BasicProperties.Type == "test.materials")
                {
                    var itemId = Guid.NewGuid();
                    var request = JsonSerializer.SerializeToUtf8Bytes(new { candidates = new[] { new { itemId,
                        sources = new[] { new { documentVersion = 1, sourceId = itemId, sourceVersion = 1,
                            sourceSha256 = new string('a', 64), sourceKind = "text" } } } } });
                    await worker.BasicPublishAsync("", prefix + "-materials", true, new BasicProperties
                    {
                        Type = "search.materials", CorrelationId = Guid.NewGuid().ToString(), ReplyTo = prefix + "-materials-results",
                        ContentType = "application/json", Persistent = false, Expiration = "15000",
                        Headers = new Dictionary<string, object?> { ["metadata"] = JsonSerializer.SerializeToUtf8Bytes(new
                            { schemaVersion = 1, deadlineAt = DateTimeOffset.UtcNow.AddSeconds(15) }) }
                    }, request);
                    await materialsComplete.Task.WaitAsync(TimeSpan.FromSeconds(10));
                }
                if (command.BasicProperties.Type == "index.upsert")
                {
                    Check(command.BasicProperties.Persistent && command.BasicProperties.ReplyTo == prefix + "-results", "index receipt uses durable result queue");
                    indexSeen = true;
                }
                else transientQueues.Add(command.BasicProperties.ReplyTo!);
                if (command.BasicProperties.Type == "test.cancel") await Task.Delay(200);
                var properties = new BasicProperties { CorrelationId = command.BasicProperties.CorrelationId,
                    Type = command.BasicProperties.Type, Persistent = command.BasicProperties.Persistent,
                    Headers = new Dictionary<string, object?> { ["metadata"] = JsonSerializer.SerializeToUtf8Bytes(metadata) } };
                if (command.BasicProperties.Type == "test.invalid") properties.Headers["metadata"] = "invalid-json"u8.ToArray();
                await worker.BasicPublishAsync("", command.BasicProperties.ReplyTo!, true, properties, "{\"ok\":true}"u8.ToArray());
                if (command.BasicProperties.Type == "test.duplicate")
                    await worker.BasicPublishAsync("", command.BasicProperties.ReplyTo!, true, properties, "{\"duplicate\":true}"u8.ToArray());
                await worker.BasicAckAsync(command.DeliveryTag, false);
            }
            catch (Exception error) { errors.Enqueue(error); }
        };
        foreach (var suffix in new[] { "index", "image", "query" })
            await worker.BasicConsumeAsync(prefix + "-" + suffix, false, consumer);
        using var gateway = new RabbitMqGateway(settings, NullLogger<RabbitMqGateway>.Instance, scopes);
        await gateway.StartAsync(default);
        try
        {
            var deadline = DateTimeOffset.UtcNow.AddSeconds(20);
            while (!gateway.Ready && DateTimeOffset.UtcNow < deadline) await Task.Delay(50);
            Check(gateway.Ready, "long-lived AMQP connection and consumers start");
            await Query("image.redact", "private raw input"u8.ToArray(), "image/png");
            await Query("image.embed", "private raw input"u8.ToArray(), "image/png");
            await Query("search.hybrid.image", "private raw input"u8.ToArray(), "image/png");
            await Query("search.hybrid.images", new byte[3 * BoundedImage.MaxBytes], "application/octet-stream");
            await Query("index.upsert", "{}"u8.ToArray(), "application/json", true);
            await Query("test.materials", "{}"u8.ToArray(), "application/json");
            await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => Query("search.hybrid", "{}"u8.ToArray(), "application/json")));
            await Query("test.duplicate", [], "application/json");
            try { await Query("test.invalid", [], "application/json"); throw new InvalidOperationException("Invalid metadata should fail."); }
            catch (ApiException error) when (error.StatusCode == 502) { }
            using (var cancelled = new CancellationTokenSource(50))
            {
                try { await gateway.RequestAsync(new AiCommand("test.cancel", JsonSerializer.SerializeToElement(new { schemaVersion = 1 }), [], "application/json"), cancelled.Token); throw new InvalidOperationException("Cancellation should interrupt waiter."); }
                catch (OperationCanceledException) { }
            }
            await Task.Delay(300);
            await Query("search.hybrid", [], "application/json");
            Check(imageSeen && batchSeen && indexSeen && materialsSeen && transientQueues.Distinct().Count() == 1,
                "nested material requests finish while the original AI request awaits its own reply, without a deadlock");
            await worker.QueueDeleteAsync(prefix + "-query");
            try { await Query("search.hybrid", [], "application/json"); throw new InvalidOperationException("Unroutable publish should fail."); }
            catch (ApiException error) when (error.StatusCode == 503) { }
            if (errors.TryDequeue(out var failure)) throw failure;
            Console.WriteLine("PASS: real RabbitMQ request/reply, binary raw input, TTL, confirms/mandatory, durable receipts, concurrent requests, cancellation and duplicate/late replies");
        }
        finally { await gateway.StopAsync(default); }

        async Task Query(string kind, byte[] body, string mime, bool persistent = false)
        {
            await using var reply = await gateway.RequestAsync(new AiCommand(kind,
                JsonSerializer.SerializeToElement(new { schemaVersion = 1 }), body, mime, persistent), default);
            Check(reply.Body.AsSpan().SequenceEqual("{\"ok\":true}"u8), "reply matches the live correlation waiter");
            await reply.CompleteAsync();
        }
    }
    static void Check(bool condition, string description)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + description);
    }
}
