using Findie.Api.Contracts;
using Findie.Api.Infrastructure;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;

namespace Findie.Api.Controllers;

[Route("api/saved-searches")]
public sealed class SavedSearchesController(SavedSearchService searches) : RecoveryController
{
    [HttpGet]
    public async Task<ActionResult<IReadOnlyList<SavedSearchResponse>>> List(CancellationToken ct) => Ok(await searches.ListAsync(Actor, ct));
    [HttpPost]
    [EnableRateLimiting("images")]
    [StreamedMultipart]
    [RequestSizeLimit(3 * BoundedImage.MaxBytes + 65536)]
    public async Task<ActionResult<SavedSearchResponse>> Create([FromQuery] ImageSearchFilter filter, CancellationToken ct)
    {
        var result = await searches.CreateAsync(Actor, RequestKey, filter, Request.ContentType, Request.Body, Request.ContentLength, ct);
        return StatusCode(201, result);
    }
    [HttpDelete("{id:guid}")]
    public async Task<IActionResult> Delete(Guid id, CancellationToken ct) { await searches.DeleteAsync(Actor, id, ct); return NoContent(); }
    [HttpPut("{id:guid}/matches/{itemId:guid}/read")]
    public async Task<IActionResult> Read(Guid id, Guid itemId, CancellationToken ct) { await searches.ReadAsync(Actor, id, itemId, ct); return NoContent(); }
}
