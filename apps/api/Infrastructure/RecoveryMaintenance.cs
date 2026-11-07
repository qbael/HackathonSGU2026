using System.Text;
using System.Text.Json;
using Findie.Api.Data;
using Findie.Api.Models;
using Findie.Api.Repositories;
using Findie.Api.Services;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Infrastructure;

public sealed class RecoveryMaintenance(IServiceScopeFactory scopes, IAiGateway ai, IProcessedStorage storage,
    IConfiguration configuration, ILogger<RecoveryMaintenance> logger, TimeProvider? timeProvider = null) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var clock = timeProvider ?? TimeProvider.System;
        var nextCleanup = DateTimeOffset.MinValue;
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                if (ai.Ready) await DispatchOneAsync(stoppingToken);
                var now = clock.GetUtcNow();
                if (storage.Configured && now >= nextCleanup)
                {
                    nextCleanup = now.AddMinutes(10);
                    await CleanupOneAsync(stoppingToken);
                }
            }
            catch (Exception error) when (!stoppingToken.IsCancellationRequested)
            { logger.LogWarning("Recovery maintenance deferred ({ErrorType}).", error.GetType().Name); }
            await Task.Delay(TimeSpan.FromSeconds(2), stoppingToken);
        }
    }
    public async Task<bool> DispatchOneAsync(CancellationToken ct)
    {
        using var scope = scopes.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
        IndexOutbox? job;
        await using (var transaction = await db.Database.BeginTransactionAsync(ct))
        {
            job = await db.IndexOutbox.FromSqlRaw("""
                SELECT * FROM index_outbox
                WHERE (status IN ('pending', 'retry') AND next_attempt_at <= now())
                   OR (status = 'running' AND lease_until <= now())
                ORDER BY next_attempt_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
                """).SingleOrDefaultAsync(ct);
            if (job is null) return false;
            if (job.Attempts == job.MaxAttempts)
            {
                job.Status = "failed"; job.FinishedAt = DateTimeOffset.UtcNow;
                job.LeaseToken = null; job.LeaseUntil = null; job.LastErrorCode = "attempts_exhausted";
                await db.SaveChangesAsync(ct); await transaction.CommitAsync(ct);
                return true;
            }
            job.Attempts++;
            job.Status = "running";
            job.LeaseToken = Guid.NewGuid();
            job.LeaseUntil = DateTimeOffset.UtcNow.AddSeconds(90);
            await db.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);
        }
        var images = new List<AiPart>();
        string? cacheError = null;
        try
        {
            var kind = job.EventKind == "snapshot" ? "index.upsert" : "index.remove";
            var model = AiProtocol.Setting(configuration, "EmbeddingModelId");
            var revision = AiProtocol.Setting(configuration, "EmbeddingRevision");
            var dimensions = AiProtocol.EmbeddingDimensions(configuration);
            Guid? cacheScope = null;
            var deadline = DateTimeOffset.UtcNow.AddSeconds(30);
            var canonical = RecoveryWorkflow.CanonicalJson(job.Payload);
            if (RecoveryWorkflow.Hash(canonical) != job.PayloadSha256) throw new ApiException(502, "Invalid outbox checksum.");
            if (job.EventKind == "snapshot")
            {
                var repository = scope.ServiceProvider.GetRequiredService<IRecoveryRepository>();
                var item = await repository.ItemAsync(job.ItemId, false, ct);
                if (item is null || !RecoveryWorkflow.Public(item) || item.DocumentVersion != job.DocumentVersion)
                { await Finish("obsolete", null); return true; }
                cacheScope = item.PostedBy;
                foreach (var image in item.Images.Where(RecoveryWorkflow.PublicImage).OrderBy(image => image.Position))
                {
                    if (image.OriginalEmbedding is { } cached)
                    {
                        byte[] body;
                        try
                        {
                            using var document = JsonDocument.Parse(cached);
                            var data = document.RootElement;
                            if (data.GetProperty("modelId").GetString() != model || data.GetProperty("modelRevision").GetString() != revision
                                || data.GetProperty("dimensions").GetInt32() != dimensions
                                || data.TryGetProperty("ocr", out var ocr) && (ocr.GetProperty("modelId").GetString() != AiProtocol.Setting(configuration, "RedactionModelId")
                                    || ocr.GetProperty("modelRevision").GetString() != AiProtocol.Setting(configuration, "RedactionRevision")))
                            {
                                cacheError = "original_embedding_requires_reupload";
                                throw new ApiException(502, "The original image embedding or OCR model changed; upload the image again.");
                            }
                            body = Encoding.UTF8.GetBytes(AiProtocol.Embedding(data, configuration));
                        }
                        catch (Exception error) when (AiProtocol.Malformed(error))
                        { throw new ApiException(502, "Invalid cached original image embedding."); }
                        var vectorMetadata = JsonSerializer.SerializeToElement(new { schemaVersion = 1, jobId = job.Id, job.LeaseToken,
                            job.ItemId, job.DocumentVersion, snapshotSha256 = job.PayloadSha256, sourceId = image.Id,
                            sourceVersion = image.ContentVersion, sourceSha256 = image.ProcessedObject!.Sha256,
                            payloadSha256 = RecoveryWorkflow.Hash(body), modelId = model, modelRevision = revision,
                            processingProfile = "image-v1", dimensions, cacheScope, deadlineAt = DateTimeOffset.UtcNow.AddSeconds(30) }, RecoveryWorkflow.Json);
                        images.Add(new AiPart(vectorMetadata, body, "application/json", "index.source.vector"));
                        continue;
                    }
                    // shortcut: legacy uploads have no original vector; reupload to replace their masked-image embeddings.
                    var bytes = await storage.ReadAsync(image.ProcessedObject!, ct);
                    if (RecoveryWorkflow.Hash(bytes) != image.ProcessedObject!.Sha256 || bytes.Length != image.ProcessedObject.ByteSize)
                    { Array.Clear(bytes); throw new ApiException(502, "Invalid stored output."); }
                    var partMetadata = JsonSerializer.SerializeToElement(new { schemaVersion = 1, jobId = job.Id, job.LeaseToken,
                        job.ItemId, job.DocumentVersion, snapshotSha256 = job.PayloadSha256, sourceId = image.Id,
                        sourceVersion = image.ContentVersion, sourceSha256 = image.ProcessedObject.Sha256,
                        modelId = model, modelRevision = revision, processingProfile = "image-v1", dimensions, cacheScope,
                        deadlineAt = DateTimeOffset.UtcNow.AddSeconds(30) }, RecoveryWorkflow.Json);
                    images.Add(new AiPart(partMetadata, bytes, image.ProcessedObject.ContentType!));
                }
            }
            var metadata = JsonSerializer.SerializeToElement(new { schemaVersion = 1, jobId = job.Id,
                job.LeaseToken, job.ItemId, job.DocumentVersion, snapshotSha256 = job.PayloadSha256,
                modelId = model, modelRevision = revision, dimensions, cacheScope, deadlineAt = deadline }, RecoveryWorkflow.Json);
            await using var reply = await ai.RequestAsync(new AiCommand(kind, metadata, Encoding.UTF8.GetBytes(canonical), "application/json", true, images), ct);
            using var receiptScope = scopes.CreateScope();
            await receiptScope.ServiceProvider.GetRequiredService<IndexReceiptService>().AcceptAsync(reply.Metadata, ct);
            await reply.CompleteAsync();
        }
        catch (ApiException error)
        {
            var terminal = job.Attempts >= job.MaxAttempts || error.StatusCode == 502;
            await Finish(terminal ? "failed" : "retry", cacheError ?? (error.StatusCode == 502 ? "invalid_result" : "dependency_unavailable"));
        }
        finally { foreach (var image in images) Array.Clear(image.Body); }
        return true;

        async Task Finish(string state, string? error)
        {
            var terminal = state != "retry";
            var next = DateTimeOffset.UtcNow.AddSeconds(5 * Math.Pow(2, job.Attempts));
            await db.IndexOutbox.Where(value => value.Id == job.Id && value.Status == "running"
                && value.LeaseToken == job.LeaseToken && value.LeaseUntil > DateTimeOffset.UtcNow).ExecuteUpdateAsync(update => update
                .SetProperty(value => value.Status, state).SetProperty(value => value.LeaseToken, (Guid?)null)
                .SetProperty(value => value.LeaseUntil, (DateTimeOffset?)null).SetProperty(value => value.LastErrorCode, error)
                .SetProperty(value => value.NextAttemptAt, next).SetProperty(value => value.FinishedAt, terminal ? DateTimeOffset.UtcNow : (DateTimeOffset?)null), ct);
        }
    }
    public async Task<bool> CleanupOneAsync(CancellationToken ct)
    {
        using var scope = scopes.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
        StoredObject? value;
        await using (var transaction = await db.Database.BeginTransactionAsync(ct))
        {
            value = await db.StoredObjects.FromSqlRaw("""
                SELECT * FROM stored_objects
                WHERE object_kind = 'processed' AND cleanup_attempts < 5
                  AND ((object_state = 'reserved' AND expires_at <= now())
                    OR (object_state = 'delete_pending' AND cleanup_next_at <= now()))
                  AND NOT EXISTS (SELECT 1 FROM item_images WHERE processed_object_id = stored_objects.id)
                ORDER BY cleanup_next_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
                """).SingleOrDefaultAsync(ct);
            if (value is null) return false;
            value.ObjectState = "delete_pending";
            value.CleanupAttempts++;
            value.CleanupNextAt = DateTimeOffset.UtcNow.AddMinutes(2);
            await db.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);
        }
        try
        {
            await storage.DeleteAsync(value, ct);
            value.ObjectState = "deleted";
            value.DeletedAt = DateTimeOffset.UtcNow;
            value.CleanupNextAt = null;
            value.LastErrorCode = null;
        }
        catch (ApiException)
        {
            value.LastErrorCode = "storage_unavailable";
            value.CleanupNextAt = value.CleanupAttempts == 5 ? null : DateTimeOffset.UtcNow.AddMinutes(value.CleanupAttempts * 2);
        }
        await db.SaveChangesAsync(ct);
        return true;
    }
}
