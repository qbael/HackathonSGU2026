using System.ComponentModel.DataAnnotations;
using Findie.Api.Contracts;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc;

namespace Findie.Api.Controllers;

[Route("api/intake-requests")]
public sealed class IntakeRequestsController(IIntakeService intakes) : RecoveryController
{
    [HttpGet]
    public async Task<ActionResult<PageResponse<IntakeResponse>>> List([FromQuery] Guid? pointId,
        [FromQuery, Range(1, 10000)] int page = 1, [FromQuery, Range(1, 100)] int pageSize = 20, CancellationToken ct = default) =>
        Ok(await intakes.ListAsync(Actor, pointId, page, pageSize, ct));
    [HttpGet("{id:guid}")]
    public async Task<ActionResult<IntakeResponse>> Get(Guid id, CancellationToken ct) => Ok(await intakes.GetAsync(Actor, id, ct));
    [HttpPost("{id:guid}/decision")]
    public async Task<ActionResult<IntakeResponse>> Decide(Guid id, IntakeDecisionRequest request, CancellationToken ct) =>
        Ok(await intakes.DecideAsync(Actor, RequestKey, id, request, ct));
}
