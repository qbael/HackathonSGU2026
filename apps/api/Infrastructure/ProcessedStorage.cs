using Amazon.Runtime;
using Amazon.S3;
using Amazon.S3.Model;
using Findie.Api.Models;
using Findie.Api.Services;

namespace Findie.Api.Infrastructure;

public interface IProcessedStorage
{
    bool Configured { get; }
    string Bucket { get; }
    Task PutAsync(StoredObject value, byte[] bytes, CancellationToken ct);
    Task<byte[]> ReadAsync(StoredObject value, CancellationToken ct);
    Task DeleteAsync(StoredObject value, CancellationToken ct);
}

public sealed class ProcessedStorage : IProcessedStorage, IDisposable
{
    readonly IAmazonS3? client;
    public string Bucket { get; }
    public bool Configured => client is not null;
    public ProcessedStorage(IConfiguration configuration)
    {
        Bucket = configuration["Storage:Bucket"] ?? "";
        var endpoint = configuration["Storage:Endpoint"];
        var accessKey = configuration["Storage:AccessKeyId"];
        var secret = configuration["Storage:SecretAccessKey"];
        if (new[] { Bucket, endpoint, accessKey, secret }.All(string.IsNullOrWhiteSpace)) return;
        if (new[] { Bucket, endpoint, accessKey, secret }.Any(string.IsNullOrWhiteSpace)
            || !Uri.TryCreate(endpoint, UriKind.Absolute, out var uri) || uri.Scheme != "https"
            || uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0)
            throw new InvalidOperationException("R2 requires an HTTPS endpoint, bucket and server credentials.");
        client = new AmazonS3Client(new BasicAWSCredentials(accessKey, secret), new AmazonS3Config
        { ServiceURL = endpoint, ForcePathStyle = true, AuthenticationRegion = "auto", MaxErrorRetry = 2, Timeout = TimeSpan.FromSeconds(60) });
    }
    IAmazonS3 Client => client ?? throw new ApiException(503, "Processed image storage is not configured.");
    public async Task PutAsync(StoredObject value, byte[] bytes, CancellationToken ct)
    {
        try
        {
            using var stream = new MemoryStream(bytes, writable: false);
            await Client.PutObjectAsync(new PutObjectRequest { BucketName = value.Bucket, Key = value.ObjectKey,
                ContentType = value.ContentType, InputStream = stream, UseChunkEncoding = false,
                DisablePayloadSigning = true, DisableDefaultChecksumValidation = true }, ct);
        }
        catch (Exception error) when (StorageFailure(error, ct)) { throw new ApiException(503, "Processed image storage is unavailable."); }
    }
    public async Task<byte[]> ReadAsync(StoredObject value, CancellationToken ct)
    {
        try
        {
            using var response = await Client.GetObjectAsync(value.Bucket, value.ObjectKey, ct);
            return await BoundedImage.ReadAsync(response.ResponseStream, response.ContentLength, ct);
        }
        catch (Exception error) when (StorageFailure(error, ct)) { throw new ApiException(503, "Processed image storage is unavailable."); }
    }
    public async Task DeleteAsync(StoredObject value, CancellationToken ct)
    {
        try { await Client.DeleteObjectAsync(value.Bucket, value.ObjectKey, ct); }
        catch (Exception error) when (StorageFailure(error, ct)) { throw new ApiException(503, "Processed image storage is unavailable."); }
    }
    public void Dispose() => client?.Dispose();
    static bool StorageFailure(Exception error, CancellationToken ct) => error is AmazonServiceException or AmazonClientException
        or HttpRequestException or IOException or TimeoutException || error is OperationCanceledException && !ct.IsCancellationRequested;
}

public static class BoundedImage
{
    public const int MaxBytes = 10 * 1024 * 1024;
    public static bool Mime(string? type) => type is "image/jpeg" or "image/png" or "image/webp";
    public static async Task<byte[]> ReadAsync(Stream stream, long? contentLength, CancellationToken ct, int maxBytes = MaxBytes)
    {
        if (contentLength > maxBytes) throw new ApiException(413, "Image upload exceeds the size limit.");
        using var memory = new MemoryStream();
        var buffer = new byte[65536];
        try
        {
            int read;
            while ((read = await stream.ReadAsync(buffer, ct)) > 0)
            {
                if (memory.Length + read > maxBytes) throw new ApiException(413, "Image upload exceeds the size limit.");
                memory.Write(buffer, 0, read);
            }
            if (memory.Length == 0) throw new ApiException(400, "Image body is empty.");
            return memory.ToArray();
        }
        finally
        {
            Array.Clear(buffer);
            if (memory.TryGetBuffer(out var written)) Array.Clear(written.Array!);
        }
    }
    public static bool Signature(byte[] bytes, string type) => type switch
    {
        "image/png" => bytes.AsSpan().StartsWith(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }),
        "image/jpeg" => bytes.Length >= 3 && bytes[0] == 255 && bytes[1] == 216 && bytes[2] == 255,
        "image/webp" => bytes.Length >= 12 && bytes.AsSpan(0, 4).SequenceEqual("RIFF"u8) && bytes.AsSpan(8, 4).SequenceEqual("WEBP"u8),
        _ => false
    };
}
