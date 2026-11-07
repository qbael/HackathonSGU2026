using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Findie.Api.Contracts;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Repositories;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.Net.Http.Headers;

namespace Findie.Api.Services;

public interface ISearchService
{
    Task<SearchResponse> TextAsync(Guid actor, SearchRequest request, CancellationToken ct);
    Task<SearchResponse> ImageAsync(Guid actor, ImageSearchFilter filter, string? mime, Stream stream, long? length, CancellationToken ct);
    Task<SearchResponse> ImagesAsync(Guid actor, ImageSearchFilter filter, string? contentType, Stream stream, long? length, CancellationToken ct);
}

public sealed class SearchService(IRecoveryRepository repository, IAiGateway ai, IConfiguration configuration, RecoveryWorkflow workflow) : ISearchService
{
    const double MaxTimeBonus = 0.05;
    const int CandidateLimit = 30;

    public Task<SearchResponse> TextAsync(Guid actor, SearchRequest request, CancellationToken ct)
    {
        var text = RecoveryWorkflow.Text(request.Text, 2000, "Search text");
        return SearchAsync(actor, "text", text, request.Area, request.From, request.Until, request.Limit,
            ParseLostAt(request.LostAt), [], "application/json", ct);
    }
    public async Task<SearchResponse> ImageAsync(Guid actor, ImageSearchFilter filter, string? mime, Stream stream, long? length, CancellationToken ct)
    {
        if (!BoundedImage.Mime(mime)) throw new ApiException(415, "Use a JPEG, PNG or WebP binary body.");
        var lostAt = ParseLostAt(filter.LostAt);
        var bytes = await BoundedImage.ReadAsync(stream, length, ct);
        try { return await SearchAsync(actor, "image", null, filter.Area, filter.From, filter.Until, filter.Limit, lostAt, bytes, mime!, ct); }
        finally { Array.Clear(bytes); }
    }
    public async Task<SearchResponse> ImagesAsync(Guid actor, ImageSearchFilter filter, string? contentType, Stream stream, long? length, CancellationToken ct)
    {
        ValidateFilters(filter.Area, filter.From, filter.Until, filter.Limit);
        var lostAt = ParseLostAt(filter.LostAt);
        if (length > 3 * BoundedImage.MaxBytes + 65536) throw new ApiException(413, "Search upload exceeds 30 MiB plus form headers.");
        if (!MediaTypeHeaderValue.TryParse(contentType, out var type) || type.MediaType != "multipart/form-data")
            throw new ApiException(415, "Use multipart/form-data with one to three images.");
        var boundary = HeaderUtilities.RemoveQuotes(type.Boundary).Value;
        if (string.IsNullOrWhiteSpace(boundary) || boundary.Length > 128) throw new ApiException(400, "Invalid multipart boundary.");
        var images = new List<(byte[] Bytes, string Mime)>();
        string? text = null;
        var hasText = false;
        try
        {
            try
            {
                var reader = new MultipartReader(boundary, stream) { HeadersCountLimit = 16, HeadersLengthLimit = 16384 };
                MultipartSection? section;
                while ((section = await reader.ReadNextSectionAsync(ct)) is not null)
                {
                    if (!ContentDispositionHeaderValue.TryParse(section.ContentDisposition, out var disposition)
                        || disposition.DispositionType != "form-data") throw new ApiException(400, "Invalid multipart field.");
                    var name = HeaderUtilities.RemoveQuotes(disposition.Name).Value;
                    var file = disposition.FileName.HasValue || disposition.FileNameStar.HasValue;
                    if (name == "images" && file)
                    {
                        if (images.Count == 3) throw new ApiException(400, "Upload at most three search images.");
                        if (!BoundedImage.Mime(section.ContentType)) throw new ApiException(415, "Use JPEG, PNG or WebP search images.");
                        images.Add((await BoundedImage.ReadAsync(section.Body, null, ct), section.ContentType!));
                    }
                    else if (name == "text" && !file && !hasText)
                    {
                        hasText = true;
                        var buffer = new byte[8001];
                        try
                        {
                            var used = 0;
                            int read;
                            while ((read = await section.Body.ReadAsync(buffer.AsMemory(used), ct)) > 0)
                            {
                                used += read;
                                if (used == buffer.Length) throw new ApiException(400, "Search text exceeds 2000 characters.");
                            }
                            text = RecoveryWorkflow.Optional(new UTF8Encoding(false, true).GetString(buffer, 0, used));
                            if (text?.Length > 2000) throw new ApiException(400, "Search text exceeds 2000 characters.");
                        }
                        finally { Array.Clear(buffer); }
                    }
                    else throw new ApiException(400, "Use only images and a single optional text field.");
                }
                if (images.Count == 0) throw new ApiException(400, "Upload one to three search images.");
            }
            catch (Exception error) when (error is IOException or InvalidDataException or DecoderFallbackException)
            { throw new ApiException(400, "Invalid multipart search input."); }
            var body = new byte[images.Sum(image => image.Bytes.Length)];
            try
            {
                var offset = 0;
                foreach (var image in images)
                {
                    image.Bytes.CopyTo(body, offset);
                    offset += image.Bytes.Length;
                }
                var mode = text is null ? "image" : "combined";
                var profile = text is null ? "image-fusion-v1" : "multimodal-fusion-v1";
                var metadata = JsonSerializer.SerializeToElement(new { schemaVersion = 1,
                    modelId = AiProtocol.Setting(configuration, "EmbeddingModelId"), modelRevision = AiProtocol.Setting(configuration, "EmbeddingRevision"),
                    processingProfile = "multimodal-v1", searchProfileId = profile, searchProfileVersion = 1,
                    mode, area = RecoveryWorkflow.Optional(filter.Area), from = filter.From, until = filter.Until, limit = filter.Limit,
                    candidateLimit = CandidateLimit, cacheScope = actor, deadlineAt = DateTimeOffset.UtcNow.AddSeconds(940), text,
                    images = images.Select(image => new { contentType = image.Mime, length = image.Bytes.Length }) }, RecoveryWorkflow.Json);
                var candidates = await QueryAsync(new AiCommand("search.hybrid.images", metadata, body, "application/octet-stream"),
                    mode, images.Count + (text is null ? 0 : 1), ct);
                return await ResultsAsync(actor, candidates, mode, profile, filter.Area, filter.From, filter.Until, filter.Limit, lostAt, ct);
            }
            finally { Array.Clear(body); }
        }
        finally { foreach (var image in images) Array.Clear(image.Bytes); }
    }
    async Task<SearchResponse> SearchAsync(Guid actor, string mode, string? text, string? area, DateOnly? from, DateOnly? until,
        int limit, DateTimeOffset? lostAt, byte[] bytes, string mime, CancellationToken ct) =>
        await ResultsAsync(actor, await QueryAsync(actor, mode, text, area, from, until, limit, bytes, mime, ct), mode,
            AiProtocol.Setting(configuration, mode == "text" ? "TextSearchProfile" : "ImageSearchProfile"), area, from, until, limit, lostAt, ct);

