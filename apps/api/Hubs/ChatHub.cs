using System.Security.Claims;
using Findie.Api.Repositories;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.SignalR;

namespace Findie.Api.Hubs;

[Authorize]
public class ChatHub(IRecoveryRepository repository) : Hub
{
    public override async Task OnConnectedAsync()
    {
        if (Guid.TryParse(Context.User?.FindFirstValue(ClaimTypes.NameIdentifier), out var userId))
        {
            await Groups.AddToGroupAsync(Context.ConnectionId, $"user_{userId}");
        }
        await base.OnConnectedAsync();
    }

    public async Task JoinConversation(Guid conversationId)
    {
        if (!Guid.TryParse(Context.User?.FindFirstValue(ClaimTypes.NameIdentifier), out var actor))
        {
            throw new HubException("Unauthorized");
        }

        var chat = await repository.ConversationAsync(conversationId, false, Context.ConnectionAborted);
        if (chat is null || chat.Claim.Status != "approved"
            || (chat.Claim.ClaimantUserId != actor && chat.Claim.ReviewerUserId != actor))
        {
            throw new HubException("Conversation not found or access denied.");
        }

        await Groups.AddToGroupAsync(Context.ConnectionId, $"conversation_{conversationId}");
    }

    public async Task LeaveConversation(Guid conversationId)
    {
        await Groups.RemoveFromGroupAsync(Context.ConnectionId, $"conversation_{conversationId}");
    }
}
