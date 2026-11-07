namespace Findie.Api.Models;

public sealed class IntakeRequest
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid ItemId { get; set; }
    public Guid RequestedBy { get; set; }
    public Guid TargetPointId { get; set; }
    public long SourceCustodyVersion { get; set; }
    public string Status { get; set; } = "pending";
    public Guid? DecidedBy { get; set; }
    public DateTimeOffset? DecidedAt { get; set; }
    public string? DecisionNote { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public Item Item { get; set; } = null!;
    public ApplicationUser Requester { get; set; } = null!;
    public ReceptionPoint TargetPoint { get; set; } = null!;
    public ApplicationUser? Decider { get; set; }
}
