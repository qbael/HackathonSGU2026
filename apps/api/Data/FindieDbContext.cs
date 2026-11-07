using System.Text.Json;
using Findie.Api.Models;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Identity.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore;

namespace Findie.Api.Data;

public sealed class FindieDbContext(DbContextOptions<FindieDbContext> options)
    : IdentityDbContext<ApplicationUser, IdentityRole<Guid>, Guid>(options)
{
    public DbSet<ReceptionPoint> ReceptionPoints => Set<ReceptionPoint>();
    public DbSet<PointStaff> PointStaff => Set<PointStaff>();
    public DbSet<Item> Items => Set<Item>();
    public DbSet<StoredObject> StoredObjects => Set<StoredObject>();
    public DbSet<ItemImage> ItemImages => Set<ItemImage>();
    public DbSet<VerificationQuestion> VerificationQuestions => Set<VerificationQuestion>();
    public DbSet<Claim> Claims => Set<Claim>();
    public DbSet<ClaimAnswer> ClaimAnswers => Set<ClaimAnswer>();
    public DbSet<Conversation> Conversations => Set<Conversation>();
    public DbSet<Message> Messages => Set<Message>();
    public DbSet<IntakeRequest> IntakeRequests => Set<IntakeRequest>();
    public DbSet<CustodyEvent> CustodyEvents => Set<CustodyEvent>();
    public DbSet<AiJob> AiJobs => Set<AiJob>();
    public DbSet<IdempotencyKey> IdempotencyKeys => Set<IdempotencyKey>();
    public DbSet<IndexOutbox> IndexOutbox => Set<IndexOutbox>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        modelBuilder.Entity<ApplicationUser>(entity =>
        {
            entity.ToTable("app_users", table => table.HasCheckConstraint("users_display_name_check",
                "char_length(btrim(display_name)) BETWEEN 1 AND 120"));
            entity.Property(user => user.DisplayName).HasMaxLength(120);
            entity.HasIndex(user => user.NormalizedEmail).IsUnique().HasFilter("normalized_email IS NOT NULL");
        });
        modelBuilder.Entity<IdentityRole<Guid>>().ToTable("roles");
        modelBuilder.Entity<IdentityUserRole<Guid>>().ToTable("user_roles");
        modelBuilder.Entity<IdentityUserClaim<Guid>>().ToTable("user_claims");
        modelBuilder.Entity<IdentityUserLogin<Guid>>().ToTable("user_logins");
        modelBuilder.Entity<IdentityUserToken<Guid>>().ToTable("user_tokens");
        modelBuilder.Entity<IdentityRoleClaim<Guid>>().ToTable("role_claims");

        modelBuilder.Entity<ReceptionPoint>(entity =>
        {
            entity.ToTable("reception_points", table =>
            {
                table.HasCheckConstraint("points_name_check", "btrim(name) <> ''");
                table.HasCheckConstraint("points_address_check", "btrim(public_address) <> ''");
            });
            entity.Property(point => point.Active).HasDefaultValue(true);
            entity.HasIndex(point => new { point.Name, point.Id }).HasFilter("active");
        });

        modelBuilder.Entity<PointStaff>(entity =>
        {
            entity.ToTable("point_staff", table => table.HasCheckConstraint("staff_permissions_check", "can_receive OR can_return"));
            entity.HasKey(staff => new { staff.PointId, staff.UserId });
            entity.HasOne(staff => staff.Point).WithMany(point => point.Staff).HasForeignKey(staff => staff.PointId);
            entity.HasOne(staff => staff.User).WithMany().HasForeignKey(staff => staff.UserId);
            entity.HasIndex(staff => staff.UserId).HasFilter("revoked_at IS NULL");
        });

        modelBuilder.Entity<Item>(entity =>
        {
            entity.ToTable("items", table =>
            {
                table.HasCheckConstraint("items_title_check", "char_length(btrim(title)) BETWEEN 1 AND 200");
                table.HasCheckConstraint("items_description_check", "char_length(btrim(public_description)) BETWEEN 1 AND 5000");
                table.HasCheckConstraint("items_area_check", "btrim(found_area) <> ''");
                table.HasCheckConstraint("items_timezone_check", "btrim(found_timezone) <> ''");
                table.HasCheckConstraint("items_lifecycle_check", "lifecycle IN ('active', 'returned', 'deleted')");
                table.HasCheckConstraint("items_publication_check", "publication_state IN ('draft', 'published', 'hidden')");
                table.HasCheckConstraint("items_versions_check", "content_version > 0 AND custody_version > 0 AND row_version > 0 AND document_version > 0");
                table.HasCheckConstraint("items_found_time_check", """
                    (found_time_precision = 'unknown' AND found_on IS NULL AND found_from IS NULL AND found_until IS NULL) OR
                    (found_time_precision = 'date' AND found_on IS NOT NULL AND found_from IS NULL AND found_until IS NULL) OR
                    (found_time_precision = 'exact' AND found_on IS NULL AND found_from IS NOT NULL AND found_until IS NULL) OR
                    (found_time_precision = 'range' AND found_on IS NULL AND found_from IS NOT NULL AND found_until IS NOT NULL AND found_from <= found_until)
                    """);
                table.HasCheckConstraint("items_custody_check", """
                    (custody_kind = 'person' AND holder_user_id IS NOT NULL AND holder_point_id IS NULL AND external_name IS NULL AND external_public_address IS NULL AND external_instructions IS NULL) OR
                    (custody_kind = 'point' AND holder_user_id IS NULL AND holder_point_id IS NOT NULL AND external_name IS NULL AND external_public_address IS NULL AND external_instructions IS NULL) OR
                    (custody_kind = 'external' AND holder_user_id IS NULL AND holder_point_id IS NULL AND external_name IS NOT NULL AND btrim(external_name) <> '' AND external_public_address IS NOT NULL AND btrim(external_public_address) <> '')
                    """);
            });
            entity.Property(item => item.Title).HasMaxLength(200);
            entity.Property(item => item.PublicDescription).HasMaxLength(5000);
            entity.Property(item => item.FoundTimePrecision).HasDefaultValue("unknown");
            entity.Property(item => item.FoundTimezone).HasDefaultValue("Asia/Ho_Chi_Minh");
            entity.Property(item => item.Lifecycle).HasDefaultValue("active");
            entity.Property(item => item.PublicationState).HasDefaultValue("draft");
            entity.Property(item => item.ContentVersion).HasDefaultValue(1L);
            entity.Property(item => item.CustodyVersion).HasDefaultValue(1L);
            entity.Property(item => item.DocumentVersion).HasDefaultValue(1L);
            entity.Property(item => item.RowVersion).HasDefaultValue(1L).IsConcurrencyToken();
            entity.HasOne(item => item.Author).WithMany().HasForeignKey(item => item.PostedBy);
            entity.HasOne(item => item.HolderUser).WithMany().HasForeignKey(item => item.HolderUserId);
            entity.HasOne(item => item.HolderPoint).WithMany().HasForeignKey(item => item.HolderPointId);
            entity.HasIndex(item => new { item.CreatedAt, item.Id }).IsDescending(true, false)
                .HasFilter("publication_state = 'published' AND lifecycle = 'active'");
            entity.HasIndex(item => new { item.PostedBy, item.CreatedAt }).IsDescending(false, true);
            entity.HasIndex(item => item.FoundOn).HasFilter("found_on IS NOT NULL");
            entity.HasIndex(item => new { item.FoundFrom, item.FoundUntil }).HasFilter("found_from IS NOT NULL");
        });

        modelBuilder.Entity<StoredObject>(entity =>
        {
            entity.ToTable("stored_objects", table =>
            {
                table.HasCheckConstraint("objects_key_check", "btrim(bucket) <> '' AND btrim(object_key) <> ''");
                table.HasCheckConstraint("objects_kind_check", "object_kind = 'processed'");
                table.HasCheckConstraint("objects_state_check", "object_state IN ('reserved', 'validated', 'delete_pending', 'deleted')");
                table.HasCheckConstraint("objects_hash_check", "sha256 ~ '^[0-9a-f]{64}$'");
                table.HasCheckConstraint("objects_type_check", "content_type IN ('image/jpeg', 'image/png', 'image/webp')");
                table.HasCheckConstraint("objects_dimensions_check", "byte_size > 0 AND width > 0 AND height > 0");
                table.HasCheckConstraint("objects_attempts_check", "cleanup_attempts >= 0");
                table.HasCheckConstraint("objects_validated_check", "object_state <> 'validated' OR (sha256 IS NOT NULL AND content_type IS NOT NULL AND byte_size IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL AND validated_at IS NOT NULL)");
                table.HasCheckConstraint("objects_deleted_check", "(object_state = 'deleted') = (deleted_at IS NOT NULL)");
                table.HasCheckConstraint("objects_reserved_check", "object_state <> 'reserved' OR expires_at IS NOT NULL");
            });
            entity.Property(value => value.ObjectKind).HasDefaultValue("processed");
            entity.Property(value => value.ObjectState).HasDefaultValue("reserved");
            entity.Property(value => value.CleanupAttempts).HasDefaultValue(0);
            entity.HasOne(value => value.Owner).WithMany().HasForeignKey(value => value.OwnerUserId);
            entity.HasIndex(value => new { value.Bucket, value.ObjectKey }).IsUnique();
            entity.HasIndex(value => new { value.CleanupNextAt, value.ExpiresAt }).HasFilter("object_state <> 'deleted'");
        });

        modelBuilder.Entity<ItemImage>(entity =>
        {
            entity.ToTable("item_images", table =>
            {
                table.HasCheckConstraint("images_position_check", "position > 0 AND content_version > 0");
                table.HasCheckConstraint("images_processing_check", "processing_state IN ('pending', 'processing', 'needs_review', 'ready', 'failed', 'rejected')");
                table.HasCheckConstraint("images_review_check", "review_state IN ('pending', 'approved', 'rejected')");
                table.HasCheckConstraint("images_regions_check", "jsonb_typeof(sensitive_regions) = 'array'");
                table.HasCheckConstraint("images_reviewer_check", "(review_state = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR (review_state IN ('approved', 'rejected') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)");
                table.HasCheckConstraint("images_output_check", "processing_state NOT IN ('needs_review', 'ready') OR (processed_object_id IS NOT NULL AND redaction_model_id IS NOT NULL AND redaction_model_revision IS NOT NULL AND redaction_profile IS NOT NULL)");
                table.HasCheckConstraint("images_ready_check", "processing_state <> 'ready' OR review_state = 'approved'");
                table.HasCheckConstraint("images_rejected_check", "processing_state <> 'rejected' OR review_state = 'rejected'");
            });
            entity.HasAlternateKey(image => new { image.Id, image.ItemId });
            entity.Property(image => image.ContentVersion).HasDefaultValue(1L);
            entity.Property(image => image.ProcessingState).HasDefaultValue("pending");
            entity.Property(image => image.ReviewState).HasDefaultValue("pending");
            entity.Property(image => image.SensitiveRegions).HasColumnType("jsonb");
            entity.Property(image => image.OriginalEmbedding).HasColumnType("jsonb");
            entity.HasOne(image => image.Item).WithMany(item => item.Images).HasForeignKey(image => image.ItemId);
            entity.HasOne(image => image.ProcessedObject).WithMany().HasForeignKey(image => image.ProcessedObjectId);
            entity.HasOne(image => image.Reviewer).WithMany().HasForeignKey(image => image.ReviewedBy);
            entity.HasIndex(image => image.ProcessedObjectId).IsUnique();
            entity.HasIndex(image => new { image.ItemId, image.Position }).IsUnique().HasFilter("retired_at IS NULL");
        });

        modelBuilder.Entity<VerificationQuestion>(entity =>
        {
            entity.ToTable("verification_questions", table =>
            {
                table.HasCheckConstraint("questions_slot_check", "slot BETWEEN 1 AND 3");
                table.HasCheckConstraint("questions_text_check", "char_length(btrim(question_text)) BETWEEN 1 AND 500");
            });
            entity.HasKey(question => new { question.ItemId, question.Slot });
            entity.Property(question => question.QuestionText).HasMaxLength(500);
            entity.HasOne(question => question.Item).WithMany(item => item.VerificationQuestions).HasForeignKey(question => question.ItemId);
        });

        modelBuilder.Entity<Claim>(entity =>
        {
            entity.ToTable("claims", table =>
            {
                table.HasCheckConstraint("claims_version_check", "source_custody_version > 0");
                table.HasCheckConstraint("claims_status_check", "status IN ('pending', 'approved', 'rejected')");
                table.HasCheckConstraint("claims_participants_check", "claimant_user_id <> reviewer_user_id");
                table.HasCheckConstraint("claims_decision_check", "(status = 'pending' AND decided_by IS NULL AND decided_at IS NULL) OR (status <> 'pending' AND decided_by IS NOT NULL AND decided_by = reviewer_user_id AND decided_at IS NOT NULL)");
            });
            entity.HasAlternateKey(claim => new { claim.Id, claim.ItemId });
            // EF keys are immutable: change Status with ExecuteUpdate, detach, then query the claim again.
            entity.HasAlternateKey(claim => new { claim.Id, claim.Status });
            entity.Property(claim => claim.Status).HasDefaultValue("pending");
            entity.Property(claim => claim.DecisionNote).HasMaxLength(2000);
            entity.HasOne(claim => claim.Item).WithMany(item => item.Claims).HasForeignKey(claim => claim.ItemId);
            entity.HasOne(claim => claim.Claimant).WithMany().HasForeignKey(claim => claim.ClaimantUserId);
            entity.HasOne(claim => claim.Reviewer).WithMany().HasForeignKey(claim => claim.ReviewerUserId);
            entity.HasOne(claim => claim.Decider).WithMany().HasForeignKey(claim => claim.DecidedBy);
            entity.HasIndex(claim => new { claim.ItemId, claim.Status, claim.CreatedAt });
            entity.HasIndex(claim => new { claim.ClaimantUserId, claim.CreatedAt }).IsDescending(false, true);
            entity.HasIndex(claim => new { claim.ReviewerUserId, claim.Status, claim.CreatedAt });
        });

        modelBuilder.Entity<ClaimAnswer>(entity =>
        {
            entity.ToTable("claim_answers", table =>
            {
                table.HasCheckConstraint("answers_slot_check", "slot BETWEEN 1 AND 3");
                table.HasCheckConstraint("answers_question_check", "char_length(btrim(question_text_snapshot)) BETWEEN 1 AND 500");
                table.HasCheckConstraint("answers_text_check", "char_length(btrim(answer_text)) BETWEEN 1 AND 2000");
            });
            entity.HasKey(answer => new { answer.ClaimId, answer.Slot });
            entity.Property(answer => answer.QuestionTextSnapshot).HasMaxLength(500);
            entity.Property(answer => answer.AnswerText).HasMaxLength(2000);
            entity.HasOne(answer => answer.Claim).WithMany(claim => claim.Answers).HasForeignKey(answer => answer.ClaimId);
        });

        modelBuilder.Entity<Conversation>(entity =>
        {
            entity.ToTable("conversations", table => table.HasCheckConstraint("conversations_approval_check", "approval_status = 'approved'"));
            entity.HasKey(conversation => conversation.ClaimId);
            entity.Property(conversation => conversation.ApprovalStatus).HasDefaultValue("approved");
            entity.HasOne(conversation => conversation.Claim).WithOne(claim => claim.Conversation)
                .HasForeignKey<Conversation>(conversation => new { conversation.ClaimId, conversation.ApprovalStatus })
                .HasPrincipalKey<Claim>(claim => new { claim.Id, claim.Status });
        });

        modelBuilder.Entity<Message>(entity =>
        {
            entity.ToTable("messages", table => table.HasCheckConstraint("messages_body_check", "char_length(btrim(body)) BETWEEN 1 AND 4000"));
            entity.Property(message => message.Body).HasMaxLength(4000);
            entity.Property(message => message.MessageSequence).UseIdentityAlwaysColumn();
            entity.HasOne(message => message.Conversation).WithMany(conversation => conversation.Messages).HasForeignKey(message => message.ConversationId);
            entity.HasOne(message => message.Sender).WithMany().HasForeignKey(message => message.SenderUserId);
            entity.HasIndex(message => message.MessageSequence).IsUnique();
            entity.HasIndex(message => new { message.ConversationId, message.SenderUserId, message.ClientMessageId }).IsUnique();
            entity.HasIndex(message => new { message.ConversationId, message.MessageSequence });
        });

        modelBuilder.Entity<IntakeRequest>(entity =>
        {
            entity.ToTable("intake_requests", table =>
            {
                table.HasCheckConstraint("intake_version_check", "source_custody_version > 0");
                table.HasCheckConstraint("intake_status_check", "status IN ('pending', 'received', 'rejected')");
                table.HasCheckConstraint("intake_decision_check", "(status = 'pending' AND decided_by IS NULL AND decided_at IS NULL) OR (status <> 'pending' AND decided_by IS NOT NULL AND decided_at IS NOT NULL)");
            });
            entity.HasAlternateKey(request => new { request.Id, request.ItemId });
            entity.Property(request => request.Status).HasDefaultValue("pending");
            entity.Property(request => request.DecisionNote).HasMaxLength(2000);
            entity.HasOne(request => request.Item).WithMany(item => item.IntakeRequests).HasForeignKey(request => request.ItemId);
            entity.HasOne(request => request.Requester).WithMany().HasForeignKey(request => request.RequestedBy);
            entity.HasOne(request => request.TargetPoint).WithMany().HasForeignKey(request => request.TargetPointId);
            entity.HasOne(request => request.Decider).WithMany().HasForeignKey(request => request.DecidedBy);
            entity.HasIndex(request => new { request.TargetPointId, request.Status, request.CreatedAt });
            entity.HasIndex(request => new { request.ItemId, request.Status });
            entity.HasIndex(request => new { request.RequestedBy, request.CreatedAt }).IsDescending(false, true);
        });

        modelBuilder.Entity<CustodyEvent>(entity =>
        {
            entity.ToTable("custody_events", table =>
            {
                table.HasCheckConstraint("custody_version_check", "custody_version > 0");
                table.HasCheckConstraint("custody_from_check", "jsonb_typeof(from_custody) = 'object'");
                table.HasCheckConstraint("custody_to_check", "jsonb_typeof(to_custody) = 'object'");
                table.HasCheckConstraint("custody_event_check", """
                    (event_kind = 'registered' AND from_custody IS NULL AND to_custody IS NOT NULL AND intake_request_id IS NULL AND claim_id IS NULL AND recipient_user_id IS NULL) OR
                    (event_kind = 'received' AND from_custody IS NOT NULL AND to_custody IS NOT NULL AND intake_request_id IS NOT NULL AND claim_id IS NULL AND recipient_user_id IS NULL) OR
                    (event_kind = 'returned' AND from_custody IS NOT NULL AND to_custody IS NULL AND intake_request_id IS NULL)
                    """);
            });
            entity.Property(value => value.FromCustody).HasColumnType("jsonb");
            entity.Property(value => value.ToCustody).HasColumnType("jsonb");
            entity.Property(value => value.VerificationNote).HasMaxLength(2000);
            entity.HasOne(value => value.Item).WithMany(item => item.CustodyEvents).HasForeignKey(value => value.ItemId);
            entity.HasOne(value => value.Actor).WithMany().HasForeignKey(value => value.ActorUserId);
            entity.HasOne(value => value.Recipient).WithMany().HasForeignKey(value => value.RecipientUserId);
            entity.HasOne(value => value.IntakeRequest).WithMany().HasForeignKey(value => new { value.IntakeRequestId, value.ItemId })
                .HasPrincipalKey(request => new { request.Id, request.ItemId });
            entity.HasOne(value => value.Claim).WithMany().HasForeignKey(value => new { value.ClaimId, value.ItemId })
                .HasPrincipalKey(claim => new { claim.Id, claim.ItemId });
            entity.HasIndex(value => new { value.ItemId, value.CustodyVersion }).IsUnique();
            entity.HasIndex(value => value.IntakeRequestId).IsUnique();
            entity.HasIndex(value => value.ItemId, "custody_one_registration").IsUnique().HasFilter("event_kind = 'registered'");
            entity.HasIndex(value => value.ItemId, "custody_one_return").IsUnique().HasFilter("event_kind = 'returned'");
            entity.HasIndex(value => new { value.ItemId, value.OccurredAt, value.Id });
        });

        modelBuilder.Entity<AiJob>(entity =>
        {
            entity.ToTable("ai_jobs", table =>
            {
                table.HasCheckConstraint("jobs_source_check", "source_version > 0 AND source_sha256 ~ '^[0-9a-f]{64}$'");
                table.HasCheckConstraint("jobs_model_check", "btrim(model_id) <> '' AND btrim(model_revision) <> '' AND btrim(processing_profile) <> ''");
                table.HasCheckConstraint("jobs_kind_check", "(job_kind = 'embed_text' AND image_id IS NULL) OR (job_kind = 'embed_image' AND image_id IS NOT NULL)");
                table.HasCheckConstraint("jobs_status_check", "status IN ('pending', 'running', 'retry', 'succeeded', 'failed', 'obsolete')");
                table.HasCheckConstraint("jobs_attempts_check", "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts");
                table.HasCheckConstraint("jobs_lease_check", "(status = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR (status <> 'running' AND lease_token IS NULL AND lease_until IS NULL)");
                table.HasCheckConstraint("jobs_finished_check", "(status IN ('succeeded', 'failed', 'obsolete')) = (finished_at IS NOT NULL)");
            });
            entity.Property(job => job.Status).HasDefaultValue("pending");
            entity.Property(job => job.Attempts).HasDefaultValue(0);
            entity.Property(job => job.NextAttemptAt).HasDefaultValueSql("now()");
            entity.HasOne(job => job.Item).WithMany().HasForeignKey(job => job.ItemId);
            entity.HasOne(job => job.Image).WithMany().HasForeignKey(job => new { job.ImageId, job.ItemId })
                .HasPrincipalKey(image => new { image.Id, image.ItemId });
            entity.HasIndex(job => new { job.ItemId, job.SourceVersion, job.JobKind, job.ModelId, job.ModelRevision, job.ProcessingProfile })
                .IsUnique().HasFilter("image_id IS NULL");
            entity.HasIndex(job => new { job.ImageId, job.SourceVersion, job.JobKind, job.ModelId, job.ModelRevision, job.ProcessingProfile })
                .IsUnique().HasFilter("image_id IS NOT NULL");
            entity.HasIndex(job => new { job.NextAttemptAt, job.Id }).HasFilter("status IN ('pending', 'retry')");
            entity.HasIndex(job => job.LeaseUntil).HasFilter("status = 'running'");
        });

        modelBuilder.Entity<IdempotencyKey>(entity =>
        {
            entity.ToTable("idempotency_keys", table =>
            {
                table.HasCheckConstraint("idempotency_operation_check", "btrim(operation) <> ''");
                table.HasCheckConstraint("idempotency_hash_check", "request_sha256 ~ '^[0-9a-f]{64}$'");
                table.HasCheckConstraint("idempotency_resource_check", "resource_type IN ('item', 'image', 'claim', 'intake', 'custody_event')");
                table.HasCheckConstraint("idempotency_response_check", "response_status BETWEEN 200 AND 299");
            });
            entity.HasKey(value => new { value.ActorUserId, value.IdempotencyKeyValue });
            entity.Property(value => value.IdempotencyKeyValue).HasColumnName("idempotency_key");
            entity.HasOne(value => value.Actor).WithMany().HasForeignKey(value => value.ActorUserId);
        });

        modelBuilder.Entity<IndexOutbox>(entity =>
        {
            entity.ToTable("index_outbox", table =>
            {
                table.HasCheckConstraint("outbox_version_check", "document_version > 0");
                table.HasCheckConstraint("outbox_kind_check", "event_kind IN ('snapshot', 'tombstone')");
                table.HasCheckConstraint("outbox_payload_check", "jsonb_typeof(payload) = 'object'");
                table.HasCheckConstraint("outbox_hash_check", "payload_sha256 ~ '^[0-9a-f]{64}$'");
                table.HasCheckConstraint("outbox_status_check", "status IN ('pending', 'running', 'retry', 'succeeded', 'failed', 'obsolete')");
                table.HasCheckConstraint("outbox_attempts_check", "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts");
                table.HasCheckConstraint("outbox_lease_check", "(status = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR (status <> 'running' AND lease_token IS NULL AND lease_until IS NULL)");
                table.HasCheckConstraint("outbox_finished_check", "(status IN ('succeeded', 'failed', 'obsolete')) = (finished_at IS NOT NULL)");
            });
            entity.Property(value => value.Payload).HasColumnType("jsonb");
            entity.Property(value => value.Status).HasDefaultValue("pending");
            entity.Property(value => value.Attempts).HasDefaultValue(0);
            entity.Property(value => value.NextAttemptAt).HasDefaultValueSql("now()");
            entity.HasIndex(value => new { value.ItemId, value.DocumentVersion }).IsUnique();
            entity.HasIndex(value => new { value.NextAttemptAt, value.Id }).HasFilter("status IN ('pending', 'retry')");
            entity.HasIndex(value => value.LeaseUntil).HasFilter("status = 'running'");
        });

        foreach (var entity in modelBuilder.Model.GetEntityTypes())
        {
            foreach (var property in entity.GetProperties())
            {
                if (property.Name != nameof(IdempotencyKey.IdempotencyKeyValue))
                    property.SetColumnName(JsonNamingPolicy.SnakeCaseLower.ConvertName(property.Name));
                if (property.Name is "CreatedAt" or "UpdatedAt" or "RecordedAt" or "AssignedAt")
                    property.SetDefaultValueSql("now()");
            }
            foreach (var foreignKey in entity.GetForeignKeys())
                foreignKey.DeleteBehavior = DeleteBehavior.Restrict;
        }
    }
}
