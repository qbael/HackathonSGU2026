namespace Findie.Api.Models;

public sealed class Item
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid PostedBy { get; set; }
    public string Title { get; set; } = string.Empty;
    public string PublicDescription { get; set; } = string.Empty;
    public string FoundArea { get; set; } = string.Empty;
    public string FoundTimePrecision { get; set; } = "unknown";
    public DateOnly? FoundOn { get; set; }
    public DateTimeOffset? FoundFrom { get; set; }
    public DateTimeOffset? FoundUntil { get; set; }
    public string FoundTimezone { get; set; } = "Asia/Ho_Chi_Minh";
    public string CustodyKind { get; set; } = "person";
    public Guid? HolderUserId { get; set; }
    public Guid? HolderPointId { get; set; }
    public string? ExternalName { get; set; }
    public string? ExternalPublicAddress { get; set; }
    public string? ExternalInstructions { get; set; }
    public string Lifecycle { get; set; } = "active";
    public string PublicationState { get; set; } = "draft";
    public long ContentVersion { get; set; } = 1;
    public long CustodyVersion { get; set; } = 1;
    public long RowVersion { get; set; } = 1;
    public long DocumentVersion { get; set; } = 1;
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset UpdatedAt { get; set; } = DateTimeOffset.UtcNow;
    public ApplicationUser Author { get; set; } = null!;
    public ApplicationUser? HolderUser { get; set; }
    public ReceptionPoint? HolderPoint { get; set; }
    public ICollection<ItemImage> Images { get; set; } = [];
    public ICollection<VerificationQuestion> VerificationQuestions { get; set; } = [];
    public ICollection<Claim> Claims { get; set; } = [];
    public ICollection<IntakeRequest> IntakeRequests { get; set; } = [];
    public ICollection<CustodyEvent> CustodyEvents { get; set; } = [];
}
