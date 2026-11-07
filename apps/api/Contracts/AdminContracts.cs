using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record AdminOverviewResponse(
    int TotalItems,
    int ActiveItems,
    int ReturnedItems,
    int HiddenItems,
    int TotalUsers,
    int ActiveUsers,
    int DisabledUsers,
    int TotalHubs,
    int ActiveHubs,
    int TotalCustodyEvents,
    int TotalHandovers
);

public sealed record AdminUserResponse(
    Guid Id,
    string? Email,
    string DisplayName,
    DateTimeOffset CreatedAt,
    DateTimeOffset? DisabledAt,
    bool IsAdmin,
    int ItemsCount
);

public sealed class AdminUserFilter
{
    [StringLength(200)] public string? Query { get; set; }
    [Range(1, 10000)] public int Page { get; set; } = 1;
    [Range(1, 100)] public int PageSize { get; set; } = 20;
}

public sealed record AdminItemImageSummary(
    Guid Id,
    short Position,
    long ContentVersion,
    string ProcessingState,
    string ReviewState,
    string? FailureCode,
    DateTimeOffset? RetiredAt,
    string PreviewUrl,
    string? RedactionModelId,
    string? RedactionProfile
);

public sealed record AdminItemResponse(
    Guid Id,
    string Title,
    string PublicDescription,
    string FoundArea,
    string FoundTimePrecision,
    DateOnly? FoundOn,
    DateTimeOffset? FoundFrom,
    DateTimeOffset? FoundUntil,
    string Lifecycle,
    string PublicationState,
    long RowVersion,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt,
    Guid AuthorId,
    string AuthorDisplayName,
    string? AuthorEmail,
    string CustodyKind,
    Guid? HolderPointId,
    string? HolderPointName,
    IReadOnlyList<AdminItemImageSummary> Images
);

public sealed class AdminItemFilter
{
    [StringLength(200)] public string? Query { get; set; }
    [RegularExpression("^(active|returned|deleted)$")] public string? Lifecycle { get; set; }
    [RegularExpression("^(draft|published|hidden)$")] public string? PublicationState { get; set; }
    [Range(1, 10000)] public int Page { get; set; } = 1;
    [Range(1, 100)] public int PageSize { get; set; } = 20;
}

public sealed record SetPublicationRequest(
    [Required, RegularExpression("^(published|hidden)$")] string PublicationState
);

public sealed record AdminPointResponse(
    Guid Id,
    string Name,
    string PublicAddress,
    string? Directions,
    bool Active,
    DateTimeOffset CreatedAt,
    int StaffCount,
    int ItemsCount
);

public sealed record CreatePointRequest(
    [Required, StringLength(200, MinimumLength = 1)] string Name,
    [Required, StringLength(500, MinimumLength = 1)] string PublicAddress,
    [StringLength(2000)] string? Directions
);

public sealed record AdminStaffResponse(
    Guid PointId,
    Guid UserId,
    string? Email,
    string DisplayName,
    bool CanReceive,
    bool CanReturn,
    DateTimeOffset AssignedAt,
    DateTimeOffset? RevokedAt
);

public sealed record AssignStaffRequest(
    [Required, EmailAddress] string UserEmail,
    bool CanReceive,
    bool CanReturn
);
