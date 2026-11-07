using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Findie.Api.Data;
using Findie.Api.Models;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

static class AdminChecks
{
    static int checks;

    public static async Task RunAsync(WebApplicationFactory<FindieDbContext> factory, Func<HttpClient, string, Task> login)
    {
        // 1. Setup users: a normal user and an admin user
        using var normalUser = await User("normal-user");
        using var admin = await User("admin");

        var normalProfile = await Get(normalUser, "/api/users/me");
        var normalUserId = Id(normalProfile);
        Check(!normalProfile.GetProperty("isAdmin").GetBoolean(), "normal user is not admin");

        var adminProfile = await Get(admin, "/api/users/me");
        var adminId = Id(adminProfile);
        Check(adminProfile.GetProperty("isAdmin").GetBoolean(), "admin user has isAdmin = true");

        // 2. Authorization Boundaries (401 & 403 checks)
        using var anonymous = factory.CreateClient();
        await Send(anonymous, HttpMethod.Get, "/api/admin/overview", null, 401);
        await Send(anonymous, HttpMethod.Get, "/api/admin/users", null, 401);
        await Send(anonymous, HttpMethod.Get, "/api/admin/items", null, 401);
        await Send(anonymous, HttpMethod.Get, "/api/admin/points", null, 401);

        await Send(normalUser, HttpMethod.Get, "/api/admin/overview", null, 403);
        await Send(normalUser, HttpMethod.Get, "/api/admin/users", null, 403);
        await Send(normalUser, HttpMethod.Get, "/api/admin/items", null, 403);
        await Send(normalUser, HttpMethod.Get, "/api/admin/points", null, 403);

        // 3. Admin Overview Endpoint
        var overview = await Get(admin, "/api/admin/overview");
        Check(overview.TryGetProperty("totalItems", out _) && overview.TryGetProperty("totalUsers", out _), "admin overview returns stats structure");

        // 4. Admin Users Moderation
        var usersPage = await Get(admin, "/api/admin/users");
        Check(usersPage.GetProperty("items").GetArrayLength() > 0, "admin can list users");

        // Admin cannot toggle self
        await Send(admin, HttpMethod.Post, $"/api/admin/users/{adminId}/toggle-status", null, 400);

        // Admin toggles normal user status -> disabled
        var toggledUser = await Send(admin, HttpMethod.Post, $"/api/admin/users/{normalUserId}/toggle-status", null, 200);
        Check(toggledUser.GetProperty("disabledAt").ValueKind != JsonValueKind.Null, "normal user is now disabled");

        // Normal user is blocked from making requests
        await Send(normalUser, HttpMethod.Get, "/api/users/me", null, 403);

        // Admin toggles normal user status again -> re-enabled
        var reenabledUser = await Send(admin, HttpMethod.Post, $"/api/admin/users/{normalUserId}/toggle-status", null, 200);
        Check(reenabledUser.GetProperty("disabledAt").ValueKind == JsonValueKind.Null, "normal user is re-enabled");
        await Send(normalUser, HttpMethod.Get, "/api/users/me", null, 200);

        // 5. Admin Items Moderation
        var createItemBody = new
        {
            content = new
            {
                title = "Item for Admin Moderation",
                publicDescription = "A test item description",
                foundArea = "Library",
                foundTimePrecision = "date",
                foundOn = "2026-02-01",
                verificationQuestions = Array.Empty<string>()
            },
            custody = new { kind = "person" }
        };
        var createdItem = await Send(normalUser, HttpMethod.Post, "/api/items", createItemBody, 201, Guid.NewGuid());
        var itemId = Id(createdItem);

        // Admin lists items
        var itemsPage = await Get(admin, "/api/admin/items?query=Item%20for%20Admin%20Moderation");
        Check(itemsPage.GetProperty("items").GetArrayLength() > 0, "admin item search finds created item");

        // Admin sets publication state to hidden
        var hideResult = await Send(admin, HttpMethod.Post, $"/api/admin/items/{itemId}/set-publication",
            new { publicationState = "hidden" }, 200);
        Check(hideResult.GetProperty("publicationState").GetString() == "hidden", "admin hid item");

        // Admin sets publication state to published
        var pubResult = await Send(admin, HttpMethod.Post, $"/api/admin/items/{itemId}/set-publication",
            new { publicationState = "published" }, 200);
        Check(pubResult.GetProperty("publicationState").GetString() == "published", "admin published item");

        // 6. Admin Points & Staff Moderation
        var pointsList = await Get(admin, "/api/admin/points");
        Check(pointsList.GetArrayLength() > 0, "admin lists reception points");

        var newPoint = await Send(admin, HttpMethod.Post, "/api/admin/points",
            new { name = "Moderated Admin Desk", publicAddress = "Building C Lobby", directions = "Floor 1 near elevator" }, 201);
        var pointId = Id(newPoint);
        Check(newPoint.GetProperty("active").GetBoolean(), "newly created point is active");

        // Toggle point active state
        var toggledPoint = await Send(admin, HttpMethod.Post, $"/api/admin/points/{pointId}/toggle", null, 200);
        Check(!toggledPoint.GetProperty("active").GetBoolean(), "point toggled to inactive");

        var reactivatedPoint = await Send(admin, HttpMethod.Post, $"/api/admin/points/{pointId}/toggle", null, 200);
        Check(reactivatedPoint.GetProperty("active").GetBoolean(), "point toggled back to active");

        // Assign staff to point
        var assignStaffBody = new
        {
            userEmail = "normal-user@example.test",
            canReceive = true,
            canReturn = true
        };
        var staffResult = await Send(admin, HttpMethod.Post, $"/api/admin/points/{pointId}/staff", assignStaffBody, 200);
        Check(staffResult.GetProperty("canReceive").GetBoolean() && staffResult.GetProperty("canReturn").GetBoolean(), "staff permissions assigned");

        // Verify staff list
        var pointStaffList = await Get(admin, $"/api/admin/points/{pointId}/staff");
        Check(pointStaffList.GetArrayLength() == 1, "point has 1 assigned staff member");

        // Verify normalUser now reflects isStaff = true in /api/users/me
        var staffProfile = await Get(normalUser, "/api/users/me");
        Check(staffProfile.GetProperty("isStaff").GetBoolean(), "normal user profile reflects isStaff = true");
        Check(staffProfile.GetProperty("managedPoints").GetArrayLength() > 0, "managedPoints includes the assigned point");

        // Revoke staff
        await Send(admin, HttpMethod.Delete, $"/api/admin/points/{pointId}/staff/{normalUserId}", null, 204);

        // Verify staff is revoked
        var updatedStaffProfile = await Get(normalUser, "/api/users/me");
        Check(!updatedStaffProfile.GetProperty("isStaff").GetBoolean(), "normal user profile reflects isStaff = false after revocation");

        Console.WriteLine($"PASS: {checks} admin API checks (role-based access, user toggle, publication moderation, point management, staff assignment and revocation)");

        async Task<HttpClient> User(string subject)
        {
            var browser = factory.CreateClient(new WebApplicationFactoryClientOptions
            {
                AllowAutoRedirect = false,
                HandleCookies = true,
                BaseAddress = new Uri("https://localhost")
            });
            await login(browser, subject);
            using var csrfMsg = await browser.GetAsync("/api/auth/csrf");
            var csrfJson = await csrfMsg.Content.ReadFromJsonAsync<JsonElement>();
            browser.DefaultRequestHeaders.Add("X-CSRF-TOKEN", csrfJson.GetProperty("token").GetString());
            return browser;
        }
    }

    static Guid Id(JsonElement value) => value.GetProperty("id").GetGuid();

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
