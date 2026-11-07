using Findie.Api.Data;
using Findie.Api.Models;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Repositories;

public sealed class ReceptionPointRepository(FindieDbContext database) : IReceptionPointRepository
{
    // shortcut: lists at most 100 points; add pagination when the directory exceeds this size.
    public Task<List<ReceptionPoint>> ListActiveAsync(CancellationToken cancellationToken) =>
        database.ReceptionPoints.AsNoTracking().Where(point => point.Active)
            .OrderBy(point => point.Name).ThenBy(point => point.Id).Take(100).ToListAsync(cancellationToken);

    public Task<ReceptionPoint?> GetActiveAsync(Guid id, CancellationToken cancellationToken) =>
        database.ReceptionPoints.AsNoTracking().SingleOrDefaultAsync(point => point.Id == id && point.Active, cancellationToken);
}
