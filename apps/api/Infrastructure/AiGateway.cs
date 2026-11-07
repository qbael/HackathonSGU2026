using System.Collections.Concurrent;
using System.Text;
using System.Text.Json;
using Findie.Api.Services;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;

namespace Findie.Api.Infrastructure;

public sealed record AiPart(JsonElement Metadata, byte[] Body, string ContentType, string Kind = "index.source.image");
public sealed record AiCommand(string Kind, JsonElement Metadata, byte[] Body, string ContentType,
    bool Persistent = false, IReadOnlyList<AiPart>? Images = null);

public sealed class AiReply(JsonElement metadata, byte[] body, Func<bool, Task>? complete = null) : IAsyncDisposable
{
    int completed;
    public JsonElement Metadata { get; } = metadata;
    public byte[] Body { get; } = body;
    public Task CompleteAsync(bool committed = true) => Interlocked.Exchange(ref completed, 1) == 0
        ? complete?.Invoke(committed) ?? Task.CompletedTask : Task.CompletedTask;
    public async ValueTask DisposeAsync()
    {
        await CompleteAsync(false);
        Array.Clear(Body);
    }
}

public interface IAiGateway
{
    bool Ready { get; }
    Task<AiReply> RequestAsync(AiCommand command, CancellationToken ct);
}

