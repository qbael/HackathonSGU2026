using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Findie.Api.Data;
using Findie.Api.Models;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;
using Findie.Api.Infrastructure;
using Findie.Api.Controllers;
using Microsoft.AspNetCore.Mvc.Controllers;
using Microsoft.AspNetCore.Routing;
using System.Text.RegularExpressions;

PaginationChecks.Run();
await MaintenanceChecks.RunAsync();
if (args.Contains("--maintenance-only")) return;

var connection = Environment.GetEnvironmentVariable("ConnectionStrings__Database")
    ?? throw new InvalidOperationException("Use python3 apps/api/tests/integration.py to create a disposable database.");
if (new NpgsqlConnectionStringBuilder(connection).Database?.StartsWith("findie_test_", StringComparison.Ordinal) != true)
    throw new InvalidOperationException("Integration checks only accept a findie_test_ database.");

Environment.SetEnvironmentVariable("Ai__ServiceToken", "integration-token");
Environment.SetEnvironmentVariable("AdminEmails", "admin@example.test");
Environment.SetEnvironmentVariable("Authentication__Google__ClientId", "integration-client");
Environment.SetEnvironmentVariable("Authentication__Google__ClientSecret", "integration-secret");
if (!args.Contains("--cross-service-only"))
{
    Environment.SetEnvironmentVariable("Ai__RedactionRevision", "integration-redaction-revision");
    Environment.SetEnvironmentVariable("Ai__EmbeddingRevision", "integration-embedding-revision");
    Environment.SetEnvironmentVariable("Ai__EmbeddingDimensions", "768");
}
Environment.SetEnvironmentVariable("RabbitMq__Uri", "");
Environment.SetEnvironmentVariable("Storage__Endpoint", "");
var google = new FakeGoogleHandler();
var aiGateway = new StubAiGateway();
var storage = new StubStorage();
await using var factory = new WebApplicationFactory<FindieDbContext>().WithWebHostBuilder(builder =>
{
    builder.UseEnvironment("Production");
    builder.UseSetting("contentRoot", Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../")));
    builder.ConfigureServices(services =>
    {
        services.PostConfigure<GoogleOptions>(GoogleDefaults.AuthenticationScheme, options => options.Backchannel = new HttpClient(google));
        services.AddSingleton<IAiGateway>(aiGateway);
        services.AddSingleton<IProcessedStorage>(storage);
    });
});

if (args.Contains("--cross-service-only"))
{
    await CrossServiceChecks.RunAsync(factory);
    return;
}

using (var scope = factory.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
    Check(!db.Database.HasPendingModelChanges(), "migration matches the current EF model");
    Check(db.Model.GetEntityTypes().Count() == 24, "24 Identity and business entity types");
    Check(db.Model.GetEntityTypes().SelectMany(entity => entity.GetForeignKeys())
        .All(key => key.DeleteBehavior == DeleteBehavior.Restrict), "all relationships restrict deletion");
    Check(!db.Model.GetEntityTypes().SelectMany(entity => entity.GetProperties())
        .Any(property => property.Name.Contains("Original", StringComparison.Ordinal) && property.Name != nameof(ItemImage.OriginalEmbedding)), "no original image storage outside derived vectors");
    db.ReceptionPoints.AddRange(Enumerable.Range(0, 105).Select(index => new ReceptionPoint
    {
        Name = $"Point {index:D3}", PublicAddress = "Public campus address", Directions = "Main entrance"
    }));
    db.ReceptionPoints.Add(new ReceptionPoint { Name = "Inactive", PublicAddress = "Private", Active = false });
    await db.SaveChangesAsync();
}

using var anonymous = NewClient();
await Expect(anonymous.GetAsync("/api/users/me"), HttpStatusCode.Unauthorized, "profile requires authentication");
await Expect(anonymous.GetAsync("/api/reception-points"), HttpStatusCode.Unauthorized, "points require authentication");
await Expect(anonymous.GetAsync("/api/auth/google?returnUrl=https://evil.example"), HttpStatusCode.BadRequest, "reject external redirects");
await Expect(anonymous.GetAsync("/api/auth/google/callback"), HttpStatusCode.Unauthorized, "callback needs an external cookie");
await Expect(anonymous.GetAsync("/api/auth/google/signin?code=fake&state=forged"), HttpStatusCode.Unauthorized, "OAuth rejects forged state");
await Expect(anonymous.PostAsJsonAsync("/api/auth/register", new { }), HttpStatusCode.NotFound, "no password registration endpoint");

using var client = NewClient();
await GoogleLogin(client, "owner", "owner@example.test", verified: true, HttpStatusCode.Redirect);
var profile = await Read(client, "/api/users/me");
Check(profile.GetProperty("email").GetString() == "owner@example.test", "Google identity persisted");
Check(profile.EnumerateObject().Select(property => property.Name).Order().SequenceEqual(
    new[] { "createdAt", "displayName", "email", "id", "isAdmin", "isStaff", "managedPoints" }), "profile DTO exposes only safe fields");
var ownerId = profile.GetProperty("id").GetGuid();

await Expect(client.PutAsJsonAsync("/api/users/me", new { displayName = "Updated" }), HttpStatusCode.BadRequest, "writes require CSRF");
var token = (await Read(client, "/api/auth/csrf")).GetProperty("token").GetString()!;
client.DefaultRequestHeaders.Add("X-CSRF-TOKEN", token);
await Expect(client.PutAsJsonAsync("/api/users/me", new { displayName = "   " }), HttpStatusCode.BadRequest, "blank display name rejected");
await Expect(client.PutAsJsonAsync("/api/users/me", new { displayName = new string('x', 121) }), HttpStatusCode.BadRequest, "long display name rejected");
await Expect(client.PutAsJsonAsync("/api/users/me", new { displayName = (string?)null }), HttpStatusCode.BadRequest, "null display name rejected");
await Expect(client.PutAsJsonAsync("/api/users/me", new { displayName = "  Tên mới  ", id = Guid.NewGuid(), disabledAt = DateTimeOffset.UtcNow }),
    HttpStatusCode.OK, "profile updates with CSRF");
profile = await Read(client, "/api/users/me");
Check(profile.GetProperty("displayName").GetString() == "Tên mới" && profile.GetProperty("id").GetGuid() == ownerId,
    "trim display name and ignore attempted identity overposting");
var points = await Read(client, "/api/reception-points");
Check(points.GetArrayLength() == 100 && points[0].GetProperty("name").GetString() == "Point 000"
    && points[99].GetProperty("name").GetString() == "Point 099", "bounded and sorted active point list");
var pointId = points[0].GetProperty("id").GetGuid();
await Expect(client.GetAsync($"/api/reception-points/{pointId}"), HttpStatusCode.OK, "active point detail");
await Expect(client.GetAsync($"/api/reception-points/{Guid.NewGuid()}"), HttpStatusCode.NotFound, "missing point returns 404");
using (var scope = factory.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
    var inactive = await db.ReceptionPoints.SingleAsync(point => !point.Active);
    await Expect(client.GetAsync($"/api/reception-points/{inactive.Id}"), HttpStatusCode.NotFound, "inactive point returns 404");
}

using var repeat = NewClient();
await GoogleLogin(repeat, "owner", "owner@example.test", verified: true, HttpStatusCode.Redirect);
Check((await Read(repeat, "/api/users/me")).GetProperty("id").GetGuid() == ownerId, "repeat Google login reuses provider account");
using var collision = NewClient();
await GoogleLogin(collision, "other-subject", "owner@example.test", verified: true, HttpStatusCode.Unauthorized);
using var unverified = NewClient();
await GoogleLogin(unverified, "unverified", "unverified@example.test", verified: false, HttpStatusCode.Unauthorized);

using (var scope = factory.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
    Check(await db.Users.CountAsync() == 1 && await db.UserLogins.CountAsync() == 1, "failed sign-ins leave no partial users or linked accounts");
    var user = await db.Users.SingleAsync();
    Check(user.PasswordHash is null, "Google account has no password");
    user.DisabledAt = DateTimeOffset.UtcNow;
    await db.SaveChangesAsync();
}
await Expect(repeat.GetAsync("/api/users/me"), HttpStatusCode.Forbidden, "disable takes effect on existing session");
using var disabled = NewClient();
await GoogleLogin(disabled, "owner", "owner@example.test", verified: true, HttpStatusCode.Unauthorized);
using (var scope = factory.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
    var user = await db.Users.SingleAsync();
    user.DisabledAt = null;
    await db.SaveChangesAsync();
}
await Expect(client.PostAsync("/api/auth/logout", null), HttpStatusCode.NoContent, "logout succeeds with CSRF");
await Expect(client.GetAsync("/api/users/me"), HttpStatusCode.Unauthorized, "logout removes session");

await CheckDatabaseRules();
await RecoveryChecks.RunAsync(factory, async (browser, subject) =>
    await GoogleLogin(browser, subject, subject + "@example.test", true, HttpStatusCode.Redirect));
await ItemDeletionChecks.RunAsync(factory, aiGateway, async (browser, subject) =>
    await GoogleLogin(browser, subject, subject + "@example.test", true, HttpStatusCode.Redirect));
await ImageSearchChecks.RunAsync(factory, aiGateway, storage, async (browser, subject) =>
    await GoogleLogin(browser, subject, subject + "@example.test", true, HttpStatusCode.Redirect));
await SearchQueryChecks.RunAsync(factory);
await SavedSearchChecks.RunAsync(factory, aiGateway, storage, async (browser, subject) =>
    await GoogleLogin(browser, subject, subject + "@example.test", true, HttpStatusCode.Redirect));
await AdminChecks.RunAsync(factory, async (browser, subject) =>
    await GoogleLogin(browser, subject, subject + "@example.test", true, HttpStatusCode.Redirect));
await BrokerChecks.RunAsync(factory.Services.GetRequiredService<IServiceScopeFactory>());
using (var seedScope = factory.Services.CreateScope())
    await LocalSeedChecks.RunAsync(seedScope.ServiceProvider.GetRequiredService<FindieDbContext>());
var documentation = string.Join("\n", new[] { "recovery.md", "media-search.md", "saved-searches.md" }.Select(file => File.ReadAllText(
    Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../../../docs/api/", file)))));
static string NormalizeRoute(string route) => Regex.Replace(route.Split('?')[0].TrimStart('/'), "\\{[^}]+\\}", "{id}");
var documented = Regex.Matches(documentation, @"(?m)^## (GET|POST|PUT|DELETE) (/api/[^\s?]+)")
    .Select(match => match.Groups[1].Value + " " + NormalizeRoute(match.Groups[2].Value)).ToHashSet();
var implemented = factory.Services.GetRequiredService<EndpointDataSource>().Endpoints.OfType<RouteEndpoint>()
    .Where(endpoint => endpoint.Metadata.GetMetadata<ControllerActionDescriptor>() is { } action
        && typeof(RecoveryController).IsAssignableFrom(action.ControllerTypeInfo))
    .SelectMany(endpoint => endpoint.Metadata.GetMetadata<HttpMethodMetadata>()!.HttpMethods.Select(method =>
        method + " " + NormalizeRoute(endpoint.RoutePattern.RawText!))).ToHashSet();
Check(implemented.Count == 33 && documented.SetEquals(implemented), "every new recovery/media/search endpoint has dedicated API documentation");
Console.WriteLine("PASS: all 33 business/media/search endpoints have matching per-endpoint documentation");
Console.WriteLine("PASS: migrations, EF relationships, Google OAuth, Identity, cookie/CSRF, profile validation, DTOs, point lookup, SQL invariants and concurrency");

HttpClient NewClient() => factory.CreateClient(new WebApplicationFactoryClientOptions
{
    AllowAutoRedirect = false, HandleCookies = true, BaseAddress = new Uri("https://localhost")
});

async Task GoogleLogin(HttpClient browser, string subject, string email, bool verified, HttpStatusCode expected)
{
    google.Subject = subject;
    google.Email = email;
    google.Verified = verified;
    using var challenge = await browser.GetAsync("/api/auth/google?returnUrl=%2F");
    Check(challenge.StatusCode == HttpStatusCode.Redirect, "Google challenge redirects");
    var location = challenge.Headers.Location!;
    Check(location.Host == "accounts.google.com", "challenge goes to Google");
    var state = QueryHelpers.ParseQuery(location.Query)["state"].ToString();
    Check(!string.IsNullOrEmpty(state), "OAuth state is issued");
    using var remote = await browser.GetAsync($"/api/auth/google/signin?code=integration-code&state={Uri.EscapeDataString(state)}");
    Check(remote.StatusCode == HttpStatusCode.Redirect, "remote callback validates state and issues external cookie");
    using var callback = await browser.GetAsync(remote.Headers.Location);
    Check(callback.StatusCode == expected, $"complete Google login for {subject}: expected {expected}, got {callback.StatusCode}");
}

async Task CheckDatabaseRules()
{
    using var scope = factory.Services.CreateScope();
    var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
    var manager = scope.ServiceProvider.GetRequiredService<UserManager<ApplicationUser>>();
    var claimant = new ApplicationUser { UserName = "claimant", DisplayName = "Claimant", Email = "claimant@example.test" };
    Check((await manager.CreateAsync(claimant)).Succeeded, "second identity created for claim fixture");
    var item = new Item { PostedBy = ownerId, HolderUserId = ownerId, Title = "Found wallet", PublicDescription = "A black wallet", FoundArea = "Campus" };
    db.Items.Add(item);
    await db.SaveChangesAsync();
    var claim = new Findie.Api.Models.Claim { ItemId = item.Id, ClaimantUserId = claimant.Id, ReviewerUserId = ownerId, SourceCustodyVersion = 1 };
    db.Claims.Add(claim);
    await db.SaveChangesAsync();
    Check(!await db.VerificationQuestions.AnyAsync(), "claim supports zero verification questions");

    await Reject($"UPDATE items SET holder_point_id = {pointId} WHERE id = {item.Id}", PostgresErrorCodes.CheckViolation, "two holders rejected");
    await Reject($"UPDATE items SET found_time_precision = 'range' WHERE id = {item.Id}", PostgresErrorCodes.CheckViolation, "invalid time range rejected");
    await Reject($"INSERT INTO verification_questions (item_id, slot, question_text) VALUES ({item.Id}, 4, 'Question')", PostgresErrorCodes.CheckViolation, "fourth question rejected");
    await Reject($"INSERT INTO conversations (claim_id) VALUES ({claim.Id})", PostgresErrorCodes.ForeignKeyViolation, "pending claim cannot open chat");
    await Reject($"INSERT INTO item_images (id, item_id, position, processing_state) VALUES ({Guid.NewGuid()}, {item.Id}, 1, 'ready')", PostgresErrorCodes.CheckViolation, "unreviewed image cannot be ready");
    await Reject($"INSERT INTO stored_objects (id, owner_user_id, bucket, object_key, object_kind, expires_at) VALUES ({Guid.NewGuid()}, {ownerId}, 'private', 'original', 'original', now())", PostgresErrorCodes.CheckViolation, "original image object rejected");
    await Reject($"DELETE FROM app_users WHERE id = {ownerId}", PostgresErrorCodes.ForeignKeyViolation, "referenced users cannot be deleted");
    await db.Claims.Where(value => value.Id == claim.Id).ExecuteUpdateAsync(update => update
        .SetProperty(value => value.Status, "approved").SetProperty(value => value.DecidedBy, ownerId)
        .SetProperty(value => value.DecidedAt, DateTimeOffset.UtcNow));
    db.Entry(claim).State = EntityState.Detached;
    claim = await db.Claims.SingleAsync(value => value.Id == claim.Id);
    db.Conversations.Add(new Conversation { ClaimId = claim.Id });
    await db.SaveChangesAsync();
    var message = new Message { ConversationId = claim.Id, SenderUserId = ownerId, ClientMessageId = Guid.NewGuid(), Body = "Hello" };
    db.Messages.Add(message);
    await db.SaveChangesAsync();
    Check(message.MessageSequence > 0, "message ordering is database generated");
    await Reject($"INSERT INTO messages (id, conversation_id, sender_user_id, client_message_id, body) VALUES ({Guid.NewGuid()}, {claim.Id}, {ownerId}, {message.ClientMessageId}, 'Retry')", PostgresErrorCodes.UniqueViolation, "duplicate message key rejected");
    await db.Database.ExecuteSqlInterpolatedAsync($"INSERT INTO custody_events (id, item_id, event_kind, custody_version, actor_user_id, from_custody, occurred_at) VALUES ({Guid.NewGuid()}, {item.Id}, 'returned', 2, {ownerId}, '{{}}'::jsonb, now())");
    await Reject($"INSERT INTO custody_events (id, item_id, event_kind, custody_version, actor_user_id, from_custody, occurred_at) VALUES ({Guid.NewGuid()}, {item.Id}, 'returned', 3, {ownerId}, '{{}}'::jsonb, now())", PostgresErrorCodes.UniqueViolation, "second return rejected");
    await Reject($"INSERT INTO ai_jobs (id, item_id, job_kind, source_version, source_sha256, model_id, model_revision, processing_profile, max_attempts) VALUES ({Guid.NewGuid()}, {item.Id}, 'redact_image', 1, {new string('a', 64)}, 'model', 'revision', 'profile', 3)", PostgresErrorCodes.CheckViolation, "durable raw-image redaction job rejected");
    db.IndexOutbox.Add(new IndexOutbox { ItemId = Guid.NewGuid(), DocumentVersion = 1, EventKind = "tombstone", Payload = "{}", PayloadSha256 = new string('b', 64), MaxAttempts = 3 });
    await db.SaveChangesAsync();
    Check(await db.IndexOutbox.CountAsync() == 1, "tombstone survives without an item FK");

    using var otherScope = factory.Services.CreateScope();
    var otherDb = otherScope.ServiceProvider.GetRequiredService<FindieDbContext>();
    var stale = await otherDb.Items.SingleAsync(value => value.Id == item.Id);
    item.Title = "Updated wallet";
    item.RowVersion++;
    await db.SaveChangesAsync();
    stale.Title = "Stale edit";
    stale.RowVersion++;
    try
    {
        await otherDb.SaveChangesAsync();
        throw new InvalidOperationException("FAIL: stale item update should fail");
    }
    catch (DbUpdateConcurrencyException) { }

    async Task Reject(FormattableString sql, string code, string description)
    {
        try
        {
            await db.Database.ExecuteSqlInterpolatedAsync(sql);
        }
        catch (PostgresException exception) when (exception.SqlState == code)
        {
            return;
        }
        throw new InvalidOperationException($"FAIL: {description}");
    }
}

static async Task<JsonElement> Read(HttpClient client, string path)
{
    using var response = await client.GetAsync(path);
    Check(response.IsSuccessStatusCode, $"GET {path}: {response.StatusCode}");
    return await response.Content.ReadFromJsonAsync<JsonElement>();
}

static async Task Expect(Task<HttpResponseMessage> request, HttpStatusCode expected, string description)
{
    using var response = await request;
    Check(response.StatusCode == expected, $"{description}: expected {expected}, got {response.StatusCode}");
}

static void Check(bool condition, string description)
{
    if (!condition) throw new InvalidOperationException($"FAIL: {description}");
}

sealed class FakeGoogleHandler : HttpMessageHandler
{
    public string Subject { get; set; } = "owner";
    public string Email { get; set; } = "owner@example.test";
    public bool Verified { get; set; } = true;

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        object body = request.RequestUri!.AbsoluteUri == GoogleDefaults.TokenEndpoint
            ? new { access_token = "integration-access-token", token_type = "Bearer", expires_in = 3600 }
            : request.RequestUri.AbsoluteUri == GoogleDefaults.UserInformationEndpoint
                ? new { sub = Subject, email = Email, email_verified = Verified, name = "Google user" }
                : throw new InvalidOperationException("Unexpected external request during OAuth test.");
        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(body) });
    }
}
