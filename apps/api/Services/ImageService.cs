using System.Text.Json;
using Findie.Api.Contracts;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Repositories;

namespace Findie.Api.Services;

public interface IImageService
{
    Task<IReadOnlyList<ImageResponse>> ListAsync(Guid actor, Guid itemId, CancellationToken ct);
    Task<ImageResponse> UploadAsync(Guid actor, Guid key, Guid itemId, short position, string? mime, Stream body, long? length, CancellationToken ct, bool omitOcr = false, bool coarsePreview = false, JsonElement? reviewedRegions = null, (JsonElement Data, string SourceSha256)? originalEmbedding = null);
    Task<ImageResponse> RestoreOriginalEmbeddingAsync(Guid actor, Guid key, Guid itemId, Guid imageId, long contentVersion, string processedSha256, string sourceSha256, JsonElement embedding, CancellationToken ct);
    Task<ImageResponse> ReviewAsync(Guid actor, Guid key, Guid itemId, Guid imageId, ReviewImageRequest request, CancellationToken ct);
    Task<ImageResponse> RetireAsync(Guid actor, Guid key, Guid itemId, Guid imageId, RetireImageRequest request, CancellationToken ct);
    Task<(byte[] Bytes, string ContentType)> ContentAsync(Guid actor, Guid itemId, Guid imageId, CancellationToken ct);
}

