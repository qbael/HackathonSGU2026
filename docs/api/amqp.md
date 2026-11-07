# Hợp đồng .NET ↔ Python qua RabbitMQ

Phiên bản schema 1, cập nhật 07/11/2026. Đây là hợp đồng adapter .NET đã triển khai;
worker Python/search database thực thi OCR, embedding riêng cho ảnh và văn bản, image.redact và full manifest/parts theo [hướng dẫn AI](../guides/ai-service.md). FastAPI chỉ health. Receipt chỉ sau kiểm full manifest và commit projection được bật; model/credential thật vẫn cần nghiệm thu.
Tài liệu nền: [kiến trúc](../architecture/system-architecture.md); API HTTP:
[nghiệp vụ](recovery.md), [ảnh/tìm kiếm](media-search.md).

## Kết nối, topology và bảo vệ dữ liệu

`RabbitMq:Uri` rỗng: adapter tắt, API cơ bản vẫn hoạt động. Có URI: một kết nối lâu dài,
heartbeat 30 giây, channel publish confirms/mandatory riêng và channel consumer riêng;
reconnect ban đầu/mất kết nối backoff 1–30 giây + jitter. Không mở connection mỗi request.
Yêu cầu AMQPS có kiểm chứng certificate ngoài loopback; AMQP chỉ được phép local loopback.
Không log URI/credential, ảnh, query, OCR, answer hoặc message body.

| Queue mặc định | Chủ provisioning và tính chất |
| --- | --- |
| `findie.ai.commands` | Ops tạo durable quorum, persistent index commands/vector parts hoặc output parts cũ, TTL 30 giây, DLX/retention hữu hạn |
| `findie.api.results` | Ops tạo durable quorum, persistent index receipts, TTL hữu hạn và DLX; .NET kiểm queue tồn tại khi kết nối |
| `findie.ai.image` | Python tạo non-durable/exclusive/auto-delete, nonpersistent raw input/query, TTL queue tối đa 955 giây; TTL message 300 giây cho embedding/OCR và che, 315 giây cho tìm ảnh đơn, 955 giây cho nhóm ảnh; trần 4 message/32 MiB; **không DLX/alternate routing/tracing body** |
| `findie.ai.query` | Python tạo non-durable/exclusive/auto-delete cho tìm text, TTL 45 giây, tối đa 32 message/2 MiB |
| `findie.api.materials` | .NET tạo non-durable/exclusive/auto-delete cho yêu cầu lấy dữ liệu chấm, TTL 15 giây, tối đa 32 message/2 MiB; không DLX |
| `findie.ai.materials.results` | Python tạo non-durable/exclusive/auto-delete cho dữ liệu chấm, TTL 15 giây, tối đa 4 message/32 MiB, `x-overflow=reject-publish`; không DLX |
| Reply queue do broker sinh | .NET tạo exclusive/non-durable/auto-delete cho output ảnh/query; TTL 60 giây, tối đa 64 message/32 MiB; không DLX |

Có thể đổi tên qua `RabbitMq:IndexQueue|ResultQueue|ImageQueue|QueryQueue|MaterialsQueue|MaterialsReplyQueue`; chỉ server
cấu hình, không nhận route/reply_to từ HTTP client. Định nghĩa durable queues mẫu tại
[rabbitmq-definitions.json](rabbitmq-definitions.json), import bằng công cụ quản trị broker
vào vhost `/` hoặc sửa vhost theo môi trường. File không chứa user/password/permission;
ops cấp tài khoản triển khai và tài khoản API/Python tách biệt. Ngoài luồng commands/results,
.NET configure/consume `findie.api.materials`, Python configure/consume `findie.ai.materials.results`.
Tên hai queue phải đồng bộ với `AI_MATERIALS_QUEUE`/`AI_MATERIALS_REPLY_QUEUE`; chỉ cấp
thêm quyền đúng hai queue này, không dùng tài khoản admin.
Không dùng quyền admin cho runtime. Không đưa RabbitMQ ra internet.

Broker đang chạy cần cập nhật ACL cho hai queue materials trước khi khởi động lại API/worker;
không đổi quyền thành `.*` để khắc phục lỗi khai báo queue. Queue tạm được tạo lại sau khi
hai service ngắt kết nối, gồm TTL tìm kiếm mới và chính sách overflow của reply materials.

