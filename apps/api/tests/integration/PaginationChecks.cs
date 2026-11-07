using Findie.Api.Services;

static class PaginationChecks
{
    public static void Run()
    {
        foreach (var (count, page, size, totalPages, hasMore) in new[]
        {
            (0, 1, 10, 1, false),
            (1, 1, 10, 1, false),
            (10, 1, 10, 1, false),
            (11, 1, 10, 2, true),
            (11, 2, 10, 2, false),
            (11, 3, 10, 2, false),
            (100001, 9999, 10, 10000, true),
            (100001, 10000, 10, 10000, false),
            (int.MaxValue, 10000, 100, 10000, false),
        })
        {
            var result = RecoveryWorkflow.Page(Array.Empty<int>(), page, size, count);
            if (result.TotalPages != totalPages || result.HasMore != hasMore || result.Page != page || result.PageSize != size)
                throw new InvalidOperationException($"FAIL: pagination metadata for {count} records at page {page} with size {size}.");
        }
        Console.WriteLine("PASS: pagination totals cover empty, exact, partial, out-of-range and capped pages");
    }
}
