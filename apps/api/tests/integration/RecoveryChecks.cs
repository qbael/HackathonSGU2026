using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Findie.Api.Data;
using Findie.Api.Models;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

static class RecoveryChecks
{
    static int checks;
    public static async Task RunAsync(WebApplicationFactory<FindieDbContext> factory, Func<HttpClient, string, Task> login)
    {
        using var owner = await User("finder");
        using var claimant = await User("seeker");
        using var other = await User("second-seeker");
        using var staff = await User("staff");
        using var outsider = await User("outsider");
        var ownerId = (await Get(owner, "/api/users/me")).GetProperty("id").GetGuid();
        var staffId = (await Get(staff, "/api/users/me")).GetProperty("id").GetGuid();
        Guid point, secondPoint;
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var first = new ReceptionPoint { Name = "API test point", PublicAddress = "Campus desk" };
            var second = new ReceptionPoint { Name = "API second point", PublicAddress = "Second desk" };
            point = first.Id; secondPoint = second.Id;
            db.AddRange(first, second);
            db.PointStaff.Add(new PointStaff { PointId = point, UserId = staffId, CanReceive = true, CanReturn = true });
            await db.SaveChangesAsync();
        }
        using var anonymous = factory.CreateClient();
        foreach (var path in new[] { "/api/items", "/api/claims", "/api/conversations", "/api/intake-requests" })
        {
            await Send(anonymous, HttpMethod.Get, path, null, 401);
            await CheckPage(outsider, path + "?pageSize=1", 1, 1, 0, false);
        }

        var body = CreateBody();
        var key = Guid.NewGuid();
        var item = await Send(owner, HttpMethod.Post, "/api/items", body, 201, key);
        Check(!item.GetProperty("canClaim").GetBoolean(), "draft item cannot be claimed");
        var itemId = Id(item);
        var pathItem = $"/api/items/{itemId}";
        var replay = await Send(owner, HttpMethod.Post, "/api/items", body, 201, key);
        Check(Id(replay) == itemId, "create retry returns the same item");
        await Send(owner, HttpMethod.Post, "/api/items", CreateBody("Different"), 409, key);
        await Send(owner, HttpMethod.Post, "/api/items", body, 400, Guid.Empty);
        using (var missingKey = new HttpRequestMessage(HttpMethod.Post, "/api/items") { Content = JsonContent.Create(body) })
            Check((await owner.SendAsync(missingKey)).StatusCode == HttpStatusCode.BadRequest, "missing idempotency key rejected");
        await Send(owner, HttpMethod.Post, "/api/items", new { content = Content(), custody = new { kind = "person", pointId = point } }, 400);
        await Send(owner, HttpMethod.Post, "/api/items", new { content = Content(), custody = new { kind = "external", name = "Desk" } }, 400);
        await Send(owner, HttpMethod.Post, "/api/items", new { content = Content(), custody = new { kind = "point", pointId = point, confirmedPhysicalReceipt = true } }, 403);
        await Send(owner, HttpMethod.Post, "/api/items", CreateBody("   "), 400);
        await Send(owner, HttpMethod.Post, "/api/items", new
        {
            content = new { title = "Missing description", foundArea = "Campus", foundTimePrecision = "unknown" },
            custody = new { kind = "person" }
        }, 400);
        foreach (var description in new string?[] { null, "", "   " })
            await Send(owner, HttpMethod.Post, "/api/items", new
            {
                content = new { title = "Missing description", publicDescription = description, foundArea = "Campus", foundTimePrecision = "unknown" },
                custody = new { kind = "person" }
            }, 400);
        await Send(owner, HttpMethod.Post, "/api/items", new { content = Content(questions: ["1", "2", "3", "4"]), custody = new { kind = "person" } }, 400);
        await Send(owner, HttpMethod.Post, "/api/items", new { content = Content(questions: [null!]), custody = new { kind = "person" } }, 400);
        foreach (var time in new object[] {
            new { title = "Time", publicDescription = "Time test", foundArea = "Campus", foundTimePrecision = "date", foundOn = "2999-01-01" },
            new { title = "Time", publicDescription = "Time test", foundArea = "Campus", foundTimePrecision = "range", foundFrom = "2026-01-02T00:00:00Z", foundUntil = "2026-01-01T00:00:00Z" },
            new { title = "Time", publicDescription = "Time test", foundArea = "Campus", foundTimePrecision = "unknown", foundTimezone = "Invalid/Zone" }
        }) await Send(owner, HttpMethod.Post, "/api/items", new { content = time, custody = new { kind = "person" } }, 400);
        await Send(outsider, HttpMethod.Get, pathItem, null, 404);
        item = await Publish(owner, item);
        Check(!item.GetProperty("canClaim").GetBoolean()
            && (await Get(claimant, pathItem)).GetProperty("canClaim").GetBoolean(), "claim eligibility is specific to the viewer");
        Check((await Get(claimant, "/api/items")).GetProperty("items")[0].GetProperty("canClaim").GetBoolean()
            && !(await Get(owner, "/api/items")).GetProperty("items")[0].GetProperty("canClaim").GetBoolean(), "item lists preserve viewer claim eligibility");
        Check((await Get(claimant, pathItem)).GetProperty("custody").GetProperty("kind").GetString() == "person", "public person custody");
        var questionSet = await Get(claimant, pathItem + "/verification-questions");
        var contentVersion = questionSet.GetProperty("contentVersion").GetInt64();
        Check(contentVersion == 1 && questionSet.GetProperty("questions").GetArrayLength() == 0, "zero questions include their content version");
        Check((await Get(claimant, "/api/items?q=API%20wallet&area=Campus")).GetProperty("items").GetArrayLength() == 1, "basic text search without image");
        Check((await Get(claimant, "/api/items?q=%25")).GetProperty("items").GetArrayLength() == 0, "LIKE wildcards treated literally");
        await CheckPage(claimant, "/api/items?q=%25&pageSize=1", 1, 1, 0, false);
        await Send(owner, HttpMethod.Get, "/api/items?from=2026-10-02&until=2026-10-01", null, 400);
        await Send(owner, HttpMethod.Get, "/api/items?from=0001-01-01", null, 400);
        await Send(owner, HttpMethod.Get, "/api/items?pageSize=101", null, 400);
        await Send(owner, HttpMethod.Get, "/api/items?scope=everything", null, 400);
        await Send(owner, HttpMethod.Put, pathItem, new { rowVersion = 1, content = Content() }, 409);
        await Send(outsider, HttpMethod.Put, pathItem, new { rowVersion = Version(item), content = Content() }, 403);

