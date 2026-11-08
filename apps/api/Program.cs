using Findie.Api.Data;
using Findie.Api.Models;
using Findie.Api.Repositories;
using Findie.Api.Services;
using Findie.Api.Security;
using System.Security.Claims;
using Microsoft.AspNetCore.Antiforgery;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Npgsql;
using System.Threading.RateLimiting;
using Findie.Api.Infrastructure;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.AspNetCore.DataProtection;
var seedLocal = args.Contains("--seed-local", StringComparer.Ordinal);
var importPublicSamples = args.Contains("--import-public-samples", StringComparer.Ordinal);
var builder = WebApplication.CreateBuilder(seedLocal || importPublicSamples ? [] : args);

if (args.Contains("--migrate", StringComparer.Ordinal) || args.Contains("--check-schema", StringComparer.Ordinal))
{
    var dsn = builder.Configuration.GetConnectionString("Database")
        ?? throw new InvalidOperationException("Migration database is required.");
    await using var db = new FindieDbContext(new DbContextOptionsBuilder<FindieDbContext>().UseNpgsql(dsn).Options);
    if (args.Contains("--check-schema", StringComparer.Ordinal))
    {
        Environment.ExitCode = (await db.Database.GetPendingMigrationsAsync()).Any() ? 1 : 0;
        return;
    }
    await using var migrationLock = new NpgsqlConnection(dsn);
    await migrationLock.OpenAsync();
    await using var gate = new NpgsqlCommand("SELECT pg_advisory_lock(643182015)", migrationLock);
    await gate.ExecuteNonQueryAsync();
    await db.Database.MigrateAsync();
    return;
}

if (importPublicSamples && !builder.Environment.IsDevelopment())
    throw new InvalidOperationException("Source sample import is allowed only in Development.");

if (seedLocal)
{
    if (!builder.Environment.IsDevelopment())
        throw new InvalidOperationException("Local seeding is allowed only in Development.");
    var seedConnection = builder.Configuration.GetConnectionString("Database");
    if (string.IsNullOrWhiteSpace(seedConnection))
        throw new InvalidOperationException("Set ConnectionStrings__Database before local seeding.");
    await using var seedDb = new FindieDbContext(new DbContextOptionsBuilder<FindieDbContext>().UseNpgsql(seedConnection).Options);
    Environment.ExitCode = await LocalSeed.RunAsync(seedDb, args, Console.Out);
    return;
}

var connectionString = builder.Configuration.GetConnectionString("Database");
if (string.IsNullOrWhiteSpace(connectionString))
    throw new InvalidOperationException("Set ConnectionStrings__Database before starting Findie API.");

try
{
    _ = new NpgsqlConnectionStringBuilder(connectionString);
}
catch (ArgumentException)
{
    throw new InvalidOperationException("ConnectionStrings__Database is invalid.");
}

if (!Uri.TryCreate(builder.Configuration["Ai:BaseUrl"], UriKind.Absolute, out var aiBaseUrl)
    || (aiBaseUrl.Scheme != Uri.UriSchemeHttp && aiBaseUrl.Scheme != Uri.UriSchemeHttps)
    || !string.IsNullOrEmpty(aiBaseUrl.UserInfo)
    || !string.IsNullOrEmpty(aiBaseUrl.Query)
    || !string.IsNullOrEmpty(aiBaseUrl.Fragment))
    throw new InvalidOperationException("Ai__BaseUrl must be an absolute HTTP(S) URL without credentials, query or fragment.");

var serviceToken = builder.Configuration["Ai:ServiceToken"];
if (string.IsNullOrWhiteSpace(serviceToken) || serviceToken.Any(char.IsControl))
    throw new InvalidOperationException("Set Ai__ServiceToken to a nonblank service token without control characters.");

if (!int.TryParse(builder.Configuration["Ai:TimeoutSeconds"], out var aiTimeout) || aiTimeout is < 1 or > 120)
    throw new InvalidOperationException("Ai__TimeoutSeconds must be between 1 and 120.");

builder.Services.AddSingleton(_ => NpgsqlDataSource.Create(connectionString));
builder.Services.AddDbContext<FindieDbContext>((services, options) =>
    options.UseNpgsql(services.GetRequiredService<NpgsqlDataSource>()));
builder.Services.AddIdentityCore<ApplicationUser>(options => options.User.RequireUniqueEmail = true)
    .AddRoles<IdentityRole<Guid>>()
    .AddEntityFrameworkStores<FindieDbContext>()
    .AddSignInManager<ApplicationSignInManager>();
