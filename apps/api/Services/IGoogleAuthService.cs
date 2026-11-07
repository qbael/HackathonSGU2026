namespace Findie.Api.Services;

public interface IGoogleAuthService
{
    /// <summary>Completes the external sign-in and returns the signed-in user id, or null when sign-in failed.</summary>
    Task<Guid?> CompleteSignInAsync();
}
