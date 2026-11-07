using Findie.Api.Contracts;
using Findie.Api.Data;
using Findie.Api.Models;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;

namespace Findie.Api.Repositories;

public sealed class RecoveryRepository(FindieDbContext db) : IRecoveryRepository
{
    public Task<IDbContextTransaction> BeginAsync(CancellationToken ct) => db.Database.BeginTransactionAsync(ct);
    public async Task LockRequestAsync(Guid actor, Guid key, CancellationToken ct) =>
        await db.Database.ExecuteSqlInterpolatedAsync($"SELECT pg_advisory_xact_lock(hashtextextended({actor + ":" + key}, 0))", ct);
    public Task<IdempotencyKey?> ReplayAsync(Guid actor, Guid key, CancellationToken ct) =>
        db.IdempotencyKeys.AsNoTracking().SingleOrDefaultAsync(value => value.ActorUserId == actor && value.IdempotencyKeyValue == key, ct);

    private static IQueryable<Item> WithDetails(IQueryable<Item> items) => items
        .Include(item => item.HolderUser).Include(item => item.HolderPoint)
        .Include(item => item.VerificationQuestions)
        .Include(item => item.Images).ThenInclude(image => image.ProcessedObject).AsSplitQuery();

    public Task<Item?> ItemAsync(Guid id, bool forUpdate, CancellationToken ct) => WithDetails(forUpdate
        ? db.Items.FromSqlInterpolated($"SELECT * FROM items WHERE id = {id} FOR UPDATE")
        : db.Items.AsNoTracking().Where(item => item.Id == id)).SingleOrDefaultAsync(ct);

    public Task<List<SearchItem>> SearchItemsAsync(Guid actor, IReadOnlyCollection<Guid> ids, CancellationToken ct)
    {
        if (ids.Count == 0) return Task.FromResult<List<SearchItem>>([]);
        var candidateIds = ids.ToArray();
        return db.Items.AsNoTracking().Where(item => candidateIds.Contains(item.Id))
            .Include(item => item.HolderUser).Include(item => item.HolderPoint)
            .Include(item => item.Images.Where(image => image.RetiredAt == null && image.ProcessingState == "ready"
                && image.ReviewState == "approved" && image.ProcessedObject != null
                && image.ProcessedObject.ObjectKind == "processed" && image.ProcessedObject.ObjectState == "validated"))
                .ThenInclude(image => image.ProcessedObject)
            .AsSingleQuery()
            .Select(item => new SearchItem(item, item.CustodyKind == "person" ? item.HolderUserId == actor
                : item.CustodyKind == "external" ? item.PostedBy == actor
                : item.CustodyKind == "point" && db.PointStaff.Any(staff => staff.PointId == item.HolderPointId
                    && staff.UserId == actor && staff.RevokedAt == null && staff.Point.Active && staff.CanReceive)))
            .ToListAsync(ct);
    }

    public Task<(List<Item> Items, int TotalCount)> ItemsAsync(Guid actor, ItemFilter filter, CancellationToken ct)
    {
        var items = db.Items.AsNoTracking().Where(item => item.Lifecycle != "deleted");
        items = filter.Scope switch
        {
            "mine" => items.Where(item => item.PostedBy == actor || item.HolderUserId == actor),
            "managed" => items.Where(item => item.HolderUserId == actor
                || item.CustodyKind == "external" && item.PostedBy == actor
                || item.HolderPointId != null && db.PointStaff.Any(staff => staff.PointId == item.HolderPointId
                    && staff.UserId == actor && staff.RevokedAt == null && staff.Point.Active && (staff.CanReceive || staff.CanReturn))),
            _ => items.Where(item => item.PublicationState == "published" && item.Lifecycle == "active")
        };
        if (filter.Q is { Length: > 0 } q)
            items = items.Where(item => EF.Functions.ILike(item.Title, Pattern(q), "\\")
                || EF.Functions.ILike(item.PublicDescription, Pattern(q), "\\"));
        if (filter.Area is { Length: > 0 } area)
            items = items.Where(item => EF.Functions.ILike(item.FoundArea, Pattern(area), "\\"));
        if (filter.PointId is { } point) items = items.Where(item => item.HolderPointId == point);
        if (filter.From is { } from)
        {
            var start = new DateTimeOffset(from.ToDateTime(TimeOnly.MinValue), TimeSpan.FromHours(7)).ToUniversalTime();
            items = items.Where(item => item.FoundOn >= from || (item.FoundUntil ?? item.FoundFrom) >= start);
        }
        if (filter.Until is { } until)
        {
            var end = new DateTimeOffset(until.AddDays(1).ToDateTime(TimeOnly.MinValue), TimeSpan.FromHours(7)).ToUniversalTime();
            items = items.Where(item => item.FoundOn <= until || item.FoundFrom < end);
        }
        return PageAsync(WithDetails(items.OrderByDescending(item => item.CreatedAt).ThenBy(item => item.Id)),
            filter.Page, filter.PageSize, ct);
    }