builder.Services.AddAuthentication(IdentityConstants.ApplicationScheme).AddIdentityCookies();
builder.Services.Configure<SecurityStampValidatorOptions>(options => options.OnRefreshingPrincipal = context =>
{
    // Identity rebuilds the principal during stamp checks and drops the original sign-in method.
    if (context.CurrentPrincipal?.FindFirst(ClaimTypes.AuthenticationMethod) is { Value: GoogleDefaults.AuthenticationScheme } method
        && context.NewPrincipal?.Identity is ClaimsIdentity identity)
        identity.AddClaim(method);
    return Task.CompletedTask;
});
var googleClientId = builder.Configuration["Authentication:Google:ClientId"];
var googleClientSecret = builder.Configuration["Authentication:Google:ClientSecret"];
var googleConfigured = !string.IsNullOrWhiteSpace(googleClientId) && !string.IsNullOrWhiteSpace(googleClientSecret);
var cookieSecurity = builder.Environment.IsDevelopment() ? CookieSecurePolicy.SameAsRequest : CookieSecurePolicy.Always;
if (googleConfigured)
    builder.Services.AddAuthentication().AddGoogle(options =>
    {
        options.ClientId = googleClientId!;
        options.ClientSecret = googleClientSecret!;
        options.SignInScheme = IdentityConstants.ExternalScheme;
        options.CallbackPath = "/api/auth/google/signin";
        options.SaveTokens = false;
        options.ClaimActions.MapJsonKey("urn:google:email_verified", "email_verified");
        options.CorrelationCookie.SameSite = SameSiteMode.Lax;
        options.CorrelationCookie.SecurePolicy = cookieSecurity;
        options.Events.OnRemoteFailure = async context =>
        {
            context.HandleResponse();
            await Results.Problem(statusCode: 401, title: "Google authentication failed.").ExecuteAsync(context.HttpContext);
        };
    });
builder.Services.ConfigureExternalCookie(options =>
{
    options.Cookie.HttpOnly = true;
    options.Cookie.SecurePolicy = cookieSecurity;
    options.Cookie.SameSite = SameSiteMode.Lax;
});
builder.Services.ConfigureApplicationCookie(options =>
{
    options.Cookie.Name = "Findie.GoogleSession";
    options.Cookie.HttpOnly = true;
    options.Cookie.SecurePolicy = cookieSecurity;
    options.Cookie.SameSite = SameSiteMode.Lax;
    options.Events.OnRedirectToLogin = context =>
    {
        context.Response.StatusCode = StatusCodes.Status401Unauthorized;
        return Task.CompletedTask;
    };
    options.Events.OnRedirectToAccessDenied = context =>
    {
        context.Response.StatusCode = StatusCodes.Status403Forbidden;
        return Task.CompletedTask;
    };
});
builder.Services.AddAntiforgery(options =>
{
    options.HeaderName = "X-CSRF-TOKEN";
    options.SuppressReadingTokenFromFormBody = true;
    options.Cookie.SecurePolicy = cookieSecurity;
});
var adminEmailsConfig = builder.Configuration["AdminEmails"]
    ?? builder.Configuration["ADMIN_EMAILS"]
    ?? builder.Configuration["Admin:Emails"];
builder.Services.AddSingleton(new AdminOptions(adminEmailsConfig));
builder.Services.AddAuthorization(options =>
{
    options.DefaultPolicy = new AuthorizationPolicyBuilder()
        .RequireAuthenticatedUser().AddRequirements(new ActiveUserRequirement()).Build();
    options.AddPolicy("AdminOnly", policy =>
        policy.RequireAuthenticatedUser().AddRequirements(new ActiveUserRequirement(), new AdminUserRequirement()));
});
builder.Services.AddScoped<IAuthorizationHandler, ActiveUserHandler>();
builder.Services.AddScoped<IAuthorizationHandler, AdminUserHandler>();
builder.Services.AddScoped<IUserRepository, UserRepository>();
builder.Services.AddScoped<IUserService, UserService>();
builder.Services.AddScoped<IReceptionPointRepository, ReceptionPointRepository>();
builder.Services.AddScoped<IReceptionPointService, ReceptionPointService>();
builder.Services.AddScoped<IGoogleAuthService, GoogleAuthService>();
builder.Services.AddScoped<IRecoveryRepository, RecoveryRepository>();
builder.Services.AddScoped<RecoveryWorkflow>();
builder.Services.AddScoped<IItemService, ItemService>();
builder.Services.AddScoped<IClaimService, ClaimService>();
builder.Services.AddScoped<IConversationService, ConversationService>();
builder.Services.AddScoped<IIntakeService, IntakeService>();
builder.Services.AddScoped<IImageService, ImageService>();
builder.Services.AddScoped<ISearchService, SearchService>();
builder.Services.AddScoped<SavedSearchService>();
builder.Services.AddScoped<SavedSearchMaintenance>();
if (!string.IsNullOrWhiteSpace(builder.Configuration["RabbitMq:Uri"]))
    builder.Services.AddHostedService<SavedSearchMaintenance>();
