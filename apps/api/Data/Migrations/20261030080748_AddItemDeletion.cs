using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Findie.Api.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddItemDeletion : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropCheckConstraint(
                name: "items_lifecycle_check",
                table: "items");

            migrationBuilder.AddCheckConstraint(
                name: "items_lifecycle_check",
                table: "items",
                sql: "lifecycle IN ('active', 'returned', 'deleted')");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropCheckConstraint(
                name: "items_lifecycle_check",
                table: "items");

            migrationBuilder.AddCheckConstraint(
                name: "items_lifecycle_check",
                table: "items",
                sql: "lifecycle IN ('active', 'returned')");
        }
    }
}
