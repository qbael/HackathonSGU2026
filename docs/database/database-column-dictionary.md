# Mô tả các cột trong cơ sở dữ liệu Findie

**Phiên bản:** 1.4.0 · **Ngày:** 2026-10-23 · **Trạng thái:** từ điển snapshot bootstrap; chưa di trú hybrid/processed-only.

**Runtime ngày 24/10/2026 đã khác snapshot này:** 22 bảng ứng dụng .NET với Google Identity/processed-only/outbox và kho `findie_search` riêng. Nguồn cột/ràng buộc runtime là EF migrations và `services/ai/db/migrations`; xem [thiết kế hiện tại](database-design.md). Danh sách bên dưới chỉ dùng đối chiếu lịch sử.

Tài liệu mô tả đầy đủ **164 cột của 16 bảng**, theo [DDL bootstrap hiện tại](database-schema.sql).
Xem thêm [thiết kế cơ sở dữ liệu](database-design.md) và [ERD draw.io](findie-erd.drawio).

SQL/ERD và danh sách cột này là snapshot **trước hybrid search**, chưa phải schema đích.
Trong đích, hai logical database nằm trên cùng PostgreSQL instance: `findie` chỉ .NET cho
nghiệp vụ/R2 metadata/job/outbox; `findie_search` chỉ Python cho embedding, bản chiếu công
khai, FTS và hybrid ranking. Python không đọc DB nghiệp vụ/R2; .NET không tạo/ghi/truy vấn
vector. `item_embeddings` có FK nghiệp vụ bên dưới là bảng chuyển tiếp cần di trú hoặc
tạo lại, không phải quyền để Python truy cập DB nghiệp vụ.

**Chính sách 1.4.0:** ảnh gốc đầu vào và ảnh truy vấn không lưu R2/DB/job/outbox/log/DLQ/
backup; chỉ ở RAM ứng dụng trong request có deadline. Python che/mờ nếu nhận diện nhạy cảm,
hoặc vẫn chuẩn hóa/loại EXIF/encode mới nếu không nhạy cảm; chỉ output hợp lệ mới được .NET
lưu R2 riêng tư, chờ người có quyền duyệt. `original_object_id` NOT NULL và kind `original`
trong snapshot này **không tương thích** chính sách đích, phải migration sang một
`processed_object_id`/kind `processed`, không được diễn giải cột original thành output.

Các trường logic đích, outbox snapshot/tombstone và ánh xạ document/source version cần
migration được mô tả ở mục 7/10 [thiết kế DB](database-design.md); chưa thêm cột/bảng vào
SQL trong lần sửa này. Bảng profile/mục tiêu độ chính xác chỉ giữ tại mục 5.3
[kiến trúc hệ thống](../architecture/system-architecture.md), mọi mục tiêu hiện chưa đo.

Quy ước: **PK** = khóa chính, **FK** = khóa ngoại, **UQ** = duy nhất. Cột **NULL = Có** có thể để trống, nhưng một số trạng thái vẫn yêu cầu phải có giá trị. Các thời điểm `timestamptz` được ứng dụng xử lý theo UTC và hiển thị theo `Asia/Ho_Chi_Minh`.

## 1. `app_users` — Tài khoản người dùng

Lưu danh tính ứng dụng, ánh xạ với nhà cung cấp đăng nhập OIDC.

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `id` | `uuid` | Không | **PK**. Mã người dùng do backend sinh. |
| `auth_issuer` | `text` | Không | Định danh nhà cung cấp OIDC đã xác thực người dùng. |
| `auth_subject` | `text` | Không | Định danh người dùng trong phạm vi `auth_issuer`. |
| `display_name` | `text` | Không | Tên hiển thị, dài 1–120 ký tự sau khi bỏ khoảng trắng đầu/cuối. |
| `disabled_at` | `timestamptz` | Có | Thời điểm tài khoản bị vô hiệu hóa; NULL nếu chưa vô hiệu hóa. |
| `created_at` | `timestamptz` | Không | Thời điểm tạo tài khoản; mặc định `now()`. |

**Ràng buộc:** cặp `(auth_issuer, auth_subject)` duy nhất. Bảng không lưu mật khẩu hoặc token đăng nhập.

## 2. `reception_points` — Điểm tiếp nhận

Lưu các điểm tiếp nhận được hệ thống quản lý.

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `id` | `uuid` | Không | **PK**. Mã điểm tiếp nhận. |
| `name` | `text` | Không | Tên điểm tiếp nhận, không được rỗng. |
| `public_address` | `text` | Không | Địa chỉ công khai để người dùng đến gửi hoặc nhận đồ. |
| `directions` | `text` | Có | Hướng dẫn đường đi hoặc cách tìm đúng quầy tiếp nhận. |
| `active` | `boolean` | Không | Điểm còn hoạt động hay không; mặc định `true`. |
| `created_at` | `timestamptz` | Không | Thời điểm tạo bản ghi; mặc định `now()`. |

