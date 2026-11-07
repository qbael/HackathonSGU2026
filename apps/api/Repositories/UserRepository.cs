using Findie.Api.Contracts;
using Findie.Api.Data;
using Findie.Api.Models;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Repositories;

public sealed class UserRepository(FindieDbContext database, UserManager<ApplicationUser> users) : IUserRepository
{
    public Task<ApplicationUser?> GetByIdAsync(Guid id, CancellationToken cancellationToken) =>
        database.Users.SingleOrDefaultAsync(user => user.Id == id, cancellationToken);

    public Task<IdentityResult> UpdateAsync(ApplicationUser user) => users.UpdateAsync(user);

    public Task<List<ManagedPointSummary>> ListManagedPointsAsync(Guid userId, CancellationToken cancellationToken) =>
        database.PointStaff.AsNoTracking()
            .Where(staff => staff.UserId == userId && staff.RevokedAt == null && staff.Point.Active)
            .OrderBy(staff => staff.Point.Name).ThenBy(staff => staff.PointId)
            .Select(staff => new ManagedPointSummary(staff.PointId, staff.Point.Name))
            .ToListAsync(cancellationToken);

    public Task<ApplicationUser?> FindByLoginAsync(string provider, string providerKey) =>
        users.FindByLoginAsync(provider, providerKey);

    public async Task<IdentityResult> CreateWithLoginAsync(ApplicationUser user, UserLoginInfo login)
    {
        await using var transaction = await database.Database.BeginTransactionAsync();
        var result = await users.CreateAsync(user);
        if (!result.Succeeded)
            return result;

        result = await users.AddLoginAsync(user, login);
        if (result.Succeeded)
            await transaction.CommitAsync();
        return result;
    }
}
