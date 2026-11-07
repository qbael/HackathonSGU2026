using System.ComponentModel.DataAnnotations;
using System.Net.Mail;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Findie.Api.Contracts;
using Findie.Api.Data;
using Findie.Api.Services;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Infrastructure;

public static class LocalPublicSamples
{
    sealed record Photo(string Path, string Mime, string Sha256);
    sealed record Sample(string SourceId, string SourceUrl, string Path, CreateItemRequest Payload,
        List<Photo> Photos, string Fingerprint, string? LegacyTitleFingerprint, bool SyntheticScenario = false,
        string? PreviousSourceUrl = null, string? PreviousFingerprint = null, string? CoarsePreviewSourceSha256 = null);
    sealed record Preview(short Position, Guid ImageId, long ContentVersion, string Sha256, string File);
    sealed record ImportState(Guid ActorId, string Fingerprint, Guid? ItemId, List<Preview> Images)
    {
        [JsonExtensionData] public Dictionary<string, JsonElement>? Metadata { get; init; }
    }
    sealed record Reviewed(List<ReviewedImage> Images);
    sealed record ReviewedImage(Guid ImageId, long ContentVersion, string Sha256);
    sealed record MaskRegion(string Label, int[] Bbox);
    sealed record MaskedCorrection(string SourceFingerprint, Guid ActorId, Guid ItemId, Guid ImageId,
        long ContentVersion, string Sha256, short Position, string File, string MaskedSha256, List<MaskRegion> Regions, string? Method = null);
    sealed record CorrectionJournal(string PlanSha256, Preview OldImage, Preview? NewImage = null);
    sealed record ReviewedMasks(string PlanSha256, string InputSha256, List<MaskRegion> Regions);
    static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web) { WriteIndented = true };

    public static async Task<int> RunAsync(IServiceProvider services, string[] args, TextWriter output)
    {
        if (args.Length is not (4 or 5) || args[0] != "--import-public-samples" || args[2] != "--actor-email"
            || args.Length == 5 && args[4] is not ("--publish-reviewed" or "--review-only" or "--drafts-only" or "--sync-titles" or "--sync-source-urls" or "--replace-masked" or "--embed-originals")
            || !MailAddress.TryCreate(args[3], out var email) || email.Address != args[3])
            throw new ArgumentException("Use --import-public-samples PREPARED_JSON --actor-email existing-google-user@example.com [--drafts-only | --review-only | --publish-reviewed | --sync-titles | --sync-source-urls | --replace-masked | --embed-originals].");
        var publish = args.Contains("--publish-reviewed", StringComparer.Ordinal);
        var reviewOnly = args.Contains("--review-only", StringComparer.Ordinal);
        var review = publish || reviewOnly;
        var draftsOnly = args.Contains("--drafts-only", StringComparer.Ordinal);
        var syncTitles = args.Contains("--sync-titles", StringComparer.Ordinal);
        var syncSourceUrls = args.Contains("--sync-source-urls", StringComparer.Ordinal);
        var sync = syncTitles || syncSourceUrls;
        var replaceMasked = args.Contains("--replace-masked", StringComparer.Ordinal);
        var embedOriginals = args.Contains("--embed-originals", StringComparer.Ordinal);
        var samples = JsonSerializer.Deserialize<List<Sample>>(await File.ReadAllTextAsync(args[1]), Json)
            ?? throw new ArgumentException("Prepared samples must be a JSON array.");
        if (samples.Count == 0 || samples.Select(sample => sample.SourceId).Distinct().Count() != samples.Count
            || samples.Select(sample => sample.SourceUrl).Distinct().Count() != samples.Count)
            throw new ArgumentException("Prepared samples must contain distinct source posts.");
        foreach (var sample in samples)
        {
            Validator.ValidateObject(sample.Payload.Content, new ValidationContext(sample.Payload.Content), true);
            Validator.ValidateObject(sample.Payload.Custody, new ValidationContext(sample.Payload.Custody), true);
            if (syncTitles && (sample.LegacyTitleFingerprint is null || sample.LegacyTitleFingerprint == sample.Fingerprint))
                throw new ArgumentException("Title sync requires prepared input with the exact legacy title fingerprint.");
            if (syncSourceUrls && (sample.PreviousFingerprint is null || sample.PreviousFingerprint == sample.Fingerprint
                || !Uri.TryCreate(sample.PreviousSourceUrl, UriKind.Absolute, out var previousUrl)
                || !Uri.TryCreate(sample.SourceUrl, UriKind.Absolute, out var sourceUrl)
                || previousUrl.Scheme != "https" || sourceUrl.Scheme != "https" || previousUrl.Host != sourceUrl.Host
                || sample.PreviousSourceUrl == sample.SourceUrl
                || !sample.Payload.Content.PublicDescription.EndsWith("\nNguồn: " + sample.SourceUrl, StringComparison.Ordinal)))
                throw new ArgumentException("Source URL sync requires the previous fingerprint and an exact replacement source link on the same HTTPS host.");
            if ((!sample.SyntheticScenario && sample.Payload.Custody.Kind != "external")
                || (sample.SyntheticScenario && !sample.Payload.Content.PublicDescription.Contains("KỊCH BẢN GIẢ ĐỊNH"))
                || !sample.Payload.Content.PublicDescription.Contains("DỮ LIỆU MẪU")
                || !sample.Payload.Content.PublicDescription.Contains(sample.SourceUrl) || sample.Photos.Count is < 1 or > 3
                || !File.Exists(sample.Path)) throw new ArgumentException("Prepared sample input is invalid or its source file is missing.");
            if (sample.CoarsePreviewSourceSha256 is { } originalHash && (!sample.SyntheticScenario || sample.Photos.Count != 1
                || originalHash.Length != 64 || originalHash.Any(c => c is not (>= '0' and <= '9' or >= 'a' and <= 'f'))
                || sample.Photos[0].Mime != "image/png" || System.IO.Path.GetFileName(sample.Photos[0].Path) != "publication-preview.png"
                || sample.Photos[0].Sha256 == originalHash))
                throw new ArgumentException("Coarse preview import requires a synthetic sample and a separate PNG derivative.");
            foreach (var photo in sample.Photos)
            {
                var sourceFolder = System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(sample.Path))!;
                var relative = System.IO.Path.GetRelativePath(sourceFolder, System.IO.Path.GetFullPath(photo.Path));
                if (relative == ".." || relative.StartsWith(".." + System.IO.Path.DirectorySeparatorChar)
                    || System.IO.Path.IsPathRooted(relative) || new FileInfo(photo.Path).Length > BoundedImage.MaxBytes
                    || RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(photo.Path)) != photo.Sha256)
                    throw new ArgumentException("Photo changed or is outside its source folder; prepare the input again.");
            }
        }
        Guid actor;
        using (var scope = services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
            var normalized = new UpperInvariantLookupNormalizer().NormalizeEmail(email.Address);
            actor = await db.Users.Where(user => user.NormalizedEmail == normalized && user.EmailConfirmed && user.DisabledAt == null
                && db.UserLogins.Any(login => login.UserId == user.Id && login.LoginProvider == GoogleDefaults.AuthenticationScheme))
                .Select(user => user.Id).SingleOrDefaultAsync();
            if (actor == Guid.Empty) throw new InvalidOperationException("Sign in with the explicitly selected Google account before importing; no account was created.");
        }
        var gateway = services.GetRequiredService<RabbitMqGateway>();
        if (!review && !draftsOnly && !sync && !embedOriginals)
        {
            await gateway.StartAsync(default);
            var deadline = DateTimeOffset.UtcNow.AddSeconds(30);
            while (!gateway.Ready && DateTimeOffset.UtcNow < deadline) await Task.Delay(100);
            if (!gateway.Ready) throw new InvalidOperationException("AI broker did not become ready.");
        }
        try
        {
            var completed = 0;
            foreach (var sample in samples)
            {
                var folder = System.IO.Path.GetDirectoryName(sample.Path)!;
                var statePath = System.IO.Path.Combine(folder, "local-import-state.json");
                var state = File.Exists(statePath)
                    ? JsonSerializer.Deserialize<ImportState>(await File.ReadAllTextAsync(statePath), Json)!
                    : new ImportState(actor, sample.Fingerprint, null, []);
                if (state.ActorId != actor || state.Fingerprint != sample.Fingerprint
                    && !(syncTitles && state.Fingerprint == sample.LegacyTitleFingerprint)
                    && !(syncSourceUrls && state.Fingerprint == sample.PreviousFingerprint))
                    throw new InvalidOperationException("Imported source/account changed; review its existing draft before proceeding.");
                Guid Key(string operation) => new(SHA256.HashData(Encoding.UTF8.GetBytes("source-sample:" + sample.SourceUrl + ":" + operation))[..16]);
                if (state.ItemId is null)
                {
                    if (sync || replaceMasked || embedOriginals) throw new InvalidOperationException("This operation requires an existing imported item.");
                    if (review) continue;
                    var created = await InScope(provider => provider.GetRequiredService<IItemService>()
                        .CreateAsync(actor, Key("create"), sample.Payload, default));
                    state = state with { ItemId = created.Id };
                    await Save();
                }
                var itemId = state.ItemId.Value;
                var item = await InScope(provider => provider.GetRequiredService<IItemService>().GetAsync(actor, itemId, default));
                if (item.PublicationState == "published" && !sync && !replaceMasked && !embedOriginals) { await output.WriteLineAsync($"Already published: {itemId}"); continue; }
                var restoringSample = sample.SyntheticScenario && ((replaceMasked || embedOriginals) && (item.PublicationState is "published" or "hidden")
                    || review && item.PublicationState == "hidden");
                if (item.Lifecycle != "active" || item.PublicationState != "draft" && !restoringSample)
                    throw new InvalidOperationException("Imported item is no longer an active draft or restorable synthetic sample.");
                if (restoringSample && !await InScope(provider => provider.GetRequiredService<FindieDbContext>().Items
                    .AnyAsync(value => value.Id == itemId && value.PostedBy == actor && value.Lifecycle == "active")))
                    throw new InvalidOperationException("Only the selected account's own active synthetic samples may be restored.");
                if (embedOriginals)
                {
                    if (!sample.SyntheticScenario || state.Images.Count != sample.Photos.Count)
                        throw new InvalidOperationException("Original embedding restoration requires every exact imported synthetic-sample image.");
                    foreach (var image in state.Images)
                    {
                        var photo = sample.Photos[image.Position - 1];
                        var cachePath = System.IO.Path.Combine(folder, $"original-embedding-{image.Position}.json");
                        if (new FileInfo(cachePath) is { LinkTarget: not null } || new FileInfo(cachePath).Length is < 1 or > 1048576)
                            throw new InvalidOperationException("Original embedding cache must be a bounded local file.");
                        var bytes = await File.ReadAllBytesAsync(cachePath);
                        using var document = JsonDocument.Parse(bytes);
                        var embedding = document.RootElement;
                        var hash = RecoveryWorkflow.Hash(bytes);
                        await InScope(provider => provider.GetRequiredService<IImageService>().RestoreOriginalEmbeddingAsync(actor,
                            Key($"original-embedding:{image.ImageId}:{image.ContentVersion}:{photo.Sha256}:{hash}"), itemId,
                            image.ImageId, image.ContentVersion, image.Sha256, photo.Sha256, embedding, default));
                        var metadata = state.Metadata ?? [];
                        metadata["originalEmbedding:" + image.ImageId] = JsonSerializer.SerializeToElement(new { image.ImageId,
                            image.ContentVersion, sourceSha256 = photo.Sha256, processedSha256 = image.Sha256, cacheSha256 = hash,
                            modelId = embedding.GetProperty("modelId").GetString(), modelRevision = embedding.GetProperty("modelRevision").GetString(),
                            dimensions = embedding.GetProperty("dimensions").GetInt32() }, Json);
                        state = state with { Metadata = metadata };
                    }
                    await Save();
                    await output.WriteLineAsync($"{++completed}/{samples.Count}: restored original-source embedding for {itemId}.");
                    continue;
                }
                if (replaceMasked)
                {
                    var planPath = System.IO.Path.Combine(folder, "masked-correction.json");
                    if (!File.Exists(planPath)) continue;
                    if (new FileInfo(planPath).Length is < 1 or > 16384) throw new InvalidOperationException("Correction plan exceeds its metadata limit.");
                    var planBytes = await File.ReadAllBytesAsync(planPath);
                    var planHash = RecoveryWorkflow.Hash(planBytes);
                    var plan = JsonSerializer.Deserialize<MaskedCorrection>(planBytes, Json)!;
                    if (plan.SourceFingerprint != sample.Fingerprint || plan.ActorId != actor || plan.ItemId != itemId
                        || plan.Position is < 1 or > 3 || plan.ContentVersion < 1
                        || plan.Method is not null && (plan.Method != "coarse-thumbnail" || !sample.SyntheticScenario)
                        || string.IsNullOrWhiteSpace(plan.File) || System.IO.Path.GetFileName(plan.File) != plan.File
                        || plan.Regions is null || plan.Regions.Count > 32
                        || plan.Regions.Count == 0 && (!sample.SyntheticScenario || plan.Method is not null)
                        || plan.Regions.Any(region =>
                            (region.Label is not ("face" or "identity_number" or "identifier_number" or "passport_number" or "mrz" or "signature" or "phone" or "address" or "qr_code" or "barcode")
                                && !(sample.SyntheticScenario && region.Label == "text"))
                            || region.Bbox is not { Length: 4 } || region.Bbox.Any(value => value is < 0 or > 1000)
                            || region.Bbox[0] >= region.Bbox[2] || region.Bbox[1] >= region.Bbox[3]))
                        throw new InvalidOperationException("Masked correction plan does not match this imported draft or has invalid regions.");
                    var maskedPath = System.IO.Path.Combine(folder, plan.File);
                    var maskedInfo = new FileInfo(maskedPath);
                    if (maskedInfo.LinkTarget is not null || maskedInfo.Length is < 1 or > BoundedImage.MaxBytes)
                        throw new InvalidOperationException("Masked derivative must be a bounded local PNG file.");
                    var masked = await File.ReadAllBytesAsync(maskedPath);
                    if (!BoundedImage.Signature(masked, "image/png") || RecoveryWorkflow.Hash(masked) != plan.MaskedSha256)
                        throw new InvalidOperationException("Masked derivative changed since its correction plan was reviewed.");
                    ReviewedMasks? reviewedMasks = null;
                    var masksReviewPath = System.IO.Path.Combine(folder, "masked-correction-review.json");
                    if (File.Exists(masksReviewPath))
                    {
                        if (!sample.SyntheticScenario || plan.Method is not null || new FileInfo(masksReviewPath) is { LinkTarget: not null }
                            || new FileInfo(masksReviewPath).Length is < 1 or > 8192)
                            throw new InvalidOperationException("Reviewed masks require a bounded local synthetic-sample review.");
                        reviewedMasks = JsonSerializer.Deserialize<ReviewedMasks>(await File.ReadAllTextAsync(masksReviewPath), Json)!;
                        if (reviewedMasks.PlanSha256 != planHash || reviewedMasks.InputSha256 != plan.MaskedSha256
                            || reviewedMasks.Regions is null || reviewedMasks.Regions.Count > 32
                            || reviewedMasks.Regions.Any(region => region.Label is not ("face" or "identity_number" or "identifier_number" or "passport_number" or "mrz" or "signature" or "phone" or "address" or "qr_code" or "barcode" or "text")
                                || region.Bbox is not { Length: 4 } || region.Bbox.Any(value => value is < 0 or > 1000)
                                || region.Bbox[0] >= region.Bbox[2] || region.Bbox[1] >= region.Bbox[3]))
                            throw new InvalidOperationException("Reviewed masks do not match this exact correction input and plan.");
                    }
                    if (plan.MaskedSha256 == plan.Sha256 && reviewedMasks?.Regions.Count is not > 0)
                        throw new InvalidOperationException("Unchanged correction input requires explicit reviewed mask coordinates.");
                    var journalPath = System.IO.Path.Combine(folder, $"masked-correction-{planHash}.journal.json");
                    CorrectionJournal journal;
                    if (File.Exists(journalPath))
                    {
                        journal = JsonSerializer.Deserialize<CorrectionJournal>(await File.ReadAllTextAsync(journalPath), Json)!;
                        if (journal.PlanSha256 != planHash) throw new InvalidOperationException("Correction journal belongs to a different plan.");
                    }
                    else
                    {
                        var old = state.Images.Single(image => image.Position == plan.Position);
                        if (old.ImageId != plan.ImageId || old.ContentVersion != plan.ContentVersion || old.Sha256 != plan.Sha256)
                            throw new InvalidOperationException("Correction plan does not identify the exact imported processed image.");
                        var images = await InScope(provider => provider.GetRequiredService<IImageService>().ListAsync(actor, itemId, default));
                        if (!images.Any(image => image.Id == old.ImageId && image.Position == old.Position && image.ContentVersion == old.ContentVersion && image.PreviewUrl is not null))
                            throw new InvalidOperationException("Processed image changed before correction.");
                        var current = await InScope(provider => provider.GetRequiredService<IImageService>().ContentAsync(actor, itemId, old.ImageId, default));
                        if (RecoveryWorkflow.Hash(current.Bytes) != old.Sha256
                            || RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(System.IO.Path.Combine(folder, old.File))) != old.Sha256)
                            throw new InvalidOperationException("Current processed image or retained preview changed before correction.");
                        journal = new CorrectionJournal(planHash, old);
                        await SaveJson(journalPath, journal);
                    }
                    var previous = journal.OldImage;
                    var saved = state.Images.Single(image => image.Position == plan.Position);
                    if (previous.ImageId != plan.ImageId || previous.ContentVersion != plan.ContentVersion
                        || previous.Sha256 != plan.Sha256 || previous.Position != plan.Position
                        || saved != previous && saved != journal.NewImage)
                        throw new InvalidOperationException("Imported image state changed outside this correction journal.");
                    if (journal.NewImage is null)
                    {
                        await InScope(provider => provider.GetRequiredService<IImageService>().RetireAsync(actor,
                            Key($"mask:{planHash}:retire"), itemId, previous.ImageId, new RetireImageRequest(previous.ContentVersion), default));
                        var originalCachePath = System.IO.Path.Combine(folder, $"original-embedding-{plan.Position}.json");
                        JsonElement? originalCache = File.Exists(originalCachePath) ? ReadOriginalEmbedding(folder, plan.Position) : null;
                        await using var body = new MemoryStream(masked, writable: false);
                        var replacement = await InScope(provider => provider.GetRequiredService<IImageService>().UploadAsync(actor,
                            Key($"mask:{planHash}:upload"), itemId, plan.Position, "image/png", body, body.Length, default, omitOcr: sample.SyntheticScenario,
                            coarsePreview: plan.Method == "coarse-thumbnail",
                            reviewedRegions: reviewedMasks is null ? null : JsonSerializer.SerializeToElement(reviewedMasks.Regions, Json),
                            originalEmbedding: originalCache is null ? null : (originalCache.Value, sample.Photos[plan.Position - 1].Sha256)));
                        var processed = await InScope(provider => provider.GetRequiredService<IImageService>().ContentAsync(actor, itemId, replacement.Id, default));
                        var extension = processed.ContentType switch { "image/png" => "png", "image/webp" => "webp", _ => "jpg" };
                        var file = $"processed-{replacement.Id}.{extension}";
                        await File.WriteAllBytesAsync(System.IO.Path.Combine(folder, file), processed.Bytes);
                        journal = journal with { NewImage = new Preview(plan.Position, replacement.Id, replacement.ContentVersion, RecoveryWorkflow.Hash(processed.Bytes), file) };
                        await SaveJson(journalPath, journal);
                    }
                    var next = journal.NewImage!;
                    var latest = await InScope(provider => provider.GetRequiredService<IImageService>().ContentAsync(actor, itemId, next.ImageId, default));
                    if (RecoveryWorkflow.Hash(latest.Bytes) != next.Sha256
                        || RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(System.IO.Path.Combine(folder, next.File))) != next.Sha256)
                        throw new InvalidOperationException("Replacement output changed before import state was saved.");
                    if (saved == next)
                    {
                        if (state.Metadata?.ContainsKey("privacyCorrection:" + planHash) != true)
                            throw new InvalidOperationException("Replacement import state is missing its correction audit.");
                        await output.WriteLineAsync($"{++completed}/{samples.Count}: verified existing masked replacement {next.ImageId}.");
                        continue;
                    }
                    var reviewedPath = System.IO.Path.Combine(folder, "reviewed.json");
                    if (File.Exists(reviewedPath))
                    {
                        var archive = System.IO.Path.Combine(folder, $"reviewed-before-mask-{planHash}.json");
                        if (File.Exists(archive) && RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(archive)) != RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(reviewedPath)))
                            throw new InvalidOperationException("A different reviewed manifest already exists in the correction archive.");
                        File.Move(reviewedPath, archive, true);
                    }
                    var metadata = state.Metadata ?? [];
                    metadata["privacyCorrection:" + planHash] = JsonSerializer.SerializeToElement(new { planHash, plan, previous, replacement = next, reviewedMasks }, Json);
                    state = state with { Images = state.Images.Select(image => image.Position == plan.Position ? next : image).ToList(), Metadata = metadata };
                    await Save();
                    await output.WriteLineAsync($"{++completed}/{samples.Count}: replaced masked image {next.ImageId}; awaiting visual review before publication.");
                    continue;
                }
                if (sync)
                {
                    var changed = await InScope(async provider =>
                    {
                        var db = provider.GetRequiredService<FindieDbContext>();
                        var current = await db.Items.AsNoTracking().Include(value => value.VerificationQuestions)
                            .SingleAsync(value => value.Id == itemId);
                        if (current.PostedBy != actor || current.PublicationState != "draft" || current.Lifecycle != "active")
                            throw new InvalidOperationException("Sample sync requires the selected account's active draft.");
                        var title = current.Title;
                        var description = current.PublicDescription;
                        if (syncTitles)
                        {
                            title = sample.Payload.Content.Title;
                            if (current.Title == title) return false;
                            if (current.Title != "[Mẫu] " + title)
                                throw new InvalidOperationException("Existing title changed beyond the sample prefix; review the draft.");
                        }
                        else
                        {
                            description = sample.Payload.Content.PublicDescription;
                            if (current.PublicDescription == description) return false;
                            var oldDescription = description[..^(sample.SourceUrl.Length)] + sample.PreviousSourceUrl;
                            if (current.PublicDescription != oldDescription)
                                throw new InvalidOperationException("Existing description differs from the prior prepared source; review the draft.");
                        }
                        var content = new ItemInput(title, description, current.FoundArea, current.FoundTimePrecision,
                            current.FoundOn, current.FoundFrom, current.FoundUntil, current.FoundTimezone,
                            current.VerificationQuestions.OrderBy(question => question.Slot).Select(question => question.QuestionText).ToList());
                        await provider.GetRequiredService<IItemService>().UpdateAsync(actor, Key((syncTitles ? "remove-sample-title:" : "sync-source-url:") + sample.Fingerprint),
                            itemId, new UpdateItemRequest(current.RowVersion, content), default);
                        return true;
                    });
                    if (state.Fingerprint != sample.Fingerprint)
                    {
                        state = state with { Fingerprint = sample.Fingerprint };
                        await Save();
                    }
                    await output.WriteLineAsync($"{++completed}/{samples.Count}: {(changed ? "updated" : "verified")} {(syncTitles ? "title" : "source URL")} for {itemId}.");
                    continue;
                }
                if (draftsOnly)
                {
                    await output.WriteLineAsync($"{++completed}/{samples.Count}: saved draft {itemId}; source photos retained locally for processing.");
                    continue;
                }
                if (!review)
                {
                    for (short position = 1; position <= sample.Photos.Count; position++)
                    {
                        if (state.Images.Any(image => image.Position == position)) continue;
                        var photo = sample.Photos[position - 1];
                        await using var stream = File.OpenRead(photo.Path);
                        var image = await InScope(provider => provider.GetRequiredService<IImageService>().UploadAsync(actor,
                            Key($"image:{position}:{photo.Sha256}"), itemId, position, photo.Mime, stream, stream.Length, default, omitOcr: sample.SyntheticScenario,
                            coarsePreview: sample.CoarsePreviewSourceSha256 is not null));
                        var processed = await InScope(provider => provider.GetRequiredService<IImageService>().ContentAsync(actor, itemId, image.Id, default));
                        var extension = processed.ContentType switch { "image/png" => "png", "image/webp" => "webp", _ => "jpg" };
                        var file = $"processed-{image.Id}.{extension}";
                        await File.WriteAllBytesAsync(System.IO.Path.Combine(folder, file), processed.Bytes);
                        state.Images.Add(new Preview(position, image.Id, image.ContentVersion, RecoveryWorkflow.Hash(processed.Bytes), file));
                        if (sample.CoarsePreviewSourceSha256 is { } originalHash)
                        {
                            var metadata = state.Metadata ?? [];
                            metadata["coarsePublicationPreview"] = JsonSerializer.SerializeToElement(new { imageId = image.Id,
                                originalHash, previewInputHash = photo.Sha256 }, Json);
                            state = state with { Metadata = metadata };
                        }
                        await Save();
                    }
                    await output.WriteLineAsync($"{++completed}/{samples.Count}: draft {itemId}; inspect processed photos in {folder}.");
                }
                else
                {
                    var reviewPath = System.IO.Path.Combine(folder, "reviewed.json");
                    if (!File.Exists(reviewPath)) { await output.WriteLineAsync($"Awaiting reviewed.json: {itemId}"); continue; }
                    var reviewed = JsonSerializer.Deserialize<Reviewed>(await File.ReadAllTextAsync(reviewPath), Json)!;
                    if (state.Images.Count != sample.Photos.Count || reviewed.Images.Count != state.Images.Count
                        || reviewed.Images.Select(image => image.ImageId).Distinct().Count() != reviewed.Images.Count)
                        throw new InvalidOperationException("Review must cover every exact processed image.");
                    foreach (var image in state.Images)
                    {
                        if (!reviewed.Images.Any(value => value.ImageId == image.ImageId && value.ContentVersion == image.ContentVersion && value.Sha256 == image.Sha256))
                            throw new InvalidOperationException("Reviewed image identity/version/hash does not match the processed preview.");
                        var processed = await InScope(provider => provider.GetRequiredService<IImageService>().ContentAsync(actor, itemId, image.ImageId, default));
                        if (RecoveryWorkflow.Hash(processed.Bytes) != image.Sha256
                            || RecoveryWorkflow.Hash(await File.ReadAllBytesAsync(System.IO.Path.Combine(folder, image.File))) != image.Sha256)
                            throw new InvalidOperationException("Processed preview changed since visual review.");
                        await InScope(provider => provider.GetRequiredService<IImageService>().ReviewAsync(actor, Key($"review:{image.ImageId}:{image.ContentVersion}"),
                            itemId, image.ImageId, new ReviewImageRequest(image.ContentVersion, "approved"), default));
                    }
                    if (publish)
                    {
                        item = await InScope(provider => provider.GetRequiredService<IItemService>().GetAsync(actor, itemId, default));
                        if (sample.SyntheticScenario)
                        {
                            var sourceSuffix = "\nNguồn: " + sample.SourceUrl;
                            var imported = sample.Payload.Content.PublicDescription;
                            if (!imported.EndsWith(sourceSuffix, StringComparison.Ordinal))
                                throw new InvalidOperationException("Sample description does not end with its prepared source link.");
                            var publicDescription = imported[..^sourceSuffix.Length] + "\nNguồn bài gốc được lưu trong bộ dữ liệu mẫu.";
                            const string coarseNote = "\nẢnh công khai đã giảm chi tiết để che thông tin cá nhân.";
                            var clearDescription = publicDescription;
                            if (HasActiveCoarsePreview(state)) publicDescription += coarseNote;
                            if (item.PublicDescription != publicDescription)
                            {
                                if (item.PublicDescription != imported && item.PublicDescription != clearDescription
                                    && item.PublicDescription != clearDescription + coarseNote)
                                    throw new InvalidOperationException("The sample description changed since preparation; review before publishing.");
                                var content = await InScope(async provider =>
                                {
                                    var db = provider.GetRequiredService<FindieDbContext>();
                                    var questions = await db.VerificationQuestions.Where(value => value.ItemId == itemId)
                                        .OrderBy(value => value.Slot).Select(value => value.QuestionText).ToListAsync();
                                    return new ItemInput(item.Title, publicDescription, item.FoundArea, item.FoundTimePrecision,
                                        item.FoundOn, item.FoundFrom, item.FoundUntil, item.FoundTimezone, questions);
                                });
                                item = await InScope(provider => provider.GetRequiredService<IItemService>().UpdateAsync(actor, Key($"public-source-note:{item.RowVersion}"),
                                    itemId, new UpdateItemRequest(item.RowVersion, content), default));
                            }
                        }
                        await InScope(provider => provider.GetRequiredService<IItemService>().PublishAsync(actor, Key($"publish:{item.RowVersion}"), itemId,
                            new PublicationRequest(item.RowVersion, "published"), default));
                    }
                    await output.WriteLineAsync($"{++completed}/{samples.Count}: {(publish ? "published" : "kept draft with")} visually reviewed sample {itemId}.");
                }

                Task Save() => SaveJson(statePath, state);
            }
        }
        finally { if (!review && !draftsOnly && !sync && !embedOriginals) await gateway.StopAsync(default); }
        return 0;

        async Task<T> InScope<T>(Func<IServiceProvider, Task<T>> work)
        {
            using var scope = services.CreateScope();
            return await work(scope.ServiceProvider);
        }
    }

    static JsonElement ReadOriginalEmbedding(string folder, short position)
    {
        var path = System.IO.Path.Combine(folder, $"original-embedding-{position}.json");
        if (new FileInfo(path) is { LinkTarget: not null } || new FileInfo(path).Length is < 1 or > 1048576)
            throw new InvalidOperationException("Original embedding cache must be a bounded local file.");
        using var document = JsonDocument.Parse(File.ReadAllBytes(path));
        return document.RootElement.Clone();
    }

    static bool HasActiveCoarsePreview(ImportState state)
    {
        var active = state.Images.Select(image => image.ImageId).ToHashSet();
        bool IsActive(JsonElement image) => image.TryGetProperty("imageId", out var id)
            && id.TryGetGuid(out var value) && active.Contains(value);
        return state.Metadata?.Any(entry => entry.Key == "coarsePublicationPreview" && IsActive(entry.Value)
            || entry.Key.StartsWith("privacyCorrection:", StringComparison.Ordinal)
            && entry.Value.TryGetProperty("replacement", out var replacement) && IsActive(replacement)
            && entry.Value.TryGetProperty("plan", out var plan) && plan.TryGetProperty("method", out var method)
            && method.GetString() == "coarse-thumbnail") == true;
    }

    static async Task SaveJson<T>(string path, T value)
    {
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        await File.WriteAllTextAsync(temporary, JsonSerializer.Serialize(value, Json) + "\n");
        File.Move(temporary, path, true);
    }
}
