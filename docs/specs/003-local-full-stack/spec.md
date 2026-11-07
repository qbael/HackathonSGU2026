# Feature Specification: Chạy Findie đầy đủ tại local

**Created**: 2026-10-27
**Status**: Approved for implementation by the owner's chat request
**Input**: Hoàn thiện những phần thiếu; ứng dụng chạy local, các model chạy trên Google Colab qua Ollama và ngrok. Chủ dự án chưa có notebook hoặc endpoint.

**Cập nhật 28/10/2026**: Chủ dự án chọn `Qwen/Qwen3-VL-Embedding-2B` chạy bằng Transformers cho embedding văn bản/ảnh; gateway giữ hợp đồng Ollama cho local, model nhận diện vùng tiếp tục qua Ollama.

## User Scenarios & Testing

### User Story 1 - Khởi động môi trường thật (P1)

Người phát triển có thể chuẩn bị hai database, broker, dữ liệu Hub và chạy web/API/worker bằng các lệnh được tài liệu hóa, giữ dữ liệu khi chạy lại.

Acceptance: chạy setup hai lần không mất dữ liệu; đăng nhập Google và cấp quyền Hub cho tài khoản đã tồn tại; doctor báo rõ phần chưa sẵn sàng và không coi health live là toàn hệ thống hoạt động.

### User Story 2 - Đăng và tìm ảnh (P1)

Người nhặt đăng ảnh, xem output đã xử lý, duyệt rồi công khai; người tìm dùng ảnh để nhận gợi ý đúng bộ lọc. Chỉ ảnh đã duyệt được lập chỉ mục.

Acceptance: PII được che, ảnh không PII vẫn được encode bỏ metadata; model lỗi không lưu original; nhiều ảnh được commit cùng manifest; kết quả cũ không phục hồi ảnh đã gỡ; tìm ảnh không suy diễn từ khóa OCR.

### User Story 3 - Model từ xa trong phiên demo (P1)

Người phát triển mở notebook mới, chạy Qwen text/image bằng Transformers và model vision bằng Ollama, mở endpoint ngrok có xác thực, lấy cấu hình model về local và kiểm tra kết nối.

Acceptance: request thiếu/sai token bị từ chối, không mở API quản lý model; model revision/số chiều được kiểm tra; notebook có cell dừng tunnel; token không nằm trong output đã lưu hoặc git.

### Edge Cases

Ảnh giả MIME/quá pixel/animation/EXIF orientation; JSON vùng che sai; token/model sai; ngrok hoặc Colab ngắt; deadline; manifest/parts lặp, lệch nguồn, đến thiếu hoặc sai thứ tự; snapshot cũ sau tombstone; grant staff cho tài khoản chưa đăng nhập; dữ liệu hiện hữu và đường dẫn sau refactor.

## Requirements

- **FR-001**: Tái dùng Google cookie auth, các luồng nghiệp vụ và giao diện hiện có; không tạo auth bypass hoặc public admin API.
- **FR-002**: Chuẩn bị hạ tầng và hai database/role tách biệt lặp lại an toàn; có lệnh seed Hub và gán staff cho tài khoản đã đăng nhập.
- **FR-003**: Có pipeline giải mã/chuẩn hóa/che ảnh bằng gợi ý model, kiểm schema/tọa độ/byte/pixel, luôn loại EXIF và chỉ trả output; raw không vào DB, R2, tệp hay log.
- **FR-004**: Lưu/lập chỉ mục nguồn text và nhiều ảnh đã duyệt theo full snapshot, provenance và watermark/tombstone; receipt chỉ sau commit đầy đủ.
- **FR-005**: Tìm ảnh dùng vector ảnh thật; bộ lọc áp dụng trước giới hạn; không dùng caption/OCR để giả vector ảnh.
- **FR-006**: Kết nối model qua HTTPS/token, ghim revision; notebook kiểm text/image/vision trước xuất cấu hình và mở tunnel; không đưa DB/RabbitMQ/web local ra internet.
- **FR-007**: Có lệnh chạy/dừng và kiểm trạng thái đầy đủ; lỗi phụ thuộc giữ dữ liệu và báo rõ phương án lọc cơ bản.
- **FR-008**: Kiểm thử tự động parser/ảnh/model/giao thức, tích hợp hai service với broker/DB thật; phân biệt test double với model/OAuth/R2 thật.

### Key Entities

Không tạo entity nghiệp vụ mới. Search document mở rộng từ một nguồn text thành text + các nguồn ảnh; định danh nguồn và phiên bản vẫn theo outbox hiện hữu. PointStaff do CLI local cấp cho người dùng có sẵn.

## Success Criteria

- **SC-001**: Build/test web và API đạt; các test store chạy đầy đủ trên database tạm.
- **SC-002**: Luồng xử lý ảnh → duyệt → manifest/parts → tìm ảnh → gỡ không công khai raw và không trả nguồn lỗi thời.
- **SC-003**: Có hướng dẫn từ Colab trống tới endpoint xác thực và lệnh chạy local; thiếu credential/endpoint được báo thành việc cần người vận hành, không thành trạng thái thành công giả.

## Assumptions

Một instance mỗi service. Giữ R2 private và Google OAuth đã có cấu hình local; không tự tạo tài khoản cloud hoặc dùng model giả làm runtime mặc định. Chủ dự án chủ động chạy phiên Colab/ngrok bằng tài khoản của mình; không có cơ chế giữ phiên/né giới hạn Colab. Dashboard quản trị đầy đủ, SignalR và attachment chat không cần để hoàn thành các hành trình MVP hiện có.
