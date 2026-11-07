namespace Findie.Api.Models;

public sealed class VerificationQuestion
{
    public Guid ItemId { get; set; }
    public short Slot { get; set; }
    public string QuestionText { get; set; } = string.Empty;
    public Item Item { get; set; } = null!;
}
