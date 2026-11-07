using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Findie.Api.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddSavedSearches : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropCheckConstraint(
                name: "idempotency_resource_check",
                table: "idempotency_keys");

            migrationBuilder.CreateTable(
                name: "saved_searches",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    text = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true),
                    area = table.Column<string>(type: "character varying(200)", maxLength: 200, nullable: true),
                    from = table.Column<DateOnly>(type: "date", nullable: true),
                    until = table.Column<DateOnly>(type: "date", nullable: true),
                    lost_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    image_embeddings = table.Column<string>(type: "jsonb", nullable: false),
                    model_id = table.Column<string>(type: "text", nullable: false),
                    model_revision = table.Column<string>(type: "text", nullable: false),
                    dimensions = table.Column<int>(type: "integer", nullable: false),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    next_check_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    after_item_id = table.Column<Guid>(type: "uuid", nullable: true),
                    last_checked_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    needs_refresh = table.Column<bool>(type: "boolean", nullable: false),
                    lease_token = table.Column<Guid>(type: "uuid", nullable: true),
                    lease_until = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_saved_searches", x => x.id);
                    table.CheckConstraint("saved_search_dates_check", "\"from\" IS NULL OR until IS NULL OR \"from\" <= until");
                    table.CheckConstraint("saved_search_images_check", "jsonb_typeof(image_embeddings) = 'array' AND jsonb_array_length(image_embeddings) <= 3");
                    table.CheckConstraint("saved_search_input_check", "(text IS NOT NULL AND char_length(btrim(text)) BETWEEN 1 AND 2000) OR jsonb_array_length(image_embeddings) > 0");
                    table.CheckConstraint("saved_search_lease_check", "(lease_token IS NULL) = (lease_until IS NULL)");
                    table.ForeignKey(
                        name: "FK_saved_searches_app_users_user_id",
                        column: x => x.user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "saved_search_matches",
                columns: table => new
                {
                    saved_search_id = table.Column<Guid>(type: "uuid", nullable: false),
                    item_id = table.Column<Guid>(type: "uuid", nullable: false),
                    document_version = table.Column<long>(type: "bigint", nullable: false),
                    score = table.Column<double>(type: "double precision", nullable: false),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    read_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_saved_search_matches", x => new { x.saved_search_id, x.item_id });
                    table.CheckConstraint("saved_search_match_score_check", "score >= 0.85 AND score <= 1 AND document_version > 0");
                    table.ForeignKey(
                        name: "FK_saved_search_matches_items_item_id",
                        column: x => x.item_id,
                        principalTable: "items",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_saved_search_matches_saved_searches_saved_search_id",
                        column: x => x.saved_search_id,
                        principalTable: "saved_searches",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.AddCheckConstraint(
                name: "idempotency_resource_check",
                table: "idempotency_keys",
                sql: "resource_type IN ('item', 'image', 'claim', 'intake', 'custody_event', 'saved_search')");

            migrationBuilder.CreateIndex(
                name: "IX_saved_search_matches_item_id",
                table: "saved_search_matches",
                column: "item_id");

            migrationBuilder.CreateIndex(
                name: "IX_saved_searches_next_check_at_id",
                table: "saved_searches",
                columns: new[] { "next_check_at", "id" },
                filter: "NOT needs_refresh");

            migrationBuilder.CreateIndex(
                name: "IX_saved_searches_user_id_created_at",
                table: "saved_searches",
                columns: new[] { "user_id", "created_at" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql("DELETE FROM idempotency_keys WHERE resource_type = 'saved_search';");

            migrationBuilder.DropTable(
                name: "saved_search_matches");

            migrationBuilder.DropTable(
                name: "saved_searches");

            migrationBuilder.DropCheckConstraint(
                name: "idempotency_resource_check",
                table: "idempotency_keys");

            migrationBuilder.AddCheckConstraint(
                name: "idempotency_resource_check",
                table: "idempotency_keys",
                sql: "resource_type IN ('item', 'image', 'claim', 'intake', 'custody_event')");
        }
    }
}
