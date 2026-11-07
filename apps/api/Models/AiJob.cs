namespace Findie.Api.Models;

public sealed class AiJob
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid ItemId { get; set; }
    public Guid? ImageId { get; set; }
    public string JobKind { get; set; } = string.Empty;
    public long SourceVersion { get; set; }
    public string SourceSha256 { get; set; } = string.Empty;
    public string ModelId { get; set; } = string.Empty;
    public string ModelRevision { get; set; } = string.Empty;
    public string ProcessingProfile { get; set; } = string.Empty;
    public string Status { get; set; } = "pending";
    public int Attempts { get; set; }
    public int MaxAttempts { get; set; }
    public DateTimeOffset NextAttemptAt { get; set; } = DateTimeOffset.UtcNow;
    public Guid? LeaseToken { get; set; }
    public DateTimeOffset? LeaseUntil { get; set; }
    public string? LastErrorCode { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? FinishedAt { get; set; }
    public Item Item { get; set; } = null!;
    public ItemImage? Image { get; set; }
}
