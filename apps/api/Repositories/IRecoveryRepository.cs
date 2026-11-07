using Findie.Api.Contracts;
using Findie.Api.Models;
using Microsoft.EntityFrameworkCore.Storage;

namespace Findie.Api.Repositories;

public interface IRecoveryRepository
{
    Task<IDbContextTransaction> BeginAsync(CancellationToken ct);
    Task LockRequestAsync(Guid actor, Guid key, CancellationToken ct);
    Task<IdempotencyKey?> ReplayAsync(Guid actor, Guid key, CancellationToken ct);
    Task<Item?> ItemAsync(Guid id, bool forUpdate, CancellationToken ct);
    Task<(List<Item> Items, int TotalCount)> ItemsAsync(Guid actor, ItemFilter filter, CancellationToken ct);
    Task<ReceptionPoint?> PointAsync(Guid id, CancellationToken ct);
    Task<bool> PointPermissionAsync(Guid actor, Guid point, bool receive, CancellationToken ct);
    Task<bool> ActiveUserAsync(Guid id, CancellationToken ct);
    Task LockObjectAsync(StoredObject value, CancellationToken ct);
    Task<Claim?> ClaimAsync(Guid id, CancellationToken ct);
    Task<(List<Claim> Items, int TotalCount)> ClaimsAsync(Guid actor, Guid? itemId, int page, int pageSize, CancellationToken ct);
    Task<bool> ExistingClaimAsync(Guid actor, Item item, CancellationToken ct);
    Task DecideClaimAsync(Guid id, Guid actor, string decision, string? note, DateTimeOffset now, CancellationToken ct);
    Task<Conversation?> ConversationAsync(Guid id, bool forUpdate, CancellationToken ct);
    Task<(List<Conversation> Items, int TotalCount)> ConversationsAsync(Guid actor, int page, int pageSize, CancellationToken ct);
    Task<Message?> ExistingMessageAsync(Guid conversationId, Guid actor, Guid key, CancellationToken ct);
    Task<List<Message>> MessagesAsync(Guid id, long after, int limit, CancellationToken ct);
    Task<IntakeRequest?> IntakeAsync(Guid id, CancellationToken ct);
    Task DecideIntakeAsync(Guid id, Guid actor, string decision, string? note, CancellationToken ct);
    Task<(List<IntakeRequest> Items, int TotalCount)> IntakesAsync(Guid actor, Guid? pointId, int page, int pageSize, CancellationToken ct);
    Task<bool> ExistingIntakeAsync(Item item, Guid pointId, CancellationToken ct);
    Task<(List<CustodyEvent> Items, int TotalCount)> EventsAsync(Guid itemId, int page, int pageSize, CancellationToken ct);
    Task<CustodyEvent?> EventAsync(Guid id, CancellationToken ct);
    void ReplaceQuestions(Item item, IReadOnlyList<string> questions);
    void Add<T>(T entity) where T : class;
    Task SaveAsync(CancellationToken ct);
}
