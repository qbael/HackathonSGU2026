# Tài liệu Findie

Tài liệu sản phẩm, thiết kế, hướng dẫn phát triển và tư liệu demo được tập trung trong thư mục này.

```text
product/        Đặc tả sản phẩm: Markdown, Word và PDF
architecture/   Kiến trúc hệ thống
database/       Thiết kế dữ liệu, từ điển cột, SQL và ERD
api/            Tổng quan API, endpoint, AMQP và kiểm thử
security/       Kế hoạch an ninh, SAST/Semgrep, Gitleaks và quy trình audit
guides/         Hướng dẫn phát triển, AI service và Colab
design/         Thiết kế giao diện Stitch
specs/          Phạm vi, kế hoạch và nhiệm vụ theo tính năng
assets/         Hình minh họa dùng trong tài liệu
demo/           Ảnh, video và tóm tắt demo
```

## Sản phẩm và thiết kế

- [Kế hoạch Tối ưu hóa UI/UX & Tinh gọn Mã nguồn](KE_HOACH_TOI_UU_UI_UX.md): Đánh giá chi tiết trải nghiệm người dùng, loại bỏ dev/test artifacts, chuẩn hóa thông báo lỗi và lộ trình cải tiến giao diện Findie.
- Đặc tả ứng dụng: [Markdown](product/DAC_TA_FINDIE.md), [Word](product/DAC_TA_FINDIE.docx), [PDF](product/DAC_TA_FINDIE.pdf).
- [Kiến trúc hệ thống](architecture/system-architecture.md): .NET xử lý nghiệp vụ, quyền và R2; RabbitMQ chuyển lệnh/kết quả; Python xử lý ảnh, embedding và hybrid search. Redis cache embedding và ứng viên từ khóa/vị trí. Ảnh gốc chỉ xử lý tạm; R2 giữ đầu ra đã xử lý và được duyệt trước khi công khai.
- [Thiết kế cơ sở dữ liệu đích](database/database-design.md): phân quyền hai database logic cho .NET và Python. Runtime .NET có EF Core/Identity, outbox và migration có bảo vệ dữ liệu bootstrap cũ; xem [API](api/README.md).
- Snapshot bootstrap: [từ điển cột](database/database-column-dictionary.md), [DDL](database/database-schema.sql), [SQL kiểm tra](database/database-check.sql), [ERD draw.io](database/findie-erd.drawio), [ảnh ERD](assets/findie-erd-overview.png). Các tệp này vẫn mô tả 16 bảng/164 cột và liên kết ảnh gốc/bản xử lý cũ; chưa phải schema hybrid search hai database hoặc chính sách chỉ lưu ảnh đầu ra. Giữ nguyên để đối chiếu migration, không dùng luồng lưu ảnh gốc cũ làm kiến trúc đích.
- [Hiến chương dự án](../.specify/memory/constitution.md) được giữ tại vị trí cấu hình của Spec Kit.

## Phát triển và kiểm thử

- [Báo cáo Toàn diện về Hệ thống Kiểm thử (Testing Report)](TESTING_REPORT.md): Tổng hợp danh sách toàn bộ các test cases, ma trận bao phủ (Unit, Integration, E2E, Security) và hướng dẫn chi tiết cách chạy kiểm thử cho dự án.
- [Báo cáo Chức năng Bảo mật](security/SECURITY_REPORT.md): Tổng hợp toàn bộ cơ chế bảo vệ (Privacy, Auth, Network, SAST/SCA) và bảng lệnh thực thi kiểm tra an ninh.
- [Kế hoạch An ninh & Review Code](security/SECURITY_PLAN.md): Tích hợp Semgrep, Gitleaks, quy tắc bảo vệ PII, Zero Raw Image và quy trình kiểm duyệt code.
- [Cài đặt và chạy local](guides/development.md), gồm cấu hình OAuth Google; ứng dụng hiện chỉ hỗ trợ đăng nhập Google.
- [API .NET](api/README.md): Google cookie/CSRF, hồ sơ/điểm, món đồ, claim/chat, tiếp nhận/trao trả, ảnh/search; tài liệu từng endpoint, AMQP và kiểm thử.
- [Python AI service với Ollama](guides/ai-service.md): tìm bằng mô tả tiếng Việt, vị trí phòng/hội trường, đổi model và cấu hình chỉ mục.
- [Thử AI trên Google Colab](guides/colab.md).
- Hồ sơ khởi tạo: [phạm vi](specs/001-project-bootstrap/spec.md), [kế hoạch](specs/001-project-bootstrap/plan.md), [nhiệm vụ](specs/001-project-bootstrap/tasks.md).
- [Kiểm thử E2E](guides/e2e-testing-guide.md): cấu hình và cách chạy Playwright hiện hành.

## Tư liệu demo

- [Tóm tắt Findie](demo/findie-dang-bai/TOM_TAT_FINDIE.txt) và [video demo](demo/findie-dang-bai/findie-demo.mp4).
- Các luồng: [đăng đồ nhặt được](demo/findie-dang-bai/01-dang-do-nhat-duoc.png), [tìm đồ](demo/findie-dang-bai/02-tim-do-that-lac.png), [yêu cầu và hẹn trả](demo/findie-dang-bai/03-yeu-cau-va-hen-trao-tra.png), [nhận tại điểm tiếp nhận](demo/findie-dang-bai/04-nhan-tai-diem-tiep-nhan.png).

## Tạo lại sơ đồ

Nguồn sơ đồ được giữ trong `docs/database/findie-erd.drawio` và `docs/assets/kien-truc-he-thong.svg`; các ảnh minh họa hiện có nằm trong `docs/assets/`.

Chạy từ thư mục gốc dự án. Các script render dùng Playwright của runtime Codex và Google Chrome trên máy hiện tại.

```sh
python3 scripts/docs/erd/build_erd.py
node scripts/docs/erd/render_local.cjs
node scripts/docs/render_architecture.cjs
```

Script cập nhật ERD trong `docs/database/` và ảnh trong `docs/assets/`; đầu ra kiểm tra tạm nằm trong `.cache/docs/`.
