# Khởi tạo Findie

Yêu cầu ngày 2026-10-22: tạo cấu trúc và cấu hình ban đầu theo đặc tả hiện có,
database chạy Docker, thử hai mô hình AI trên Google Colab Free.

- Có frontend React/TypeScript, API .NET, FastAPI nội bộ và hướng dẫn chạy local.
- Docker Compose dùng PostgreSQL/pgvector, nạp `docs/database/database-schema.sql` vào volume mới.
- Tái sử dụng `docs/database/database-check.sql` để kiểm tra ràng buộc, không nhân đôi schema.
- Notebook standalone cho Qwen3-VL-Embedding-2B và Qwen3-VL-4B-Instruct/OpenCV;
  chạy từng model trên GPU Colab, lưu siêu dữ liệu và kiểm tra output.
- Có cấu hình mẫu, secret local riêng, lockfile và tự kiểm tra có thể chạy lại.

Phạm vi là nền tảng phát triển. Đăng nhập, bài đăng, tìm kiếm nghiệp vụ, chat, worker,
upload R2 và phục vụ suy luận thật chưa được triển khai; giao diện/trạng thái phải nói đúng.
Không thay đổi các chính sách nghiệp vụ còn mở trong hiến chương.