public sealed class ImageService(IRecoveryRepository repository, RecoveryWorkflow workflow, IAiGateway ai,
    IProcessedStorage storage, IConfiguration configuration) : IImageService
{
    public async Task<IReadOnlyList<ImageResponse>> ListAsync(Guid actor, Guid itemId, CancellationToken ct)
    {
        var item = await workflow.ItemAsync(itemId, false, ct);
        await workflow.RequireManagerAsync(item, actor, ct);
        return item.Images.OrderBy(image => image.Position).ThenBy(image => image.CreatedAt).Select(Response).ToList();
    }
    public async Task<ImageResponse> UploadAsync(Guid actor, Guid key, Guid itemId, short position, string? mime,
        Stream body, long? length, CancellationToken ct, bool omitOcr = false, bool coarsePreview = false, JsonElement? reviewedRegions = null, (JsonElement Data, string SourceSha256)? originalEmbedding = null)
    {
        if (reviewedRegions is not null && (!omitOcr || mime != "image/png" || coarsePreview))
            throw new ApiException(400, "Reviewed masks require a PNG without OCR and cannot use a coarse preview.");
        if (coarsePreview && (!omitOcr || mime != "image/png"))
            throw new ApiException(400, "A coarse preview must be a PNG without OCR.");
        var current = await workflow.ItemAsync(itemId, false, ct);
        await workflow.RequireManagerAsync(current, actor, ct);
        if (!BoundedImage.Mime(mime)) throw new ApiException(415, "Use image/jpeg, image/png or image/webp with a binary request body.");
        var bytes = await BoundedImage.ReadAsync(body, length, ct);
        try
        {
            var request = new { position, mime, sha256 = RecoveryWorkflow.Hash(bytes), length = bytes.Length };
            var suppliedEmbedding = originalEmbedding is { } supplied ? ValidateOriginalEmbedding(supplied.Data, supplied.SourceSha256) : null;
            object operationRequest = reviewedRegions is { } reviewed ? new { image = request, reviewedRegions = reviewed } : request;
            if (suppliedEmbedding is not null)
                operationRequest = new { image = operationRequest, originalEmbeddingSha256 = RecoveryWorkflow.Hash(suppliedEmbedding) };
            var operation = $"image.upload:{itemId}";
            if (await workflow.ReplayedAsync(actor, key, operation, operationRequest, "image", ct) is { } oldId)
                return Response(Find(current, oldId));
            RecoveryWorkflow.RequireActive(current);
            if (position is < 1 or > 3) throw new ApiException(400, "Image position must be between 1 and 3.");
            if (current.Images.Any(image => image.RetiredAt == null && image.Position == position))
                throw new ApiException(409, "This image position is occupied; retire the existing image first.");
            if (current.Images.Count(image => image.RetiredAt == null) >= 3)
                throw new ApiException(409, "An item may have at most three images; retire an existing image first.");
            if (!storage.Configured) throw new ApiException(503, "Processed image storage is not configured.");
            var model = AiProtocol.Setting(configuration, "RedactionModelId");
            var revision = AiProtocol.Setting(configuration, "RedactionRevision");
            var profile = AiProtocol.Setting(configuration, "RedactionProfile");
            var imageId = Guid.NewGuid();
            string? embedding = suppliedEmbedding;
            if (embedding is null)
            {
                var embeddingRequest = JsonSerializer.SerializeToNode(new { schemaVersion = 1, imageId, itemId, sourceVersion = 1,
                    sourceSha256 = request.sha256, modelId = AiProtocol.Setting(configuration, "EmbeddingModelId"),
                    modelRevision = AiProtocol.Setting(configuration, "EmbeddingRevision"), dimensions = AiProtocol.EmbeddingDimensions(configuration),
                    processingProfile = "image-v1", cacheScope = actor, deadlineAt = DateTimeOffset.UtcNow.AddMinutes(5) }, RecoveryWorkflow.Json)!.AsObject();
                if (omitOcr) embeddingRequest["omitOcr"] = true;
                if (coarsePreview) embeddingRequest["coarsePreview"] = true;
                var embeddingMetadata = JsonSerializer.SerializeToElement(embeddingRequest);
                await using (var embeddingReply = await ai.RequestAsync(new AiCommand("image.embed", embeddingMetadata, bytes, mime!), ct))
                {
                    try
                    {
                        AiProtocol.Require(embeddingReply.Metadata, "image.embed");
                        foreach (var field in new[] { "imageId", "itemId", "sourceVersion", "sourceSha256", "modelId", "modelRevision", "dimensions", "processingProfile" })
                            if (embeddingReply.Metadata.GetProperty(field).ToString() != embeddingMetadata.GetProperty(field).ToString()) throw new JsonException();
                        if (embeddingReply.Body.Length > 1048576) throw new JsonException();
                        using var document = JsonDocument.Parse(embeddingReply.Body);
                        if (omitOcr && document.RootElement.ValueKind != JsonValueKind.Null
                            && document.RootElement.TryGetProperty("ocr", out _)) throw new JsonException();
                        embedding = document.RootElement.ValueKind == JsonValueKind.Null ? null
                            : AiProtocol.Embedding(document.RootElement, configuration, request.sha256);
                        await embeddingReply.CompleteAsync();
                    }
                    catch (Exception error) when (AiProtocol.Malformed(error))
                    { throw new ApiException(502, "AI returned an invalid original image embedding; no image was stored."); }
                }
            }
            var redactionRequest = JsonSerializer.SerializeToNode(new { schemaVersion = 1, imageId, itemId, sourceVersion = 1,
                sourceSha256 = request.sha256, modelId = model, modelRevision = revision, processingProfile = profile,
                deadlineAt = DateTimeOffset.UtcNow.AddMinutes(5) }, RecoveryWorkflow.Json)!.AsObject();
            if (coarsePreview) redactionRequest["coarsePreview"] = true;
            if (reviewedRegions is { } masks) redactionRequest["reviewedRegions"] = JsonSerializer.SerializeToNode(masks);
            var metadata = JsonSerializer.SerializeToElement(redactionRequest);
            await using var reply = await ai.RequestAsync(new AiCommand("image.redact", metadata, bytes, mime!), ct);
            var output = ValidateOutput(reply, metadata);
            var value = new StoredObject { OwnerUserId = actor, Bucket = storage.Bucket, ObjectKey = $"processed/{itemId}/{Guid.NewGuid():N}",
                Sha256 = output.Hash, ContentType = output.Mime, ByteSize = reply.Body.Length, Width = output.Width, Height = output.Height,
                ExpiresAt = DateTimeOffset.UtcNow.AddHours(1), CleanupNextAt = DateTimeOffset.UtcNow.AddHours(1) };
            repository.Add(value);
            await repository.SaveAsync(ct);
            await storage.PutAsync(value, reply.Body, ct);
            var id = await workflow.WriteAsync(actor, key, operation, operationRequest, "image", 201, async () =>
            {
                var item = await workflow.ItemAsync(itemId, true, ct);
                await workflow.RequireManagerAsync(item, actor, ct);
                RecoveryWorkflow.RequireActive(item);
                RecoveryWorkflow.RequireVersion(item, current.RowVersion);
                await repository.LockObjectAsync(value, ct);
                if (value.ObjectState != "reserved" || value.ExpiresAt <= DateTimeOffset.UtcNow)
                    throw new ApiException(409, "The output reservation expired; upload the image again.");
                if (item.Images.Any(image => image.RetiredAt == null && image.Position == position))
                    throw new ApiException(409, "This image position was occupied during processing.");
                if (item.Images.Count(image => image.RetiredAt == null) >= 3)
                    throw new ApiException(409, "An item may have at most three images; retire an existing image first.");
                value.ObjectState = "validated";
                value.ValidatedAt = DateTimeOffset.UtcNow;
                value.ExpiresAt = value.CleanupNextAt = null;
                var image = new ItemImage { Id = imageId, ItemId = itemId, Position = position, ProcessedObjectId = value.Id,
                    ProcessedObject = value, ProcessingState = "needs_review", SensitiveRegions = output.Regions, OriginalEmbedding = embedding,
                    RedactionModelId = model, RedactionModelRevision = revision, RedactionProfile = profile };
                repository.Add(image);
                item.Images.Add(image);
                workflow.Changed(item);
                return imageId;
            }, ct);
            await reply.CompleteAsync();
            return Response(Find(await workflow.ItemAsync(itemId, false, ct), id));
        }
        finally { Array.Clear(bytes); }
    }
    static (string Mime, string Hash, int Width, int Height, string Regions) ValidateOutput(AiReply reply, JsonElement expected)
    {
        try
        {
            var data = reply.Metadata;
            AiProtocol.Require(data, "image.redact");
            foreach (var field in new[] { "imageId", "itemId", "sourceVersion", "sourceSha256", "modelId", "modelRevision", "processingProfile" })
                if (data.GetProperty(field).ToString() != expected.GetProperty(field).ToString()) throw new JsonException();
            if (expected.TryGetProperty("coarsePreview", out _) && !data.GetProperty("coarsePreview").GetBoolean())
                throw new JsonException();
            var mime = data.GetProperty("contentType").GetString()!;
            var hash = data.GetProperty("sha256").GetString()!;
            var width = data.GetProperty("width").GetInt32();
            var height = data.GetProperty("height").GetInt32();
            var regions = data.GetProperty("sensitiveRegions");
            if (expected.TryGetProperty("reviewedRegions", out var masks) && !JsonElement.DeepEquals(masks, regions))
                throw new JsonException();
            if (!BoundedImage.Mime(mime) || !BoundedImage.Signature(reply.Body, mime) || reply.Body.Length > BoundedImage.MaxBytes
                || data.GetProperty("byteSize").GetInt32() != reply.Body.Length || hash != RecoveryWorkflow.Hash(reply.Body)
                || width is < 1 or > 10000 || height is < 1 or > 10000 || (long)width * height > 40000000
                || regions.ValueKind != JsonValueKind.Array || regions.GetRawText().Length > 8000) throw new JsonException();
            return (mime, hash, width, height, regions.GetRawText());
        }
        catch (Exception error) when (AiProtocol.Malformed(error)) { throw new ApiException(502, "AI returned an invalid processed image; no image was stored."); }
    }
    string ValidateOriginalEmbedding(JsonElement embedding, string sourceSha256)
    {
        try
        {
            if (embedding.GetRawText().Length > 1048576 || embedding.TryGetProperty("ocr", out _)) throw new JsonException();
            return AiProtocol.Embedding(embedding, configuration, sourceSha256);
        }
        catch (Exception error) when (AiProtocol.Malformed(error))
        { throw new ApiException(400, "The original embedding must match the selected source hash and configured model without OCR."); }
    }
    public async Task<ImageResponse> RestoreOriginalEmbeddingAsync(Guid actor, Guid key, Guid itemId, Guid imageId,
        long contentVersion, string processedSha256, string sourceSha256, JsonElement embedding, CancellationToken ct)
    {
        var current = await workflow.ItemAsync(itemId, false, ct);
        await workflow.RequireManagerAsync(current, actor, ct);
        RecoveryWorkflow.RequireActive(current);
        RequireCurrent(Find(current, imageId));
        var canonical = ValidateOriginalEmbedding(embedding, sourceSha256);
        var request = new { contentVersion, processedSha256, sourceSha256, embeddingSha256 = RecoveryWorkflow.Hash(canonical) };
        await workflow.WriteAsync(actor, key, $"image.restore-original-embedding:{itemId}:{imageId}", request, "image", 200, async () =>
        {
            var item = await workflow.ItemAsync(itemId, true, ct);
            await workflow.RequireManagerAsync(item, actor, ct);
            RecoveryWorkflow.RequireActive(item);
            var image = Find(item, imageId);
            RequireCurrent(image);
            if (image.OriginalEmbedding != canonical)
            {
                image.OriginalEmbedding = canonical;
                workflow.Changed(item);
            }
            return imageId;
        }, ct);
        return Response(Find(await workflow.ItemAsync(itemId, false, ct), imageId));

        void RequireCurrent(ItemImage image)
        {
            if (image.ContentVersion != contentVersion || image.RetiredAt is not null
                || image.ProcessingState is not ("ready" or "needs_review")
                || image.ProcessedObject is not { ObjectState: "validated" } value || value.Sha256 != processedSha256)
                throw new ApiException(409, "The processed image changed before its original embedding was restored.");
        }
    }
    public async Task<ImageResponse> ReviewAsync(Guid actor, Guid key, Guid itemId, Guid imageId, ReviewImageRequest request, CancellationToken ct)
    {
        await workflow.WriteAsync(actor, key, $"image.review:{itemId}:{imageId}", request, "image", 200, async () =>
        {
            var item = await workflow.ItemAsync(itemId, true, ct);
            await workflow.RequireManagerAsync(item, actor, ct);
            RecoveryWorkflow.RequireActive(item);
            var image = Find(item, imageId);
            if (image.ContentVersion != request.ContentVersion || image.RetiredAt != null
                || image.ProcessingState is not ("needs_review" or "ready") || image.ProcessedObject?.ObjectState != "validated")
                throw new ApiException(409, "The output changed or is no longer reviewable.");
            image.ReviewState = request.Decision;
            image.ProcessingState = request.Decision == "approved" ? "ready" : "rejected";
            if (request.Decision == "rejected") image.OriginalEmbedding = null;
            image.ReviewedBy = actor;
            image.ReviewedAt = DateTimeOffset.UtcNow;
            if (item.PublicationState == "published" && !item.Images.Any(RecoveryWorkflow.PublicImage))
                item.PublicationState = "hidden";
            workflow.Changed(item);
            return imageId;
        }, ct);
        var current = await workflow.ItemAsync(itemId, false, ct);
        await workflow.RequireManagerAsync(current, actor, ct);
        return Response(Find(current, imageId));
    }
    public async Task<ImageResponse> RetireAsync(Guid actor, Guid key, Guid itemId, Guid imageId, RetireImageRequest request, CancellationToken ct)
    {
        await workflow.WriteAsync(actor, key, $"image.retire:{itemId}:{imageId}", request, "image", 200, async () =>
        {
            var item = await workflow.ItemAsync(itemId, true, ct);
            await workflow.RequireManagerAsync(item, actor, ct);
            var image = Find(item, imageId);
            if (image.ContentVersion != request.ContentVersion || image.RetiredAt is not null) throw new ApiException(409, "The image changed or was already retired.");
            image.RetiredAt = DateTimeOffset.UtcNow;
            image.ContentVersion++;
            if (image.ProcessedObject is { } value)
            {
                value.ObjectState = "delete_pending";
                value.CleanupNextAt = DateTimeOffset.UtcNow;
            }
            image.ProcessedObject = null;
            image.ProcessedObjectId = null;
            image.OriginalEmbedding = null;
            image.ProcessingState = "rejected";
            image.ReviewState = "rejected";
            image.ReviewedBy = actor;
            image.ReviewedAt = DateTimeOffset.UtcNow;
            if (item.PublicationState == "published" && !item.Images.Any(RecoveryWorkflow.PublicImage))
                item.PublicationState = "hidden";
            workflow.Changed(item);
            return imageId;
        }, ct);
        var current = await workflow.ItemAsync(itemId, false, ct);
        await workflow.RequireManagerAsync(current, actor, ct);
        return Response(Find(current, imageId));
    }
    public async Task<(byte[] Bytes, string ContentType)> ContentAsync(Guid actor, Guid itemId, Guid imageId, CancellationToken ct)
    {
        var item = await workflow.ItemAsync(itemId, false, ct);
        var image = Find(item, imageId);
        if (image.RetiredAt != null || image.ProcessedObject is not { ObjectState: "validated", ObjectKind: "processed" } value
            || !(RecoveryWorkflow.Public(item) && RecoveryWorkflow.PublicImage(image)) && !await workflow.CanManageAsync(item, actor, ct))
            throw new ApiException(404, "Processed image not found.");
        var bytes = await storage.ReadAsync(value, ct);
        if (bytes.Length != value.ByteSize || RecoveryWorkflow.Hash(bytes) != value.Sha256)
            throw new ApiException(503, "The stored output failed integrity verification.");
        var latest = await workflow.ItemAsync(itemId, false, ct);
        var source = Find(latest, imageId);
        if (source.RetiredAt != null || source.ContentVersion != image.ContentVersion || source.ProcessedObjectId != value.Id
            || source.ProcessedObject?.ObjectState != "validated"
            || !(RecoveryWorkflow.Public(latest) && RecoveryWorkflow.PublicImage(source)) && !await workflow.CanManageAsync(latest, actor, ct))
        { Array.Clear(bytes); throw new ApiException(404, "Processed image is no longer available."); }
        return (bytes, value.ContentType!);
    }
    static ItemImage Find(Item item, Guid id) => item.Images.SingleOrDefault(image => image.Id == id) ?? throw new ApiException(404, "Image not found.");
    static ImageResponse Response(ItemImage image) => new(image.Id, image.ItemId, image.Position, image.ContentVersion,
        image.ProcessingState, image.ReviewState, image.FailureCode,
        image.RetiredAt == null && image.ProcessedObject is { ObjectState: "validated" } ? $"/api/items/{image.ItemId}/images/{image.Id}/content" : null);
}

