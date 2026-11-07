using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Findie.Api.Controllers.Admin;

[ApiController]
[Authorize(Policy = "AdminOnly")]
public abstract class AdminControllerBase : ControllerBase
{
    protected Guid Actor => Guid.TryParse(User.FindFirstValue(ClaimTypes.NameIdentifier), out var id) ? id : Guid.Empty;
}
