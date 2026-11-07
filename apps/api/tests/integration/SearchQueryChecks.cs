using System.Buffers.Binary;
using System.Data.Common;
using System.Net.Http.Headers;
using System.Text.Json;
using Findie.Api.Contracts;
using Findie.Api.Data;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Repositories;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;

static class SearchQueryChecks
{
    static readonly byte[] Output = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j8i0AAAAASUVORK5CYII=");

    public static async Task RunAsync(WebApplicationFactory<FindieDbContext> factory)
    {
        using var scope = factory.Services.CreateScope();
        var setup = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
        var owner = new ApplicationUser { UserName = "batch-owner", DisplayName = "Batch owner" };
        var actor = new ApplicationUser { UserName = "batch-seeker", DisplayName = "Batch seeker" };
        setup.Users.AddRange(owner, actor);
        var points = Enumerable.Range(0, 10).Select(index => new ReceptionPoint
            { Name = $"Batch point {index}", PublicAddress = "Campus", Active = index != 4 }).ToArray();
        setup.ReceptionPoints.AddRange(points);
        setup.PointStaff.AddRange(points.Select((point, index) => new PointStaff
        {
            PointId = point.Id, UserId = actor.Id, CanReceive = index != 2, CanReturn = true,
            RevokedAt = index == 3 ? DateTimeOffset.UtcNow : null
        }));
        var items = Enumerable.Range(0, 30).Select(index => new Item
        {
            PostedBy = index == 21 ? actor.Id : owner.Id,
            Title = $"Batch bottle {index}", PublicDescription = "White bottle", FoundArea = index == 29 ? "Quang Trung" : "Elsewhere",
            FoundTimePrecision = "date", FoundOn = new DateOnly(2026, 1, 1),
            CustodyKind = index < 20 ? "point" : index < 22 ? "external" : "person",
            HolderPointId = index < 20 ? points[index < 10 ? index : 0].Id : null,
            HolderUserId = index >= 22 ? index == 22 ? actor.Id : owner.Id : null,
            ExternalName = index is 20 or 21 ? "Public desk" : null,
            ExternalPublicAddress = index is 20 or 21 ? "Campus" : null,
        }).ToArray();
        foreach (var item in items)
        {
            item.Images.Add(Image(item, 1, approved: true));
            item.VerificationQuestions.Add(new VerificationQuestion { Slot = 1, QuestionText = "Private comparison question" });
        }
        items[29].Images.Add(Image(items[29], 2, approved: true));
        var privateImage = Image(items[0], 2, approved: false);
        items[0].Images.Add(privateImage);
        setup.Items.AddRange(items);
        await setup.SaveChangesAsync();
        foreach (var item in items) item.PublicationState = "published";
        await setup.SaveChangesAsync();

        var counter = new QueryCounter();
        var options = new DbContextOptionsBuilder<FindieDbContext>().UseNpgsql(factory.Services.GetRequiredService<NpgsqlDataSource>())
            .AddInterceptors(counter).Options;
        await using var db = new FindieDbContext(options);
        var repository = new RecoveryRepository(db);
        var ai = new StubAiGateway();
        object[] candidates = [];
        ai.Handler = command =>
        {
            Check(command.Metadata.GetProperty("candidateLimit").GetInt32() == 20, "all search commands request at most twenty candidates");
            return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)),
                JsonSerializer.SerializeToUtf8Bytes(new { candidates })));
        };
        var search = new SearchService(repository, ai, factory.Services.GetRequiredService<IConfiguration>(), new RecoveryWorkflow(repository));
        async Task<SearchResponse> Text(object[] values, string? area = null, DateOnly? from = null)
        {
            candidates = values;
            counter.Commands.Clear();
            var response = await search.TextAsync(actor.Id, new SearchRequest("white bottle", Area: area, From: from), default);
            Check(counter.Commands.Count == (values.Length == 0 ? 0 : 1), "search loads the complete candidate batch in one SQL command");
            Check(counter.Commands.All(command => !command.Contains("verification_questions", StringComparison.OrdinalIgnoreCase)),
                "search does not load verification questions");
            Check(!JsonSerializer.Serialize(response).Contains("PRIVATE_SEARCH_CACHE", StringComparison.Ordinal), "search DTO does not expose internal image caches");
            return response;
        }

        Check((await Text([])).Items.Count == 0, "an empty candidate reply does not query the database");
        Check((await Text([Source(items[0])])).Items.Single().Item.CanDelete, "one Hub candidate needs only one SQL command including permissions");
        var full = await Text(items.Take(19).Append(items[29]).Select(item => Source(item)).ToArray(), "quang trung");
        Check(full.Items.Count == 10 && full.Items[0].Item.Id == items[29].Id,
            "a local candidate at the end of twenty candidates is ranked before the response limit");
        Check(full.Items.Count(hit => hit.Item.Id == items[29].Id) == 1 && full.Items[0].Item.Images.Count == 2,
            "a batch JOIN materializes one item with both approved images without duplicate roots");
        var sameHub = await Text(items.Skip(10).Take(10).Select(item => Source(item)).ToArray());
        Check(sameHub.Items.All(hit => hit.Item.CanDelete), "ten items at the same Hub do not add permission queries");
        var distinctHubs = await Text(items.Take(10).Select(item => Source(item)).ToArray());
        Check(distinctHubs.Items.Select(hit => hit.Item.CanDelete).SequenceEqual(Enumerable.Range(0, 10).Select(index => index is not (2 or 3 or 4))),
            "Hub permissions require receiving rights, an active point and an unrevoked assignment without extra queries");
        Check(distinctHubs.Items[0].Item.Images.Count == 1, "only approved public image metadata enters search responses");
        var personal = await Text(items.Skip(20).Take(4).Select(item => Source(item)).ToArray());
        Check(personal.Items.Select(hit => hit.Item.CanDelete).SequenceEqual([false, true, true, false]),
            "batch loading preserves external-poster and personal-holder management rights");
        var duplicate = await Text(Enumerable.Repeat(Source(items[0]), 20).ToArray());
        Check(duplicate.Items.Count == 1 && !duplicate.Partial, "duplicate candidates are loaded and displayed once without marking the response partial");
        var missing = JsonSerializer.SerializeToElement(Source(items[0])).EnumerateObject().ToDictionary(property => property.Name, property => (object?)property.Value.Clone());
        missing["itemId"] = Guid.NewGuid();
        var removed = await Text([missing, Source(items[0], hash: new string('0', 64)), Source(items[0], image: privateImage)]);
        Check(removed.Items.Count == 0 && removed.Partial, "missing, stale and nonpublic image sources fail closed after batching");
        Check((await Text([Source(items[0])], from: new DateOnly(2026, 1, 2))).Items.Count == 0, "batch rehydration keeps the date filter strict");
        candidates = Enumerable.Repeat(Source(items[0]), 21).ToArray();
        counter.Commands.Clear();
        try
        {
            await search.TextAsync(actor.Id, new SearchRequest("white bottle"), default);
            throw new InvalidOperationException("FAIL: twenty-one candidates should be rejected");
        }
        catch (ApiException error) when (error.StatusCode == 502) { }
        Check(counter.Commands.Count == 0, "oversized AI replies are rejected before any batch SQL");

        candidates = [Source(items[0])];
        counter.Commands.Clear();
        using (var image = new MemoryStream(Output, writable: false))
            Check((await search.ImageAsync(actor.Id, new ImageSearchFilter(), "image/png", image, Output.Length, default)).Items.Count == 1
                && counter.Commands.Count == 1, "single-image search uses the same one-query loader");
        using (var multipart = new MultipartFormDataContent())
        {
            for (var index = 0; index < 3; index++)
            {
                var image = new ByteArrayContent(Output);
                image.Headers.ContentType = new MediaTypeHeaderValue("image/png");
                multipart.Add(image, "images", $"query-{index}.png");
            }
            multipart.Add(new StringContent("white bottle"), "text");
            var source = JsonSerializer.SerializeToElement(Source(items[0]));
            candidates = [new { itemId = items[0].Id, score = 1d / 61, imageScore = 1d / 61, textScore = 0d,
                sources = new[] { source.EnumerateObject().Where(property => property.Name != "itemId")
                    .ToDictionary(property => property.Name, property => property.Value.Clone()) } }];
            counter.Commands.Clear();
            using var body = await multipart.ReadAsStreamAsync();
            Check((await search.ImagesAsync(actor.Id, new ImageSearchFilter(), multipart.Headers.ContentType!.ToString(), body,
                multipart.Headers.ContentLength, default)).Items.Count == 1 && counter.Commands.Count == 1,
                "three images plus description still request twenty candidates and execute one batch query");
        }
        ai.Handler = command => Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)),
            JsonSerializer.SerializeToUtf8Bytes(new { candidates, rankingMethod = "reranker" })));
        var quality = await Text([Quality(items[0], 0.9), Quality(items[1], 0.8)]);
        Check(quality.RankingMethod == "reranker" && quality.Items.Count == 2 && !quality.Partial,
            "Python quality scores and ranking method survive the final business check without padding");
        var extraSource = Quality(items[0], 0.9);
        extraSource["sources"] = new[] { Source(items[0]), Source(items[0], image: privateImage) };
        Check((await Text([extraSource])).Items.Count == 0,
            "single-query quality results validate every material image source, including added provenance");
        try
        {
            await Text([Quality(items[0], 1.1)]);
            throw new InvalidOperationException("FAIL: an invalid relevance score should be rejected");
        }
        catch (ApiException error) when (error.StatusCode == 502) { }
        ai.Handler = command => Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)),
            JsonSerializer.SerializeToUtf8Bytes(new { candidates })));
        await CheckMaterials();
        candidates = [Source(items[0])];
        using var canceled = new CancellationTokenSource();
        canceled.Cancel();
        try
        {
            await search.TextAsync(actor.Id, new SearchRequest("white bottle"), canceled.Token);
            throw new InvalidOperationException("FAIL: a canceled search should not succeed");
        }
        catch (OperationCanceledException) { }
        Console.WriteLine("PASS: search candidate cap, one SQL batch, Hub permissions, ordering, privacy and cancellation");

        Dictionary<string, object?> Quality(Item item, double score)
        {
            var source = JsonSerializer.SerializeToElement(Source(item));
            var value = source.EnumerateObject().ToDictionary(property => property.Name, property => (object?)property.Value.Clone());
            value["relevanceScore"] = score;
            value["imageRelevant"] = false;
            value["textRelevant"] = true;
            return value;
        }

        async Task CheckMaterials()
        {
            var storage = (StubStorage)factory.Services.GetRequiredService<IProcessedStorage>();
            foreach (var item in items)
                foreach (var image in item.Images) storage.Objects[image.ProcessedObject!.Id] = Output.ToArray();
            var provider = new SearchMaterialsService(repository, storage);
            var packets = new List<JsonElement>();
            Task Capture(Guid itemId, byte[] packet, CancellationToken ct)
            {
                var size = BinaryPrimitives.ReadInt32BigEndian(packet);
                using var document = JsonDocument.Parse(packet.AsMemory(4, size));
                var manifest = document.RootElement.Clone();
                Check(manifest.GetProperty("itemId").GetGuid() == itemId, "material packet binds its item ID");
                Check(!document.RootElement.GetRawText().Contains("PRIVATE_SEARCH_CACHE"), "materials never include original embedding or OCR caches");
                if (manifest.GetProperty("status").GetString() == "ready")
                {
                    Check(packet.AsSpan(4 + size).SequenceEqual(Output), "material binary packet contains only approved processed image bytes");
                    Check(manifest.GetProperty("image").GetProperty("sourceSha256").GetString() == RecoveryWorkflow.Hash(Output),
                        "material manifest binds the processed bytes hash");
                }
                else Check(packet.Length == size + 4, "failed material packets contain no image bytes");
                packets.Add(manifest);
                return Task.CompletedTask;
            }
            byte[] Request(params object[] values) => JsonSerializer.SerializeToUtf8Bytes(new { candidates = values });
            object Candidate(Item item, string? hash = null, ItemImage? image = null) => new
                { itemId = item.Id, sources = new[] { Source(item, hash, image) } };
            var materialItems = items.Take(19).Append(items[29]).Select(item => Candidate(item)).ToArray();
            Check(await provider.ProvideAsync(Request(materialItems), Capture, default) == 20
                && packets.Count == 20 && packets.All(packet => packet.GetProperty("status").GetString() == "ready"),
                "Python receives materials for the complete twenty-candidate pool before any UI limit");
            packets.Clear();
            await provider.ProvideAsync(Request(Candidate(items[0], image: privateImage), Candidate(items[1], hash: new string('0', 64))), Capture, default);
            Check(packets.All(packet => packet.GetProperty("status").GetString() == "stale"),
                "unapproved and stale sources are withheld even when their item has another approved image");
            packets.Clear();
            storage.CorruptRead = true;
            try { await provider.ProvideAsync(Request(Candidate(items[0])), Capture, default); }
            finally { storage.CorruptRead = false; }
            Check(packets.Single().GetProperty("status").GetString() == "unavailable", "corrupt stored output requests whole-pool quality fallback");
            packets.Clear();
            storage.OnRead = async () =>
            {
                storage.OnRead = null;
                await setup.Database.ExecuteSqlInterpolatedAsync($"UPDATE items SET publication_state = 'hidden' WHERE id = {items[0].Id}");
            };
            try { await provider.ProvideAsync(Request(Candidate(items[0])), Capture, default); }
            finally
            {
                storage.OnRead = null;
                await setup.Database.ExecuteSqlInterpolatedAsync($"UPDATE items SET publication_state = 'published' WHERE id = {items[0].Id}");
            }
            Check(packets.Single().GetProperty("status").GetString() == "stale", "a source revoked during storage reads is never sent to the model");
            try
            {
                await provider.ProvideAsync(Request(materialItems.Append(Candidate(items[20])).ToArray()), Capture, default);
                throw new InvalidOperationException("FAIL: twenty-one material candidates should be rejected");
            }
            catch (JsonException) { }
        }

        ItemImage Image(Item item, short position, bool approved) => new()
        {
            Item = item, Position = position, ProcessingState = approved ? "ready" : "needs_review", ReviewState = approved ? "approved" : "pending",
            SensitiveRegions = "[]", OriginalEmbedding = "{\"private\":\"PRIVATE_SEARCH_CACHE\"}",
            RedactionModelId = "fixture-redactor", RedactionModelRevision = "fixture-revision", RedactionProfile = "fixture-v1",
            ReviewedBy = approved ? owner.Id : null, ReviewedAt = approved ? DateTimeOffset.UtcNow : null,
            ProcessedObject = new StoredObject
            {
                OwnerUserId = owner.Id, Bucket = "private-test-output", ObjectKey = $"processed/{item.Id}/{Guid.NewGuid():N}",
                ObjectState = "validated", Sha256 = RecoveryWorkflow.Hash(Output), ContentType = "image/png", ByteSize = Output.Length,
                Width = 1, Height = 1, ValidatedAt = DateTimeOffset.UtcNow
            }
        };
    }

    static object Source(Item item, string? hash = null, ItemImage? image = null)
    {
        image ??= item.Images.Single(value => value.Position == 1);
        return new { itemId = item.Id, documentVersion = item.DocumentVersion, sourceId = image.Id, sourceKind = "image",
            sourceVersion = image.ContentVersion, sourceSha256 = hash ?? image.ProcessedObject!.Sha256 };
    }
    static void Check(bool condition, string description)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + description);
    }
    sealed class QueryCounter : DbCommandInterceptor
    {
        public List<string> Commands { get; } = [];
        public override ValueTask<DbDataReader> ReaderExecutedAsync(DbCommand command, CommandExecutedEventData data,
            DbDataReader result, CancellationToken ct = default)
        {
            Commands.Add(command.CommandText);
            return ValueTask.FromResult(result);
        }
    }
}
