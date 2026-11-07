using Findie.Api.Contracts;
using Findie.Api.Data;
using Findie.Api.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Controllers.Admin;

[Route("api/admin/points")]
public sealed class AdminPointsController(FindieDbContext database) : AdminControllerBase
{
    [HttpGet]
    public async Task<ActionResult<IReadOnlyList<AdminPointResponse>>> GetPoints(CancellationToken cancellationToken)
    {
        var points = await database.ReceptionPoints
            .AsNoTracking()
            .OrderBy(p => p.Name)
            .Select(p => new
            {
                p.Id,
                p.Name,
                p.PublicAddress,
                p.Directions,
                p.Active,
                p.CreatedAt,
                StaffCount = database.PointStaff.Count(s => s.PointId == p.Id && s.RevokedAt == null),
                ItemsCount = database.Items.Count(i => i.HolderPointId == p.Id && i.Lifecycle == "active")
            })
            .ToListAsync(cancellationToken);

        var result = points.Select(p => new AdminPointResponse(
            Id: p.Id,
            Name: p.Name,
            PublicAddress: p.PublicAddress,
            Directions: p.Directions,
            Active: p.Active,
            CreatedAt: p.CreatedAt,
            StaffCount: p.StaffCount,
            ItemsCount: p.ItemsCount
        )).ToList();

        return Ok(result);
    }

    [HttpPost]
    public async Task<ActionResult<AdminPointResponse>> CreatePoint([FromBody] CreatePointRequest request, CancellationToken cancellationToken)
    {
        var name = request.Name.Trim();
        var address = request.PublicAddress.Trim();
        if (string.IsNullOrEmpty(name))
            return BadRequest(new ProblemDetails { Status = 400, Title = "Tên trạm tiếp nhận không được để trống." });
        if (string.IsNullOrEmpty(address))
            return BadRequest(new ProblemDetails { Status = 400, Title = "Địa chỉ trạm tiếp nhận không được để trống." });

        var point = new ReceptionPoint
        {
            Id = Guid.NewGuid(),
            Name = name,
            PublicAddress = address,
            Directions = string.IsNullOrWhiteSpace(request.Directions) ? null : request.Directions.Trim(),
            Active = true,
            CreatedAt = DateTimeOffset.UtcNow
        };

        database.ReceptionPoints.Add(point);
        await database.SaveChangesAsync(cancellationToken);

        return Created($"/api/admin/points/{point.Id}", new AdminPointResponse(
            Id: point.Id,
            Name: point.Name,
            PublicAddress: point.PublicAddress,
            Directions: point.Directions,
            Active: point.Active,
            CreatedAt: point.CreatedAt,
            StaffCount: 0,
            ItemsCount: 0
        ));
    }

    [HttpPatch("{id:guid}/toggle")]
    [HttpPost("{id:guid}/toggle")]
    public async Task<ActionResult<AdminPointResponse>> TogglePoint(Guid id, CancellationToken cancellationToken)
    {
        var point = await database.ReceptionPoints.SingleOrDefaultAsync(p => p.Id == id, cancellationToken);
        if (point is null)
            return NotFound(new ProblemDetails { Status = 404, Title = "Không tìm thấy trạm tiếp nhận." });

        point.Active = !point.Active;
        await database.SaveChangesAsync(cancellationToken);

        var staffCount = await database.PointStaff.CountAsync(s => s.PointId == point.Id && s.RevokedAt == null, cancellationToken);
        var itemsCount = await database.Items.CountAsync(i => i.HolderPointId == point.Id && i.Lifecycle == "active", cancellationToken);

        return Ok(new AdminPointResponse(
            Id: point.Id,
            Name: point.Name,
            PublicAddress: point.PublicAddress,
            Directions: point.Directions,
            Active: point.Active,
            CreatedAt: point.CreatedAt,
            StaffCount: staffCount,
            ItemsCount: itemsCount
        ));
    }

    [HttpGet("{id:guid}/staff")]
    public async Task<ActionResult<IReadOnlyList<AdminStaffResponse>>> GetStaff(Guid id, CancellationToken cancellationToken)
    {
        var pointExists = await database.ReceptionPoints.AnyAsync(p => p.Id == id, cancellationToken);
        if (!pointExists)
            return NotFound(new ProblemDetails { Status = 404, Title = "Không tìm thấy trạm tiếp nhận." });

        var staffMembers = await database.PointStaff
            .AsNoTracking()
            .Where(s => s.PointId == id)
            .Include(s => s.User)
            .OrderByDescending(s => s.AssignedAt)
            .Select(s => new AdminStaffResponse(
                s.PointId,
                s.UserId,
                s.User.Email,
                s.User.DisplayName,
                s.CanReceive,
                s.CanReturn,
                s.AssignedAt,
                s.RevokedAt
            ))
            .ToListAsync(cancellationToken);

        return Ok(staffMembers);
    }

    [HttpPost("{id:guid}/staff")]
    public async Task<ActionResult<AdminStaffResponse>> AssignStaff(Guid id, [FromBody] AssignStaffRequest request, CancellationToken cancellationToken)
    {
        if (!request.CanReceive && !request.CanReturn)
            return BadRequest(new ProblemDetails { Status = 400, Title = "Nhân viên trạm phải có ít nhất quyền Tiếp nhận hoặc Trao trả." });

        var point = await database.ReceptionPoints.SingleOrDefaultAsync(p => p.Id == id, cancellationToken);
        if (point is null)
            return NotFound(new ProblemDetails { Status = 404, Title = "Không tìm thấy trạm tiếp nhận." });

        var normalizedEmail = request.UserEmail.Trim().ToUpperInvariant();
        var user = await database.Users.SingleOrDefaultAsync(u => u.NormalizedEmail == normalizedEmail, cancellationToken);
        if (user is null)
            return NotFound(new ProblemDetails { Status = 404, Title = $"Không tìm thấy người dùng với email '{request.UserEmail}'." });

        var staff = await database.PointStaff.SingleOrDefaultAsync(s => s.PointId == id && s.UserId == user.Id, cancellationToken);
        if (staff is not null)
        {
            staff.CanReceive = request.CanReceive;
            staff.CanReturn = request.CanReturn;
            staff.RevokedAt = null;
            staff.AssignedAt = DateTimeOffset.UtcNow;
        }
        else
        {
            staff = new PointStaff
            {
                PointId = id,
                UserId = user.Id,
                CanReceive = request.CanReceive,
                CanReturn = request.CanReturn,
                AssignedAt = DateTimeOffset.UtcNow,
                RevokedAt = null
            };
            database.PointStaff.Add(staff);
        }

        await database.SaveChangesAsync(cancellationToken);

        return Ok(new AdminStaffResponse(
            PointId: staff.PointId,
            UserId: user.Id,
            Email: user.Email,
            DisplayName: user.DisplayName,
            CanReceive: staff.CanReceive,
            CanReturn: staff.CanReturn,
            AssignedAt: staff.AssignedAt,
            RevokedAt: staff.RevokedAt
        ));
    }

    [HttpDelete("{id:guid}/staff/{userId:guid}")]
    public async Task<IActionResult> RevokeStaff(Guid id, Guid userId, CancellationToken cancellationToken)
    {
        var staff = await database.PointStaff.SingleOrDefaultAsync(s => s.PointId == id && s.UserId == userId, cancellationToken);
        if (staff is null)
            return NotFound(new ProblemDetails { Status = 404, Title = "Không tìm thấy phân quyền nhân viên tương ứng." });

        staff.RevokedAt = DateTimeOffset.UtcNow;
        await database.SaveChangesAsync(cancellationToken);

        return NoContent();
    }
}
