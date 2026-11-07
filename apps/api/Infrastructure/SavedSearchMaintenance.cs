using System.Text.Json;
using Findie.Api.Data;
using Findie.Api.Models;
using Findie.Api.Repositories;
using Findie.Api.Services;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Infrastructure;

public sealed class SavedSearchMaintenance(IServiceScopeFactory scopes, IAiGateway ai, IConfiguration configuration,
    ILogger<SavedSearchMaintenance> logger, TimeProvider? timeProvider = null) : BackgroundService
{
    public const double Threshold = 0.85;
    static readonly TimeSpan Interval = TimeSpan.FromHours(1);
    DateTimeOffset Now => (timeProvider ?? TimeProvider.System).GetUtcNow();

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                if (ai.Ready && await CheckOneAsync(stoppingToken)) continue;
            }
            catch (Exception error) when (!stoppingToken.IsCancellationRequested)
            { logger.LogWarning("Saved search schedule deferred ({ErrorType}).", error.GetType().Name); }
            await Task.Delay(TimeSpan.FromSeconds(30), stoppingToken);
        }
    }
    public async Task<bool> CheckOneAsync(CancellationToken ct)
    {
        using var scope = scopes.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
        var repository = scope.ServiceProvider.GetRequiredService<IRecoveryRepository>();
        SavedSearch? job;
        var now = Now;
        await using (var transaction = await db.Database.BeginTransactionAsync(ct))
        {
            job = await db.SavedSearches.FromSqlInterpolated($"""
                SELECT * FROM saved_searches
                WHERE NOT needs_refresh AND next_check_at <= {now} AND (lease_until IS NULL OR lease_until <= {now})
                  AND EXISTS (SELECT 1 FROM app_users WHERE id = saved_searches.user_id AND disabled_at IS NULL)
                ORDER BY next_check_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
                """).SingleOrDefaultAsync(ct);
            if (job is null) return false;
            job.LeaseToken = Guid.NewGuid();
            job.LeaseUntil = now.AddMinutes(2);
            await db.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);
        }
        db.Entry(job).State = EntityState.Detached;
        try
        {
            if (job.ModelId != AiProtocol.Setting(configuration, "EmbeddingModelId")
                || job.ModelRevision != AiProtocol.Setting(configuration, "EmbeddingRevision")
                || job.Dimensions != AiProtocol.EmbeddingDimensions(configuration))
            {
                await db.SavedSearches.Where(value => value.Id == job.Id && value.LeaseToken == job.LeaseToken)
                    .ExecuteUpdateAsync(update => update.SetProperty(value => value.NeedsRefresh, true)
                        .SetProperty(value => value.LeaseToken, (Guid?)null).SetProperty(value => value.LeaseUntil, (DateTimeOffset?)null), ct);
                return true;
            }
            using var images = JsonDocument.Parse(job.ImageEmbeddings);
            var metadata = JsonSerializer.SerializeToElement(new { schemaVersion = 1, modelId = job.ModelId, modelRevision = job.ModelRevision,
                dimensions = job.Dimensions, cacheScope = job.UserId, deadlineAt = DateTimeOffset.UtcNow.AddSeconds(30) }, RecoveryWorkflow.Json);
            var body = JsonSerializer.SerializeToUtf8Bytes(new { text = job.Text, images = images.RootElement, from = job.From,
                until = job.Until, afterItemId = job.AfterItemId }, RecoveryWorkflow.Json);
            MatchPage page;
            try
            {
                await using var reply = await ai.RequestAsync(new AiCommand("search.saved", metadata, body, "application/json"), ct);
                page = ReadPage(reply, job);
                await reply.CompleteAsync();
            }
            finally { Array.Clear(body); }
            await using var transaction = await db.Database.BeginTransactionAsync(ct);
            var current = await db.SavedSearches.FromSqlInterpolated($"SELECT * FROM saved_searches WHERE id = {job.Id} FOR UPDATE")
                .SingleOrDefaultAsync(ct);
            if (current is null || current.LeaseToken != job.LeaseToken || current.LeaseUntil <= Now) return true;
            var ids = page.Candidates.Select(value => value.ItemId).ToArray();
            // Lock source items until commit so withdrawal cannot race notification creation.
            if (ids.Length > 0) await db.Database.ExecuteSqlInterpolatedAsync($"SELECT id FROM items WHERE id = ANY({ids}) ORDER BY id FOR SHARE", ct);
            var items = (await repository.SearchItemsAsync(job.UserId, ids, ct)).ToDictionary(value => value.Item.Id, value => value.Item);
            var existing = await db.SavedSearchMatches.Where(value => value.SavedSearchId == job.Id && ids.Contains(value.ItemId))
                .ToDictionaryAsync(value => value.ItemId, ct);
            foreach (var candidate in page.Candidates)
            {
                if (candidate.Score < Threshold || !items.TryGetValue(candidate.ItemId, out var item) || !RecoveryWorkflow.Public(item)
                    || item.PostedBy == job.UserId || item.HolderUserId == job.UserId || !item.Images.Any(RecoveryWorkflow.PublicImage)
                    || !SearchService.Matches(item, job.From, job.Until)
                    || !candidate.Sources.All(source => SearchService.CurrentSource(item, source.DocumentVersion, source.SourceId,
                        source.SourceVersion, source.Hash, source.Image))) continue;
                if (!existing.TryGetValue(item.Id, out var match))
                {
                    match = new SavedSearchMatch { SavedSearchId = job.Id, ItemId = item.Id, CreatedAt = Now };
                    db.SavedSearchMatches.Add(match);
                }
                match.Score = candidate.Score;
                match.DocumentVersion = item.DocumentVersion;
            }
            var completedAt = Now;
            current.AfterItemId = page.NextAfter;
            current.NextCheckAt = page.NextAfter is null ? completedAt.Add(Interval) : completedAt;
            if (page.NextAfter is null) current.LastCheckedAt = completedAt;
            current.LeaseToken = null;
            current.LeaseUntil = null;
            await db.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);
        }
        catch (Exception error) when (!ct.IsCancellationRequested)
        {
            // Never log query text, embeddings, image data, or dependency response bodies.
            logger.LogWarning("Saved search check deferred ({ErrorType}).", error.GetType().Name);
            db.ChangeTracker.Clear();
            await db.SavedSearches.Where(value => value.Id == job.Id && value.LeaseToken == job.LeaseToken)
                .ExecuteUpdateAsync(update => update.SetProperty(value => value.NextCheckAt, Now.AddMinutes(1))
                    .SetProperty(value => value.LeaseToken, (Guid?)null).SetProperty(value => value.LeaseUntil, (DateTimeOffset?)null), ct);
        }
        return true;
    }
    static MatchPage ReadPage(AiReply reply, SavedSearch job)
    {
        try
        {
            AiProtocol.Require(reply.Metadata, "search.saved");
            if (reply.Metadata.GetProperty("modelId").GetString() != job.ModelId
                || reply.Metadata.GetProperty("modelRevision").GetString() != job.ModelRevision
                || reply.Metadata.GetProperty("dimensions").GetInt32() != job.Dimensions || reply.Body.Length > 1024 * 1024) throw new JsonException();
            using var document = JsonDocument.Parse(reply.Body);
            var rows = document.RootElement.GetProperty("candidates");
            if (rows.ValueKind != JsonValueKind.Array || rows.GetArrayLength() > 100) throw new JsonException();
            using var images = JsonDocument.Parse(job.ImageEmbeddings);
            var hasImages = images.RootElement.GetArrayLength() > 0;
            var candidates = new List<MatchCandidate>();
            var previous = job.AfterItemId?.ToString("D");
            foreach (var row in rows.EnumerateArray())
            {
                var id = row.GetProperty("itemId").GetGuid();
                var score = row.GetProperty("relevanceScore").GetDouble();
                if (id == Guid.Empty || !double.IsFinite(score) || score < 0 || score > 1
                    || previous is not null && StringComparer.Ordinal.Compare(id.ToString("D"), previous) <= 0) throw new JsonException();
                previous = id.ToString("D");
                var sources = new List<MatchSource>();
                foreach (var source in row.GetProperty("sources").EnumerateArray())
                {
                    var kind = source.GetProperty("sourceKind").GetString();
                    var version = source.GetProperty("documentVersion").GetInt64();
                    var sourceVersion = source.GetProperty("sourceVersion").GetInt64();
                    var hash = source.GetProperty("sourceSha256").GetString();
                    var sourceId = source.GetProperty("sourceId").GetGuid();
                    if (kind is not ("image" or "text") || version <= 0 || sourceVersion <= 0 || sourceId == Guid.Empty
                        || hash is not { Length: 64 } || hash.Any(c => c is not (>= '0' and <= '9' or >= 'a' and <= 'f'))) throw new JsonException();
                    sources.Add(new(version, sourceId, sourceVersion, hash, kind == "image"));
                }
                if (sources.Count != (job.Text is null || !hasImages ? 1 : 2)
                    || sources.Any(source => source.Image) != hasImages || sources.Any(source => !source.Image) != (job.Text is not null)) throw new JsonException();
                candidates.Add(new(id, score, sources));
            }
            var cursor = document.RootElement.GetProperty("nextAfter");
            Guid? next = cursor.ValueKind == JsonValueKind.Null ? null : cursor.GetGuid();
            if (next is not null && (candidates.Count != 100 || next != candidates[^1].ItemId)) throw new JsonException();
            return new(candidates, next);
        }
        catch (Exception error) when (AiProtocol.Malformed(error)) { throw new ApiException(502, "Invalid saved search matches."); }
    }
    sealed record MatchSource(long DocumentVersion, Guid SourceId, long SourceVersion, string Hash, bool Image);
    sealed record MatchCandidate(Guid ItemId, double Score, IReadOnlyList<MatchSource> Sources);
    sealed record MatchPage(IReadOnlyList<MatchCandidate> Candidates, Guid? NextAfter);
}