    private static async Task<(List<T> Items, int TotalCount)> PageAsync<T>(IQueryable<T> query, int page, int pageSize, CancellationToken ct)
    {
        var totalCount = await query.CountAsync(ct);
        var items = await query.Skip((page - 1) * pageSize).Take(pageSize).ToListAsync(ct);
        return (items, totalCount);
    }

    private static string Pattern(string value) => "%" + value.Replace("\\", "\\\\").Replace("%", "\\%").Replace("_", "\\_") + "%";

    public Task<ReceptionPoint?> PointAsync(Guid id, CancellationToken ct) =>
        db.ReceptionPoints.SingleOrDefaultAsync(point => point.Id == id && point.Active, ct);
    public Task<bool> PointPermissionAsync(Guid actor, Guid point, bool receive, CancellationToken ct) =>
        db.PointStaff.AnyAsync(staff => staff.PointId == point && staff.UserId == actor && staff.RevokedAt == null
            && staff.Point.Active && (receive ? staff.CanReceive : staff.CanReturn), ct);
    public Task<bool> ActiveUserAsync(Guid id, CancellationToken ct) => db.Users.AnyAsync(user => user.Id == id && user.DisabledAt == null, ct);
    public async Task LockObjectAsync(StoredObject value, CancellationToken ct)
    {
        await db.Database.ExecuteSqlInterpolatedAsync($"SELECT id FROM stored_objects WHERE id = {value.Id} FOR UPDATE", ct);
        await db.Entry(value).ReloadAsync(ct);
    }

    private IQueryable<Claim> Claims => db.Claims.AsNoTracking().Include(claim => claim.Item)
        .Include(claim => claim.Answers).Include(claim => claim.Conversation).AsSplitQuery();
    public Task<Claim?> ClaimAsync(Guid id, CancellationToken ct) => Claims.SingleOrDefaultAsync(claim => claim.Id == id, ct);
    public Task<(List<Claim> Items, int TotalCount)> ClaimsAsync(Guid actor, Guid? itemId, int page, int pageSize, CancellationToken ct) => PageAsync(Claims
        .Where(claim => (claim.ClaimantUserId == actor || claim.ReviewerUserId == actor
                && claim.Item.HolderUserId == actor && claim.Item.CustodyVersion == claim.SourceCustodyVersion)
            && (itemId == null || claim.ItemId == itemId))
        .OrderByDescending(claim => claim.CreatedAt).ThenBy(claim => claim.Id), page, pageSize, ct);
    public Task<bool> ExistingClaimAsync(Guid actor, Item item, CancellationToken ct) => db.Claims.AnyAsync(claim =>
        claim.ItemId == item.Id && claim.ClaimantUserId == actor && claim.SourceCustodyVersion == item.CustodyVersion
        && (claim.Status == "pending" || claim.Status == "approved"), ct);
    public async Task DecideClaimAsync(Guid id, Guid actor, string decision, string? note, DateTimeOffset now, CancellationToken ct) =>
        await db.Claims.Where(claim => claim.Id == id && claim.Status == "pending").ExecuteUpdateAsync(update => update
            .SetProperty(claim => claim.Status, decision).SetProperty(claim => claim.DecidedBy, actor)
            .SetProperty(claim => claim.DecidedAt, now).SetProperty(claim => claim.DecisionNote, note), ct);

