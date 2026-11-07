using System.Security.Claims;
using Findie.Api.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;

namespace Findie.Api.Controllers;

[ApiController]
[Authorize]
[EnableRateLimiting("business")]
[RequestSizeLimit(65536)]
public abstract class RecoveryController : ControllerBase
{
    protected Guid Actor => Guid.Parse(User.FindFirstValue(ClaimTypes.NameIdentifier)!);
    protected Guid RequestKey => Guid.TryParse(Request.Headers["Idempotency-Key"], out var key) && key != Guid.Empty
        ? key : throw new ApiException(400, "Idempotency-Key must be a nonempty UUID.");
}
