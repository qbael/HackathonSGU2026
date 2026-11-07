using System.Security.Claims;
using Findie.Api.Models;
using Findie.Api.Repositories;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Findie.Api.Services;

public sealed class GoogleAuthService(IUserRepository users, SignInManager<ApplicationUser> signIn) : IGoogleAuthService
{
    public async Task<Guid?> CompleteSignInAsync()
    {
        var login = await signIn.GetExternalLoginInfoAsync();
        if (login?.LoginProvider != GoogleDefaults.AuthenticationScheme
            || !bool.TryParse(login.Principal.FindFirstValue("urn:google:email_verified"), out var emailVerified)
            || !emailVerified)
            return null;

        var user = await users.FindByLoginAsync(login.LoginProvider, login.ProviderKey);
        if (user is null)
        {
            var email = login.Principal.FindFirstValue(ClaimTypes.Email);
            if (string.IsNullOrWhiteSpace(email))
                return null;

            var name = login.Principal.FindFirstValue(ClaimTypes.Name)?.Trim();
            if (string.IsNullOrEmpty(name))
                name = "Findie user";
            user = new ApplicationUser
            {
                UserName = $"google_{Guid.NewGuid():N}",
                Email = email,
                EmailConfirmed = true,
                DisplayName = name[..Math.Min(name.Length, 120)]
            };

            // Never link accounts by matching email; the verified provider key is the identity.
            try
            {
                if (!(await users.CreateWithLoginAsync(user, login)).Succeeded)
                    return null;
            }
            catch (DbUpdateException exception) when (exception.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation })
            {
                return null;
            }
        }
        if (user.DisabledAt is not null)
            return null;

        var result = await signIn.ExternalLoginSignInAsync(login.LoginProvider, login.ProviderKey,
            isPersistent: false, bypassTwoFactor: false);
        return result.Succeeded ? user.Id : null;
    }
}
