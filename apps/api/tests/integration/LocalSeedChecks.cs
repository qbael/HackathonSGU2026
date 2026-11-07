using Findie.Api.Data;
using Findie.Api.Infrastructure;
using Microsoft.EntityFrameworkCore;

static class LocalSeedChecks
{
    public static async Task RunAsync(FindieDbContext db)
    {
        using var output = new StringWriter();
        var userCount = await db.Users.CountAsync();
        Check(await LocalSeed.RunAsync(db, ["--seed-local", "--staff-email", "not-signed-in@example.test"], output) == 2,
            "missing account asks for Google sign-in");
        Check(await db.Users.CountAsync() == userCount, "seed never invents an account");
        await LocalSeed.RunAsync(db, ["--seed-local"], output);
        var hubIds = Enumerable.Range(1, 6).Select(index => Guid.Parse($"fd000000-0000-0000-0000-{index:D12}")).ToArray();
        Check(await db.ReceptionPoints.CountAsync(point => hubIds.Contains(point.Id)) == 6, "all six Hub seeds are idempotent");
        var point = await db.ReceptionPoints.SingleAsync(value => value.Id == LocalSeed.PointId);
        point.Name = "Keep configured Hub name";
        await db.SaveChangesAsync();
        var user = await db.Users.SingleAsync(value => value.NormalizedEmail == "OWNER@EXAMPLE.TEST");
        var name = user.DisplayName;
        var seed = new[] { "--seed-local", "--staff-email", "OWNER@example.test" };
        Check(await LocalSeed.RunAsync(db, seed, output) == 0 && await LocalSeed.RunAsync(db, seed, output) == 0,
            "existing verified Google user can receive repeated explicit staff grants");
        var staff = await db.PointStaff.SingleAsync(value => value.PointId == LocalSeed.PointId && value.UserId == user.Id);
        Check(await db.PointStaff.CountAsync(value => hubIds.Contains(value.PointId) && value.UserId == user.Id
            && value.CanReceive && value.CanReturn && value.RevokedAt == null) == 6, "staff has receive/return permissions at all six Hubs");
        Check(point.Name == "Keep configured Hub name" && user.DisplayName == name && await db.Users.CountAsync() == userCount,
            "seed preserves Hub configuration and user profiles");
        Check(await LocalSeed.RunAsync(db, ["--seed-local", "--staff-email", "claimant@example.test"], output) == 2,
            "non-Google account is not granted staff permissions");
        var samplePoint = await db.ReceptionPoints.SingleAsync(value => value.Id == hubIds[1]);
        var sampleStaff = await db.PointStaff.SingleAsync(value => value.PointId == samplePoint.Id && value.UserId == user.Id);
        samplePoint.Name = "Keep configured sample Hub";
        samplePoint.Active = false;
        sampleStaff.CanReceive = false;
        point.Active = false;
        staff.CanReceive = false;
        await db.SaveChangesAsync();
        Check(await LocalSeed.RunAsync(db, seed, output) == 2 && !staff.CanReceive && !point.Active
            && !sampleStaff.CanReceive && !samplePoint.Active && samplePoint.Name == "Keep configured sample Hub",
            "seed preserves configured and inactive demo/sample Hubs");
        point.Active = samplePoint.Active = true;
        await db.SaveChangesAsync();
        Console.WriteLine("PASS: local Hub/staff seed is idempotent, keeps profiles and requires an existing active Google user");
    }

    static void Check(bool condition, string description)
    {
        if (!condition) throw new InvalidOperationException("FAIL: " + description);
    }
}