Nơi giữ ngoài hệ thống được lưu trong `items`, không tạo thành điểm tiếp nhận ở bảng này.

## 3. `point_staff` — Phân công nhân viên tại điểm

Xác định người dùng nào có quyền tiếp nhận hoặc trao trả tại một điểm cụ thể.

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `point_id` | `uuid` | Không | Thành phần **PK**, **FK → `reception_points.id`**. Điểm được phân công. |
| `user_id` | `uuid` | Không | Thành phần **PK**, **FK → `app_users.id`**. Nhân viên được phân công. |
| `can_receive` | `boolean` | Không | Có quyền xác nhận đã nhận đồ thực tế; mặc định `false`. |
| `can_return` | `boolean` | Không | Có quyền xác nhận trao trả đồ; mặc định `false`. |
| `assigned_at` | `timestamptz` | Không | Thời điểm phân công; mặc định `now()`. |
| `revoked_at` | `timestamptz` | Có | Thời điểm thu hồi phân công; NULL nếu chưa thu hồi. |

**Ràng buộc:** PK ghép `(point_id, user_id)`; ít nhất một trong hai quyền phải là `true`. Quyền chỉ có hiệu lực tại điểm được chỉ định.

## 4. `items` — Món đồ và bài đăng

Lưu thông tin công khai, nơi nhặt, nơi giữ và trạng thái của món đồ.

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `id` | `uuid` | Không | **PK**. Mã món đồ. |
| `posted_by` | `uuid` | Không | **FK → `app_users.id`**. Người tạo bài đăng. |
| `title` | `text` | Không | Tiêu đề bài đăng, dài 1–200 ký tự. |
| `public_description` | `text` | Không | Mô tả công khai dùng để hiển thị và tạo vector văn bản; dài 1–5.000 ký tự. |
| `found_area` | `text` | Không | Khu vực nhặt được đồ; không được rỗng. |
| `found_time_precision` | `text` | Không | Độ chính xác thời gian: `unknown`, `date`, `range` hoặc `exact`. |
| `found_on` | `date` | Có | Ngày nhặt theo lịch địa phương khi chỉ biết ngày. |
| `found_from` | `timestamptz` | Có | Thời điểm chính xác hoặc đầu khoảng thời gian nhặt ước lượng. |
| `found_until` | `timestamptz` | Có | Cuối khoảng thời gian nhặt ước lượng. |
| `found_timezone` | `text` | Không | Múi giờ của dữ liệu thời gian được nhập; mặc định `Asia/Ho_Chi_Minh`. |
| `custody_kind` | `text` | Không | Loại nơi giữ: `person`, `point` hoặc `external`. |
| `holder_user_id` | `uuid` | Có | **FK → `app_users.id`**. Người đang giữ, bắt buộc khi `custody_kind = person`. |
| `holder_point_id` | `uuid` | Có | **FK → `reception_points.id`**. Điểm đang giữ, bắt buộc khi `custody_kind = point`. |
| `external_name` | `text` | Có | Tên nơi giữ ngoài hệ thống; bắt buộc với nhánh `external`. |
| `external_public_address` | `text` | Có | Địa chỉ công khai của nơi ngoài hệ thống; bắt buộc với nhánh `external`. |
| `external_instructions` | `text` | Có | Hướng dẫn liên hệ hoặc nhận đồ tại nơi ngoài hệ thống. |
| `lifecycle` | `text` | Không | Vòng đời món đồ: `active`, `returned` hoặc `deleted` (xóa mềm bài đăng); mặc định `active`. |
| `publication_state` | `text` | Không | Trạng thái hiển thị: `draft`, `published` hoặc `hidden`; mặc định `draft`. |
| `content_version` | `bigint` | Không | Phiên bản nội dung văn bản dùng tạo vector; mặc định `1`, phải lớn hơn 0. |
| `custody_version` | `bigint` | Không | Phiên bản nơi giữ/bàn giao, dùng phát hiện thao tác dựa trên trạng thái cũ; mặc định `1`. |
| `row_version` | `bigint` | Không | Phiên bản bản ghi để kiểm soát cập nhật đồng thời; mặc định `1`. |
| `created_at` | `timestamptz` | Không | Thời điểm tạo bài đăng; mặc định `now()`. |
| `updated_at` | `timestamptz` | Không | Thời điểm cập nhật gần nhất; mặc định ban đầu là `now()`. |

**Ràng buộc thời gian:**

