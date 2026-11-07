namespace Findie.Api.Models;

public sealed class Claim
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid ItemId { get; set; }
    public Guid ClaimantUserId { get; set; }
    public Guid ReviewerUserId { get; set; }
    public long SourceCustodyVersion { get; set; }
    public string Status { get; set; } = "pending";
    public Guid? DecidedBy { get; set; }
    public DateTimeOffset? DecidedAt { get; set; }
    public string? DecisionNote { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public Item Item { get; set; } = null!;
    public ApplicationUser Claimant { get; set; } = null!;
    public ApplicationUser Reviewer { get; set; } = null!;
    public ApplicationUser? Decider { get; set; }
    public ICollection<ClaimAnswer> Answers { get; set; } = [];
    public Conversation? Conversation { get; set; }
}
