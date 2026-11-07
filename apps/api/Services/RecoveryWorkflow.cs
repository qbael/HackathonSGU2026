using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Findie.Api.Contracts;
using Findie.Api.Models;
using Findie.Api.Repositories;

namespace Findie.Api.Services;

public sealed class RecoveryWorkflow(IRecoveryRepository repository)
{
    public static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    public static string Hash(string value) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
    public static string Hash(byte[] value) => Convert.ToHexStringLower(SHA256.HashData(value));
    public static string CanonicalJson(string json)
    {
        using var document = JsonDocument.Parse(json);
        using var output = new MemoryStream();
        using (var writer = new Utf8JsonWriter(output)) Write(document.RootElement, writer);
        return Encoding.UTF8.GetString(output.ToArray());
        static void Write(JsonElement value, Utf8JsonWriter writer)
        {
            if (value.ValueKind == JsonValueKind.Object)
            {
                writer.WriteStartObject();
                foreach (var property in value.EnumerateObject().OrderBy(property => property.Name, StringComparer.Ordinal))
                { writer.WritePropertyName(property.Name); Write(property.Value, writer); }
                writer.WriteEndObject();
            }
            else if (value.ValueKind == JsonValueKind.Array)
            {
                writer.WriteStartArray();
                foreach (var child in value.EnumerateArray()) Write(child, writer);
                writer.WriteEndArray();
            }
            else value.WriteTo(writer);
        }
    }
    public static string RequestHash(string operation, object request) => Hash(JsonSerializer.Serialize(new { operation, request }, Json));
    public async Task<Guid?> ReplayedAsync(Guid actor, Guid key, string operation, object request, string type, CancellationToken ct)
    {
        var replay = await repository.ReplayAsync(actor, key, ct);
        if (replay is null) return null;
        if (replay.Operation != operation || replay.RequestSha256 != RequestHash(operation, request) || replay.ResourceType != type)
            throw new ApiException(409, "Idempotency-Key was already used for a different request.");
        return replay.ResourceId;
    }

    public async Task<Guid> WriteAsync(Guid actor, Guid key, string operation, object request, string type,
        short status, Func<Task<Guid>> write, CancellationToken ct)
    {
        var hash = RequestHash(operation, request);
        await using var transaction = await repository.BeginAsync(ct);
        await repository.LockRequestAsync(actor, key, ct);
        var replay = await repository.ReplayAsync(actor, key, ct);
        if (replay is not null)
        {
            if (replay.Operation != operation || replay.RequestSha256 != hash || replay.ResourceType != type)
                throw new ApiException(409, "Idempotency-Key was already used for a different request.");
            return replay.ResourceId;
        }
        var id = await write();
        repository.Add(new IdempotencyKey { ActorUserId = actor, IdempotencyKeyValue = key, Operation = operation,
            RequestSha256 = hash, ResourceType = type, ResourceId = id, ResponseStatus = status });
        await repository.SaveAsync(ct);
        await transaction.CommitAsync(ct);
        return id;
    }

    public async Task<Item> ItemAsync(Guid id, bool locked, CancellationToken ct)
    {
        var item = await repository.ItemAsync(id, locked, ct);
        return item is null || item.Lifecycle == "deleted" ? throw new ApiException(404, "Item not found.") : item;
    }

    public Task<bool> CanManageAsync(Item item, Guid actor, CancellationToken ct) => item.CustodyKind switch
    {
        "person" => Task.FromResult(item.HolderUserId == actor),
        "external" => Task.FromResult(item.PostedBy == actor),
        "point" => repository.PointPermissionAsync(actor, item.HolderPointId!.Value, receive: true, ct),
        _ => Task.FromResult(false)
    };
    public async Task RequireManagerAsync(Item item, Guid actor, CancellationToken ct)
    {
        if (!await CanManageAsync(item, actor, ct)) throw new ApiException(403, "Only the current custodian can manage this item.");
    }
    public async Task RequireReadAsync(Item item, Guid actor, CancellationToken ct)
    {
        if (!Public(item) && item.PostedBy != actor && !await CanManageAsync(item, actor, ct)
            && !(item.HolderPointId is { } point && await repository.PointPermissionAsync(actor, point, false, ct)))
            throw new ApiException(404, "Item not found.");
    }
    public static bool Public(Item item) => item.PublicationState == "published" && item.Lifecycle == "active";
    public static void RequireActive(Item item)
    {
        if (item.Lifecycle != "active") throw new ApiException(409, "This item has already been returned.");
    }
    public static void RequireVersion(Item item, long version)
    {
        if (item.RowVersion != version) throw new ApiException(409, "The item changed; reload before retrying.");
    }
    public static string? Optional(string? value) => string.IsNullOrWhiteSpace(value) ? null : value.Trim();
    public static string Text(string? value, int max, string name)
    {
        var text = value?.Trim();
        if (string.IsNullOrEmpty(text) || text.Length > max) throw new ApiException(400, $"{name} must contain 1 to {max} characters.");
        return text;
    }
    public static PageResponse<T> Page<T>(IReadOnlyList<T> values, int page, int size, int totalCount)
    {
        var totalPages = Math.Clamp((int)Math.Ceiling((double)totalCount / size), 1, 10000);
        return new(values, page, size, page < totalPages, totalPages);
    }

