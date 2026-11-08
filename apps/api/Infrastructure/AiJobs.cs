using System.Collections.Concurrent;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc;

namespace Findie.Api.Infrastructure;

// shortcut: jobs live on one instance and disappear on restart; re-upload then, use durable safe results before scaling out.
public sealed class AiJobs(IServiceScopeFactory scopes, IHostApplicationLifetime lifetime)
{
    sealed class Job(Guid actor)
    {
        public Guid Actor { get; } = actor;
        public DateTimeOffset Expires { get; } = DateTimeOffset.UtcNow.AddMinutes(35);
        public Task<IResult> Result { get; set; } = null!;
    }
    readonly ConcurrentDictionary<Guid, Job> jobs = new();
    readonly SemaphoreSlim capacity = new(4, 4);
    public bool Enabled(IConfiguration configuration) => configuration.GetValue<bool>("Ai:AsyncJobs");
    public async Task<AcceptedResult> UploadAsync(Guid actor, HttpRequest request,
        Func<IServiceProvider, Stream, CancellationToken, Task<object>> operation, CancellationToken ct, int maxBytes = BoundedImage.MaxBytes)
    {
        var bytes = await BoundedImage.ReadAsync(request.Body, request.ContentLength, ct, maxBytes);
        try
        {
            return Start(actor, async (services, token) =>
            {
                try { using var stream = new MemoryStream(bytes, writable: false); return await operation(services, stream, token); }
                finally { Array.Clear(bytes); }
            });
        }
        catch { Array.Clear(bytes); throw; }
    }
    public AcceptedResult Start(Guid actor, Func<IServiceProvider, CancellationToken, Task<object>> operation)
    {
        foreach (var pair in jobs)
            if (pair.Value.Expires < DateTimeOffset.UtcNow && pair.Value.Result.IsCompleted) jobs.TryRemove(pair.Key, out _);
        if (jobs.Count >= 128 || !capacity.Wait(0)) throw new ApiException(503, "AI request capacity is exhausted; retry shortly.");
        var id = Guid.NewGuid();
        var job = new Job(actor);
        job.Result = Task.Run(async () =>
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(lifetime.ApplicationStopping);
            timeout.CancelAfter(TimeSpan.FromMinutes(30));
            using var scope = scopes.CreateScope();
            try { return Results.Ok(await operation(scope.ServiceProvider, timeout.Token)); }
            catch (ApiException error) { return Results.Problem(statusCode: error.StatusCode, title: error.Message); }
            catch { return Results.Problem(statusCode: 503, title: "Processing interrupted; upload again to retry."); }
            finally { capacity.Release(); }
        });
        jobs[id] = job;
        return new AcceptedResult($"/api/jobs/{id}", new { status = "processing" });
    }
    static IResult Pending(Guid id) => Results.Accepted($"/api/jobs/{id}", new { status = "processing" });
    public IResult Get(Guid id, Guid actor)
    {
        if (!jobs.TryGetValue(id, out var job) || job.Actor != actor || job.Expires < DateTimeOffset.UtcNow)
            return Results.NotFound();
        return job.Result.IsCompletedSuccessfully ? job.Result.Result : Pending(id);
    }
}
