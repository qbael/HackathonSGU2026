namespace Findie.Api.Models;

public sealed class StoredObject
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid OwnerUserId { get; set; }
    public string Bucket { get; set; } = string.Empty;
    public string ObjectKey { get; set; } = string.Empty;
    public string ObjectKind { get; set; } = "processed";
    public string ObjectState { get; set; } = "reserved";
    public string? Sha256 { get; set; }
    public string? ContentType { get; set; }
    public long? ByteSize { get; set; }
    public int? Width { get; set; }
    public int? Height { get; set; }
    public DateTimeOffset? ExpiresAt { get; set; }
    public DateTimeOffset? CleanupNextAt { get; set; }
    public int CleanupAttempts { get; set; }
    public string? LastErrorCode { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? ValidatedAt { get; set; }
    public DateTimeOffset? DeletedAt { get; set; }
    public ApplicationUser Owner { get; set; } = null!;
}
