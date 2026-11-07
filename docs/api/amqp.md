# Hợp đồng .NET ↔ Python qua RabbitMQ

Phiên bản schema 1, cập nhật 05/11/2026. Đây là hợp đồng adapter .NET đã triển khai;
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
| `findie.ai.image` | Python tạo non-durable/exclusive/auto-delete, nonpersistent raw input/query, TTL queue tối đa 940 giây; TTL từng message 300 giây cho embedding/OCR, che và ảnh đơn, 940 giây cho nhóm ảnh; trần 4 message/32 MiB; **không DLX/alternate routing/tracing body** |
| `findie.ai.query` | Python tạo queue text query tạm, non-durable/exclusive/auto-delete, TTL hữu hạn |
| Reply queue do broker sinh | .NET tạo exclusive/non-durable/auto-delete cho output ảnh/query; TTL 60 giây, tối đa 64 message/32 MiB; không DLX |

Có thể đổi tên qua `RabbitMq:IndexQueue|ResultQueue|ImageQueue|QueryQueue`; chỉ server
cấu hình, không nhận route/reply_to từ HTTP client. Định nghĩa durable queues mẫu tại
[rabbitmq-definitions.json](rabbitmq-definitions.json), import bằng công cụ quản trị broker
vào vhost `/` hoặc sửa vhost theo môi trường. File không chứa user/password/permission;
ops cấp tài khoản triển khai và tài khoản API/Python tách biệt. .NET chỉ publish commands,
consume results và khai báo/consume reply queue của mình; Python làm chiều ngược lại.
Không dùng quyền admin cho runtime. Không đưa RabbitMQ ra internet.

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

`BasicProperties`: `Type` là operation bên dưới, `CorrelationId` UUID do .NET tạo,
`ReplyTo` queue do .NET chỉ định, `ContentType`, `Persistent`, `Expiration:"300000"` cho
`image.embed`, `image.redact`, `search.hybrid.image`; `Expiration:"940000"` cho
`search.hybrid.images`; `Expiration:"30000"` cho các operation khác.
Header `metadata` là **bytes JSON UTF-8**, tối đa 16 KiB. Body ảnh nhị phân tối đa 10 MiB,
riêng nhóm ảnh `search.hybrid.images` tối đa 30 MiB;
body text/snapshot/ứng viên JSON UTF-8, không base64. Body vector JSON tối đa 1 MiB,
không đưa vector vào header metadata. Tối đa 32 waiter AI đang chờ;
deadline 300 giây cho ảnh đơn, 940 giây cho nhóm ảnh, 30 giây cho text/index; không giữ DB
transaction khi gọi broker hoặc model/R2.

