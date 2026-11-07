using Findie.Api.Contracts;
using Findie.Api.Models;
using Findie.Api.Repositories;

namespace Findie.Api.Services;

public interface IIntakeService
{
    Task<IntakeResponse> CreateAsync(Guid actor, Guid key, Guid itemId, CreateIntakeRequest request, CancellationToken ct);
    Task<IntakeResponse> GetAsync(Guid actor, Guid id, CancellationToken ct);
    Task<PageResponse<IntakeResponse>> ListAsync(Guid actor, Guid? pointId, int page, int size, CancellationToken ct);
    Task<IntakeResponse> DecideAsync(Guid actor, Guid key, Guid id, IntakeDecisionRequest request, CancellationToken ct);
}

public sealed class IntakeService(IRecoveryRepository repository, RecoveryWorkflow workflow) : IIntakeService
{
    public async Task<IntakeResponse> CreateAsync(Guid actor, Guid key, Guid itemId, CreateIntakeRequest request, CancellationToken ct)
    {
        var id = await workflow.WriteAsync(actor, key, $"intake.create:{itemId}", request, "intake", 201, async () =>
        {
            var item = await workflow.ItemAsync(itemId, true, ct);
            await workflow.RequireManagerAsync(item, actor, ct);
            RecoveryWorkflow.RequireActive(item);
            RecoveryWorkflow.RequireVersion(item, request.RowVersion);
            if (item.HolderPointId == request.TargetPointId) throw new ApiException(409, "This point already holds the item.");
            if (await repository.PointAsync(request.TargetPointId, ct) is null) throw new ApiException(400, "Reception point is unavailable.");
            if (await repository.ExistingIntakeAsync(item, request.TargetPointId, ct)) throw new ApiException(409, "A pending intake already exists.");
            var intake = new IntakeRequest { ItemId = itemId, RequestedBy = actor, TargetPointId = request.TargetPointId,
                SourceCustodyVersion = item.CustodyVersion };
            repository.Add(intake);
            return intake.Id;
        }, ct);
        return await GetAsync(actor, id, ct);
    }
    public async Task<IntakeResponse> GetAsync(Guid actor, Guid id, CancellationToken ct)
    {
        var intake = await repository.IntakeAsync(id, ct) ?? throw new ApiException(404, "Intake not found.");
        if (intake.RequestedBy != actor && !await repository.PointPermissionAsync(actor, intake.TargetPointId, true, ct))
            throw new ApiException(404, "Intake not found.");
        return Response(intake);
    }
    public async Task<PageResponse<IntakeResponse>> ListAsync(Guid actor, Guid? pointId, int page, int size, CancellationToken ct)
    {
        var (items, totalCount) = await repository.IntakesAsync(actor, pointId, page, size, ct);
        return RecoveryWorkflow.Page(items.Select(Response).ToList(), page, size, totalCount);
    }
    public async Task<IntakeResponse> DecideAsync(Guid actor, Guid key, Guid id, IntakeDecisionRequest request, CancellationToken ct)
    {
        await workflow.WriteAsync(actor, key, $"intake.decide:{id}", request, "intake", 200, async () =>
        {
            var intake = await repository.IntakeAsync(id, ct) ?? throw new ApiException(404, "Intake not found.");
            var item = await workflow.ItemAsync(intake.ItemId, true, ct);
            intake = (await repository.IntakeAsync(id, ct))!;
            if (!await repository.PointPermissionAsync(actor, intake.TargetPointId, true, ct)) throw new ApiException(403, "Receiving permission at the target point is required.");
            RecoveryWorkflow.RequireActive(item);
            RecoveryWorkflow.RequireVersion(item, request.RowVersion);
            if (intake.Status != "pending" || intake.SourceCustodyVersion != item.CustodyVersion)
                throw new ApiException(409, "This intake is stale or has already been decided.");
            if (request.Decision == "received" && !request.ConfirmedPhysicalReceipt)
                throw new ApiException(400, "Confirm physical receipt before changing custody.");
            await repository.DecideIntakeAsync(id, actor, request.Decision, RecoveryWorkflow.Optional(request.Note), ct);
            if (request.Decision == "received")
            {
                var from = RecoveryWorkflow.CustodySnapshot(item);
                item.CustodyKind = "point";
                item.HolderUserId = null;
                item.HolderUser = null;
                item.HolderPointId = intake.TargetPointId;
                item.HolderPoint = await repository.PointAsync(intake.TargetPointId, ct);
                item.ExternalName = item.ExternalPublicAddress = item.ExternalInstructions = null;
                workflow.Changed(item, custody: true);
                workflow.Event(item, actor, "received", from, intake: id);
            }
            return id;
        }, ct);
        return await GetAsync(actor, id, ct);
    }
    private static IntakeResponse Response(IntakeRequest intake) => new(intake.Id, intake.ItemId, intake.RequestedBy, intake.TargetPointId,
        intake.Status, intake.Status == "pending" && (intake.Item.CustodyVersion != intake.SourceCustodyVersion || intake.Item.Lifecycle != "active"),
        intake.CreatedAt, intake.DecidedAt, intake.DecisionNote, intake.Item.RowVersion);
}
