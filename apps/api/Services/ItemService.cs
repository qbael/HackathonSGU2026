using Findie.Api.Contracts;
using Findie.Api.Models;
using Findie.Api.Repositories;

namespace Findie.Api.Services;

public interface IItemService
{
    Task<PageResponse<ItemResponse>> ListAsync(Guid actor, ItemFilter filter, CancellationToken ct);
    Task<ItemResponse> GetAsync(Guid actor, Guid id, CancellationToken ct);
    Task<QuestionSetResponse> QuestionsAsync(Guid actor, Guid id, CancellationToken ct);
    Task<ItemResponse> CreateAsync(Guid actor, Guid key, CreateItemRequest request, CancellationToken ct);
    Task<ItemResponse> UpdateAsync(Guid actor, Guid key, Guid id, UpdateItemRequest request, CancellationToken ct);
    Task DeleteAsync(Guid actor, Guid key, Guid id, DeleteItemRequest request, CancellationToken ct);
    Task<ItemResponse> PublishAsync(Guid actor, Guid key, Guid id, PublicationRequest request, CancellationToken ct);
    Task<CustodyEventResponse> ReturnAsync(Guid actor, Guid key, Guid id, ReturnItemRequest request, CancellationToken ct);
    Task<PageResponse<CustodyEventResponse>> EventsAsync(Guid actor, Guid id, int page, int size, CancellationToken ct);
}