- `unknown`: cả ba cột thời gian đều NULL.
- `date`: chỉ `found_on` có giá trị.
- `exact`: chỉ `found_from` có giá trị.
- `range`: có `found_from` và `found_until`, với đầu khoảng không lớn hơn cuối khoảng.

**Ràng buộc nơi giữ:** chỉ một nhánh cá nhân/điểm/ngoài hệ thống được có dữ liệu. Khi đã trả, các cột nơi giữ thể hiện nơi giữ cuối cùng trước khi trả.

`updated_at` và các cột phiên bản do backend cập nhật; DDL chưa có trigger tự động.

## 5. `stored_objects` — Đối tượng ảnh trên Cloudflare R2

Snapshot lưu metadata/vòng đời R2 và còn có loại original/sanitized cũ. Trong đích 1.4.0,
.NET chỉ dự trữ/ghi processed output **sau** kết quả Python hợp lệ; không có object gốc.
.NET kiểm quyền/byte/hash; Python giải mã/kiểm MIME/pixel/nhạy cảm và encode output.

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `id` | `uuid` | Không | **PK**. Mã đối tượng lưu trữ. |
| `owner_user_id` | `uuid` | Không | **FK → `app_users.id`**. Người dùng sở hữu đối tượng trong ứng dụng. |
| `bucket` | `text` | Không | Tên bucket R2 riêng tư. |
| `object_key` | `text` | Không | Khóa đối tượng do backend tạo trong bucket; không phải URL công khai. |
| `object_kind` | `text` | Không | Snapshot chỉ cho `original` hoặc `sanitized`; không phải thiết kế đích. Cần migration kind `processed`, không lưu original. |
| `object_state` | `text` | Không | `reserved`, `validated`, `delete_pending`, `deleted`; mặc định `reserved`. Đích chỉ reserve output đã được Python xử lý trước upload R2. |
| `sha256` | `text` | Có | SHA-256 của byte ảnh, gồm 64 ký tự hexadecimal viết thường. |
| `content_type` | `text` | Có | MIME thực do Python kiểm tra: JPEG, PNG hoặc WebP; không lấy MIME client khai làm metadata đã kiểm. |
| `byte_size` | `bigint` | Có | Dung lượng ảnh tính bằng byte, phải lớn hơn 0. |
| `width` | `integer` | Có | Chiều rộng ảnh do Python xác nhận sau giải mã, tính bằng pixel. |
| `height` | `integer` | Có | Chiều cao ảnh do Python xác nhận sau giải mã, tính bằng pixel. |
| `expires_at` | `timestamptz` | Có | Hạn dự trữ hoặc mốc đủ điều kiện dọn đối tượng không còn sử dụng. |
| `cleanup_next_at` | `timestamptz` | Có | Thời điểm được phép thử dọn/xóa đối tượng tiếp theo. |
| `cleanup_attempts` | `integer` | Không | Số lần đã thử dọn/xóa; mặc định `0`, không được âm. |
| `last_error_code` | `text` | Có | Mã lỗi gần nhất của thao tác lưu trữ hoặc dọn tệp. |
| `created_at` | `timestamptz` | Không | Thời điểm dự trữ bản ghi đối tượng; mặc định `now()`. |
| `validated_at` | `timestamptz` | Có | Thời điểm .NET xác nhận upload thành công và metadata/hash output hợp lệ từ Python; không xác nhận lưu input gốc. |
| `deleted_at` | `timestamptz` | Có | Thời điểm xác nhận đối tượng đã được xóa khỏi R2. |

**Ràng buộc:** `(bucket, object_key)` duy nhất. `reserved` phải có hạn hết hiệu lực; `validated` phải có đầy đủ hash, MIME, dung lượng, kích thước và thời điểm kiểm tra. `deleted_at` có giá trị khi và chỉ khi trạng thái là `deleted`.

`validated` xác nhận output đã được Python kiểm/xử lý và lưu thành công, chưa đồng nghĩa
được duyệt công khai. Đích chưa có output hợp lệ thì không tạo `reserved` hoặc ghi R2;
không có endpoint xem/download original. Hạn `expires_at` không cho phép dọn output còn
được ảnh/job chỉ mục hợp lệ tham chiếu. DDL chưa có kind `processed` và không tự kiểm bytes;
cần migration, không suy diễn rằng schema cũ đã đáp ứng luồng mới.

## 6. `item_images` — Ảnh gắn với món đồ

Snapshot liên kết original và sanitized cũ; FK gốc bắt buộc dưới đây không tương thích
1.4.0. Thiết kế đích chỉ có một processed object hiện hành mỗi ảnh và trạng thái duyệt.

