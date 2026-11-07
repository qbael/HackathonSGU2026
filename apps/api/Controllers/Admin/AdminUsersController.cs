using Findie.Api.Contracts;
using Findie.Api.Data;
using Findie.Api.Security;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Controllers.Admin;

[Route("api/admin/users")]
public sealed class AdminUsersController(FindieDbContext database, AdminOptions adminOptions) : AdminControllerBase
{
    [HttpGet]
    public async Task<ActionResult<PageResponse<AdminUserResponse>>> GetUsers([FromQuery] AdminUserFilter filter, CancellationToken cancellationToken)
    {
        var page = Math.Max(1, filter.Page);
        var pageSize = Math.Clamp(filter.PageSize, 1, 100);

        var query = database.Users.AsNoTracking();

        if (!string.IsNullOrWhiteSpace(filter.Query))
        {
            var search = filter.Query.Trim();
            var upper = search.ToUpperInvariant();
            query = query.Where(u =>
                EF.Functions.ILike(u.DisplayName, $"%{search}%") ||
                (u.NormalizedEmail != null && u.NormalizedEmail.Contains(upper)));
        }

        var total = await query.CountAsync(cancellationToken);

        var users = await query
            .OrderByDescending(u => u.CreatedAt)
            .Skip((page - 1) * pageSize)
            .Take(pageSize + 1)
            .Select(u => new
            {
                u.Id,
                u.Email,
                u.DisplayName,
                u.CreatedAt,
                u.DisabledAt,
                ItemsCount = database.Items.Count(i => i.PostedBy == u.Id)
            })
            .ToListAsync(cancellationToken);

        var hasMore = users.Count > pageSize;
        var totalPages = Math.Clamp((int)Math.Ceiling((double)total / pageSize), 1, 10000);
        var pagedUsers = users.Take(pageSize).Select(u => new AdminUserResponse(
            Id: u.Id,
            Email: u.Email,
            DisplayName: u.DisplayName,
            CreatedAt: u.CreatedAt,
            DisabledAt: u.DisabledAt,
            IsAdmin: adminOptions.IsAdmin(u.Email),
            ItemsCount: u.ItemsCount
        )).ToList();

        return Ok(new PageResponse<AdminUserResponse>(pagedUsers, page, pageSize, hasMore, totalPages));
    }

    [HttpPost("{id:guid}/toggle-status")]
    public async Task<ActionResult<AdminUserResponse>> ToggleStatus(Guid id, CancellationToken cancellationToken)
    {
        if (id == Actor)
            return BadRequest(new ProblemDetails { Status = 400, Title = "Không thể tự vô hiệu hóa tài khoản quản trị của chính mình." });

        var user = await database.Users.SingleOrDefaultAsync(u => u.Id == id, cancellationToken);
        if (user is null)
            return NotFound(new ProblemDetails { Status = 404, Title = "Không tìm thấy người dùng." });

        user.DisabledAt = user.DisabledAt is null ? DateTimeOffset.UtcNow : null;
        await database.SaveChangesAsync(cancellationToken);

        var itemsCount = await database.Items.CountAsync(i => i.PostedBy == user.Id, cancellationToken);

        return Ok(new AdminUserResponse(
            Id: user.Id,
            Email: user.Email,
            DisplayName: user.DisplayName,
            CreatedAt: user.CreatedAt,
            DisabledAt: user.DisabledAt,
            IsAdmin: adminOptions.IsAdmin(user.Email),
            ItemsCount: itemsCount
        ));
    }
}
