# Thiết kế cơ sở dữ liệu Findie

**Phiên bản:** 1.4.0 · **Ngày:** 2026-10-23 · **Trạng thái:** thiết kế đích hybrid search; SQL/ERD bootstrap chưa được di trú.

**Runtime cập nhật 24/10/2026:** API dùng EF Core/Npgsql và ASP.NET Core Identity (`ApplicationUser : IdentityUser<Guid>`), hiện chỉ đăng nhập qua Google OAuth; không mở đăng ký/mật khẩu/bearer token. Migration khởi tạo tại `apps/api/Data/Migrations` tạo **22 bảng ứng dụng** (7 Identity, 14 nghiệp vụ và `index_outbox`), ngoài lịch sử migration. Ảnh chỉ tham chiếu `processed_object_id`, object kind chỉ `processed`, `items` có `document_version`, không có bảng vector trong DB nghiệp vụ. `make db-migrate` thay bootstrap **chỉ khi toàn bộ bảng rỗng**, kiểm tra dưới khóa và áp dụng SQL trong cùng transaction; database cũ có dữ liệu bị từ chối nguyên trạng, cần migration dữ liệu riêng. Không xóa volume.

Kho `findie_search` cho văn bản đã có schema thực thi tại `services/ai/findie_ai/schema.sql` (`ai_items`, `ai_documents`); xem [AI service](../guides/ai-service.md). Thiết kế đích tách role Python/.NET và đặt `search_documents` (bản chiếu công khai/FTS/watermark/tombstone), `search_sources` (manifest/vector) trong DB Python. Model .NET `IndexOutbox` lưu snapshot/tombstone, hash, document version, retry và lease; không có FK đến item. Đã có API nghiệp vụ, dispatcher/consumer RabbitMQ .NET và R2 output/cleanup; worker Python embedding/hybrid search văn bản đã triển khai qua Ollama; phần ảnh chưa triển khai. Quy tắc runtime và hợp đồng: [API](../api/README.md), [AMQP](../api/amqp.md), [quyết định tính năng](../specs/002-recovery-api/spec.md).

Thiết kế dựa trên [đặc tả](../product/DAC_TA_FINDIE.md), [kiến trúc](../architecture/system-architecture.md) và
[hiến chương](../../.specify/memory/constitution.md). Một PostgreSQL instance chứa hai logical
database: `findie` do .NET sở hữu cho nghiệp vụ và `findie_search` do Python sở hữu cho
embedding/bản chiếu công khai/hybrid search. **Cloudflare R2 riêng tư chỉ lưu output ảnh
đã được Python xử lý**, do .NET đọc/ghi; database nghiệp vụ chỉ giữ metadata/tham chiếu
output. Tuyệt đối không lưu ảnh gốc đầu vào hoặc ảnh truy vấn trên R2.
Các yêu cầu đã chốt không bị thay thế bởi các giả định triển khai trong tài liệu này.

**Phân biệt snapshot lịch sử và runtime:** SQL, từ điển cột và ERD đi kèm vẫn là snapshot
bootstrap **16 bảng/164 cột trước hybrid search**, trong đó `item_embeddings` còn thuộc DB
nghiệp vụ với FK nội bộ. `original_object_id` bắt buộc và object kinds `original`/`sanitized`
trong snapshot không tương thích chính sách chỉ lưu processed output của 1.4.0. Chúng cũng
chưa có search store độc lập, FTS hoặc outbox snapshot/tombstone. Những thiếu sót đó thuộc snapshot cũ; runtime hiện tại đã có các cấu trúc mới nêu trên. Danh mục bảng và các ràng buộc SQL bên dưới mô tả snapshot này; thiết kế đích
ở mục 7 và kế hoạch migration ở mục 10. Không áp dụng SQL cũ như schema đích đã hoàn tất.

Tệp đi kèm:

- [ERD chỉnh sửa bằng draw.io](findie-erd.drawio): snapshot bootstrap.
- [DDL PostgreSQL](database-schema.sql): tạo mới 16 bảng bootstrap trong một giao dịch, chưa phải migration hybrid.
- [Mô tả các cột](database-column-dictionary.md): đủ 164 cột trong 16 bảng của DDL bootstrap.
- [Tự kiểm ràng buộc SQL](database-check.sql): kiểm snapshot bootstrap; dữ liệu thử được rollback.