public sealed class ItemService(IRecoveryRepository repository, RecoveryWorkflow workflow) : IItemService
{
    public async Task<PageResponse<ItemResponse>> ListAsync(Guid actor, ItemFilter filter, CancellationToken ct)
    {
        if (filter.From > filter.Until || filter.From == DateOnly.MinValue || filter.Until == DateOnly.MaxValue)
            throw new ApiException(400, "Invalid date filter.");
        filter.Q = RecoveryWorkflow.Optional(filter.Q);
        filter.Area = RecoveryWorkflow.Optional(filter.Area);
        var (items, totalCount) = await repository.ItemsAsync(actor, filter, ct);
        var responses = new List<ItemResponse>();
        foreach (var item in items) responses.Add(await workflow.ResponseAsync(item, actor, ct));
        return RecoveryWorkflow.Page(responses, filter.Page, filter.PageSize, totalCount);
    }
    public async Task<ItemResponse> GetAsync(Guid actor, Guid id, CancellationToken ct)
    {
        var item = await workflow.ItemAsync(id, false, ct);
        await workflow.RequireReadAsync(item, actor, ct);
        return await workflow.ResponseAsync(item, actor, ct);
    }
    public async Task<QuestionSetResponse> QuestionsAsync(Guid actor, Guid id, CancellationToken ct)
    {
        var item = await workflow.ItemAsync(id, false, ct);
        await workflow.RequireReadAsync(item, actor, ct);
        if (item.CustodyKind != "person") throw new ApiException(409, "Claims apply only to items held by a person.");
        return new QuestionSetResponse(item.ContentVersion, item.VerificationQuestions.OrderBy(question => question.Slot)
            .Select(question => new QuestionResponse(question.Slot, question.QuestionText)).ToList());
    }
    public async Task<ItemResponse> CreateAsync(Guid actor, Guid key, CreateItemRequest request, CancellationToken ct)
    {
        var id = await workflow.WriteAsync(actor, key, "item.create", request, "item", 201, async () =>
        {
            var item = new Item { PostedBy = actor, HolderUserId = actor };
            SetContent(item, request.Content);
            var custody = request.Custody;
            if (custody.Kind == "person")
            {
                if (custody.PointId is not null || custody.Name is not null || custody.Address is not null || custody.Instructions is not null
                    || custody.ConfirmedPhysicalReceipt) throw new ApiException(400, "Person custody cannot contain point or external fields.");
            }
            else if (custody.Kind == "external")
            {
                if (custody.PointId is not null || custody.ConfirmedPhysicalReceipt) throw new ApiException(400, "Invalid external custody fields.");
                item.CustodyKind = "external";
                item.HolderUserId = null;
                item.ExternalName = RecoveryWorkflow.Text(custody.Name, 200, "External name");
                item.ExternalPublicAddress = RecoveryWorkflow.Text(custody.Address, 500, "Public address");
                item.ExternalInstructions = RecoveryWorkflow.Optional(custody.Instructions);
            }
            else if (custody.Kind == "point")
            {
                if (custody.PointId is not { } pointId || custody.Name is not null || custody.Address is not null || custody.Instructions is not null)
                    throw new ApiException(400, "Point custody requires only a point ID.");
                var point = await repository.PointAsync(pointId, ct) ?? throw new ApiException(400, "Reception point is unavailable.");
                if (custody.ConfirmedPhysicalReceipt)
                {
                    if (!await repository.PointPermissionAsync(actor, pointId, true, ct)) throw new ApiException(403, "Receiving permission is required.");
                    item.CustodyKind = "point";
                    item.HolderUserId = null;
                    item.HolderPointId = pointId;
                    item.HolderPoint = point;
                }
                else repository.Add(new IntakeRequest { ItemId = item.Id, RequestedBy = actor, TargetPointId = pointId, SourceCustodyVersion = 1 });
            }
            else throw new ApiException(400, "Invalid custody kind.");
            repository.Add(item);
            workflow.Event(item, actor, "registered", null);
            workflow.Enqueue(item);
            return item.Id;
        }, ct);
        return await GetAsync(actor, id, ct);
    }
    public async Task<ItemResponse> UpdateAsync(Guid actor, Guid key, Guid id, UpdateItemRequest request, CancellationToken ct)
    {
        await workflow.WriteAsync(actor, key, $"item.update:{id}", request, "item", 200, async () =>
        {
            var item = await workflow.ItemAsync(id, true, ct);
            await workflow.RequireManagerAsync(item, actor, ct);
            RecoveryWorkflow.RequireActive(item);
            RecoveryWorkflow.RequireVersion(item, request.RowVersion);
            SetContent(item, request.Content);
            workflow.Changed(item, content: true);
            return id;
        }, ct);
        return await GetAsync(actor, id, ct);
    }
    public async Task DeleteAsync(Guid actor, Guid key, Guid id, DeleteItemRequest request, CancellationToken ct)
    {
        await workflow.WriteAsync(actor, key, $"item.delete:{id}", request, "item", 204, async () =>
        {
            var item = await workflow.ItemAsync(id, true, ct);
            await workflow.RequireManagerAsync(item, actor, ct);
            RecoveryWorkflow.RequireVersion(item, request.RowVersion);
            item.Lifecycle = "deleted";
            foreach (var image in item.Images) image.OriginalEmbedding = null;
            workflow.Changed(item);
            return id;
        }, ct);
    }
    public async Task<ItemResponse> PublishAsync(Guid actor, Guid key, Guid id, PublicationRequest request, CancellationToken ct)
    {
        await workflow.WriteAsync(actor, key, $"item.publish:{id}", request, "item", 200, async () =>
        {
            var item = await workflow.ItemAsync(id, true, ct);
            await workflow.RequireManagerAsync(item, actor, ct);
            RecoveryWorkflow.RequireActive(item);
            RecoveryWorkflow.RequireVersion(item, request.RowVersion);
            if (request.State == "published" && !item.Images.Any(RecoveryWorkflow.PublicImage))
                throw new ApiException(409, "Upload and approve at least one image before publishing this item.");
            if (item.PublicationState != request.State)
            {
                item.PublicationState = request.State;
                workflow.Changed(item);
            }
            return id;
        }, ct);
        return await GetAsync(actor, id, ct);
    }
    private void SetContent(Item item, ItemInput content)
    {
        item.Title = RecoveryWorkflow.Text(content.Title, 200, "Title");
        item.PublicDescription = RecoveryWorkflow.Text(content.PublicDescription, 5000, "Public description");
        item.FoundArea = RecoveryWorkflow.Text(content.FoundArea, 200, "Found area");
        TimeZoneInfo timezone;
        try { timezone = TimeZoneInfo.FindSystemTimeZoneById(content.FoundTimezone); }
        catch (Exception error) when (error is TimeZoneNotFoundException or InvalidTimeZoneException)
        { throw new ApiException(400, "Found timezone must be a valid IANA timezone."); }
        if (content.FoundTimezone != "UTC" && !content.FoundTimezone.Contains('/')) throw new ApiException(400, "Use an IANA timezone.");
        var now = DateTimeOffset.UtcNow;
        var valid = content.FoundTimePrecision switch
        {
            "unknown" => content.FoundOn is null && content.FoundFrom is null && content.FoundUntil is null,
            "date" => content.FoundOn is not null && content.FoundOn <= DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(now, timezone).DateTime)
                && content.FoundFrom is null && content.FoundUntil is null,
            "exact" => content.FoundOn is null && content.FoundFrom is not null && content.FoundFrom <= now && content.FoundUntil is null,
            "range" => content.FoundOn is null && content.FoundFrom is not null && content.FoundUntil is not null
                && content.FoundFrom <= content.FoundUntil && content.FoundUntil <= now,
            _ => false
        };
        if (!valid) throw new ApiException(400, "Found time is invalid or in the future.");
        item.FoundTimePrecision = content.FoundTimePrecision;
        item.FoundOn = content.FoundOn;
        item.FoundFrom = content.FoundFrom?.ToUniversalTime();
        item.FoundUntil = content.FoundUntil?.ToUniversalTime();
        item.FoundTimezone = content.FoundTimezone;
        var questions = content.VerificationQuestions ?? [];
        if (questions.Count > 3) throw new ApiException(400, "At most three verification questions are allowed.");
        repository.ReplaceQuestions(item, questions.Select(question => RecoveryWorkflow.Text(question, 500, "Question")).ToList());
    }
    public async Task<CustodyEventResponse> ReturnAsync(Guid actor, Guid key, Guid id, ReturnItemRequest request, CancellationToken ct)
    {
        var eventId = await workflow.WriteAsync(actor, key, $"item.return:{id}", request, "custody_event", 201, async () =>
        {
            var item = await workflow.ItemAsync(id, true, ct);
            if (item.CustodyKind == "point")
            {
                if (!await repository.PointPermissionAsync(actor, item.HolderPointId!.Value, false, ct))
                    throw new ApiException(403, "Returning permission at this point is required.");
                if (request.ClaimId is not null) throw new ApiException(400, "Point handovers do not use claims.");
                _ = RecoveryWorkflow.Text(request.VerificationNote, 2000, "Direct verification note");
            }
            else await workflow.RequireManagerAsync(item, actor, ct);
            RecoveryWorkflow.RequireActive(item);
            RecoveryWorkflow.RequireVersion(item, request.RowVersion);
            if (!request.ConfirmedPhysicalHandover) throw new ApiException(400, "Confirm the verified physical handover.");
            var recipient = request.RecipientUserId;
            if (item.CustodyKind == "person")
            {
                var claim = request.ClaimId is { } claimId ? await repository.ClaimAsync(claimId, ct) : null;
                if (claim is null || claim.ItemId != id || claim.Status != "approved" || claim.ReviewerUserId != actor
                    || claim.SourceCustodyVersion != item.CustodyVersion) throw new ApiException(409, "A current approved claim for this item is required.");
                if (recipient is not null && recipient != claim.ClaimantUserId) throw new ApiException(400, "Recipient must match the claim.");
                recipient = claim.ClaimantUserId;
            }
            else if (request.ClaimId is not null) throw new ApiException(400, "This custody kind does not use claims.");
            if (recipient is { } user && !await repository.ActiveUserAsync(user, ct)) throw new ApiException(400, "Recipient is unavailable.");
            var from = RecoveryWorkflow.CustodySnapshot(item);
            item.Lifecycle = "returned";
            var result = Guid.NewGuid();
            workflow.Changed(item, custody: true);
            workflow.Event(item, actor, "returned", from, claim: request.ClaimId, recipient: recipient,
                note: request.VerificationNote, id: result);
            return result;
        }, ct);
        var value = await repository.EventAsync(eventId, ct) ?? throw new ApiException(404, "Handover not found.");
        var current = await workflow.ItemAsync(id, false, ct);
        if (current.CustodyKind == "point")
        {
            if (!await repository.PointPermissionAsync(actor, current.HolderPointId!.Value, false, ct)) throw new ApiException(403, "Returning permission was revoked.");
        }
        else await workflow.RequireManagerAsync(current, actor, ct);
        return EventResponse(value);
    }
    public async Task<PageResponse<CustodyEventResponse>> EventsAsync(Guid actor, Guid id, int page, int size, CancellationToken ct)
    {
        var item = await workflow.ItemAsync(id, false, ct);
        if (item.PostedBy != actor && !await workflow.CanManageAsync(item, actor, ct)
            && !(item.HolderPointId is { } point && await repository.PointPermissionAsync(actor, point, false, ct)))
            throw new ApiException(403, "Custody history is private to the custodian and author.");
        var (items, totalCount) = await repository.EventsAsync(id, page, size, ct);
        return RecoveryWorkflow.Page(items.Select(EventResponse).ToList(), page, size, totalCount);
    }
    private static CustodyEventResponse EventResponse(CustodyEvent value) => new(value.Id, value.ItemId, value.EventKind, value.CustodyVersion, value.OccurredAt);
}
