using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using Findie.Api.Data;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

static class SavedSearchChecks
{
    static readonly byte[] Image = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j8i0AAAAASUVORK5CYII=");
    static int checks;

    public static async Task RunAsync(WebApplicationFactory<FindieDbContext> factory, StubAiGateway ai, StubStorage storage,
        Func<HttpClient, string, Task> login)
    {
        using var seeker = await User("saved-seeker");
        using var other = await User("saved-other");
        var seekerId = (await Get(seeker, "/api/users/me")).GetProperty("id").GetGuid();
        var otherId = (await Get(other, "/api/users/me")).GetProperty("id").GetGuid();
        var previousHandler = ai.Handler;
        try
        {
            using (var anonymous = factory.CreateClient())
                await Send(anonymous, HttpMethod.Get, "/api/saved-searches", 401);
            var csrf = seeker.DefaultRequestHeaders.GetValues("X-CSRF-TOKEN").Single();
            seeker.DefaultRequestHeaders.Remove("X-CSRF-TOKEN");
            await Save(seeker, "White bottle", 0, 400);
            seeker.DefaultRequestHeaders.Add("X-CSRF-TOKEN", csrf);
            await Save(seeker, null, 0, 400);
            await Save(seeker, "White bottle", 4, 400);
            await Save(seeker, new string('x', 2001), 0, 400);
            await Save(seeker, "White bottle", 0, 400, query: "?from=2026-01-03&until=2026-01-01");
            await Save(seeker, "White bottle", 0, 400, key: Guid.Empty);
            var key = Guid.NewGuid();
            var text = await Save(seeker, "  White bottle  ", 0, 201, key,
                "?area=Campus&from=2026-01-01&lostAt=2026-01-01T09%3A00%3A00%2B07%3A00");
            var textId = text.GetProperty("id").GetGuid();
            var replay = await Save(seeker, "  White bottle  ", 0, 201, key,
                "?area=Campus&from=2026-01-01&lostAt=2026-01-01T09%3A00%3A00%2B07%3A00");
            Check(replay.GetProperty("id").GetGuid() == textId, "saving the same request twice creates one search");
            await Save(seeker, "A different bottle", 0, 409, key);
            Check(text.GetProperty("text").GetString() == "White bottle" && text.GetProperty("imageCount").GetInt32() == 0
                && text.GetProperty("matches").GetArrayLength() == 0, "a trimmed description and filters can be followed without an image");
            Check((await Get(other, "/api/saved-searches")).GetArrayLength() == 0, "saved searches are private to their owner");
            await Send(other, HttpMethod.Delete, $"/api/saved-searches/{textId}", 404);

            var storagePuts = storage.Puts;
            var embedCalls = 0;
            ai.Handler = command =>
            {
                Check(command.Kind == "image.embed" && command.Metadata.GetProperty("omitOcr").GetBoolean(),
                    "saving an image derives only an embedding without OCR");
                Check(command.Metadata.GetProperty("cacheScope").GetGuid() == seekerId, "image embedding cache is account-scoped");
                embedCalls++;
                var vector = new double[command.Metadata.GetProperty("dimensions").GetInt32()];
                vector[0] = 1;
                return Reply(command, new { modelId = command.Metadata.GetProperty("modelId").GetString(),
                    modelRevision = command.Metadata.GetProperty("modelRevision").GetString(), dimensions = vector.Length,
                    sourceSha256 = command.Metadata.GetProperty("sourceSha256").GetString(), vector });
            };
            var imageKey = Guid.NewGuid();
            var combined = await Save(seeker, "Black wallet", 2, 201, imageKey);
            var combinedId = combined.GetProperty("id").GetGuid();
            await Save(seeker, "Black wallet", 2, 201, imageKey);
            Check(embedCalls == 2 && combined.GetProperty("imageCount").GetInt32() == 2 && storage.Puts == storagePuts,
                "image save retries reuse the private derived vectors and never store originals");
            Check(!combined.GetRawText().Contains("vector", StringComparison.OrdinalIgnoreCase)
                && !combined.GetRawText().Contains("sourceSha256", StringComparison.Ordinal), "saved-search DTOs never expose embeddings or image hashes");
            var imageOnly = await Save(seeker, null, 1, 201);
            Check(imageOnly.GetProperty("text").ValueKind == JsonValueKind.Null
                && imageOnly.GetProperty("imageCount").GetInt32() == 1, "image-only searches are supported");
            ai.Handler = _ => throw new ApiException(503, "Simulated image embedding outage.");
            await Save(seeker, "Failed image save", 1, 503);
            Check((await Get(seeker, "/api/saved-searches")).GetArrayLength() == 3,
                "an embedding failure leaves no partial saved search");

            var accepted = await Item(otherId, "At threshold");
            var below = await Item(otherId, "Below threshold");
            var hidden = await Item(otherId, "Hidden match");
            var returned = await Item(otherId, "Returned match");
            var stale = await Item(otherId, "Stale source");
            var own = await Item(seekerId, "Own post");
            using (var scope = factory.Services.CreateScope())
            {
                var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
                await db.Items.Where(value => value.Id == hidden.Id).ExecuteUpdateAsync(update => update.SetProperty(value => value.PublicationState, "hidden"));
                await db.Items.Where(value => value.Id == returned.Id).ExecuteUpdateAsync(update => update.SetProperty(value => value.Lifecycle, "returned"));
            }
            var searchCalls = 0;
            ai.Handler = command =>
            {
                Check(command.Kind == "search.saved", "the scheduled job uses saved vectors rather than raw-image search");
                using var body = JsonDocument.Parse(command.Body);
                Check(body.RootElement.GetProperty("images").GetArrayLength() == 2, "cron receives both stored image embeddings");
                searchCalls++;
                return Reply(command, new { candidates = new[] {
                    Candidate(accepted, .85), Candidate(below, .8499), Candidate(hidden, .99),
                    Candidate(returned, .99), Candidate(stale, .99, stale: true), Candidate(own, .99)
                }.OrderBy(value => JsonSerializer.SerializeToElement(value).GetProperty("itemId").GetGuid().ToString("D"), StringComparer.Ordinal).ToArray(), nextAfter = (Guid?)null });
            };
            await Due(combinedId);
            await Tick();
            var checkedSearch = (await Get(seeker, "/api/saved-searches")).EnumerateArray().Single(value => value.GetProperty("id").GetGuid() == combinedId);
            var matches = checkedSearch.GetProperty("matches");
            Check(matches.GetArrayLength() == 1 && matches[0].GetProperty("itemId").GetGuid() == accepted.Id
                && matches[0].GetProperty("score").GetDouble() == .85, "0.85 is inclusive; weaker, hidden, returned, stale and own posts do not notify");
            Check(checkedSearch.GetProperty("lastCheckedAt").ValueKind == JsonValueKind.String, "successful cron records its check time");
            await Tick();
            Check(searchCalls == 1, "the same search is not rerun before its next scheduled check");
            await Due(combinedId);
            using (var scope = factory.Services.CreateScope())
                await scope.ServiceProvider.GetRequiredService<FindieDbContext>().SavedSearches.Where(value => value.Id == combinedId)
                    .ExecuteUpdateAsync(update => update.SetProperty(value => value.LeaseToken, Guid.NewGuid())
                        .SetProperty(value => value.LeaseUntil, DateTimeOffset.UtcNow.AddMinutes(2)));
            await Tick();
            Check(searchCalls == 1, "an active lease prevents duplicate work by another API instance");
            using (var scope = factory.Services.CreateScope())
                await scope.ServiceProvider.GetRequiredService<FindieDbContext>().SavedSearches.Where(value => value.Id == combinedId)
                    .ExecuteUpdateAsync(update => update.SetProperty(value => value.LeaseUntil, DateTimeOffset.UtcNow.AddMinutes(-1)));
            await Tick();
            Check(searchCalls == 2 && (await Matches(combinedId)).GetArrayLength() == 1,
                "expired worker leases are reclaimed without duplicating search-item notifications");
            await Send(other, HttpMethod.Put, $"/api/saved-searches/{combinedId}/matches/{accepted.Id}/read", 404);
            await Send(seeker, HttpMethod.Put, $"/api/saved-searches/{combinedId}/matches/{accepted.Id}/read", 204);
            Check((await Matches(combinedId))[0].GetProperty("readAt").ValueKind == JsonValueKind.String, "owners can mark notifications read");
            await Due(combinedId);
            await Tick();
            Check((await Matches(combinedId))[0].GetProperty("readAt").ValueKind == JsonValueKind.String, "rechecks preserve notification read state");

            using (var scope = factory.Services.CreateScope())
            {
                var saved = await scope.ServiceProvider.GetRequiredService<FindieDbContext>().SavedSearches.SingleAsync(value => value.Id == combinedId);
                Check(saved.LastCheckedAt is not null && saved.NextCheckAt - saved.LastCheckedAt.Value == TimeSpan.FromHours(1),
                    "a completed scan schedules its next check exactly one hour later");
            }

            var cursor = Guid.Parse("00000000-0000-0000-0000-000000000100");
            DateTimeOffset? previousCheck;
            using (var scope = factory.Services.CreateScope())
                previousCheck = (await scope.ServiceProvider.GetRequiredService<FindieDbContext>().SavedSearches.SingleAsync(value => value.Id == combinedId)).LastCheckedAt;
            ai.Handler = command => Reply(command, new { candidates = Enumerable.Range(1, 100)
                .Select(index => Candidate(accepted, .9, id: Guid.Parse($"00000000-0000-0000-0000-{index:D12}"))).ToArray(), nextAfter = cursor });
            await Due(combinedId);
            await Tick();
            using (var scope = factory.Services.CreateScope())
            {
                var saved = await scope.ServiceProvider.GetRequiredService<FindieDbContext>().SavedSearches.SingleAsync(value => value.Id == combinedId);
                Check(saved.AfterItemId == cursor && saved.LastCheckedAt == previousCheck,
                    "a full page persists its UUID cursor without marking the scan complete");
            }
            ai.Handler = _ => throw new ApiException(503, "Simulated failure between match pages.");
            await Due(combinedId);
            await Tick();
            using (var scope = factory.Services.CreateScope())
                Check((await scope.ServiceProvider.GetRequiredService<FindieDbContext>().SavedSearches.SingleAsync(value => value.Id == combinedId)).AfterItemId == cursor,
                    "a failed continuation preserves the durable match cursor");
            ai.Handler = command =>
            {
                using var body = JsonDocument.Parse(command.Body);
                Check(body.RootElement.GetProperty("afterItemId").GetGuid() == cursor,
                    "a retry resumes after the committed UUID rather than restarting the first page");
                return Reply(command, new { candidates = new[] { Candidate(accepted, .85) }, nextAfter = (Guid?)null });
            };
            await Due(combinedId);
            await Tick();
            using (var scope = factory.Services.CreateScope())
            {
                var saved = await scope.ServiceProvider.GetRequiredService<FindieDbContext>().SavedSearches.SingleAsync(value => value.Id == combinedId);
                Check(saved.AfterItemId is null && saved.LastCheckedAt > previousCheck,
                    "the final page clears the cursor and marks the complete scan successful");
            }

            using (var scope = factory.Services.CreateScope())
                await scope.ServiceProvider.GetRequiredService<FindieDbContext>().Items.Where(value => value.Id == accepted.Id)
                    .ExecuteUpdateAsync(update => update.SetProperty(value => value.PublicationState, "hidden"));
            Check((await Matches(combinedId)).GetArrayLength() == 0, "notifications stop exposing posts as soon as they are hidden");

            DateTimeOffset? lastChecked;
            using (var scope = factory.Services.CreateScope())
                lastChecked = (await scope.ServiceProvider.GetRequiredService<FindieDbContext>().SavedSearches.SingleAsync(value => value.Id == combinedId)).LastCheckedAt;
            ai.Handler = _ => throw new ApiException(503, "Simulated saved-search outage.");
            await Due(combinedId);
            await Tick();
            using (var scope = factory.Services.CreateScope())
            {
                var saved = await scope.ServiceProvider.GetRequiredService<FindieDbContext>().SavedSearches.SingleAsync(value => value.Id == combinedId);
                Check(saved.LastCheckedAt == lastChecked && saved.LeaseToken is null && saved.NextCheckAt > DateTimeOffset.UtcNow,
                    "AI outages preserve last successful check and schedule a durable retry");
            }
            using (var scope = factory.Services.CreateScope())
                await scope.ServiceProvider.GetRequiredService<FindieDbContext>().SavedSearches.Where(value => value.Id == combinedId)
                    .ExecuteUpdateAsync(update => update.SetProperty(value => value.ModelRevision, "retired-revision"));
            await Due(combinedId);
            await Tick();
            Check((await Get(seeker, "/api/saved-searches")).EnumerateArray().Single(value => value.GetProperty("id").GetGuid() == combinedId)
                .GetProperty("needsRefresh").GetBoolean(), "a model revision change requests a fresh image instead of comparing incompatible vectors");

            ai.Handler = command =>
            {
                using var body = JsonDocument.Parse(command.Body);
                Check(command.Kind == "search.saved" && body.RootElement.GetProperty("images").GetArrayLength() == 0
                    && body.RootElement.GetProperty("text").GetString() == "White bottle", "description-only cron uses its saved query without images");
                return Reply(command, new { candidates = Array.Empty<object>(), nextAfter = (Guid?)null });
            };
            await Due(textId);
            await Tick();
            Check((await Get(seeker, "/api/saved-searches")).EnumerateArray().Single(value => value.GetProperty("id").GetGuid() == textId)
                .GetProperty("lastCheckedAt").ValueKind == JsonValueKind.String, "an empty successful search still advances its scheduled check");

            foreach (var saved in (await Get(seeker, "/api/saved-searches")).EnumerateArray())
                await Send(seeker, HttpMethod.Delete, $"/api/saved-searches/{saved.GetProperty("id").GetGuid()}", 204);
            Check((await Get(seeker, "/api/saved-searches")).GetArrayLength() == 0, "stopping tracking removes the saved query and its notifications");
            using (var scope = factory.Services.CreateScope())
            {
                var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
                Check(!await db.SavedSearches.AnyAsync(value => value.UserId == seekerId)
                    && !await db.SavedSearchMatches.AnyAsync(value => value.SavedSearchId == combinedId), "deletion removes private vectors and notification rows");
            }
            Console.WriteLine($"PASS: {checks} saved-search checks (private images, cron threshold, ownership, replay, source validation, retry and notifications)");
        }
        finally { ai.Handler = previousHandler; }

        async Task<HttpClient> User(string subject)
        {
            var browser = factory.CreateClient(new WebApplicationFactoryClientOptions
            { AllowAutoRedirect = false, HandleCookies = true, BaseAddress = new Uri("https://localhost") });
            await login(browser, subject);
            browser.DefaultRequestHeaders.Add("X-CSRF-TOKEN", (await Get(browser, "/api/auth/csrf")).GetProperty("token").GetString());
            return browser;
        }
        async Task<Item> Item(Guid poster, string title)
        {
            var item = new Item { PostedBy = poster, HolderUserId = poster, Title = title,
                PublicDescription = "Distinct black wallet", FoundArea = "Campus" };
            using (var scope = factory.Services.CreateScope())
            {
                var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
                db.Items.Add(item);
                await db.SaveChangesAsync();
            }
            await PublicationImageFixture.EnsureAsync(factory, item.Id);
            using (var scope = factory.Services.CreateScope())
            {
                var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
                await db.Items.Where(value => value.Id == item.Id)
                    .ExecuteUpdateAsync(update => update.SetProperty(value => value.PublicationState, "published"));
                return await db.Items.AsNoTracking().Include(value => value.Images).ThenInclude(value => value.ProcessedObject)
                    .SingleAsync(value => value.Id == item.Id);
            }
        }
        async Task Due(Guid id)
        {
            using var scope = factory.Services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            await db.SavedSearches.ExecuteUpdateAsync(update => update.SetProperty(value => value.NextCheckAt, DateTimeOffset.UtcNow.AddDays(1)));
            await db.SavedSearches.Where(value => value.Id == id).ExecuteUpdateAsync(update => update.SetProperty(value => value.NextCheckAt, DateTimeOffset.UtcNow.AddMinutes(-1)));
        }
        async Task Tick()
        {
            using var scope = factory.Services.CreateScope();
            await scope.ServiceProvider.GetRequiredService<SavedSearchMaintenance>().CheckOneAsync(default);
        }
        async Task<JsonElement> Matches(Guid id) => (await Get(seeker, "/api/saved-searches")).EnumerateArray()
            .Single(value => value.GetProperty("id").GetGuid() == id).GetProperty("matches");
    }

