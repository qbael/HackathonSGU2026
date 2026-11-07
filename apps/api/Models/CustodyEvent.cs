namespace Findie.Api.Models;

public sealed class CustodyEvent
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid ItemId { get; set; }
    public string EventKind { get; set; } = string.Empty;
    public long CustodyVersion { get; set; }
    public Guid ActorUserId { get; set; }
    public Guid? IntakeRequestId { get; set; }
    public Guid? ClaimId { get; set; }
    public Guid? RecipientUserId { get; set; }
    public string? FromCustody { get; set; }
    public string? ToCustody { get; set; }
    public string? VerificationNote { get; set; }
    public DateTimeOffset OccurredAt { get; set; }
    public DateTimeOffset RecordedAt { get; set; } = DateTimeOffset.UtcNow;
    public Item Item { get; set; } = null!;
    public ApplicationUser Actor { get; set; } = null!;
    public IntakeRequest? IntakeRequest { get; set; }
    public Claim? Claim { get; set; }
    public ApplicationUser? Recipient { get; set; }
}
