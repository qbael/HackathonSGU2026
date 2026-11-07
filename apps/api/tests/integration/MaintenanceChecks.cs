using Findie.Api.Infrastructure;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

static class MaintenanceChecks
{
    public static async Task RunAsync()
    {
        using var stopping = new CancellationTokenSource();
        var clock = new CleanupClock(stopping);
        var scopes = new FailingScopes(clock);
        var configuration = new ConfigurationBuilder().Build();
        using var ai = new RabbitMqGateway(configuration, NullLogger<RabbitMqGateway>.Instance, scopes);
        using var worker = new RecoveryMaintenance(scopes, ai, new StubStorage(), configuration,
            NullLogger<RecoveryMaintenance>.Instance, clock);
        await worker.StartAsync(stopping.Token);
        try { await worker.ExecuteTask!.WaitAsync(TimeSpan.FromSeconds(15)); }
        catch (OperationCanceledException) when (stopping.IsCancellationRequested) { }
        if (clock.Reads != 4 || !scopes.Attempts.SequenceEqual(new[] { 1, 3 }))
            throw new InvalidOperationException("FAIL: cleanup runs immediately and at ten minutes, including after failure.");
        Console.WriteLine("PASS: cleanup runs immediately, skips before ten minutes, and retries at ten minutes after failure");
    }

    sealed class CleanupClock(CancellationTokenSource stopping) : TimeProvider
    {
        readonly int[] seconds = [0, 599, 600, 601];
        public int Reads { get; private set; }
        public override DateTimeOffset GetUtcNow()
        {
            var elapsed = seconds[Reads++];
            if (Reads == seconds.Length) stopping.Cancel();
            return DateTimeOffset.UnixEpoch.AddSeconds(elapsed);
        }
    }

    sealed class FailingScopes(CleanupClock clock) : IServiceScopeFactory
    {
        public List<int> Attempts { get; } = [];
        public IServiceScope CreateScope()
        {
            Attempts.Add(clock.Reads);
            throw new InvalidOperationException("Simulated database failure.");
        }
    }
}