    static object Candidate(Item item, double score, bool stale = false, Guid? id = null)
    {
        var image = item.Images.Single();
        return new { itemId = id ?? item.Id, relevanceScore = score, sources = new[] {
            new { documentVersion = item.DocumentVersion, sourceId = item.Id, sourceVersion = item.ContentVersion,
                sourceSha256 = stale ? new string('0', 64) : RecoveryWorkflow.Hash(item.Title + "\n" + item.PublicDescription), sourceKind = "text" },
            new { documentVersion = item.DocumentVersion, sourceId = image.Id, sourceVersion = image.ContentVersion,
                sourceSha256 = image.ProcessedObject!.Sha256!, sourceKind = "image" }
        } };
    }
    static Task<AiReply> Reply(AiCommand command, object result) => Task.FromResult(new AiReply(
        JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)), JsonSerializer.SerializeToUtf8Bytes(result)));
    static Task<JsonElement> Get(HttpClient browser, string path) => Send(browser, HttpMethod.Get, path, 200);
    static async Task<JsonElement> Save(HttpClient browser, string? text, int imageCount, int expected, Guid? key = null, string query = "")
    {
        using var form = new MultipartFormDataContent();
        if (text is not null) form.Add(new StringContent(text), "text");
        for (var index = 0; index < imageCount; index++)
        {
            var image = new ByteArrayContent(Image);
            image.Headers.ContentType = new MediaTypeHeaderValue("image/png");
            form.Add(image, "images", $"search-{index}.png");
        }
        using var request = new HttpRequestMessage(HttpMethod.Post, "/api/saved-searches" + query) { Content = form };
        request.Headers.Add("Idempotency-Key", (key ?? Guid.NewGuid()).ToString());
        using var response = await browser.SendAsync(request);
        Check((int)response.StatusCode == expected, $"POST saved search expected {expected}, got {(int)response.StatusCode}: {await response.Content.ReadAsStringAsync()}");
        return response.IsSuccessStatusCode ? (await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync())).RootElement.Clone() : default;
    }
    static async Task<JsonElement> Send(HttpClient browser, HttpMethod method, string path, int expected)
    {
        using var request = new HttpRequestMessage(method, path);
        if (method != HttpMethod.Get) request.Headers.Add("Idempotency-Key", Guid.NewGuid().ToString());
        using var response = await browser.SendAsync(request);
        Check((int)response.StatusCode == expected, $"{method} {path} expected {expected}, got {(int)response.StatusCode}: {await response.Content.ReadAsStringAsync()}");
        return response.IsSuccessStatusCode && expected != 204
            ? (await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync())).RootElement.Clone() : default;
    }
    static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + message);
        checks++;
    }
}