Mở `findie-erd.drawio` bằng **File → Open from → Device** trong [draw.io](https://app.diagrams.net/).
Sơ đồ có 5 trang: tổng quan; tài khoản và món đồ; yêu cầu nhận và chat; tiếp nhận và trao trả;
R2 và xử lý AI. Ngay trang tổng quan đã có đủ 16 bảng, 164 cột, kiểu dữ liệu, NULL, PK/FK và
các ràng buộc duy nhất; phóng to để đọc từng bảng. Các trang chi tiết tách theo nhóm nghiệp
vụ; FK người thực hiện được ghi trong bảng để tránh đường nối chồng chéo.
DDL là nguồn đối chiếu cho snapshot hiện có; cần cập nhật migration/DDL/ERD/kiểm tra trước
khi triển khai đích. Các điều kiện phân quyền/giao dịch vẫn cần .NET thực thi.

## 1. Phạm vi và các lựa chọn thiết kế

Database `findie` phục vụ API .NET, hội thoại và job/outbox. .NET xử lý nghiệp vụ, phân
quyền, R2, nguồn/phiên bản, điều kiện công khai và DTO cuối cùng; không tạo/ghi/truy vấn
vector. Python xử lý toàn bộ embedding, nhận diện/OCR/ảnh, trực tiếp ghi vector/bản chiếu
và chạy hybrid search tại `findie_search`. Hai service trao đổi lệnh/kết quả duy nhất qua RabbitMQ bằng AMQP
0-9-1 với kết nối lâu dài riêng tới broker, channel publish/consume tái sử dụng, heartbeat
và reconnect. RabbitMQ.Client 7.2.2 đã cài ở .NET; aio-pika (Python) còn là thư viện đề xuất, chưa cài đặt.
psycopg 3 là driver search store đề xuất, chưa cài/chốt phiên bản. Credential/ACL tách theo
service: Python chỉ truy cập `findie_search`, không truy cập `findie` hoặc R2; .NET chỉ
truy cập DB nghiệp vụ, không có quyền vector/search store. FastAPI chỉ health/vận hành.
Không thêm Redis, vendor/máy chủ tìm kiếm khác, lịch hẹn, thanh toán hay vận chuyển.

| Lựa chọn | Cách áp dụng |
| --- | --- |
| PostgreSQL | Hai logical database trên cùng instance, không thêm vendor/máy chủ DB |
| pgvector + PostgreSQL FTS | Python dùng `vector(2048)`/exact cosine, `tsvector`/`tsquery`/`ts_rank_cd`/GIN và weighted RRF trong `findie_search` |
| Khóa chính | UUID do .NET sinh; UUID không phải bằng chứng có quyền truy cập |
| Xác thực runtime | Tạm thời chỉ Google OAuth, Authorization Code + PKCE qua .NET; phiên cookie `HttpOnly`, `Secure` ngoài Development, `SameSite=Lax` và chống CSRF |
| Tài khoản runtime | Identity và khóa duy nhất `(login_provider, provider_key)` tại `AspNetUserLogins`; không tự liên kết tài khoản theo email, không lưu token Google hoặc mở đăng nhập mật khẩu |
| Quyền tại điểm | Cặp `(point_id, user_id)` cùng `can_receive`, `can_return`, `revoked_at`; vai trò không lấy từ request của React |
| Thời gian sự kiện | `timestamptz`, phiên DB dùng UTC; giao diện dùng `Asia/Ho_Chi_Minh` |
| Thời điểm nhặt | Ngày địa phương hoặc khoảng thời gian, có độ chính xác riêng; không đổi ngày không biết giờ thành 00:00 giả |
| Ảnh | Original chỉ ở RAM ứng dụng trong deadline; R2 chỉ lưu processed output; mỗi ảnh có một processed object hiện hành, chỉ public sau duyệt |
| Xóa dữ liệu | Mặc định `ON DELETE RESTRICT`; gỡ hiển thị/vô hiệu hóa trước, xóa theo quy trình có chủ đích sau khi chốt thời hạn lưu |

Google và phiên cookie đã được chọn ngày 24/10/2026; quyền đọc công khai và chính sách thời hạn phiên
chi tiết còn cần chốt. DDL bootstrap bên dưới giữ cấu trúc OIDC lịch sử, không phải schema Identity runtime. Các giới hạn
độ dài chuỗi trong DDL là giá trị cơ sở đề xuất để triển khai, không phải quyết định sản phẩm đã nghiệm thu.

## 2. Danh mục 16 bảng và quan hệ của snapshot bootstrap

Ký hiệu: PK là khóa chính, FK là khóa ngoại, UQ là duy nhất. DDL là danh sách cột, kiểu dữ liệu,
NULL và ràng buộc đầy đủ; bảng dưới giải thích ý nghĩa nghiệp vụ.

| Bảng | Khóa và dữ liệu chính | Quan hệ / trách nhiệm |
| --- | --- | --- |
| `app_users` | PK `id`; UQ `auth_issuer, auth_subject`; tên hiển thị, `disabled_at` | Một người có thể vừa nhặt vừa tìm; không tách thành hai loại tài khoản |
| `reception_points` | PK `id`; tên, địa chỉ công khai, chỉ dẫn, `active` | Điểm được hệ thống quản lý; nơi ngoài hệ thống không tạo bản ghi điểm giả |
| `point_staff` | PK/FK `point_id, user_id`; quyền nhận/trả, mốc phân công/thu hồi | Người dùng và điểm quan hệ N–N; mỗi quyền chỉ có hiệu lực tại điểm đó |
| `items` | PK `id`; FK người đăng/người giữ/điểm giữ; mô tả công khai, nơi/thời gian nhặt, trạng thái, các phiên bản | Trung tâm nghiệp vụ, đúng một nhánh nơi giữ tại một thời điểm |
| `stored_objects` | PK `id`; UQ `bucket, object_key`; loại, trạng thái, SHA-256, MIME thực, kích thước, hạn dọn | Theo dõi mọi đối tượng R2 kể cả tải dở, kết quả AI thua tranh chấp và ảnh đã thay thế |
| `item_images` | PK `id`; FK `item_id`, `original_object_id`, `sanitized_object_id`, người duyệt; vị trí, phiên bản, kết quả xử lý | Liên kết original/sanitized legacy, không dùng trong đích 1.4.0; migration thay bằng một `processed_object_id` hiện hành |
| `verification_questions` | PK `item_id, slot`; `slot` từ 1 đến 3; nội dung câu hỏi hiện tại | Không có hàng nào tương ứng 0 câu hỏi; không cần câu hỏi giả |
| `claims` | PK `id`; FK món/người yêu cầu/người duyệt; phiên bản nơi giữ lúc gửi, trạng thái/quyết định | Người duyệt là bản chụp người giữ tại lúc tạo yêu cầu, không tự đổi theo nơi giữ sau này |
| `claim_answers` | PK `claim_id, slot`; nội dung câu hỏi chụp lúc gửi, câu trả lời | Tối đa 3 hàng; không FK tới câu hỏi hiện tại để chỉnh câu hỏi không làm biến đổi bằng chứng đã gửi |
| `conversations` | PK/FK `claim_id`; FK có điều kiện trạng thái `approved` | Một yêu cầu có 0 hoặc 1 hội thoại; hai bên lấy từ claimant/reviewer bất biến của yêu cầu |
| `messages` | PK `id`; FK hội thoại/người gửi; mã gửi lại, thứ tự, nội dung, mốc lưu | UQ `conversation_id, sender_user_id, client_message_id`; hỗ trợ tải lại lịch sử |
| `intake_requests` | PK `id`; FK món/người gửi/điểm đích/người quyết định; phiên bản nơi giữ nguồn | `pending` là chờ nhận thực tế; `received` chỉ khi nhân viên xác nhận đã cầm món đồ |
| `custody_events` | PK `id`; FK món/người thao tác/yêu cầu tiếp nhận/yêu cầu nhận/người nhận nếu có; bản chụp trước/sau | Lịch sử đăng ký nơi giữ, nhận thực tế và trao trả; tối đa một sự kiện `returned` cho mỗi món |
| `ai_jobs` | PK `id`; FK món/ảnh; loại redact/embed, nguồn/phiên bản/hash, mô hình/profile, retry, lease | Job suy luận bootstrap do .NET sở hữu; chưa có outbox payload/tombstone hoặc loại upsert/remove đầy đủ |
| `item_embeddings` | PK `id`; FK món/ảnh; modality, nguồn/phiên bản/hash, mô hình/profile, vector | Bảng vector cũ trong DB nghiệp vụ; cần chuyển/tạo lại tại `findie_search`, bỏ FK xuyên DB |
| `idempotency_keys` | PK `actor_user_id, idempotency_key`; thao tác, hash request, tài nguyên kết quả | Chống lặp tác động khi client thử lại các thao tác nghiệp vụ; không lưu bản sao câu trả lời/chat |

`idempotency_keys.resource_id` là tham chiếu đa loại có chủ đích, không phải FK. .NET kiểm tra
`resource_type`, tài nguyên tồn tại, quyền truy cập và lưu kết quả cùng giao dịch nghiệp vụ.
Các FK ghép `(image_id, item_id)`, `(claim_id, item_id)`, `(intake_request_id, item_id)` ngăn
liên kết một ảnh/yêu cầu thuộc món khác trong snapshot bootstrap. Search store đích chỉ dùng
ID tham chiếu logic; không có FK hoặc truy vấn chéo hai database.

## 3. Nơi giữ, thời gian và phiên bản

### Ba nhánh nơi giữ

`items.custody_kind` quyết định bộ cột được phép có giá trị:

| Loại | Bắt buộc | Phải NULL |
| --- | --- | --- |
| `person` | `holder_user_id` | `holder_point_id` và các trường `external_*` |
| `point` | `holder_point_id` | `holder_user_id` và các trường `external_*` |
| `external` | `external_name`, `external_public_address` | Hai FK người/điểm; `external_instructions` tùy chọn |

`CHECK` kiểm tra cả trường bắt buộc khác NULL lẫn các trường loại trừ. Không lưu địa chỉ nhà
riêng trong nơi nhặt, bản chụp lịch sử hoặc thông tin nơi giữ công khai. Trao trả hoàn tất đặt
`lifecycle = 'returned'`; giữ bộ cột nơi giữ như **nơi giữ cuối cùng trước khi trả**, không có nghĩa
nơi đó vẫn đang giữ món đồ. Không hiển thị món đã trả trong danh sách có thể nhận. Người nhận
được ghi ở sự kiện trả, không bị biến thành người giữ mới của một món đang có thể nhận.

Xóa bài đăng đặt `lifecycle = 'deleted'`, giữ nguyên nơi giữ và lịch sử liên quan. .NET
loại bài đã xóa khỏi mọi scope, chi tiết và tìm kiếm, đồng thời ghi tombstone vào outbox;
claim/intake cũ hết hiệu lực và hội thoại chỉ còn đọc. Đây là xóa mềm, không xóa dữ liệu
hoặc object ảnh đã lưu.

`custody_events.from_custody/to_custody` là JSON chụp loại nơi giữ, ID, tên điểm/nơi và địa chỉ
công khai tại thời điểm thao tác. Bản chụp tránh mất lịch sử khi điểm đổi tên. JSON không thay
FK của nơi giữ hiện tại; .NET phải kiểm tra cấu trúc và đối chiếu với hàng `items` bị khóa.

### Thời điểm nhặt

- `unknown`: không biết ngày/giờ; các cột ngày và khoảng thời gian NULL.
- `date`: `found_on` là ngày địa phương; không tạo thời điểm chính xác thay thế.
- `exact`: `found_from` là thời điểm đã biết, `found_until` NULL.
- `range`: `found_from <= found_until`; giữ nguyên khoảng ước lượng, kể cả qua nửa đêm.

`found_timezone` giữ ngữ cảnh ngày/giờ nhập; .NET kiểm tra tên múi giờ IANA và không cho ngày
nhặt tương lai theo chính sách đã chốt. Đặc tả đang **đề xuất** bắt buộc ngày; schema giữ khả năng
biểu diễn `unknown` trung thực. Nếu chốt bắt buộc ngày khi đăng, API từ chối `unknown` ở thao tác
đó, không tự điền một ngày giả. Các bộ lọc phải xử lý độ chính xác và thông báo khi nới điều kiện.

### Ba phiên bản riêng

| Trường | Tăng khi nào | Dùng để |
| --- | --- | --- |
| `items.row_version` | Mọi cập nhật món đồ | Phát hiện biểu mẫu cũ / cập nhật đồng thời bằng điều kiện phiên bản |
| `items.content_version` | Mô tả công khai dùng tạo vector thay đổi | Vô hiệu hóa vector văn bản và tác vụ nguồn cũ |
| `items.custody_version` | Đăng ký/chuyển nơi giữ/trao trả thực tế | Ngăn duyệt/tiếp nhận theo nơi giữ cũ, kể cả khi nơi giữ đổi rồi quay về cùng người |
| `item_images.content_version` | Thay nguồn, yêu cầu xử lý lại hoặc sửa vùng che ảnh | Vô hiệu hóa kết quả xử lý/vector ảnh và phê duyệt cho phiên bản cũ |

.NET tăng phiên bản; không có trigger tự tăng trong DDL. Sửa câu hỏi và chụp bộ câu hỏi khi gửi
yêu cầu đều khóa hàng món đồ để tránh chụp nửa bộ câu hỏi cũ, nửa bộ mới.

Đích hybrid cần thêm/ánh xạ `document_version` tăng đơn điệu theo món để bao phủ cả nội
dung, nguồn ảnh, duyệt, nơi giữ và quyền hiển thị. Các cột phiên bản hiện tại không tự tạo
hợp đồng này; migration phải định nghĩa ánh xạ và outbox nguyên tử, không giả định đã có.

## 4. Chỉ lưu processed output trên R2

### Ranh giới dữ liệu và lược đồ đích

Ảnh gốc do người dùng tải lên **không được lưu trên R2**, kể cả bucket riêng tư hoặc prefix
`original/`/`temporary/`. Không có endpoint xem/tải original, object gốc hoặc tham chiếu nguồn
gốc trong DB. .NET nhận upload trong bộ nhớ có trần byte, Python xử lý trong bộ nhớ; bỏ
bytes sau hoàn tất, lỗi hoặc deadline. Không ghi raw bytes vào tệp tạm ứng dụng, job/outbox,
log, DLQ hoặc backup. Ảnh truy vấn cũng tuân theo quy tắc này, không được tạm đưa vào R2.

Lược đồ đích cần `item_images.processed_object_id` (hoặc tương đương) trỏ tới **một output
hiện hành** và `stored_objects.object_kind = 'processed'`. Đó là yêu cầu migration, chưa
phải cột/giá trị có trong DDL bootstrap. Không đổi ý nghĩa `original_object_id` thành output
để né FK bắt buộc. Các output thay thế có object/key riêng và được dọn theo retention.

Output gồm cả hai trường hợp: phát hiện nhạy cảm thì che/mờ trước khi encode; không phát
hiện thì vẫn chuẩn hóa, bỏ EXIF và encode ảnh mới. Lỗi nhận diện không phải bằng chứng
không nhạy cảm. Không có output hợp lệ thì không dự trữ/ghi bất kỳ ảnh nào lên R2. Tất cả
output lưu riêng tư, chờ người có quyền duyệt trước khi public hoặc tạo embedding ảnh.

### Luồng upload, xử lý và lưu output

1. Browser gửi upload cho .NET. Backend kiểm quyền, dữ liệu nghiệp vụ và giới hạn byte;
   nhận ảnh vào RAM có giới hạn, không giải mã hoặc spool ra đĩa. Gửi `image.redact` qua
   RabbitMQ request/reply tạm với correlation/deadline; chưa tạo R2 object hoặc durable
   job/outbox chứa ảnh gốc. Dữ liệu món/mô tả hợp lệ có thể được giữ độc lập khi ảnh lỗi.
2. Python kiểm envelope/deadline/byte, giải mã/kiểm MIME thực/số pixel và tài nguyên, chạy
   Qwen nhận diện/OCR/vùng nhạy cảm. Có vùng cần che thì kiểm schema/tọa độ và dùng OpenCV
   che/mờ; không có vùng vẫn chuẩn hóa/loại EXIF/resize theo profile. Cả hai nhánh đều encode
   output mới và kiểm output/hash/MIME/kích thước. Model lỗi, tọa độ không hợp lệ hoặc output
   không đạt thì trả mã lỗi an toàn, không dùng input làm fallback.
3. Python trả bytes output/metadata qua RabbitMQ. .NET chỉ chấp nhận correlation/deadline/
   phiên xử lý hiện hành, kiểm hợp đồng, hash và số byte; không giải mã ảnh. Chỉ lúc có
   output hợp lệ mới tạo `stored_objects` loại `processed`, trạng thái `reserved`, có
   `expires_at`/key ngẫu nhiên trước upload R2. `reserved` chỉ theo dõi output chờ lưu, không
   phải nơi chứa input chưa được Python kiểm.
4. .NET ghi output R2 ngoài transaction DB. Upload thành công và metadata/hash output hợp
   lệ mới đặt `validated`; không tự coi input hoặc kết quả không đầy đủ là validated.
   Giao dịch nghiệp vụ khóa đối tượng, kiểm quyền/phiên bản, ghi metadata và liên kết
   `processed_object_id`, đặt `needs_review`/review pending và ghi snapshot/outbox phù hợp.
   Manifest tìm kiếm chưa được phép chứa ảnh đang chờ duyệt. Output lỗi/thua tranh chấp
   hoặc upload bỏ dở vẫn có metadata để dọn, không làm phát sinh object original.
5. Người có quyền chỉ xem **output**, duyệt đúng phiên bản. Chỉ khi approved thì ảnh ở
   `ready` và transaction .NET mới ghi `index.upsert` cho nguồn output công khai. Python
   tự tạo/kiểm/chuẩn hóa/lưu embedding tại `findie_search`. Text công khai có thể lập chỉ
   mục độc lập; ảnh chưa duyệt không có embedding công khai.
6. Cần che thêm thì xử lý lại output hiện tại hoặc yêu cầu người dùng tải lại original,
   tạo output/key/version mới và reset duyệt. Không có original để tải lại/bỏ mờ. Chỉ lưu
   loại vùng/tọa độ chuẩn hóa và model/revision/profile cần thiết, không lưu toàn bộ OCR.

Phải bỏ byte gốc ở cả .NET/Python sau xong/lỗi/deadline; không log body khi validate lỗi.
Chỉ retry xử lý đầu vào trong lúc bytes còn RAM và cùng request chưa hết deadline; mất
process/RAM hoặc deadline phải yêu cầu tải lại. Không hứa job bền vững có thể phát lại ảnh
gốc. Nếu output cũng chỉ còn trong RAM trước khi upload R2 thành công, retry ghi chỉ sống
trong thời hạn đó; crash không có nguồn bền vững thì cần tải lại, không hứa job tự phục hồi.
Durable retry chỉ bắt đầu cho chỉ mục từ output đã lưu và được duyệt hoặc thao tác có
nguồn output bền vững hợp lệ. `ai_jobs.redact_image` bootstrap cần migration/
luồng điều phối mới, không dùng để khôi phục original đã mất.

### Transport ảnh tạm và giới hạn lưu giữ

Queue ảnh tạm do Python khai báo với tên broker sinh, binding `image.redact`/`search.hybrid.image`, tách khỏi luồng chỉ mục durable: non-durable, exclusive, auto-delete; message
mang input là nonpersistent, TTL/deadline hữu hạn và **không có raw-body DLQ/dead-letter**.
Ảnh query dùng `search.hybrid.image` cũng phải theo route ảnh tạm này, không đi queue durable
chỉ vì là tìm kiếm. Request/reply dùng connection/channel lâu dài; owner/topology bootstrap
và routing cụ thể phải chốt trước triển khai. Publisher confirm/routing chỉ xác nhận giao
nhận, không biến request này thành job khôi phục được sau crash.

ACK/drop body ở kết quả kết thúc hoặc lỗi vĩnh viễn; hết TTL thì bỏ, chỉ lưu mã lỗi an toàn.
Không requeue vô hạn hoặc gửi poison chứa original sang DLQ. Output/chỉ mục có thể dùng
transport bền vững theo chính sách riêng, nhưng không được chứa lại input gốc. **RabbitMQ
có thể page nonpersistent message xuống đĩa**: non-durable/nonpersistent và TTL chỉ giới hạn
vòng đời logic, không bảo đảm forensic chỉ RAM/xóa tức thì. Phải cấm raw body log, DLQ và
backup, giới hạn byte/prefetch/concurrency/TTL và kiểm cấu hình broker thực tế.

### Điều kiện đọc và dọn output

R2 chỉ có processed output trong bucket riêng tư, không bật `r2.dev`. .NET cấp URL/dữ liệu
ngắn hạn cho public khi bài được xem, ảnh chưa retired, `ready`, review approved, object
kind `processed` và `validated`, đúng phiên bản; endpoint duyệt output kiểm quyền riêng.
Không tồn tại API original. Python không có credential R2 và không tải URL tùy ý.

.NET worker dọn khóa object, kiểm không còn tham chiếu và đã hết hạn, đặt `delete_pending`,
commit rồi xóa R2 ngoài transaction. Xóa thành công mới đặt `deleted_at`; lỗi giữ metadata,
retry/backoff hữu hạn. Object còn được ảnh/job chỉ mục hợp lệ tham chiếu không bị xóa vì
lifecycle chung. Không xóa metadata khi vẫn phải dọn object thực tế; upload output bỏ dở
và kết quả thua tranh chấp đều phải được theo dõi.

Gỡ ảnh đặt `retired_at`, tăng phiên bản, ghi snapshot/tombstone cùng transaction nghiệp vụ
và ngừng cấp URL ngay. Python vô hiệu/xóa vector theo outbox; .NET loại ứng viên cũ kể cả
chỉ mục đang trễ. URL đã cấp có thể sống đến hết hạn. Purge sau retention phải giữ outbox
chưa hoàn tất và watermark chống phát lại; dọn job/metadata output có kiểm soát rồi mới dọn
object không còn tham chiếu. `original_object_id` và FK legacy là việc phải migration,
không áp dụng nguyên trạng cho pipeline mới. Nếu từng có original cũ, phải kiểm kê và lập
kế hoạch gỡ quyền/cleanup có kiểm soát; lần sửa tài liệu không xóa R2 hoặc dữ liệu thực tế.

## 5. Yêu cầu nhận đồ, câu trả lời và hội thoại

### Yêu cầu và bằng chứng

.NET chỉ tạo claim khi món còn có thể nhận, do cá nhân giữ và người gọi được phép yêu cầu.
Trong giao dịch khóa món, ghi claimant từ phiên máy chủ; ghi reviewer từ người giữ thực tế và
`source_custody_version`; chụp toàn bộ 0–3 câu hỏi vào `claim_answers`, kể cả câu chưa được trả
lời. Không có câu hỏi thì không tạo dòng answer, claim vẫn hợp lệ. Quy tắc bắt buộc trả lời
câu đã tạo là quyết định sản phẩm còn mở; SQL cho phép `answer_text` NULL.

`claimant_user_id`, `reviewer_user_id`, phiên bản nơi giữ và câu trả lời chụp lúc gửi là bất biến
đối với các endpoint MVP. Chỉ claimant và reviewer còn có quyền tại thời điểm truy cập được
đọc bằng chứng; không tự cấp cho người giữ mới hoặc toàn bộ nhân viên của điểm mới. Khi duyệt,
kiểm tra reviewer vẫn là người giữ, món active và phiên bản nơi giữ còn khớp. Yêu cầu lỗi thời
không được duyệt; không tự hủy hay tự chuyển người duyệt khi chưa có chính sách tương ứng.

### Hội thoại đúng hai bên

`conversations.claim_id` vừa là PK vừa tham chiếu claim; không có bảng thành viên mở rộng.
Hai người được phép tham gia lấy từ claimant/reviewer bất biến. FK ghép với `approval_status =
'approved'` khiến DB từ chối tạo hội thoại cho claim pending/rejected; mỗi claim tối đa một chat.
Không tạo chat mặc định cho đồ tại điểm hoặc nơi ngoài hệ thống.

Mọi lần đọc lịch sử, kết nối SignalR, tham gia nhóm, gửi tin và kết nối lại đều kiểm tra danh tính,
claim approved và chính sách vòng đời hiện tại tại .NET. Không tin sender hoặc group ID do
client tự khai. DB có FK sender tồn tại nhưng không tự kiểm tra sender là một trong hai bên.

Lưu tin theo thứ tự sau:

1. Khóa hàng `conversations` bằng `SELECT ... FOR UPDATE` **trước khi INSERT tin nhắn**; kiểm
   tra lại quyền và trạng thái. Tất cả đường ghi tin phải dùng cùng thứ tự khóa này.
2. Tra khóa `(conversation_id, sender_user_id, client_message_id)`. Nếu đã có cùng nội dung,
   trả lại tin cũ; cùng mã nhưng khác nội dung trả lỗi xung đột.
3. INSERT tin và commit, sau đó mới xác nhận/phát SignalR. Client loại sự kiện trùng bằng ID.
4. Đọc bù dùng `message_sequence > last_seen ORDER BY message_sequence`, phân trang có giới hạn.

Khóa theo hội thoại ở bước 1 là bắt buộc: sequence IDENTITY được cấp trước commit; nếu chỉ
INSERT song song, tin số 102 có thể commit trước 101 khiến con trỏ 102 bỏ lỡ tin 101. Khóa này
bảo đảm thứ tự commit của các tin trong cùng hội thoại. Khoảng trống do rollback là hợp lệ.
Không giữ khóa trong lúc phát SignalR; sự kiện có thể mất nhưng dữ liệu đã commit có thể đọc lại.

Thu hồi phê duyệt/rút yêu cầu chưa được mô hình hóa thành trạng thái triển khai. FK sẽ chặn
đổi claim approved đã có chat sang rejected; việc thêm thu hồi cần quyết định vòng đời chat và
migration tương ứng. Quyền đọc/gửi sau đổi nơi giữ hoặc trả đồ cũng chưa chốt; phương án đề xuất
là dừng gửi khi điều kiện hiện hành không còn đúng và chỉ giữ lịch sử cho các bên theo chính
sách lưu giữ được duyệt. Đây chưa phải hành vi sản phẩm được thông qua.

## 6. Giao dịch tiếp nhận, trao trả và gửi lại

Mọi thay đổi nghiệp vụ dùng giao dịch ngắn với thứ tự khóa nhất quán: món đồ, yêu cầu liên quan,
đối tượng hoặc hội thoại nếu có. Không gọi R2, AI hay SignalR trong giao dịch đang giữ khóa.

| Thao tác | Các bước nguyên tử trong PostgreSQL |
| --- | --- |
| Đăng món | Lưu item + nơi giữ thực tế; chỉ gắn processed output đã upload/validated nếu có; ghi `registered` phiên bản 1 và snapshot/outbox sau lưu output theo schema đích; lưu khóa idempotency |
| Gửi tiếp nhận | Tạo request pending với `source_custody_version`; không sửa nơi giữ |
| Từ chối tiếp nhận | Kiểm tra nhân viên điểm đích; cập nhật request/reason; không sửa nơi giữ |
| Xác nhận đã nhận | Khóa item/request; kiểm tra active, pending, phiên bản nguồn, điểm active và `can_receive` chưa thu hồi; cập nhật request received + nơi giữ point + phiên bản; ghi sự kiện received |
| Duyệt claim | Khóa item/claim; kiểm tra người giữ hiện tại và phiên bản nguồn; cập nhật approved và tạo chat trong cùng giao dịch |
| Trao trả cá nhân | Kiểm tra người giữ thực tế, claim approved đúng món/phiên bản và người nhận; ghi một event returned + lifecycle returned + tăng phiên bản |
| Trao trả tại điểm | Nhân viên hiện được phân công, `can_return`, đã xác minh trực tiếp; event returned + lifecycle returned + tăng phiên bản; không bắt buộc có claim/chat |

`custody_events` là nhật ký chỉ thêm, không phải bảng được cập nhật/xóa qua API thông thường.
`occurred_at` là thời điểm bàn giao thực tế, `recorded_at` là lúc ghi nhận. Hai mốc có thể khác;
API xác thực mốc thực tế theo quy trình, không tin thời gian tùy ý từ client. Với nhận tại điểm,
`recipient_user_id` có thể NULL nếu người nhận trực tiếp không có tài khoản; `verification_note`
là ghi chú tối thiểu riêng tư, không mặc định thu ảnh giấy tờ/số định danh. Bộ bằng chứng cần lưu
phải được chốt trước dữ liệu thật.

Chỉ mục duy nhất có điều kiện trên `custody_events(item_id) WHERE event_kind = 'returned'`
chặn lần trả thứ hai ngay cả khi ứng dụng sai. Khóa hàng item và kiểm tra lifecycle ngăn đồng
thời nhận vào điểm và trao trả. SQL không tự tạo sự kiện hoặc đồng bộ lifecycle: .NET phải thực
hiện tất cả ghi trong một giao dịch, rollback toàn bộ nếu một phần thất bại.

`idempotency_keys` có hiệu lực cho tạo/sửa món, xử lý ảnh, gửi/xét claim, gửi/xét intake và trả đồ:

- Máy chủ tính hash canonical gồm loại thao tác, tài nguyên và payload; lấy actor từ phiên.
- Chèn khóa cùng giao dịch nghiệp vụ, với ID kết quả được biết trước. Khóa trùng chờ giao dịch
  trước kết thúc; cùng hash/operation trả kết quả cũ, khác payload trả xung đột.
- Lỗi/rollback không để lại kết quả thành công giả. Khi đọc kết quả cũ vẫn kiểm tra quyền hiện tại.
- Chưa tự hết hạn khóa nghiệp vụ khi chưa chốt chính sách retry/retention; xóa khóa quá sớm có
  thể cho phép tác động lặp. Tin nhắn dùng khóa duy nhất riêng trong bảng `messages`.

Schema không đặt UNIQUE một claim approved trên mỗi món và không tự hủy các request pending
khác khi trả/chuyển nơi giữ. Duyệt nhiều người, rút/thu hồi, stale request hiển thị ra sao và quyền
cập nhật trả ở nơi ngoài hệ thống là quyết định sản phẩm. Trước khi triển khai endpoint chịu
ảnh hưởng, chốt chính sách và kiểm tra trong transaction; không suy diễn từ việc schema lưu
được nhiều dòng. Mở chỉ đường không thay đổi DB và không ghi nhận trao trả.

## 7. Kho vector và hybrid search do Python sở hữu

Cấu hình cơ sở: Qwen/Qwen3-VL-Embedding-2B cho cả văn bản và ảnh, đầu ra 2048 chiều;
Qwen/Qwen3-VL-4B-Instruct đề xuất vùng ảnh, OpenCV tạo bản che. Trước triển khai phải ghim
revision/commit của trọng số, tokenizer/processor và thư viện; không dùng `main`/`latest`
như revision đã kiểm chứng. Python kiểm đúng 2048 chiều, từng giá trị hữu hạn, khác không,
chuẩn hóa L2 và tương thích model/revision/profile trước khi ghi vector.

`model_id + model_revision + processing_profile + dimensions` xác định cấu hình vector.
Profile bất biến gồm chuẩn hóa văn bản, prompt, tokenizer, resize và tiền xử lý do Python
thực hiện. `source_sha256` là hash payload văn bản công khai theo hợp đồng hoặc byte **ảnh
sạch đã duyệt**; định danh/hash input chỉ dùng tạm trong request, không lưu tham chiếu
original trong DB/job/outbox hoặc đưa vào chỉ mục công khai.

### 7.1. Dữ liệu logic đích tại `findie_search`

Các trường sau mô tả yêu cầu migration, **chưa phải cột/bảng trong DDL hiện có**.

| Nhóm dữ liệu | Thông tin cần giữ | Quy tắc |
| --- | --- | --- |
| Bản chiếu món đồ | `item_id`, snapshot công khai đầy đủ, `document_version`, snapshot hash, manifest nguồn text/ảnh được phép | Chỉ mô tả công khai và metadata lọc an toàn: khu vực/thời gian, trạng thái công khai/chưa trả, trạng thái duyệt ảnh; không khóa R2 hoặc bằng chứng |
| Nguồn/vector | ID tham chiếu logic món/ảnh, modality, source version/hash, document version, model/revision/profile, dimensions, vector | Python sinh/kiểm/chuẩn hóa/upsert; ảnh chỉ từ bản sạch đã duyệt; ID do nguồn cấp không tạo FK xuyên DB |
| Chỉ mục từ khóa | Văn bản công khai, cấu hình FTS nhất quán, `tsvector`, GIN | Không OCR riêng tư, câu trả lời, chat hoặc địa chỉ nhà; cập nhật cùng transaction bản chiếu/vector áp dụng |
| Watermark/tombstone | Phiên bản đơn điệu lớn nhất và dấu gỡ theo món/nguồn, snapshot hash, định danh message/job đã áp dụng để xử lý lặp | Không xóa dấu phiên bản khi xóa vector; message cũ không được hồi sinh dữ liệu |

Database này không giữ ảnh gốc/ảnh sạch hoặc vector truy vấn tạm. Python chỉ có credential
kho tìm kiếm; không đọc nguồn bằng SQL xuyên DB, không lấy R2 hoặc tải URL tùy ý. .NET không
được tạo/ghi/truy vấn vector hoặc chạy hybrid ranking; nó gửi snapshot/bytes được phép qua
RabbitMQ và đọc nghiệp vụ hiện tại để tạo DTO.

### 7.2. Hybrid search và kiểm tra kết quả

1. .NET kiểm query/bộ lọc, gửi `search.hybrid` với correlation, deadline và giới hạn ứng viên.
   Python tạo vector truy vấn tạm, chọn profile có phiên bản; không lưu lịch sử/embedding truy vấn.
2. Python áp dụng điều kiện công khai/chưa trả, nguồn ảnh sạch/duyệt, khu vực/thời gian vào
   cả hai nhánh **trước giới hạn ứng viên**. Chỉ dùng model/revision/profile và phiên bản
   nguồn hiện hành của bản chiếu; không âm thầm mở rộng bộ lọc.
3. Nhánh dense dùng exact cosine `<=>` của pgvector. Nhánh lexical dùng PostgreSQL FTS
   `tsvector`/`tsquery`, `ts_rank_cd`, GIN. Baseline `simple` + `unaccent` dùng thống nhất
   document/query phải đo tiếng Việt có/không dấu, từ ghép và nhãn hiệu; không gọi đây là BM25.
4. Thu gọn từng nhánh về món đồ duy nhất, nhiều ảnh lấy hạng tốt nhất; hợp nhất bằng
   weighted RRF: `w_dense / (60 + rank_dense) + w_keyword / (60 + rank_keyword)`, hạng từ 1,
   nhánh thiếu đóng góp 0, phá hòa ổn định theo ID. Không cộng trực tiếp cosine với điểm FTS.
   Ảnh-only không có từ khóa hợp lệ dùng dense + bộ lọc, không bịa OCR/từ khóa. Không trộn
   điểm text/ảnh khác thang đo hoặc cấu hình xuyên modality chưa đánh giá.
5. Python trả ID, hạng/điểm thành phần, document/source version/hash và model/profile.
   .NET kiểm lại quyền, trạng thái published/active/chưa trả, bộ lọc, nguồn/duyệt ảnh và
   phiên bản hiện tại trước **mỗi DTO kết quả và lượt đọc chi tiết**. Loại ứng viên cũ, giữ
   thứ tự hợp lệ; chỉ refill trong số vòng/deadline hữu hạn, không lấy đủ bằng dữ liệu cũ.

Bảng profile, trọng số/candidate budgets và mục tiêu độ chính xác theo từng trường hợp ở
**mục 5.3 [kiến trúc hệ thống](../architecture/system-architecture.md)** là nguồn chuẩn duy nhất. Hit@10 và
Recall@50 phải đo theo món đồ duy nhất sau kiểm tra nghiệp vụ, cùng tập test độc lập có
nhãn; hiện chưa đo. Không coi cosine/RRF là xác suất hoặc tự đặt ngưỡng đã đạt. So sánh
lexical-only, dense-only và hybrid, báo riêng truy vấn không có món phù hợp.

Baseline giữ `vector(2048)` và exact search. Khi cần ANN phải benchmark rồi chọn
halfvec/giảm chiều hoặc phương án tăng tốc và migration/reindex rõ ràng; không âm thầm cắt
chiều. GIN FTS thuộc migration kho tìm kiếm mới, chưa tồn tại trong DDL bootstrap.

Truy vấn tạm có waiter .NET với thời hạn hữu hạn, không giữ transaction DB; kết quả trùng,
muộn hoặc không còn waiter bị ACK/bỏ. `ai_jobs.item_id` bắt buộc nên không dùng để lưu tìm
kiếm tạm không gắn món. Broker/model/search store lỗi phải báo dịch vụ không khả dụng và
cho dùng danh sách/bộ lọc cơ bản từ DB nghiệp vụ, không báo nhầm là không tìm thấy.

### 7.3. Outbox, phiên bản và hai transaction độc lập

Các bước bền vững dưới đây áp dụng chỉ mục/đồng bộ sau khi có output đã lưu; không áp dụng
cho raw input của `image.redact`. Original không nằm trong job hoặc outbox.

1. .NET ghi snapshot công khai đầy đủ hoặc tombstone cùng transaction nghiệp vụ cho mọi
   thay đổi ảnh hưởng tìm kiếm: mô tả/ảnh, duyệt/thu hồi, nơi giữ, xuất bản/ẩn, trao trả/xóa.
   `document_version` tăng đơn điệu theo món; manifest liệt kê từng nguồn với version/hash
   và model/profile. Cần migration outbox chứa payload và ánh xạ phiên bản; `ai_jobs` cũ chỉ
   có redact/embed và lease, không đủ payload/type cho `index.upsert`/`index.remove`.
2. Dispatcher .NET lease việc đến hạn bằng `FOR UPDATE SKIP LOCKED`, ghi attempts/deadline,
   commit rồi publish ngoài DB transaction, có publisher confirm/mandatory routing. Job
   hiện có giữ `running` và ảnh giữ `processing` khi đã dispatch/đang chờ; chưa có cột
   `published`. Crash/confirm không rõ cho phép phát lại cùng job/lease còn hạn; lease hết
   hạn mới cấp attempt mới khi attempt chưa kết thúc. Không tăng attempts vì phát lại.
3. Python nhận `index.upsert`/`index.remove`; chỉ áp dụng snapshot mới hơn hoặc phát lại
   cùng snapshot hash/định danh. Cùng `document_version` nhưng hash snapshot khác là conflict.
   Nhiều job text/ảnh có ID riêng cùng tham chiếu một snapshot/manifest hợp lệ không phải
   conflict chỉ vì payload nguồn khác nhau. Kết quả embedding lâu chỉ được commit dưới
   khóa/điều kiện nếu document watermark và source version/hash còn hiện hành. Tombstone
   chặn mọi upsert cũ, kể cả sau khi vector đã xóa; cần đối soát/rebuild theo snapshot .NET.
4. Python commit vector/bản chiếu/FTS áp dụng trong transaction riêng ở `findie_search`,
   rồi publish biên nhận chứa job/correlation/lease/document/source/model và xác nhận đã
   commit. Chỉ ACK lệnh sau result được confirmed/routed. Crash sau commit trước biên nhận
   phải cho phép phát lại an toàn và gửi lại biên nhận, không tạo vector trùng.
5. .NET kiểm receipt, khóa nguồn/job và kiểm lease/phiên bản/điều kiện hiện tại; commit
   trạng thái job/nghiệp vụ trong `findie`, rồi ACK result. Duplicate/stale được chủ đích
   loại rồi ACK; không hoàn tất job của lease mới bằng receipt cũ. **Commit Python và
   commit .NET không nguyên tử với nhau**; bỏ receipt cũ không tự xóa vector ở search store.
6. .NET quản lý retry hữu hạn bằng attempts/`max_attempts`/`next_attempt_at` và backoff; lỗi
   tạm thời thành retry, lỗi vĩnh viễn/hết giới hạn thành failed. Lỗi schema/poison vào DLQ
   có retention; DB/transport lỗi phải có giao lại/backoff/giới hạn, không requeue nóng vô
   hạn. Python không tạo vòng retry mô hình độc lập. Thử lại giữ identity cùng nội dung/
   nguồn, không tạo job mới vô hạn để vượt giới hạn. Timeout/lease/backoff phải chốt khi triển khai.

`image.redact` là request/reply tạm theo mục 4, không có khả năng replay original bền vững.
Ảnh AMQP là body nhị phân, metadata
JSON nhỏ trong header; văn bản/receipt/ứng viên là JSON. Baseline **10 MiB/body ảnh**, header
đề xuất 16 KiB, giới hạn tổng message phải có chỗ cho header. Không base64 hoặc URL tùy ý.
Message chỉ mục/output bền vững và DLQ tương ứng vẫn có thể chứa dữ liệu riêng tư trên đĩa:
cần TLS/ACL/retention và giới hạn dung lượng. Raw input phải bị loại khỏi durable queue,
DLQ, log và backup; broker vẫn có thể page message nonpersistent như đã nêu ở mục 4.

## 8. Bất biến do DB và dịch vụ thực thi

[PostgreSQL không dùng CHECK để kiểm tra dữ liệu bảng khác](https://www.postgresql.org/docs/current/ddl-constraints.html).
Vì vậy DDL không được trình bày như hệ thống phân quyền hoặc luồng nghiệp vụ đã hoàn chỉnh.

| Yêu cầu | DDL bootstrap bảo đảm | Dịch vụ / kiểm thử tích hợp phải bảo đảm |
| --- | --- | --- |
| BR01 tìm không ảnh | Embedding text có `image_id` NULL hợp lệ | Không bắt ảnh truy vấn; không embedding bằng chứng riêng tư |
| BR02 ba nhánh giữ | CHECK exactly-one + FK người/điểm | Phản ánh người/nơi thực tế, kiểm tra quyền ghi; DTO đúng nhánh |
| BR03 từ 0 đến 3 câu | Slot 1..3 + PK theo món/claim | Chụp toàn bộ bộ câu hỏi nhất quán; không chặn claim không câu hỏi |
| BR04 approved mới chat | FK claim/status approved, chat duy nhất | Xác thực từng read/send/connect, đúng hai bên; snapshot bất biến |
| BR05 chờ không chuyển giữ | Trạng thái intake tách khỏi items | Không update nơi giữ khi pending/rejected; stale check lúc nhận |
| BR06 điểm xác minh trả | FK sự kiện/actor và một event returned | Phân công điểm còn hiệu lực, xác minh trực tiếp, ghi nguyên tử |
| Không trả hai lần | Partial unique index event returned/item | Lock item; lifecycle + event + request + idempotency chung transaction |
| Ảnh an toàn | FK đối tượng, shape trạng thái/provenance | .NET kiểm byte/quyền/lease; Python kiểm MIME/pixel và xử lý ảnh; .NET kiểm review/version/public/cleanup |
| Chat bền vững | Nội dung + unique mã gửi lại | Serialize theo chat trước cấp sequence; commit rồi publish; quyền reconnect |
| Không vector cũ | FK nguồn, 2048 chiều, identity duy nhất ở bảng legacy; chưa có watermark/outbox đích | Python kiểm vector/phiên bản/tombstone trước ghi; .NET kiểm receipt, eligibility/source hiện tại trước mỗi DTO |
| Phân quyền | FK xác nhận các ID tồn tại | Không đọc trực tiếp DB từ client; không dùng ID, FK hoặc ẩn nút thay quyền |

Không áp dụng RLS trong DDL nền. Đích cấp role `.NET` chỉ ở `findie`, role Python chỉ ở
`findie_search`, không quyền chéo DB; role migration riêng, quyền ứng dụng tối thiểu, không
cấp `DROP` hoặc quản lý role. Cần cấu hình/kiểm thử ACL ở migration, SQL cũ chưa bảo đảm.
Các endpoint không cho sửa trực tiếp FK, version, trạng thái review hay actor. Phiên bị vô hiệu
hóa và quyền nhân viên phải được kiểm tra lại phía máy chủ, không chỉ đọc claim cũ từ token.

## 9. Chỉ mục, xóa và vận hành

Các chỉ mục B-tree bootstrap hỗ trợ danh sách public, bài của người đăng/người giữ, hàng
đợi claim/intake, lịch sử chat/sự kiện, việc đến hạn/lease hết hạn và scope vector legacy.
Search store đích cần chỉ mục phiên bản/nguồn/bộ lọc và GIN FTS của riêng nó qua migration.
Không tạo index cho mọi cột. Địa điểm tìm kiếm bắt đầu bằng chuỗi khu vực đã chuẩn hóa phía API;
chưa thêm PostGIS hoặc taxonomy địa giới khi sản phẩm chưa cần. Đo truy vấn thực tế trước khi
thêm chỉ mục hay bộ lọc địa lý khác.

Tất cả FK nghiệp vụ `ON DELETE RESTRICT` tránh xóa dây chuyền chat/bằng chứng/lịch sử. Vô hiệu
hóa tài khoản bằng `disabled_at`, điểm bằng `active = false`, thu hồi phân công bằng `revoked_at`,
gỡ bài bằng publication hidden, gỡ ảnh bằng retired. Đây không thay thế quyền được xóa dữ liệu:
trước dữ liệu thật phải chốt thời hạn lưu và quy trình xóa/ẩn danh đồng bộ DB, vector, R2 và backup.
Snapshot câu hỏi/bằng chứng/chat cần lịch xóa riêng; không giữ vô thời hạn chỉ vì đã dùng RESTRICT.
Message và DLQ RabbitMQ cũng có thể chứa ảnh riêng tư; chính sách xóa/retention phải bao phủ
cả broker, không chỉ DB/R2. Điều này chỉ cho phép output hoặc dữ liệu chỉ mục phù hợp;
original tuyệt đối không vào body DLQ/backup/log. Message cũ không được hồi sinh ảnh đã gỡ.

Backup PostgreSQL phải bao phủ cả hai database, outbox và watermark; nó không tự sao lưu R2.
Khôi phục search store có thể dùng rebuild từ snapshot được .NET cho phép, giữ thứ tự phiên
bản/tombstone và kiểm tra quyền hiện tại; không chép lại vector cũ để phục hồi nội dung đã gỡ.
Kế hoạch khôi phục phải kiểm chứng tham chiếu khóa, đối tượng thực tế và cấu hình bí mật; phục hồi DB cũ có thể
tham chiếu đối tượng đã bị xóa. Không ghi nội dung ảnh, token, tin nhắn hay câu trả lời vào log.

Ảnh truy vấn chỉ ở bộ nhớ ứng dụng trong request; không tệp tạm, R2 hoặc lịch sử tìm kiếm.
Bỏ bytes sau hoàn tất/lỗi/deadline; vector truy vấn không lưu trong search store. Raw query
phải theo transport ảnh nonpersistent/TTL/no body DLQ, broker vẫn có thể page xuống đĩa;
không cam kết forensic chỉ RAM hoặc xóa tức thì. Truy vấn text/output và chỉ mục có chính
sách transport/retention riêng; không tận dụng bảng ảnh bài đăng để lưu ngầm query.

## 10. DDL, kiểm chứng và việc cần chốt

`database-schema.sql` là DDL **bootstrap trước hybrid, cho database trống** có pgvector,
không phải schema đích hoặc migration sản xuất. Chạy một lần bằng `psql -v ON_ERROR_STOP=1 -f docs/database/database-schema.sql`
trên database kiểm thử; không chạy lên database đang có dữ liệu. DDL không seed người dùng,
điểm hay phân quyền, không cấu hình R2, không triển khai API/worker và không chứng minh chất lượng AI.
Trước triển khai hybrid phải thực hiện kế hoạch migration tối thiểu:

1. Tạo `findie_search` trên cùng instance; role Python chỉ tại đây, role .NET chỉ tại
   `findie`; bật extension/chốt phiên bản psycopg 3/pgvector và cấu hình TLS/ACL.
2. Tạo lược đồ search projection/vector/FTS-GIN/watermark theo mục 7.1, ID tham chiếu logic
   không FK xuyên DB. Chuyển hoặc tạo lại `item_embeddings` legacy từ nguồn công khai/ảnh
   sạch đã duyệt; loại FK phụ thuộc DB nghiệp vụ và không để .NET tiếp tục ghi/truy vấn vector.
3. Bổ sung outbox bền vững chứa full snapshot/manifest/tombstone và loại upsert/remove,
   ánh xạ `document_version`/source version/hash và idempotency. Ghi outbox cùng transaction
   mọi thay đổi ảnh hưởng tìm kiếm. Không giả định `ai_jobs` cũ hoặc `row_version` tự đáp ứng.
4. Thay original FK bắt buộc bằng một `processed_object_id` hiện hành mỗi ảnh, dùng kind
   `processed` và metadata/hash output. Không đổi nghĩa cột original thành output. Bỏ
   prefix original/temporary; cập nhật retention và luồng tạm thay `ai_jobs.redact_image`
   phát lại từ original. Index outbox bền vững chỉ dùng nguồn output đã lưu/được duyệt.
   Nếu có original cũ, kiểm kê tham chiếu, gỡ quyền và lập cleanup có kiểm soát; không tự
   xóa object/dữ liệu trong lần sửa tài liệu này.
5. Cập nhật EF Core/migration, DDL, ERD, từ điển và bộ kiểm tra theo schema đích; thử nâng
   cấp/rollback/rebuild trên DB dùng một lần, đối soát nguồn/chỉ mục và bảo toàn tombstone.
6. Kiểm thử commit độc lập, replay/crash/lease, ACL cấm chéo DB, message đảo thứ tự và
   snapshot xung đột, hide/delete trong lúc embedding, index lag/refill hữu hạn. Đo FTS tiếng
   Việt và Hit@10/Recall@50 theo mục 5.3 kiến trúc, chỉ công bố kết quả thực đo. Kiểm cả
   nhánh có/không nhạy cảm đều encode output, model lỗi không ghi R2, raw không log/DLQ/
   backup, query không R2, crash/deadline yêu cầu tải lại và không có API original.

Bộ tự kiểm cần chạy trên database dùng một lần: thêm dữ liệu hợp lệ; xác nhận lỗi với hai nơi
cùng giữ, câu hỏi slot 4/trùng slot, hội thoại cho pending/rejected, ảnh ready chưa review,
vector sai chiều, liên kết ảnh/yêu cầu sai món, hai lần return và gửi lại tin cùng mã. Tình huống
0 câu hỏi/claim approved/chat hợp lệ phải thành công. Kiểm thử ứng dụng còn phải bao phủ quyền
truy cập, hai thao tác bàn giao đồng thời, thứ tự commit tin nhắn, lease bị giành lại, kết quả AI
cũ, R2 mất kết nối và race giữa dọn/gắn tệp. Kiểm thử RabbitMQ cần bao phủ message trùng,
confirm không xác định/crash, mất kết nối/khôi phục, ACK sau commit, lỗi poison/DLQ và retry
hữu hạn; kiểm upload phải chứng minh .NET không giải mã, input không ghi R2 và `reserved`
chỉ được tạo cho output Python hợp lệ. SQL bootstrap không thay thế các kiểm thử đó.

Kiểm chứng lịch sử của snapshot bootstrap: DDL và `database-check.sql` trên PostgreSQL 17
với pgvector trong container tạm tạo đủ 16 bảng, chấp nhận claim không câu hỏi/chat đã duyệt/vector 2048 chiều và từ chối
15 trường hợp dữ liệu vi phạm. Chạy lại bằng `psql -v ON_ERROR_STOP=1 -f docs/database/database-check.sql`
sau DDL; script rollback toàn bộ dữ liệu thử. Đây là kiểm tra cấu trúc DB, chưa phải kiểm thử
phân quyền, giao dịch nghiệp vụ của .NET hoặc kết nối R2 thực tế.
Lần sửa ngày 2026-10-23 chỉ cập nhật tài liệu; không chạy lại SQL, không đổi DDL hoặc triển
khai RabbitMQ. Khi triển khai phải rà soát mapping EF Core/migration thực tế và kiểm thử
dispatcher/consumer/search store; chưa chạy migration, kiểm thử hybrid hoặc đo độ chính xác.
Không mặc định sổ job hiện tại đã có outbox snapshot/tombstone chạy được.

Các quyết định chưa chốt, không được âm thầm coi là đã có:

1. Quyền đọc khi chưa đăng nhập, cấp/thu hồi nhân viên và chính sách thời hạn phiên; provider hiện chỉ Google.
2. Ai tạo câu hỏi, có bắt trả lời, bằng chứng trực tiếp và ai được duyệt bản che ảnh.
3. Nhiều claim cùng approved, rút/thu hồi, request lỗi thời và quyền chat sau chuyển nơi/trả đồ.
4. Đồng ý trước khi nhận thực tế và quyền xác nhận trao trả ở nơi ngoài hệ thống.
5. Giới hạn upload/pixel, quy tắc vùng cần che, thời hạn lưu/xóa, sửa/gỡ và tranh chấp.
6. Revision mô hình/profile cụ thể, chất lượng tiếng Việt/ảnh đã che, phần cứng, tốc độ và chi phí.
7. Phiên bản RabbitMQ/thư viện, hợp đồng message, byte/header/queue/prefetch, TTL/DLQ/ACL,
   heartbeat/reconnect, lease/deadline, publisher confirm/routing và retry transport hữu hạn.
8. Mapping lược đồ/migration hai DB, outbox/document version/watermark, đối soát/rebuild;
   cấu hình FTS tiếng Việt, profile và ngưỡng/mục tiêu đo theo bảng chuẩn trong kiến trúc.

Thiết kế hiện tại cho phép hoàn thiện những quyết định này bằng chính sách và migration có
chủ đích; chưa tuyên bố các chính sách đề xuất đã được nhóm sản phẩm phê duyệt.
