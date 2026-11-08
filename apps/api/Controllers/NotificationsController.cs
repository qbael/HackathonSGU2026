using Findie.Api.Contracts;
using Findie.Api.Repositories;
using Microsoft.AspNetCore.Mvc;

namespace Findie.Api.Controllers;

[Route("api/notifications")]
public sealed class NotificationsController(IRecoveryRepository repository) : RecoveryController
{
    [HttpGet("summary")]
    public async Task<ActionResult<NotificationSummaryResponse>> Summary(CancellationToken ct) =>
        Ok(await repository.NotificationSummaryAsync(Actor, ct));
}
