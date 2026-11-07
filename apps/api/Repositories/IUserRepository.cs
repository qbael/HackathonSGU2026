using Findie.Api.Contracts;
using Findie.Api.Models;
using Microsoft.AspNetCore.Identity;

namespace Findie.Api.Repositories;

public interface IUserRepository
{
    Task<ApplicationUser?> GetByIdAsync(Guid id, CancellationToken cancellationToken);
    Task<IdentityResult> UpdateAsync(ApplicationUser user);
    Task<ApplicationUser?> FindByLoginAsync(string provider, string providerKey);
    Task<IdentityResult> CreateWithLoginAsync(ApplicationUser user, UserLoginInfo login);
    Task<List<ManagedPointSummary>> ListManagedPointsAsync(Guid userId, CancellationToken cancellationToken);
}
