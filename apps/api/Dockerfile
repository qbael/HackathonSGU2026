FROM node:24-bookworm-slim AS web
WORKDIR /web
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY global.json ./
COPY apps/api/ apps/api/
RUN dotnet restore apps/api/Findie.Api.csproj --locked-mode
RUN dotnet publish apps/api/Findie.Api.csproj -c Release --no-restore -o /out
COPY --from=web /web/dist/ /out/wwwroot/

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/* \
    && curl -fsS https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /usr/local/share/rds-ca.pem
COPY --from=build /out/ ./
USER $APP_UID
ENV ASPNETCORE_HTTP_PORTS=8080 ASPNETCORE_ENVIRONMENT=Production
EXPOSE 8080
ENTRYPOINT ["dotnet", "Findie.Api.dll"]