EF runtime bổ sung `original_embedding` (`jsonb`, nullable) bằng migration
`AddOriginalImageEmbedding`: lưu vector từ ảnh upload trước khi che, kèm `modelId`,
`modelRevision`, `dimensions` và `sourceSha256` của ảnh upload; không lưu bytes ảnh gốc.
Vector này chỉ phục vụ lập chỉ mục nội bộ, không xuất hiện trong DTO công khai,
và bị xóa khi từ chối ảnh, gỡ ảnh hoặc xóa bài. Bản ghi legacy có giá trị NULL tiếp tục dùng
ảnh đã che khi lập chỉ mục; đổi model của vector gốc cần upload lại ảnh.

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `id` | `uuid` | Không | **PK**. Mã ảnh nghiệp vụ. |
| `item_id` | `uuid` | Không | **FK → `items.id`**. Món đồ sở hữu ảnh. |
| `position` | `smallint` | Không | Thứ tự hiển thị ảnh, phải lớn hơn 0. |
| `original_object_id` | `uuid` | Không | **FK → `stored_objects.id`**, **UQ**. Original legacy, NOT NULL thật trong snapshot; phải bỏ/thay FK khi migration, không đổi nghĩa thành output. |
| `sanitized_object_id` | `uuid` | Có | **FK → `stored_objects.id`**, **UQ**. Output đã xử lý legacy; cần migration về processed object hiện hành cùng việc loại FK original. |
| `content_version` | `bigint` | Không | Phiên bản ảnh/quy trình che; mặc định `1`, tăng khi thay nguồn hoặc xử lý lại. |
| `processing_state` | `text` | Không | `pending`, `processing`, `needs_review`, `ready`, `failed`, `rejected`; mặc định `pending`. `processing` gồm đã dispatch/đang chờ kết quả Python, chưa chứng minh worker đang suy luận. |
| `review_state` | `text` | Không | Trạng thái duyệt: `pending`, `approved`, `rejected`; mặc định `pending`. |
| `sensitive_regions` | `jsonb` | Có | Mảng vùng nhạy cảm gồm loại vùng và tọa độ; không dùng để lưu toàn bộ nội dung OCR. |
| `redaction_model_id` | `text` | Có | Tên mô hình đã đề xuất vùng cần che. |
| `redaction_model_revision` | `text` | Có | Revision cụ thể của mô hình dùng xử lý ảnh. |
| `redaction_profile` | `text` | Có | Định danh cấu hình prompt, nhận diện vùng và xử lý OpenCV. |
| `reviewed_by` | `uuid` | Có | **FK → `app_users.id`**. Người đã duyệt hoặc từ chối bản ảnh. |
| `reviewed_at` | `timestamptz` | Có | Thời điểm đưa ra quyết định duyệt. |
| `failure_code` | `text` | Có | Mã lỗi của quá trình xử lý ảnh. |
| `retired_at` | `timestamptz` | Có | Thời điểm gỡ ảnh khỏi sử dụng/hiển thị; chưa có nghĩa ảnh đã được xóa khỏi R2. |
| `created_at` | `timestamptz` | Không | Thời điểm tạo bản ghi ảnh; mặc định `now()`. |

**Ràng buộc chính của snapshot:**

- Ảnh gốc và bản xử lý phải là hai đối tượng khác nhau.
- `(item_id, position)` duy nhất đối với ảnh chưa bị gỡ.
- `(id, item_id)` duy nhất để hỗ trợ FK ghép từ các bảng AI.
- Khi đã duyệt/từ chối, phải có người và thời điểm duyệt.
- `ready` yêu cầu `approved`, bản xử lý và thông tin mô hình/profile.

Không áp dụng nguyên trạng các FK/kind trên cho luồng mới. Cần che thêm thì xử lý lại
output hiện có hoặc tải lại original; không có original đã lưu để khôi phục hay bỏ mờ.

## 7. `verification_questions` — Câu hỏi xác minh hiện tại

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `item_id` | `uuid` | Không | Thành phần **PK**, **FK → `items.id`**. Món đồ được đặt câu hỏi. |
| `slot` | `smallint` | Không | Thành phần **PK**. Vị trí câu hỏi, chỉ nhận giá trị 1–3. |
| `question_text` | `text` | Không | Nội dung câu hỏi xác minh, dài 1–500 ký tự. |

**Ràng buộc:** PK ghép `(item_id, slot)` giới hạn tối đa ba câu hỏi mỗi món. Không có bản ghi tương ứng với không đặt câu hỏi.

## 8. `claims` — Yêu cầu nhận đồ

