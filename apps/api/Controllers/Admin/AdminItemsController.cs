using Findie.Api.Contracts;
using Findie.Api.Data;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Controllers.Admin;

[Route("api/admin/items")]
public sealed class AdminItemsController(FindieDbContext database) : AdminControllerBase
{
    [HttpGet]
    public async Task<ActionResult<PageResponse<AdminItemResponse>>> GetItems([FromQuery] AdminItemFilter filter, CancellationToken cancellationToken)
    {
        var page = Math.Max(1, filter.Page);
        var pageSize = Math.Clamp(filter.PageSize, 1, 100);

        var query = database.Items
            .AsNoTracking()
            .Include(i => i.Author)
            .Include(i => i.HolderPoint)
            .Include(i => i.Images.OrderBy(img => img.Position))
            .AsQueryable();

        if (!string.IsNullOrWhiteSpace(filter.Query))
        {
            var search = filter.Query.Trim();
            query = query.Where(i =>
                EF.Functions.ILike(i.Title, $"%{search}%") ||
                EF.Functions.ILike(i.PublicDescription, $"%{search}%") ||
                EF.Functions.ILike(i.FoundArea, $"%{search}%"));
        }

        if (!string.IsNullOrWhiteSpace(filter.Lifecycle))
        {
            query = query.Where(i => i.Lifecycle == filter.Lifecycle);
        }

        if (!string.IsNullOrWhiteSpace(filter.PublicationState))
        {
            query = query.Where(i => i.PublicationState == filter.PublicationState);
        }

        var total = await query.CountAsync(cancellationToken);

        var items = await query
            .OrderByDescending(i => i.CreatedAt)
            .Skip((page - 1) * pageSize)
            .Take(pageSize + 1)
            .ToListAsync(cancellationToken);

        var hasMore = items.Count > pageSize;
        var totalPages = Math.Clamp((int)Math.Ceiling((double)total / pageSize), 1, 10000);
        var pagedItems = items.Take(pageSize).Select(i => new AdminItemResponse(
            Id: i.Id,
            Title: i.Title,
            PublicDescription: i.PublicDescription,
            FoundArea: i.FoundArea,
            FoundTimePrecision: i.FoundTimePrecision,
            FoundOn: i.FoundOn,
            FoundFrom: i.FoundFrom,
            FoundUntil: i.FoundUntil,
            Lifecycle: i.Lifecycle,
            PublicationState: i.PublicationState,
            RowVersion: i.RowVersion,
            CreatedAt: i.CreatedAt,
            UpdatedAt: i.UpdatedAt,
            AuthorId: i.Author.Id,
            AuthorDisplayName: i.Author.DisplayName,
            AuthorEmail: i.Author.Email,
            CustodyKind: i.CustodyKind,
            HolderPointId: i.HolderPointId,
            HolderPointName: i.HolderPoint?.Name,
            Images: i.Images.Select(img => new AdminItemImageSummary(
                Id: img.Id,
                Position: img.Position,
                ContentVersion: img.ContentVersion,
                ProcessingState: img.ProcessingState,
                ReviewState: img.ReviewState,
                FailureCode: img.FailureCode,
                RetiredAt: img.RetiredAt,
                PreviewUrl: $"/api/items/{i.Id}/images/{img.Id}/content",
                RedactionModelId: img.RedactionModelId,
                RedactionProfile: img.RedactionProfile
            )).ToList()
        )).ToList();

        return Ok(new PageResponse<AdminItemResponse>(pagedItems, page, pageSize, hasMore, totalPages));
    }

    [HttpPost("{id:guid}/set-publication")]
    public async Task<ActionResult> SetPublication(Guid id, [FromBody] SetPublicationRequest request, CancellationToken cancellationToken)
    {
        var item = await database.Items.SingleOrDefaultAsync(i => i.Id == id, cancellationToken);
        if (item is null)
            return NotFound(new ProblemDetails { Status = 404, Title = "Không tìm thấy tin đăng." });

        item.PublicationState = request.PublicationState;
        item.RowVersion++;
        item.UpdatedAt = DateTimeOffset.UtcNow;
        await database.SaveChangesAsync(cancellationToken);

        return Ok(new { item.Id, item.PublicationState, item.RowVersion, item.UpdatedAt });
    }

    [HttpPost("{itemId:guid}/images/{imageId:guid}/retire")]
    public async Task<ActionResult> RetireImage(Guid itemId, Guid imageId, CancellationToken cancellationToken)
    {
        var image = await database.ItemImages.SingleOrDefaultAsync(img => img.ItemId == itemId && img.Id == imageId, cancellationToken);
        if (image is null)
            return NotFound(new ProblemDetails { Status = 404, Title = "Không tìm thấy hình ảnh." });

        image.RetiredAt = DateTimeOffset.UtcNow;
        image.ReviewedBy = Actor;
        image.ReviewedAt = DateTimeOffset.UtcNow;
        if (image.ReviewState == "pending")
        {
            image.ReviewState = "rejected";
            image.ProcessingState = "rejected";
        }
        await database.SaveChangesAsync(cancellationToken);

        return Ok(new { image.Id, image.ItemId, image.RetiredAt, image.ReviewState });
    }
}