builder.Services.AddScoped<SearchMaterialsService>();
builder.Services.AddSingleton<RabbitMqGateway>();
builder.Services.AddSingleton<IAiGateway>(services => services.GetRequiredService<RabbitMqGateway>());
builder.Services.AddHostedService(services => services.GetRequiredService<RabbitMqGateway>());
builder.Services.AddSingleton<IProcessedStorage, ProcessedStorage>();
builder.Services.AddSingleton<AiJobs>();
if (builder.Configuration.GetValue<bool>("Ai:PrivateHttpImages"))
    builder.Services.AddSingleton<IAiGateway, PrivateImageGateway>();
if (builder.Configuration["DataProtection:KeyPath"] is { Length: > 0 } keyPath)
    builder.Services.AddDataProtection().SetApplicationName("Findie").PersistKeysToFileSystem(new DirectoryInfo(keyPath));
builder.Services.AddScoped<RecoveryMaintenance>();
builder.Services.AddScoped<IndexReceiptService>();
if (!string.IsNullOrWhiteSpace(builder.Configuration["RabbitMq:Uri"]) || !string.IsNullOrWhiteSpace(builder.Configuration["Storage:Endpoint"]))
    builder.Services.AddHostedService<RecoveryMaintenance>();
builder.Services.AddExceptionHandler<ApiExceptionHandler>();
builder.Services.AddRateLimiter(options =>
{
    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    options.AddPolicy("business", context => RateLimitPartition.GetFixedWindowLimiter(
        context.User.FindFirstValue(ClaimTypes.NameIdentifier) ?? context.Connection.RemoteIpAddress?.ToString() ?? "anonymous",
        _ => new FixedWindowRateLimiterOptions { PermitLimit = 120, Window = TimeSpan.FromMinutes(1), QueueLimit = 0 }));
    options.AddPolicy("images", context => RateLimitPartition.GetFixedWindowLimiter(
        context.User.FindFirstValue(ClaimTypes.NameIdentifier) ?? context.Connection.RemoteIpAddress?.ToString() ?? "anonymous",
        _ => new FixedWindowRateLimiterOptions { PermitLimit = 20, Window = TimeSpan.FromMinutes(1), QueueLimit = 0 }));
});
builder.Services.AddControllers();
builder.Services.AddSignalR();
builder.Services.AddProblemDetails();
builder.Services.AddHealthChecks().AddCheck<DatabaseHealthCheck>("database", timeout: TimeSpan.FromSeconds(5));
builder.Services.AddHttpClient("ai", client =>
{
    client.BaseAddress = aiBaseUrl;
    client.Timeout = TimeSpan.FromSeconds(aiTimeout);
    client.DefaultRequestHeaders.Add("X-Service-Token", serviceToken);
}).ConfigurePrimaryHttpMessageHandler(() => new HttpClientHandler { AllowAutoRedirect = false });

builder.Services.AddHsts(options =>
{
    options.Preload = true;
    options.IncludeSubDomains = true;
    options.MaxAge = TimeSpan.FromDays(365);
});

var allowedOrigins = builder.Configuration["Cors:AllowedOrigins"]
    ?.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
    ?? (builder.Environment.IsDevelopment()
        ? ["http://localhost:5173", "http://127.0.0.1:5173"]
        : []);

builder.Services.AddCors(options =>
{
    options.AddPolicy("FindieCors", policy =>
    {
        if (allowedOrigins.Length > 0)
        {
            policy.WithOrigins(allowedOrigins)
                .AllowAnyHeader()
                .AllowAnyMethod()
                .AllowCredentials();
        }
        else
        {
            policy.SetIsOriginAllowed(_ => false);
        }
    });
});

var app = builder.Build();

if (importPublicSamples)
{
    Environment.ExitCode = await LocalPublicSamples.RunAsync(app.Services, args, Console.Out);
    return;
}

var forwardedOptions = new ForwardedHeadersOptions
{
    ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedHost | ForwardedHeaders.XForwardedProto,
    ForwardedProtoHeaderName = builder.Configuration["ForwardedProtoHeaderName"] ?? "X-Forwarded-Proto",
};
forwardedOptions.KnownNetworks.Clear();
forwardedOptions.KnownProxies.Clear();
var configuredForwardedHosts = builder.Configuration["ForwardedHosts"]
    ?.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