Lưu yêu cầu của người tìm và quyết định của người có quyền xét duyệt.

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `id` | `uuid` | Không | **PK**. Mã yêu cầu nhận đồ. |
| `item_id` | `uuid` | Không | **FK → `items.id`**. Món đồ được yêu cầu nhận. |
| `claimant_user_id` | `uuid` | Không | **FK → `app_users.id`**. Người gửi yêu cầu. |
| `reviewer_user_id` | `uuid` | Không | **FK → `app_users.id`**. Bản chụp người có quyền duyệt tại thời điểm gửi. |
| `source_custody_version` | `bigint` | Không | Phiên bản nơi giữ lúc gửi yêu cầu, dùng phát hiện yêu cầu đã lỗi thời. |
| `status` | `text` | Không | `pending`, `approved` hoặc `rejected`; mặc định `pending`. |
| `decided_by` | `uuid` | Có | **FK → `app_users.id`**. Người đã đưa ra quyết định. |
| `decided_at` | `timestamptz` | Có | Thời điểm duyệt hoặc từ chối. |
| `decision_note` | `text` | Có | Ghi chú quyết định, tối đa 2.000 ký tự. |
| `created_at` | `timestamptz` | Không | Thời điểm gửi yêu cầu; mặc định `now()`. |

**Ràng buộc:** người yêu cầu phải khác người duyệt. Khi không còn `pending`, `decided_by` phải bằng `reviewer_user_id` và có `decided_at`. Hai cặp `(id, item_id)` và `(id, status)` duy nhất để hỗ trợ các FK ghép.

## 9. `claim_answers` — Câu trả lời và bản chụp câu hỏi

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `claim_id` | `uuid` | Không | Thành phần **PK**, **FK → `claims.id`**. Yêu cầu chứa câu trả lời. |
| `slot` | `smallint` | Không | Thành phần **PK**. Vị trí câu hỏi đã chụp, từ 1–3. |
| `question_text_snapshot` | `text` | Không | Nội dung câu hỏi tại lúc gửi yêu cầu; dài 1–500 ký tự. |
| `answer_text` | `text` | Có | Câu trả lời riêng tư; nếu có phải dài 1–2.000 ký tự. |

**Ràng buộc:** PK ghép `(claim_id, slot)`. Không có FK đến `verification_questions`, nên sửa câu hỏi hiện tại không làm đổi bằng chứng đã gửi. Yêu cầu không có câu hỏi vẫn hợp lệ.

## 10. `conversations` — Hội thoại sau phê duyệt

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `claim_id` | `uuid` | Không | **PK**, thành phần **FK ghép**. Dùng mã yêu cầu làm mã hội thoại. |
| `approval_status` | `text` | Không | Luôn là `approved`, dùng kiểm tra yêu cầu đã được duyệt. |
| `created_at` | `timestamptz` | Không | Thời điểm mở hội thoại; mặc định `now()`. |

**Ràng buộc:** FK `(claim_id, approval_status) → claims(id, status)` chỉ cho tạo hội thoại với yêu cầu đã duyệt. Mỗi yêu cầu có tối đa một hội thoại; hai bên tham gia lấy từ người yêu cầu và người duyệt.

## 11. `messages` — Tin nhắn

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `id` | `uuid` | Không | **PK**. Mã tin nhắn. |
| `conversation_id` | `uuid` | Không | **FK → `conversations.claim_id`**. Hội thoại chứa tin nhắn. |
| `sender_user_id` | `uuid` | Không | **FK → `app_users.id`**. Người gửi, được backend xác định từ phiên đăng nhập. |
| `client_message_id` | `uuid` | Không | Mã phía client tạo để gửi lại an toàn khi lỗi mạng. |
| `message_sequence` | `bigint` | Không | Số tự sinh bằng IDENTITY, **UQ** trên toàn bảng; dùng làm con trỏ tải lịch sử. |
| `body` | `text` | Không | Nội dung tin nhắn, dài 1–4.000 ký tự. |
| `created_at` | `timestamptz` | Không | Thời điểm lưu tin; mặc định `now()`. |

**Ràng buộc:** `(conversation_id, sender_user_id, client_message_id)` duy nhất. `message_sequence` được cấp trên toàn bảng, không bắt đầu lại cho mỗi hội thoại; backend cần khóa hội thoại trước khi chèn để tránh con trỏ bỏ sót tin commit muộn.

## 12. `intake_requests` — Yêu cầu chuyển đồ vào điểm

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `id` | `uuid` | Không | **PK**. Mã yêu cầu tiếp nhận. |
| `item_id` | `uuid` | Không | **FK → `items.id`**. Món đồ dự định chuyển vào điểm. |
| `requested_by` | `uuid` | Không | **FK → `app_users.id`**. Người gửi yêu cầu chuyển đồ. |
| `target_point_id` | `uuid` | Không | **FK → `reception_points.id`**. Điểm được đề nghị tiếp nhận. |
| `source_custody_version` | `bigint` | Không | Phiên bản nơi giữ lúc tạo yêu cầu; phải lớn hơn 0. |
| `status` | `text` | Không | `pending`, `received`, `rejected`; mặc định `pending`. |
| `decided_by` | `uuid` | Có | **FK → `app_users.id`**. Nhân viên xác nhận tiếp nhận hoặc từ chối. |
| `decided_at` | `timestamptz` | Có | Thời điểm ghi nhận quyết định. |
| `decision_note` | `text` | Có | Ghi chú tiếp nhận hoặc lý do từ chối, tối đa 2.000 ký tự. |
| `created_at` | `timestamptz` | Không | Thời điểm tạo yêu cầu; mặc định `now()`. |

