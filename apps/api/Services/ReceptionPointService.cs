using Findie.Api.Contracts;
using Findie.Api.Models;
using Findie.Api.Repositories;

namespace Findie.Api.Services;

public sealed class ReceptionPointService(IReceptionPointRepository points) : IReceptionPointService
{
    public async Task<IReadOnlyList<ReceptionPointResponse>> ListAsync(CancellationToken cancellationToken) =>
        (await points.ListActiveAsync(cancellationToken)).Select(ToResponse).ToList();

    public async Task<ReceptionPointResponse?> GetAsync(Guid id, CancellationToken cancellationToken)
    {
        var point = await points.GetActiveAsync(id, cancellationToken);
        return point is null ? null : ToResponse(point);
    }

    private static ReceptionPointResponse ToResponse(ReceptionPoint point) =>
        new(point.Id, point.Name, point.PublicAddress, point.Directions);
}
