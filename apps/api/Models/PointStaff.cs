namespace Findie.Api.Models;

public sealed class PointStaff
{
    public Guid PointId { get; set; }
    public Guid UserId { get; set; }
    public bool CanReceive { get; set; }
    public bool CanReturn { get; set; }
    public DateTimeOffset AssignedAt { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? RevokedAt { get; set; }
    public ReceptionPoint Point { get; set; } = null!;
    public ApplicationUser User { get; set; } = null!;
}
