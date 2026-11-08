using Findie.Api.Contracts;
using Findie.Api.Hubs;
using Findie.Api.Models;
using Microsoft.AspNetCore.SignalR;
using Findie.Api.Repositories;

namespace Findie.Api.Services;

public interface IConversationService
{
    Task<PageResponse<ConversationResponse>> ListAsync(Guid actor, int page, int size, CancellationToken ct);
    Task<ConversationResponse> GetAsync(Guid actor, Guid id, CancellationToken ct);
    Task<MessagePage> MessagesAsync(Guid actor, Guid id, long after, int limit, CancellationToken ct);
    Task<MessageResponse> SendAsync(Guid actor, Guid id, SendMessageRequest request, CancellationToken ct);
}

public sealed class ConversationService(IRecoveryRepository repository, RecoveryWorkflow workflow, IHubContext<ChatHub> hubContext) : IConversationService
{
    public async Task<PageResponse<ConversationResponse>> ListAsync(Guid actor, int page, int size, CancellationToken ct)
    {
        var (items, totalCount) = await repository.ConversationsAsync(actor, page, size, ct);
        return RecoveryWorkflow.Page(items.Select(Response).ToList(), page, size, totalCount);
    }
    public async Task<ConversationResponse> GetAsync(Guid actor, Guid id, CancellationToken ct) => Response(await AuthorizedAsync(actor, id, ct));
    private async Task<Conversation> AuthorizedAsync(Guid actor, Guid id, CancellationToken ct)
    {
        var chat = await repository.ConversationAsync(id, false, ct);
        if (chat is null || chat.Claim.Status != "approved" || chat.Claim.ClaimantUserId != actor && chat.Claim.ReviewerUserId != actor)
            throw new ApiException(404, "Conversation not found.");
        return chat;
    }
    public async Task<MessagePage> MessagesAsync(Guid actor, Guid id, long after, int limit, CancellationToken ct)
    {
        await AuthorizedAsync(actor, id, ct);
        var messages = await repository.MessagesAsync(id, after, limit, ct);
        var values = messages.Take(limit).Select(MessageResponse).ToList();
        return new MessagePage(values, values.LastOrDefault()?.Sequence ?? after, messages.Count > limit);
    }
    public async Task<MessageResponse> SendAsync(Guid actor, Guid id, SendMessageRequest request, CancellationToken ct)
    {
        if (request.ClientMessageId == Guid.Empty) throw new ApiException(400, "ClientMessageId must be a nonempty UUID.");
        var body = RecoveryWorkflow.Text(request.Body, 4000, "Message");
        var chat = await AuthorizedAsync(actor, id, ct);
        await using var transaction = await repository.BeginAsync(ct);
        await workflow.ItemAsync(chat.Claim.ItemId, true, ct);
        chat = (await repository.ConversationAsync(id, true, ct))!;
        if (chat.Claim.Status != "approved" || chat.Claim.ClaimantUserId != actor && chat.Claim.ReviewerUserId != actor)
            throw new ApiException(404, "Conversation not found.");
        var existing = await repository.ExistingMessageAsync(id, actor, request.ClientMessageId, ct);
        if (existing is not null)
        {
            if (existing.Body != body) throw new ApiException(409, "ClientMessageId was already used for different content.");
            return MessageResponse(existing);
        }
        if (!CanSend(chat)) throw new ApiException(409, "This conversation is read-only after custody changes or handover.");
        var message = new Message { ConversationId = id, SenderUserId = actor, ClientMessageId = request.ClientMessageId, Body = body };
        repository.Add(message);
        await repository.SaveAsync(ct);
        await transaction.CommitAsync(ct);
        var response = MessageResponse(message);
        try
        {
            await hubContext.Clients.Group($"conversation_{id}").SendAsync("ReceiveMessage", response, ct);
            var recipientId = chat.Claim.ClaimantUserId == actor ? chat.Claim.ReviewerUserId : chat.Claim.ClaimantUserId;
            var notification = new
            {
                Type = "message",
                ConversationId = id,
                ItemId = chat.Claim.ItemId,
                SenderUserId = actor,
                Message = response
            };
            await hubContext.Clients.User(recipientId.ToString()).SendAsync("NotificationReceived", notification, ct);
            await hubContext.Clients.Group($"user_{recipientId}").SendAsync("NotificationReceived", notification, ct);
        }
        catch { }
        return response;
    }
    private static bool CanSend(Conversation chat) => chat.Claim.Status == "approved" && chat.Claim.Item.Lifecycle == "active"
        && chat.Claim.Item.CustodyKind == "person" && chat.Claim.Item.HolderUserId == chat.Claim.ReviewerUserId
        && chat.Claim.Item.CustodyVersion == chat.Claim.SourceCustodyVersion;
    private static ConversationResponse Response(Conversation chat) => new(chat.ClaimId, chat.Claim.ItemId,
        chat.Claim.ClaimantUserId, chat.Claim.ReviewerUserId, CanSend(chat), chat.CreatedAt);
    private static MessageResponse MessageResponse(Message message) => new(message.Id, message.ConversationId, message.SenderUserId,
        message.ClientMessageId, message.MessageSequence, message.Body, message.CreatedAt);
}
