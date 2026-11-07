namespace Findie.Api.Models;

public sealed class ReceptionPoint
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string Name { get; set; } = string.Empty;
    public string PublicAddress { get; set; } = string.Empty;
    public string? Directions { get; set; }
    public bool Active { get; set; } = true;
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public ICollection<PointStaff> Staff { get; set; } = [];
}