**Ràng buộc:** trạng thái khác `pending` phải có người và thời điểm quyết định. `(id, item_id)` duy nhất. Yêu cầu đang chờ không làm thay đổi nơi giữ; backend chỉ chuyển nơi giữ khi xác nhận đã nhận thực tế.

## 13. `custody_events` — Lịch sử nơi giữ và trao trả

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `id` | `uuid` | Không | **PK**. Mã sự kiện. |
| `item_id` | `uuid` | Không | **FK → `items.id`**. Món đồ liên quan. |
| `event_kind` | `text` | Không | Loại sự kiện: `registered`, `received` hoặc `returned`. |
| `custody_version` | `bigint` | Không | Phiên bản nơi giữ sau sự kiện, phải lớn hơn 0. |
| `actor_user_id` | `uuid` | Không | **FK → `app_users.id`**. Người thực hiện xác nhận nghiệp vụ. |
| `intake_request_id` | `uuid` | Có | **UQ**, thành phần **FK ghép** đến yêu cầu tiếp nhận cùng món; bắt buộc với `received`. |
| `claim_id` | `uuid` | Có | Thành phần **FK ghép** đến yêu cầu nhận cùng món; có thể để trống khi trả trực tiếp tại điểm. |
| `recipient_user_id` | `uuid` | Có | **FK → `app_users.id`**. Người nhận nếu có tài khoản trong hệ thống. |
| `from_custody` | `jsonb` | Có | Bản chụp nơi giữ trước sự kiện, gồm loại nơi giữ và thông tin công khai liên quan. |
| `to_custody` | `jsonb` | Có | Bản chụp nơi giữ sau sự kiện. |
| `verification_note` | `text` | Có | Ghi chú xác minh/bàn giao riêng tư, tối đa 2.000 ký tự. |
| `occurred_at` | `timestamptz` | Không | Thời điểm sự kiện thực tế diễn ra. |
| `recorded_at` | `timestamptz` | Không | Thời điểm hệ thống ghi nhận; mặc định `now()`. |

**Ràng buộc chính:**

- `(item_id, custody_version)` duy nhất.
- Mỗi món có tối đa một sự kiện `registered` và một sự kiện `returned`.
- `registered`: có nơi giữ đích, chưa có nơi giữ nguồn.
- `received`: có cả nguồn, đích và yêu cầu tiếp nhận.
- `returned`: có nơi giữ nguồn, nơi giữ đích NULL.
- FK ghép kèm `item_id` ngăn liên kết yêu cầu thuộc món khác.

## 14. `ai_jobs` — Tác vụ AI bền vững

