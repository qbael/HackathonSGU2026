using System.Security.Claims;
using Findie.Api.Repositories;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Authorization;

namespace Findie.Api.Security;

public sealed class ActiveUserRequirement : IAuthorizationRequirement;

public sealed class ActiveUserHandler(IUserRepository users) : AuthorizationHandler<ActiveUserRequirement>
{
    protected override async Task HandleRequirementAsync(AuthorizationHandlerContext context, ActiveUserRequirement requirement)
    {
        if (context.User.Identity?.IsAuthenticated != true
            || context.User.FindFirstValue(ClaimTypes.AuthenticationMethod) != GoogleDefaults.AuthenticationScheme
            || !Guid.TryParse(context.User.FindFirstValue(ClaimTypes.NameIdentifier), out var userId))
            return;

        var cancellationToken = (context.Resource as HttpContext)?.RequestAborted ?? CancellationToken.None;
        var user = await users.GetByIdAsync(userId, cancellationToken);
        if (user is { DisabledAt: null })
            context.Succeed(requirement);
    }
}
