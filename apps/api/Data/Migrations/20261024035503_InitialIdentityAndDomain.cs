using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace Findie.Api.Data.Migrations
{
    /// <inheritdoc />
    public partial class InitialIdentityAndDomain : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "app_users",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    display_name = table.Column<string>(type: "character varying(120)", maxLength: 120, nullable: false),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    disabled_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    user_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: true),
                    normalized_user_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: true),
                    email = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: true),
                    normalized_email = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: true),
                    email_confirmed = table.Column<bool>(type: "boolean", nullable: false),
                    password_hash = table.Column<string>(type: "text", nullable: true),
                    security_stamp = table.Column<string>(type: "text", nullable: true),
                    concurrency_stamp = table.Column<string>(type: "text", nullable: true),
                    phone_number = table.Column<string>(type: "text", nullable: true),
                    phone_number_confirmed = table.Column<bool>(type: "boolean", nullable: false),
                    two_factor_enabled = table.Column<bool>(type: "boolean", nullable: false),
                    lockout_end = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    lockout_enabled = table.Column<bool>(type: "boolean", nullable: false),
                    access_failed_count = table.Column<int>(type: "integer", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_app_users", x => x.id);
                    table.CheckConstraint("users_display_name_check", "char_length(btrim(display_name)) BETWEEN 1 AND 120");
                });

            migrationBuilder.CreateTable(
                name: "index_outbox",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    item_id = table.Column<Guid>(type: "uuid", nullable: false),
                    document_version = table.Column<long>(type: "bigint", nullable: false),
                    event_kind = table.Column<string>(type: "text", nullable: false),
                    payload = table.Column<string>(type: "jsonb", nullable: false),
                    payload_sha256 = table.Column<string>(type: "text", nullable: false),
                    status = table.Column<string>(type: "text", nullable: false, defaultValue: "pending"),
                    attempts = table.Column<int>(type: "integer", nullable: false, defaultValue: 0),
                    max_attempts = table.Column<int>(type: "integer", nullable: false),
                    next_attempt_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    lease_token = table.Column<Guid>(type: "uuid", nullable: true),
                    lease_until = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    last_error_code = table.Column<string>(type: "text", nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    finished_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_index_outbox", x => x.id);
                    table.CheckConstraint("outbox_attempts_check", "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts");
                    table.CheckConstraint("outbox_finished_check", "(status IN ('succeeded', 'failed', 'obsolete')) = (finished_at IS NOT NULL)");
                    table.CheckConstraint("outbox_hash_check", "payload_sha256 ~ '^[0-9a-f]{64}$'");
                    table.CheckConstraint("outbox_kind_check", "event_kind IN ('snapshot', 'tombstone')");
                    table.CheckConstraint("outbox_lease_check", "(status = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR (status <> 'running' AND lease_token IS NULL AND lease_until IS NULL)");
                    table.CheckConstraint("outbox_payload_check", "jsonb_typeof(payload) = 'object'");
                    table.CheckConstraint("outbox_status_check", "status IN ('pending', 'running', 'retry', 'succeeded', 'failed', 'obsolete')");
                    table.CheckConstraint("outbox_version_check", "document_version > 0");
                });

            migrationBuilder.CreateTable(
                name: "reception_points",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    name = table.Column<string>(type: "text", nullable: false),
                    public_address = table.Column<string>(type: "text", nullable: false),
                    directions = table.Column<string>(type: "text", nullable: true),
                    active = table.Column<bool>(type: "boolean", nullable: false, defaultValue: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_reception_points", x => x.id);
                    table.CheckConstraint("points_address_check", "btrim(public_address) <> ''");
                    table.CheckConstraint("points_name_check", "btrim(name) <> ''");
                });

            migrationBuilder.CreateTable(
                name: "roles",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: true),
                    normalized_name = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: true),
                    concurrency_stamp = table.Column<string>(type: "text", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_roles", x => x.id);
                });

            migrationBuilder.CreateTable(
                name: "idempotency_keys",
                columns: table => new
                {
                    actor_user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    idempotency_key = table.Column<Guid>(type: "uuid", nullable: false),
                    operation = table.Column<string>(type: "text", nullable: false),
                    request_sha256 = table.Column<string>(type: "text", nullable: false),
                    resource_type = table.Column<string>(type: "text", nullable: false),
                    resource_id = table.Column<Guid>(type: "uuid", nullable: false),
                    response_status = table.Column<short>(type: "smallint", nullable: false),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_idempotency_keys", x => new { x.actor_user_id, x.idempotency_key });
                    table.CheckConstraint("idempotency_hash_check", "request_sha256 ~ '^[0-9a-f]{64}$'");
                    table.CheckConstraint("idempotency_operation_check", "btrim(operation) <> ''");
                    table.CheckConstraint("idempotency_resource_check", "resource_type IN ('item', 'image', 'claim', 'intake', 'custody_event')");
                    table.CheckConstraint("idempotency_response_check", "response_status BETWEEN 200 AND 299");
                    table.ForeignKey(
                        name: "FK_idempotency_keys_app_users_actor_user_id",
                        column: x => x.actor_user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "stored_objects",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    owner_user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    bucket = table.Column<string>(type: "text", nullable: false),
                    object_key = table.Column<string>(type: "text", nullable: false),
                    object_kind = table.Column<string>(type: "text", nullable: false, defaultValue: "processed"),
                    object_state = table.Column<string>(type: "text", nullable: false, defaultValue: "reserved"),
                    sha256 = table.Column<string>(type: "text", nullable: true),
                    content_type = table.Column<string>(type: "text", nullable: true),
                    byte_size = table.Column<long>(type: "bigint", nullable: true),
                    width = table.Column<int>(type: "integer", nullable: true),
                    height = table.Column<int>(type: "integer", nullable: true),
                    expires_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    cleanup_next_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    cleanup_attempts = table.Column<int>(type: "integer", nullable: false, defaultValue: 0),
                    last_error_code = table.Column<string>(type: "text", nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    validated_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    deleted_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_stored_objects", x => x.id);
                    table.CheckConstraint("objects_attempts_check", "cleanup_attempts >= 0");
                    table.CheckConstraint("objects_deleted_check", "(object_state = 'deleted') = (deleted_at IS NOT NULL)");
                    table.CheckConstraint("objects_dimensions_check", "byte_size > 0 AND width > 0 AND height > 0");
                    table.CheckConstraint("objects_hash_check", "sha256 ~ '^[0-9a-f]{64}$'");
                    table.CheckConstraint("objects_key_check", "btrim(bucket) <> '' AND btrim(object_key) <> ''");
                    table.CheckConstraint("objects_kind_check", "object_kind = 'processed'");
                    table.CheckConstraint("objects_reserved_check", "object_state <> 'reserved' OR expires_at IS NOT NULL");
                    table.CheckConstraint("objects_state_check", "object_state IN ('reserved', 'validated', 'delete_pending', 'deleted')");
                    table.CheckConstraint("objects_type_check", "content_type IN ('image/jpeg', 'image/png', 'image/webp')");
                    table.CheckConstraint("objects_validated_check", "object_state <> 'validated' OR (sha256 IS NOT NULL AND content_type IS NOT NULL AND byte_size IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL AND validated_at IS NOT NULL)");
                    table.ForeignKey(
                        name: "FK_stored_objects_app_users_owner_user_id",
                        column: x => x.owner_user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "user_claims",
                columns: table => new
                {
                    id = table.Column<int>(type: "integer", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    claim_type = table.Column<string>(type: "text", nullable: true),
                    claim_value = table.Column<string>(type: "text", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_user_claims", x => x.id);
                    table.ForeignKey(
                        name: "FK_user_claims_app_users_user_id",
                        column: x => x.user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "user_logins",
                columns: table => new
                {
                    login_provider = table.Column<string>(type: "text", nullable: false),
                    provider_key = table.Column<string>(type: "text", nullable: false),
                    provider_display_name = table.Column<string>(type: "text", nullable: true),
                    user_id = table.Column<Guid>(type: "uuid", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_user_logins", x => new { x.login_provider, x.provider_key });
                    table.ForeignKey(
                        name: "FK_user_logins_app_users_user_id",
                        column: x => x.user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "user_tokens",
                columns: table => new
                {
                    user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    login_provider = table.Column<string>(type: "text", nullable: false),
                    name = table.Column<string>(type: "text", nullable: false),
                    value = table.Column<string>(type: "text", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_user_tokens", x => new { x.user_id, x.login_provider, x.name });
                    table.ForeignKey(
                        name: "FK_user_tokens_app_users_user_id",
                        column: x => x.user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "items",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    posted_by = table.Column<Guid>(type: "uuid", nullable: false),
                    title = table.Column<string>(type: "character varying(200)", maxLength: 200, nullable: false),
                    public_description = table.Column<string>(type: "character varying(5000)", maxLength: 5000, nullable: false),
                    found_area = table.Column<string>(type: "text", nullable: false),
                    found_time_precision = table.Column<string>(type: "text", nullable: false, defaultValue: "unknown"),
                    found_on = table.Column<DateOnly>(type: "date", nullable: true),
                    found_from = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    found_until = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    found_timezone = table.Column<string>(type: "text", nullable: false, defaultValue: "Asia/Ho_Chi_Minh"),
                    custody_kind = table.Column<string>(type: "text", nullable: false),
                    holder_user_id = table.Column<Guid>(type: "uuid", nullable: true),
                    holder_point_id = table.Column<Guid>(type: "uuid", nullable: true),
                    external_name = table.Column<string>(type: "text", nullable: true),
                    external_public_address = table.Column<string>(type: "text", nullable: true),
                    external_instructions = table.Column<string>(type: "text", nullable: true),
                    lifecycle = table.Column<string>(type: "text", nullable: false, defaultValue: "active"),
                    publication_state = table.Column<string>(type: "text", nullable: false, defaultValue: "draft"),
                    content_version = table.Column<long>(type: "bigint", nullable: false, defaultValue: 1L),
                    custody_version = table.Column<long>(type: "bigint", nullable: false, defaultValue: 1L),
                    row_version = table.Column<long>(type: "bigint", nullable: false, defaultValue: 1L),
                    document_version = table.Column<long>(type: "bigint", nullable: false, defaultValue: 1L),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    updated_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_items", x => x.id);
                    table.CheckConstraint("items_area_check", "btrim(found_area) <> ''");
                    table.CheckConstraint("items_custody_check", "(custody_kind = 'person' AND holder_user_id IS NOT NULL AND holder_point_id IS NULL AND external_name IS NULL AND external_public_address IS NULL AND external_instructions IS NULL) OR\n(custody_kind = 'point' AND holder_user_id IS NULL AND holder_point_id IS NOT NULL AND external_name IS NULL AND external_public_address IS NULL AND external_instructions IS NULL) OR\n(custody_kind = 'external' AND holder_user_id IS NULL AND holder_point_id IS NULL AND external_name IS NOT NULL AND btrim(external_name) <> '' AND external_public_address IS NOT NULL AND btrim(external_public_address) <> '')");
                    table.CheckConstraint("items_description_check", "char_length(btrim(public_description)) BETWEEN 1 AND 5000");
                    table.CheckConstraint("items_found_time_check", "(found_time_precision = 'unknown' AND found_on IS NULL AND found_from IS NULL AND found_until IS NULL) OR\n(found_time_precision = 'date' AND found_on IS NOT NULL AND found_from IS NULL AND found_until IS NULL) OR\n(found_time_precision = 'exact' AND found_on IS NULL AND found_from IS NOT NULL AND found_until IS NULL) OR\n(found_time_precision = 'range' AND found_on IS NULL AND found_from IS NOT NULL AND found_until IS NOT NULL AND found_from <= found_until)");
                    table.CheckConstraint("items_lifecycle_check", "lifecycle IN ('active', 'returned')");
                    table.CheckConstraint("items_publication_check", "publication_state IN ('draft', 'published', 'hidden')");
                    table.CheckConstraint("items_timezone_check", "btrim(found_timezone) <> ''");
                    table.CheckConstraint("items_title_check", "char_length(btrim(title)) BETWEEN 1 AND 200");
                    table.CheckConstraint("items_versions_check", "content_version > 0 AND custody_version > 0 AND row_version > 0 AND document_version > 0");
                    table.ForeignKey(
                        name: "FK_items_app_users_holder_user_id",
                        column: x => x.holder_user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_items_app_users_posted_by",
                        column: x => x.posted_by,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_items_reception_points_holder_point_id",
                        column: x => x.holder_point_id,
                        principalTable: "reception_points",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "point_staff",
                columns: table => new
                {
                    point_id = table.Column<Guid>(type: "uuid", nullable: false),
                    user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    can_receive = table.Column<bool>(type: "boolean", nullable: false),
                    can_return = table.Column<bool>(type: "boolean", nullable: false),
                    assigned_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    revoked_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_point_staff", x => new { x.point_id, x.user_id });
                    table.CheckConstraint("staff_permissions_check", "can_receive OR can_return");
                    table.ForeignKey(
                        name: "FK_point_staff_app_users_user_id",
                        column: x => x.user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_point_staff_reception_points_point_id",
                        column: x => x.point_id,
                        principalTable: "reception_points",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "role_claims",
                columns: table => new
                {
                    id = table.Column<int>(type: "integer", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    role_id = table.Column<Guid>(type: "uuid", nullable: false),
                    claim_type = table.Column<string>(type: "text", nullable: true),
                    claim_value = table.Column<string>(type: "text", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_role_claims", x => x.id);
                    table.ForeignKey(
                        name: "FK_role_claims_roles_role_id",
                        column: x => x.role_id,
                        principalTable: "roles",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "user_roles",
                columns: table => new
                {
                    user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    role_id = table.Column<Guid>(type: "uuid", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_user_roles", x => new { x.user_id, x.role_id });
                    table.ForeignKey(
                        name: "FK_user_roles_app_users_user_id",
                        column: x => x.user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_user_roles_roles_role_id",
                        column: x => x.role_id,
                        principalTable: "roles",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "claims",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    item_id = table.Column<Guid>(type: "uuid", nullable: false),
                    claimant_user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    reviewer_user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    source_custody_version = table.Column<long>(type: "bigint", nullable: false),
                    status = table.Column<string>(type: "text", nullable: false, defaultValue: "pending"),
                    decided_by = table.Column<Guid>(type: "uuid", nullable: true),
                    decided_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    decision_note = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_claims", x => x.id);
                    table.UniqueConstraint("AK_claims_id_item_id", x => new { x.id, x.item_id });
                    table.UniqueConstraint("AK_claims_id_status", x => new { x.id, x.status });
                    table.CheckConstraint("claims_decision_check", "(status = 'pending' AND decided_by IS NULL AND decided_at IS NULL) OR (status <> 'pending' AND decided_by IS NOT NULL AND decided_by = reviewer_user_id AND decided_at IS NOT NULL)");
                    table.CheckConstraint("claims_participants_check", "claimant_user_id <> reviewer_user_id");
                    table.CheckConstraint("claims_status_check", "status IN ('pending', 'approved', 'rejected')");
                    table.CheckConstraint("claims_version_check", "source_custody_version > 0");
                    table.ForeignKey(
                        name: "FK_claims_app_users_claimant_user_id",
                        column: x => x.claimant_user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_claims_app_users_decided_by",
                        column: x => x.decided_by,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_claims_app_users_reviewer_user_id",
                        column: x => x.reviewer_user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_claims_items_item_id",
                        column: x => x.item_id,
                        principalTable: "items",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "intake_requests",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    item_id = table.Column<Guid>(type: "uuid", nullable: false),
                    requested_by = table.Column<Guid>(type: "uuid", nullable: false),
                    target_point_id = table.Column<Guid>(type: "uuid", nullable: false),
                    source_custody_version = table.Column<long>(type: "bigint", nullable: false),
                    status = table.Column<string>(type: "text", nullable: false, defaultValue: "pending"),
                    decided_by = table.Column<Guid>(type: "uuid", nullable: true),
                    decided_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    decision_note = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_intake_requests", x => x.id);
                    table.UniqueConstraint("AK_intake_requests_id_item_id", x => new { x.id, x.item_id });
                    table.CheckConstraint("intake_decision_check", "(status = 'pending' AND decided_by IS NULL AND decided_at IS NULL) OR (status <> 'pending' AND decided_by IS NOT NULL AND decided_at IS NOT NULL)");
                    table.CheckConstraint("intake_status_check", "status IN ('pending', 'received', 'rejected')");
                    table.CheckConstraint("intake_version_check", "source_custody_version > 0");
                    table.ForeignKey(
                        name: "FK_intake_requests_app_users_decided_by",
                        column: x => x.decided_by,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_intake_requests_app_users_requested_by",
                        column: x => x.requested_by,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_intake_requests_items_item_id",
                        column: x => x.item_id,
                        principalTable: "items",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_intake_requests_reception_points_target_point_id",
                        column: x => x.target_point_id,
                        principalTable: "reception_points",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "item_images",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    item_id = table.Column<Guid>(type: "uuid", nullable: false),
                    position = table.Column<short>(type: "smallint", nullable: false),
                    processed_object_id = table.Column<Guid>(type: "uuid", nullable: true),
                    content_version = table.Column<long>(type: "bigint", nullable: false, defaultValue: 1L),
                    processing_state = table.Column<string>(type: "text", nullable: false, defaultValue: "pending"),
                    review_state = table.Column<string>(type: "text", nullable: false, defaultValue: "pending"),
                    sensitive_regions = table.Column<string>(type: "jsonb", nullable: true),
                    redaction_model_id = table.Column<string>(type: "text", nullable: true),
                    redaction_model_revision = table.Column<string>(type: "text", nullable: true),
                    redaction_profile = table.Column<string>(type: "text", nullable: true),
                    reviewed_by = table.Column<Guid>(type: "uuid", nullable: true),
                    reviewed_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    failure_code = table.Column<string>(type: "text", nullable: true),
                    retired_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_item_images", x => x.id);
                    table.UniqueConstraint("AK_item_images_id_item_id", x => new { x.id, x.item_id });
                    table.CheckConstraint("images_output_check", "processing_state NOT IN ('needs_review', 'ready') OR (processed_object_id IS NOT NULL AND redaction_model_id IS NOT NULL AND redaction_model_revision IS NOT NULL AND redaction_profile IS NOT NULL)");
                    table.CheckConstraint("images_position_check", "position > 0 AND content_version > 0");
                    table.CheckConstraint("images_processing_check", "processing_state IN ('pending', 'processing', 'needs_review', 'ready', 'failed', 'rejected')");
                    table.CheckConstraint("images_ready_check", "processing_state <> 'ready' OR review_state = 'approved'");
                    table.CheckConstraint("images_regions_check", "jsonb_typeof(sensitive_regions) = 'array'");
                    table.CheckConstraint("images_rejected_check", "processing_state <> 'rejected' OR review_state = 'rejected'");
                    table.CheckConstraint("images_review_check", "review_state IN ('pending', 'approved', 'rejected')");
                    table.CheckConstraint("images_reviewer_check", "(review_state = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR (review_state IN ('approved', 'rejected') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)");
                    table.ForeignKey(
                        name: "FK_item_images_app_users_reviewed_by",
                        column: x => x.reviewed_by,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_item_images_items_item_id",
                        column: x => x.item_id,
                        principalTable: "items",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_item_images_stored_objects_processed_object_id",
                        column: x => x.processed_object_id,
                        principalTable: "stored_objects",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "verification_questions",
                columns: table => new
                {
                    item_id = table.Column<Guid>(type: "uuid", nullable: false),
                    slot = table.Column<short>(type: "smallint", nullable: false),
                    question_text = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_verification_questions", x => new { x.item_id, x.slot });
                    table.CheckConstraint("questions_slot_check", "slot BETWEEN 1 AND 3");
                    table.CheckConstraint("questions_text_check", "char_length(btrim(question_text)) BETWEEN 1 AND 500");
                    table.ForeignKey(
                        name: "FK_verification_questions_items_item_id",
                        column: x => x.item_id,
                        principalTable: "items",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "claim_answers",
                columns: table => new
                {
                    claim_id = table.Column<Guid>(type: "uuid", nullable: false),
                    slot = table.Column<short>(type: "smallint", nullable: false),
                    question_text_snapshot = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: false),
                    answer_text = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_claim_answers", x => new { x.claim_id, x.slot });
                    table.CheckConstraint("answers_question_check", "char_length(btrim(question_text_snapshot)) BETWEEN 1 AND 500");
                    table.CheckConstraint("answers_slot_check", "slot BETWEEN 1 AND 3");
                    table.CheckConstraint("answers_text_check", "char_length(btrim(answer_text)) BETWEEN 1 AND 2000");
                    table.ForeignKey(
                        name: "FK_claim_answers_claims_claim_id",
                        column: x => x.claim_id,
                        principalTable: "claims",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "conversations",
                columns: table => new
                {
                    claim_id = table.Column<Guid>(type: "uuid", nullable: false),
                    approval_status = table.Column<string>(type: "text", nullable: false, defaultValue: "approved"),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_conversations", x => x.claim_id);
                    table.CheckConstraint("conversations_approval_check", "approval_status = 'approved'");
                    table.ForeignKey(
                        name: "FK_conversations_claims_claim_id_approval_status",
                        columns: x => new { x.claim_id, x.approval_status },
                        principalTable: "claims",
                        principalColumns: new[] { "id", "status" },
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "custody_events",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    item_id = table.Column<Guid>(type: "uuid", nullable: false),
                    event_kind = table.Column<string>(type: "text", nullable: false),
                    custody_version = table.Column<long>(type: "bigint", nullable: false),
                    actor_user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    intake_request_id = table.Column<Guid>(type: "uuid", nullable: true),
                    claim_id = table.Column<Guid>(type: "uuid", nullable: true),
                    recipient_user_id = table.Column<Guid>(type: "uuid", nullable: true),
                    from_custody = table.Column<string>(type: "jsonb", nullable: true),
                    to_custody = table.Column<string>(type: "jsonb", nullable: true),
                    verification_note = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true),
                    occurred_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    recorded_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_custody_events", x => x.id);
                    table.CheckConstraint("custody_event_check", "(event_kind = 'registered' AND from_custody IS NULL AND to_custody IS NOT NULL AND intake_request_id IS NULL AND claim_id IS NULL AND recipient_user_id IS NULL) OR\n(event_kind = 'received' AND from_custody IS NOT NULL AND to_custody IS NOT NULL AND intake_request_id IS NOT NULL AND claim_id IS NULL AND recipient_user_id IS NULL) OR\n(event_kind = 'returned' AND from_custody IS NOT NULL AND to_custody IS NULL AND intake_request_id IS NULL)");
                    table.CheckConstraint("custody_from_check", "jsonb_typeof(from_custody) = 'object'");
                    table.CheckConstraint("custody_to_check", "jsonb_typeof(to_custody) = 'object'");
                    table.CheckConstraint("custody_version_check", "custody_version > 0");
                    table.ForeignKey(
                        name: "FK_custody_events_app_users_actor_user_id",
                        column: x => x.actor_user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_custody_events_app_users_recipient_user_id",
                        column: x => x.recipient_user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_custody_events_claims_claim_id_item_id",
                        columns: x => new { x.claim_id, x.item_id },
                        principalTable: "claims",
                        principalColumns: new[] { "id", "item_id" },
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_custody_events_intake_requests_intake_request_id_item_id",
                        columns: x => new { x.intake_request_id, x.item_id },
                        principalTable: "intake_requests",
                        principalColumns: new[] { "id", "item_id" },
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_custody_events_items_item_id",
                        column: x => x.item_id,
                        principalTable: "items",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "ai_jobs",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    item_id = table.Column<Guid>(type: "uuid", nullable: false),
                    image_id = table.Column<Guid>(type: "uuid", nullable: true),
                    job_kind = table.Column<string>(type: "text", nullable: false),
                    source_version = table.Column<long>(type: "bigint", nullable: false),
                    source_sha256 = table.Column<string>(type: "text", nullable: false),
                    model_id = table.Column<string>(type: "text", nullable: false),
                    model_revision = table.Column<string>(type: "text", nullable: false),
                    processing_profile = table.Column<string>(type: "text", nullable: false),
                    status = table.Column<string>(type: "text", nullable: false, defaultValue: "pending"),
                    attempts = table.Column<int>(type: "integer", nullable: false, defaultValue: 0),
                    max_attempts = table.Column<int>(type: "integer", nullable: false),
                    next_attempt_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    lease_token = table.Column<Guid>(type: "uuid", nullable: true),
                    lease_until = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    last_error_code = table.Column<string>(type: "text", nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    finished_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_ai_jobs", x => x.id);
                    table.CheckConstraint("jobs_attempts_check", "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts");
                    table.CheckConstraint("jobs_finished_check", "(status IN ('succeeded', 'failed', 'obsolete')) = (finished_at IS NOT NULL)");
                    table.CheckConstraint("jobs_kind_check", "(job_kind = 'embed_text' AND image_id IS NULL) OR (job_kind = 'embed_image' AND image_id IS NOT NULL)");
                    table.CheckConstraint("jobs_lease_check", "(status = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR (status <> 'running' AND lease_token IS NULL AND lease_until IS NULL)");
                    table.CheckConstraint("jobs_model_check", "btrim(model_id) <> '' AND btrim(model_revision) <> '' AND btrim(processing_profile) <> ''");
                    table.CheckConstraint("jobs_source_check", "source_version > 0 AND source_sha256 ~ '^[0-9a-f]{64}$'");
                    table.CheckConstraint("jobs_status_check", "status IN ('pending', 'running', 'retry', 'succeeded', 'failed', 'obsolete')");
                    table.ForeignKey(
                        name: "FK_ai_jobs_item_images_image_id_item_id",
                        columns: x => new { x.image_id, x.item_id },
                        principalTable: "item_images",
                        principalColumns: new[] { "id", "item_id" },
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_ai_jobs_items_item_id",
                        column: x => x.item_id,
                        principalTable: "items",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "messages",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    conversation_id = table.Column<Guid>(type: "uuid", nullable: false),
                    sender_user_id = table.Column<Guid>(type: "uuid", nullable: false),
                    client_message_id = table.Column<Guid>(type: "uuid", nullable: false),
                    message_sequence = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityAlwaysColumn),
                    body = table.Column<string>(type: "character varying(4000)", maxLength: 4000, nullable: false),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_messages", x => x.id);
                    table.CheckConstraint("messages_body_check", "char_length(btrim(body)) BETWEEN 1 AND 4000");
                    table.ForeignKey(
                        name: "FK_messages_app_users_sender_user_id",
                        column: x => x.sender_user_id,
                        principalTable: "app_users",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_messages_conversations_conversation_id",
                        column: x => x.conversation_id,
                        principalTable: "conversations",
                        principalColumn: "claim_id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "IX_ai_jobs_image_id_item_id",
                table: "ai_jobs",
                columns: new[] { "image_id", "item_id" });

            migrationBuilder.CreateIndex(
                name: "IX_ai_jobs_image_id_source_version_job_kind_model_id_model_rev~",
                table: "ai_jobs",
                columns: new[] { "image_id", "source_version", "job_kind", "model_id", "model_revision", "processing_profile" },
                unique: true,
                filter: "image_id IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "IX_ai_jobs_item_id_source_version_job_kind_model_id_model_revi~",
                table: "ai_jobs",
                columns: new[] { "item_id", "source_version", "job_kind", "model_id", "model_revision", "processing_profile" },
                unique: true,
                filter: "image_id IS NULL");

            migrationBuilder.CreateIndex(
                name: "IX_ai_jobs_lease_until",
                table: "ai_jobs",
                column: "lease_until",
                filter: "status = 'running'");

            migrationBuilder.CreateIndex(
                name: "IX_ai_jobs_next_attempt_at_id",
                table: "ai_jobs",
                columns: new[] { "next_attempt_at", "id" },
                filter: "status IN ('pending', 'retry')");

            migrationBuilder.CreateIndex(
                name: "EmailIndex",
                table: "app_users",
                column: "normalized_email",
                unique: true,
                filter: "normalized_email IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "UserNameIndex",
                table: "app_users",
                column: "normalized_user_name",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_claims_claimant_user_id_created_at",
                table: "claims",
                columns: new[] { "claimant_user_id", "created_at" },
                descending: new[] { false, true });

            migrationBuilder.CreateIndex(
                name: "IX_claims_decided_by",
                table: "claims",
                column: "decided_by");

            migrationBuilder.CreateIndex(
                name: "IX_claims_item_id_status_created_at",
                table: "claims",
                columns: new[] { "item_id", "status", "created_at" });

            migrationBuilder.CreateIndex(
                name: "IX_claims_reviewer_user_id_status_created_at",
                table: "claims",
                columns: new[] { "reviewer_user_id", "status", "created_at" });

            migrationBuilder.CreateIndex(
                name: "IX_conversations_claim_id_approval_status",
                table: "conversations",
                columns: new[] { "claim_id", "approval_status" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "custody_one_registration",
                table: "custody_events",
                column: "item_id",
                unique: true,
                filter: "event_kind = 'registered'");

            migrationBuilder.CreateIndex(
                name: "custody_one_return",
                table: "custody_events",
                column: "item_id",
                unique: true,
                filter: "event_kind = 'returned'");

            migrationBuilder.CreateIndex(
                name: "IX_custody_events_actor_user_id",
                table: "custody_events",
                column: "actor_user_id");

            migrationBuilder.CreateIndex(
                name: "IX_custody_events_claim_id_item_id",
                table: "custody_events",
                columns: new[] { "claim_id", "item_id" });

            migrationBuilder.CreateIndex(
                name: "IX_custody_events_intake_request_id",
                table: "custody_events",
                column: "intake_request_id",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_custody_events_intake_request_id_item_id",
                table: "custody_events",
                columns: new[] { "intake_request_id", "item_id" });

            migrationBuilder.CreateIndex(
                name: "IX_custody_events_item_id_custody_version",
                table: "custody_events",
                columns: new[] { "item_id", "custody_version" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_custody_events_item_id_occurred_at_id",
                table: "custody_events",
                columns: new[] { "item_id", "occurred_at", "id" });

            migrationBuilder.CreateIndex(
                name: "IX_custody_events_recipient_user_id",
                table: "custody_events",
                column: "recipient_user_id");

            migrationBuilder.CreateIndex(
                name: "IX_index_outbox_item_id_document_version",
                table: "index_outbox",
                columns: new[] { "item_id", "document_version" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_index_outbox_lease_until",
                table: "index_outbox",
                column: "lease_until",
                filter: "status = 'running'");

            migrationBuilder.CreateIndex(
                name: "IX_index_outbox_next_attempt_at_id",
                table: "index_outbox",
                columns: new[] { "next_attempt_at", "id" },
                filter: "status IN ('pending', 'retry')");

            migrationBuilder.CreateIndex(
                name: "IX_intake_requests_decided_by",
                table: "intake_requests",
                column: "decided_by");

            migrationBuilder.CreateIndex(
                name: "IX_intake_requests_item_id_status",
                table: "intake_requests",
                columns: new[] { "item_id", "status" });

            migrationBuilder.CreateIndex(
                name: "IX_intake_requests_requested_by_created_at",
                table: "intake_requests",
                columns: new[] { "requested_by", "created_at" },
                descending: new[] { false, true });

            migrationBuilder.CreateIndex(
                name: "IX_intake_requests_target_point_id_status_created_at",
                table: "intake_requests",
                columns: new[] { "target_point_id", "status", "created_at" });

            migrationBuilder.CreateIndex(
                name: "IX_item_images_item_id_position",
                table: "item_images",
                columns: new[] { "item_id", "position" },
                unique: true,
                filter: "retired_at IS NULL");

            migrationBuilder.CreateIndex(
                name: "IX_item_images_processed_object_id",
                table: "item_images",
                column: "processed_object_id",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_item_images_reviewed_by",
                table: "item_images",
                column: "reviewed_by");

            migrationBuilder.CreateIndex(
                name: "IX_items_created_at_id",
                table: "items",
                columns: new[] { "created_at", "id" },
                descending: new[] { true, false },
                filter: "publication_state = 'published' AND lifecycle = 'active'");

            migrationBuilder.CreateIndex(
                name: "IX_items_found_from_found_until",
                table: "items",
                columns: new[] { "found_from", "found_until" },
                filter: "found_from IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "IX_items_found_on",
                table: "items",
                column: "found_on",
                filter: "found_on IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "IX_items_holder_point_id",
                table: "items",
                column: "holder_point_id");

            migrationBuilder.CreateIndex(
                name: "IX_items_holder_user_id",
                table: "items",
                column: "holder_user_id");

            migrationBuilder.CreateIndex(
                name: "IX_items_posted_by_created_at",
                table: "items",
                columns: new[] { "posted_by", "created_at" },
                descending: new[] { false, true });

            migrationBuilder.CreateIndex(
                name: "IX_messages_conversation_id_message_sequence",
                table: "messages",
                columns: new[] { "conversation_id", "message_sequence" });

            migrationBuilder.CreateIndex(
                name: "IX_messages_conversation_id_sender_user_id_client_message_id",
                table: "messages",
                columns: new[] { "conversation_id", "sender_user_id", "client_message_id" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_messages_message_sequence",
                table: "messages",
                column: "message_sequence",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_messages_sender_user_id",
                table: "messages",
                column: "sender_user_id");

            migrationBuilder.CreateIndex(
                name: "IX_point_staff_user_id",
                table: "point_staff",
                column: "user_id",
                filter: "revoked_at IS NULL");

            migrationBuilder.CreateIndex(
                name: "IX_reception_points_name_id",
                table: "reception_points",
                columns: new[] { "name", "id" },
                filter: "active");

            migrationBuilder.CreateIndex(
                name: "IX_role_claims_role_id",
                table: "role_claims",
                column: "role_id");

            migrationBuilder.CreateIndex(
                name: "RoleNameIndex",
                table: "roles",
                column: "normalized_name",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_stored_objects_bucket_object_key",
                table: "stored_objects",
                columns: new[] { "bucket", "object_key" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_stored_objects_cleanup_next_at_expires_at",
                table: "stored_objects",
                columns: new[] { "cleanup_next_at", "expires_at" },
                filter: "object_state <> 'deleted'");

            migrationBuilder.CreateIndex(
                name: "IX_stored_objects_owner_user_id",
                table: "stored_objects",
                column: "owner_user_id");

            migrationBuilder.CreateIndex(
                name: "IX_user_claims_user_id",
                table: "user_claims",
                column: "user_id");

            migrationBuilder.CreateIndex(
                name: "IX_user_logins_user_id",
                table: "user_logins",
                column: "user_id");

            migrationBuilder.CreateIndex(
                name: "IX_user_roles_role_id",
                table: "user_roles",
                column: "role_id");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "ai_jobs");

            migrationBuilder.DropTable(
                name: "claim_answers");

            migrationBuilder.DropTable(
                name: "custody_events");

            migrationBuilder.DropTable(
                name: "idempotency_keys");

            migrationBuilder.DropTable(
                name: "index_outbox");

            migrationBuilder.DropTable(
                name: "messages");

            migrationBuilder.DropTable(
                name: "point_staff");

            migrationBuilder.DropTable(
                name: "role_claims");

            migrationBuilder.DropTable(
                name: "user_claims");

            migrationBuilder.DropTable(
                name: "user_logins");

            migrationBuilder.DropTable(
                name: "user_roles");

            migrationBuilder.DropTable(
                name: "user_tokens");

            migrationBuilder.DropTable(
                name: "verification_questions");

            migrationBuilder.DropTable(
                name: "item_images");

            migrationBuilder.DropTable(
                name: "intake_requests");

            migrationBuilder.DropTable(
                name: "conversations");

            migrationBuilder.DropTable(
                name: "roles");

            migrationBuilder.DropTable(
                name: "stored_objects");

            migrationBuilder.DropTable(
                name: "claims");

            migrationBuilder.DropTable(
                name: "items");

            migrationBuilder.DropTable(
                name: "app_users");

            migrationBuilder.DropTable(
                name: "reception_points");
        }
    }
}
