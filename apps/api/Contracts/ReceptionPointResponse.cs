namespace Findie.Api.Contracts;

public sealed record ReceptionPointResponse(Guid Id, string Name, string PublicAddress, string? Directions);
