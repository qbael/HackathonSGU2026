namespace Findie.Api.Models;

public sealed class ClaimAnswer
{
    public Guid ClaimId { get; set; }
    public short Slot { get; set; }
    public string QuestionTextSnapshot { get; set; } = string.Empty;
    public string? AnswerText { get; set; }
    public Claim Claim { get; set; } = null!;
}