        await Send(owner, HttpMethod.Post, pathItem + "/claims", new { contentVersion }, 400);
        await Send(claimant, HttpMethod.Post, pathItem + "/claims", new { }, 400);
        var claimKey = Guid.NewGuid();
        var claim = await Send(claimant, HttpMethod.Post, pathItem + "/claims", new { contentVersion }, 201, claimKey);
        var claimId = Id(claim);
        Check(claim.GetProperty("answers").GetArrayLength() == 0, "claim without questions succeeds");
        Check(Id(await Send(claimant, HttpMethod.Post, pathItem + "/claims", new { contentVersion }, 201, claimKey)) == claimId,
            "claim retry preserves its content version and resource");
        await Send(claimant, HttpMethod.Post, pathItem + "/claims", new { contentVersion }, 409);
        await Send(outsider, HttpMethod.Get, $"/api/claims/{claimId}", null, 404);
        await Send(claimant, HttpMethod.Get, $"/api/conversations/{claimId}", null, 404);
        await Send(outsider, HttpMethod.Post, $"/api/claims/{claimId}/decision", new { decision = "approved" }, 403);
        claim = await Send(owner, HttpMethod.Post, $"/api/claims/{claimId}/decision", new { decision = "approved" }, 200);
        Check(claim.GetProperty("conversationId").GetGuid() == claimId, "approval creates exactly one conversation");
        var secondClaim = await Send(other, HttpMethod.Post, pathItem + "/claims", new { contentVersion }, 201);
        await Send(owner, HttpMethod.Post, $"/api/claims/{Id(secondClaim)}/decision", new { decision = "approved" }, 200);
        Check((await Get(owner, "/api/claims")).GetProperty("items").GetArrayLength() == 2, "multiple approvals are allowed");
        Check((await Get(claimant, "/api/conversations")).GetProperty("items").GetArrayLength() == 1, "conversation list is participant-scoped");
        await CheckPage(owner, $"/api/claims?itemId={itemId}&pageSize=1", 1, 2, 1, true);
        await CheckPage(owner, $"/api/claims?itemId={itemId}&pageSize=1&page=2", 2, 2, 1, false);
        await CheckPage(claimant, "/api/claims?pageSize=1", 1, 1, 1, false);
        await CheckPage(owner, $"/api/claims?itemId={Guid.NewGuid()}&pageSize=1", 1, 1, 0, false);
        await CheckPage(owner, "/api/conversations?pageSize=1", 1, 2, 1, true);
        await CheckPage(owner, "/api/conversations?pageSize=1&page=2", 2, 2, 1, false);
        await CheckPage(claimant, "/api/conversations?pageSize=1", 1, 1, 1, false);
        var messagePath = $"/api/conversations/{claimId}/messages";
        await Send(outsider, HttpMethod.Get, messagePath, null, 404);
        await Send(outsider, HttpMethod.Post, messagePath, new { clientMessageId = Guid.NewGuid(), body = "Intrusion" }, 404);
        await Send(claimant, HttpMethod.Post, messagePath, new { clientMessageId = Guid.Empty, body = "Hello" }, 400);
        await Send(claimant, HttpMethod.Post, messagePath, new { clientMessageId = Guid.NewGuid(), body = "   " }, 400);
        var messageKey = Guid.NewGuid();
        var message = await Send(claimant, HttpMethod.Post, messagePath, new { clientMessageId = messageKey, body = "  Private chat  ", senderUserId = ownerId }, 200);
        var repeated = await Send(claimant, HttpMethod.Post, messagePath, new { clientMessageId = messageKey, body = "Private chat" }, 200);
        Check(Id(repeated) == Id(message) && message.GetProperty("senderUserId").GetGuid() != ownerId, "message replay and sender overposting protection");
        await Send(claimant, HttpMethod.Post, messagePath, new { clientMessageId = messageKey, body = "Changed" }, 409);
        await Task.WhenAll(Enumerable.Range(0, 8).Select(i => Send(owner, HttpMethod.Post, messagePath,
            new { clientMessageId = Guid.NewGuid(), body = "Concurrent " + i }, 200)));
        var allSequences = new List<long>();
        long after = 0;
        do
        {
            var page = await Get(claimant, messagePath + $"?after={after}&limit=3");
            allSequences.AddRange(page.GetProperty("items").EnumerateArray().Select(value => value.GetProperty("sequence").GetInt64()));
            after = page.GetProperty("nextAfter").GetInt64();
            if (!page.GetProperty("hasMore").GetBoolean()) break;
        } while (true);
        Check(allSequences.Count == 9 && allSequences.SequenceEqual(allSequences.Order()) && allSequences.Distinct().Count() == 9, "concurrent messages preserve cursor order without gaps from uncommitted writes");

