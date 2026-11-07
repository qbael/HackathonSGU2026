namespace Findie.Api.Models;

public sealed class IndexOutbox
{
    public Guid Id { get; set; } = Guid.NewGuid();
    // A tombstone must survive deletion of its source item, so ItemId has no foreign key.
    public Guid ItemId { get; set; }
    public long DocumentVersion { get; set; }
    public string EventKind { get; set; } = string.Empty;
    public string Payload { get; set; } = string.Empty;
    public string PayloadSha256 { get; set; } = string.Empty;
    public string Status { get; set; } = "pending";
    public int Attempts { get; set; }
    public int MaxAttempts { get; set; }
    public DateTimeOffset NextAttemptAt { get; set; } = DateTimeOffset.UtcNow;
    public Guid? LeaseToken { get; set; }
    public DateTimeOffset? LeaseUntil { get; set; }
    public string? LastErrorCode { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? FinishedAt { get; set; }
}
