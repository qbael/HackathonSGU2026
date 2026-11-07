using System.Net.Mail;
using Findie.Api.Data;
using Findie.Api.Models;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Infrastructure;

public static class LocalSeed
{
    public static readonly Guid PointId = Guid.Parse("fd000000-0000-0000-0000-000000000001");
    static readonly (Guid Id, string Name, string Address)[] Hubs =
    [
        (PointId, "Findie Demo Hub", "Quầy demo Findie (môi trường local)"),
        (Guid.Parse("fd000000-0000-0000-0000-000000000002"), "Findie Hub Mẫu – Thủ Đức", "Quầy giả định khu Thủ Đức, TP. Hồ Chí Minh (môi trường local)"),
        (Guid.Parse("fd000000-0000-0000-0000-000000000003"), "Findie Hub Mẫu – Quận 5", "Quầy giả định khu Quận 5, TP. Hồ Chí Minh (môi trường local)"),
        (Guid.Parse("fd000000-0000-0000-0000-000000000004"), "Findie Hub Mẫu – Bình Thạnh", "Quầy giả định khu Bình Thạnh, TP. Hồ Chí Minh (môi trường local)"),
        (Guid.Parse("fd000000-0000-0000-0000-000000000005"), "Findie Hub Mẫu – Tân Bình", "Quầy giả định khu Tân Bình, TP. Hồ Chí Minh (môi trường local)"),
        (Guid.Parse("fd000000-0000-0000-0000-000000000006"), "Findie Hub Mẫu – Quận 1", "Quầy giả định khu Quận 1, TP. Hồ Chí Minh (môi trường local)")
    ];

    public static async Task<int> RunAsync(FindieDbContext db, string[] args, TextWriter output)
    {
        string? email = null;
        if (args.Length == 3 && args[0] == "--seed-local" && args[1] == "--staff-email"
            && MailAddress.TryCreate(args[2].Trim(), out var address) && address.Address == args[2].Trim())
            email = address.Address;
        else if (args.Length != 1 || args[0] != "--seed-local")
            throw new ArgumentException("Use --seed-local [--staff-email existing-google-user@example.com].");

        await using var transaction = await db.Database.BeginTransactionAsync();
        await db.Database.ExecuteSqlRawAsync("SELECT pg_advisory_xact_lock(643182016)");
        ApplicationUser? user = null;
        if (email is not null)
        {
            var normalized = new UpperInvariantLookupNormalizer().NormalizeEmail(email);
            user = await db.Users.SingleOrDefaultAsync(value => value.NormalizedEmail == normalized
                && value.EmailConfirmed && value.DisabledAt == null
                && db.UserLogins.Any(login => login.UserId == value.Id && login.LoginProvider == GoogleDefaults.AuthenticationScheme));
        }
        var inactive = false;
        foreach (var (id, name, publicAddress) in Hubs)
        {
            var point = await db.ReceptionPoints.FindAsync(id);
            if (point is null)
            {
                point = new ReceptionPoint { Id = id, Name = name, PublicAddress = publicAddress,
                    Directions = "Điểm thử nghiệm giả định; xác nhận địa điểm thật trước khi bàn giao." };
                db.ReceptionPoints.Add(point);
            }
            if (!point.Active) { inactive = true; continue; }
            if (user is null) continue;
            var staff = await db.PointStaff.FindAsync(id, user.Id);
            if (staff is null)
            {
                staff = new PointStaff { PointId = id, UserId = user.Id };
                db.PointStaff.Add(staff);
            }
            staff.CanReceive = staff.CanReturn = true;
            staff.RevokedAt = null;
        }
        await db.SaveChangesAsync();
        await transaction.CommitAsync();
        await output.WriteLineAsync($"Local demo Hubs configured: {Hubs.Length}. Existing Hub and user profiles preserved.");
        if (email is null)
            await output.WriteLineAsync("Sign in with Google, then run make local-seed STAFF_EMAIL=your-email to grant receive/return permissions at active demo Hubs.");
        else if (user is null)
        {
            await output.WriteLineAsync("No active verified Google account found. Sign in first, then repeat the staff seed command.");
            return 2;
        }
        else if (inactive)
        {
            await output.WriteLineAsync("Inactive demo Hubs were preserved; permissions were granted only at active demo Hubs.");
            return 2;
        }
        else await output.WriteLineAsync("Existing Google account has receive/return permissions at all active demo Hubs.");
        return 0;
    }
}
