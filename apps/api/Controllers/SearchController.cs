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
public sealed class SearchController(ISearchService search) : RecoveryController
{
    [HttpPost]
    public async Task<ActionResult<SearchResponse>> Text(SearchRequest request, CancellationToken ct) => Ok(await search.TextAsync(Actor, request, ct));
    [HttpPost("image")]
    [RequestSizeLimit(BoundedImage.MaxBytes)]
    public async Task<ActionResult<SearchResponse>> Image([FromQuery] ImageSearchFilter filter, CancellationToken ct) =>
        Ok(await search.ImageAsync(Actor, filter, Request.ContentType, Request.Body, Request.ContentLength, ct));
    [HttpPost("images")]
    [StreamedMultipart]
    [RequestSizeLimit(3 * BoundedImage.MaxBytes + 65536)]
    public async Task<ActionResult<SearchResponse>> Images([FromQuery] ImageSearchFilter filter, CancellationToken ct) =>
        Ok(await search.ImagesAsync(Actor, filter, Request.ContentType, Request.Body, Request.ContentLength, ct));
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
