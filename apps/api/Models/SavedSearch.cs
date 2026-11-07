namespace Findie.Api.Models;

public sealed class SavedSearch
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public Guid UserId { get; set; }
    public ApplicationUser User { get; set; } = null!;
    public string? Text { get; set; }
    public string? Area { get; set; }
    public DateOnly? From { get; set; }
    public DateOnly? Until { get; set; }
    public DateTimeOffset? LostAt { get; set; }
    public string ImageEmbeddings { get; set; } = "[]";
    public string ModelId { get; set; } = string.Empty;
    public string ModelRevision { get; set; } = string.Empty;
    public int Dimensions { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset NextCheckAt { get; set; } = DateTimeOffset.UtcNow;
    public Guid? AfterItemId { get; set; }
    public DateTimeOffset? LastCheckedAt { get; set; }
    public bool NeedsRefresh { get; set; }
    public Guid? LeaseToken { get; set; }
    public DateTimeOffset? LeaseUntil { get; set; }
    public List<SavedSearchMatch> Matches { get; set; } = [];
}

public sealed class SavedSearchMatch
{
    public Guid SavedSearchId { get; set; }
    public SavedSearch SavedSearch { get; set; } = null!;
    public Guid ItemId { get; set; }
    public Item Item { get; set; } = null!;
    public long DocumentVersion { get; set; }
    public double Score { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? ReadAt { get; set; }
}
