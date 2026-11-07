using Findie.Api.Models;

namespace Findie.Api.Repositories;

public interface IReceptionPointRepository
{
    Task<List<ReceptionPoint>> ListActiveAsync(CancellationToken cancellationToken);
    Task<ReceptionPoint?> GetActiveAsync(Guid id, CancellationToken cancellationToken);
}