Broker local đặt `max_message_size=33554432` (32 MiB) trong `scripts/rabbitmq.conf`
để nhận nhóm ảnh 30 MiB; broker triển khai riêng cần cùng giới hạn. RabbitMQ mặc định
giới hạn message 16 MiB theo [tài liệu cấu hình](https://www.rabbitmq.com/docs/configure#config-items).
Sau khi cập nhật cấu hình broker local đang chạy, khởi động lại service `rabbitmq`;
khởi động lại API và worker cùng phiên bản để dùng hợp đồng nhóm ảnh mới.

Metadata request chung: `schemaVersion:1`, `deadlineAt` ISO UTC, định danh model/version
và profile tùy operation. Worker kiểm deadline trước suy luận và trước commit.
Metadata response phải echo định danh/configuration của request, thêm
`kind:<operation>`, `succeeded:true|false`. .NET chỉ hoàn tất đúng correlation còn sống.
Lỗi an toàn `succeeded:false` thành HTTP 503; không trả trace/OCR/dữ liệu worker ra client.

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
giới nội bộ để tránh che mất phần đuôi. Khuôn mặt, địa chỉ riêng tư/quê quán, QR và mã
vạch vẫn che toàn bộ theo quy tắc hiện có. Họ tên, ngày sinh, các ngày cấp/hết hạn,
thông tin học tập khác, bố cục, logo, tên cơ quan và nhãn trường giữ nguyên.
Nhãn vùng là `face`, `identity_number`, `phone`, `identifier_number`, `address`, `qr_code`, `barcode`.
Mỗi `bbox` gồm bốn số nguyên `[x1,y1,x2,y2]` trong khoảng 0–1000 theo toàn ảnh;
mỗi giá trị nhạy cảm hoặc trường địa chỉ đầy đủ có một khung riêng; trường địa chỉ
có thể gồm nhãn và các dòng tiếp theo. Chữ/khuôn mặt thêm viền
2–4 px; QR/mã vạch dùng `max(2, ceil(cạnh_ngắn / 200))`, tức 5–8 px khi cạnh ngắn
là 1000–1600 px, để che kín mép mã khi khung nhận diện hơi thiếu.

Nếu lượt đầu phát hiện địa chỉ, worker lấy vùng bao các khung địa chỉ từ pixel gốc
đã chuẩn hóa, mở rộng mỗi bên ngang 50% chiều rộng và trên/dưới một chiều cao vùng,
để model thấy nhãn trường và ngày tháng lân cận khi xác định ranh giới địa chỉ.
Lượt nhận diện bổ sung chỉ tìm địa chỉ trong vùng cắt, quy đổi khung về toàn ảnh,
giữ cả khung cũ lẫn khung bổ sung và bỏ bản trùng chính xác. Không có khung địa chỉ
thì không gọi lượt bổ sung; hai lượt cùng chịu deadline 300 giây. Lỗi lượt bổ sung
hoặc tổng quá 32 vùng khiến xử lý thất bại; không trả ảnh che dở.

Worker luôn decode, kiểm MIME/frame/pixel, phát hiện PII, che/mờ nếu có, bỏ EXIF và encode
ảnh mới kể cả không có PII. Lỗi model không được coi là ảnh sạch. Response body là output,
metadata echo nguồn/config, thêm `kind:"image.redact",succeeded,contentType,sha256,
byteSize,width,height,sensitiveRegions:[]`. Không trả original key, OCR text riêng tư hoặc
URL bất kỳ. Python không có credential R2.

.NET kiểm hợp đồng/hash/byte và chỉ lưu output. Reply bị trùng/muộn/không còn waiter được
ACK/bỏ; lỗi cuối không đưa original vào DLQ. Crash mất raw thì HTTP client phải tải lại.

## search.hybrid và search.hybrid.image

Text: query queue, body `{text,area,from,until}` JSON. Image: image queue, body raw query
nhị phân, nonpersistent, không R2/job/outbox/vector query bền vững.
Text có deadline 30 giây; ảnh có deadline 300 giây để tạo vector chỉ từ ảnh truy vấn.

Metadata: `schemaVersion,modelId,modelRevision,processingProfile,searchProfileId,
searchProfileVersion:1,mode,area,from,until,limit,candidateLimit:200,deadlineAt`.
Processing profile `text-v1|image-v1`; cấu hình text-only giữ `qwen3-embedding:4b`/2048. Notebook full mode chọn `Qwen/Qwen3-VL-Embedding-2B`/2048, nhận ảnh native qua Transformers sau gateway tương thích Ollama. `modelRevision` là SHA-256 fingerprint của commit model/processor, mã inference, profile và gói đã ghim; không phải manifest Ollama. `modelId`, revision và số chiều phải đồng bộ hai service; không dùng model text cho ảnh.
Gateway full mode cần công bố `embedding,vision` cho model embedding và `completion,vision` cho model OCR.
Text profile mặc định `text-description-v1`, image `image-only-v1`. Đây là baseline,
chưa có benchmark/phân loại profile theo độ đặc thù query.
Khi capability ảnh bật, text query xét cả vector mô tả đã ghép OCR và vector ảnh riêng,
hợp nhất với từ khóa trên nguồn văn bản. Tìm ảnh dùng vector ảnh; không
thêm điều kiện chính xác theo số hoặc đuôi số. OCR/embedding vẫn có thể nhận sai ký tự.
Hybrid text dùng weighted RRF `weight / (60 + rank)` với hệ số mặc định 1.2 ngữ nghĩa,
0.8 từ khóa (tỷ trọng 60/40, cấu hình `AI_SEARCH_SEMANTIC_WEIGHT`) và 0.03 vị trí.
`area` là ưu tiên, không lọc ứng viên trong Python. .NET cộng 5% điểm một lần cho món
có `foundArea` chứa khu vực yêu cầu, không phân biệt hoa thường; `from/until` vẫn lọc cứng.

Response metadata echo model/profile, thêm kind/succeeded. Body tối đa 1 MiB:

```json
{
  "candidates": [
    {
      "itemId": "<uuid>",
      "documentVersion": 5,
      "sourceId": "<itemId cho text, imageId cho image>",
      "sourceKind": "image",
      "sourceVersion": 2,
      "sourceSha256": "<64 lowercase hex>"
    }
  ]
}
```

Tối đa 200 candidate trả cho .NET, thứ tự là rank đã tính tại Python; không trả vector.
`candidateLimit` hợp lệ từ 1–200; API yêu cầu 200 để cộng ưu tiên khu vực trước khi cắt
kết quả cuối còn `limit=1..10`. Các pool truy hồi nội bộ cũng tối đa 200 mỗi kênh.
Python có thể thêm hạng/điểm dense/keyword/RRF để chẩn đoán, API hiện chỉ xuất rank.
.NET kiểm lại toàn bộ eligibility, document/source version/hash và bộ lọc ngày trước DTO;
`sourceKind:"text"|"image"` xác định nguồn thật, độc lập với chế độ query, để text query
trúng OCR vẫn được đối chiếu hash/phiên bản ảnh đã duyệt. Không tự nới ngày hoặc refill
vô hạn. HTTP `filtersRelaxed:true` chỉ khi kết quả hiển thị có món ngoài `area` đã yêu cầu.
Không coi RRF/cosine là xác suất sở hữu.

## search.hybrid.images

Một RPC cho nhóm 1–3 ảnh và mô tả tùy chọn. Route `findie.ai.image`, nonpersistent,
`ContentType:application/octet-stream`, deadline/TTL 940 giây. Body là bytes các ảnh
nối liên tiếp theo thứ tự `images`; mỗi ảnh tối đa 10 MiB, tổng tối đa 30 MiB.
Không base64, tệp tạm, R2 hoặc outbox. Metadata bổ sung:

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
  "candidateLimit": 400,
  "deadlineAt": "<UTC timestamp>",
  "cacheScope": "<actor UUID>",
  "text": "Ví màu đen",
  "images": [{"contentType": "image/jpeg", "length": 12345}]
}
```

Không có mô tả: `mode:image`, `searchProfileId:image-fusion-v1`. `candidateLimit` hợp lệ
1–800; API yêu cầu `200 * (số ảnh + số nhánh text)` để giữ toàn bộ pool đã gộp trước bonus.
Ví dụ trên có một ảnh và một nhánh text nên yêu cầu 400. Worker kiểm số ảnh,
MIME/length từng phần và tổng length khớp body trước suy luận. Python tìm từng ảnh
tuần tự với deadline 300 giây/ảnh, chạy text hybrid tối đa 30 giây nếu có mô tả,
rồi gộp weighted RRF: mỗi ảnh có hệ số 1, nhánh text có hệ số 0.5, đóng góp
`weight / (60 + rank)` với rank bắt đầu từ 1. Một món chỉ góp điểm một lần trong mỗi
danh sách và xuất hiện một lần trong kết quả. Một nhánh lỗi làm cả request thất bại.
`imageScore` là tổng đóng góp từ các nhánh truy vấn ảnh, `textScore` là đóng góp từ
nhánh truy vấn text; `score = imageScore + textScore`. Phân nhóm theo nhánh truy vấn,
độc lập với `sourceKind` của nguồn đã trúng.

Thứ tự nhóm: có cả `imageScore > 0` và `textScore > 0` trước, chỉ ảnh tiếp theo,
chỉ text cuối cùng. Trong từng nhóm xếp giảm dần theo `score`, `imageScore` hoặc
`textScore` tương ứng. .NET giữ thứ tự nhóm, chỉ điều chỉnh điểm trong nhóm bằng
bonus khu vực và thời điểm mất trước khi giới hạn kết quả.

Response metadata echo cấu hình, thêm `kind:search.hybrid.images,succeeded`; không
echo `text`, `images` hoặc `cacheScope`. Body JSON tối đa 1 MiB; mỗi danh sách truy hồi
nội bộ giữ tối đa 200 ứng viên, nên union sau fusion tối đa `200 * số nhánh`, không quá
800. Trả toàn bộ pool này để cộng ưu tiên khu vực trước khi cắt kết quả cuối ở .NET:

```json
{
  "candidates": [{
    "itemId": "<uuid>",
    "score": 0.02459016393442623,
    "imageScore": 0.01639344262295082,
    "textScore": 0.00819672131147541,
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

`sources` chứa mọi nguồn đã góp điểm, được bỏ ref trùng, tối đa số nhánh (4).
Mỗi ref giữ cả document version để không dùng đóng góp từ snapshot cũ. .NET kiểm
các điểm hữu hạn/không âm, tổng điểm dương bằng điểm ảnh cộng điểm text, thứ tự nhóm
và provenance, rồi đọc dữ liệu nghiệp vụ để kiểm từng nguồn. Nếu bất kỳ nguồn góp
điểm không còn hợp lệ, loại cả ứng viên. .NET không tính lại RRF; điểm Python được
nhân với `(1 + bonusKhuVuc) * (1 + bonusThoiGian)` trong từng nhóm, sau đó giới hạn 1–10 kết quả
và dựng DTO HTTP chỉ chứa rank. Bonus khu vực tối đa 5%, áp dụng một lần mỗi món;
ngày vẫn lọc cứng. Không refill; input bị bỏ khi thành công, lỗi hoặc hủy.

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
