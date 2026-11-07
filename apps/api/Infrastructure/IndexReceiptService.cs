using System.Text.Json;
using Findie.Api.Data;
using Findie.Api.Services;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Infrastructure;

public sealed class IndexReceiptService(FindieDbContext db, IConfiguration configuration)
{
    public async Task AcceptAsync(JsonElement metadata, CancellationToken ct)
    {
        try
        {
            var id = metadata.GetProperty("jobId").GetGuid();
            var source = await db.IndexOutbox.AsNoTracking().SingleOrDefaultAsync(value => value.Id == id, ct);
            if (source is null) return;
            AiProtocol.Require(metadata, source.EventKind == "snapshot" ? "index.upsert" : "index.remove");
            if (metadata.GetProperty("itemId").GetGuid() != source.ItemId
                || metadata.GetProperty("documentVersion").GetInt64() != source.DocumentVersion
                || metadata.GetProperty("snapshotSha256").GetString() != source.PayloadSha256
                || metadata.GetProperty("modelId").GetString() != AiProtocol.Setting(configuration, "EmbeddingModelId")
                || metadata.GetProperty("modelRevision").GetString() != AiProtocol.Setting(configuration, "EmbeddingRevision")
                || metadata.GetProperty("dimensions").GetInt32() != AiProtocol.EmbeddingDimensions(configuration)
                || !metadata.GetProperty("committed").GetBoolean())
                throw new JsonException();
            await using var transaction = await db.Database.BeginTransactionAsync(ct);
            var item = await db.Items.FromSqlInterpolated($"SELECT * FROM items WHERE id = {source.ItemId} FOR UPDATE").AsNoTracking().SingleOrDefaultAsync(ct);
            var job = await db.IndexOutbox.FromSqlInterpolated($"SELECT * FROM index_outbox WHERE id = {id} FOR UPDATE").SingleAsync(ct);
            if (job.Status != "running" || job.LeaseToken != metadata.GetProperty("leaseToken").GetGuid() || job.LeaseUntil <= DateTimeOffset.UtcNow)
                return;
            var current = item?.DocumentVersion == job.DocumentVersion && (job.EventKind == "tombstone" || RecoveryWorkflow.Public(item));
            job.Status = current || item is null && job.EventKind == "tombstone" ? "succeeded" : "obsolete";
            job.LeaseToken = null; job.LeaseUntil = null; job.LastErrorCode = null; job.FinishedAt = DateTimeOffset.UtcNow;
            await db.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);
        }
        catch (Exception error) when (AiProtocol.Malformed(error)) { throw new ApiException(502, "Invalid index receipt."); }
    }
}
