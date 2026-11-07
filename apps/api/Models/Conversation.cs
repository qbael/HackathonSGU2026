namespace Findie.Api.Models;

public sealed class Conversation
{
    public Guid ClaimId { get; set; }
    public string ApprovalStatus { get; set; } = "approved";
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public Claim Claim { get; set; } = null!;
    public ICollection<Message> Messages { get; set; } = [];
}