Sổ job suy luận bootstrap do .NET sở hữu, lưu công việc xử lý ảnh/tạo vector, retry và lease.
Python nhận lệnh/trả kết quả qua RabbitMQ AMQP 0-9-1; không đọc bảng này hoặc DB nghiệp vụ.
`redact_image` hiện có là thiết kế legacy gắn ảnh/R2, không cung cấp khả năng phát lại
raw input trong đích 1.4.0. Xử lý original mới dùng request/reply tạm: retry chỉ khi bytes
còn RAM trong deadline, mất process/RAM thì yêu cầu tải lại. Original không nằm trong job.
Các cột hiện tại chưa có payload full snapshot/tombstone, document version hoặc đầy đủ
loại đồng bộ/xóa chỉ mục; không được coi bảng này là outbox đích đã hoàn tất. Cần migration
theo thiết kế DB; chưa thêm bảng/cột hoặc trạng thái `published` trong DDL lần này.

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `id` | `uuid` | Không | **PK**. Mã job giữ nguyên khi retry/phát lại, đưa vào message làm `job_id`. |
| `item_id` | `uuid` | Không | **FK → `items.id`**. Món đồ cần xử lý. |
| `image_id` | `uuid` | Có | Thành phần **FK ghép → `item_images(id, item_id)`**. Ảnh cần xử lý. |
| `job_kind` | `text` | Không | Snapshot cho `redact_image`, `embed_text`, `embed_image`; `redact_image` legacy không phải retry original bền vững trong đích 1.4.0. |
| `source_version` | `bigint` | Không | Phiên bản nội dung nguồn mà tác vụ xử lý. |
| `source_sha256` | `text` | Không | SHA-256 của dữ liệu đầu vào, dùng kiểm tra nguồn có thay đổi hay không. |
| `model_id` | `text` | Không | Tên mô hình được chỉ định cho tác vụ. |
| `model_revision` | `text` | Không | Revision cụ thể của trọng số/mô hình. |
| `processing_profile` | `text` | Không | Định danh cấu hình tiền xử lý, prompt và quy trình tương ứng. |
| `status` | `text` | Không | `pending`, `running`, `retry`, `succeeded`, `failed`, `obsolete`; mặc định `pending`. `running` gồm đã lease/đang phát lệnh/đang chờ kết quả, không xác nhận broker đã nhận. |
| `attempts` | `integer` | Không | Số attempt .NET đã cấp lease; mặc định `0`, không âm. Phát lại cùng lease do confirm không xác định không tăng lần thử. |
| `max_attempts` | `integer` | Không | Giới hạn số lần thử, phải lớn hơn 0. |
| `next_attempt_at` | `timestamptz` | Không | Thời điểm sớm nhất .NET được retry với backoff; mặc định `now()`. |
| `lease_token` | `uuid` | Có | Token attempt do .NET cấp, truyền qua lệnh/kết quả để loại kết quả từ lease cũ. |
| `lease_until` | `timestamptz` | Có | Deadline lease do .NET quản lý; hết hạn cho phép cấp attempt/token mới. |
| `last_error_code` | `text` | Có | Mã lỗi gần nhất; không lưu dữ liệu nhạy cảm của đầu vào. |
| `created_at` | `timestamptz` | Không | Thời điểm tạo tác vụ; mặc định `now()`. |
| `finished_at` | `timestamptz` | Có | Thời điểm kết thúc ở trạng thái `succeeded`, `failed` hoặc `obsolete`. |

**Ràng buộc chính:**

- `embed_text` phải có `image_id = NULL`; hai loại tác vụ ảnh phải có ảnh nguồn.
- `running` phải có cả `lease_token` và `lease_until`.
- Trạng thái kết thúc phải có `finished_at`; các trạng thái khác không có.
- Tác vụ duy nhất theo nguồn, phiên bản, loại việc, mô hình, revision và profile.
- .NET thực thi `max_attempts`, backoff/`next_attempt_at`, lease và phiên bản nguồn trước khi lưu.

.NET ghi job/outbox chỉ mục từ output đã lưu/được duyệt cùng transaction nghiệp vụ;
dispatcher lease rồi publish ngoài transaction
với publisher confirm và mandatory routing. Crash/confirm không xác định cho phép phát lại
cùng job/lease còn hạn; không hứa transaction nguyên tử DB–broker. Python trả cùng
job/correlation/lease/document/source/model; với `index.upsert`/`index.remove`, commit vector/
bản chiếu/FTS trong search store trước biên nhận, chỉ ACK lệnh sau result được confirmed/
routed. .NET kiểm biên nhận và commit job trong transaction riêng rồi ACK result, hoặc
chủ đích bỏ duplicate/stale. Hai commit Python/.NET không nguyên tử; bỏ receipt cũ không
tự xóa vector đã ghi. Message sai schema
hoặc poison vĩnh viễn của luồng chỉ mục bền vững vào DLQ có retention; không requeue vô hạn.
Raw input là ngoại lệ: ACK/drop ở lỗi kết thúc, không body DLQ/log/backup. Đây là yêu cầu triển khai, chưa có
dispatcher/consumer chạy được chỉ nhờ DDL.

Body ảnh là byte AMQP nhị phân (giới hạn đề xuất 10 MiB mỗi message), metadata JSON nhỏ
trong header; văn bản/receipt/ứng viên dùng JSON, Python lưu vector trực tiếp. Không base64
hoặc URL tùy ý. Queue raw input do Python khai báo, tên broker sinh, binding `image.redact`/`search.hybrid.image`, non-durable/exclusive/auto-delete, message
nonpersistent/TTL hữu hạn và không raw-body DLQ; kể cả ảnh truy vấn không đi durable queue.
Broker có thể page nonpersistent bytes xuống đĩa; TTL là vòng đời logic, không bảo đảm
forensic chỉ RAM hoặc xóa tức thì. Output/chỉ mục có thể durable với ACL/TLS/retention riêng.
Hai service
giữ kết nối broker riêng lâu dài với heartbeat/reconnect; FastAPI chỉ health/vận hành.
`item_id` bắt buộc, nên bảng này không lưu truy vấn tìm kiếm tạm không gắn món đồ.

## 15. `item_embeddings` — Vector tìm kiếm legacy trong snapshot bootstrap

