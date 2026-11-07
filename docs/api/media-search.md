# API ảnh và tìm kiếm

Quy ước cookie, CSRF, lỗi và idempotency tại [API nghiệp vụ](recovery.md#quy-ước-chung).
Ảnh/tìm kiếm có giới hạn 20 request nặng/phút/tài khoản, vượt trả **429**.
Upload và truy vấn một ảnh nhận **body nhị phân**; tìm nhiều ảnh dùng
`multipart/form-data` tại `/api/search/images`. Không nhận base64,
URL ảnh hoặc đường dẫn file từ client. .NET đọc trực tiếp stream vào RAM tối đa **10 MiB/ảnh**,
không dùng `IFormFile` hoặc ghi tệp tạm. Python chịu trách nhiệm giải mã/kiểm ảnh thực.

Web chuẩn bị ảnh trước cả upload, tìm một ảnh và tìm nhiều ảnh: kiểm MIME/signature
JPEG/PNG/WebP, giới hạn file gốc 10 MiB, từ chối PNG/WebP động và ảnh vượt 10000 px
mỗi chiều hoặc 40 triệu pixel. Trình duyệt đọc hướng EXIF, tạo bản JPEG quality 0.92
trên nền trắng, thu cạnh dài về tối đa 1600 px, giữ tỷ lệ, không phóng lớn/cắt ảnh
hoặc làm nét/khử nhiễu. Nếu ảnh đã trong giới hạn 1600 px và bản JPEG không nhỏ hơn
file gốc thì gửi file gốc; ảnh cần thu nhỏ luôn gửi bản đã thu nhỏ. Cùng đối tượng
`File` dùng lại cùng bytes đã chuẩn bị khi retry upload để giữ idempotency.
Hợp đồng API trực tiếp không thay đổi; server luôn kiểm lại ảnh.
Nén JPEG có thể làm mất chi tiết chữ nhỏ; chưa có benchmark chứng minh tăng độ chính xác.

Phần .NET có adapter AMQP/R2; worker Python hỗ trợ text, che/chuẩn hóa ảnh và tìm ảnh native qua Ollama theo [hướng dẫn](../guides/ai-service.md). Cần cấu hình broker, private bucket và model/revision có capability phù hợp. Chưa có worker trả kết quả thì báo **503**,
không giả lập kết quả hoặc lưu original. Xem [cấu hình local](../guides/development.md).

## GET /api/items/{itemId}/images — trạng thái ảnh dành cho quản lý

Quyền: người quản lý nơi giữ hiện tại (person holder, external author, point canReceive).
Response **200** mảng `ImageResponse`, có cả ảnh đã gỡ để đối chiếu:

```json
{
  "id": "<uuid>",
  "itemId": "<uuid>",
  "position": 1,
  "contentVersion": 1,
  "processingState": "needs_review",
  "reviewState": "pending",
  "failureCode": null,
  "previewUrl": "/api/items/<itemId>/images/<id>/content"
}
```

`previewUrl` chỉ trỏ output đã lưu hợp lệ; null khi gỡ/không có output. Không trả
bucket/object key, original, OCR hoặc credential. Không có item **404**, thiếu quyền **403**.
Người xem thông thường lấy ảnh được duyệt từ `GET /api/items/{id}`.
Cache embedding ảnh gốc và OCR là dữ liệu nội bộ, không có trong DTO ảnh hoặc món đồ.

## POST /api/items/{itemId}/images?position=1 — xử lý và tải output

Quyền quản lý như trên, item còn active. Header:
`Content-Type: image/jpeg|image/png|image/webp`, `X-CSRF-TOKEN`, `Idempotency-Key`.
Query `position=1..3`, mặc định 1; mỗi tin có tối đa 3 ảnh chưa gỡ và mỗi vị trí
có tối đa một ảnh chưa gỡ. Ảnh cũ ở vị trí 4/5 được giữ nguyên và vẫn tính vào giới hạn;
cần gỡ ảnh để còn dưới 3 ảnh trước khi tải thêm.
Chỉ phát lại đúng khóa/input của upload cũ ở vị trí 4/5 được trả **201**;
không chấp nhận upload mới ở các vị trí đó.

```sh
curl -b cookies.txt -H 'X-CSRF-TOKEN: <token>' -H 'Idempotency-Key: <uuid>' \
  -H 'Content-Type: image/jpeg' --data-binary @wallet.jpg \
  'http://127.0.0.1:5080/api/items/<itemId>/images?position=1'
```

Response **201** `ImageResponse`, `Location` trỏ content. Web chờ tối đa 11 phút cho
toàn bộ upload; deadline từng bước AI riêng như sau:

1. Kiểm quyền/byte, hash input trong RAM và gửi `image.embed` tạm qua AMQP, deadline
   300 giây, để đọc OCR và tạo vector riêng từ ảnh chưa che. OCR tối đa
   3000 ký tự, có cờ nội dung không rõ; giữ số 0 đầu, không tự hoàn thiện số bị khuất.
   Kiểm nguồn/model/chiều và vector hữu hạn,
   khác zero; nếu capability tìm ảnh bị tắt, worker trả JSON `null` và không có cache.
2. Gửi cùng input chưa che vào `image.redact` với profile `redact-v4`, chờ tối đa 5 phút.
   Kiểm schema, source ID/version/hash, model/revision/profile, MIME signature, số byte,
   hash output, dimensions (tối đa 10000 mỗi chiều và 40 triệu pixel). .NET không decode ảnh.
3. Chỉ sau output hợp lệ mới ghi reservation loại `processed`, upload output vào R2
   ngoài transaction, rồi khóa item/object và gắn output thành `needs_review` cùng
   cache vector/OCR nếu có. Chỉ ảnh được duyệt mới đưa vector và từ khóa OCR vào chỉ mục.
4. Nếu item/quyền đã thay đổi trong khi xử lý, không gắn output cũ. Reservation hết hạn
   sau một giờ để cleanup. Dữ liệu gốc bị bỏ khi hoàn tất/lỗi/hủy.

Sai MIME **415**, body rỗng hoặc vị trí ngoài 1..3 **400**, quá 10 MiB **413**,
đã đủ 3 ảnh chưa gỡ, vị trí/version đã đổi hoặc đã trả
**409**, sai quyền **403**, output sai hợp đồng **502**, AI/broker/R2 chưa sẵn sàng **503**.
Không có output hợp lệ thì không tạo object/reservation. Lỗi upload R2 có thể để lại
reservation output để dọn; không để lại image đã gắn hoặc báo đăng ảnh thành công.
Gửi lại đúng khóa/input trả cùng ảnh, không chạy AI/upload thêm. Cùng khóa ảnh khác **409**.

`redact-v4` che khoảng 60% phần đầu và giữ khoảng 40% phần cuối của số CCCD/CMND,
điện thoại và mã định danh như MSSV, mã nhân viên, số thẻ/tài khoản. Tỷ lệ dựa trên
chiều rộng vùng nhận diện, không phải phép đếm ký tự. Số hộ chiếu (`passport_number`),
toàn bộ vùng mã đọc máy (`mrz`), chữ ký (`signature`), khuôn mặt, địa chỉ/quê quán/nơi sinh, QR và mã
vạch được che toàn bộ. Họ tên, ngày sinh, ngày cấp/hết hạn và thông tin đối chiếu
khác ngoài MRZ giữ nguyên; dữ liệu lặp trong MRZ vẫn được che kín.
Khi lượt đầu thấy dấu hiệu giấy tờ (khuôn mặt, số định danh/hộ chiếu, MRZ, chữ ký,
QR hoặc mã vạch), worker kiểm tra thêm các trường trên toàn ảnh rồi gộp, bỏ khung
trùng chính xác và kiểm giới hạn 32 vùng; lỗi hoặc quá giới hạn không trả ảnh che dở.
Ảnh đã xử lý trước thay đổi này giữ output cũ; muốn áp dụng cách che hoặc embedding
ảnh gốc hoặc OCR mới phải tải lại ảnh gốc. Chỉ mục văn bản ghép mô tả hiện hành với
OCR của ảnh đã duyệt; sửa mô tả không cần tải lại ảnh.

## POST /api/items/{itemId}/images/{imageId}/review — duyệt hoặc từ chối

Body `{"contentVersion":1,"decision":"approved"}` hoặc `decision:"rejected"`.
Yêu cầu CSRF và idempotency; quyền quản lý hiện tại. Response **200** `ImageResponse`.
Chỉ review output validated ở `needs_review|ready`, đúng version và item active.
Approved → `ready`; rejected → `rejected`. Có thể từ chối output từng được duyệt để
thu hồi công khai. Từ chối rồi muốn dùng ảnh khác thì gỡ ảnh và upload lại.
Nếu từ chối ảnh công khai cuối cùng, tin tự chuyển sang `hidden`. Duyệt ảnh thay thế
không tự công khai lại; người quản lý cần xuất bản lại tin.
Ghi reviewer/time phía server, tăng row/document version và snapshot/tombstone nguyên tử.
Sai quyền **403**, ảnh không thuộc món **404**, version cũ/đã gỡ/trạng thái sai **409**.

## POST /api/items/{itemId}/images/{imageId}/retire — gỡ output

Body `{"contentVersion":1}`, CSRF và idempotency. Response **200** `ImageResponse`.
Quyền quản lý hiện tại. Ghi retiredAt, tăng source version, bỏ liên kết object, đánh dấu
output `delete_pending`, cập nhật outbox cùng transaction. Không xóa lịch sử món đồ.
Cache embedding/OCR gốc của ảnh được bỏ khi từ chối, gỡ ảnh hoặc xóa món đồ.
Gỡ ảnh công khai cuối cùng tự chuyển tin sang `hidden` và ghi tombstone cùng transaction;
gỡ một ảnh khi vẫn còn ảnh công khai khác giữ nguyên trạng thái xuất bản.
Version sai/đã gỡ **409**, sai quyền **403**, ảnh không thuộc món **404**.
Cleanup xóa R2 sau commit; lỗi được retry tối đa 5 lần, sau đó cần vận hành xử lý.

## GET /api/items/{itemId}/images/{imageId}/content — đọc output

Response **200** bytes với MIME đã kiểm, `Cache-Control:no-store`,
`X-Content-Type-Options:nosniff`. Người xem thông thường chỉ đọc khi item published/active
và output ready/approved/validated/chưa gỡ. Quản lý hiện tại được xem trước output
validated chưa duyệt. Kiểm lại quyền/source sau khi đọc R2 để không trả ảnh vừa bị thu hồi.
Không đủ điều kiện/đã gỡ/ảnh thuộc món khác **404**; R2 lỗi/hash lệch **503**.
Không cung cấp endpoint original, download URL original hoặc presigned upload cho trình duyệt.

## POST /api/search — tìm bằng mô tả tiếng Việt

Cookie + CSRF; không yêu cầu Idempotency-Key vì không lưu query/job nghiệp vụ.

```json
{
  "text": "Ví đen, khóa kéo vàng, không có dây đeo",
  "area": "Công viên Bờ Sông",
  "from": "2026-10-01",
  "until": "2026-10-24",
  "lostAt": "2026-10-18T09:30:00+07:00",
  "limit": 10
}
```

`text` 1–2000 sau trim, bắt buộc; `area` tùy chọn tối đa 200. Khi có khu vực,
Python lọc và tìm trong khu vực trước. Nếu không có tin đạt ngưỡng phù hợp thì mới tìm
thêm ngoài khu vực; khi mở rộng, tin trong khu vực vẫn xếp trước.
`from/until` là bộ lọc ngày bắt buộc tuân thủ khi có,
bao gồm hai đầu; `limit=1..10`, mặc định 10. Quy tắc này áp dụng cho cả ba endpoint AI;
`GET /api/items?area=...` vẫn lọc cứng theo khu vực.
`lostAt` là thời điểm mất ước tính, tùy chọn, dùng ISO 8601 kèm múi giờ.
Giá trị sai hoặc nằm trong tương lai trả **400**.
Không bắt ảnh. Gửi JSON tới Python qua AMQP `search.hybrid`; Python chọn thuật toán
ngữ nghĩa/từ khóa theo profile cấu hình. Hybrid text dùng weighted RRF với tỷ trọng
ngữ nghĩa/từ khóa mặc định 60/40 (`AI_SEARCH_SEMANTIC_WEIGHT=0.6`), cộng tín hiệu vị trí
nhỏ có hệ số 0.03; hệ số hai nhánh chính lần lượt là 1.2 và 0.8, cộng `weight / (60 + rank)`.
.NET không đọc vector/search database.
Python cache ứng viên FTS/vị trí trong Redis cho truy vấn văn bản, với TTL mặc định
60 giây và vô hiệu hóa theo phiên bản chỉ mục cập nhật trong cùng transaction.
Nhánh ngữ nghĩa vẫn xếp hạng vector trong PostgreSQL. Khi trúng cache, .NET vẫn
kiểm tra nghiệp vụ. Khi Redis lỗi, Python tìm trực tiếp trong PostgreSQL.
Xem [cấu hình và kiểm thử Redis](../guides/ai-service.md#cache-từ-khóa-bằng-redis).
Nhánh text tìm trên tiêu đề/mô tả/khu vực và OCR của ảnh đã duyệt thuộc bài công khai.
Khi capability ảnh bật, nhánh này cũng xét vector ảnh riêng. OCR không được trả trong DTO hay
ghi lại vào mô tả công khai. Ảnh cũ chưa có OCR cần tải lại để bổ sung. Không có điều
kiện đối chiếu chính xác toàn bộ số hoặc đuôi CCCD/MSSV; kết quả gợi ý và OCR vẫn có
thể sai hoặc trùng nhau.

Response **200**:

```json
{
  "items": [{"rank":1,"item":"<ItemResponse như API món đồ>"}],
  "mode": "text",
  "searchProfileId": "text-description-v1",
  "searchProfileVersion": 1,
  "partial": false,
  "filtersRelaxed": false,
  "fallbackUrl": "/api/items",
  "rankingMethod": "similarity_fallback"
}
```

`rank` là vị trí gợi ý sau kiểm tra nghiệp vụ, không phải xác suất sở hữu. Response
thực tế `item` là object ItemResponse. .NET kiểm lại published/active, document/source
version/hash, model/profile và bộ lọc ngày hiện tại, bỏ ứng viên cũ/trùng.
Món khớp khu vực khi `foundArea` chứa `area`, không phân biệt hoa thường. .NET xếp
món khớp khu vực trước mọi món ngoài khu vực, kể cả khi món ngoài khu vực có điểm
cao hơn hoặc khớp nhiều loại truy vấn hơn. Không truyền `area` thì giữ thứ tự nhóm và điểm.
Khi có `lostAt`, .NET cộng tối đa 5% điểm cho giờ nhặt gần sau giờ mất,
giảm dần về 0 trong 24 giờ. Khoảng giờ nhặt có thể khớp được tối đa 2,5%.
Tin chỉ ghi ngày nhặt được cộng 2% nếu cùng ngày theo múi giờ của tin.
Trong từng khu vực và nhóm truy vấn, điểm được nhân với `1 + bonusThoiGian`.
Khu vực quyết định thứ tự trước nhóm truy vấn và điểm; bộ lọc ngày luôn được giữ nguyên.
`filtersRelaxed:true` chỉ khi có `area` và danh sách trả về có món ngoài khu vực ưu tiên;
không có nghĩa là đã nới ngày. Cả ba endpoint tìm kiếm nhận tối đa **20 món duy nhất**
từ Python cho toàn bộ request. Mỗi kênh/nhánh truy hồi cũng giữ tối đa 20; nếu mở rộng,
kết quả ngoài khu vực nối sau kết quả trong khu vực trước khi cắt pool chung.
.NET đọc cả pool bằng một truy vấn SQL JOIN kèm ảnh công khai và quyền quản lý Hub
qua correlated `EXISTS`, kiểm phiên bản/quyền hiện tại rồi xếp khu vực và nhóm trước
khi cắt kết quả cuối còn `limit=1..10`. Không truy vấn lại từng món hay refill ngoài
pool 20; `partial:true` khi bỏ ứng viên khiến kết quả chưa đủ limit.
Kết quả hợp lệ rỗng là **200** với `items:[]`.

Input rỗng/khoảng ngày sai (kể cả from=0001-01-01 hoặc until=9999-12-31) **400**; response AI sai schema/model **502**;
broker/model/search store thiếu hoặc timeout 45 giây **503**. Lúc lỗi dùng
`GET /api/items?area=...&from=...&until=...` để lọc cơ bản; không đổi lỗi thành rỗng.
Tên profile là hợp đồng cấu hình, chưa phải chứng nhận đạt chất lượng tìm kiếm.

## POST /api/search/image — tìm bằng ảnh

Cookie + CSRF, body ảnh JPEG/PNG/WebP nhị phân tối đa 10 MiB. Query `area`, `from`,
`until`, `lostAt`, `limit` như tìm text. Response **200** cùng SearchResponse, `mode:"image"`,
profile mặc định `image-only-v1`. Gửi AMQP `search.hybrid.image` nonpersistent/TTL;
chỉ nhận ứng viên gắn với ảnh đã che được duyệt ở đúng phiên bản hiện tại. Ảnh upload
mới khi capability ảnh bật dùng vector từ ảnh gốc; nguồn cũ/không có cache vẫn dùng
vector bản che hoặc cache ảnh cũ. Ảnh truy vấn được embedding riêng, không chạy OCR;
deadline mỗi ảnh 300 giây. Không coi độ giống là khớp số chính xác.
RPC gồm chấm lại tối đa 315 giây. Trình duyệt chờ tối đa 345 giây cho endpoint một ảnh.

```sh
curl -b cookies.txt -H 'X-CSRF-TOKEN: <token>' -H 'Content-Type: image/png' \
  --data-binary @query.png 'http://127.0.0.1:5080/api/search/image?limit=10'
```

Sai MIME **415**, quá byte **413**, body rỗng/bộ lọc sai **400**, dịch vụ **502/503** như
tìm text. Ảnh query không lưu DB/R2/outbox hoặc lịch sử; input bị bỏ sau request.
Để tìm bằng nhiều ảnh kèm mô tả, dùng endpoint bên dưới.

## POST /api/search/images — tìm bằng tối đa ba ảnh và mô tả

Cookie + CSRF; body `multipart/form-data`, không yêu cầu Idempotency-Key.
Query `area`, `from`, `until`, `lostAt`, `limit` giống tìm text. Các phần form:

- `images`: bắt buộc **1–3 file**, mỗi file JPEG/PNG/WebP, từ 1 byte đến **10 MiB**.
- `text`: tối đa một trường UTF-8 tùy chọn, tối đa **2000 ký tự** sau trim;
  bỏ trống/khoảng trắng tương đương không gửi mô tả.

Tổng request tối đa 30 MiB cộng 64 KiB cho form/header; không nhận trường khác.
.NET dùng `MultipartReader`, đọc stream vào RAM, không `IFormFile` hoặc tệp tạm.
Kiểm xong toàn bộ ảnh, mô tả và bộ lọc mới gọi AI. .NET gửi một lệnh
`search.hybrid.images` chứa cả nhóm ảnh và mô tả tùy chọn. Python tìm từng ảnh,
chạy nhánh text hybrid nếu có mô tả rồi hợp nhất thứ hạng trước khi trả ứng viên.
Thời gian xử lý AI chung tối đa **955 giây**, trình duyệt chờ tối đa
**975 giây**, gồm tối đa ba nhánh ảnh 300 giây và một nhánh text 30 giây và 15 giây nhận ảnh/chấm lại; một nhánh truy hồi lỗi thì cả
request lỗi, không trả kết quả thành công thiếu nhánh.

```sh
curl -b cookies.txt -H 'X-CSRF-TOKEN: <token>' \
  -F 'images=@front.jpg;type=image/jpeg' \
  -F 'images=@back.png;type=image/png' \
  -F 'images=@detail.webp;type=image/webp' \
  -F 'text=Ví màu đen, khóa kéo vàng' \
  'http://127.0.0.1:5080/api/search/images?area=Campus&limit=10'
```

Response **200** cùng `SearchResponse`: `mode:"image"` khi không có mô tả,
`mode:"combined"` khi có mô tả; `searchProfileId` tương ứng `image-fusion-v1` hoặc
`multimodal-fusion-v1`, `searchProfileVersion:1`. Python hợp nhất bằng weighted
reciprocal rank fusion: mỗi danh sách ảnh đóng góp `1 / (60 + rank)`, nhánh mô tả
đóng góp `0.5 / (60 + rank)`, rank bắt đầu từ 1. Mỗi món đóng góp một lần trong mỗi
danh sách và chỉ xuất hiện một lần trong kết quả; không trộn điểm similarity giữa model.
Nhánh mô tả vẫn dùng hybrid text 60/40 bên trong.

Khi có `area`, tìm trong khu vực trước; nếu không có món nào đạt ngưỡng cosine
ảnh **hoặc** mô tả thì mới tìm ngoài khu vực. Nhiều ảnh dùng cosine cao nhất.
Mỗi kênh/nhánh và pool chung đều tối đa **20 món**, không nhân theo số đầu vào.
Món yếu trong khu vực không chiếm chỗ khi mở rộng; ngày vẫn lọc cứng.

Python chấm toàn bộ pool bằng Qwen3-VL-Reranker-2B khi đã cấu hình. Python lấy ảnh
đã duyệt và mô tả công khai từ .NET qua RabbitMQ, chấm ảnh/text riêng rồi lọc ngưỡng
và tỷ lệ so với điểm tốt nhất trong từng khu vực/nhóm. Một loại mạnh là đủ.
Không dùng RRF như chất lượng tuyệt đối. Toàn bước bổ sung có ngân sách 15 giây;
lỗi/quá giờ dùng bộ lọc cosine cho toàn pool, không trộn điểm model dở dang.

.NET nhận 0–20 món đã lọc, kiểm lại nguồn hiện hành, ưu tiên khu vực và nhóm đạt
ngưỡng rồi áp dụng bonus `lostAt` trên `relevanceScore` trước khi lấy tối đa 10 món.
Không refill ngoài pool hoặc thêm món yếu để đủ 10. HTTP chỉ xuất rank và thêm
`rankingMethod: "reranker" | "similarity_fallback"`; giao diện báo khi dùng dự phòng.
`partial`, `filtersRelaxed`, `fallbackUrl` giữ ý nghĩa cũ. Không cần migration DB.
Chi tiết ngưỡng và benchmark tại [hướng dẫn đánh giá](../guides/search-evaluation.md).

Thiếu ảnh, quá ba ảnh, ảnh rỗng, text/form/bộ lọc sai **400**; sai MIME **415**;
quá byte **413**; phản hồi AI sai **502**; AI/broker/timeout **503**. Ảnh query
không lưu DB/R2/outbox/lịch sử; mọi buffer ảnh bị xóa cả khi thành công, lỗi hoặc hủy.

## Cấu hình cần thiết

```dotenv
RabbitMq__Uri=amqps://<user>:<password>@<private-host>/<vhost>
Ai__RedactionRevision=<immutable-model-revision>
Ai__EmbeddingRevision=<immutable-model-revision>
Storage__Endpoint=https://<account-id>.r2.cloudflarestorage.com
Storage__Bucket=<private-output-bucket>
Storage__AccessKeyId=<server-only>
Storage__SecretAccessKey=<server-only>
```

Giữ bucket private, tắt public domain/r2.dev, credential chỉ cho bucket output.
Model ID/profile mặc định trong `apps/api/appsettings.json`, được cấu hình Ollama văn bản trong `.env.example` ghi đè. Revision rỗng/main/latest
bị từ chối; phải ghim revision đã triển khai trong Python. Không gửi các biến này vào React.
Adapter R2 dùng [SDK AWS .NET theo hướng dẫn Cloudflare](https://developers.cloudflare.com/r2/examples/aws/aws-sdk-net/).
Chưa kiểm chứng Cloudflare R2 thật hoặc độ chính xác mô hình; xem [kiểm thử](testing.md).
