using Findie.Api.Contracts;
using Findie.Api.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Findie.Api.Controllers;

[ApiController]
[Authorize]
[Route("api/reception-points")]
public sealed class ReceptionPointsController(IReceptionPointService points) : ControllerBase
{
    [HttpGet]
    public async Task<ActionResult<IReadOnlyList<ReceptionPointResponse>>> List(CancellationToken cancellationToken) =>
        Ok(await points.ListAsync(cancellationToken));

    [HttpGet("{id:guid}")]
    public async Task<ActionResult<ReceptionPointResponse>> Get(Guid id, CancellationToken cancellationToken)
    {
        var point = await points.GetAsync(id, cancellationToken);
        return point is null ? NotFound() : Ok(point);
    }
}
