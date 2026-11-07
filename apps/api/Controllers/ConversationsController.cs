using System.ComponentModel.DataAnnotations;
using Findie.Api.Contracts;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc;

namespace Findie.Api.Controllers;

[Route("api/conversations")]
public sealed class ConversationsController(IConversationService conversations) : RecoveryController
{
    [HttpGet]
    public async Task<ActionResult<PageResponse<ConversationResponse>>> List([FromQuery, Range(1, 10000)] int page = 1,
        [FromQuery, Range(1, 100)] int pageSize = 20, CancellationToken ct = default) =>
        Ok(await conversations.ListAsync(Actor, page, pageSize, ct));
    [HttpGet("{id:guid}")]
    public async Task<ActionResult<ConversationResponse>> Get(Guid id, CancellationToken ct) =>
        Ok(await conversations.GetAsync(Actor, id, ct));
    [HttpGet("{id:guid}/messages")]
    public async Task<ActionResult<MessagePage>> Messages(Guid id, [FromQuery, Range(0, long.MaxValue)] long after = 0,
        [FromQuery, Range(1, 100)] int limit = 50, CancellationToken ct = default) =>
        Ok(await conversations.MessagesAsync(Actor, id, after, limit, ct));
    [HttpPost("{id:guid}/messages")]
    public async Task<ActionResult<MessageResponse>> Send(Guid id, SendMessageRequest request, CancellationToken ct) =>
        Ok(await conversations.SendAsync(Actor, id, request, ct));
}
