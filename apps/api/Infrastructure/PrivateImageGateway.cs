using System.Buffers.Binary;
using System.Text.Json;
using Findie.Api.Services;

namespace Findie.Api.Infrastructure;

// Original bytes bypass the broker; only reviewed index materials may use AMQP.
public sealed class PrivateImageGateway(RabbitMqGateway broker, IHttpClientFactory clients) : IAiGateway
{
    public bool Ready => broker.Ready;
    public async Task<AiReply> RequestAsync(AiCommand command, CancellationToken ct)
    {
        if (command.Kind is not ("image.embed" or "image.redact" or "search.hybrid.image" or "search.hybrid.images"))
            return await broker.RequestAsync(command, ct);
        using var client = clients.CreateClient("ai");
        client.Timeout = TimeSpan.FromSeconds(960);
        using var content = new ByteArrayContent(command.Body);
        content.Headers.ContentType = new(command.ContentType);
        using var request = new HttpRequestMessage(HttpMethod.Post, "/v1/images/" + command.Kind) { Content = content };
        request.Headers.Add("X-Ai-Metadata", Convert.ToBase64String(JsonSerializer.SerializeToUtf8Bytes(command.Metadata)));
        try
        {
            using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);
            if (!response.IsSuccessStatusCode) throw new ApiException(503, "AI image processing is unavailable; retry the upload.");
            await using var stream = await response.Content.ReadAsStreamAsync(ct);
            var size = new byte[4];
            await stream.ReadExactlyAsync(size, ct);
            var length = BinaryPrimitives.ReadInt32BigEndian(size);
            if (length is < 1 or > 16384) throw new JsonException();
            var header = new byte[length];
            await stream.ReadExactlyAsync(header, ct);
            using var metadata = JsonDocument.Parse(header);
            var body = await BoundedImage.ReadAsync(stream, null, ct);
            return new AiReply(metadata.RootElement.Clone(), body);
        }
        catch (Exception error) when (!ct.IsCancellationRequested && error is not ApiException)
        { throw new ApiException(503, "AI image processing is unavailable; retry the upload."); }
    }
}
