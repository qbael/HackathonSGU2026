using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Findie.Api.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddOriginalImageEmbedding : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "original_embedding",
                table: "item_images",
                type: "jsonb",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "original_embedding",
                table: "item_images");
        }
    }
}