    async Task<IReadOnlyList<SearchCandidate>> QueryAsync(Guid actor, string mode, string? text, string? area, DateOnly? from, DateOnly? until,
        int limit, byte[] bytes, string mime, CancellationToken ct)
    {
        ValidateFilters(area, from, until, limit);
        area = RecoveryWorkflow.Optional(area);
        var model = AiProtocol.Setting(configuration, "EmbeddingModelId");
        var revision = AiProtocol.Setting(configuration, "EmbeddingRevision");
        var profile = AiProtocol.Setting(configuration, mode == "text" ? "TextSearchProfile" : "ImageSearchProfile");
        var metadata = JsonSerializer.SerializeToElement(new { schemaVersion = 1, modelId = model, modelRevision = revision,
            processingProfile = mode + "-v1", searchProfileId = profile, searchProfileVersion = 1,
            mode, area, from, until, limit, candidateLimit = CandidateLimit, cacheScope = actor,
            deadlineAt = DateTimeOffset.UtcNow.AddSeconds(mode == "image" ? 300 : 30) }, RecoveryWorkflow.Json);
        var kind = mode == "image" ? "search.hybrid.image" : "search.hybrid";
        var body = mode == "image" ? bytes : JsonSerializer.SerializeToUtf8Bytes(new { text, area, from, until }, RecoveryWorkflow.Json);
        try { return await QueryAsync(new AiCommand(kind, metadata, body, mime), mode, 0, ct); }
        finally { if (mode == "text") Array.Clear(body); }
    }
    async Task<IReadOnlyList<SearchCandidate>> QueryAsync(AiCommand command, string mode, int fusionBranches, CancellationToken ct)
    {
        try
        {
            await using var reply = await ai.RequestAsync(command, ct);
            AiProtocol.Require(reply.Metadata, command.Kind);
            foreach (var field in new[] { "modelId", "modelRevision", "processingProfile", "searchProfileId", "searchProfileVersion", "mode" })
                if (reply.Metadata.GetProperty(field).ToString() != command.Metadata.GetProperty(field).ToString()) throw new JsonException();
            if (reply.Body.Length > 1024 * 1024) throw new JsonException();
            using var document = JsonDocument.Parse(reply.Body);
            var candidates = document.RootElement.GetProperty("candidates");
            if (candidates.ValueKind != JsonValueKind.Array
                || candidates.GetArrayLength() > command.Metadata.GetProperty("candidateLimit").GetInt32()
                || candidates.GetArrayLength() > CandidateLimit) throw new JsonException();
            var result = new List<SearchCandidate>();
            var previousScore = double.PositiveInfinity;
            var previousGroup = -1;
            foreach (var candidate in candidates.EnumerateArray())
            {
                var sources = new List<SearchSource>();
                var score = fusionBranches == 0 ? 1d / (61 + result.Count) : candidate.GetProperty("score").GetDouble();
                var imageScore = mode == "image" ? score : 0d;
                var textScore = mode == "text" ? score : 0d;
                if (fusionBranches > 0)
                {
                    imageScore = candidate.GetProperty("imageScore").GetDouble();
                    textScore = candidate.GetProperty("textScore").GetDouble();
                    var maxImageScore = command.Metadata.GetProperty("images").GetArrayLength() / 61d;
                    var maxTextScore = mode == "combined" ? 0.5 / 61d : 0d;
                    if (!double.IsFinite(score) || score <= 0 || score > maxImageScore + maxTextScore + 1e-12
                        || !double.IsFinite(imageScore) || imageScore < 0 || imageScore > maxImageScore + 1e-12
                        || !double.IsFinite(textScore) || textScore < 0 || textScore > maxTextScore + 1e-12
                        || mode == "image" && textScore != 0
                        || Math.Abs(score - imageScore - textScore) > 1e-12) throw new JsonException();
                    var evidence = candidate.GetProperty("sources");
                    if (evidence.ValueKind != JsonValueKind.Array || evidence.GetArrayLength() < 1 || evidence.GetArrayLength() > fusionBranches)
                        throw new JsonException();
                    foreach (var source in evidence.EnumerateArray()) sources.Add(ReadSource(source, mode == "image", true));
                }
                else sources.Add(ReadSource(candidate, mode == "image"));
                var hit = new SearchCandidate(candidate.GetProperty("itemId").GetGuid(), score, imageScore, textScore, sources);
                if (hit.Group < previousGroup || hit.Group == previousGroup && score > previousScore) throw new JsonException();
                result.Add(hit);
                previousScore = score;
                previousGroup = hit.Group;
            }
            await reply.CompleteAsync();
            return result;
        }
        catch (Exception error) when (AiProtocol.Malformed(error)) { throw new ApiException(502, "AI returned an invalid search response; use GET /api/items for basic filters."); }
    }
    static SearchSource ReadSource(JsonElement source, bool imageOnly, bool strict = false)
    {
        var kind = source.GetProperty("sourceKind").GetString();
        var documentVersion = source.GetProperty("documentVersion").GetInt64();
        var sourceVersion = source.GetProperty("sourceVersion").GetInt64();
        var hash = source.GetProperty("sourceSha256").GetString();
        if (kind is not ("text" or "image") || imageOnly && kind != "image" || strict && (documentVersion <= 0 || sourceVersion <= 0
            || hash is not { Length: 64 } || hash.Any(c => c is not (>= '0' and <= '9' or >= 'a' and <= 'f'))))
            throw new JsonException();
        return new SearchSource(documentVersion, source.GetProperty("sourceId").GetGuid(), sourceVersion, hash, kind == "image");
    }
    async Task<SearchResponse> ResultsAsync(Guid actor, IReadOnlyList<SearchCandidate> candidates, string mode, string profile,
        string? area, DateOnly? from, DateOnly? until, int limit, DateTimeOffset? lostAt, CancellationToken ct)
    {
        area = RecoveryWorkflow.Optional(area);
        var scores = new Dictionary<Guid, (SearchCandidate Candidate, Item Item)>();
        var items = (await repository.SearchItemsAsync(actor, candidates.Select(candidate => candidate.ItemId).Distinct().ToArray(), ct))
            .ToDictionary(value => value.Item.Id);
        var removed = false;
        foreach (var candidate in candidates)
        {
            items.TryGetValue(candidate.ItemId, out var loaded);
            var item = loaded?.Item;
            var validSources = item is not null && candidate.Sources.All(source => item.DocumentVersion == source.DocumentVersion && (source.Image
                ? item.Images.Any(image => image.Id == source.SourceId && RecoveryWorkflow.PublicImage(image)
                    && image.ContentVersion == source.SourceVersion && image.ProcessedObject!.Sha256 == source.SourceHash)
                : source.SourceId == item.Id && item.ContentVersion == source.SourceVersion
                    && source.SourceHash == RecoveryWorkflow.Hash(item.Title + "\n" + item.PublicDescription)));
            if (item is null || !RecoveryWorkflow.Public(item) || !validSources || !Matches(item, from, until))
            { removed = true; continue; }
            if (!scores.TryGetValue(item.Id, out var current)
                || (-candidate.Group, candidate.Score, candidate.ImageScore, candidate.TextScore).CompareTo(
                    (-current.Candidate.Group, current.Candidate.Score, current.Candidate.ImageScore, current.Candidate.TextScore)) > 0)
                scores[item.Id] = (candidate, item);
        }
        var hits = new List<SearchHit>();
        foreach (var value in scores.Values.OrderByDescending(value => area is not null && MatchesArea(value.Item, area))
            .ThenBy(value => value.Candidate.Group).ThenByDescending(value =>
                value.Candidate.Score * (1 + (lostAt is { } whenLost ? TimeBonus(value.Item, whenLost) : 0)))
            .ThenByDescending(value => value.Candidate.ImageScore).ThenByDescending(value => value.Candidate.TextScore).Take(limit))
            hits.Add(new SearchHit(hits.Count + 1, workflow.Response(value.Item, actor, items[value.Item.Id].CanManage)));
        return new SearchResponse(hits, mode, profile, 1, removed && hits.Count < limit,
            area is not null && hits.Any(hit => !hit.Item.FoundArea.Contains(area, StringComparison.OrdinalIgnoreCase)), "/api/items");
    }
    static DateTimeOffset? ParseLostAt(string? value)
    {
        if (value is null) return null;
        if (!Regex.IsMatch(value, @"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,7})?)?(Z|[+-]\d{2}:\d{2})\z")
            || !DateTimeOffset.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.None, out var lostAt)
            || lostAt > DateTimeOffset.UtcNow)
            throw new ApiException(400, "Lost time must be a past ISO 8601 timestamp with a timezone offset.");
        return lostAt;
    }
    static double TimeBonus(Item item, DateTimeOffset lostAt)
    {
        // shortcut: these weights are heuristic, tune them when labelled search results are available.
        if (item.FoundFrom is { } start && (item.FoundUntil ?? start) >= lostAt)
        {
            var hoursAfterLoss = Math.Max(0, (start - lostAt).TotalHours);
            var precisionWeight = item.FoundUntil is null ? 1d : 0.5;
            return MaxTimeBonus * precisionWeight * Math.Max(0, 1 - hoursAfterLoss / 24);
        }
        if (item.FoundOn is { } day && TimeZoneInfo.TryFindSystemTimeZoneById(item.FoundTimezone, out var timezone)
            && day == DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(lostAt, timezone).DateTime))
            return 0.02;
        return 0;
    }
    static void ValidateFilters(string? area, DateOnly? from, DateOnly? until, int limit)
    {
        if (from > until || from == DateOnly.MinValue || until == DateOnly.MaxValue) throw new ApiException(400, "Invalid date filter.");
        if (area?.Length > 200 || limit is < 1 or > 10) throw new ApiException(400, "Invalid search filter.");
    }
    sealed record SearchSource(long DocumentVersion, Guid SourceId, long SourceVersion, string? SourceHash, bool Image);
    sealed record SearchCandidate(Guid ItemId, double Score, double ImageScore, double TextScore, IReadOnlyList<SearchSource> Sources)
    {
        public int Group => ImageScore > 0 && TextScore > 0 ? 0 : ImageScore > 0 ? 1 : 2;
    }
    static bool MatchesArea(Item item, string area) => item.FoundArea.Contains(area, StringComparison.OrdinalIgnoreCase);
    static bool Matches(Item item, DateOnly? from, DateOnly? until)
    {
        if (from is { } first)
        {
            var start = new DateTimeOffset(first.ToDateTime(TimeOnly.MinValue), TimeSpan.FromHours(7)).ToUniversalTime();
            if (!(item.FoundOn >= first || (item.FoundUntil ?? item.FoundFrom) >= start)) return false;
        }
        if (until is { } last)
        {
            var end = new DateTimeOffset(last.AddDays(1).ToDateTime(TimeOnly.MinValue), TimeSpan.FromHours(7)).ToUniversalTime();
            if (!(item.FoundOn <= last || item.FoundFrom < end)) return false;
        }
        return true;
    }
}