        var secretItem = await Publish(owner, await Send(owner, HttpMethod.Post, "/api/items", new
        { content = Content("Question item", ["What is inside?", "Optional question"]), custody = new { kind = "person" } }, 201));
        var secretId = Id(secretItem);
        await CheckPage(claimant, "/api/items?pageSize=1", 1, 2, 1, true);
        await CheckPage(claimant, "/api/items?pageSize=1&page=2", 2, 2, 1, false);
        await CheckPage(claimant, "/api/items?pageSize=1&page=3", 3, 2, 0, false);
        await CheckPage(claimant, "/api/items?q=API%20wallet&area=Campus&pageSize=1", 1, 1, 1, false);
        await CheckPage(claimant, "/api/items?scope=mine&pageSize=1", 1, 1, 0, false);
        var secretQuestions = await Get(claimant, $"/api/items/{secretId}/verification-questions");
        var secretContentVersion = secretQuestions.GetProperty("contentVersion").GetInt64();
        await Send(claimant, HttpMethod.Post, $"/api/items/{secretId}/claims", new { contentVersion = secretContentVersion, answers = new[] { new { slot = 3, answerText = "Unknown slot" } } }, 400);
        await Send(claimant, HttpMethod.Post, $"/api/items/{secretId}/claims", new { contentVersion = secretContentVersion, answers = new[] { new { slot = 1, answerText = "a" }, new { slot = 1, answerText = "b" } } }, 400);
        var evidenceKey = Guid.NewGuid();
        var evidenceBody = new { contentVersion = secretContentVersion, answers = new[] { new { slot = 1, answerText = "TOP_SECRET_EVIDENCE" } } };
        var evidence = await Send(claimant, HttpMethod.Post, $"/api/items/{secretId}/claims", evidenceBody, 201, evidenceKey);
        Check(evidence.GetProperty("answers")[1].GetProperty("answerText").ValueKind == JsonValueKind.Null, "optional unanswered question is snapshotted");
        secretItem = await Send(owner, HttpMethod.Put, $"/api/items/{secretId}", new { rowVersion = Version(secretItem), content = Content("Question item", ["Updated question"]) }, 200);
        evidence = await Get(claimant, $"/api/claims/{Id(evidence)}");
        Check(evidence.GetProperty("answers")[0].GetProperty("questionText").GetString() == "What is inside?", "question snapshot remains immutable after editing");
        Check(Id(await Send(claimant, HttpMethod.Post, $"/api/items/{secretId}/claims", evidenceBody, 201, evidenceKey)) == Id(evidence),
            "claim replay remains valid after questions change");
        await Send(other, HttpMethod.Post, $"/api/items/{secretId}/claims", new
        { contentVersion = secretContentVersion, answers = new[] { new { slot = 1, answerText = "Answer to the old question" } } }, 409);
        var refreshedQuestions = await Get(other, $"/api/items/{secretId}/verification-questions");
        Check(refreshedQuestions.GetProperty("contentVersion").GetInt64() > secretContentVersion
            && refreshedQuestions.GetProperty("questions")[0].GetProperty("questionText").GetString() == "Updated question",
            "question refetch returns the replacement text with its new version");
        var currentEvidence = await Send(other, HttpMethod.Post, $"/api/items/{secretId}/claims", new
        { contentVersion = refreshedQuestions.GetProperty("contentVersion").GetInt64(), answers = new[] { new { slot = 1, answerText = "Answer to the updated question" } } }, 201);
        Check(currentEvidence.GetProperty("answers")[0].GetProperty("questionText").GetString() == "Updated question"
            && currentEvidence.GetProperty("answers")[0].GetProperty("answerText").GetString() == "Answer to the updated question",
            "stale submission creates no claim and refetched answers match their question snapshot");
        await Send(owner, HttpMethod.Post, $"/api/claims/{Id(evidence)}/decision", new { decision = "rejected", note = "Private decision" }, 200);
        await Send(claimant, HttpMethod.Get, $"/api/conversations/{Id(evidence)}", null, 404);
        Check(!(await Get(outsider, $"/api/items/{secretId}")).GetRawText().Contains("TOP_SECRET"), "public DTO excludes private evidence");

