using System.Text;
using Findie.Api.Services;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.Net.Http.Headers;

namespace Findie.Api.Infrastructure;

public sealed class SearchUpload : IDisposable
{
    public List<(byte[] Bytes, string Mime)> Images { get; } = [];
    public string? Text { get; private set; }
    public void Dispose() { foreach (var image in Images) Array.Clear(image.Bytes); }
    public static async Task<SearchUpload> ReadAsync(string? contentType, Stream stream, long? length, bool requireImages, CancellationToken ct)
    {
        var upload = new SearchUpload();
        if (length > 3 * BoundedImage.MaxBytes + 65536) throw new ApiException(413, "Search upload exceeds 30 MiB plus form headers.");
        if (!MediaTypeHeaderValue.TryParse(contentType, out var type) || type.MediaType != "multipart/form-data")
            throw new ApiException(415, "Use multipart/form-data with a description and/or up to three images.");
        var boundary = HeaderUtilities.RemoveQuotes(type.Boundary).Value;
        if (string.IsNullOrWhiteSpace(boundary) || boundary.Length > 128) throw new ApiException(400, "Invalid multipart boundary.");
        var images = upload.Images;
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
                if (images.Count == 0 && (requireImages || text is null))
                    throw new ApiException(400, "Enter a description or upload one to three search images.");
            }
            catch (Exception error) when (error is IOException or InvalidDataException or DecoderFallbackException)
            { throw new ApiException(400, "Invalid multipart search input."); }
            upload.Text = text;
            return upload;
        }
        catch { upload.Dispose(); throw; }
    }
}
