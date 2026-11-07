using Findie.Api.Contracts;

namespace Findie.Api.Services;

public interface IUserService
{
    Task<UserProfile?> GetProfileAsync(Guid userId, CancellationToken cancellationToken);
    Task<UserProfile?> UpdateProfileAsync(Guid userId, UpdateUserRequest request, CancellationToken cancellationToken);
}
