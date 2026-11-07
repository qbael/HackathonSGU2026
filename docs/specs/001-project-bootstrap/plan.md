# Kế hoạch khởi tạo

**Ghi chú ngày 23/10/2026, kiến trúc đích v1.4.0:** đây là hồ sơ bộ khung đã khởi tạo.
[Kiến trúc đích](../../architecture/system-architecture.md) giao Python toàn bộ AI/ảnh, lưu embedding và
hybrid search; .NET giữ nghiệp vụ, R2, job/outbox, kiểm quyền/điều kiện hiện tại và DTO cuối.
RabbitMQ/AMQP lâu dài truyền lệnh/kết quả, lập/xóa chỉ mục và truy vấn/ứng viên. PostgreSQL
dùng chung một instance với hai database logic: `findie` chỉ .NET truy cập, `findie_search`
chứa pgvector/FTS và bản chiếu công khai chỉ Python truy cập. Python không được cấp quyền
DB nghiệp vụ/R2. Hybrid search dùng FTS PostgreSQL + cosine chính xác + weighted RRF theo
profile từng trường hợp; ảnh không kèm văn bản chỉ dùng vector/bộ lọc, chất lượng cần đo.
Ảnh gốc chỉ tạm trong RAM .NET/Python, không lưu R2 hoặc bytes gốc trong outbox bền vững.
Python có PII thì che/mờ, không PII thì chuẩn hóa/mã hóa lại ảnh sạch; .NET chỉ lưu ảnh
đầu ra vào R2 riêng tư và quản lý duyệt trước công khai. Bỏ dữ liệu gốc sau xử lý/lỗi/
deadline; mất payload phải tải lại. Payload ảnh tạm qua broker có TTL/dọn riêng, tách
khỏi metadata/chỉ mục bền vững; không giả định toàn bộ RabbitMQ chỉ lưu trong RAM.
HTTP FastAPI bootstrap chỉ kiểm tra trạng thái. PostgreSQL 17/DDL hiện tại chưa đổi;
RabbitMQ, hybrid search và database tìm kiếm riêng là công việc triển khai tiếp theo.
DDL/ERD bootstrap còn liên kết original/sanitized cũ; cần migration cho luồng chỉ lưu
ảnh đầu ra, không dùng snapshot đó như chính sách lưu ảnh gốc của kiến trúc đích.

## Đối chiếu hiến chương trước thiết kế

- Bootstrap giữ React → .NET → PostgreSQL; FastAPI hiện không có quyền truy cập DB/R2.
  Khi triển khai kiến trúc đích, chỉ Python sở hữu `findie_search`, chỉ .NET sở hữu `findie`/R2.
- Chưa xây luồng bảo vệ khi nhà cung cấp danh tính và quy tắc nhận đồ chưa chốt.
- Database chỉ bind loopback, dữ liệu có volume; không thêm lệnh tự động xóa volume.
- Model chạy thử Colab riêng; không mở tunnel công khai hay coi Colab là host API.
- Vector 2048 chiều, cùng model/revision/profile; ảnh phải được người thử kiểm tra.

## Cấu trúc và lựa chọn

- `apps/web`: React/TypeScript/Vite, trang trạng thái và proxy API local.
- `apps/api`: .NET 10 LTS, Npgsql 10; probe DB, API trạng thái, cấu hình AI/R2.
- `services/ai`: Python 3.12/FastAPI, liveness và trạng thái nội bộ có shared token.
- `notebooks/colab`: hai notebook độc lập, khóa revision, giảm VRAM, export kết quả.
- Root: Compose PostgreSQL 17/pgvector 0.8.2; schema tham chiếu trực tiếp từ docs.

Không tạo bộ entity/EF migration song song với SQL ở giai đoạn này; khi có nghiệp vụ,
chốt cách quản lý migration và runtime DB role giới hạn quyền trước dùng dữ liệu thật.
R2 có cấu hình server, chưa kết nối tài khoản. Phạm vi bootstrap không thêm Redis/queue/vector DB;
RabbitMQ và database logic `findie_search` cùng instance PostgreSQL đã được chọn cho kiến
trúc đích v1.4.0 ngày 23/10/2026 và cần bổ sung ở bước triển khai sau; không thêm hãng hoặc
máy chủ database mới.

## Kiểm chứng và đối chiếu sau thiết kế

Build frontend/API; thử trạng thái khi dependency lỗi và xác thực nội bộ; chạy SQL check
trên DB Docker thực; kiểm tra notebook JSON/cell Python và validation không cần GPU.
Không tuyên bố đã benchmark hay chạy inference trên GPU Colab nếu chưa có phiên thực tế.
Thiết kế giữ nguyên ranh giới, không triển khai thay đổi quyền/custody/chat trong lần khởi tạo.