public sealed class RabbitMqGateway(IConfiguration configuration, ILogger<RabbitMqGateway> logger, IServiceScopeFactory scopes) : BackgroundService, IAiGateway
{
    readonly ConcurrentDictionary<string, TaskCompletionSource<AiReply>> pending = new();
    readonly SemaphoreSlim publisher = new(1, 1);
    readonly SemaphoreSlim capacity = new(32, 32);
    IConnection? connection;
    IChannel? publish;
    string? replyQueue;
    public bool Ready => connection?.IsOpen == true && publish?.IsOpen == true && replyQueue is not null;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var uri = configuration["RabbitMq:Uri"];
        if (string.IsNullOrWhiteSpace(uri)) return;
        var endpoint = new Uri(uri);
        if (endpoint.Scheme is not ("amqp" or "amqps") || endpoint.Scheme == "amqp" && !endpoint.IsLoopback)
            throw new InvalidOperationException("Use AMQPS, or AMQP on loopback for local development.");
        var delay = 1;
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var factory = new ConnectionFactory { Uri = endpoint, RequestedHeartbeat = TimeSpan.FromSeconds(30),
                    RequestedConnectionTimeout = TimeSpan.FromSeconds(5), AutomaticRecoveryEnabled = false, MaxInboundMessageBodySize = BoundedImage.MaxBytes };
                await using var connected = await factory.CreateConnectionAsync(stoppingToken);
                await using var send = await connected.CreateChannelAsync(new CreateChannelOptions(true, true), stoppingToken);
                await using var receive = await connected.CreateChannelAsync(new CreateChannelOptions(false, false, consumerDispatchConcurrency: 8), stoppingToken);
                var queue = await receive.QueueDeclareAsync("", durable: false, exclusive: true, autoDelete: true,
                    arguments: new Dictionary<string, object?> { ["x-message-ttl"] = 60000, ["x-max-length"] = 64,
                        ["x-max-length-bytes"] = 32 * 1024 * 1024 }, cancellationToken: stoppingToken);
                await receive.BasicQosAsync(0, 8, false, stoppingToken);
                var consumer = new AsyncEventingBasicConsumer(receive);
                consumer.ReceivedAsync += async (_, message) =>
                {
                    var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                    var accepted = false;
                    var discard = false;
                    if (message.BasicProperties.CorrelationId is { } correlation && pending.TryGetValue(correlation, out var waiter)
                        && message.BasicProperties.Headers?.TryGetValue("metadata", out var value) == true && value is byte[] header && header.Length <= 16384)
                    {
                        try
                        {
                            using var document = JsonDocument.Parse(header);
                            var metadata = document.RootElement.Clone();
                            var reply = new AiReply(metadata, message.Body.ToArray(), committed =>
                            { completion.TrySetResult(committed); return Task.CompletedTask; });
                            accepted = waiter.TrySetResult(reply);
                            if (!accepted) await reply.DisposeAsync();
                        }
                        catch (JsonException)
                        {
                            discard = message.BasicProperties.Type is "index.upsert" or "index.remove";
                            waiter.TrySetException(new ApiException(502, "Invalid AI response metadata."));
                        }
                    }
                    else if (message.BasicProperties.Type is "index.upsert" or "index.remove")
                    {
                        try
                        {
                            if (message.BasicProperties.Headers?.TryGetValue("metadata", out var receiptValue) != true
                                || receiptValue is not byte[] receiptHeader || receiptHeader.Length > 16384) throw new JsonException();
                            using var metadata = JsonDocument.Parse(receiptHeader);
                            using var scope = scopes.CreateScope();
                            await scope.ServiceProvider.GetRequiredService<IndexReceiptService>().AcceptAsync(metadata.RootElement, stoppingToken);
                        }
                        catch (Exception error) when (!stoppingToken.IsCancellationRequested)
                        { discard = true; logger.LogWarning("Index receipt deferred to dead-letter handling ({ErrorType}).", error.GetType().Name); }
                    }
                    try
                    {
                        var committed = !discard && (!accepted || await completion.Task.WaitAsync(TimeSpan.FromSeconds(60), stoppingToken));
                        if (committed) await receive.BasicAckAsync(message.DeliveryTag, false, stoppingToken);
                        else await receive.BasicNackAsync(message.DeliveryTag, false, false, stoppingToken);
                    }
                    catch (TimeoutException)
                    {
                        if (receive.IsOpen) await receive.BasicNackAsync(message.DeliveryTag, false, false, stoppingToken);
                    }
                    catch (Exception error) when (error is OperationCanceledException or RabbitMQ.Client.Exceptions.RabbitMQClientException) { }
                };
                await receive.BasicConsumeAsync(queue.QueueName, false, consumer, stoppingToken);
                var resultQueue = configuration["RabbitMq:ResultQueue"] ?? "findie.api.results";
                await receive.QueueDeclarePassiveAsync(resultQueue, stoppingToken);
                await receive.BasicConsumeAsync(resultQueue, false, consumer, stoppingToken);
                connection = connected; publish = send; replyQueue = queue.QueueName;
                delay = 1;
                while (connected.IsOpen && send.IsOpen && receive.IsOpen) await Task.Delay(1000, stoppingToken);
            }
            catch (Exception error) when (!stoppingToken.IsCancellationRequested)
            {
                logger.LogWarning("AI broker unavailable ({ErrorType}); retrying connection.", error.GetType().Name);
            }
            finally
            {
                replyQueue = null; publish = null; connection = null;
                foreach (var waiter in pending.Values) waiter.TrySetException(new ApiException(503, "AI broker connection was lost."));
            }
            if (!stoppingToken.IsCancellationRequested)
            {
                await Task.Delay(TimeSpan.FromSeconds(delay) + TimeSpan.FromMilliseconds(Random.Shared.Next(250)), stoppingToken);
                delay = Math.Min(delay * 2, 30);
            }
        }
    }

    public async Task<AiReply> RequestAsync(AiCommand command, CancellationToken ct)
    {
        if (!Ready) throw new ApiException(503, "AI service is unavailable; use GET /api/items for basic filters.");
        if (!await capacity.WaitAsync(0, ct)) throw new ApiException(503, "AI request capacity is exhausted; retry shortly.");
        var correlation = Guid.NewGuid().ToString();
        var waiter = new TaskCompletionSource<AiReply>(TaskCreationOptions.RunContinuationsAsynchronously);
        pending[correlation] = waiter;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var timeoutSeconds = command.Kind == "search.hybrid.images" ? 940
            : command.Kind is "image.embed" or "image.redact" or "search.hybrid.image" ? 300 : 30;
        deadline.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds));
        try
        {
            await publisher.WaitAsync(deadline.Token);
            try
            {
                var channel = publish ?? throw new ApiException(503, "AI broker is unavailable.");
                var route = command.Persistent ? configuration["RabbitMq:IndexQueue"] ?? "findie.ai.commands"
                    : command.Kind == "search.hybrid.images" || command.ContentType.StartsWith("image/") ? configuration["RabbitMq:ImageQueue"] ?? "findie.ai.image"
                    : configuration["RabbitMq:QueryQueue"] ?? "findie.ai.query";
                await Publish(command.Kind, command.Metadata, command.Body, command.ContentType);
                foreach (var image in command.Images ?? [])
                    await Publish(image.Kind, image.Metadata, image.Body, image.ContentType);

                async Task Publish(string kind, JsonElement metadata, byte[] body, string contentType)
                {
                    var header = JsonSerializer.SerializeToUtf8Bytes(metadata);
                    if (header.Length > 16384 || body.Length > (kind == "search.hybrid.images" ? 3 : 1) * BoundedImage.MaxBytes)
                        throw new ApiException(400, "AI message exceeds configured limits.");
                    var properties = new BasicProperties { CorrelationId = correlation,
                        ReplyTo = command.Persistent ? configuration["RabbitMq:ResultQueue"] ?? "findie.api.results" : replyQueue,
                        Type = kind, ContentType = contentType, Persistent = command.Persistent, Expiration = (timeoutSeconds * 1000).ToString(),
                        Headers = new Dictionary<string, object?> { ["metadata"] = header } };
                    await channel.BasicPublishAsync("", route, true, properties, body, deadline.Token);
                }
            }
            finally { publisher.Release(); }
            return await waiter.Task.WaitAsync(deadline.Token);
        }
        catch (Exception error) when (!ct.IsCancellationRequested && error is not ApiException)
        {
            throw new ApiException(503, "AI service did not return a valid result before the deadline.");
        }
        finally
        {
            waiter.TrySetCanceled();
            pending.TryRemove(correlation, out _);
            capacity.Release();
            if (waiter.Task.IsCompletedSuccessfully && deadline.IsCancellationRequested) await waiter.Task.Result.DisposeAsync();
        }
    }
}
