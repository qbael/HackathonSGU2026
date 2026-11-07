using System.Security.Claims;
using Findie.Api.Contracts;
using Findie.Api.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Controllers;

[ApiController]
[Authorize]
[Route("api/users")]
public sealed class UsersController(IUserService users) : ControllerBase
{
    [HttpGet("me")]
    public async Task<ActionResult<UserProfile>> Me(CancellationToken cancellationToken)
    {
        var profile = await users.GetProfileAsync(Guid.Parse(User.FindFirstValue(ClaimTypes.NameIdentifier)!), cancellationToken);
        return profile is null ? Unauthorized() : Ok(profile);
    }

    [HttpPut("me")]
    public async Task<ActionResult<UserProfile>> UpdateMe(UpdateUserRequest request, CancellationToken cancellationToken)
    {
        try
        {
            var profile = await users.UpdateProfileAsync(Guid.Parse(User.FindFirstValue(ClaimTypes.NameIdentifier)!), request, cancellationToken);
            return profile is null ? Unauthorized() : Ok(profile);
        }
        catch (ArgumentException exception)
        {
            ModelState.AddModelError(nameof(request.DisplayName), exception.Message);
            return ValidationProblem(ModelState);
        }
        catch (DbUpdateConcurrencyException)
        {
            return Problem(statusCode: 409, title: "The profile changed; reload before saving.");
        }
    }
}
