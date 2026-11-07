using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Findie.Api.Data;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

static class ItemDeletionChecks
{
    static int checks;
    public static async Task RunAsync(WebApplicationFactory<FindieDbContext> factory, StubAiGateway ai,
        Func<HttpClient, string, Task> login)
    {
        using var owner = await User("delete-owner");
        using var claimant = await User("delete-claimant");
        using var receiver = await User("delete-receiver");
        using var returner = await User("delete-returner");
        var ownerId = Id(await Get(owner, "/api/users/me"));
        var receiverId = Id(await Get(receiver, "/api/users/me"));
        var returnerId = Id(await Get(returner, "/api/users/me"));
        Guid point;
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var desk = new ReceptionPoint { Name = "Deletion check desk", PublicAddress = "Campus" };
            point = desk.Id;
            db.Add(desk);
            db.PointStaff.AddRange(
                new PointStaff { PointId = point, UserId = receiverId, CanReceive = true },
                new PointStaff { PointId = point, UserId = returnerId, CanReturn = true });
            await db.SaveChangesAsync();
        }

        var draft = await Create(owner, "Deletion draft");
        var draftPath = $"/api/items/{Id(draft)}";
        Check(draft.GetProperty("canDelete").GetBoolean(), "personal custodian can delete a draft");
        using (var anonymous = factory.CreateClient())
            await Send(anonymous, HttpMethod.Delete, draftPath, new { rowVersion = Version(draft) }, 401);
        var csrf = owner.DefaultRequestHeaders.GetValues("X-CSRF-TOKEN").Single();
        owner.DefaultRequestHeaders.Remove("X-CSRF-TOKEN");
        await Send(owner, HttpMethod.Delete, draftPath, new { rowVersion = Version(draft) }, 400);
        owner.DefaultRequestHeaders.Add("X-CSRF-TOKEN", csrf);
        using (var missingKey = new HttpRequestMessage(HttpMethod.Delete, draftPath) { Content = JsonContent.Create(new { rowVersion = Version(draft) }) })
        using (var response = await owner.SendAsync(missingKey))
            Check(response.StatusCode == HttpStatusCode.BadRequest, "delete requires an idempotency key");
        await Send(owner, HttpMethod.Delete, draftPath, new { rowVersion = Version(draft) }, 400, Guid.Empty);
        foreach (var invalid in new object[] { new { }, new { rowVersion = 0 }, new { rowVersion = -1 } })
            await Send(owner, HttpMethod.Delete, draftPath, invalid, 400);
        await Send(claimant, HttpMethod.Delete, draftPath, new { rowVersion = Version(draft) }, 403);
        await Send(owner, HttpMethod.Delete, draftPath, new { rowVersion = Version(draft) + 1 }, 409);
        await Send(owner, HttpMethod.Delete, $"/api/items/{Guid.NewGuid()}", new { rowVersion = 1 }, 404);
        Check(Version(await Get(owner, draftPath)) == Version(draft), "rejected deletions leave the item unchanged");
        var concurrentKey = Guid.NewGuid();
        await Task.WhenAll(Enumerable.Range(0, 2).Select(_ =>
            Send(owner, HttpMethod.Delete, draftPath, new { rowVersion = Version(draft) }, 204, concurrentKey)));
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var deleted = await db.Items.SingleAsync(value => value.Id == Id(draft));
            Check(deleted.Lifecycle == "deleted" && deleted.RowVersion == Version(draft) + 1
                && await db.IndexOutbox.CountAsync(value => value.ItemId == deleted.Id) == 2,
                "concurrent retries commit one deletion and one additional outbox entry");
        }

        var item = await Publish(owner, await Create(owner, "Deletion published"));
        var itemId = Id(item);
        var path = $"/api/items/{itemId}";
        Check(!(await Get(claimant, path)).GetProperty("canDelete").GetBoolean(), "public readers cannot delete");
        foreach (var listScope in new[] { "public", "mine", "managed" })
            Check((await Get(owner, $"/api/items?scope={listScope}&q=Deletion%20published")).GetProperty("items")[0]
                .GetProperty("canDelete").GetBoolean(), "item lists include the viewer's deletion permission");
        var claim = await Send(claimant, HttpMethod.Post, path + "/claims", new { contentVersion = 1 }, 201);
        var claimPath = $"/api/claims/{Id(claim)}";
        await Send(owner, HttpMethod.Post, claimPath + "/decision", new { decision = "approved" }, 200);
        var chatPath = $"/api/conversations/{Id(claim)}";
        var message = await Send(claimant, HttpMethod.Post, chatPath + "/messages",
            new { clientMessageId = Guid.NewGuid(), body = "Retained deletion conversation" }, 200);
        var intake = await Send(owner, HttpMethod.Post, path + "/intake-requests",
            new { targetPointId = point, rowVersion = Version(item) }, 201);
        var intakePath = $"/api/intake-requests/{Id(intake)}";
        var imageId = item.GetProperty("images")[0].GetProperty("id").GetGuid();
        using (var scope = factory.Services.CreateScope())
            await scope.ServiceProvider.GetRequiredService<FindieDbContext>().ItemImages.Where(value => value.Id == imageId)
                .ExecuteUpdateAsync(update => update.SetProperty(value => value.OriginalEmbedding, "{}"));
        var key = Guid.NewGuid();
        await Send(owner, HttpMethod.Delete, path, new { rowVersion = Version(item) }, 204, key);
        await Send(owner, HttpMethod.Delete, path, new { rowVersion = Version(item) }, 204, key);
        await Send(owner, HttpMethod.Delete, path, new { rowVersion = Version(item) + 1 }, 409, key);
        await Send(owner, HttpMethod.Delete, path, new { rowVersion = Version(item) }, 404);
        foreach (var suffix in new[] { "", "/verification-questions", "/custody-events", "/images", $"/images/{imageId}/content" })
            await Send(owner, HttpMethod.Get, path + suffix, null, 404);
        await Send(claimant, HttpMethod.Get, path, null, 404);
        foreach (var listScope in new[] { "public", "mine", "managed" })
            Check((await Get(owner, $"/api/items?scope={listScope}&q=Deletion%20published")).GetProperty("items").GetArrayLength() == 0,
                "deleted items disappear from every item scope");
        await Send(owner, HttpMethod.Put, path, new { rowVersion = Version(item), content = Content("Restore") }, 404);
        await Send(owner, HttpMethod.Put, path + "/publication", new { rowVersion = Version(item), state = "published" }, 404);
        await Send(claimant, HttpMethod.Post, path + "/claims", new { contentVersion = 1 }, 404);
        await Send(owner, HttpMethod.Post, path + "/intake-requests", new { targetPointId = point, rowVersion = Version(item) }, 404);
        await Send(owner, HttpMethod.Post, path + "/return", new { rowVersion = Version(item), confirmedPhysicalHandover = true, claimId = Id(claim) }, 404);
        await Send(owner, HttpMethod.Post, path + $"/images/{imageId}/review", new { contentVersion = 1, decision = "approved" }, 404);
        await Send(owner, HttpMethod.Post, path + $"/images/{imageId}/retire", new { contentVersion = 1 }, 404);
        await Send(owner, HttpMethod.Post, claimPath + "/decision", new { decision = "rejected" }, 404);
        await Send(receiver, HttpMethod.Post, intakePath + "/decision",
            new { decision = "received", rowVersion = Version(item), confirmedPhysicalReceipt = true }, 404);
        Check((await Get(claimant, claimPath)).GetProperty("stale").GetBoolean()
            && (await Get(owner, claimPath)).GetProperty("stale").GetBoolean(), "existing claims remain readable and stale");
        Check((await Get(owner, $"/api/claims?itemId={itemId}")).GetProperty("items")[0].GetProperty("stale").GetBoolean(),
            "claim lists retain stale claims after deletion");
        Check((await Get(owner, intakePath)).GetProperty("stale").GetBoolean()
            && (await Get(receiver, "/api/intake-requests")).GetProperty("items")[0].GetProperty("stale").GetBoolean(),
            "existing intakes remain readable and stale");
        Check(!(await Get(claimant, chatPath)).GetProperty("canSend").GetBoolean()
            && !(await Get(owner, "/api/conversations")).GetProperty("items")[0].GetProperty("canSend").GetBoolean(),
            "conversation detail and list become read-only");
        Check(Id((await Get(owner, chatPath + "/messages")).GetProperty("items")[0]) == Id(message), "conversation messages remain readable");
        await Send(claimant, HttpMethod.Post, chatPath + "/messages", new { clientMessageId = Guid.NewGuid(), body = "After deletion" }, 404);

        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var deleted = await db.Items.Include(value => value.Images).SingleAsync(value => value.Id == itemId);
            Check(deleted.Lifecycle == "deleted" && deleted.RowVersion == Version(item) + 1
                && deleted.DocumentVersion == item.GetProperty("documentVersion").GetInt64() + 1
                && deleted.ContentVersion == 1 && deleted.CustodyVersion == 1, "deletion advances row/document versions without changing content or custody");
            Check(deleted.Images.Count == 1 && deleted.Images.Single().RetiredAt is null
                && await db.StoredObjects.AnyAsync(value => value.Id == deleted.Images.Single().ProcessedObjectId)
                && await db.CustodyEvents.CountAsync(value => value.ItemId == itemId) == 1
                && await db.Claims.AnyAsync(value => value.Id == Id(claim))
                && await db.IntakeRequests.AnyAsync(value => value.Id == Id(intake))
                && await db.Conversations.AnyAsync(value => value.ClaimId == Id(claim))
                && await db.Messages.AnyAsync(value => value.Id == Id(message)), "soft deletion retains images, audit history, claims, intakes and chat");
            Check(deleted.Images.All(value => value.OriginalEmbedding is null), "soft deletion clears private original embeddings");
            var outbox = await db.IndexOutbox.Where(value => value.ItemId == itemId).OrderBy(value => value.DocumentVersion).ToListAsync();
            using var payload = JsonDocument.Parse(outbox.Last().Payload);
            Check(outbox.Count == 3 && outbox.Last().EventKind == "tombstone"
                && outbox.Last().DocumentVersion == deleted.DocumentVersion
                && payload.RootElement.GetProperty("document").ValueKind == JsonValueKind.Null
                && payload.RootElement.GetProperty("sources").GetArrayLength() == 0
                && await db.IdempotencyKeys.CountAsync(value => value.ActorUserId == ownerId && value.IdempotencyKeyValue == key) == 1,
                "deletion and retries produce exactly one terminal search tombstone and replay record");
            var previousHandler = ai.Handler;
            ai.Handler = command => Task.FromResult(new AiReply(JsonSerializer.SerializeToElement(StubAiGateway.ReplyMetadata(command)),
                JsonSerializer.SerializeToUtf8Bytes(new { candidates = new[] { new { itemId, documentVersion = deleted.DocumentVersion,
                    sourceKind = "text", sourceId = itemId, sourceVersion = deleted.ContentVersion,
                    sourceSha256 = RecoveryWorkflow.Hash(deleted.Title + "\n" + deleted.PublicDescription) } } })));
            try
            {
                var search = await Send(claimant, HttpMethod.Post, "/api/search", new { text = "Deletion published" }, 200);
                Check(search.GetProperty("items").GetArrayLength() == 0 && search.GetProperty("partial").GetBoolean(),
                    "AI cannot resurrect deleted items even with matching source and document versions");
            }
            finally { ai.Handler = previousHandler; }
        }

        var external = await Send(owner, HttpMethod.Post, "/api/items", new
        { content = Content("Deletion external"), custody = new { kind = "external", name = "Library", address = "Campus" } }, 201);
        external = await Publish(owner, external);
        external = await Send(owner, HttpMethod.Put, $"/api/items/{Id(external)}/publication", new { rowVersion = Version(external), state = "hidden" }, 200);
        Check(external.GetProperty("canDelete").GetBoolean(), "external author can delete a hidden post");
        await Send(claimant, HttpMethod.Delete, $"/api/items/{Id(external)}", new { rowVersion = Version(external) }, 403);
        await Send(owner, HttpMethod.Delete, $"/api/items/{Id(external)}", new { rowVersion = Version(external) }, 204);

        var transferred = await Create(owner, "Deletion transferred");
        var transferPath = $"/api/items/{Id(transferred)}";
        var transfer = await Send(owner, HttpMethod.Post, transferPath + "/intake-requests", new { targetPointId = point, rowVersion = Version(transferred) }, 201);
        await Send(receiver, HttpMethod.Post, $"/api/intake-requests/{Id(transfer)}/decision",
            new { decision = "received", rowVersion = Version(transferred), confirmedPhysicalReceipt = true }, 200);
        transferred = await Get(receiver, transferPath);
        Check(transferred.GetProperty("canDelete").GetBoolean()
            && !(await Get(owner, transferPath)).GetProperty("canDelete").GetBoolean()
            && !(await Get(returner, transferPath)).GetProperty("canDelete").GetBoolean(), "only receiving staff can delete after point custody transfer");
        Check(!(await Get(returner, "/api/items?scope=managed&q=Deletion%20transferred")).GetProperty("items")[0].GetProperty("canDelete").GetBoolean(),
            "managed list does not grant delete to return-only staff");
        await Send(owner, HttpMethod.Delete, transferPath, new { rowVersion = Version(transferred) }, 403);
        await Send(returner, HttpMethod.Delete, transferPath, new { rowVersion = Version(transferred) }, 403);
        await Send(returner, HttpMethod.Post, transferPath + "/return",
            new { rowVersion = Version(transferred), confirmedPhysicalHandover = true, verificationNote = "Verified at desk" }, 201);
        transferred = await Get(receiver, transferPath);
        Check(transferred.GetProperty("lifecycle").GetString() == "returned" && transferred.GetProperty("canDelete").GetBoolean(),
            "current custodian may delete a returned item");
        await Send(receiver, HttpMethod.Delete, transferPath, new { rowVersion = Version(transferred) }, 204);

        var held = new Item { PostedBy = ownerId, HolderUserId = receiverId, Title = "Deletion different holder", PublicDescription = "Wallet", FoundArea = "Campus" };
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            db.Items.Add(held);
            await db.SaveChangesAsync();
        }
        var heldPath = $"/api/items/{held.Id}";
        Check(!(await Get(owner, heldPath)).GetProperty("canDelete").GetBoolean()
            && (await Get(receiver, heldPath)).GetProperty("canDelete").GetBoolean(), "personal deletion follows the holder rather than the original author");
        await Send(owner, HttpMethod.Delete, heldPath, new { rowVersion = 1 }, 403);
        var races = await Task.WhenAll(Enumerable.Range(0, 2).Select(_ => Raw(receiver, HttpMethod.Delete, heldPath, new { rowVersion = 1 })));
        Check(races.Select(value => value.Status).Order().SequenceEqual(new[] { 204, 404 }), "concurrent distinct delete requests commit only once");
        Console.WriteLine($"PASS: {checks} item deletion checks (current custody permission, CSRF, replay, concurrency, tombstone and retained history)");

        async Task<HttpClient> User(string subject)
        {
            var browser = factory.CreateClient(new WebApplicationFactoryClientOptions
            { AllowAutoRedirect = false, HandleCookies = true, BaseAddress = new Uri("https://localhost") });
            await login(browser, subject);
            browser.DefaultRequestHeaders.Add("X-CSRF-TOKEN", (await Get(browser, "/api/auth/csrf")).GetProperty("token").GetString());
            return browser;
        }
        async Task<JsonElement> Publish(HttpClient browser, JsonElement value)
        {
            await PublicationImageFixture.EnsureAsync(factory, Id(value));
            return await Send(browser, HttpMethod.Put, $"/api/items/{Id(value)}/publication", new { rowVersion = Version(value), state = "published" }, 200);
        }
    }
    static object Content(string title) => new { title, publicDescription = "Black wallet", foundArea = "Campus", foundTimePrecision = "unknown" };
    static Task<JsonElement> Create(HttpClient browser, string title) => Send(browser, HttpMethod.Post, "/api/items", new { content = Content(title), custody = new { kind = "person" } }, 201);
    static Guid Id(JsonElement value) => value.GetProperty("id").GetGuid();
    static long Version(JsonElement value) => value.GetProperty("rowVersion").GetInt64();
    static Task<JsonElement> Get(HttpClient browser, string path) => Send(browser, HttpMethod.Get, path, null, 200);
    static async Task<(int Status, JsonElement Body)> Raw(HttpClient browser, HttpMethod method, string path, object? body, Guid? key = null)
    {
        using var request = new HttpRequestMessage(method, path);
        if (body is not null) request.Content = JsonContent.Create(body);
        if (method != HttpMethod.Get) request.Headers.Add("Idempotency-Key", (key ?? Guid.NewGuid()).ToString());
        using var response = await browser.SendAsync(request);
        var text = await response.Content.ReadAsStringAsync();
        return ((int)response.StatusCode, text.Length == 0 ? default : JsonDocument.Parse(text).RootElement.Clone());
    }
    static async Task<JsonElement> Send(HttpClient browser, HttpMethod method, string path, object? body, int expected, Guid? key = null)
    {
        var response = await Raw(browser, method, path, body, key);
        Check(response.Status == expected, $"{method} {path}: expected {expected}, got {response.Status}: {response.Body}");
        return response.Body;
    }
    static void Check(bool condition, string description)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + description);
        Interlocked.Increment(ref checks);
    }
}
