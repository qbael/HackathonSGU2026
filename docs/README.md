# Tài liệu Findie

Tài liệu sản phẩm, thiết kế, hướng dẫn phát triển và tư liệu demo được tập trung trong thư mục này.

```text
product/        Đặc tả sản phẩm: Markdown, Word và PDF
architecture/   Kiến trúc hệ thống
database/       Thiết kế dữ liệu, từ điển cột, SQL và ERD
api/            Tổng quan API, endpoint, AMQP và kiểm thử
guides/         Hướng dẫn phát triển, AI service và Colab
specs/          Đặc tả và hồ sơ triển khai bootstrap, API, local full stack
assets/         Hình minh họa dùng trong tài liệu
demo/           Ảnh, video và tóm tắt demo
```

## Sản phẩm và thiết kế

- Đặc tả ứng dụng: [Markdown](product/DAC_TA_FINDIE.md), [Word](product/DAC_TA_FINDIE.docx), [PDF](product/DAC_TA_FINDIE.pdf).
- [Kiến trúc hệ thống](architecture/system-architecture.md): .NET xử lý nghiệp vụ, quyền và R2; RabbitMQ chuyển lệnh/kết quả; Python xử lý ảnh, embedding và hybrid search. Redis cache embedding và ứng viên từ khóa/vị trí. Ảnh gốc chỉ xử lý tạm; R2 giữ đầu ra đã xử lý và được duyệt trước khi công khai.
- [Thiết kế cơ sở dữ liệu đích](database/database-design.md): phân quyền hai database logic cho .NET và Python. Runtime .NET có EF Core/Identity, outbox và migration có bảo vệ dữ liệu bootstrap cũ; xem [API](api/README.md).
- Snapshot bootstrap: [từ điển cột](database/database-column-dictionary.md), [DDL](database/database-schema.sql), [SQL kiểm tra](database/database-check.sql), [ERD draw.io](database/findie-erd.drawio), [ảnh ERD](assets/findie-erd-overview.png). Các tệp này vẫn mô tả 16 bảng/164 cột và liên kết ảnh gốc/bản xử lý cũ; chưa phải schema hybrid search hai database hoặc chính sách chỉ lưu ảnh đầu ra. Giữ nguyên để đối chiếu migration, không dùng luồng lưu ảnh gốc cũ làm kiến trúc đích.
- [Hiến chương dự án](../.specify/memory/constitution.md) được giữ tại vị trí cấu hình của Spec Kit.

## Phát triển và kiểm thử

- [Cài đặt và chạy local](guides/development.md), gồm cấu hình OAuth Google; ứng dụng hiện chỉ hỗ trợ đăng nhập Google.
- [API .NET](api/README.md): Google cookie/CSRF, hồ sơ/điểm, món đồ, claim/chat, tiếp nhận/trao trả, ảnh/search; tài liệu từng endpoint, AMQP và kiểm thử.
- [Python AI service với Ollama](guides/ai-service.md): tìm bằng mô tả tiếng Việt, vị trí phòng/hội trường, đổi model và cấu hình chỉ mục.
- [Thử AI trên Google Colab](guides/colab.md).
- Hồ sơ khởi tạo: [phạm vi](specs/001-project-bootstrap/spec.md), [kế hoạch](specs/001-project-bootstrap/plan.md), [nhiệm vụ](specs/001-project-bootstrap/tasks.md).
- [Kiểm thử E2E](guides/e2e-testing-guide.md): cấu hình và cách chạy Playwright hiện hành.

## Tư liệu demo

- [Tóm tắt Findie](demo/findie-dang-bai/TOM_TAT_FINDIE.txt) và [video demo](demo/findie-dang-bai/findie-demo.mp4).
- Các luồng: [đăng đồ nhặt được](demo/findie-dang-bai/01-dang-do-nhat-duoc.png), [tìm đồ](demo/findie-dang-bai/02-tim-do-that-lac.png), [yêu cầu và hẹn trả](demo/findie-dang-bai/03-yeu-cau-va-hen-trao-tra.png), [nhận tại điểm tiếp nhận](demo/findie-dang-bai/04-nhan-tai-diem-tiep-nhan.png).

## Sơ đồ

Nguồn sơ đồ được giữ trong `docs/database/findie-erd.drawio` và `docs/assets/kien-truc-he-thong.svg`; các ảnh minh họa hiện có nằm trong `docs/assets/`.
