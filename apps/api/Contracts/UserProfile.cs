using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record ManagedPointSummary(Guid Id, string Name);

public sealed record UserProfile(
    Guid Id,
    string? Email,
    string DisplayName,
    DateTimeOffset CreatedAt,
    bool IsAdmin = false,
    bool IsStaff = false,
    IReadOnlyList<ManagedPointSummary>? ManagedPoints = null);

public sealed record UpdateUserRequest([Required, StringLength(120)] string DisplayName);