Lưu vector của mô tả công khai hoặc bản ảnh an toàn đã duyệt trong DDL cũ. Các FK dưới đây
có thật trong snapshot DB nghiệp vụ; kiến trúc hybrid đích cần chuyển/tạo lại dữ liệu tại
`findie_search` với ID tham chiếu logic, **không FK xuyên database**. Bảng này không thể
được cấp cho Python để né ranh giới DB nghiệp vụ; cần migration trước triển khai.

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `id` | `uuid` | Không | **PK**. Mã bản ghi vector. |
| `item_id` | `uuid` | Không | **FK → `items.id`**. Món đồ được vector biểu diễn. |
| `image_id` | `uuid` | Có | Thành phần **FK ghép → `item_images(id, item_id)`**. Ảnh được biểu diễn nếu là vector ảnh. |
| `modality` | `text` | Không | Loại nguồn: `text` hoặc `image`. |
| `source_version` | `bigint` | Không | Phiên bản mô tả hoặc ảnh dùng tạo vector. |
| `source_sha256` | `text` | Không | SHA-256 payload văn bản công khai theo hợp đồng đầu vào hoặc byte ảnh đã che được duyệt; chuẩn hóa AI thuộc Python/profile. |
| `model_id` | `text` | Không | Tên mô hình tạo vector. |
| `model_revision` | `text` | Không | Revision mô hình đã dùng để tạo vector. |
| `processing_profile` | `text` | Không | Định danh cấu hình tiền xử lý và prompt của vector. |
| `dimensions` | `integer` | Không | Số chiều vector; mặc định và bắt buộc bằng `2048`. |
| `embedding` | `vector(2048)` | Không | Giá trị vector được pgvector lưu để tính khoảng cách tương đồng. |
| `created_at` | `timestamptz` | Không | Thời điểm tạo bản ghi vector; mặc định `now()`. |

**Ràng buộc:** vector `text` không gắn ảnh; vector `image` phải gắn ảnh thuộc đúng món. Mỗi nguồn chỉ giữ một vector cho mỗi bộ `(model_id, model_revision, processing_profile)`; phiên bản mới cập nhật vector tương ứng.

Trong đích, Python tạo/kiểm/chuẩn hóa/upsert vector, lập FTS và hybrid search tại kho riêng;
.NET kiểm receipt/job và điều kiện nguồn/quyền hiện tại trước mỗi DTO. Python commit kho
tìm kiếm trước biên nhận; .NET hoàn tất job trong transaction độc lập. Chỉ mô tả công khai
và ảnh sạch đã duyệt đi vào chỉ mục; vector truy vấn tạm không được lưu ở đây hoặc search DB.

## 16. `idempotency_keys` — Chống lặp thao tác

Lưu kết quả thao tác đã thành công để client thử lại mà không tạo thêm tác động nghiệp vụ.

| Cột | Kiểu | NULL | Mô tả |
|---|---|---|---|
| `actor_user_id` | `uuid` | Không | Thành phần **PK**, **FK → `app_users.id`**. Người thực hiện thao tác. |
| `idempotency_key` | `uuid` | Không | Thành phần **PK**. Khóa ổn định được dùng lại khi thử lại cùng thao tác. |
| `operation` | `text` | Không | Tên thao tác, chẳng hạn tạo món hoặc xác nhận trao trả. |
| `request_sha256` | `text` | Không | Hash payload chuẩn hóa để phát hiện cùng khóa nhưng khác dữ liệu. |
| `resource_type` | `text` | Không | Loại tài nguyên kết quả: `item`, `image`, `claim`, `intake`, `custody_event`. |
| `resource_id` | `uuid` | Không | Mã tài nguyên kết quả; tham chiếu đa loại, có chủ đích không dùng FK. |
| `response_status` | `smallint` | Không | Mã HTTP thành công đã ghi nhận, giới hạn 200–299. |
| `created_at` | `timestamptz` | Không | Thời điểm lưu kết quả thao tác; mặc định `now()`. |

**Ràng buộc:** PK ghép `(actor_user_id, idempotency_key)`. Backend kiểm tra `operation` và hash khi dùng lại khóa, đồng thời kiểm tra lại quyền truy cập kết quả.

Tài liệu giữ đúng danh sách cột DDL bootstrap, chưa mô tả bằng cột giả một lược đồ hybrid
đã triển khai. Các kiểm tra phân quyền/chuyển trạng thái do .NET thực thi; migration search
store/outbox/FTS, ACL và kiểm thử đồng bộ hai database còn phải làm.
Migration ảnh phải thay FK original bắt buộc/kind cũ, bỏ prefix original/temporary và
cập nhật retention. Original legacy nếu từng tồn tại cần kiểm kê/cleanup có kiểm soát;
lần sửa tài liệu không xóa R2/dữ liệu và không thay một cột nào của snapshot 164 cột.