public static class AiProtocol
{
    public static string Embedding(JsonElement data, IConfiguration configuration, string? sourceHash = null)
    {
        var fields = data.EnumerateObject().Select(property => property.Name).Order().ToArray();
        var hasOcr = data.TryGetProperty("ocr", out var ocr);
        if (!fields.SequenceEqual((hasOcr
            ? new[] { "modelId", "modelRevision", "dimensions", "sourceSha256", "vector", "ocr" }
            : new[] { "modelId", "modelRevision", "dimensions", "sourceSha256", "vector" }).Order())) throw new JsonException();
        var model = data.GetProperty("modelId").GetString();
        var revision = data.GetProperty("modelRevision").GetString();
        var dimensions = data.GetProperty("dimensions").GetInt32();
        var hash = data.GetProperty("sourceSha256").GetString();
        var vector = data.GetProperty("vector").EnumerateArray().Select(value => value.GetDouble()).ToArray();
        var normSquared = vector.Sum(value => value * value);
        if (model != Setting(configuration, "EmbeddingModelId") || revision != Setting(configuration, "EmbeddingRevision")
            || dimensions != EmbeddingDimensions(configuration) || vector.Length != dimensions
            || hash is not { Length: 64 } || hash.Any(c => c is not (>= '0' and <= '9' or >= 'a' and <= 'f'))
            || sourceHash is not null && hash != sourceHash || vector.Any(value => !double.IsFinite(value))
            || !double.IsFinite(normSquared) || normSquared <= 0) throw new JsonException();
        if (hasOcr)
        {
            if (!ocr.EnumerateObject().Select(property => property.Name).Order().SequenceEqual(
                new[] { "text", "hasUnclearText", "modelId", "modelRevision", "processingProfile" }.Order())
                || ocr.GetProperty("text").GetString() is not { Length: <= 3000 }
                || ocr.GetProperty("modelId").GetString() != Setting(configuration, "RedactionModelId")
                || ocr.GetProperty("modelRevision").GetString() != Setting(configuration, "RedactionRevision")
                || ocr.GetProperty("processingProfile").GetString() != "ocr-v1") throw new JsonException();
            _ = ocr.GetProperty("hasUnclearText").GetBoolean();
            return JsonSerializer.Serialize(new { modelId = model, modelRevision = revision, dimensions, sourceSha256 = hash, vector, ocr }, RecoveryWorkflow.Json);
        }
        return JsonSerializer.Serialize(new { modelId = model, modelRevision = revision, dimensions, sourceSha256 = hash, vector }, RecoveryWorkflow.Json);
    }
    public static int EmbeddingDimensions(IConfiguration configuration) =>
        int.TryParse(configuration["Ai:EmbeddingDimensions"], out var dimensions) && dimensions is > 0 and <= 16000
            ? dimensions : throw new ApiException(503, "AI embedding dimensions must be configured between 1 and 16000.");
    public static bool Malformed(Exception error) => error is JsonException or KeyNotFoundException or InvalidOperationException or FormatException or OverflowException;
    public static void Require(JsonElement data, string kind)
    {
        if (data.GetProperty("schemaVersion").GetInt32() != 1 || data.GetProperty("kind").GetString() != kind) throw new JsonException();
        if (!data.GetProperty("succeeded").GetBoolean()) throw new ApiException(503, "AI processing failed; retry or use basic item filters.");
    }
    public static string Setting(IConfiguration configuration, string key) => configuration["Ai:" + key] is { Length: > 0 } value
        && value is not ("main" or "latest") ? value : throw new ApiException(503, "AI model revision/profile is not configured.");
}
