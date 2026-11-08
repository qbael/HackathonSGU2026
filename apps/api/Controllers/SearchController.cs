using Findie.Api.Contracts;
using Findie.Api.Infrastructure;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;
using Microsoft.AspNetCore.Mvc.ModelBinding;
using Microsoft.AspNetCore.RateLimiting;

namespace Findie.Api.Controllers;

[Route("api/search")]
[EnableRateLimiting("images")]
public sealed class SearchController(ISearchService search, AiJobs jobs, IConfiguration configuration) : RecoveryController
{
    [HttpPost]
    public async Task<ActionResult<SearchResponse>> Text(SearchRequest request, CancellationToken ct)
    {
        var actor = Actor;
        if (jobs.Enabled(configuration)) return jobs.Start(actor, async (services, token) =>
            await services.GetRequiredService<ISearchService>().TextAsync(actor, request, token));
        return Ok(await search.TextAsync(actor, request, ct));
    }
    [HttpPost("image")]
    [RequestSizeLimit(BoundedImage.MaxBytes)]
    public async Task<ActionResult<SearchResponse>> Image([FromQuery] ImageSearchFilter filter, CancellationToken ct)
    {
        var actor = Actor; var mime = Request.ContentType; var length = Request.ContentLength;
        if (jobs.Enabled(configuration)) return await jobs.UploadAsync(actor, Request, async (services, stream, token) =>
            await services.GetRequiredService<ISearchService>().ImageAsync(actor, filter, mime, stream, length, token), ct);
        return Ok(await search.ImageAsync(actor, filter, mime, Request.Body, length, ct));
    }
    [HttpPost("images")]
    [StreamedMultipart]
    [RequestSizeLimit(3 * BoundedImage.MaxBytes + 65536)]
    public async Task<ActionResult<SearchResponse>> Images([FromQuery] ImageSearchFilter filter, CancellationToken ct)
    {
        var actor = Actor; var mime = Request.ContentType; var length = Request.ContentLength;
        if (jobs.Enabled(configuration)) return await jobs.UploadAsync(actor, Request, async (services, stream, token) =>
            await services.GetRequiredService<ISearchService>().ImagesAsync(actor, filter, mime, stream, length, token), ct,
            3 * BoundedImage.MaxBytes + 65536);
        return Ok(await search.ImagesAsync(actor, filter, mime, Request.Body, length, ct));
    }
}

sealed class StreamedMultipartAttribute : Attribute, IResourceFilter
{
    public void OnResourceExecuting(ResourceExecutingContext context)
    {
        // Form model binding would buffer uploaded originals before the streaming action runs.
        context.ValueProviderFactories.RemoveType<FormValueProviderFactory>();
        context.ValueProviderFactories.RemoveType<FormFileValueProviderFactory>();
        context.ValueProviderFactories.RemoveType<JQueryFormValueProviderFactory>();
    }
    public void OnResourceExecuted(ResourceExecutedContext context) { }
}
