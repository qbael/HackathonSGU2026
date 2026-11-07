using Findie.Api.Contracts;
using Findie.Api.Data;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Controllers.Admin;

[Route("api/admin/overview")]
public sealed class AdminOverviewController(FindieDbContext database) : AdminControllerBase
{
    [HttpGet]
    public async Task<ActionResult<AdminOverviewResponse>> GetOverview(CancellationToken cancellationToken)
    {
        var totalItems = await database.Items.CountAsync(cancellationToken);
        var activeItems = await database.Items.CountAsync(i => i.Lifecycle == "active", cancellationToken);
        var returnedItems = await database.Items.CountAsync(i => i.Lifecycle == "returned", cancellationToken);
        var hiddenItems = await database.Items.CountAsync(i => i.PublicationState == "hidden", cancellationToken);

        var totalUsers = await database.Users.CountAsync(cancellationToken);
        var activeUsers = await database.Users.CountAsync(u => u.DisabledAt == null, cancellationToken);
        var disabledUsers = await database.Users.CountAsync(u => u.DisabledAt != null, cancellationToken);

        var totalHubs = await database.ReceptionPoints.CountAsync(cancellationToken);
        var activeHubs = await database.ReceptionPoints.CountAsync(p => p.Active, cancellationToken);

        var totalCustodyEvents = await database.CustodyEvents.CountAsync(cancellationToken);
        var totalHandovers = await database.CustodyEvents.CountAsync(e => e.EventKind == "returned", cancellationToken);

        return Ok(new AdminOverviewResponse(
            TotalItems: totalItems,
            ActiveItems: activeItems,
            ReturnedItems: returnedItems,
            HiddenItems: hiddenItems,
            TotalUsers: totalUsers,
            ActiveUsers: activeUsers,
            DisabledUsers: disabledUsers,
            TotalHubs: totalHubs,
            ActiveHubs: activeHubs,
            TotalCustodyEvents: totalCustodyEvents,
            TotalHandovers: totalHandovers
        ));
    }
}
