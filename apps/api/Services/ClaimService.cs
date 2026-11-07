using Findie.Api.Contracts;
using Findie.Api.Models;
using Findie.Api.Repositories;

namespace Findie.Api.Services;

public interface IClaimService
{
    Task<ClaimResponse> CreateAsync(Guid actor, Guid key, Guid itemId, CreateClaimRequest request, CancellationToken ct);
    Task<ClaimResponse> GetAsync(Guid actor, Guid id, CancellationToken ct);
    Task<PageResponse<ClaimResponse>> ListAsync(Guid actor, Guid? itemId, int page, int size, CancellationToken ct);
    Task<ClaimResponse> DecideAsync(Guid actor, Guid key, Guid id, DecisionRequest request, CancellationToken ct);
}

public sealed class ClaimService(IRecoveryRepository repository, RecoveryWorkflow workflow) : IClaimService
{
    public async Task<ClaimResponse> CreateAsync(Guid actor, Guid key, Guid itemId, CreateClaimRequest request, CancellationToken ct)
    {
        var id = await workflow.WriteAsync(actor, key, $"claim.create:{itemId}", request, "claim", 201, async () =>
        {
            var item = await workflow.ItemAsync(itemId, true, ct);
            if (!RecoveryWorkflow.Public(item)) throw new ApiException(404, "Item is not available.");
            if (item.CustodyKind != "person") throw new ApiException(409, "Claims apply only to items held by a person.");
            if (item.PostedBy == actor || item.HolderUserId == actor) throw new ApiException(400, "The author or holder cannot claim their own item.");
            if (item.ContentVersion != request.ContentVersion) throw new ApiException(409, "The questions changed; reload them before submitting your answers.");
            if (await repository.ExistingClaimAsync(actor, item, ct)) throw new ApiException(409, "An active claim already exists.");
            var answers = request.Answers ?? [];
            if (answers.Count > 3 || answers.Select(answer => answer?.Slot).Distinct().Count() != answers.Count
                || answers.Any(answer => answer is null || item.VerificationQuestions.All(question => question.Slot != answer.Slot)))
                throw new ApiException(400, "Answers must use distinct slots from the current questions.");
            var claim = new Claim { ItemId = itemId, ClaimantUserId = actor, ReviewerUserId = item.HolderUserId!.Value,
                SourceCustodyVersion = item.CustodyVersion };
            foreach (var question in item.VerificationQuestions.OrderBy(question => question.Slot))
            {
                var answer = RecoveryWorkflow.Optional(answers.SingleOrDefault(value => value.Slot == question.Slot)?.AnswerText);
                if (answer?.Length > 2000) throw new ApiException(400, "Answer exceeds 2000 characters.");
                claim.Answers.Add(new ClaimAnswer { Slot = question.Slot, QuestionTextSnapshot = question.QuestionText, AnswerText = answer });
            }
            repository.Add(claim);
            return claim.Id;
        }, ct);
        return await GetAsync(actor, id, ct);
    }
    public async Task<ClaimResponse> GetAsync(Guid actor, Guid id, CancellationToken ct)
    {
        var claim = await repository.ClaimAsync(id, ct) ?? throw new ApiException(404, "Claim not found.");
        if (claim.ClaimantUserId != actor && !(claim.ReviewerUserId == actor && claim.Item.HolderUserId == actor
            && claim.Item.CustodyVersion == claim.SourceCustodyVersion)) throw new ApiException(404, "Claim not found.");
        return Response(claim);
    }
    public async Task<PageResponse<ClaimResponse>> ListAsync(Guid actor, Guid? itemId, int page, int size, CancellationToken ct)
    {
        var (items, totalCount) = await repository.ClaimsAsync(actor, itemId, page, size, ct);
        return RecoveryWorkflow.Page(items.Select(Response).ToList(), page, size, totalCount);
    }
    public async Task<ClaimResponse> DecideAsync(Guid actor, Guid key, Guid id, DecisionRequest request, CancellationToken ct)
    {
        await workflow.WriteAsync(actor, key, $"claim.decide:{id}", request, "claim", 200, async () =>
        {
            var claim = await repository.ClaimAsync(id, ct) ?? throw new ApiException(404, "Claim not found.");
            var item = await workflow.ItemAsync(claim.ItemId, true, ct);
            claim = (await repository.ClaimAsync(id, ct))!;
            if (claim.ReviewerUserId != actor || item.HolderUserId != actor) throw new ApiException(403, "Only the current claim reviewer may decide.");
            RecoveryWorkflow.RequireActive(item);
            if (claim.SourceCustodyVersion != item.CustodyVersion || claim.Status != "pending")
                throw new ApiException(409, "This claim is stale or has already been decided.");
            await repository.DecideClaimAsync(id, actor, request.Decision, RecoveryWorkflow.Optional(request.Note), DateTimeOffset.UtcNow, ct);
            if (request.Decision == "approved") repository.Add(new Conversation { ClaimId = id });
            return id;
        }, ct);
        return await GetAsync(actor, id, ct);
    }
    private static ClaimResponse Response(Claim claim) => new(claim.Id, claim.ItemId, claim.ClaimantUserId, claim.ReviewerUserId,
        claim.Status, claim.Item.CustodyVersion != claim.SourceCustodyVersion || claim.Item.Lifecycle != "active",
        claim.CreatedAt, claim.DecidedAt, claim.DecisionNote, claim.Conversation?.ClaimId,
        claim.Answers.OrderBy(answer => answer.Slot).Select(answer => new ClaimAnswerResponse(answer.Slot, answer.QuestionTextSnapshot, answer.AnswerText)).ToList());
}
