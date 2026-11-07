using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Findie.Api.Data;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

static class ImageSearchChecks
{
    static int checks;
    const string PrivateOcr = "PRIVATE OCR SAMPLE 0016 - NEVER EXPOSE";
    static readonly byte[] Output = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j8i0AAAAASUVORK5CYII=");
    public static async Task RunAsync(WebApplicationFactory<FindieDbContext> factory, StubAiGateway ai, StubStorage storage,
        Func<HttpClient, string, Task> login)
    {
        foreach (var value in new string?[] { null, "", "0", "-1", "16001", "not-a-number" })
        {
            var configuration = new ConfigurationBuilder().AddInMemoryCollection(
                new Dictionary<string, string?> { ["Ai:EmbeddingDimensions"] = value }).Build();
            try { AiProtocol.EmbeddingDimensions(configuration); throw new InvalidOperationException("Invalid embedding dimensions should fail."); }
            catch (ApiException error) when (error.StatusCode == 503) { Check(true, "invalid embedding dimensions are rejected"); }
        }
        using var owner = await User("image-owner");
        using var seeker = await User("image-seeker");
        var item = await Send(owner, HttpMethod.Post, "/api/items", Create("Image test"), 201);
        var itemId = item.GetProperty("id").GetGuid();
        await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = 1, state = "published" }, 409);
        var imagesPath = $"/api/items/{itemId}/images";
        var original = Encoding.UTF8.GetBytes("PRIVATE ORIGINAL INPUT - MUST NEVER ENTER STORAGE");
        byte[]? lastInput = null;
        var embeddingCompleted = false;
        await Binary(owner, imagesPath, original, "application/octet-stream", 415);
        await Binary(owner, imagesPath, [], "image/png", 400);
        await Binary(owner, imagesPath, new byte[BoundedImage.MaxBytes + 1], "image/png", 413);
        await Binary(seeker, imagesPath, original, "image/png", 403);
        await Binary(owner, imagesPath, original, "image/png", 503);
        Check(storage.Puts == 0, "AI failure never uploads original or output");
        ai.Handler = command =>
        {
            if (command.Kind == "image.embed") return ImageReply(command);
            var metadata = ImageMetadata(command);
            metadata["sha256"] = new string('0', 64);
            return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(metadata), Output.ToArray()));
        };
        await Binary(owner, imagesPath, original, "image/png", 502);
        Check(storage.Puts == 0, "invalid output hash never reaches R2");
        foreach (var field in new[] { "modelId", "modelRevision", "dimensions", "sourceSha256", "vector" })
        {
            ai.Handler = command =>
            {
                var payload = EmbeddingPayload(command, factory.Services.GetRequiredService<IConfiguration>());
                payload[field] = field == "dimensions" ? 1 : field == "vector" ? new double[768] : "wrong";
                return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)), JsonSerializer.SerializeToUtf8Bytes(payload)));
            };
            await Binary(owner, imagesPath, original, "image/png", 502);
        }
        Check(storage.Puts == 0, "invalid original embeddings fail before processed storage writes");
        ai.Handler = ImageReply;
        var uploadKey = Guid.NewGuid();
        var image = await Binary(owner, imagesPath, original, "image/png", 201, uploadKey);
        Check(lastInput?.All(value => value == 0) == true, "raw request buffer is cleared after processing");
        var imageId = image.GetProperty("id").GetGuid();
        using (var scope = factory.Services.CreateScope())
        {
            var cached = await scope.ServiceProvider.GetRequiredService<FindieDbContext>().ItemImages
                .Where(value => value.Id == imageId).Select(value => value.OriginalEmbedding).SingleAsync();
            using var document = JsonDocument.Parse(cached!);
            Check(document.RootElement.GetProperty("sourceSha256").GetString() == RecoveryWorkflow.Hash(original)
                && document.RootElement.GetProperty("vector").GetArrayLength() == 768, "upload persists the validated original vector without original bytes");
            Check(document.RootElement.GetProperty("ocr").GetProperty("text").GetString() == PrivateOcr,
                "upload preserves validated private OCR alongside its original image vector");
            Check(!image.TryGetProperty("originalEmbedding", out _) && !image.GetRawText().Contains(PrivateOcr),
                "private OCR and original embedding are excluded from image responses");
            var legacy = document.RootElement.EnumerateObject().Where(property => property.Name != "ocr")
                .ToDictionary(property => property.Name, property => property.Value.Clone());
            var validated = AiProtocol.Embedding(JsonSerializer.SerializeToElement(legacy), factory.Services.GetRequiredService<IConfiguration>());
            Check(!validated.Contains("\"ocr\""), "legacy visual-only caches remain valid without invented OCR");
            foreach (var field in new[] { "text", "hasUnclearText", "modelId", "modelRevision", "processingProfile", "extra", "missing" })
            {
                var payload = document.RootElement.EnumerateObject().ToDictionary(property => property.Name, property => (object?)property.Value.Clone());
                var ocr = document.RootElement.GetProperty("ocr").EnumerateObject().ToDictionary(property => property.Name, property => (object?)property.Value.Clone());
                if (field == "missing") ocr.Remove("text");
                else ocr[field] = field == "text" ? new string('x', 3001) : "invalid";
                payload["ocr"] = ocr;
                var rejected = false;
                try { AiProtocol.Embedding(JsonSerializer.SerializeToElement(payload), factory.Services.GetRequiredService<IConfiguration>()); }
                catch (Exception error) when (AiProtocol.Malformed(error)) { rejected = true; }
                Check(rejected, "private OCR rejects invalid schema, bounds or model identity");
            }
        }
        var contentPath = $"{imagesPath}/{imageId}/content";
        var reviewPath = $"{imagesPath}/{imageId}/review";
        Check(image.GetProperty("processingState").GetString() == "needs_review", "output is held for human review");
        var calls = ai.Calls;
        var replay = await Binary(owner, imagesPath, original, "image/png", 201, uploadKey);
        Check(replay.GetProperty("id").GetGuid() == imageId && calls == ai.Calls && storage.Puts == 1, "upload replay avoids AI and R2 writes");
        await Binary(owner, imagesPath, original, "image/png", 409);
        await Send(seeker, HttpMethod.Get, imagesPath, null, 403);
        await Send(owner, HttpMethod.Get, imagesPath, null, 200);
        await Send(seeker, HttpMethod.Get, contentPath, null, 404);
        using (var content = await owner.GetAsync(contentPath))
        {
            Check(content.StatusCode == HttpStatusCode.OK && (await content.Content.ReadAsByteArrayAsync()).SequenceEqual(Output), "review preview contains only processed bytes");
            Check(content.Headers.CacheControl?.NoStore == true, "private output responses prohibit caching");
        }
        Check((await Get(owner, $"/api/items/{itemId}")).GetProperty("images").GetArrayLength() == 0, "pending output is excluded from the item DTO");
        await Send(seeker, HttpMethod.Get, $"/api/items/{itemId}", null, 404);
        item = await Get(owner, $"/api/items/{itemId}");
        await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 409);
        await Send(seeker, HttpMethod.Post, reviewPath, new { contentVersion = 1, decision = "approved" }, 403);
        await Send(owner, HttpMethod.Post, reviewPath, new { contentVersion = 2, decision = "approved" }, 409);
        await Send(owner, HttpMethod.Post, reviewPath, new { contentVersion = 1, decision = "approved" }, 200);
        item = await Get(owner, $"/api/items/{itemId}");
        item = await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 200);
        Check((await Get(seeker, $"/api/items/{itemId}")).GetProperty("images").GetArrayLength() == 1, "approved output becomes public");
        using (var content = await seeker.GetAsync(contentPath)) Check(content.IsSuccessStatusCode, "approved public output is readable");
        storage.CorruptRead = true;
        await Send(seeker, HttpMethod.Get, contentPath, null, 503);
        storage.CorruptRead = false;

        var returned = await Send(owner, HttpMethod.Post, "/api/items", new
        { content = Content("Upload replay after return"), custody = new { kind = "external", name = "Library", address = "Campus desk" } }, 201);
        var returnedId = returned.GetProperty("id").GetGuid();
        var returnedImages = $"/api/items/{returnedId}/images";
        var returnedUploadKey = Guid.NewGuid();
        var returnedImage = await Binary(owner, returnedImages, original, "image/png", 201, returnedUploadKey);
        await Send(owner, HttpMethod.Post, $"/api/items/{returnedId}/return", new { rowVersion = 2, confirmedPhysicalHandover = true }, 201);
        var callsAfterReturn = ai.Calls;
        var putsAfterReturn = storage.Puts;
        var returnedReplay = await Binary(owner, returnedImages, original, "image/png", 201, returnedUploadKey);
        Check(returnedReplay.GetProperty("id").GetGuid() == returnedImage.GetProperty("id").GetGuid()
            && ai.Calls == callsAfterReturn && storage.Puts == putsAfterReturn, "upload replay after handover returns the same image without calling AI or R2");
        await Binary(owner, returnedImages + "?position=2", original, "image/png", 409);
        await Send(owner, HttpMethod.Post, $"{returnedImages}/{returnedImage.GetProperty("id").GetGuid()}/retire", new { contentVersion = 1 }, 200);

        var otherItem = await Send(owner, HttpMethod.Post, "/api/items", Create("Other image test"), 201);
        var otherId = otherItem.GetProperty("id").GetGuid();
        await Send(owner, HttpMethod.Post, $"/api/items/{otherId}/images/{imageId}/review", new { contentVersion = 1, decision = "approved" }, 404);
        storage.FailPut = true;
        await Binary(owner, $"/api/items/{otherId}/images", original, "image/png", 503);
        storage.FailPut = false;
        Check((await Get(owner, $"/api/items/{otherId}/images")).GetArrayLength() == 0, "failed R2 upload leaves no attached image");
        var processing = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var resume = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        ai.Handler = async command => {
            if (command.Kind == "image.redact") { processing.SetResult(); await resume.Task; }
            return await ImageReply(command);
        };
        var inFlight = Binary(owner, $"/api/items/{otherId}/images", original, "image/png", 409);
        await processing.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await Send(owner, HttpMethod.Put, $"/api/items/{otherId}", new { rowVersion = 1, content = Content("Edited while processing") }, 200);
        resume.SetResult();
        await inFlight;
        Check((await Get(owner, $"/api/items/{otherId}/images")).GetArrayLength() == 0, "late processing output cannot attach to a changed item");
        ai.Handler = ImageReply;

        var second = await Send(owner, HttpMethod.Post, "/api/items", Create("Second searchable item"), 201);
        await PublicationImageFixture.EnsureAsync(factory, second.GetProperty("id").GetGuid());
        second = await Send(owner, HttpMethod.Put, $"/api/items/{second.GetProperty("id").GetGuid()}/publication", new { rowVersion = 1, state = "published" }, 200);
        var secondId = second.GetProperty("id").GetGuid();
        var firstCandidate = await Candidate(itemId, false);
        var secondCandidate = await Candidate(secondId, false);
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "  " }, 400);
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet", limit = 11 }, 400);
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet", from = "2026-02-01", until = "2026-01-01" }, 400);
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet", from = "0001-01-01" }, 400);
        ai.Handler = _ => throw new ApiException(503, "Worker unavailable.");
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet" }, 503);
        ai.Handler = command => SearchReply(command, [secondCandidate, firstCandidate, secondCandidate]);
        var results = await Send(seeker, HttpMethod.Post, "/api/search", new { text = "ví màu đen", area = "Campus", from = "2026-01-01", until = "2026-01-01" }, 200);
        Check(results.GetProperty("items").GetArrayLength() == 2 && results.GetProperty("items")[0].GetProperty("item").GetProperty("id").GetGuid() == secondId,
            "search rehydrates eligible items, deduplicates and preserves worker ranking");
        await Send(owner, HttpMethod.Put, $"/api/items/{secondId}/publication", new { rowVersion = 2, state = "hidden" }, 200);
        results = await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet" }, 200);
        Check(results.GetProperty("items").GetArrayLength() == 1 && results.GetProperty("partial").GetBoolean(), "hidden and stale candidates are removed at response time");
        results = await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet", area = "Different district" }, 200);
        Check(results.GetProperty("items").GetArrayLength() == 1 && results.GetProperty("filtersRelaxed").GetBoolean(),
            "a wrong area retains matching published items and reports results outside the preferred area");
        ai.Handler = command => SearchReply(command, []);
        results = await Send(seeker, HttpMethod.Post, "/api/search", new { text = "missing" }, 200);
        Check(results.GetProperty("items").GetArrayLength() == 0, "successful empty search differs from unavailable worker");
        ai.Handler = command => {
            var metadata = StubAiGateway.ReplyMetadata(command); metadata["modelRevision"] = "wrong-model";
            return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(metadata), "{\"candidates\":[]}"u8.ToArray()));
        };
        await Send(seeker, HttpMethod.Post, "/api/search", new { text = "wallet" }, 502);
        var imageCandidate = await Candidate(itemId, true);
        using var ocrSeeker = await User("ocr-search-validation");
        ai.Handler = command => SearchReply(command, [imageCandidate]);
        results = await Send(ocrSeeker, HttpMethod.Post, "/api/search", new { text = "0016" }, 200);
        Check(results.GetProperty("items").GetArrayLength() == 1 && !results.GetRawText().Contains(PrivateOcr),
            "text queries accept approved image-backed OCR candidates without exposing private OCR");
        foreach (var field in new[] { "sourceVersion", "sourceSha256" })
        {
            var stale = JsonSerializer.SerializeToElement(imageCandidate).EnumerateObject()
                .ToDictionary(property => property.Name, property => (object?)property.Value.Clone());
            stale[field] = field == "sourceVersion" ? 2 : new string('0', 64);
            ai.Handler = command => SearchReply(command, [stale]);
            results = await Send(ocrSeeker, HttpMethod.Post, "/api/search", new { text = "0016" }, 200);
            Check(results.GetProperty("items").GetArrayLength() == 0 && results.GetProperty("partial").GetBoolean(),
                "text queries reject image-backed OCR with a stale image version or processed hash");
        }
        foreach (var invalidKind in new string?[] { null, "ocr", "unknown" })
        {
            var invalid = JsonSerializer.SerializeToElement(imageCandidate).EnumerateObject()
                .ToDictionary(property => property.Name, property => (object?)property.Value.Clone());
            if (invalidKind is null) invalid.Remove("sourceKind");
            else invalid["sourceKind"] = invalidKind;
            ai.Handler = command => SearchReply(command, [invalid]);
            await Send(ocrSeeker, HttpMethod.Post, "/api/search", new { text = "0016" }, 502);
        }
        ai.Handler = command => SearchReply(command, [firstCandidate]);
        await Binary(ocrSeeker, "/api/search/image", original, "image/png", 502);
        ai.Handler = command => {
            Check(command.Metadata.GetProperty("candidateLimit").GetInt32() == 20, "single-image requests cap candidates at twenty before API ranking");
            Check(command.Kind == "search.hybrid.image" && !command.Persistent && command.Body.SequenceEqual(original), "image query uses transient binary transport");
            var remaining = command.Metadata.GetProperty("deadlineAt").GetDateTimeOffset() - DateTimeOffset.UtcNow;
            Check(remaining.TotalSeconds is > 310 and <= 315, "image queries include fifteen seconds for quality evaluation");
            return SearchReply(command, [imageCandidate]);
        };
        var putCount = storage.Puts;
        results = await Binary(seeker, "/api/search/image", original, "image/png", 200);
        Check(results.GetProperty("items").GetArrayLength() == 1 && storage.Puts == putCount, "image search never writes query images to R2");
        await CheckMultipartSearch();
        var reading = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseRead = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        storage.OnRead = async () => { reading.SetResult(); await releaseRead.Task; };
        var staleRead = Send(seeker, HttpMethod.Get, contentPath, null, 404);
        await reading.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await Send(owner, HttpMethod.Post, reviewPath, new { contentVersion = 1, decision = "rejected" }, 200);
        using (var scope = factory.Services.CreateScope())
            Check(await scope.ServiceProvider.GetRequiredService<FindieDbContext>().ItemImages
                .AnyAsync(value => value.Id == imageId && value.OriginalEmbedding == null), "permanent review rejection clears the original embedding");
        releaseRead.SetResult();
        await staleRead;
        storage.OnRead = null;
        await Send(seeker, HttpMethod.Get, contentPath, null, 404);
        item = await Get(owner, $"/api/items/{itemId}");
        Check(item.GetProperty("publicationState").GetString() == "hidden", "rejecting the last public image hides the item");
        await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 409);
        results = await Binary(seeker, "/api/search/image", original, "image/png", 200);
        Check(results.GetProperty("items").GetArrayLength() == 0, "revoked image review invalidates old search sources");
        ai.Handler = command => SearchReply(command, [imageCandidate]);
        results = await Send(ocrSeeker, HttpMethod.Post, "/api/search", new { text = "0016" }, 200);
        Check(results.GetProperty("items").GetArrayLength() == 0, "text queries cannot rehydrate revoked image-backed OCR candidates");
        await Send(owner, HttpMethod.Post, $"{imagesPath}/{imageId}/retire", new { contentVersion = 1 }, 200);
        using (var scope = factory.Services.CreateScope())
            Check(await scope.ServiceProvider.GetRequiredService<FindieDbContext>().ItemImages
                .AnyAsync(value => value.Id == imageId && value.OriginalEmbedding == null), "retiring an image clears its original embedding");
        await Send(owner, HttpMethod.Get, contentPath, null, 404);
        ai.Handler = ImageReply;
        var replacement = await Binary(owner, imagesPath, original, "image/png", 201);
        var replacementId = replacement.GetProperty("id").GetGuid();
        await Send(owner, HttpMethod.Post, $"{imagesPath}/{replacementId}/review", new { contentVersion = 1, decision = "approved" }, 200);
        item = await Get(owner, $"/api/items/{itemId}");
        Check(item.GetProperty("publicationState").GetString() == "hidden", "approving a replacement does not automatically republish the item");
        item = await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 200);
        await Send(owner, HttpMethod.Post, $"{imagesPath}/{replacementId}/retire", new { contentVersion = 1 }, 200);
        Check((await Get(owner, $"/api/items/{itemId}")).GetProperty("publicationState").GetString() == "hidden", "retiring the last public image hides the item");
        await Send(seeker, HttpMethod.Get, $"/api/items/{itemId}", null, 404);

        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            Check((await db.StoredObjects.ToListAsync()).All(value => value.ObjectKind == "processed" && value.Sha256 != RecoveryWorkflow.Hash(original)), "database contains only processed output metadata");
            Check(storage.Objects.Values.All(value => value.SequenceEqual(Output)), "R2 receives only normalized output");
            Check((await db.IndexOutbox.Select(value => value.Payload).ToListAsync()).All(value => !value.Contains("PRIVATE ORIGINAL")), "raw input never enters outbox");
            Check((await db.IndexOutbox.Select(value => value.Payload).ToListAsync()).All(value => !value.Contains(PrivateOcr)),
                "private OCR never enters the public outbox document");
            await db.StoredObjects.Where(value => value.ObjectState == "reserved").ExecuteUpdateAsync(update => update
                .SetProperty(value => value.ExpiresAt, DateTimeOffset.UtcNow.AddSeconds(-1)));
        }
        var maintenance = new RecoveryMaintenance(factory.Services.GetRequiredService<IServiceScopeFactory>(), ai, storage,
            factory.Services.GetRequiredService<IConfiguration>(), NullLogger<RecoveryMaintenance>.Instance);
        while (await maintenance.CleanupOneAsync(default)) { }
        Check(storage.Objects.Count == 0, "retired and abandoned outputs are cleaned without original payloads");
        await CheckOutbox(maintenance);
        await CheckUploadLimit();
        await CheckLostTimeRanking();
        await CheckSoftAreaAndGroups();
        await CheckOriginalEmbeddingRestoration();
        Console.WriteLine($"PASS: {checks} image/search/outbox checks (output-only storage, review, stale results, bounded retry and cleanup)");

        async Task CheckSoftAreaAndGroups()
        {
            using var poster = await User("soft-area-owner");
            using var browser = await User("soft-area-seeker");
            var remote = await Publish("Remote matching bottle", "Chợ Quán");
            var local = await Publish("Nearby matching bottle", "Đường Quang Trung");
            var weak = await Publish("Nearby weaker match", "Đường Quang Trung");
            var imageOnly = await Publish("Image-only match", "Elsewhere");
            var textOnly = await Publish("Description-only match", "Elsewhere");
            object[] candidates = [
                Fused(0.016, 0.008, remote.Image, remote.Text), Fused(0.0155, 0.008, local.Image, local.Text),
                Fused(0.01, 0.005, weak.Image, weak.Text), Fused(1d / 61, 0, imageOnly.Image),
                Fused(0.016, 0, remote.Image), Fused(0, 0.008, textOnly.Image), Fused(0, 0.007, remote.Text)];
            ai.Handler = command => SearchReply(command, candidates);
            const string query = "/api/search/images?area=quang%20trung";
            var result = await Multipart(browser, query, [original], "white bottle", 200);
            Check(Ids(result).SequenceEqual([local.Id, weak.Id, remote.Id, imageOnly.Id, textOnly.Id]),
                "results put the preferred area first, then combined, image-only and text-only groups, without duplicates");
            Check(result.GetProperty("filtersRelaxed").GetBoolean() && !result.GetProperty("partial").GetBoolean(),
                "out-of-area results are reported and duplicate matches do not make the response partial");
            var limited = await Multipart(browser, query + "&limit=1", [original], "white bottle", 200);
            Check(Ids(limited).SequenceEqual([local.Id]) && !limited.GetProperty("filtersRelaxed").GetBoolean(),
                "area ranking considers later candidates before limiting and flags only displayed out-of-area results");
            ai.Handler = command => SearchReply(command, Enumerable.Repeat(Fused(0.016, 0.008, remote.Image, remote.Text), 15)
                .Append(Fused(0.0155, 0.008, local.Image, local.Text)).ToArray());
            limited = await Multipart(browser, query + "&limit=1", [original], "white bottle", 200);
            Check(Ids(limited).SequenceEqual([local.Id]), "area ordering considers candidates beyond the old fifteen-candidate cutoff");
            ai.Handler = command => SearchReply(command, candidates);
            var unfiltered = await Multipart(browser, "/api/search/images", [original], "white bottle", 200);
            Check(Ids(unfiltered).SequenceEqual([remote.Id, local.Id, weak.Id, imageOnly.Id, textOnly.Id]),
                "without an area preference each group keeps descending relevance scores");
            ai.Handler = command => SearchReply(command, [Fused(0.016, 0.008, remote.Image, remote.Text), Fused(0.01, 0.005, weak.Image, weak.Text)]);
            result = await Multipart(browser, query, [original], "white bottle", 200);
            Check(Ids(result).SequenceEqual([weak.Id, remote.Id]), "the preferred area comes before a higher-scoring out-of-area match");
            result = await Multipart(browser, query + "&from=2026-01-02", [original], "white bottle", 200);
            Check(!Ids(result).Any(), "soft area ranking keeps date filters strict");

            ai.Handler = command => SearchReply(command, [remote.Image, local.Image]);
            result = await Binary(browser, "/api/search/image?area=quang%20trung", original, "image/png", 200);
            Check(Ids(result).SequenceEqual([local.Id, remote.Id]), "single-image search puts the preferred area first while retaining remote matches");
            ai.Handler = command => SearchReply(command, [remote.Text, local.Text]);
            result = await Send(browser, HttpMethod.Post, "/api/search", new { text = "white bottle", area = "quang trung" }, 200);
            Check(Ids(result).SequenceEqual([local.Id, remote.Id]), "text search puts the preferred area first while retaining remote matches");

            ai.Handler = command => SearchReply(command, [Fused(0.016, 0.008, remote.Image, remote.Text),
                Fused(0.016, 0, local.Image), Fused(0, 0.008, weak.Text)]);
            result = await Multipart(browser, "/api/search/images?area=QUANG%20TRUNG", [original], "white bottle", 200);
            Check(Ids(result).SequenceEqual([local.Id, weak.Id, remote.Id]),
                "case-insensitive area priority puts local image-only and text-only matches before remote combined matches");
            limited = await Multipart(browser, query + "&limit=2", [original], "white bottle", 200);
            Check(Ids(limited).SequenceEqual([local.Id, weak.Id]) && !limited.GetProperty("filtersRelaxed").GetBoolean(),
                "the result limit is applied after area and modality grouping");
            result = await Multipart(browser, "/api/search/images?area=unknown", [original], "white bottle", 200);
            Check(Ids(result).SequenceEqual([remote.Id, local.Id, weak.Id]) && result.GetProperty("filtersRelaxed").GetBoolean(),
                "an unmatched area keeps all results in their normal group and relevance order");

            using var validationBrowser = await User("area-ranking-validation");
            foreach (var (field, invalid) in new (string, object?)[] {
                ("imageScore", -0.001), ("imageScore", 1d), ("textScore", -0.001), ("textScore", 0.01),
                ("score", 0.001), ("imageScore", "not-a-score"), ("textScore", null) })
            {
                var candidate = (Dictionary<string, object?>)Fused(0.016, 0.008, remote.Image, remote.Text);
                candidate[field] = invalid;
                ai.Handler = command => SearchReply(command, [candidate]);
                await Multipart(validationBrowser, "/api/search/images", [original], "white bottle", 502);
            }
            var missing = (Dictionary<string, object?>)Fused(0.016, 0.008, remote.Image, remote.Text);
            missing.Remove("imageScore");
            ai.Handler = command => SearchReply(command, [missing]);
            await Multipart(validationBrowser, "/api/search/images", [original], "white bottle", 502);
            ai.Handler = command => SearchReply(command, [Fused(0.016, 0, imageOnly.Image), Fused(0.01, 0.005, remote.Image, remote.Text)]);
            await Multipart(validationBrowser, "/api/search/images", [original], "white bottle", 502);
            ai.Handler = command => SearchReply(command, [Fused(0.016, 0.0000000000001, imageOnly.Image)]);
            await Multipart(validationBrowser, "/api/search/images", [original], null, 502);

            async Task<(Guid Id, object Text, object Image)> Publish(string title, string area)
            {
                var created = await Send(poster, HttpMethod.Post, "/api/items", new {
                    content = new { title, publicDescription = "White bottle", foundArea = area,
                        foundTimePrecision = "date", foundOn = "2026-01-01" }, custody = new { kind = "person" } }, 201);
                var id = created.GetProperty("id").GetGuid();
                await PublicationImageFixture.EnsureAsync(factory, id);
                await Send(poster, HttpMethod.Put, $"/api/items/{id}/publication", new { rowVersion = 1, state = "published" }, 200);
                return (id, await Candidate(id, false), await Candidate(id, true));
            }
            static IEnumerable<Guid> Ids(JsonElement response) => response.GetProperty("items").EnumerateArray()
                .Select(hit => hit.GetProperty("item").GetProperty("id").GetGuid());
        }

        async Task CheckOriginalEmbeddingRestoration()
        {
            using var browser = await User("original-vector-owner");
            var created = await Send(browser, HttpMethod.Post, "/api/items", Create("Original vector restore"), 201);
            var id = created.GetProperty("id").GetGuid();
            await PublicationImageFixture.EnsureAsync(factory, id);
            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var originalItem = await db.Items.AsNoTracking().Include(value => value.Images).ThenInclude(value => value.ProcessedObject).SingleAsync(value => value.Id == id);
            var image = originalItem.Images.Single();
            var service = scope.ServiceProvider.GetRequiredService<IImageService>();
            var config = factory.Services.GetRequiredService<IConfiguration>();
            var sourceHash = RecoveryWorkflow.Hash("native original image source");
            var vector = new double[AiProtocol.EmbeddingDimensions(config)]; vector[0] = 1;
            var payload = new Dictionary<string, object?> { ["modelId"] = AiProtocol.Setting(config, "EmbeddingModelId"),
                ["modelRevision"] = AiProtocol.Setting(config, "EmbeddingRevision"), ["dimensions"] = vector.Length,
                ["sourceSha256"] = sourceHash, ["vector"] = vector };
            var key = Guid.NewGuid();
            async Task Reject(Guid actor, long version, string hash, JsonElement data, int status)
            {
                try
                {
                    await service.RestoreOriginalEmbeddingAsync(actor, Guid.NewGuid(), id, image.Id, version, hash, sourceHash, data, default);
                    throw new InvalidOperationException("Original embedding restoration should have been rejected.");
                }
                catch (ApiException error) when (error.StatusCode == status) { Check(true, "original vector restoration rejects unauthorized or stale input"); }
            }
            var valid = JsonSerializer.SerializeToElement(payload);
            await Reject(Guid.NewGuid(), 1, image.ProcessedObject!.Sha256!, valid, 403);
            await Reject(originalItem.PostedBy, 2, image.ProcessedObject.Sha256!, valid, 409);
            await Reject(originalItem.PostedBy, 1, new string('f', 64), valid, 409);
            var wrong = new Dictionary<string, object?>(payload) { ["sourceSha256"] = new string('e', 64) };
            await Reject(originalItem.PostedBy, 1, image.ProcessedObject.Sha256!, JsonSerializer.SerializeToElement(wrong), 400);
            wrong = new Dictionary<string, object?>(payload) { ["ocr"] = new { text = PrivateOcr } };
            await Reject(originalItem.PostedBy, 1, image.ProcessedObject.Sha256!, JsonSerializer.SerializeToElement(wrong), 400);
            var puts = storage.Puts;
            await service.RestoreOriginalEmbeddingAsync(originalItem.PostedBy, key, id, image.Id, 1, image.ProcessedObject.Sha256!, sourceHash, valid, default);
            var after = await db.Items.AsNoTracking().Include(value => value.Images).SingleAsync(value => value.Id == id);
            Check(after.DocumentVersion == originalItem.DocumentVersion + 1 && after.ContentVersion == originalItem.ContentVersion
                && after.CustodyVersion == originalItem.CustodyVersion && after.PublicationState == originalItem.PublicationState,
                "restoring a native vector reindexes without changing display content, custody or publication");
            using var stored = JsonDocument.Parse(after.Images.Single().OriginalEmbedding!);
            Check(stored.RootElement.GetProperty("sourceSha256").GetString() == sourceHash && !stored.RootElement.TryGetProperty("ocr", out _)
                && after.Images.Single().ContentVersion == 1 && storage.Puts == puts,
                "native source vector changes without storing original bytes or replacing the processed image");
            await service.RestoreOriginalEmbeddingAsync(originalItem.PostedBy, key, id, image.Id, 1, image.ProcessedObject.Sha256!, sourceHash, valid, default);
            Check((await db.Items.AsNoTracking().SingleAsync(value => value.Id == id)).DocumentVersion == after.DocumentVersion,
                "native-vector restoration replay does not enqueue another version");
            var priorHandler = ai.Handler;
            ai.Handler = command =>
            {
                Check(command.Kind == "image.redact" && command.Body.SequenceEqual(Output),
                    "verified native vector reuse sends only the processed display input for redaction");
                return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(ImageMetadata(command)), Output.ToArray()));
            };
            await using var processedInput = new MemoryStream(Output, writable: false);
            var reused = await service.UploadAsync(originalItem.PostedBy, Guid.NewGuid(), id, 2, "image/png", processedInput,
                Output.Length, default, omitOcr: true, reviewedRegions: JsonSerializer.SerializeToElement(Array.Empty<object>()),
                originalEmbedding: (valid, sourceHash));
            var reusedCache = await db.ItemImages.AsNoTracking().Where(value => value.Id == reused.Id).Select(value => value.OriginalEmbedding).SingleAsync();
            using var reusedData = JsonDocument.Parse(reusedCache!);
            Check(reusedData.RootElement.GetProperty("sourceSha256").GetString() == sourceHash && storage.Puts == puts + 1,
                "reviewed display replacement reuses the verified native source vector and stores only processed image bytes");
            ai.Handler = priorHandler;
            await service.RetireAsync(originalItem.PostedBy, Guid.NewGuid(), id, image.Id, new Findie.Api.Contracts.RetireImageRequest(1), default);
            await Reject(originalItem.PostedBy, 1, image.ProcessedObject.Sha256!, valid, 409);
        }

        async Task CheckLostTimeRanking()
        {
            using var browser = await User("lost-time-seeker");
            const string text = "wallet";
            const string lostAt = "2026-01-02T09:00:00+07:00";
            var later = await Publish("Found a week later", "exact", "2026-01-09T09:00:00+07:00");
            var overlap = await Publish("Found around the time of loss", "range", "2026-01-02T08:55:00+07:00", "2026-01-02T09:10:00+07:00");
            var near = await Publish("Found five minutes later", "exact", "2026-01-02T09:05:00+07:00");
            var before = await Publish("Found one minute before", "exact", "2026-01-02T08:59:00+07:00");
            var unknown = await Publish("Found at an unknown time", "unknown");
            ai.Handler = command => command.Kind switch
            {
                "search.hybrid.image" => SearchReply(command, [later.Image, overlap.Image, near.Image, before.Image, unknown.Image]),
                "search.hybrid.images" => SearchReply(command, [
                    Fused(1d / 61, 0.5 / 61, later.Image, later.Text), Fused(1d / 62, 0.5 / 62, overlap.Image, overlap.Text),
                    Fused(1d / 63, 0.5 / 63, near.Image, near.Text), Fused(1d / 64, 0.5 / 64, before.Image, before.Text),
                    Fused(1d / 65, 0.5 / 65, unknown.Image, unknown.Text)]),
                _ => SearchReply(command, [later.Text, overlap.Text, near.Text, before.Text, unknown.Text])
            };

            var baseline = await Send(browser, HttpMethod.Post, "/api/search", new { text }, 200);
            Check(Ids(baseline).SequenceEqual([later.Id, overlap.Id, near.Id, before.Id, unknown.Id]),
                "omitting loss time preserves worker ranking");
            var ranked = await Send(browser, HttpMethod.Post, "/api/search", new { text, lostAt }, 200);
            Check(Ids(ranked).SequenceEqual([near.Id, overlap.Id, later.Id, before.Id, unknown.Id]),
                "loss time favors a nearby later find and an overlapping range while retaining earlier or unknown finds");
            var limited = await Send(browser, HttpMethod.Post, "/api/search", new { text, lostAt, limit = 1 }, 200);
            Check(Ids(limited).SequenceEqual([near.Id]), "loss time adjusts ranking before applying the result limit");
            var filtered = await Send(browser, HttpMethod.Post, "/api/search", new { text, lostAt, from = "2026-01-03" }, 200);
            Check(Ids(filtered).SequenceEqual([later.Id]), "loss time does not override the date filter");

            var query = "?lostAt=" + Uri.EscapeDataString(lostAt);
            var image = await Binary(browser, "/api/search/image" + query, original, "image/png", 200);
            var combined = await Multipart(browser, "/api/search/images" + query, [original], text, 200);
            Check(Ids(image).First() == near.Id && Ids(combined).First() == near.Id,
                "loss time ranks image and combined results as well as text results");
            ai.Handler = command => SearchReply(command, [Fused(0.016, 0.008, later.Image, later.Text), Fused(0.01, 0.005, near.Image, near.Text)]);
            combined = await Multipart(browser, "/api/search/images" + query, [original], text, 200);
            Check(Ids(combined).SequenceEqual([later.Id, near.Id]), "loss time uses Python fusion scores rather than replacing them with reciprocal final ranks");

            var beforeInvalidRequests = ai.Calls;
            await Send(browser, HttpMethod.Post, "/api/search", new { text, lostAt = "invalid" }, 400);
            await Multipart(browser, "/api/search/images?lostAt=2026-01-02T09:00:00", [original], text, 400);
            await Send(browser, HttpMethod.Post, "/api/search", new { text, lostAt = DateTimeOffset.UtcNow.AddDays(1) }, 400);
            Check(ai.Calls == beforeInvalidRequests, "invalid loss time is rejected before contacting AI");

            var dateOnly = await Publish("Found on the same local day", "date", foundOn: "2026-01-02");
            ai.Handler = command => SearchReply(command, [later.Text, dateOnly.Text]);
            var acrossMidnight = await Send(browser, HttpMethod.Post, "/api/search",
                new { text, lostAt = "2026-01-01T23:00:00Z", limit = 1 }, 200);
            Check(Ids(acrossMidnight).SequenceEqual([dateOnly.Id]), "date-only finds use their local day when comparing the loss timestamp");

            async Task<(Guid Id, object Text, object Image)> Publish(string title, string foundTimePrecision,
                string? foundFrom = null, string? foundUntil = null, string? foundOn = null)
            {
                var created = await Send(owner, HttpMethod.Post, "/api/items", new
                {
                    content = new { title, publicDescription = "Wallet", foundArea = "Campus",
                        foundTimePrecision, foundFrom, foundUntil, foundOn, foundTimezone = "Asia/Ho_Chi_Minh" },
                    custody = new { kind = "person" }
                }, 201);
                var id = created.GetProperty("id").GetGuid();
                await PublicationImageFixture.EnsureAsync(factory, id);
                await Send(owner, HttpMethod.Put, $"/api/items/{id}/publication", new { rowVersion = 1, state = "published" }, 200);
                return (id, await Candidate(id, false), await Candidate(id, true));
            }

            static IEnumerable<Guid> Ids(JsonElement response) => response.GetProperty("items").EnumerateArray()
                .Select(hit => hit.GetProperty("item").GetProperty("id").GetGuid());
        }

        async Task CheckUploadLimit()
        {
            using var browser = await User("image-limit-owner");
            var actor = (await Get(browser, "/api/users/me")).GetProperty("id").GetGuid();
            var limitedItem = await Send(browser, HttpMethod.Post, "/api/items", Create("Three image limit"), 201);
            var limitedId = limitedItem.GetProperty("id").GetGuid();
            var path = $"/api/items/{limitedId}/images";
            var firstKey = Guid.NewGuid();
            var uploaded = new List<JsonElement>();
            ai.Handler = command =>
            {
                if (command.Kind == "image.embed")
                    Check(command.Metadata.GetProperty("cacheScope").GetGuid() == actor,
                        "upload image embedding cache is scoped to the authenticated actor");
                return ImageReply(command);
            };
            for (short position = 1; position <= 3; position++)
                uploaded.Add(await Binary(browser, path + $"?position={position}", original, "image/png", 201,
                    position == 1 ? firstKey : null));
            Check(uploaded.Select(value => value.GetProperty("position").GetInt16()).SequenceEqual(new short[] { 1, 2, 3 }),
                "uploads accept and preserve positions one through three");
            var callsBefore = ai.Calls;
            var putsBefore = storage.Puts;
            var legacyKey = Guid.NewGuid();
            await Binary(browser, path + "?position=4", original, "image/png", 400);
            using (var scope = factory.Services.CreateScope())
            {
                using var input = new MemoryStream(original, writable: false);
                try
                {
                    await scope.ServiceProvider.GetRequiredService<IImageService>().UploadAsync(actor, Guid.NewGuid(), limitedId, 4,
                        "image/png", input, original.Length, default);
                    throw new InvalidOperationException("Invalid image position should fail.");
                }
                catch (ApiException error) when (error.StatusCode == 400) { Check(true, "service validates upload positions independently of HTTP binding"); }
                var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
                foreach (var legacy in await db.ItemImages.Where(value => value.ItemId == limitedId && value.Position > 1).ToListAsync())
                    legacy.Position += 2;
                var operation = $"image.upload:{limitedId}";
                db.IdempotencyKeys.Add(new IdempotencyKey { ActorUserId = actor, IdempotencyKeyValue = legacyKey,
                    Operation = operation, ResourceType = "image", ResourceId = uploaded[1].GetProperty("id").GetGuid(), ResponseStatus = 201,
                    RequestSha256 = RecoveryWorkflow.RequestHash(operation,
                        new { position = (short)4, mime = "image/png", sha256 = RecoveryWorkflow.Hash(original), length = original.Length }) });
                await db.SaveChangesAsync();
            }
            var legacyReplay = await Binary(browser, path + "?position=4", original, "image/png", 201, legacyKey);
            Check(legacyReplay.GetProperty("id").GetGuid() == uploaded[1].GetProperty("id").GetGuid()
                && legacyReplay.GetProperty("position").GetInt16() == 4 && ai.Calls == callsBefore && storage.Puts == putsBefore,
                "historical upload key at position four replays over HTTP without new AI or storage writes");
            await Binary(browser, path + "?position=4", original, "image/png", 400);
            await Binary(browser, path + "?position=2", original, "image/png", 409);
            var replay = await Binary(browser, path, original, "image/png", 201, firstKey);
            Check(replay.GetProperty("id").GetGuid() == uploaded[0].GetProperty("id").GetGuid()
                && ai.Calls == callsBefore && storage.Puts == putsBefore,
                "fourth uploads and legacy capacity are rejected before AI/storage while replay at capacity succeeds");
            await Send(browser, HttpMethod.Post, $"{path}/{uploaded[1].GetProperty("id").GetGuid()}/retire", new { contentVersion = 1 }, 200);
            await Binary(browser, path + "?position=2", original, "image/png", 201);
            using (var scope = factory.Services.CreateScope())
            {
                var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
                Check(await db.ItemImages.CountAsync(value => value.ItemId == limitedId && value.RetiredAt == null) == 3
                    && await db.ItemImages.AnyAsync(value => value.ItemId == limitedId && value.Position == 5 && value.RetiredAt == null),
                    "retiring one legacy image permits replacement without removing another legacy image or exceeding three active images");
            }
            var textOnly = await Send(browser, HttpMethod.Post, "/api/items", Create("Text-only upload"), 201);
            ai.Handler = command => command.Kind == "image.embed"
                ? Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)), "null"u8.ToArray()))
                : ImageReply(command);
            var textOnlyImage = await Binary(browser, $"/api/items/{textOnly.GetProperty("id").GetGuid()}/images", original, "image/png", 201);
            using (var scope = factory.Services.CreateScope())
                Check(await scope.ServiceProvider.GetRequiredService<FindieDbContext>().ItemImages.AnyAsync(value =>
                    value.Id == textOnlyImage.GetProperty("id").GetGuid() && value.OriginalEmbedding == null),
                    "explicit disabled image embedding permits text-only upload without a cached vector");
        }
        async Task CheckMultipartSearch()
        {
            using var validation = await User("multipart-validation");
            var inputs = new[] { original, original.Concat(new byte[] { 1 }).ToArray(), original.Concat(new byte[] { 2 }).ToArray() };
            var callsBeforeValidation = ai.Calls;
            var csrf = validation.DefaultRequestHeaders.GetValues("X-CSRF-TOKEN").Single();
            validation.DefaultRequestHeaders.Remove("X-CSRF-TOKEN");
            await Multipart(validation, "/api/search/images", [new byte[100000]], null, 400);
            validation.DefaultRequestHeaders.Add("X-CSRF-TOKEN", csrf);
            await Multipart(validation, "/api/search/images", [], null, 400);
            await Multipart(validation, "/api/search/images", [original, original, original, original], null, 400);
            await Multipart(validation, "/api/search/images", [original, original], null, 415, "application/octet-stream");
            await Multipart(validation, "/api/search/images", [original, []], null, 400);
            await Multipart(validation, "/api/search/images", [original, new byte[BoundedImage.MaxBytes + 1]], null, 413);
            await Multipart(validation, "/api/search/images", [original], new string('x', 2001), 400);
            await Multipart(validation, "/api/search/images", [original], new string('x', 8001), 400);
            await Multipart(validation, "/api/search/images?from=2026-02-01&until=2026-01-01", [original], null, 400);
            await Multipart(validation, "/api/search/images?until=9999-12-31", [original], null, 400);
            await Multipart(validation, "/api/search/images?limit=11", [original], null, 400);
            await Binary(validation, "/api/search/images", original, "image/png", 415);
            using (var malformed = new HttpRequestMessage(HttpMethod.Post, "/api/search/images") { Content = new StringContent("bad multipart") })
            {
                malformed.Content.Headers.ContentType = new MediaTypeHeaderValue("multipart/form-data") { Parameters = { new NameValueHeaderValue("boundary", "missing") } };
                await Response(validation, malformed, 400);
            }
            Check(ai.Calls == callsBeforeValidation, "all multipart images, text and filters are validated before any AI call");

            using var browser = await User("multipart-seeker");
            var buffers = new List<byte[]>();
            var batchQueries = 0;
            item = await Get(owner, $"/api/items/{secondId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{secondId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 200);
            var secondText = await Candidate(secondId, false);
            var firstText = await Candidate(itemId, false);
            ai.Handler = command =>
            {
                Check(command.Metadata.GetProperty("candidateLimit").GetInt32() == 20, "batch requests cap the complete fused candidate pool at twenty");
                Check(!command.Persistent && command.Metadata.GetProperty("area").GetString() == "Campus"
                    && command.Metadata.GetProperty("from").GetString() == "2026-01-01"
                    && command.Metadata.GetProperty("until").GetString() == "2026-01-01", "batch search receives filters through transient AI transport");
                Check(command.Kind == "search.hybrid.images" && command.ContentType == "application/octet-stream"
                    && command.Body.SequenceEqual(inputs.SelectMany(value => value)), "one binary RPC carries all three images to the Python fusion worker");
                var descriptors = command.Metadata.GetProperty("images").EnumerateArray().ToArray();
                Check(descriptors.Length == 3 && descriptors.Select(value => value.GetProperty("length").GetInt32()).SequenceEqual(inputs.Select(value => value.Length))
                    && descriptors.All(value => value.GetProperty("contentType").GetString() == "image/png")
                    && command.Metadata.GetProperty("text").GetString() == "ví màu đen", "batch metadata preserves exact image boundaries and trimmed description");
                var remaining = command.Metadata.GetProperty("deadlineAt").GetDateTimeOffset() - DateTimeOffset.UtcNow;
                Check(remaining.TotalSeconds is > 950 and <= 955, "Python receives the complete multimodal search and quality deadline");
                buffers.Add(command.Body);
                batchQueries++;
                return SearchReply(command, [Fused(0.035, 0.005, imageCandidate, firstText), Fused(0, 0.005, secondText)]);
            };
            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var objects = await db.StoredObjects.CountAsync();
            var outbox = await db.IndexOutbox.CountAsync();
            var combined = await Multipart(browser, "/api/search/images?area=Campus&from=2026-01-01&until=2026-01-01&limit=2", inputs, "  ví màu đen  ", 200);
            Check(batchQueries == 1 && combined.GetProperty("mode").GetString() == "combined"
                && combined.GetProperty("searchProfileId").GetString() == "multimodal-fusion-v1", "three images plus description return the combined search contract");
            Check(combined.GetProperty("items").GetArrayLength() == 2
                && combined.GetProperty("items")[0].GetProperty("item").GetProperty("id").GetGuid() == itemId
                && combined.GetProperty("items")[1].GetProperty("rank").GetInt32() == 2,
                "API preserves Python fusion ranking and honors result limit");
            Check(buffers.All(value => value.All(part => part == 0)) && storage.Puts == putCount
                && await db.StoredObjects.CountAsync() == objects && await db.IndexOutbox.CountAsync() == outbox,
                "multipart raw image buffers are cleared and query input creates no storage or outbox records");
            ai.Handler = command => SearchReply(command, [Fused(1d / 61, 0, imageCandidate)]);
            var imageOnly = await Multipart(browser, "/api/search/images?limit=1", [original], "  ", 200);
            Check(imageOnly.GetProperty("mode").GetString() == "image" && imageOnly.GetProperty("searchProfileId").GetString() == "image-fusion-v1"
                && imageOnly.GetProperty("items").GetArrayLength() == 1, "optional blank description supports image-only multipart search");
            var filtered = await Multipart(browser, "/api/search/images?area=Other", [original], null, 200);
            Check(filtered.GetProperty("items").GetArrayLength() == 1 && !filtered.GetProperty("partial").GetBoolean()
                && filtered.GetProperty("filtersRelaxed").GetBoolean(), "multipart image search retains results outside the preferred area");
            filtered = await Multipart(browser, "/api/search/images?from=2026-01-02", [original], null, 200);
            Check(filtered.GetProperty("items").GetArrayLength() == 0, "multipart image search rechecks date filters");
            var failedBuffers = new List<byte[]>();
            ai.Handler = command =>
            {
                failedBuffers.Add(command.Body);
                throw new ApiException(503, "Python multimodal search unavailable.");
            };
            await Multipart(browser, "/api/search/images", inputs, "wallet", 503);
            Check(failedBuffers.Count == 1 && failedBuffers.All(value => value.All(part => part == 0)), "upstream failure fails the whole search and clears the dispatched image batch");
            ai.Handler = command => Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)), "{\"candidates\":[{}]}"u8.ToArray()));
            await Multipart(browser, "/api/search/images", [original], null, 502);
            ai.Handler = async command =>
            {
                var live = await Get(owner, $"/api/items/{itemId}");
                await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = live.GetProperty("rowVersion").GetInt64(), state = "hidden" }, 200);
                return await SearchReply(command, [Fused(0.016, 0.008, imageCandidate, firstText)]);
            };
            var stale = await Multipart(browser, "/api/search/images", [original], "wallet", 200);
            Check(stale.GetProperty("items").GetArrayLength() == 0 && stale.GetProperty("partial").GetBoolean(), "API rechecks publication after Python fusion rather than leaking a stale item");
            item = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = item.GetProperty("rowVersion").GetInt64(), state = "published" }, 200);
            imageCandidate = await Candidate(itemId, true);
            firstText = await Candidate(itemId, false);
            using var provenanceBrowser = await User("fusion-provenance-seeker");
            foreach (var field in new[] { "documentVersion", "sourceVersion", "sourceSha256" })
            {
                var invalid = JsonSerializer.SerializeToElement(imageCandidate).EnumerateObject()
                    .ToDictionary(property => property.Name, property => (object?)property.Value.Clone());
                invalid[field] = field == "sourceSha256" ? new string('0', 64)
                    : JsonSerializer.SerializeToElement(imageCandidate).GetProperty(field).GetInt64() + 1;
                ai.Handler = command => SearchReply(command, [Fused(0.016, 0.008, firstText, invalid)]);
                stale = await Multipart(provenanceBrowser, "/api/search/images", [original], "wallet", 200);
                Check(stale.GetProperty("items").GetArrayLength() == 0 && stale.GetProperty("partial").GetBoolean(),
                    "a valid text source cannot keep a fused candidate whose other contributing source is stale");
            }
            foreach (var score in new[] { 0d, -1d, 1d })
            {
                ai.Handler = command => SearchReply(command, [Fused(score, 0, imageCandidate)]);
                await Multipart(provenanceBrowser, "/api/search/images", [original], null, 502);
            }
            foreach (var sourceCount in new[] { 0, 2 })
            {
                var fused = (Dictionary<string, object?>)Fused(1d / 61, 0, imageCandidate);
                fused["sources"] = Enumerable.Repeat(((object[])fused["sources"]!)[0], sourceCount).ToArray();
                ai.Handler = command => SearchReply(command, [fused]);
                await Multipart(provenanceBrowser, "/api/search/images", [original], null, 502);
            }
            var malformedSource = JsonSerializer.SerializeToElement(imageCandidate).EnumerateObject()
                .ToDictionary(property => property.Name, property => (object?)property.Value.Clone());
            malformedSource["sourceKind"] = "unknown";
            ai.Handler = command => SearchReply(command, [Fused(1d / 61, 0, malformedSource)]);
            await Multipart(provenanceBrowser, "/api/search/images", [original], null, 502);
            using var limitBrowser = await User("candidate-limit-seeker");
            ai.Handler = command =>
            {
                Check(command.Metadata.GetProperty("candidateLimit").GetInt32() == 20, "text requests cap candidates at twenty before API ranking");
                return SearchReply(command, Enumerable.Repeat(firstText, 20).ToArray());
            };
            await Send(limitBrowser, HttpMethod.Post, "/api/search", new { text = "wallet" }, 200);
            ai.Handler = command => SearchReply(command, Enumerable.Repeat(firstText, 21).ToArray());
            await Send(limitBrowser, HttpMethod.Post, "/api/search", new { text = "wallet" }, 502);
            ai.Handler = command => SearchReply(command, Enumerable.Repeat(imageCandidate, 21).ToArray());
            await Binary(limitBrowser, "/api/search/image", original, "image/png", 502);
            ai.Handler = command => SearchReply(command, Enumerable.Repeat(Fused(1d / 61, 0, imageCandidate), 21).ToArray());
            await Multipart(limitBrowser, "/api/search/images", [original], null, 502);
            ai.Handler = command => SearchReply(command, [imageCandidate]);
        }
        async Task CheckOutbox(RecoveryMaintenance worker)
        {
            ai.Handler = ImageReply;
            var liveImage = await Binary(owner, imagesPath, original, "image/png", 201);
            await Send(owner, HttpMethod.Post, $"{imagesPath}/{liveImage.GetProperty("id").GetGuid()}/review", new { contentVersion = 1, decision = "approved" }, 200);
            var liveItem = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}/publication", new { rowVersion = liveItem.GetProperty("rowVersion").GetInt64(), state = "published" }, 200);
            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            await db.IndexOutbox.Where(value => value.Status == "pending" || value.Status == "retry").ExecuteUpdateAsync(update => update
                .SetProperty(value => value.Status, "obsolete").SetProperty(value => value.FinishedAt, DateTimeOffset.UtcNow));
            var current = await Get(owner, $"/api/items/{itemId}");
            var originalCache = await db.ItemImages.Where(value => value.Id == liveImage.GetProperty("id").GetGuid())
                .Select(value => value.OriginalEmbedding).SingleAsync();
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = current.GetProperty("rowVersion").GetInt64(),
                content = Content("Outbox checksum", "Edited public description after upload") }, 200);
            Check(await db.ItemImages.AnyAsync(value => value.Id == liveImage.GetProperty("id").GetGuid() && value.OriginalEmbedding == originalCache),
                "editing public description preserves the independent image and OCR cache");
            var jobId = await db.IndexOutbox.Where(value => value.Status == "pending").Select(value => value.Id).SingleAsync();
            ai.Handler = command => {
                Check(command.Persistent && command.Kind == "index.upsert", "index command uses persistent transport");
                Check(command.Metadata.GetProperty("dimensions").GetInt32() == 768, "index dispatch uses configured nondefault embedding dimensions");
                var part = command.Images!.Single();
                using var cached = JsonDocument.Parse(part.Body);
                Check(part.Kind == "index.source.vector" && part.ContentType == "application/json"
                    && RecoveryWorkflow.Hash(part.Body) == part.Metadata.GetProperty("payloadSha256").GetString()
                    && cached.RootElement.GetProperty("sourceSha256").GetString() == RecoveryWorkflow.Hash(original)
                    && cached.RootElement.GetProperty("ocr").GetProperty("text").GetString() == PrivateOcr
                    && part.Metadata.GetProperty("sourceSha256").GetString() == RecoveryWorkflow.Hash(Output),
                    "outbox reuses the original joint vector and private OCR bound to the reviewed processed image");
                using var manifest = JsonDocument.Parse(command.Body);
                Check(manifest.RootElement.GetProperty("document").GetProperty("publicDescription").GetString() == "Edited public description after upload"
                    && !Encoding.UTF8.GetString(command.Body).Contains(PrivateOcr), "current public description stays separate from private image OCR in the manifest");
                Check(RecoveryWorkflow.Hash(RecoveryWorkflow.CanonicalJson(Encoding.UTF8.GetString(command.Body))) == command.Metadata.GetProperty("snapshotSha256").GetString(), "jsonb roundtrip preserves canonical snapshot checksum");
                var metadata = StubAiGateway.ReplyMetadata(command); metadata["committed"] = true;
                return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(metadata), [], async committed => {
                    using var ackScope = factory.Services.CreateScope();
                    if (committed) Check(await ackScope.ServiceProvider.GetRequiredService<FindieDbContext>().IndexOutbox.AnyAsync(value => value.Id == jobId && value.Status == "succeeded"), "index receipt is ACKed only after business commit");
                }));
            };
            storage.OnRead = () => throw new InvalidOperationException("Cached original vector indexing must not read masked image bytes.");
            try { Check(await worker.DispatchOneAsync(default), "outbox dispatched one due job"); }
            finally { storage.OnRead = null; }
            Check(await db.IndexOutbox.AnyAsync(value => value.Id == jobId && value.Status == "succeeded" && value.Attempts == 1), "successful receipt finishes matching lease");
            var configuration = factory.Services.GetRequiredService<IConfiguration>();
            foreach (var key in new[] { "Ai:EmbeddingRevision", "Ai:RedactionRevision" })
            {
                current = await Get(owner, $"/api/items/{itemId}");
                await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = current.GetProperty("rowVersion").GetInt64(), content = Content("Changed image/OCR model") }, 200);
                var mismatchedJob = await db.IndexOutbox.Where(value => value.Status == "pending").Select(value => value.Id).SingleAsync();
                var savedRevision = configuration[key];
                configuration[key] = "new-model-needs-reupload";
                var beforeMismatch = ai.Calls;
                try { await worker.DispatchOneAsync(default); }
                finally { configuration[key] = savedRevision; }
                Check(ai.Calls == beforeMismatch && await db.IndexOutbox.AnyAsync(value => value.Id == mismatchedJob
                    && value.Status == "failed" && value.LastErrorCode == "original_embedding_requires_reupload"),
                    "embedding or OCR model changes require reupload instead of silently substituting masked pixels");
            }
            var liveImageId = liveImage.GetProperty("id").GetGuid();
            var cachedOriginal = await db.ItemImages.Where(value => value.Id == liveImageId).Select(value => value.OriginalEmbedding).SingleAsync();
            await db.ItemImages.Where(value => value.Id == liveImageId).ExecuteUpdateAsync(update => update.SetProperty(value => value.OriginalEmbedding, (string?)null));
            current = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = current.GetProperty("rowVersion").GetInt64(), content = Content("Legacy image reindex") }, 200);
            ai.Handler = command => {
                var part = command.Images!.Single();
                Check(part.Kind == "index.source.image" && part.Body.SequenceEqual(Output), "legacy images without cached original vectors still index masked bytes");
                var metadata = StubAiGateway.ReplyMetadata(command); metadata["committed"] = true;
                return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(metadata), []));
            };
            await worker.DispatchOneAsync(default);
            await db.ItemImages.Where(value => value.Id == liveImageId).ExecuteUpdateAsync(update => update.SetProperty(value => value.OriginalEmbedding, cachedOriginal));
            current = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = current.GetProperty("rowVersion").GetInt64(), content = Content("Retry outbox") }, 200);
            jobId = await db.IndexOutbox.Where(value => value.Status == "pending").Select(value => value.Id).SingleAsync();
            ai.Handler = _ => throw new ApiException(503, "Broker unavailable.");
            for (var attempt = 1; attempt <= 3; attempt++)
            {
                await worker.DispatchOneAsync(default);
                var status = attempt == 3 ? "failed" : "retry";
                Check(await db.IndexOutbox.AnyAsync(value => value.Id == jobId && value.Status == status && value.Attempts == attempt), "outbox retry attempts are bounded and persisted");
                await db.IndexOutbox.Where(value => value.Id == jobId).ExecuteUpdateAsync(update => update.SetProperty(value => value.NextAttemptAt, DateTimeOffset.UtcNow.AddSeconds(-1)));
            }
            Check(!await worker.DispatchOneAsync(default), "exhausted outbox job is not retried forever");
            current = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = current.GetProperty("rowVersion").GetInt64(), content = Content("Late index receipt") }, 200);
            var pendingJob = await db.IndexOutbox.AsNoTracking().SingleAsync(value => value.Status == "pending");
            var lease = Guid.NewGuid();
            await db.IndexOutbox.Where(value => value.Id == pendingJob.Id).ExecuteUpdateAsync(update => update
                .SetProperty(value => value.Status, "running").SetProperty(value => value.Attempts, 1)
                .SetProperty(value => value.LeaseToken, lease).SetProperty(value => value.LeaseUntil, DateTimeOffset.UtcNow.AddSeconds(60)));
            var receipt = new Dictionary<string, object?> { ["schemaVersion"] = 1, ["kind"] = "index.upsert", ["succeeded"] = true,
                ["jobId"] = pendingJob.Id, ["leaseToken"] = Guid.NewGuid(), ["itemId"] = itemId, ["documentVersion"] = pendingJob.DocumentVersion,
                ["snapshotSha256"] = pendingJob.PayloadSha256, ["modelId"] = "Qwen/Qwen3-VL-Embedding-2B", ["modelRevision"] = "integration-embedding-revision",
                ["dimensions"] = 768, ["committed"] = true };
            await Accept();
            Check(await db.IndexOutbox.AnyAsync(value => value.Id == pendingJob.Id && value.Status == "running" && value.LeaseToken == lease), "old receipt cannot finish a newer lease");
            receipt["leaseToken"] = lease;
            receipt["snapshotSha256"] = new string('f', 64);
            try { await Accept(); throw new InvalidOperationException("Malformed index receipt should fail."); }
            catch (ApiException error) when (error.StatusCode == 502) { Check(true, "invalid receipt checksum is rejected"); }
            receipt["snapshotSha256"] = pendingJob.PayloadSha256;
            receipt["dimensions"] = 2048;
            try { await Accept(); throw new InvalidOperationException("Mismatched embedding dimensions should fail."); }
            catch (ApiException error) when (error.StatusCode == 502) { Check(true, "receipt with different embedding dimensions is rejected"); }
            receipt["dimensions"] = 768;
            await Accept();
            await Accept();
            Check(await db.IndexOutbox.AnyAsync(value => value.Id == pendingJob.Id && value.Status == "succeeded" && value.Attempts == 1), "receipt without live waiter commits once, duplicate receipt is harmless");
            current = await Get(owner, $"/api/items/{itemId}");
            await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = current.GetProperty("rowVersion").GetInt64(), content = Content("Becoming stale") }, 200);
            jobId = await db.IndexOutbox.Where(value => value.Status == "pending").Select(value => value.Id).SingleAsync();
            ai.Handler = async command => {
                var live = await Get(owner, $"/api/items/{itemId}");
                await Send(owner, HttpMethod.Put, $"/api/items/{itemId}", new { rowVersion = live.GetProperty("rowVersion").GetInt64(), content = Content("Changed during index processing") }, 200);
                var metadata = StubAiGateway.ReplyMetadata(command); metadata["committed"] = true;
                return new AiReply(JsonSerializer.SerializeToElement(metadata), []);
            };
            await worker.DispatchOneAsync(default);
            Check(await db.IndexOutbox.AnyAsync(value => value.Id == jobId && value.Status == "obsolete"), "receipt is obsolete if the source changed before business commit");

            async Task Accept()
            {
                using var receiptScope = factory.Services.CreateScope();
                await receiptScope.ServiceProvider.GetRequiredService<IndexReceiptService>().AcceptAsync(JsonSerializer.SerializeToElement(receipt), default);
            }
        }
        async Task<object> Candidate(Guid id, bool image)
        {
            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var entity = await db.Items.Include(value => value.Images).ThenInclude(value => value.ProcessedObject).SingleAsync(value => value.Id == id);
            var source = image ? entity.Images.Single(value => value.RetiredAt == null) : null;
            return new { itemId = id, documentVersion = entity.DocumentVersion, sourceKind = image ? "image" : "text", sourceId = source?.Id ?? id,
                sourceVersion = source?.ContentVersion ?? entity.ContentVersion, sourceSha256 = source?.ProcessedObject?.Sha256 ?? RecoveryWorkflow.Hash(entity.Title + "\n" + entity.PublicDescription) };
        }
        async Task<HttpClient> User(string subject)
        {
            var browser = factory.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false, HandleCookies = true, BaseAddress = new Uri("https://localhost") });
            await login(browser, subject);
            browser.DefaultRequestHeaders.Add("X-CSRF-TOKEN", (await Get(browser, "/api/auth/csrf")).GetProperty("token").GetString());
            return browser;
        }
        Task<AiReply> ImageReply(AiCommand command)
        {
            lastInput = command.Body;
            Check(command.Kind is "image.embed" or "image.redact" && !command.Persistent && command.Body.SequenceEqual(original), "original is sent only via transient AI requests");
            if (command.Kind == "image.embed")
            {
                embeddingCompleted = false;
                var embeddingRemaining = command.Metadata.GetProperty("deadlineAt").GetDateTimeOffset() - DateTimeOffset.UtcNow;
                Check(embeddingRemaining.TotalSeconds is > 295 and <= 300, "original image OCR and image embedding get a five-minute deadline");
                return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)),
                    JsonSerializer.SerializeToUtf8Bytes(EmbeddingPayload(command, factory.Services.GetRequiredService<IConfiguration>())), committed => {
                        embeddingCompleted = committed; return Task.CompletedTask;
                    }));
            }
            Check(embeddingCompleted, "original embedding reply is ACKed before waiting for image redaction");
            var remaining = command.Metadata.GetProperty("deadlineAt").GetDateTimeOffset() - DateTimeOffset.UtcNow;
            Check(remaining.TotalSeconds is > 295 and <= 300, "redaction gets a five-minute processing deadline");
            return Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(ImageMetadata(command)), Output.ToArray()));
        }
    }
    static Dictionary<string, object?> EmbeddingPayload(AiCommand command, IConfiguration configuration)
    {
        var metadata = command.Metadata;
        var vector = new double[metadata.GetProperty("dimensions").GetInt32()];
        vector[0] = 1;
        return new Dictionary<string, object?> { ["modelId"] = metadata.GetProperty("modelId").GetString(),
            ["modelRevision"] = metadata.GetProperty("modelRevision").GetString(), ["dimensions"] = vector.Length,
            ["sourceSha256"] = metadata.GetProperty("sourceSha256").GetString(), ["vector"] = vector,
            ["ocr"] = new Dictionary<string, object?> { ["text"] = PrivateOcr, ["hasUnclearText"] = false,
                ["modelId"] = configuration["Ai:RedactionModelId"], ["modelRevision"] = configuration["Ai:RedactionRevision"],
                ["processingProfile"] = "ocr-v1" } };
    }
    static Dictionary<string, object?> ImageMetadata(AiCommand command)
    {
        var metadata = StubAiGateway.ReplyMetadata(command);
        metadata["contentType"] = "image/png"; metadata["sha256"] = RecoveryWorkflow.Hash(Output);
        metadata["width"] = 1; metadata["height"] = 1; metadata["byteSize"] = Output.Length; metadata["sensitiveRegions"] = Array.Empty<object>();
        return metadata;
    }
    static Task<AiReply> SearchReply(AiCommand command, object[] candidates) => Task.FromResult(new AiReply(
        JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)), JsonSerializer.SerializeToUtf8Bytes(new { candidates })));
    static object Fused(double imageScore, double textScore, params object[] sources)
    {
        var values = sources.Select(value => JsonSerializer.SerializeToElement(value)).ToArray();
        return new Dictionary<string, object?> { ["itemId"] = values[0].GetProperty("itemId").GetGuid(), ["score"] = imageScore + textScore,
            ["imageScore"] = imageScore, ["textScore"] = textScore,
            ["sources"] = values.Select(value => (object)value.EnumerateObject().Where(property => property.Name != "itemId")
                .ToDictionary(property => property.Name, property => (object?)property.Value.Clone())).ToArray() };
    }
    static object Content(string title, string publicDescription = "Safe public description") => new { title, publicDescription, foundArea = "Campus", foundTimePrecision = "date", foundOn = "2026-01-01" };
    static object Create(string title) => new { content = Content(title), custody = new { kind = "person" } };
    static Task<JsonElement> Get(HttpClient client, string path) => Send(client, HttpMethod.Get, path, null, 200);
    static async Task<JsonElement> Send(HttpClient client, HttpMethod method, string path, object? body, int expected)
    {
        using var request = new HttpRequestMessage(method, path);
        if (body is not null) request.Content = JsonContent.Create(body);
        if (method != HttpMethod.Get) request.Headers.Add("Idempotency-Key", Guid.NewGuid().ToString());
        return await Response(client, request, expected);
    }
    static async Task<JsonElement> Binary(HttpClient client, string path, byte[] bytes, string mime, int expected, Guid? key = null)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new ByteArrayContent(bytes) };
        request.Content.Headers.ContentType = new MediaTypeHeaderValue(mime);
        request.Headers.Add("Idempotency-Key", (key ?? Guid.NewGuid()).ToString());
        return await Response(client, request, expected);
    }
    static async Task<JsonElement> Multipart(HttpClient client, string path, byte[][] images, string? text, int expected, string mime = "image/png")
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, path) { Content = new MultipartFormDataContent() };
        var form = (MultipartFormDataContent)request.Content;
        foreach (var image in images)
        {
            var content = new ByteArrayContent(image);
            content.Headers.ContentType = new MediaTypeHeaderValue(mime);
            form.Add(content, "images", "query.png");
        }
        if (text is not null) form.Add(new StringContent(text), "text");
        return await Response(client, request, expected);
    }
    static async Task<JsonElement> Response(HttpClient client, HttpRequestMessage request, int expected)
    {
        using var response = await client.SendAsync(request);
        var text = await response.Content.ReadAsStringAsync();
        Check((int)response.StatusCode == expected, $"{request.Method} {request.RequestUri}: expected {expected}, got {(int)response.StatusCode}: {text}");
        return text.Length == 0 ? default : JsonDocument.Parse(text).RootElement.Clone();
    }
    static void Check(bool condition, string description)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + description);
        Interlocked.Increment(ref checks);
    }
}