if (configuredForwardedHosts is { Length: > 0 })
{
    foreach (var host in configuredForwardedHosts)
    {
        forwardedOptions.AllowedHosts.Add(host);
    }
}
app.UseForwardedHeaders(forwardedOptions);

app.UseExceptionHandler();

app.Use(async (context, next) =>
{
    context.Response.Headers["X-Frame-Options"] = "DENY";
    context.Response.Headers["X-Content-Type-Options"] = "nosniff";
    context.Response.Headers["Referrer-Policy"] = "strict-origin-when-cross-origin";
    context.Response.Headers["X-XSS-Protection"] = "0";
    context.Response.Headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()";
    await next(context);
});

if (!app.Environment.IsDevelopment())
{
    app.UseHsts();
}

app.UseCors("FindieCors");
app.UseDefaultFiles();
app.UseStaticFiles();

app.UseAuthentication();
app.UseAuthorization();
app.UseRateLimiter();
app.Use(async (context, next) =>
{
    if (context.User.Identity?.IsAuthenticated == true
        && !context.Request.Path.StartsWithSegments("/hubs")
        && !HttpMethods.IsGet(context.Request.Method) && !HttpMethods.IsHead(context.Request.Method)
        && !HttpMethods.IsOptions(context.Request.Method))
    {
        try
        {
            await context.RequestServices.GetRequiredService<IAntiforgery>().ValidateRequestAsync(context);
        }
        catch (AntiforgeryValidationException)
        {
            await Results.Problem(statusCode: 400, title: "Invalid CSRF token.").ExecuteAsync(context);
            return;
        }
    }
    await next(context);
});
app.MapGet("/api/auth/csrf", (IAntiforgery antiforgery, HttpContext context) =>
    Results.Ok(new { token = antiforgery.GetAndStoreTokens(context).RequestToken })).RequireAuthorization();
app.MapPost("/api/auth/logout", async (SignInManager<ApplicationUser> signInManager) =>
{
    await signInManager.SignOutAsync();
    return Results.NoContent();
}).RequireAuthorization();
app.MapControllers();
app.MapGet("/api/jobs/{id:guid}", (Guid id, HttpContext context, AiJobs jobs) =>
    jobs.Get(id, Guid.Parse(context.User.FindFirstValue(ClaimTypes.NameIdentifier)!))).RequireAuthorization();
app.MapFallback(async context =>
{
    if (context.Request.Path.StartsWithSegments("/api") || context.Request.Path.StartsWithSegments("/hubs")
        || context.Request.Path.StartsWithSegments("/health") || !HttpMethods.IsGet(context.Request.Method)
        || app.Environment.WebRootPath is null || Path.HasExtension(context.Request.Path))
    { context.Response.StatusCode = 404; return; }
    var index = Path.Combine(app.Environment.WebRootPath, "index.html");
    if (!File.Exists(index)) { context.Response.StatusCode = 404; return; }
    context.Response.ContentType = "text/html; charset=utf-8";
    context.Response.Headers.CacheControl = "no-store";
    await context.Response.SendFileAsync(index);
});
app.MapHub<Findie.Api.Hubs.ChatHub>("/hubs/chat").RequireAuthorization();

app.MapGet("/health/live", () => Results.Ok(new { status = "ok", stage = "scaffold" }));

app.MapGet("/health/ready", async (HealthCheckService healthChecks, CancellationToken cancellationToken) =>
{
    var report = await healthChecks.CheckHealthAsync(cancellationToken);
    var ready = report.Status == HealthStatus.Healthy;
    return Results.Json(new { status = ready ? "ready" : "not_ready", database = ready ? "ready" : "unavailable" },
        statusCode: ready ? StatusCodes.Status200OK : StatusCodes.Status503ServiceUnavailable);
});

app.MapGet("/api/system/status", async (HealthCheckService healthChecks, IHttpClientFactory clients,
    CancellationToken cancellationToken) =>
{
    var databaseCheck = healthChecks.CheckHealthAsync(cancellationToken);
    var ai = "unavailable";
    try
    {
        using var response = await clients.CreateClient("ai").GetAsync("/health/ready", cancellationToken);
        if (response.IsSuccessStatusCode)
            ai = "ready";
    }
    catch (Exception exception) when (exception is HttpRequestException or OperationCanceledException)
    {
        // Dependency failures remain visible as unavailable; no credentials or remote body leave the API.
    }

    var database = (await databaseCheck).Status == HealthStatus.Healthy ? "ready" : "unavailable";
    return Results.Ok(new
    {
        name = "Findie API",
        stage = "scaffold",
        database,
        ai,
        features = new { business = true, authentication = googleConfigured,
            storage = app.Services.GetRequiredService<IProcessedStorage>().Configured }
    });
});

app.Run();

public partial class Program;
