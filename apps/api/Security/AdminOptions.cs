namespace Findie.Api.Security;

public sealed class AdminOptions
{
    public HashSet<string> Emails { get; } = new(StringComparer.OrdinalIgnoreCase);

    public AdminOptions(string? emailsConfig)
    {
        if (string.IsNullOrWhiteSpace(emailsConfig)) return;
        foreach (var email in emailsConfig.Split([',', ';', ' '], StringSplitOptions.RemoveEmptyEntries))
        {
            var trimmed = email.Trim();
            if (!string.IsNullOrEmpty(trimmed))
                Emails.Add(trimmed);
        }
    }

    public bool IsAdmin(string? email) =>
        !string.IsNullOrWhiteSpace(email) && Emails.Contains(email.Trim());
}
