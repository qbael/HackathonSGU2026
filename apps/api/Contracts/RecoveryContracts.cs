using System.ComponentModel.DataAnnotations;

namespace Findie.Api.Contracts;

public sealed record PageResponse<T>(IReadOnlyList<T> Items, int Page, int PageSize, bool HasMore, int TotalPages);

public sealed class ItemFilter
{
    [StringLength(200)] public string? Q { get; set; }
    [StringLength(200)] public string? Area { get; set; }
    public DateOnly? From { get; set; }
    public DateOnly? Until { get; set; }
    public Guid? PointId { get; set; }
    [RegularExpression("^(public|mine|managed)$")] public string Scope { get; set; } = "public";
    [Range(1, 10000)] public int Page { get; set; } = 1;
    [Range(1, 100)] public int PageSize { get; set; } = 20;
}

public sealed record CustodyInput(
    [Required, RegularExpression("^(person|point|external)$")] string Kind,
    Guid? PointId = null,
    [StringLength(200)] string? Name = null,
    [StringLength(500)] string? Address = null,
    [StringLength(2000)] string? Instructions = null,
    bool ConfirmedPhysicalReceipt = false);

public sealed record ItemInput(
    [Required, StringLength(200)] string Title,
    [Required, StringLength(5000)] string PublicDescription,
    [Required, StringLength(200)] string FoundArea,
    [Required, RegularExpression("^(unknown|date|exact|range)$")] string FoundTimePrecision,
    DateOnly? FoundOn = null,
    DateTimeOffset? FoundFrom = null,
    DateTimeOffset? FoundUntil = null,
    [Required, StringLength(100)] string FoundTimezone = "Asia/Ho_Chi_Minh",
    IReadOnlyList<string>? VerificationQuestions = null);

public sealed record CreateItemRequest([Required] ItemInput Content, [Required] CustodyInput Custody);
public sealed record UpdateItemRequest([Range(1, long.MaxValue)] long RowVersion, [Required] ItemInput Content);
public sealed record DeleteItemRequest([Range(1, long.MaxValue)] long RowVersion);
public sealed record PublicationRequest([Range(1, long.MaxValue)] long RowVersion,
    [Required, RegularExpression("^(published|hidden)$")] string State);

public sealed record CustodyResponse(string Kind, string? DisplayName, Guid? PointId, string? Name,
    string? PublicAddress, string? Instructions);
public sealed record ImageSummary(Guid Id, short Position, long ContentVersion, string Url);
public sealed record ItemResponse(Guid Id, string Title, string PublicDescription, string FoundArea,
    string FoundTimePrecision, DateOnly? FoundOn, DateTimeOffset? FoundFrom, DateTimeOffset? FoundUntil,
    string FoundTimezone, CustodyResponse Custody, string Lifecycle, string PublicationState,
    long RowVersion, long DocumentVersion, DateTimeOffset CreatedAt, IReadOnlyList<ImageSummary> Images, bool CanClaim, bool CanDelete);
public sealed record QuestionResponse(short Slot, string QuestionText);
public sealed record QuestionSetResponse(long ContentVersion, IReadOnlyList<QuestionResponse> Questions);

public sealed record ClaimAnswerInput([Range(1, 3)] short Slot, [StringLength(2000)] string? AnswerText);
public sealed record CreateClaimRequest([Range(1, long.MaxValue)] long ContentVersion, IReadOnlyList<ClaimAnswerInput>? Answers = null);
public sealed record DecisionRequest([Required, RegularExpression("^(approved|rejected)$")] string Decision,
    [StringLength(2000)] string? Note = null);
public sealed record ClaimAnswerResponse(short Slot, string QuestionText, string? AnswerText);
public sealed record ClaimResponse(Guid Id, Guid ItemId, Guid ClaimantUserId, Guid ReviewerUserId,
    string Status, bool Stale, DateTimeOffset CreatedAt, DateTimeOffset? DecidedAt, string? DecisionNote,
    Guid? ConversationId, IReadOnlyList<ClaimAnswerResponse> Answers);
public sealed record ConversationResponse(Guid Id, Guid ItemId, Guid ClaimantUserId, Guid ReviewerUserId,
    bool CanSend, DateTimeOffset CreatedAt);
public sealed record SendMessageRequest(Guid ClientMessageId, [Required, StringLength(4000)] string Body);
public sealed record MessageResponse(Guid Id, Guid ConversationId, Guid SenderUserId, Guid ClientMessageId,
    long Sequence, string Body, DateTimeOffset CreatedAt);
public sealed record MessagePage(IReadOnlyList<MessageResponse> Items, long NextAfter, bool HasMore);

public sealed record CreateIntakeRequest(Guid TargetPointId, [Range(1, long.MaxValue)] long RowVersion);
public sealed record IntakeDecisionRequest([Required, RegularExpression("^(received|rejected)$")] string Decision,
    [Range(1, long.MaxValue)] long RowVersion, bool ConfirmedPhysicalReceipt = false,
    [StringLength(2000)] string? Note = null);
public sealed record IntakeResponse(Guid Id, Guid ItemId, Guid RequestedBy, Guid TargetPointId,
    string Status, bool Stale, DateTimeOffset CreatedAt, DateTimeOffset? DecidedAt, string? DecisionNote, long ItemRowVersion);
public sealed record ReturnItemRequest([Range(1, long.MaxValue)] long RowVersion,
    bool ConfirmedPhysicalHandover, Guid? ClaimId = null, Guid? RecipientUserId = null,
    [StringLength(2000)] string? VerificationNote = null);
public sealed record CustodyEventResponse(Guid Id, Guid ItemId, string EventKind, long CustodyVersion,
    DateTimeOffset OccurredAt);

public sealed record ImageResponse(Guid Id, Guid ItemId, short Position, long ContentVersion,
    string ProcessingState, string ReviewState, string? FailureCode, string? PreviewUrl);
public sealed record ReviewImageRequest([Range(1, long.MaxValue)] long ContentVersion,
    [Required, RegularExpression("^(approved|rejected)$")] string Decision);
public sealed record RetireImageRequest([Range(1, long.MaxValue)] long ContentVersion);

public sealed record SearchRequest([Required, StringLength(2000)] string Text,
    [StringLength(200)] string? Area = null, DateOnly? From = null, DateOnly? Until = null,
    [Range(1, 10)] int Limit = 10, [StringLength(33)] string? LostAt = null);
public sealed class ImageSearchFilter
{
    [StringLength(200)] public string? Area { get; set; }
    public DateOnly? From { get; set; }
    public DateOnly? Until { get; set; }
    [StringLength(33)] public string? LostAt { get; set; }
    [Range(1, 10)] public int Limit { get; set; } = 10;
}
public sealed record SearchHit(int Rank, ItemResponse Item);
public sealed record SearchResponse(IReadOnlyList<SearchHit> Items, string Mode, string SearchProfileId,
    int SearchProfileVersion, bool Partial, bool FiltersRelaxed, string FallbackUrl);
