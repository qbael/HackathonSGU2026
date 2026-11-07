using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace Findie.Api.Data;

public sealed class FindieDbContextFactory : IDesignTimeDbContextFactory<FindieDbContext>
{
    public FindieDbContext CreateDbContext(string[] args)
    {
        var connectionString = Environment.GetEnvironmentVariable("ConnectionStrings__Database");
        if (string.IsNullOrWhiteSpace(connectionString))
            throw new InvalidOperationException("Set ConnectionStrings__Database before running EF tools.");

        return new FindieDbContext(new DbContextOptionsBuilder<FindieDbContext>()
            .UseNpgsql(connectionString).Options);
    }
}
