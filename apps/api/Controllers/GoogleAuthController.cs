using Findie.Api.Models;
using Findie.Api.Services;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;

namespace Findie.Api.Controllers;

[ApiController]
[Route("api/auth/google")]
public sealed class GoogleAuthController(
    IGoogleAuthService authentication,
    IUserService users,
    SignInManager<ApplicationUser> signIn,
    IAuthenticationSchemeProvider schemes) : ControllerBase
{
    [HttpGet]
    public async Task<IActionResult> Login([FromQuery] string returnUrl = "/")
    {
        if (string.IsNullOrWhiteSpace(returnUrl))
            returnUrl = "/";
        if (!Url.IsLocalUrl(returnUrl))
            return Problem(statusCode: 400, title: "Return URL must be a local path.");
        if (await schemes.GetSchemeAsync(GoogleDefaults.AuthenticationScheme) is null)
            return Problem(statusCode: 503, title: "Google authentication is not configured.");

        await HttpContext.SignOutAsync(IdentityConstants.ExternalScheme);
        var callback = Url.Action(nameof(Callback), new { returnUrl })!;
        return Challenge(signIn.ConfigureExternalAuthenticationProperties(GoogleDefaults.AuthenticationScheme, callback),
            GoogleDefaults.AuthenticationScheme);
    }

    [HttpGet("callback")]
    public async Task<IActionResult> Callback([FromQuery] string returnUrl = "/", CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(returnUrl))
            returnUrl = "/";
        if (!Url.IsLocalUrl(returnUrl))
            return Problem(statusCode: 400, title: "Return URL must be a local path.");
        try
        {
            if (await authentication.CompleteSignInAsync() is not { } userId)
                return Problem(statusCode: 401, title: "Google authentication failed.");
            if (returnUrl != "/")
                return LocalRedirect(returnUrl);

            // Direct sign-ins land in the workspace matching the account's role; deep links are never overridden.
            var profile = await users.GetProfileAsync(userId, cancellationToken);
            return LocalRedirect(profile switch
            {
                { IsAdmin: true } => "/admin",
                { IsStaff: true } => "/hub",
                _ => "/"
            });
        }
        finally
        {
            await HttpContext.SignOutAsync(IdentityConstants.ExternalScheme);
        }
    }
}
