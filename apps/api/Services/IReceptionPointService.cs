using Findie.Api.Contracts;

namespace Findie.Api.Services;

public interface IReceptionPointService
{
    Task<IReadOnlyList<ReceptionPointResponse>> ListAsync(CancellationToken cancellationToken);
    Task<ReceptionPointResponse?> GetAsync(Guid id, CancellationToken cancellationToken);
}
