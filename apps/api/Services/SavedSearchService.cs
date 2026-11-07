using System.Text.Json;
using Findie.Api.Contracts;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Repositories;

namespace Findie.Api.Services;

public sealed class SavedSearchService(IRecoveryRepository repository, IAiGateway ai, IConfiguration configuration, RecoveryWorkflow workflow)
{
    public async Task<IReadOnlyList<SavedSearchResponse>> ListAsync(Guid actor, CancellationToken ct) =>
        (await repository.SavedSearchesAsync(actor, ct)).Select(Response).ToArray();

    public async Task<SavedSearchResponse> CreateAsync(Guid actor, Guid key, ImageSearchFilter filter, string? contentType,
        Stream stream, long? length, CancellationToken ct)
    {
        SearchService.ValidateFilters(filter.Area, filter.From, filter.Until, filter.Limit);
        var lostAt = SearchService.ParseLostAt(filter.LostAt)?.ToUniversalTime();
        using var upload = await SearchUpload.ReadAsync(contentType, stream, length, false, ct);
        var request = new { text = upload.Text, area = RecoveryWorkflow.Optional(filter.Area), filter.From, filter.Until, lostAt,
            images = upload.Images.Select(image => new { sha256 = RecoveryWorkflow.Hash(image.Bytes), image.Mime }).ToArray() };
        if (await workflow.ReplayedAsync(actor, key, "search.save", request, "saved_search", ct) is { } replay)
            return Response(await repository.SavedSearchAsync(actor, replay, ct) ?? throw new ApiException(404, "Saved search no longer exists."));
        var search = new SavedSearch { UserId = actor, Text = request.text, Area = request.area, From = filter.From, Until = filter.Until,
            LostAt = lostAt, ModelId = AiProtocol.Setting(configuration, "EmbeddingModelId"),
            ModelRevision = AiProtocol.Setting(configuration, "EmbeddingRevision"), Dimensions = AiProtocol.EmbeddingDimensions(configuration) };
        var embeddings = new List<JsonElement>();
        for (var index = 0; index < upload.Images.Count; index++)
        {
            var image = upload.Images[index];
            var hash = request.images[index].sha256;
            var metadata = JsonSerializer.SerializeToElement(new { schemaVersion = 1, imageId = Guid.NewGuid(), itemId = search.Id,
                sourceVersion = 1, sourceSha256 = hash, modelId = search.ModelId, modelRevision = search.ModelRevision,
                dimensions = search.Dimensions, processingProfile = "image-v1", omitOcr = true, cacheScope = actor,
                deadlineAt = DateTimeOffset.UtcNow.AddMinutes(5) }, RecoveryWorkflow.Json);
            await using var reply = await ai.RequestAsync(new AiCommand("image.embed", metadata, image.Bytes, image.Mime), ct);
            try
            {
                AiProtocol.Require(reply.Metadata, "image.embed");
                if (reply.Body.Length > 1024 * 1024) throw new JsonException();
                using var document = JsonDocument.Parse(reply.Body);
                // Saved searches need the vector only, never OCR or original image bytes.
                if (document.RootElement.TryGetProperty("ocr", out var ocr) && ocr.ValueKind != JsonValueKind.Null) throw new JsonException();
                var canonical = AiProtocol.Embedding(document.RootElement, configuration, hash);
                using var validated = JsonDocument.Parse(canonical);
                embeddings.Add(validated.RootElement.Clone());
                await reply.CompleteAsync();
            }
            catch (Exception error) when (AiProtocol.Malformed(error))
            { throw new ApiException(502, "AI returned an invalid saved-search embedding; nothing was saved."); }
        }
        search.ImageEmbeddings = JsonSerializer.Serialize(embeddings, RecoveryWorkflow.Json);
        var id = await workflow.WriteAsync(actor, key, "search.save", request, "saved_search", 201, async () =>
        {
            await repository.AddSavedSearchAsync(search, ct);
            return search.Id;
        }, ct);
        return Response(await repository.SavedSearchAsync(actor, id, ct) ?? throw new ApiException(404, "Saved search not found."));
    }
    public Task DeleteAsync(Guid actor, Guid id, CancellationToken ct) => repository.DeleteSavedSearchAsync(actor, id, ct);
    public async Task ReadAsync(Guid actor, Guid id, Guid itemId, CancellationToken ct)
    {
        if (!await repository.ReadSavedMatchAsync(actor, id, itemId, ct)) throw new ApiException(404, "Match not found.");
    }
    static SavedSearchResponse Response(SavedSearch value)
    {
        using var images = JsonDocument.Parse(value.ImageEmbeddings);
        return new(value.Id, value.Text, images.RootElement.GetArrayLength(), value.Area, value.From, value.Until, value.LostAt,
            value.CreatedAt, value.LastCheckedAt, value.NeedsRefresh, value.Matches.OrderByDescending(match => value.Area is not null && match.Item.FoundArea.Contains(value.Area, StringComparison.OrdinalIgnoreCase))
                .ThenByDescending(match => match.Score).ThenByDescending(match => match.CreatedAt)
                .Select(match => new SavedSearchMatchResponse(match.ItemId, match.Item.Title, match.Item.FoundArea, match.Score, match.CreatedAt, match.ReadAt)).ToArray());
    }
}
