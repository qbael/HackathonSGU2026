using System.Security.Claims;
using Findie.Api.Repositories;
using Microsoft.AspNetCore.Authorization;

namespace Findie.Api.Security;

public sealed class AdminUserRequirement : IAuthorizationRequirement;

public sealed class AdminUserHandler(IUserRepository users, AdminOptions adminOptions) : AuthorizationHandler<AdminUserRequirement>
{
    protected override async Task HandleRequirementAsync(AuthorizationHandlerContext context, AdminUserRequirement requirement)
    {
        if (context.User.Identity?.IsAuthenticated != true
            || !Guid.TryParse(context.User.FindFirstValue(ClaimTypes.NameIdentifier), out var userId))
            return;

        var cancellationToken = (context.Resource as HttpContext)?.RequestAborted ?? CancellationToken.None;
        var user = await users.GetByIdAsync(userId, cancellationToken);
        if (user is { DisabledAt: null } && adminOptions.IsAdmin(user.Email))
            context.Succeed(requirement);
    }
}
