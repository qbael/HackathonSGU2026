namespace Findie.Api.Contracts;

public sealed record SavedSearchMatchResponse(Guid ItemId, string Title, string FoundArea, double Score,
    DateTimeOffset CreatedAt, DateTimeOffset? ReadAt);
public sealed record SavedSearchResponse(Guid Id, string? Text, int ImageCount, string? Area, DateOnly? From, DateOnly? Until,
    DateTimeOffset? LostAt, DateTimeOffset CreatedAt, DateTimeOffset? LastCheckedAt, bool NeedsRefresh,
    IReadOnlyList<SavedSearchMatchResponse> Matches);
