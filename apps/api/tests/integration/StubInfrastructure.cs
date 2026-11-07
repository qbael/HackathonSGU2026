using System.Text.Json;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Services;

sealed class StubAiGateway : IAiGateway
{
    public bool Ready => true;
    public int Calls { get; private set; }
    public Func<AiCommand, Task<AiReply>> Handler { get; set; } = _ => throw new ApiException(503, "AI test unavailable.");
    public Task<AiReply> RequestAsync(AiCommand command, CancellationToken ct) { Calls++; return Handler(command); }
    public static Dictionary<string, object?> ReplyMetadata(AiCommand command) => command.Metadata.EnumerateObject()
        .ToDictionary(property => property.Name, property => (object?)property.Value.Clone())
        .Concat(new Dictionary<string, object?> { ["kind"] = command.Kind, ["succeeded"] = true })
        .ToDictionary(property => property.Key, property => property.Value);
}

sealed class StubStorage : IProcessedStorage
{
    public bool Configured => true;
    public string Bucket => "private-test-output";
    public Dictionary<Guid, byte[]> Objects { get; } = [];
    public bool FailPut { get; set; }
    public bool FailDelete { get; set; }
    public bool CorruptRead { get; set; }
    public Func<Task>? OnRead { get; set; }
    public int Puts { get; private set; }
    public Task PutAsync(StoredObject value, byte[] bytes, CancellationToken ct)
    {
        if (FailPut) throw new ApiException(503, "Test storage unavailable.");
        if (value.ObjectKind != "processed" || !value.ObjectKey.StartsWith("processed/")) throw new InvalidOperationException("Unexpected non-output storage.");
        Puts++; Objects[value.Id] = bytes.ToArray(); return Task.CompletedTask;
    }
    public async Task<byte[]> ReadAsync(StoredObject value, CancellationToken ct)
    {
        if (OnRead is not null) await OnRead();
        return CorruptRead ? new byte[] { 0 } : Objects[value.Id].ToArray();
    }
    public Task DeleteAsync(StoredObject value, CancellationToken ct)
    {
        if (FailDelete) throw new ApiException(503, "Test delete unavailable.");
        Objects.Remove(value.Id); return Task.CompletedTask;
    }
}
