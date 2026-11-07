using System.ComponentModel.DataAnnotations;
using Findie.Api.Contracts;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc;

namespace Findie.Api.Controllers;

[Route("api/items")]
public sealed class ItemsController(IItemService items, IClaimService claims, IIntakeService intakes) : RecoveryController
{
    [HttpGet]
    public async Task<ActionResult<PageResponse<ItemResponse>>> List([FromQuery] ItemFilter filter, CancellationToken ct) =>
        Ok(await items.ListAsync(Actor, filter, ct));
    [HttpGet("{id:guid}")]
    public async Task<ActionResult<ItemResponse>> Get(Guid id, CancellationToken ct) => Ok(await items.GetAsync(Actor, id, ct));
    [HttpPost]
    public async Task<ActionResult<ItemResponse>> Create(CreateItemRequest request, CancellationToken ct)
    {
        var result = await items.CreateAsync(Actor, RequestKey, request, ct);
        return CreatedAtAction(nameof(Get), new { id = result.Id }, result);
    }
    [HttpPut("{id:guid}")]
    public async Task<ActionResult<ItemResponse>> Update(Guid id, UpdateItemRequest request, CancellationToken ct) =>
        Ok(await items.UpdateAsync(Actor, RequestKey, id, request, ct));
    [HttpDelete("{id:guid}")]
    public async Task<IActionResult> Delete(Guid id, [FromBody] DeleteItemRequest request, CancellationToken ct)
    {
        await items.DeleteAsync(Actor, RequestKey, id, request, ct);
        return NoContent();
    }
    [HttpPut("{id:guid}/publication")]
    public async Task<ActionResult<ItemResponse>> Publish(Guid id, PublicationRequest request, CancellationToken ct) =>
        Ok(await items.PublishAsync(Actor, RequestKey, id, request, ct));
    [HttpGet("{id:guid}/verification-questions")]
    public async Task<ActionResult<QuestionSetResponse>> Questions(Guid id, CancellationToken ct) =>
        Ok(await items.QuestionsAsync(Actor, id, ct));
    [HttpPost("{id:guid}/claims")]
    public async Task<ActionResult<ClaimResponse>> CreateClaim(Guid id, CreateClaimRequest request, CancellationToken ct)
    {
        var result = await claims.CreateAsync(Actor, RequestKey, id, request, ct);
        return Created($"/api/claims/{result.Id}", result);
    }
    [HttpPost("{id:guid}/intake-requests")]
    public async Task<ActionResult<IntakeResponse>> CreateIntake(Guid id, CreateIntakeRequest request, CancellationToken ct)
    {
        var result = await intakes.CreateAsync(Actor, RequestKey, id, request, ct);
        return Created($"/api/intake-requests/{result.Id}", result);
    }
    [HttpPost("{id:guid}/return")]
    public async Task<ActionResult<CustodyEventResponse>> Return(Guid id, ReturnItemRequest request, CancellationToken ct)
    {
        var result = await items.ReturnAsync(Actor, RequestKey, id, request, ct);
        return Created($"/api/items/{id}/custody-events", result);
    }
    [HttpGet("{id:guid}/custody-events")]
    public async Task<ActionResult<PageResponse<CustodyEventResponse>>> Events(Guid id, [FromQuery, Range(1, 10000)] int page = 1,
        [FromQuery, Range(1, 100)] int pageSize = 20, CancellationToken ct = default) =>
        Ok(await items.EventsAsync(Actor, id, page, pageSize, ct));
}