    public Task<Conversation?> ConversationAsync(Guid id, bool forUpdate, CancellationToken ct) => (forUpdate
        ? db.Conversations.FromSqlInterpolated($"SELECT * FROM conversations WHERE claim_id = {id} FOR UPDATE")
        : db.Conversations.AsNoTracking().Where(chat => chat.ClaimId == id))
        .Include(chat => chat.Claim).ThenInclude(claim => claim.Item).SingleOrDefaultAsync(ct);
    public Task<(List<Conversation> Items, int TotalCount)> ConversationsAsync(Guid actor, int page, int pageSize, CancellationToken ct) =>
        PageAsync(db.Conversations.AsNoTracking().Include(chat => chat.Claim).ThenInclude(claim => claim.Item)
            .Where(chat => chat.Claim.ClaimantUserId == actor || chat.Claim.ReviewerUserId == actor)
            .OrderByDescending(chat => chat.CreatedAt).ThenBy(chat => chat.ClaimId), page, pageSize, ct);
    public Task<Message?> ExistingMessageAsync(Guid id, Guid actor, Guid key, CancellationToken ct) =>
        db.Messages.AsNoTracking().SingleOrDefaultAsync(message => message.ConversationId == id && message.SenderUserId == actor
            && message.ClientMessageId == key, ct);
    public Task<List<Message>> MessagesAsync(Guid id, long after, int limit, CancellationToken ct) =>
        db.Messages.AsNoTracking().Where(message => message.ConversationId == id && message.MessageSequence > after)
            .OrderBy(message => message.MessageSequence).Take(limit + 1).ToListAsync(ct);

    public Task<IntakeRequest?> IntakeAsync(Guid id, CancellationToken ct) =>
        db.IntakeRequests.AsNoTracking().Include(request => request.Item).SingleOrDefaultAsync(request => request.Id == id, ct);
    public async Task DecideIntakeAsync(Guid id, Guid actor, string decision, string? note, CancellationToken ct) =>
        await db.IntakeRequests.Where(request => request.Id == id && request.Status == "pending").ExecuteUpdateAsync(update => update
            .SetProperty(request => request.Status, decision).SetProperty(request => request.DecidedBy, actor)
            .SetProperty(request => request.DecidedAt, DateTimeOffset.UtcNow).SetProperty(request => request.DecisionNote, note), ct);
    public Task<(List<IntakeRequest> Items, int TotalCount)> IntakesAsync(Guid actor, Guid? pointId, int page, int pageSize, CancellationToken ct) =>
        PageAsync(db.IntakeRequests.AsNoTracking().Include(request => request.Item).Where(request =>
                (request.RequestedBy == actor || db.PointStaff.Any(staff => staff.UserId == actor
                    && staff.PointId == request.TargetPointId && staff.RevokedAt == null && staff.CanReceive && staff.Point.Active))
                && (pointId == null || request.TargetPointId == pointId))
            .OrderByDescending(request => request.CreatedAt).ThenBy(request => request.Id), page, pageSize, ct);
    public Task<bool> ExistingIntakeAsync(Item item, Guid pointId, CancellationToken ct) => db.IntakeRequests.AnyAsync(request =>
        request.ItemId == item.Id && request.TargetPointId == pointId && request.SourceCustodyVersion == item.CustodyVersion
        && request.Status == "pending", ct);
    public Task<(List<CustodyEvent> Items, int TotalCount)> EventsAsync(Guid id, int page, int pageSize, CancellationToken ct) =>
        PageAsync(db.CustodyEvents.AsNoTracking().Where(value => value.ItemId == id).OrderBy(value => value.CustodyVersion), page, pageSize, ct);
    public Task<CustodyEvent?> EventAsync(Guid id, CancellationToken ct) =>
        db.CustodyEvents.AsNoTracking().SingleOrDefaultAsync(value => value.Id == id, ct);

    public void ReplaceQuestions(Item item, IReadOnlyList<string> questions)
    {
        var old = item.VerificationQuestions.ToDictionary(question => question.Slot);
        for (short slot = 1; slot <= questions.Count; slot++)
        {
            if (old.Remove(slot, out var existing)) existing.QuestionText = questions[slot - 1];
            else item.VerificationQuestions.Add(new VerificationQuestion { ItemId = item.Id, Slot = slot, QuestionText = questions[slot - 1] });
        }
        db.VerificationQuestions.RemoveRange(old.Values);
    }
    public void Add<T>(T entity) where T : class => db.Add(entity);
    public Task SaveAsync(CancellationToken ct) => db.SaveChangesAsync(ct);
}
