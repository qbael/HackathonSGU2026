using Findie.Api.Infrastructure;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

static class AiJobChecks
{
    sealed class Lifetime : IHostApplicationLifetime
    {
        public CancellationToken ApplicationStarted => CancellationToken.None;
        public CancellationToken ApplicationStopping => CancellationToken.None;
        public CancellationToken ApplicationStopped => CancellationToken.None;
        public void StopApplication() { }
    }
    public static async Task RunAsync()
    {
        using var services = new ServiceCollection().BuildServiceProvider();
        var jobs = new AiJobs(services.GetRequiredService<IServiceScopeFactory>(), new Lifetime());
        var actor = Guid.NewGuid();
        var finish = new TaskCompletionSource<object>(TaskCreationOptions.RunContinuationsAsynchronously);
        var accepted = jobs.Start(actor, (_, _) => finish.Task);
        var id = Guid.Parse(accepted.Location!.Split('/').Last());
        if (((IStatusCodeHttpResult)jobs.Get(id, actor)).StatusCode != 202
            || ((IStatusCodeHttpResult)jobs.Get(id, Guid.NewGuid())).StatusCode != 404)
            throw new Exception("AI jobs must isolate actors and return a pending response.");
        finish.SetResult(new { safe = true });
        for (var count = 0; count < 100 && ((IStatusCodeHttpResult)jobs.Get(id, actor)).StatusCode == 202; count++)
            await Task.Delay(5);
        if (((IStatusCodeHttpResult)jobs.Get(id, actor)).StatusCode != 200)
            throw new Exception("AI job did not return the completed safe result.");
        var blocked = new TaskCompletionSource<object>(TaskCreationOptions.RunContinuationsAsynchronously);
        for (var count = 0; count < 4; count++) jobs.Start(actor, (_, _) => blocked.Task);
        try { jobs.Start(actor, (_, _) => blocked.Task); throw new Exception("Unbounded AI jobs."); }
        catch (Findie.Api.Services.ApiException error) when (error.StatusCode == 503) { }
        blocked.SetResult(new { safe = true });
        Console.WriteLine("PASS: AI job actor isolation, pending/completed state and capacity limit");
    }
}