Local có thể chạy `make rabbitmq-up` theo [hướng dẫn Docker](../guides/development.md#rabbitmq-docker):
Compose tự import topology cùng một admin và hai tài khoản runtime riêng, mật khẩu
sinh trong `.env`. Quyền configure/consume được giới hạn theo queue. Cả hai client
hiện publish qua default exchange, nên quyền write exchange này cho phép route tới
các queue trong cùng vhost; ACL local không giới hạn được từng routing key theo chiều.

Raw chỉ ở RAM ứng dụng; RabbitMQ có thể page transient message xuống đĩa. TTL/ACK không
phải cam kết xóa forensic tức thì. Phải loại raw queues khỏi log/tracing/DLQ/backup ở broker
và tắt request body buffering/logging ở reverse proxy. Durable queue chỉ chứa vector đã tạo,
output được duyệt, cache vector/OCR của nguồn đã duyệt, snapshot công khai và receipt
metadata, không original/query image. Vector và OCR từ ảnh gốc chỉ dùng nội bộ, không
được trả ra DTO công khai; OCR không nằm trong snapshot outbox.

## Envelope AMQP

`BasicProperties`: `Type` là operation bên dưới, `CorrelationId` UUID và `ReplyTo`
do bên yêu cầu tạo/chỉ định (.NET cho index/search, Python cho `search.materials`).
`ContentType`, `Persistent` và `Expiration` theo operation:

| Operation | Deadline/TTL message |
| --- | --- |
| `image.embed`, `image.redact` | 300 giây |
| `search.hybrid` | 45 giây |
| `search.saved` | 30 giây |
| `search.hybrid.image` | 315 giây |
| `search.hybrid.images` | 955 giây |
| `search.materials` và các part trả về | Tối đa 15 giây, trong ngân sách chấm lại |
| Index và operation khác | 30 giây |

Header `metadata` là **bytes JSON UTF-8**, tối đa 16 KiB. Body ảnh nhị phân tối đa 10 MiB;
nhóm query `search.hybrid.images` vẫn tối đa **30 MiB**, độc lập với pool 20 món.
Body text/snapshot/ứng viên là JSON UTF-8, không base64; vector JSON tối đa 1 MiB.
Packet `search.materials` có thêm tiền tố 4 byte và manifest tối đa 64 KiB như mô tả bên dưới.
Không đưa vector, ảnh hoặc mô tả vào header. Tối đa 32 waiter AI đang chờ;
không giữ DB transaction khi gọi broker hoặc model/R2.

Broker local đặt `max_message_size=33554432` (32 MiB) trong `scripts/rabbitmq.conf`
để nhận nhóm ảnh 30 MiB; broker triển khai riêng cần cùng giới hạn. RabbitMQ mặc định
giới hạn message 16 MiB theo [tài liệu cấu hình](https://www.rabbitmq.com/docs/configure#config-items).
Sau khi cập nhật cấu hình broker local đang chạy, khởi động lại service `rabbitmq`;
khởi động lại API và worker cùng phiên bản để dùng hợp đồng nhóm ảnh mới.

Metadata request chung: `schemaVersion:1`, `deadlineAt` ISO UTC, định danh model/version
và profile tùy operation. Worker kiểm deadline trước suy luận và trước commit.
Response index/image/search echo định danh/configuration của request, thêm
`kind:<operation>`, `succeeded:true|false`; `search.materials` dùng metadata từng part
và completion như hợp đồng riêng bên dưới. .NET chỉ hoàn tất đúng correlation còn sống.
Lỗi truy hồi chính báo lỗi dịch vụ; lỗi riêng materials/reranker dùng similarity fallback.
Không trả trace/OCR/dữ liệu worker ra HTTP client.

## image.embed

Route `findie.ai.image`, nonpersistent, body ảnh gốc chỉ tồn tại trong request tạm.
Deadline/TTL 300 giây. Metadata:
`schemaVersion,imageId,itemId,sourceVersion:1,sourceSha256,modelId,modelRevision,
dimensions,processingProfile:"image-v1",deadlineAt`.
`sourceSha256` là hash bytes upload trước che. Worker kiểm nguồn/model/chiều, chuẩn hóa
ảnh, đọc OCR bằng model vision đã ghim và tạo vector riêng từ **ảnh chưa che**.
OCR được lưu cạnh vector để lập chỉ mục văn bản khi ảnh được duyệt.
OCR dùng schema chặt `{text,hasUnclearText}`, tối đa 3000 ký tự; giữ số 0 đầu và chữ
thấy rõ, bỏ đoạn không đọc được và đánh dấu không chắc chắn, không suy diễn hoặc giải
mã QR/barcode. Nội dung ảnh là dữ liệu, không phải lệnh cho mô hình.

Response metadata echo định danh/configuration, thêm `kind:"image.embed",succeeded`.
Body JSON tối đa 1 MiB:
`{modelId,modelRevision,dimensions,sourceSha256,vector,ocr?}`. `ocr` nếu có gồm
`text,hasUnclearText,modelId,modelRevision,processingProfile:"ocr-v1"`; model/revision
OCR là model vision, khác model/revision embedding ở lớp ngoài. `.NET` kiểm nguồn/model/chiều,
đủ số phần tử hữu hạn và vector khác zero trước khi lưu nội bộ vào
`item_images.original_embedding` kiểu jsonb. Không lưu bytes ảnh gốc, không trả vector
hoặc OCR trong `ImageResponse` và không lập chỉ mục ảnh chưa duyệt. Mô tả người đăng
không nằm trong cache này. Khi lập chỉ mục, tiêu đề/mô tả/khu vực hiện hành được ghép
với OCR của ảnh đã duyệt. Sửa mô tả không cần tải lại bytes gốc. Cache cũ vẫn dùng được;
cần tải lại ảnh gốc để bổ sung OCR còn thiếu hoặc thay vector ảnh/OCR cũ.

Khi `AI_IMAGE_SEARCH_ENABLED=false`, body thành công là JSON `null`: upload vẫn được
che/duyệt với model text-only, nhưng không có cache embedding ảnh gốc. Model/transport
lỗi khi capability đã bật làm upload thất bại; không tự chuyển sang embed bản che.
Vector đã lưu được tái dùng khi retry/cập nhật chỉ mục. Đổi model/revision/chiều khiến
cache cũ không còn tương thích; cần tải lại ảnh gốc để tạo vector mới.

## image.redact

Route `findie.ai.image`, nonpersistent, body raw ảnh. Metadata:
`schemaVersion,imageId,itemId,sourceVersion:1,sourceSha256,modelId,modelRevision,
processingProfile:"redact-v4",deadlineAt`. Full mode dùng `qwen3-vl:4b-instruct`; modelId/revision phải khớp cấu hình đã ghim của hai service.

`redact-v4` che khoảng 60% phần đầu của vùng số CCCD/CMND, điện thoại và mã định danh
như MSSV, mã nhân viên, số thẻ/tài khoản; giữ khoảng 40% phần cuối để nhận diện.
Tỷ lệ tính theo chiều rộng bbox, không OCR/đếm ký tự nên không bảo đảm đúng 40% số chữ số.
Detector vẫn trả khung toàn bộ giá trị; Python cắt phần cần che, không thêm viền ở ranh
giới nội bộ để tránh che mất phần đuôi. Số hộ chiếu (`passport_number`),
chữ ký (`signature`), khuôn mặt, địa chỉ riêng tư/quê quán/nơi sinh,
QR và mã vạch được che toàn bộ. Họ tên, ngày sinh, các ngày cấp/hết hạn và thông tin
đối chiếu giữ nguyên. MRZ không được che tự động và có thể còn đọc được trên ảnh. Bố cục, logo,
tên cơ quan và nhãn trường giữ nguyên.
Nhãn tự động là `face`, `identity_number`, `identifier_number`, `passport_number`,
`signature`, `phone`, `address`, `qr_code`, `barcode`. Nhãn `mrz` vẫn được đọc cho dữ liệu/tọa độ thủ công cũ.
Mỗi `bbox` gồm bốn số nguyên `[x1,y1,x2,y2]` trong khoảng 0–1000 theo toàn ảnh;
mỗi giá trị nhạy cảm hoặc trường địa chỉ đầy đủ có một khung riêng; trường địa chỉ
có thể gồm nhãn và các dòng tiếp theo. Chữ/khuôn mặt thêm viền
2–4 px; QR/mã vạch dùng `max(2, ceil(cạnh_ngắn / 200))`, tức 5–8 px khi cạnh ngắn
là 1000–1600 px, để che kín mép mã khi khung nhận diện hơi thiếu.

Nếu lượt đầu thấy dấu hiệu giấy tờ qua `face`, `identity_number`, `identifier_number`,
`passport_number`, `signature`, `qr_code` hoặc `barcode`, worker chạy thêm một
lượt tìm trường giấy tờ trên toàn ảnh, kể cả khi đã tìm được một số trường ở lượt đầu.
Gộp kết quả, bỏ khung trùng chính xác theo nhãn/bbox rồi kiểm giới hạn tổng 32 vùng.

Nếu kết quả phát hiện địa chỉ, worker lấy vùng bao các khung địa chỉ từ pixel gốc
đã chuẩn hóa, mở rộng mỗi bên ngang 50% chiều rộng và trên/dưới một chiều cao vùng,
để model thấy nhãn trường và ngày tháng lân cận khi xác định ranh giới địa chỉ.
Lượt nhận diện bổ sung chỉ tìm địa chỉ trong vùng cắt, quy đổi khung về toàn ảnh,
giữ cả khung cũ lẫn khung bổ sung và bỏ bản trùng chính xác. Không có khung địa chỉ
thì không gọi lượt tìm địa chỉ bổ sung; mọi lượt cùng chịu deadline 300 giây. Lỗi lượt
bổ sung hoặc tổng quá 32 vùng sau khi bỏ khung trùng khiến xử lý thất bại; không trả
ảnh che dở.

Worker luôn decode, kiểm MIME/frame/pixel, phát hiện PII, che/mờ nếu có, bỏ EXIF và encode
ảnh mới kể cả không có PII. Lỗi model không được coi là ảnh sạch. Response body là output,
metadata echo nguồn/config, thêm `kind:"image.redact",succeeded,contentType,sha256,
byteSize,width,height,sensitiveRegions:[]`. Không trả original key, OCR text riêng tư hoặc
URL bất kỳ. Python không có credential R2.

.NET kiểm hợp đồng/hash/byte và chỉ lưu output. Reply bị trùng/muộn/không còn waiter được
ACK/bỏ; lỗi cuối không đưa original vào DLQ. Crash mất raw thì HTTP client phải tải lại.

## search.hybrid và search.hybrid.image

Text: query queue, body `{text,area,from,until}` JSON, deadline 45 giây.
Image: image queue, body ảnh query nhị phân, nonpersistent, deadline 315 giây.
Không lưu query vào R2/job/outbox/vector query bền vững. Các deadline tìm kiếm gồm
thêm tối đa 15 giây để lấy dữ liệu ứng viên và chấm lại; embedding/che khi đăng ảnh
vẫn giữ deadline 300 giây riêng.

Metadata: `schemaVersion,modelId,modelRevision,processingProfile,searchProfileId,
searchProfileVersion:1,mode,area,from,until,limit,candidateLimit:20,deadlineAt`.
Processing profile `text-v1|image-v1`; cấu hình text-only giữ `qwen3-embedding:4b`/2048.
Notebook full mode chọn `Qwen/Qwen3-VL-Embedding-2B`/2048, nhận ảnh native qua Transformers.
`modelRevision` là SHA-256 fingerprint của commit model/processor, mã inference, profile
và gói đã ghim; không phải manifest Ollama. Hai service phải đồng bộ model/revision/số chiều.
Gateway công bố `embedding,vision` cho embedding và `completion,vision` cho OCR.
Text profile mặc định `text-description-v1`, image `image-only-v1`.

Khi capability ảnh bật, text query xét cả vector mô tả ghép OCR và vector ảnh riêng,
hợp nhất với từ khóa trên nguồn văn bản. Tìm ảnh dùng vector ảnh; không thêm điều kiện
chính xác theo số hoặc đuôi số. OCR/embedding vẫn có thể nhận sai ký tự.
Hybrid text dùng weighted RRF `weight / (60 + rank)` với hệ số mặc định 1.2 ngữ nghĩa,
0.8 từ khóa (`AI_SEARCH_SEMANTIC_WEIGHT=0.6`) và 0.03 vị trí. Cosine được đo cho cả
ứng viên từ khóa/vị trí ngoài semantic top 20; điểm chưa đo không được coi là độ tương đồng.

Có `area`: các nhánh tìm trong khu vực trước. Chỉ khi không có món đạt ngưỡng cosine
ở **ít nhất một loại đầu vào** thì tìm ngoài khu vực, dùng lại embedding và giữ bộ lọc ngày.
Nhiều ảnh lấy điểm ảnh tốt nhất; không bắt cùng một món phải khớp cả ảnh lẫn text.
Các món yếu trong khu vực không chiếm hết pool trước khi mở rộng.
`AI_SEARCH_MIN_IMAGE_SIMILARITY`/`AI_SEARCH_MIN_TEXT_SIMILARITY` mặc định `0.6`, hợp lệ 0–1.

Sau truy hồi/hợp nhất, **Python chấm và lọc toàn bộ pool tối đa 20 món trước khi trả .NET**.
Không gửi pool sang .NET để chọn 10 rồi mới gọi lại model. Khi đã cấu hình reranker,
Python lấy dữ liệu công khai qua `search.materials` và gọi model trên toàn pool trong
ngân sách bổ sung 15 giây. Điểm ảnh và text được chấm riêng; chỉ cần một loại đạt ngưỡng.
`AI_RERANK_MIN_IMAGE_SCORE`/`AI_RERANK_MIN_TEXT_SCORE` mặc định `0.5`.
Điểm liên quan chung `relevanceScore` là điểm cao nhất của các loại đã đạt ngưỡng.

Sau ngưỡng tuyệt đối, giữ món có điểm ít nhất bằng
`AI_SEARCH_RELATIVE_SCORE_RATIO × điểm tốt nhất` trong cùng phần khu vực và nhóm bằng chứng;
mặc định ratio `0.75`. Không so cắt đuôi xuyên nhóm. Các ngưỡng này chưa được hiệu chỉnh
bằng dữ liệu thực tế. RRF, cosine và điểm model không phải xác suất sở hữu.

Khi reranker chưa cấu hình, lỗi, OOM, quá giờ, thiếu part hoặc không chấm xong toàn pool,
Python bỏ toàn bộ điểm model dở dang và áp dụng cùng bộ lọc bằng cosine trên pool.
Món đã được xác nhận `stale` không được đưa lại vào phương án dự phòng.
Lỗi truy hồi/model embedding chính vẫn là lỗi dịch vụ, không biến thành danh sách rỗng.

Response metadata echo model/profile, thêm kind/succeeded. Body tối đa 1 MiB, ví dụ:

```json
{
  "rankingMethod": "similarity_fallback",
  "candidates": [{
    "itemId": "<uuid>",
    "documentVersion": 5,
    "sourceId": "<itemId cho text, imageId cho image>",
    "sourceKind": "image",
    "sourceVersion": 2,
    "sourceSha256": "<64 lowercase hex>",
    "relevanceScore": 0.86,
    "imageRelevant": true,
    "textRelevant": false
  }]
}
```

`candidateLimit=1..20`; API yêu cầu 20 cho cả ba endpoint, mỗi kênh/nhánh tối đa 20
và pool toàn request cũng tối đa 20 món duy nhất. Python trả **0–20 món đã qua lọc**,
không trả vector hoặc nội dung model. Nếu chấm lại dùng thêm ảnh đại diện, candidate
đơn có thêm `sources` chứa cả nguồn truy hồi và nguồn ảnh đã dùng; .NET kiểm tất cả.
Wire xếp theo `imageRelevant && textRelevant` trước, chỉ ảnh tiếp theo, chỉ text cuối;
trong nhóm xếp `relevanceScore` giảm dần. Ưu tiên khu vực được áp dụng khi lọc theo nhóm
và được .NET áp dụng khi xếp kết quả HTTP.

.NET đọc toàn bộ danh sách đã lọc bằng một SQL JOIN kèm ảnh công khai/quyền Hub,
kiểm published/active, document/source version/hash và ngày hiện hành. `sourceKind`
là loại nguồn thật, độc lập với mode query. .NET dùng `relevanceScore`, không thay
bằng `1/(61+rank)`; bonus thời gian chỉ đổi thứ tự trong cùng khu vực/nhóm, không cứu
món đã bị Python loại. Sau đó mới `Take(limit=1..10)`; không refill ngoài pool 20.
`rankingMethod` HTTP là `reranker|similarity_fallback`; giao diện thông báo khi dùng
phương án dự phòng. Ít kết quả do lọc chất lượng không làm `partial=true`.
`filtersRelaxed:true` chỉ khi có món hiển thị ngoài khu vực yêu cầu; ngày luôn lọc cứng.

## search.hybrid.images

Một RPC cho 1–3 ảnh và mô tả tùy chọn, route `findie.ai.image`, nonpersistent,
`ContentType:application/octet-stream`, deadline/TTL **955 giây**. Body là các ảnh
nối theo thứ tự `images`; mỗi ảnh tối đa 10 MiB, tổng vẫn tối đa **30 MiB**.
Không base64, tệp tạm, R2 hoặc outbox cho query. Metadata:

```json
{
  "schemaVersion": 1,
  "modelId": "<configured embedding model>",
  "modelRevision": "<pinned revision>",
  "processingProfile": "multimodal-v1",
  "searchProfileId": "multimodal-fusion-v1",
  "searchProfileVersion": 1,
  "mode": "combined",
  "area": null,
  "from": null,
  "until": null,
  "limit": 10,
  "candidateLimit": 20,
  "deadlineAt": "<UTC timestamp>",
  "cacheScope": "<actor UUID>",
  "text": "Ví màu đen",
  "images": [{"contentType": "image/jpeg", "length": 12345}]
}
```

Không có mô tả: `mode:image`, `searchProfileId:image-fusion-v1`. `candidateLimit=1..20`
độc lập số ảnh. Worker kiểm số ảnh/MIME/length/tổng body trước suy luận. Mỗi ảnh có
ngân sách embedding 300 giây, text 30 giây, chấm lại toàn pool thêm tối đa 15 giây.
Một nhánh truy hồi lỗi làm cả request thất bại; lỗi riêng reranker dùng similarity fallback.

Fusion vẫn dùng weighted RRF: mỗi ảnh hệ số 1, text hệ số 0.5, đóng góp
`weight/(60+rank)` với rank từ 1. Mỗi món góp một lần mỗi danh sách và chỉ xuất hiện một lần.
`imageScore`/`textScore` là đóng góp **RRF**, `score=imageScore+textScore`;
chúng độc lập với `relevanceScore` dùng để lọc/xếp cuối. Group sau đánh giá dựa trên
`imageRelevant`/`textRelevant`, không dựa vào việc RRF của một nhánh có lớn hơn 0.
Quy tắc OR khi mở rộng khu vực và toàn bộ bước chấm/lọc 20 món giống tìm đơn.

Response metadata echo cấu hình, thêm `kind:search.hybrid.images,succeeded`, không echo
`text`, `images` hoặc `cacheScope`. Body tối đa 1 MiB:

```json
{
  "rankingMethod": "reranker",
  "candidates": [{
    "itemId": "<uuid>",
    "score": 0.02459016393442623,
    "imageScore": 0.01639344262295082,
    "textScore": 0.00819672131147541,
    "relevanceScore": 0.91,
    "imageRelevant": true,
    "textRelevant": false,
    "sources": [{
      "documentVersion": 5,
      "sourceId": "<itemId hoặc imageId>",
      "sourceKind": "image",
      "sourceVersion": 2,
      "sourceSha256": "<64 lowercase hex>"
    }]
  }]
}
```

`sources` gồm mọi nguồn truy hồi và ảnh đại diện đã dùng để chấm, bỏ ref trùng, tối đa
6 ref với response đã đánh giá. .NET kiểm mọi nguồn; một nguồn stale làm loại cả món.
Điểm RRF vẫn được kiểm hữu hạn, không âm, không vượt tổng trọng số nhánh và tổng
`score=imageScore+textScore`; relevance phải hữu hạn trong `[0,1]`, ít nhất một cờ relevant
phải true và phù hợp mode. Không đem giới hạn số học của RRF áp vào relevance.
.NET kiểm wire theo nhóm đạt ngưỡng/relevance, ưu tiên khu vực, cộng bonus thời gian
trên relevance rồi giới hạn hiển thị 10. Không pad/refill khi không đủ món đạt chất lượng.

## search.saved — cron đối chiếu tin tìm đã lưu

Lệnh tạm trên query queue, JSON body tối đa **2 MiB**, không persistent/DLQ.
Metadata: `schemaVersion:1,modelId,modelRevision,dimensions,deadlineAt`, cùng
`cacheScope` tài khoản (không echo). Deadline tối đa 35 giây; .NET gửi 30 giây.
Body: `text` tùy chọn, `images` mảng tối đa 3 `OriginalEmbedding` không OCR,
`from`, `until` tùy chọn và `afterItemId` UUID/null. Cần mô tả hoặc ảnh.
Các vector phải khớp namespace model/revision/dimensions hiện hành.

Response metadata echo định danh model/chiều, thêm `kind:search.saved,succeeded`;
body tối đa 1 MiB: `{candidates:[{itemId,relevanceScore,sources:[...]}],nextAfter}`.
Mỗi source dùng `documentVersion,sourceId,sourceVersion,sourceSha256,sourceKind`
như tìm kiếm tương tác. Không echo mô tả, embedding hay ảnh trong reply metadata.

Python quét cosine, text-only dùng nguồn text, image-only lấy ảnh giống nhất;
kết hợp lấy trung bình text và điểm ảnh. Chỉ trả điểm **>=0.85**, không dùng
reranker/RRF/bonus. Phân trang theo ID tối đa 100 món, `nextAfter` là ID cuối
khi đủ trang, null khi hết. .NET lưu cursor, kiểm nguồn/trạng thái và chống trùng.
Xem [API, lịch chạy, privacy và quy tắc thông báo](saved-searches.md).

## search.materials — Python lấy dữ liệu chấm qua RabbitMQ

Python tạo correlation UUID riêng và gửi một request JSON **cho cả pool 1–20 món** tới
`findie.api.materials`, `Type:search.materials`, `ContentType:application/json`,
`Persistent:false`, `Expiration:15000`, `ReplyTo:findie.ai.materials.results`.
Header metadata `{schemaVersion:1,deadlineAt:<UTC>}`; body tối đa 64 KiB:

```json
{
  "candidates": [{
    "itemId": "<uuid>",
    "sources": [{
      "documentVersion": 5,
      "sourceId": "<itemId hoặc imageId>",
      "sourceVersion": 2,
      "sourceSha256": "<64 lowercase hex>",
      "sourceKind": "image"
    }]
  }]
}
```

.NET có channel/consumer riêng cho yêu cầu này, nên vẫn xử lý được trong lúc RPC tìm
kiếm ban đầu đang chờ Python. Đây chỉ là cấp dữ liệu; .NET không chọn shortlist 10
hoặc chấm relevance. Provider tải batch, bắt buộc món published/active và mọi nguồn
đúng version/hash; không dùng quyền quản lý để cấp ảnh chưa công khai.
Chọn ảnh nguồn đã duyệt trong refs, nếu không có thì ảnh đã duyệt đầu tiên theo vị trí.
.NET đọc R2, kiểm MIME/signature/length/SHA-256 và kiểm lại nguồn hiện hành sau khi đọc.
Python không nhận credential R2, object key, ảnh gốc hoặc plaintext OCR.

Mỗi món có một reply `Type:search.materials`, cùng correlation, `Persistent:false`,
TTL tối đa 15 giây, `ContentType:application/octet-stream`. Header metadata:
`{schemaVersion:1,succeeded:true,complete:false,itemId:<uuid>}`. Body gồm:

1. 4 byte số nguyên big-endian chỉ độ dài manifest JSON.
2. Manifest JSON UTF-8 tối đa 64 KiB.
3. Bytes ảnh đã xử lý tối đa 10 MiB, chỉ có khi `status:ready`.

Ví dụ manifest (không nằm trong header):

```json
{
  "itemId": "<uuid>",
  "status": "ready",
  "title": "Ví màu đen",
  "publicDescription": "Ví khóa kéo vàng",
  "image": {
    "sourceId": "<imageId>",
    "sourceVersion": 2,
    "sourceSha256": "<SHA-256 của bytes ảnh>",
    "documentVersion": 5,
    "contentType": "image/png",
    "length": 12345
  }
}
```

`stale`: món/nguồn không còn công khai hoặc sai phiên bản/hash, không có text/ảnh và
bị loại khỏi cả đường reranker lẫn fallback. `unavailable`: đọc output lỗi hoặc kiểm
integrity thất bại, không có ảnh; toàn pool chuyển sang similarity fallback.
Python kiểm lại ID, provenance, độ dài/hash/MIME, chuẩn hóa ảnh trong RAM rồi ACK từng
part. Dùng callback nhận part riêng, không giữ semaphore inference để xử lý reply.

Sau các part, .NET gửi reply JSON `{count:N}` với metadata
`{schemaVersion:1,succeeded:true,complete:true}`. Python chỉ dùng model scores khi đã
nhận đủ và chấm xong toàn pool. Lỗi provider có thể gửi `succeeded:false,complete:true`;
part trùng/sai, thiếu completion, reply muộn hoặc timeout đều chuyển sang fallback.
Các ID đã nhận `stale` vẫn bị loại nếu phần còn lại lỗi/quá giờ.

Không gom cả pool ảnh vào một message lớn. Reply queue dùng `x-overflow=reject-publish`
và publisher confirms để quá tải gây lỗi rõ ràng thay vì âm thầm bỏ part đầu. Cả hai
queue tạm không DLX/alternate routing/body tracing; lỗi được ACK/bỏ, không lưu lại dữ liệu
chấm. .NET và Python chỉ giữ ảnh trong RAM, không cache hoặc tạo bản sao trên đĩa.
Broker vẫn có giới hạn paging transient message đã nêu ở phần bảo vệ dữ liệu.

## index.upsert, index.source.vector, index.source.image và index.remove

Mọi thay đổi ảnh hưởng hiển thị/tìm kiếm ghi một outbox cùng transaction item, gồm
`itemId,documentVersion,kind,document,sources`. `document` chỉ trường công khai;
`sources` là manifest đầy đủ gồm text và ảnh ready/approved/validated, mỗi nguồn có
`kind,id,version,sha256,processingProfile`. Text hash là SHA-256 UTF-8 của
`title + "\n" + publicDescription`; image hash là output bytes. Không snapshot answer/chat.

Checksum snapshot: JSON key sắp ordinal đệ quy, array giữ thứ tự, JSON compact UTF-8 với
escaping của System.Text.Json; hash SHA-256 lowercase hex. Worker có thể xác minh trực tiếp
body bytes do .NET gửi (đã canonicalize), không cần tái tạo escaping bằng serializer Python.
.NET canonicalize lại sau PostgreSQL jsonb roundtrip để không bị lệch whitespace/thứ tự key.

Dispatcher lease một outbox đến hạn bằng `FOR UPDATE SKIP LOCKED`, tăng attempt, lease
90 giây, commit trước publish. Metadata lệnh:
`schemaVersion,jobId,leaseToken,itemId,documentVersion,snapshotSha256,modelId,
modelRevision,dimensions,deadlineAt`; số chiều lấy từ cấu hình hai service.

- `index.upsert`: persistent JSON body full snapshot. Sau manifest, .NET gửi mỗi approved
  image có cache bằng `index.source.vector`, persistent JSON body là payload đã lưu của
  `image.embed`, tối đa 1 MiB. Part metadata gồm cùng job/lease/snapshot/model và
  `sourceId,sourceVersion,sourceSha256,processingProfile,payloadSha256`.
  `payloadSha256` kiểm bytes JSON của part; `sourceSha256` ở metadata vẫn là hash
  **ảnh đã che được duyệt** trong manifest. `sourceSha256` bên trong payload cache là
  hash **ảnh gốc trước che**; hai giá trị có vai trò riêng. Worker kiểm model/revision/
  chiều của payload và vector trước khi ghép với nguồn đã duyệt. Cache khác model không
  được âm thầm thay bằng vector bản che.
  Nếu cache có `ocr`, worker kiểm schema/profile và provenance model OCR trước khi
  ghép OCR của các ảnh đủ điều kiện với mô tả để tạo vector và từ khóa trên hàng `text-v1`.
  Hàng `image-v1` giữ vector ảnh riêng. OCR không được ghi vào mô tả công khai hoặc trả
  trong response ứng viên.
  Với ảnh cũ hoặc upload lúc capability ảnh bị tắt, không có cache: .NET gửi
  `index.source.image`, persistent binary body chỉ output đã duyệt như trước. Nhánh này
  embed bản che và không thể khôi phục embedding ảnh gốc đã bỏ.
  Part ảnh nhị phân dùng cùng metadata nguồn, không có `payloadSha256`.
  Cùng correlation/reply queue; worker phải tập hợp manifest/parts theo job + lease,
  kiểm source và chỉ trả receipt sau khi các nguồn cần thiết đã commit hoặc được xác nhận
  đã có cùng version/hash. Không trả receipt riêng cho từng part.
- `index.remove`: persistent JSON tombstone, `document:null,sources:[]`; không gửi ảnh.
  Watermark/tombstone ngăn upsert cũ phục hồi dữ liệu đã gỡ.

Worker ghi search projection/vector/FTS trong transaction riêng ở `findie_search`.
Snapshot mới hơn thắng; cùng version/hash là replay hợp lệ, cùng version khác hash là
conflict. Kiểm lại watermark/source trước commit embedding lâu. ACK command/parts chỉ sau
receipt được broker confirmed và routed. Crash giữa các parts cho phép replay cùng snapshot;
payload tạm từng lease có deadline và retention, không chờ vô hạn.
Ẩn/gỡ/thu hồi duyệt/xóa làm snapshot hoặc tombstone bỏ cả vector và từ khóa OCR tương
ứng. Cache OCR nội bộ theo vòng đời cache vector: bỏ khi từ chối, gỡ ảnh hoặc xóa món.

Khi `AI_IMAGE_SEARCH_ENABLED=false`, worker vẫn nhận/kiểm mọi part vector hoặc hash/MIME/
decode part ảnh trong full manifest trước receipt, nhưng chỉ ghi projection `text-v1`. Watermark và
snapshot hash giữ nguyên full snapshot; tin có ảnh vẫn tìm được bằng text. Bật tìm ảnh
rồi reindex cùng version/hash sẽ bổ sung vector ảnh tương thích, không cần sửa outbox
payload. Nguồn không có cache dùng ảnh đã che; muốn vector từ ảnh gốc phải upload lại.

Receipt: `Type` và metadata `kind` là `index.upsert|index.remove`, persistent tới durable
result queue; metadata echo toàn bộ job/lease/item/document/hash/model/dimensions và thêm
`schemaVersion:1,succeeded:true,committed:true`; không cần body ảnh. `committed:true` có
nghĩa Python **đã commit** search transaction, không đồng nghĩa .NET đã commit.

.NET khóa item rồi job, kiểm receipt và lease hiện hành, version/source current; đánh dấu
`succeeded` hoặc `obsolete` rồi commit, **sau đó ACK**. Receipt đến sau khi mất waiter hoặc
restart vẫn được xử lý từ durable queue. Lease cũ/trùng/đã hết hạn được chủ đích bỏ/ACK,
không hoàn tất lease mới. Poison/DB lỗi ở đường receipt orphan được NACK không requeue
vào DLX hữu hạn; job vẫn bền vững để lease/retry phục hồi. Không requeue nóng vô hạn.

Broker/storage lỗi thành retry với backoff `5 * 2^attempt` giây, tối đa 3 attempt;
invalid result thành failed. Lease running hết hạn được lấy lại; hết attempt thành failed.
Snapshot không còn current được obsolete. Failed job cần vận hành xử lý/reindex có chủ
đích, không tạo job mới vô hạn để né giới hạn. Không có admin/retry endpoint công khai.

## Cleanup output

Cleanup kiểm tra ngay khi API khởi động và sau đó mỗi 10 phút, mỗi lượt xử lý tối đa một
object; việc kiểm tra outbox vẫn chạy mỗi 2 giây.

Reservation chỉ được tạo sau output hợp lệ, hết hạn sau một giờ. Khi gỡ ảnh, bỏ liên kết
và đánh dấu object delete_pending cùng transaction. Cleanup chỉ claim object không được
image tham chiếu, khóa object rồi commit trước R2 delete. Attachment khóa/reload object và
từ chối reservation đã hết hạn/đang dọn. Retry delete tối đa 5 lần, đặt hạn thử lại sau 2–8 phút
và xử lý ở lượt cleanup kế tiếp; sau giới hạn giữ error metadata để vận hành xử lý.
Không dọn original vì không có original.

## Nguồn kỹ thuật và kiểm chứng

Adapter dùng [RabbitMQ .NET client API](https://www.rabbitmq.com/client-libraries/dotnet-api-guide)
và [confirms/acknowledgements](https://www.rabbitmq.com/docs/confirms).
[BrokerChecks.cs](../../apps/api/tests/integration/BrokerChecks.cs) kiểm request/reply trên broker
thật dùng một lần; [ImageSearchChecks.cs](../../apps/api/tests/integration/ImageSearchChecks.cs)
kiểm DB/outbox/output bằng adapter doubles. Worker Python được kiểm riêng với broker/PostgreSQL thật ở `make ai-integration`; model là HTTP stub. ACL/TLS môi trường triển khai, R2 thật và benchmark mô hình chưa được nghiệm thu qua các test này.
