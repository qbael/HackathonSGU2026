using Findie.Api.Data;
using Findie.Api.Infrastructure;
using Findie.Api.Models;
using Findie.Api.Services;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

static class PublicationImageFixture
{
    static readonly byte[] Output = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j8i0AAAAASUVORK5CYII=");

    public static async Task EnsureAsync(WebApplicationFactory<FindieDbContext> factory, Guid itemId)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<FindieDbContext>();
        var item = await db.Items.Include(value => value.Images).ThenInclude(value => value.ProcessedObject)
            .SingleAsync(value => value.Id == itemId);
        if (item.Images.Any(RecoveryWorkflow.PublicImage)) return;
        var now = DateTimeOffset.UtcNow;
        var output = new StoredObject
        {
            OwnerUserId = item.PostedBy, Bucket = "private-test-output", ObjectKey = $"processed/{itemId}/{Guid.NewGuid():N}",
            ObjectState = "validated", Sha256 = RecoveryWorkflow.Hash(Output), ContentType = "image/png",
            ByteSize = Output.Length, Width = 1, Height = 1, ValidatedAt = now
        };
        // Recovery/search setup needs approved metadata; image processing and storage have their own checks.
        db.ItemImages.Add(new ItemImage
        {
            ItemId = itemId, Position = 1, ProcessedObject = output, ProcessingState = "ready", ReviewState = "approved",
            SensitiveRegions = "[]", RedactionModelId = "fixture-redactor", RedactionModelRevision = "fixture-revision",
            RedactionProfile = "fixture-v1", ReviewedBy = item.PostedBy, ReviewedAt = now
        });
        await db.SaveChangesAsync();
    }
}
