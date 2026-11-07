# Kế hoạch chạy đầy đủ tại local

## Constitution check trước nghiên cứu

Giữ React → .NET → RabbitMQ → Python; FastAPI health only. Python sở hữu findie_search, .NET sở hữu findie/R2. Raw chỉ RAM/transport tạm; chỉ output sạch duyệt được index. Không thêm public admin API, không bỏ kiểm quyền/CSRF/idempotency.

## Thiết kế

1. Sửa runner theo đường dẫn hiện tại; bổ sung bootstrap search DB/role/grant idempotent, Hub seed CLI Development và doctor.
2. Tái dùng Ollama adapter với gateway `/api/embed` input ảnh native `{image: base64}`. Theo yêu cầu 28/10/2026, full-stack notebook chọn `Qwen/Qwen3-VL-Embedding-2B` qua Transformers: 2048 chiều, FP16/SDPA, pooling token cuối không padding và L2; instruction truy vấn rỗng, system instruction thống nhất cho text/ảnh. Ghim model/processor/mã inference commit `9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda` và SHA-256 mã official; revision công bố là fingerprint SHA-256 của manifest commit/mã/profile/gói, không phải manifest Ollama. `qwen3-vl:4b-instruct` tiếp tục nhận diện vùng qua JSON schema Ollama `/api/generate`. Không giả lập ảnh bằng caption hoặc dùng lại vector cũ; import JSON mới đồng bộ hai service rồi reindex khi đổi model.
3. Decode/EXIF/normalize trong Python, mask kín vùng nhạy cảm từ bbox được validate; encode output mới. Chỉ xử lý bytes trong bộ nhớ. Các thư viện decode ảnh là dependency cần thiết cho trust boundary.
4. Worker ghép full manifest/parts có giới hạn/deadline theo job/lease; kiểm hash/model/source; commit nhiều nguồn một transaction rồi receipt/ACK. Store thêm source_id vào khóa để chứa nhiều ảnh. Query ảnh semantic-only trong image-v1, text hybrid trong text-v1.
5. Notebook pin phiên bản gói/commit/hash inference Qwen và Ollama release/checksum, pull/check digest redaction và test inference text/ảnh/vision; bearer gateway allowlist chỉ tags/show/embed/generate, giới hạn body/concurrency, không access log. Ngrok chỉ expose gateway; embedding chạy trong tiến trình Transformers, redaction qua Ollama loopback. Secrets nhập qua Colab Secrets/getpass, không lưu cell output. Cấu hình export không chứa token; local token nhập riêng.
6. Lệnh local-run quản lý web/API/worker và dừng tiến trình đã tạo, không xóa volume. Chạy kiểm thử tích hợp và báo đúng ranh giới chưa có endpoint/cloud thật.

## Constitution check sau thiết kế

Model embedding Qwen theo yêu cầu chủ dự án không thay trách nhiệm service hay các bất biến riêng tư; gateway tương thích giữ nguyên adapter và hợp đồng local. Số chiều lấy từ model cấu hình và kiểm cả hai đầu. Thay profile/model yêu cầu reindex; không so vector khác model kể cả cùng 2048 chiều. Colab/ngrok là phiên tương tác do người dùng chủ động vận hành, không cam kết hosting thường trực. Tài khoản cloud, GPU và credential thật là phụ thuộc ngoài repo.

## Phạm vi kiểm chứng

Unit ảnh độc hại/PII/no-PII/failure/digest, tests model request shape, tests assembly/replay/deadline; PostgreSQL/RabbitMQ thật với Ollama stub; API HTTP permissions/concurrency, build/smoke; web tests/build; notebook compile và proxy auth/allowlist/body limits. Model inference trên Colab và OAuth/R2 thật chỉ được đánh dấu verified sau khi thực sự chạy.
