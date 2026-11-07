# Theo dõi tin tìm và thông báo phù hợp

Người dùng chủ động chọn **Theo dõi tìm kiếm này** sau một lượt tìm kiếm AI
(vẫn có thể chọn khi có gợi ý nhưng không đúng món đồ). Trang **Tin tìm đang theo dõi**
trong menu tài khoản hiển thị kết quả khớp, đánh dấu đã đọc và dừng theo dõi.
Menu có số thông báo chưa đọc; giao diện kiểm tra lại mỗi 60 giây khi tab đang hiển thị.
Mỗi tài khoản theo dõi tối đa 20 tin; dữ liệu chỉ chủ tài khoản truy cập được.

## POST /api/saved-searches — lưu tin tìm

Yêu cầu đăng nhập, CSRF và `Idempotency-Key` UUID; giới hạn request ảnh như tìm kiếm.
Body `multipart/form-data` có `text` tùy chọn (tối đa 2000 ký tự), `images` tùy chọn
(tối đa 3 ảnh JPEG/PNG/WebP, mỗi ảnh 10 MiB). Cần ít nhất mô tả hoặc một ảnh.
Tổng body tối đa 30 MiB cộng 64 KiB header. API đọc streaming trong RAM;
không dùng form model binding hay lưu ảnh gốc ra đĩa/R2/outbox.

Query tùy chọn `area`, `from`, `until`, `lostAt` cùng hợp đồng với tìm kiếm.
Ngày nhặt là bộ lọc chặt; khu vực là ưu tiên sắp xếp thông báo.
Thời điểm mất được lưu làm ngữ cảnh, không tăng điểm để vượt ngưỡng.

API gọi `image.embed` với `omitOcr:true`, kiểm model/revision/dimensions/hash/vector
và lưu riêng embedding trong database nghiệp vụ. Không lưu OCR, URL hay bytes ảnh.
Mô tả chỉ nằm trong tin tìm riêng tư, không lập chỉ mục công khai hay ghi log.
Không tạo tin tìm dở khi embedding lỗi. Phát lại cùng key/input trả cùng bản ghi,
khác input trả **409**. Tin đã xóa trả **404** khi phát lại key cũ.

Response **201** `SavedSearchResponse`, gồm `id`, `text`, `imageCount`, `area`,
`from`, `until`, `lostAt`, `createdAt`, `lastCheckedAt`, `needsRefresh`, `matches`.
Không trả embedding/hash/khóa nội bộ. Sai input **400**, MIME **415**, quá byte **413**,
quá 20 tin **409**, AI chưa sẵn sàng **503**, reply sai hợp đồng **502**.

## GET /api/saved-searches — tin tìm và thông báo của tôi

Response **200** mảng `SavedSearchResponse` của tài khoản hiện tại.
Mỗi phần tử `matches` gồm `itemId`, `title`, `foundArea`, `score`, `createdAt`, `readAt`.
Ưu tiên cùng khu vực, sau đó điểm giảm dần. Chỉ trả món còn công khai, active,
đúng document version đã khớp; tin ẩn/xóa/trao trả hoặc đổi phiên bản bị loại ngay.

## PUT /api/saved-searches/{id}/matches/{itemId}/read — đã đọc

Yêu cầu CSRF. Response **204**, giữ nguyên thời điểm đọc khi gọi lại.
Không sở hữu tin tìm hoặc món không còn hợp lệ trả **404**.

## DELETE /api/saved-searches/{id} — dừng theo dõi

Yêu cầu CSRF. Xóa tin tìm, embedding và thông báo liên quan trong một transaction.
Response **204**; không sở hữu/không tồn tại **404**. Job chạy đồng thời phải
kiểm lại bản ghi và lease trước khi tạo thông báo, không tái tạo tin đã xóa.

## Lịch chạy và ngưỡng

API chạy job nền theo lịch, mặc định kiểm lại mỗi tin **1 giờ sau một lượt quét
hoàn tất**. Lượt đầu được xếp chạy ngay, vòng nhận việc thức mỗi 30 giây.
Dùng `BackgroundService` có sẵn, không cần cron hệ điều hành hay dependency mới.
Lịch và cursor nằm trong PostgreSQL: khởi động lại API sẽ tiếp tục công việc còn tới hạn.
API và worker phải hoạt động để có thông báo; thời gian thực tế phụ thuộc backlog/AI.

Cron gửi `search.saved` qua query queue. Python tạo vector truy vấn mô tả bằng
model/query instruction hiện hành, dùng vector ảnh đã lưu và quét cosine chính xác:

- Chỉ mô tả: cosine với nguồn text của món đồ.
- Chỉ ảnh: cosine cao nhất giữa các ảnh truy vấn và ảnh của món đồ.
- Cả hai: trung bình điểm mô tả và điểm ảnh cao nhất; cần có cả hai loại nguồn.
- Chỉ nhận **score >= 0.85**, không dùng RRF, reranker hoặc cộng điểm thời gian/khu vực.

0.85 là ngưỡng tương đồng, **không phải cam kết đúng 85%**. Cần dữ liệu có nhãn để
đánh giá false positive/false negative. Thông báo chỉ là gợi ý, không xác nhận sở hữu.

Mỗi trang tối đa 100 món theo ID, không giới hạn top20 của tìm kiếm tương tác.
Cursor được lưu sau mỗi trang để tiếp tục nếu API dừng. Khi quét hết đặt lại cursor
và lịch 1 giờ tiếp theo. Lease 2 phút cùng `FOR UPDATE SKIP LOCKED` tránh nhận trùng;
khóa món và kiểm lại trạng thái/phiên bản/hash/nguồn trước khi lưu. Không báo món do
chính người tìm đăng/giữ. Khóa duy nhất `(saved_search_id,item_id)` chống thông báo trùng;
các lượt kiểm tra sau cập nhật điểm/phiên bản nhưng giữ trạng thái đã đọc.

AI lỗi không đánh dấu kiểm tra thành công; thử lại sau 1 phút và giữ cursor.
Tiến trình mất đột ngột được nhận lại sau khi lease hết hạn. Tài khoản bị vô hiệu hóa
không chạy đối chiếu. Đổi model/revision/dimensions đặt `needsRefresh`: người dùng
cần tìm và lưu lại ảnh/mô tả, vì ảnh gốc đã bị bỏ và không thể tạo lại vector ảnh cũ.

Bản này dùng thông báo trong ứng dụng, chưa gửi email/web push. Không sửa hạ tầng
đăng bài, không chạy migration tự động khi API khởi động. Áp dụng EF migration
`AddSavedSearches` bằng quy trình quản trị database hiện có trước khi chạy bản mới;
triển khai API và Python worker cùng phiên bản.