        var intake = await Send(owner, HttpMethod.Post, pathItem + "/intake-requests", new { targetPointId = point, rowVersion = Version(item) }, 201);
        Check((await Get(owner, pathItem)).GetProperty("custody").GetProperty("kind").GetString() == "person", "pending intake keeps the person holding the item");
        await Send(owner, HttpMethod.Post, pathItem + "/intake-requests", new { targetPointId = point, rowVersion = Version(item) }, 409);
        await Send(outsider, HttpMethod.Get, $"/api/intake-requests/{Id(intake)}", null, 404);
        await Send(outsider, HttpMethod.Post, $"/api/intake-requests/{Id(intake)}/decision", new { decision = "received", rowVersion = Version(item), confirmedPhysicalReceipt = true }, 403);
        await Send(staff, HttpMethod.Post, $"/api/intake-requests/{Id(intake)}/decision", new { decision = "received", rowVersion = Version(item) }, 400);
        await Send(staff, HttpMethod.Post, $"/api/intake-requests/{Id(intake)}/decision", new { decision = "rejected", rowVersion = Version(item) }, 200);
        Check(Version(await Get(owner, pathItem)) == Version(item), "rejected intake does not change item version or custody");
        intake = await Send(owner, HttpMethod.Post, pathItem + "/intake-requests", new { targetPointId = point, rowVersion = Version(item) }, 201);
        await CheckPage(staff, $"/api/intake-requests?pointId={point}&pageSize=1", 1, 2, 1, true);
        await CheckPage(staff, $"/api/intake-requests?pointId={point}&pageSize=1&page=2", 2, 2, 1, false);
        await CheckPage(staff, $"/api/intake-requests?pointId={secondPoint}&pageSize=1", 1, 1, 0, false);
        await CheckPage(outsider, "/api/intake-requests?pageSize=1", 1, 1, 0, false);
        var receiveKey = Guid.NewGuid();
        var receiveBody = new { decision = "received", rowVersion = Version(item), confirmedPhysicalReceipt = true };
        await Send(staff, HttpMethod.Post, $"/api/intake-requests/{Id(intake)}/decision", receiveBody, 200, receiveKey);
        await Send(staff, HttpMethod.Post, $"/api/intake-requests/{Id(intake)}/decision", receiveBody, 200, receiveKey);
        item = await Get(staff, pathItem);
        Check(!item.GetProperty("canClaim").GetBoolean(), "items at a reception point cannot be claimed online");
        Check(item.GetProperty("custody").GetProperty("pointId").GetGuid() == point, "physical receipt changes to the assigned point");
        Check(!(await Get(claimant, $"/api/conversations/{claimId}")).GetProperty("canSend").GetBoolean(), "old conversation becomes read-only");
        await Get(owner, messagePath);
        await Send(owner, HttpMethod.Get, $"/api/claims/{claimId}", null, 404);
        Check((await Get(claimant, $"/api/claims/{claimId}")).GetProperty("stale").GetBoolean(), "claimant sees stale claim");
        await CheckPage(owner, $"/api/claims?itemId={itemId}&pageSize=1", 1, 1, 0, false);
        await Send(claimant, HttpMethod.Post, messagePath, new { clientMessageId = Guid.NewGuid(), body = "After transfer" }, 409);
        await Send(owner, HttpMethod.Put, pathItem, new { rowVersion = Version(item), content = Content() }, 403);
        await Send(staff, HttpMethod.Post, pathItem + "/claims", new { contentVersion }, 409);
        await Send(staff, HttpMethod.Post, pathItem + "/return", new { rowVersion = Version(item), confirmedPhysicalHandover = true }, 400);
        var returnBody = new { rowVersion = Version(item), confirmedPhysicalHandover = true, verificationNote = "Verified at desk" };
        var returns = await Task.WhenAll(Enumerable.Range(0, 2).Select(_ => Raw(staff, HttpMethod.Post, pathItem + "/return", returnBody)));
        Check(returns.Select(result => result.Status).Order().SequenceEqual(new[] { 201, 409 }), "concurrent returns allow exactly one handover");
        Check((await Get(staff, pathItem)).GetProperty("lifecycle").GetString() == "returned", "point handover updates lifecycle");
        await Send(outsider, HttpMethod.Get, pathItem, null, 404);
        Check((await Get(staff, pathItem + "/custody-events")).GetProperty("items").GetArrayLength() == 3, "registration, receipt and return recorded atomically");
        await CheckPage(staff, pathItem + "/custody-events?pageSize=1", 1, 3, 1, true);
        await CheckPage(staff, pathItem + "/custody-events?pageSize=1&page=3", 3, 3, 1, false);
        await Send(outsider, HttpMethod.Get, pathItem + "/custody-events", null, 403);

