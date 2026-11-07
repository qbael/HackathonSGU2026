# Findie API

ASP.NET Core .NET 10, Entity Framework Core/Npgsql và ASP.NET Core Identity.
Đã có model nghiệp vụ, migration khởi tạo, xác thực và các API theo kiến trúc
`Controller → Service → Repository → FindieDbContext → PostgreSQL`.
Đã triển khai đăng/sửa/ẩn tin, bộ lọc, claim/duyệt nhiều yêu cầu, chat HTTP, tiếp nhận,
trao trả, adapter ảnh/tìm kiếm AMQP, R2 output, outbox và cleanup. Worker Python/search database hỗ trợ text, xử lý ảnh và tìm ảnh native qua Ollama; xem [AI service](../guides/ai-service.md). API AI báo 503 khi phụ thuộc chưa sẵn sàng, không dùng kết quả giả.

- [Từng API nghiệp vụ: request/response, quyền, lỗi và ví dụ](recovery.md).
- [Từng API ảnh và tìm kiếm](media-search.md).
- [Hợp đồng AMQP, outbox, lease và cleanup](amqp.md).
- [Phạm vi kiểm thử và cách chạy](testing.md).

## Cấu trúc và khởi chạy

```text
apps/api/
  Models/          ApplicationUser : IdentityUser<Guid> và 15 model nghiệp vụ
  Data/            FindieDbContext : IdentityDbContext; cấu hình quan hệ/ràng buộc
    Migrations/    Migration khởi tạo và snapshot EF Core
  Contracts/       Request/response DTO, không trả entity Identity trực tiếp
  Repositories/    Truy cập EF Core; interface và implementation riêng
  Services/        Kiểm tra đầu vào và tạo DTO
  Controllers/     API hồ sơ, điểm, món đồ, claim, chat, intake, ảnh và search
  Infrastructure/ Healthcheck, AMQP request/reply, R2, outbox/receipt và cleanup output
  Security/        Google OAuth và chặn truy cập của tài khoản DisabledAt
  tests/           Smoke và kiểm thử tích hợp PostgreSQL dùng một lần
    integration/   Bộ kiểm thử .NET: xác thực, nghiệp vụ, ảnh và broker
```

Từ thư mục gốc, theo [hướng dẫn phát triển](../guides/development.md):

```sh
make setup
make db-up
make db-migrate
make api
```

`make db-migrate` dùng `scripts/db/migrate.py` để áp dụng EF migrations. Database bootstrap
cũ chỉ được chuyển đổi tự động khi toàn bộ 16 bảng đều rỗng; script từ chối nếu có dữ liệu.
Với dữ liệu cũ thực tế, cần migration chuyển đổi riêng; không xóa volume để chữa lỗi.
API không tự `Migrate`, `EnsureCreated`, tạo bảng hoặc xóa dữ liệu khi khởi động.
EF migrations là nguồn lược đồ runtime .NET; schema tìm kiếm văn bản Python nằm tại `services/ai/findie_ai/schema.sql`.

