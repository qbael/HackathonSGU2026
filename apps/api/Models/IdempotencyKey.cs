namespace Findie.Api.Models;

public sealed class IdempotencyKey
{
    public Guid ActorUserId { get; set; }
    public Guid IdempotencyKeyValue { get; set; }
    public string Operation { get; set; } = string.Empty;
    public string RequestSha256 { get; set; } = string.Empty;
    public string ResourceType { get; set; } = string.Empty;
    public Guid ResourceId { get; set; }
    public short ResponseStatus { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public ApplicationUser Actor { get; set; } = null!;
}
