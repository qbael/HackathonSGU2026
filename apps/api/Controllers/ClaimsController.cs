using System.ComponentModel.DataAnnotations;
using Findie.Api.Contracts;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc;

namespace Findie.Api.Controllers;

[Route("api/claims")]
public sealed class ClaimsController(IClaimService claims) : RecoveryController
{
    [HttpGet]
    public async Task<ActionResult<PageResponse<ClaimResponse>>> List([FromQuery] Guid? itemId,
        [FromQuery, Range(1, 10000)] int page = 1, [FromQuery, Range(1, 100)] int pageSize = 20, CancellationToken ct = default) =>
        Ok(await claims.ListAsync(Actor, itemId, page, pageSize, ct));
    [HttpGet("{id:guid}")]
    public async Task<ActionResult<ClaimResponse>> Get(Guid id, CancellationToken ct) => Ok(await claims.GetAsync(Actor, id, ct));
    [HttpPost("{id:guid}/decision")]
    public async Task<ActionResult<ClaimResponse>> Decide(Guid id, DecisionRequest request, CancellationToken ct) =>
        Ok(await claims.DecideAsync(Actor, RequestKey, id, request, ct));
}