Solution `Findie.sln` gồm API và chương trình kiểm thử tích hợp. Mỗi entity nằm trong một
tệp riêng ở `Models/`; dùng `IdentityDbContext<ApplicationUser, IdentityRole<Guid>, Guid>`
và Fluent API để ánh xạ tên cột snake_case, khóa chính/ngoại, index và check constraint.
Identity được cấu hình theo [tài liệu Microsoft](https://learn.microsoft.com/en-us/aspnet/core/security/authentication/customize-identity-model?view=aspnetcore-10.0).
Repository xử lý truy cập dữ liệu; service kiểm tra đầu vào/tạo DTO; controller xử lý HTTP.
Các repository/service có interface và được đăng ký scoped trong `Program.cs`.
Các tác vụ nền dùng scope riêng và giao dịch ngắn; không giữ transaction khi gọi AMQP/R2.

`ConnectionStrings__Database` và `Ai__ServiceToken` bắt buộc có giá trị.
`Ai__BaseUrl` mặc định `http://127.0.0.1:8000`; timeout mặc định 5 giây.
`RabbitMq__Uri`, `Storage__*`, `Ai__RedactionRevision` và `Ai__EmbeddingRevision` kích hoạt
phần AI/ảnh; xem [cấu hình và điều kiện](media-search.md#cấu-hình-cần-thiết).

## Xác thực và hồ sơ

**Tạm thời chỉ cho đăng nhập bằng Google.** ASP.NET Core Google OAuth xử lý chuyển hướng,
state/correlation và trao đổi mã ở máy chủ; Identity lưu tài khoản và external login.
`ApplicationUser` dùng khóa `Guid`, có tên hiển thị, ngày tạo và `DisabledAt`.
Role được hỗ trợ bởi Identity; cấp quyền nhân viên tại điểm chưa có API.

| Endpoint | Nội dung |
| --- | --- |
| `GET /api/auth/google?returnUrl=/` | Bắt đầu đăng nhập Google; chỉ nhận đường dẫn quay về nội bộ. Trả 503 nếu chưa cấu hình OAuth. |
| `GET /api/auth/google/signin` | Callback OAuth do middleware Google xử lý; đăng ký URI này tại Google Cloud. |
| `GET /api/auth/google/callback` | Hoàn tất liên kết tài khoản, cấp cookie rồi quay về ứng dụng. |
| `GET /api/users/me` | Hồ sơ chính chủ: `id`, `email`, `displayName`, `createdAt`. |
| `PUT /api/users/me` | `{ "displayName": "…" }`; bỏ khoảng trắng hai đầu, từ chối rỗng hoặc quá 120 ký tự. |
| `GET /api/reception-points` | Tối đa 100 điểm đang hoạt động, sắp theo tên và ID. |
| `GET /api/reception-points/{id}` | Chỉ trả điểm đang hoạt động; 404 nếu không có hoặc đã ngừng hoạt động. |
| `GET /api/auth/csrf` | Người dùng đã đăng nhập lấy `{ "token": "…" }` và cookie chống giả mạo. |
| `POST /api/auth/logout` | Gửi `X-CSRF-TOKEN`; kết thúc cookie, trả 204. |

Các API hồ sơ/điểm tiếp nhận dùng cookie phiên của ứng dụng, không nhận bearer token.
Mỗi lượt truy cập được bảo vệ đều kiểm tra tài khoản vẫn tồn tại và chưa bị vô hiệu hóa.
Không có API liệt kê người dùng, tự cấp role hoặc cấp quyền tại điểm.

Cookie `HttpOnly`, `SameSite=Lax`; ngoài Development luôn yêu cầu `Secure`/HTTPS.
HTTP loopback chỉ được phép trong Development. Mọi request thay đổi dữ liệu đã đăng nhập
cần token từ `/api/auth/csrf` trong header `X-CSRF-TOKEN`. React có nút Google, tên/email
hồ sơ và đăng xuất; giữ phiên bằng cookie, không lưu token trong localStorage.
`GET /api/users/me` trả 401 khi chưa đăng nhập là trạng thái bình thường.

Không ánh xạ đăng ký, email/password, refresh, quên mật khẩu, email confirmation hoặc 2FA.
Trước triển khai cần HTTPS và lưu Data Protection keys bền vững; khi chạy nhiều instance
cần dùng chung key ring. Cấu hình Google và URI local nằm trong [hướng dẫn phát triển](../guides/development.md#đăng-nhập-google).

## Model và database

Các model gồm tài khoản, điểm tiếp nhận, nhân viên điểm, món đồ, metadata object,
ảnh đã xử lý, câu hỏi xác minh, claim/câu trả lời, hội thoại/tin nhắn, yêu cầu tiếp nhận,
lịch sử nơi giữ, job AI, khóa idempotency và outbox chỉ mục. Schema runtime có 22 bảng
(7 bảng Identity, bao gồm `app_users`, và 15 bảng nghiệp vụ), ngoài bảng lịch sử migration.

| Nhóm | Class trong `Models/` |
| --- | --- |
| Người dùng và điểm tiếp nhận | `ApplicationUser`, `ReceptionPoint`, `PointStaff` |
| Món đồ và ảnh | `Item`, `ItemImage`, `StoredObject`, `VerificationQuestion` |
| Yêu cầu nhận và hội thoại | `Claim`, `ClaimAnswer`, `Conversation`, `Message` |
| Tiếp nhận và trao trả | `IntakeRequest`, `CustodyEvent` |
| Điều phối và gửi lại | `AiJob`, `IdempotencyKey`, `IndexOutbox` |

EF giữ khóa ngoại hạn chế xóa, câu hỏi tối đa ba slot, một nơi giữ, các phiên bản dương,
hội thoại chỉ gắn claim đã duyệt, khóa gửi lại tin nhắn và tối đa một lần trao trả.
`Item.RowVersion` là concurrency token; service tăng phiên bản trong mỗi thay đổi món.
`Claim.Status` tham gia alternate key để bảo đảm hội thoại thuộc claim approved; luồng
quyết định dùng `ExecuteUpdate` và truy vấn không tracking;
không gán `Status` hoặc dùng `Entry.Reload` trên entity đang được theo dõi.
Các service kiểm quyền hiện tại và dùng transaction/khóa row cho các chuyển trạng thái.

Ảnh chỉ có `ProcessedObjectId`; object kind chỉ là `processed`.
Không có tham chiếu ảnh gốc, raw bytes hoặc `ItemEmbedding` trong EF .NET.
`AiJob` là metadata cho embed text/image. `IndexOutbox` giữ snapshot/tombstone, phiên bản,
checksum, trạng thái retry và lease; `RecoveryMaintenance` dispatch và `IndexReceiptService`
kiểm receipt/commit trước ACK, kể cả receipt sau restart. Cần cấu hình broker/worker Python.
`Item.DocumentVersion` là phiên bản tài liệu. Database `findie_search` dự kiến có
`search_documents` (projection/watermark/tombstone), `search_sources` (embedding) và lịch sử
schema riêng; schema/worker Python cho văn bản đã có, hợp đồng .NET tại [AMQP](amqp.md).
Xem [kiến trúc đích](../architecture/system-architecture.md).

## Trạng thái và kiểm thử

| Endpoint | Ý nghĩa |
| --- | --- |
| `GET /health/live` | Tiến trình đang chạy, không kiểm phụ thuộc. |
| `GET /health/ready` | `SELECT 1` thành công; không xác nhận đã chạy migration. |
| `GET /api/system/status` | Trạng thái DB/FastAPI; `authentication` theo cấu hình Google, `business:true`, `storage` theo cấu hình R2 hợp lệ. |

`stage` giữ `scaffold` để tương thích client và thể hiện tích hợp sản phẩm chưa hoàn thiện.
Feature flag biểu diễn khả năng đã cấu hình/triển khai, không bảo đảm dịch vụ ngoài đang sẵn sàng.
HTTP tới FastAPI chỉ là health probe; lệnh/kết quả suy luận đích dùng RabbitMQ.
Readiness không buộc AI sẵn sàng. API local nghe `http://127.0.0.1:5080`, Vite proxy `/api`.

```sh
dotnet build apps/api --no-restore
python3 apps/api/tests/smoke.py
make api-integration
```

Smoke không cần DB. Integration cần Docker và image PostgreSQL/RabbitMQ ghim theo script;
tự tạo container/database tạm, chạy migration, kiểm tra Google callback bằng provider giả lập,
cookie/CSRF, API nghiệp vụ/ảnh/search, cạnh tranh cập nhật, ràng buộc SQL và broker thật rồi dọn container.
Kiểm thử còn xác nhận bootstrap có dữ liệu được giữ nguyên, bootstrap rỗng được chuyển đổi
và migration chạy lại an toàn. Các bộ tích hợp không ghi database đang dùng của bạn; chưa chứng thực
đăng nhập qua Google thật khi thiếu OAuth credentials.
