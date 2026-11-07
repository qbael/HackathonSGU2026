using System.ComponentModel.DataAnnotations;
using Findie.Api.Contracts;
using Findie.Api.Infrastructure;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;

namespace Findie.Api.Controllers;

[Route("api/items/{itemId:guid}/images")]
public sealed class ImagesController(IImageService images) : RecoveryController
{
    [HttpGet]
    public async Task<ActionResult<IReadOnlyList<ImageResponse>>> List(Guid itemId, CancellationToken ct) =>
        Ok(await images.ListAsync(Actor, itemId, ct));
    [HttpPost]
    [RequestSizeLimit(BoundedImage.MaxBytes)]
    [EnableRateLimiting("images")]
    // Legacy slots remain bindable for idempotent replay; the service rejects new uploads outside 1..3.
    public async Task<ActionResult<ImageResponse>> Upload(Guid itemId, [FromQuery, Range(1, 5)] short position = 1, CancellationToken ct = default)
    {
        var result = await images.UploadAsync(Actor, RequestKey, itemId, position, Request.ContentType,
            Request.Body, Request.ContentLength, ct);
        return Created($"/api/items/{itemId}/images/{result.Id}/content", result);
    }
    [HttpPost("{imageId:guid}/review")]
    public async Task<ActionResult<ImageResponse>> Review(Guid itemId, Guid imageId, ReviewImageRequest request, CancellationToken ct) =>
        Ok(await images.ReviewAsync(Actor, RequestKey, itemId, imageId, request, ct));
    [HttpPost("{imageId:guid}/retire")]
    public async Task<ActionResult<ImageResponse>> Retire(Guid itemId, Guid imageId, RetireImageRequest request, CancellationToken ct) =>
        Ok(await images.RetireAsync(Actor, RequestKey, itemId, imageId, request, ct));
    [HttpGet("{imageId:guid}/content")]
    public async Task<IActionResult> Content(Guid itemId, Guid imageId, CancellationToken ct)
    {
        var output = await images.ContentAsync(Actor, itemId, imageId, ct);
        Response.Headers.CacheControl = "no-store";
        Response.Headers.XContentTypeOptions = "nosniff";
        return File(output.Bytes, output.ContentType);
    }
}
