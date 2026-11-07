namespace Findie.Api.Models;

public sealed class ItemImage
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid ItemId { get; set; }
    public short Position { get; set; }
    public Guid? ProcessedObjectId { get; set; }
    public long ContentVersion { get; set; } = 1;
    public string ProcessingState { get; set; } = "pending";
    public string ReviewState { get; set; } = "pending";
    public string? SensitiveRegions { get; set; }
    public string? OriginalEmbedding { get; set; }
    public string? RedactionModelId { get; set; }
    public string? RedactionModelRevision { get; set; }
    public string? RedactionProfile { get; set; }
    public Guid? ReviewedBy { get; set; }
    public DateTimeOffset? ReviewedAt { get; set; }
    public string? FailureCode { get; set; }
    public DateTimeOffset? RetiredAt { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public Item Item { get; set; } = null!;
    public StoredObject? ProcessedObject { get; set; }
    public ApplicationUser? Reviewer { get; set; }
}