        var external = await Publish(owner, await Send(owner, HttpMethod.Post, "/api/items", new
        { content = Content("External item"), custody = new { kind = "external", name = "Library", address = "Public library desk", instructions = "Ask reception" } }, 201));
        Check(!(await Get(claimant, $"/api/items/{Id(external)}")).GetProperty("canClaim").GetBoolean(), "external items cannot be claimed online");
        Check((await Get(outsider, $"/api/items/{Id(external)}")).GetProperty("custody").GetProperty("publicAddress").GetString() == "Public library desk", "external location has public directions");
        await Send(claimant, HttpMethod.Post, $"/api/items/{Id(external)}/claims", new { contentVersion = 1 }, 409);
        await Send(owner, HttpMethod.Post, $"/api/items/{Id(external)}/return", new { rowVersion = Version(external), confirmedPhysicalHandover = true }, 201);

        var selectedPoint = await Send(owner, HttpMethod.Post, "/api/items", new
        { content = Content("Selected point"), custody = new { kind = "point", pointId = secondPoint } }, 201);
        Check(selectedPoint.GetProperty("custody").GetProperty("kind").GetString() == "person", "choosing a point creates pending intake rather than claiming physical custody");
        foreach (var state in new[] { "draft", "hidden" })
        {
            var privateItem = await Send(owner, HttpMethod.Post, "/api/items", CreateBody("Private intake " + state), 201);
            var privatePath = $"/api/items/{Id(privateItem)}";
            var privateIntake = await Send(owner, HttpMethod.Post, privatePath + "/intake-requests",
                new { targetPointId = point, rowVersion = Version(privateItem) }, 201);
            privateItem = await Send(owner, HttpMethod.Put, privatePath,
                new { rowVersion = Version(privateItem), content = Content("Updated private intake " + state) }, 200);
            if (state == "hidden") privateItem = await Send(owner, HttpMethod.Put, privatePath + "/publication",
                new { rowVersion = Version(privateItem), state }, 200);
            await Send(staff, HttpMethod.Get, privatePath, null, 404);
            privateIntake = await Get(staff, $"/api/intake-requests/{Id(privateIntake)}");
            Check(privateIntake.GetProperty("itemRowVersion").GetInt64() == Version(privateItem), "intake detail exposes current item version without granting private item access");
            var listedIntake = (await Get(staff, "/api/intake-requests")).GetProperty("items").EnumerateArray().Single(value => Id(value) == Id(privateIntake));
            Check(listedIntake.GetProperty("itemRowVersion").GetInt64() == Version(privateItem), "intake queue exposes current item version");
            var received = await Send(staff, HttpMethod.Post, $"/api/intake-requests/{Id(privateIntake)}/decision",
                new { decision = "received", rowVersion = privateIntake.GetProperty("itemRowVersion").GetInt64(), confirmedPhysicalReceipt = true }, 200);
            Check(received.GetProperty("itemRowVersion").GetInt64() == Version(await Get(staff, privatePath)), "intake decision returns updated item version");
        }
        var atPoint = await Send(staff, HttpMethod.Post, "/api/items", new
        { content = Content("Registered at desk"), custody = new { kind = "point", pointId = point, confirmedPhysicalReceipt = true } }, 201);
        Check(atPoint.GetProperty("custody").GetProperty("kind").GetString() == "point", "authorized staff may register an item physically held at point");
        var concurrentKey = Guid.NewGuid();
        var creates = await Task.WhenAll(Enumerable.Range(0, 2).Select(_ => Send(owner, HttpMethod.Post, "/api/items", CreateBody("Concurrent create"), 201, concurrentKey)));
        Check(Id(creates[0]) == Id(creates[1]), "concurrent idempotency key creates only one resource");
        var racing = await Publish(owner, await Send(owner, HttpMethod.Post, "/api/items", CreateBody("Receipt versus return"), 201));
        var racingId = Id(racing);
        var racingQuestions = await Get(claimant, $"/api/items/{racingId}/verification-questions");
        var racingClaim = await Send(claimant, HttpMethod.Post, $"/api/items/{racingId}/claims", new
        { contentVersion = racingQuestions.GetProperty("contentVersion").GetInt64() }, 201);
        await Send(owner, HttpMethod.Post, $"/api/claims/{Id(racingClaim)}/decision", new { decision = "approved" }, 200);
        var racingIntake = await Send(owner, HttpMethod.Post, $"/api/items/{racingId}/intake-requests", new { targetPointId = point, rowVersion = Version(racing) }, 201);
        var mutations = await Task.WhenAll(
            Raw(owner, HttpMethod.Post, $"/api/items/{racingId}/return", new { rowVersion = Version(racing), confirmedPhysicalHandover = true, claimId = Id(racingClaim) }),
            Raw(staff, HttpMethod.Post, $"/api/intake-requests/{Id(racingIntake)}/decision", new { rowVersion = Version(racing), decision = "received", confirmedPhysicalReceipt = true }));
        Check(mutations.Count(value => value.Status is >= 200 and < 300) == 1 && mutations.Count(value => value.Status is 403 or 409) == 1,
            "receipt versus personal return permits exactly one state transition");
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            Check(await db.CustodyEvents.CountAsync(value => value.ItemId == racingId && (value.EventKind == "received" || value.EventKind == "returned")) == 1,
                "racing receipt and return cannot both persist history");
            var assignment = await db.PointStaff.SingleAsync(value => value.PointId == point && value.UserId == staffId);
            assignment.CanReceive = false;
            await db.SaveChangesAsync();
        }
        await Get(staff, $"/api/items/{Id(atPoint)}");
        await Send(staff, HttpMethod.Put, $"/api/items/{Id(atPoint)}", new { rowVersion = Version(atPoint), content = Content() }, 403);
        await Send(staff, HttpMethod.Post, $"/api/items/{Id(atPoint)}/return", new { rowVersion = Version(atPoint), confirmedPhysicalHandover = true, verificationNote = "Return-only staff verified recipient" }, 201);
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var assignment = await db.PointStaff.SingleAsync(value => value.PointId == point && value.UserId == staffId);
            assignment.RevokedAt = DateTimeOffset.UtcNow;
            await db.SaveChangesAsync();
        }
        await Send(staff, HttpMethod.Post, $"/api/items/{Id(atPoint)}/return", new { rowVersion = Version(atPoint), confirmedPhysicalHandover = true, verificationNote = "At desk" }, 403);
        await Send(staff, HttpMethod.Post, $"/api/intake-requests/{Id(intake)}/decision", receiveBody, 404, receiveKey);

        var hidden = await Publish(owner, await Send(owner, HttpMethod.Post, "/api/items", CreateBody("Hidden item"), 201));
        await Send(owner, HttpMethod.Put, $"/api/items/{Id(hidden)}/publication", new { rowVersion = Version(hidden), state = "hidden" }, 200);
        await Send(outsider, HttpMethod.Get, $"/api/items/{Id(hidden)}", null, 404);
        Check((await Get(owner, "/api/items?scope=mine")).GetProperty("items").GetArrayLength() >= 5, "author may inspect own drafts and hidden items");

        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var payloads = await db.IndexOutbox.Where(value => value.ItemId == secretId || value.ItemId == itemId).Select(value => value.Payload).ToListAsync();
            Check(payloads.All(value => !value.Contains("TOP_SECRET_EVIDENCE") && !value.Contains("Private chat") && !value.Contains("Private decision")), "outbox never contains answers, chat or private decisions");
            var outbox = await db.IndexOutbox.Where(value => value.ItemId == itemId).OrderBy(value => value.DocumentVersion).ToListAsync();
            Check(outbox.Select(value => value.DocumentVersion).SequenceEqual(new long[] { 1, 2, 3, 4 })
                && outbox.Last().EventKind == "tombstone", "outbox follows monotonic document versions and tombstones returned item");
            Check(await db.CustodyEvents.CountAsync(value => value.ItemId == itemId && value.EventKind == "returned") == 1, "exactly one return row persisted");
            var registration = await db.CustodyEvents.SingleAsync(value => value.ItemId == itemId && value.EventKind == "registered");
            using var custodySnapshot = JsonDocument.Parse(registration.ToCustody!);
            Check(custodySnapshot.RootElement.GetProperty("holderUserId").GetGuid() == ownerId
                && payloads.All(value => !value.Contains("holderUserId")), "private custody audit preserves holder identity without exposing it in public search projection");
            Check(await db.IdempotencyKeys.CountAsync(value => value.ActorUserId == ownerId && value.IdempotencyKeyValue == key) == 1, "idempotency row committed once");
        }
        var differentHolderItem = new Item { PostedBy = ownerId, HolderUserId = staffId, Title = "Different author and holder",
            PublicDescription = "Black wallet", FoundArea = "Campus", PublicationState = "published" };
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            db.Items.Add(differentHolderItem);
            await db.SaveChangesAsync();
        }
        var differentHolderClaims = $"/api/items/{differentHolderItem.Id}/claims";
        Check(!(await Get(owner, $"/api/items/{differentHolderItem.Id}")).GetProperty("canClaim").GetBoolean()
            && !(await Get(staff, $"/api/items/{differentHolderItem.Id}")).GetProperty("canClaim").GetBoolean()
            && (await Get(outsider, $"/api/items/{differentHolderItem.Id}")).GetProperty("canClaim").GetBoolean(),
            "both author and holder are excluded while unrelated viewers can claim");
        await Send(owner, HttpMethod.Post, differentHolderClaims, new { contentVersion = 1 }, 400);
        await Send(staff, HttpMethod.Post, differentHolderClaims, new { contentVersion = 1 }, 400);
        await Send(outsider, HttpMethod.Post, differentHolderClaims, new { contentVersion = 1 }, 201);
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            await db.Items.Where(value => value.Id == differentHolderItem.Id).ExecuteUpdateAsync(update => update.SetProperty(value => value.Lifecycle, "returned"));
        }
        Check(!(await Get(staff, $"/api/items/{differentHolderItem.Id}")).GetProperty("canClaim").GetBoolean(), "returned personal-custody items cannot be claimed");
        Console.WriteLine($"PASS: {checks} recovery API checks (HTTP, authorization, validation, concurrency, replay and privacy)");

        async Task<HttpClient> User(string subject)
        {
            var browser = factory.CreateClient(new WebApplicationFactoryClientOptions
            { AllowAutoRedirect = false, HandleCookies = true, BaseAddress = new Uri("https://localhost") });
            await login(browser, subject);
            var csrf = await Get(browser, "/api/auth/csrf");
            browser.DefaultRequestHeaders.Add("X-CSRF-TOKEN", csrf.GetProperty("token").GetString());
            return browser;
        }
        async Task CheckPage(HttpClient browser, string path, int page, int totalPages, int itemCount, bool hasMore)
        {
            var result = await Get(browser, path);
            Check(result.GetProperty("page").GetInt32() == page && result.GetProperty("pageSize").GetInt32() == 1
                && result.GetProperty("totalPages").GetInt32() == totalPages
                && result.GetProperty("items").GetArrayLength() == itemCount
                && result.GetProperty("hasMore").GetBoolean() == hasMore, "filtered, authorized pagination metadata: " + path);
        }
        async Task<JsonElement> Publish(HttpClient browser, JsonElement value)
        {
            await PublicationImageFixture.EnsureAsync(factory, Id(value));
            return await Send(browser, HttpMethod.Put, $"/api/items/{Id(value)}/publication",
                new { rowVersion = Version(value), state = "published" }, 200);
        }
    }
    static object Content(string title = "API wallet", string[]? questions = null) => new
    { title, publicDescription = "Black wallet with gold zipper", foundArea = "Campus", foundTimePrecision = "date", foundOn = "2026-01-01", verificationQuestions = questions ?? [] };
    static object CreateBody(string title = "API wallet") => new { content = Content(title), custody = new { kind = "person" } };
    static Guid Id(JsonElement value) => value.GetProperty("id").GetGuid();
    static long Version(JsonElement value) => value.GetProperty("rowVersion").GetInt64();
    static Task<JsonElement> Get(HttpClient client, string path) => Send(client, HttpMethod.Get, path, null, 200);
    static async Task<(int Status, JsonElement Body)> Raw(HttpClient client, HttpMethod method, string path, object? body, Guid? key = null)
    {
        using var request = new HttpRequestMessage(method, path);
        if (body is not null) request.Content = JsonContent.Create(body);
        if (method != HttpMethod.Get) request.Headers.Add("Idempotency-Key", (key ?? Guid.NewGuid()).ToString());
        using var response = await client.SendAsync(request);
        var content = await response.Content.ReadAsStringAsync();
        return ((int)response.StatusCode, content.Length == 0 ? default : JsonDocument.Parse(content).RootElement.Clone());
    }
    static async Task<JsonElement> Send(HttpClient client, HttpMethod method, string path, object? body, int expected, Guid? key = null)
    {
        var response = await Raw(client, method, path, body, key);
        Check(response.Status == expected, $"{method} {path}: expected {expected}, got {response.Status}: {response.Body}");
        return response.Body;
    }
    static void Check(bool condition, string description)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + description);
        Interlocked.Increment(ref checks);
    }
}
