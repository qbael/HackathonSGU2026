using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Findie.Api.Contracts;
using Findie.Api.Data;
using Findie.Api.Infrastructure;
using Findie.Api.Repositories;
using Findie.Api.Services;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

static class CrossServiceChecks
{
    public static async Task RunAsync(WebApplicationFactory<FindieDbContext> factory)
    {
        var scopes = factory.Services.GetRequiredService<IServiceScopeFactory>();
        var configuration = new ConfigurationBuilder().AddConfiguration(factory.Services.GetRequiredService<IConfiguration>())
            .AddInMemoryCollection(new Dictionary<string, string?> { ["RabbitMq:Uri"] = Environment.GetEnvironmentVariable("FINDIE_TEST_BROKER_URI") }).Build();
        using var gateway = new RabbitMqGateway(configuration, NullLogger<RabbitMqGateway>.Instance, scopes);
        var storage = new StubStorage();
        using var maintenance = new RecoveryMaintenance(scopes, gateway, storage, configuration, NullLogger<RecoveryMaintenance>.Instance);
        var raw = Convert.FromBase64String(Environment.GetEnvironmentVariable("FINDIE_TEST_IMAGE_BASE64")!);
        var actor = await InScope(async services =>
        {
            var db = services.GetRequiredService<FindieDbContext>();
            // Other suites deliberately leave malformed jobs in this disposable fixture.
            await db.IndexOutbox.ExecuteDeleteAsync();
            return (await db.Users.SingleAsync(user => user.NormalizedEmail == "OWNER@EXAMPLE.TEST")).Id;
        });
        await gateway.StartAsync(default);
        try
        {
            var deadline = DateTimeOffset.UtcNow.AddSeconds(20);
            while (!gateway.Ready && DateTimeOffset.UtcNow < deadline) await Task.Delay(50);
            Check(gateway.Ready, ".NET gateway connects to the real Python worker broker");
            await using var httpFactory = factory.WithWebHostBuilder(builder => builder.ConfigureServices(services =>
                services.AddSingleton<IAiGateway>(gateway)));
            using var browser = httpFactory.CreateClient(new WebApplicationFactoryClientOptions
                { AllowAutoRedirect = false, HandleCookies = true, BaseAddress = new Uri("https://localhost") });
            using (var challenge = await browser.GetAsync("/api/auth/google?returnUrl=%2F"))
            {
                Check(challenge.StatusCode == HttpStatusCode.Redirect, "bridge HTTP client starts Google login");
                var state = QueryHelpers.ParseQuery(challenge.Headers.Location!.Query)["state"].ToString();
                using var remote = await browser.GetAsync($"/api/auth/google/signin?code=integration-code&state={Uri.EscapeDataString(state)}");
                Check(remote.StatusCode == HttpStatusCode.Redirect, "bridge HTTP client completes the external callback");
                using var callback = await browser.GetAsync(remote.Headers.Location);
                Check(callback.StatusCode == HttpStatusCode.Redirect, "bridge HTTP client receives its application cookie");
            }
            using (var csrf = await browser.GetAsync("/api/auth/csrf"))
            {
                Check(csrf.IsSuccessStatusCode, "bridge HTTP client obtains CSRF token");
                browser.DefaultRequestHeaders.Add("X-CSRF-TOKEN", (await csrf.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("token").GetString());
            }
            var item = await InScope(services => services.GetRequiredService<IItemService>().CreateAsync(actor, Guid.NewGuid(),
                new CreateItemRequest(new ItemInput("Ví da bridge", "Ví da đen nhặt tại phòng E.205", "Bridge-only Campus", "unknown"),
                    new CustodyInput("person")), default));
            var images = new List<ImageResponse>();
            for (short position = 1; position <= 2; position++)
            {
                var uploaded = await InScope(services => Images(services).UploadAsync(actor, Guid.NewGuid(), item.Id, position,
                    "image/png", new MemoryStream(raw, writable: false), raw.Length, default));
                Check(uploaded.ProcessingState == "needs_review", "Python output waits for human review");
                images.Add(await InScope(services => Images(services).ReviewAsync(actor, Guid.NewGuid(), item.Id, uploaded.Id,
                    new ReviewImageRequest(uploaded.ContentVersion, "approved"), default)));
            }
            Check(storage.Puts == 2 && storage.Objects.Values.All(output => !output.SequenceEqual(raw)
                && !Encoding.UTF8.GetString(output).Contains("BRIDGE-PRIVATE-METADATA", StringComparison.Ordinal)),
                "only normalized/masked Python output reaches the R2 test double");
            item = await Current();
            item = await InScope(services => services.GetRequiredService<IItemService>().PublishAsync(actor, Guid.NewGuid(), item.Id,
                new PublicationRequest(item.RowVersion, "published"), default));
            await Flush(item.Id, item.DocumentVersion);
            var text = await Text();
            var image = await Image();
            Check(text.Items.Count == 1 && text.Items[0].Item.Id == item.Id, "real Python text candidate passes .NET provenance checks");
            Check(image.Items.Count == 1 && image.Items[0].Item.Id == item.Id && image.Items[0].Item.Images.Count == 2,
                "real image vectors retrieve the public item with two approved source versions");
            var combined = await Batch("ví da phòng E.205", 2);
            Check(combined.Mode == "combined" && combined.SearchProfileId == "multimodal-fusion-v1"
                && combined.Items.Count == 1 && combined.Items[0].Item.Id == item.Id,
                "HTTP multipart batches two images and text through real AMQP/Python fusion before .NET validation");
            var imageBatch = await Batch(null, 1);
            Check(imageBatch.Mode == "image" && imageBatch.SearchProfileId == "image-fusion-v1"
                && imageBatch.Items.Count == 1 && imageBatch.Items[0].Item.Id == item.Id,
                "HTTP image-only batch preserves the image fusion contract across services");
            Check(!text.Items[0].Item.CanClaim && !image.Items[0].Item.CanClaim,
                "search results do not allow the poster to claim their own item");
            var outsideArea = await InScope(services => Search(services).TextAsync(actor, new SearchRequest("ví", "Wrong campus"), default));
            Check(outsideArea.Items.Count == 1 && outsideArea.Items[0].Item.Id == item.Id && outsideArea.FiltersRelaxed,
                "cross-service search retains relevant items outside the preferred area");
            await InScope(services => Images(services).RetireAsync(actor, Guid.NewGuid(), item.Id, images[0].Id,
                new RetireImageRequest(images[0].ContentVersion), default));
            item = await Current();
            Check(item.PublicationState == "published" && item.Images.Count == 1, "removing one of two approved images keeps the item public");
            var staleBatch = await Batch("ví da phòng E.205", 2);
            Check(staleBatch.Items.Count == 0 && staleBatch.Partial,
                ".NET rejects fused candidates from the stale search snapshot before the replacement is indexed");
            await Flush(item.Id, item.DocumentVersion);
            Check((await Text()).Items.Count == 1 && (await Image()).Items.Count == 1,
                "replacement snapshot retains text and the remaining approved image");
            await InScope(services => Images(services).RetireAsync(actor, Guid.NewGuid(), item.Id, images[1].Id,
                new RetireImageRequest(images[1].ContentVersion), default));
            Check((await Image()).Items.Count == 0, ".NET removes stale image hits before worker catches up");
            item = await Current();
            Check(item.PublicationState == "hidden" && item.Images.Count == 0, "removing the last approved image hides the item");
            await Flush(item.Id, item.DocumentVersion);
            Check((await Text()).Items.Count == 0 && (await Image()).Items.Count == 0,
                "last-image retirement commits a tombstone removing text and image matches across the real service boundary");
            Console.WriteLine("PASS: .NET -> RabbitMQ -> Python -> Ollama test double -> processed-output R2 double; HTTP multipart fusion, review, full multi-image manifest, search provenance, retirement and tombstone");

            Task<ItemResponse> Current() => InScope(services => services.GetRequiredService<IItemService>().GetAsync(actor, item.Id, default));
            Task<SearchResponse> Text() => InScope(services => Search(services).TextAsync(actor, new SearchRequest("ví da phòng E.205", "Bridge-only Campus"), default));
            Task<SearchResponse> Image() => InScope(services => Search(services).ImageAsync(actor, new ImageSearchFilter { Area = "Bridge-only Campus" },
                "image/png", new MemoryStream(raw, writable: false), raw.Length, default));
            async Task<SearchResponse> Batch(string? description, int count)
            {
                using var content = new MultipartFormDataContent();
                for (var index = 0; index < count; index++)
                {
                    var image = new ByteArrayContent(raw);
                    image.Headers.ContentType = new MediaTypeHeaderValue("image/png");
                    content.Add(image, "images", $"query-{index}.png");
                }
                if (description is not null) content.Add(new StringContent(description), "text");
                using var response = await browser.PostAsync("/api/search/images?area=Bridge-only%20Campus", content);
                Check(response.IsSuccessStatusCode, $"cross-service HTTP multipart search succeeds: {response.StatusCode}");
                return (await response.Content.ReadFromJsonAsync<SearchResponse>())!;
            }
        }
        finally
        {
            Array.Clear(raw);
            await gateway.StopAsync(default);
        }

        async Task Flush(Guid itemId, long version)
        {
            for (var remaining = 20; remaining > 0 && await maintenance.DispatchOneAsync(default); remaining--) { }
            var completed = await InScope(services => services.GetRequiredService<FindieDbContext>().IndexOutbox
                .AnyAsync(job => job.ItemId == itemId && job.DocumentVersion == version && job.Status == "succeeded"));
            Check(completed, "real Python receipt follows complete manifest commit and .NET outbox ACK");
        }
        ImageService Images(IServiceProvider services) => new(services.GetRequiredService<IRecoveryRepository>(),
            services.GetRequiredService<RecoveryWorkflow>(), gateway, storage, configuration);
        SearchService Search(IServiceProvider services) => new(services.GetRequiredService<IRecoveryRepository>(), gateway, configuration,
            services.GetRequiredService<RecoveryWorkflow>());
        async Task<T> InScope<T>(Func<IServiceProvider, Task<T>> operation)
        {
            using var scope = scopes.CreateScope();
            return await operation(scope.ServiceProvider);
        }
    }

    static void Check(bool condition, string description)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + description);
    }
}