    public static CustodyResponse Custody(Item item) => new(item.CustodyKind,
        item.CustodyKind == "person" ? item.HolderUser?.DisplayName : null, item.HolderPointId,
        item.CustodyKind == "point" ? item.HolderPoint?.Name : item.ExternalName,
        item.CustodyKind == "point" ? item.HolderPoint?.PublicAddress : item.ExternalPublicAddress,
        item.CustodyKind == "point" ? item.HolderPoint?.Directions : item.ExternalInstructions);
    public static string CustodySnapshot(Item item)
    {
        var custody = Custody(item);
        return JsonSerializer.Serialize(new { custody.Kind, item.HolderUserId, item.HolderPointId,
            custody.DisplayName, custody.Name, custody.PublicAddress, custody.Instructions }, Json);
    }
    public static bool PublicImage(ItemImage image) => image.RetiredAt is null && image.ProcessingState == "ready"
        && image.ReviewState == "approved" && image.ProcessedObject is { ObjectKind: "processed", ObjectState: "validated" };
    public async Task<ItemResponse> ResponseAsync(Item item, Guid actor, CancellationToken ct) =>
        Response(item, actor, await CanManageAsync(item, actor, ct));
    public ItemResponse Response(Item item, Guid actor, bool canManage) => new(item.Id, item.Title, item.PublicDescription, item.FoundArea,
        item.FoundTimePrecision, item.FoundOn, item.FoundFrom, item.FoundUntil, item.FoundTimezone, Custody(item),
        item.Lifecycle, item.PublicationState, item.RowVersion, item.DocumentVersion, item.CreatedAt,
        item.Images.Where(PublicImage).OrderBy(image => image.Position)
            .Select(image => new ImageSummary(image.Id, image.Position, image.ContentVersion,
                $"/api/items/{item.Id}/images/{image.Id}/content")).ToList(),
        Public(item) && item.CustodyKind == "person" && item.PostedBy != actor && item.HolderUserId != actor,
        canManage);

    public void Changed(Item item, bool content = false, bool custody = false)
    {
        item.RowVersion++;
        item.DocumentVersion++;
        if (content) item.ContentVersion++;
        if (custody) item.CustodyVersion++;
        item.UpdatedAt = DateTimeOffset.UtcNow;
        Enqueue(item);
    }
    public void Enqueue(Item item)
    {
        var visible = Public(item);
        // Only explicitly public fields and approved output sources can enter the search projection.
        var payload = JsonSerializer.Serialize(new
        {
            schemaVersion = 1, itemId = item.Id, documentVersion = item.DocumentVersion,
            kind = visible ? "snapshot" : "tombstone",
            document = visible ? new { item.Title, item.PublicDescription, item.FoundArea,
                item.FoundTimePrecision, item.FoundOn, item.FoundFrom, item.FoundUntil, item.FoundTimezone,
                custody = Custody(item) } : null,
            sources = visible ? new[] { new { kind = "text", id = item.Id, version = item.ContentVersion,
                sha256 = Hash(item.Title + "\n" + item.PublicDescription), processingProfile = "text-v1" } }.Concat(item.Images.Where(PublicImage)
                .OrderBy(image => image.Position).Select(image => new { kind = "image", id = image.Id,
                    version = image.ContentVersion, sha256 = image.ProcessedObject!.Sha256!, processingProfile = "image-v1" })).ToArray() : []
        }, Json);
        payload = CanonicalJson(payload);
        repository.Add(new IndexOutbox { ItemId = item.Id, DocumentVersion = item.DocumentVersion,
            EventKind = visible ? "snapshot" : "tombstone", Payload = payload, PayloadSha256 = Hash(payload), MaxAttempts = 3 });
    }
    public void Event(Item item, Guid actor, string kind, string? from, Guid? intake = null, Guid? claim = null,
        Guid? recipient = null, string? note = null, Guid? id = null) => repository.Add(new CustodyEvent
    {
        Id = id ?? Guid.NewGuid(), ItemId = item.Id, ActorUserId = actor, EventKind = kind, CustodyVersion = item.CustodyVersion,
        FromCustody = from, ToCustody = kind == "returned" ? null : CustodySnapshot(item),
        IntakeRequestId = intake, ClaimId = claim, RecipientUserId = recipient, VerificationNote = Optional(note),
        OccurredAt = DateTimeOffset.UtcNow
    });
}
