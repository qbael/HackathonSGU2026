using System.Buffers.Binary;
using System.Text.Json;
using Findie.Api.Models;
using Findie.Api.Repositories;
using Findie.Api.Services;

namespace Findie.Api.Infrastructure;

public sealed class SearchMaterialsService(IRecoveryRepository repository, IProcessedStorage storage)
{
    public const int CandidateLimit = 20;
    public const int ManifestLimit = 65536;

    public async Task<int> ProvideAsync(ReadOnlyMemory<byte> body, Func<Guid, byte[], CancellationToken, Task> send, CancellationToken ct)
    {
        if (body.Length is 0 or > ManifestLimit) throw new JsonException();
        var request = JsonSerializer.Deserialize<MaterialsRequest>(body.Span, RecoveryWorkflow.Json) ?? throw new JsonException();
        if (request.Candidates is null || request.Candidates.Length is < 1 or > CandidateLimit
            || request.Candidates.Select(candidate => candidate.ItemId).Distinct().Count() != request.Candidates.Length
            || request.Candidates.Any(candidate => candidate.ItemId == Guid.Empty || candidate.Sources is null
                || candidate.Sources.Length is < 1 or > 6 || candidate.Sources.Any(source => source.SourceId == Guid.Empty
                    || source.DocumentVersion <= 0 || source.SourceVersion <= 0 || source.SourceKind is not ("text" or "image")
                    || source.SourceSha256 is not { Length: 64 } || source.SourceSha256.Any(c => c is not (>= '0' and <= '9' or >= 'a' and <= 'f')))))
            throw new JsonException();
        var items = (await repository.SearchItemsAsync(Guid.Empty, request.Candidates.Select(candidate => candidate.ItemId).ToArray(), ct))
            .ToDictionary(value => value.Item.Id, value => value.Item);
        foreach (var candidate in request.Candidates)
        {
            ct.ThrowIfCancellationRequested();
            items.TryGetValue(candidate.ItemId, out var item);
            var status = Valid(item, candidate) ? "ready" : "stale";
            ItemImage? image = null;
            byte[]? bytes = null;
            try
            {
                if (status == "ready")
                {
                    image = candidate.Sources.Where(source => source.SourceKind == "image")
                        .Select(source => item!.Images.FirstOrDefault(value => value.Id == source.SourceId && RecoveryWorkflow.PublicImage(value)))
                        .FirstOrDefault(value => value is not null)
                        ?? item!.Images.Where(RecoveryWorkflow.PublicImage).OrderBy(value => value.Position).FirstOrDefault();
                    if (image is null) status = "stale";
                    else
                    {
                        try
                        {
                            bytes = await storage.ReadAsync(image.ProcessedObject!, ct);
                            if (bytes.Length > BoundedImage.MaxBytes || bytes.Length != image.ProcessedObject!.ByteSize
                                || !BoundedImage.Mime(image.ProcessedObject.ContentType)
                                || !BoundedImage.Signature(bytes, image.ProcessedObject.ContentType!)
                                || RecoveryWorkflow.Hash(bytes) != image.ProcessedObject.Sha256)
                                throw new ApiException(503, "Processed image failed integrity verification.");
                            var current = (await repository.SearchItemsAsync(Guid.Empty, [candidate.ItemId], ct)).SingleOrDefault()?.Item;
                            if (!Valid(current, candidate) || !current!.Images.Any(value => value.Id == image.Id
                                    && RecoveryWorkflow.PublicImage(value) && value.ContentVersion == image.ContentVersion
                                    && value.ProcessedObjectId == image.ProcessedObjectId)) status = "stale";
                        }
                        catch (Exception error) when (!ct.IsCancellationRequested && error is ApiException or IOException or HttpRequestException or TimeoutException)
                        { status = "unavailable"; }
                    }
                }
                var payload = Packet(candidate.ItemId, status, item, image, bytes);
                try { await send(candidate.ItemId, payload, ct); }
                finally { Array.Clear(payload); }
            }
            finally { if (bytes is not null) Array.Clear(bytes); }
        }
        return request.Candidates.Length;
    }

    static bool Valid(Item? item, MaterialCandidate candidate) => item is not null && RecoveryWorkflow.Public(item)
        && candidate.Sources.All(source => item.DocumentVersion == source.DocumentVersion && (source.SourceKind == "image"
            ? item.Images.Any(image => image.Id == source.SourceId && RecoveryWorkflow.PublicImage(image)
                && image.ContentVersion == source.SourceVersion && image.ProcessedObject!.Sha256 == source.SourceSha256)
            : source.SourceId == item.Id && item.ContentVersion == source.SourceVersion
                && RecoveryWorkflow.Hash(item.Title + "\n" + item.PublicDescription) == source.SourceSha256));

    static byte[] Packet(Guid itemId, string status, Item? item, ItemImage? image, byte[]? bytes)
    {
        var ready = status == "ready";
        var manifest = JsonSerializer.SerializeToUtf8Bytes(new { itemId, status,
            title = ready ? item!.Title : null, publicDescription = ready ? item!.PublicDescription : null,
            image = ready ? new { sourceId = image!.Id, sourceVersion = image.ContentVersion,
                sourceSha256 = image.ProcessedObject!.Sha256, documentVersion = item!.DocumentVersion,
                contentType = image.ProcessedObject.ContentType, length = bytes!.Length } : null }, RecoveryWorkflow.Json);
        if (manifest.Length > ManifestLimit) throw new JsonException();
        var payload = new byte[4 + manifest.Length + (ready ? bytes!.Length : 0)];
        BinaryPrimitives.WriteInt32BigEndian(payload, manifest.Length);
        manifest.CopyTo(payload.AsSpan(4));
        if (ready) bytes!.CopyTo(payload.AsSpan(4 + manifest.Length));
        Array.Clear(manifest);
        return payload;
    }

    sealed record MaterialsRequest(MaterialCandidate[] Candidates);
    sealed record MaterialCandidate(Guid ItemId, MaterialSource[] Sources);
    sealed record MaterialSource(long DocumentVersion, Guid SourceId, long SourceVersion, string SourceSha256, string SourceKind);
}
