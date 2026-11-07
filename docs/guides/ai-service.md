# AI service: văn bản, xử lý ảnh và tìm ảnh qua gateway Colab

Cập nhật 05/11/2026. Python nhận lệnh qua RabbitMQ, gọi gateway tương thích API Ollama, sở hữu database `findie_search` và trả ứng viên để .NET kiểm lại quyền/nguồn/phiên bản. FastAPI chỉ phục vụ health/status nội bộ. Web, API, worker, PostgreSQL và broker ở local; chỉ model inference chạy từ xa.

## Khởi tạo kho tìm kiếm và chạy local

```sh
make local-setup
```

Lệnh cài dependency theo lock, khởi động PostgreSQL/RabbitMQ/Redis loopback, migrate database nghiệp vụ, tạo database/role tìm kiếm riêng, migrate schema và cấp DML cho role runtime. Chạy lại giữ dữ liệu và credential; nếu bootstrap cũ có dữ liệu, migration dừng thay vì xóa. Không tự di trú DSN trỏ host/database/role tùy chỉnh. Hub demo được tạo nhưng không tạo tài khoản giả.

Điền Google OAuth/R2 private trong `.env` như README. OAuth redirect: `http://127.0.0.1:5173/api/auth/google/signin`.

## Model trên Colab qua ngrok

Upload [notebook 04](../../notebooks/colab/04_full_stack_ollama_ngrok.ipynb) vào [Colab](https://colab.research.google.com/), chọn GPU và chạy các cell từ trên xuống. Notebook cần `NGROK_AUTHTOKEN` của tài khoản ngrok và `FINDIE_OLLAMA_TOKEN` do bạn chọn (ASCII ngẫu nhiên tối thiểu 32 ký tự). Dùng Colab Secrets hoặc ô nhập ẩn; giữ token thứ hai để nhập lại trên local, không ghi vào cell/chat/git.

Notebook tải model embedding qua Transformers và cài Ollama release/checksum đã ghim cho model nhận diện vùng:

| Model | Vai trò | Cấu hình full mode |
| --- | --- | --- |
| `Qwen/Qwen3-VL-Embedding-2B` | Embedding văn bản và ảnh riêng qua Transformers | 2048 chiều, FP16, SDPA, L2; instruction truy vấn rỗng |
| `qwen3-vl:4b-instruct` | OCR chữ nhìn thấy và gợi ý vùng nhạy cảm qua hai request riêng | JSON schema chặt, temperature 0 |

Dùng đúng tag `-instruct` để trả JSON trực tiếp. Bản Qwen3-VL Thinking không hỗ trợ
tắt suy luận bằng `think:false`; cần chọn biến thể model theo [hướng dẫn của maintainer Ollama](https://github.com/ollama/ollama/issues/13353).
Khi chuyển model nhận diện vùng, chạy lại notebook, nhập cấu hình để đồng bộ tên/digest
giữa API và worker, rồi khởi động lại hai service.

Model/processor Qwen và mã inference official được ghim tại commit `9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda`, cùng cách lấy token cuối không padding đã kiểm SHA-256 trong notebook 01. Gateway xử lý `/api/embed` bằng Transformers, nhận văn bản, `{image: base64}` hoặc `{image: base64, text: OCR}`. Với input chung, ảnh và chữ vào cùng một lượt model; không cộng trung bình hai vector. `/api/generate` chuyển tới Ollama cho OCR hoặc redaction theo schema request. System instruction Qwen giống nhau cho các loại input; `AI_EMBEDDING_QUERY_INSTRUCTION` để rỗng để local không thêm instruction khác. Xem [model card Qwen](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B/tree/9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda).

`AI_EMBEDDING_REVISION` là SHA-256 của manifest JSON chuẩn hóa gồm commit model/processor, hash mã inference đã kiểm, profile và phiên bản gói đã ghim. Đây là fingerprint cấu hình Qwen, không phải digest manifest Ollama. Gateway công bố cùng giá trị qua `/api/tags` để importer và hai service kiểm identity. `AI_REDACTION_REVISION` vẫn là digest manifest Ollama. Cấu hình cũ `qwen3-embedding:4b`/2048 vẫn chạy văn bản; không bật tìm ảnh cho model text-only, không dùng caption/OCR thay embedding ảnh.

Với `AI_IMAGE_SEARCH_ENABLED=false`, vẫn có thể xử lý/duyệt ảnh nếu đã cấu hình model redaction.
`image.embed` trả JSON `null`, không tạo cache vector ảnh gốc. Worker kiểm đầy đủ manifest
và mọi part, nhưng chỉ ghi vector text cùng watermark/hash gốc; tin có ảnh vẫn tìm được
bằng mô tả. Khi bật tìm ảnh, `make local-reindex` dùng cache tương thích nếu có hoặc
embed bản che đối với nguồn không có cache. Muốn embedding ảnh gốc cho các nguồn này
phải tải lại ảnh gốc; hệ thống không giữ bytes gốc để khôi phục.

Trước khi mở tunnel, notebook kiểm model digest, capabilities, embedding text/ảnh/ảnh+chữ và JSON vision trên ảnh tổng hợp, warm cả hai model. Gateway full mode công bố `embedding,vision,image_text`; Findie chỉ dùng `embedding,vision` cho model embedding. Gateway chỉ mở `/api/tags`, `/api/show`, `/api/embed`, `/api/generate` cho model được chọn, bắt buộc Bearer token, giới hạn body/concurrency và tắt access log/traffic inspection. Không expose trực tiếp Ollama, FastAPI, DB hay broker. [Ngrok có hướng dẫn Bearer authentication cho Ollama](https://ngrok.com/docs/gateway/examples/ollama).

Tải `findie-colab.json` ở cell export; file chỉ chứa URL và cấu hình model, **không chứa token**:

```sh
python3 scripts/configure_ollama.py /duong-dan/findie-colab.json
make local-run
```

Lệnh import hỏi cùng `FINDIE_OLLAMA_TOKEN`, kiểm endpoint/token/digest rồi cập nhật `.env` atomically với quyền 0600, đồng bộ model/revision/chiều/profile của .NET/Python. Không thay credential Google/R2/database. URL đổi thì tải/import JSON mới, `Ctrl+C` và chạy lại `make local-run`.

`local-run` đợi worker/model ready trước khi chạy API/web, báo URL `http://127.0.0.1:5173`. `Ctrl+C` dừng đúng web/API/worker của phiên; `make local-stop` dừng DB/broker/Redis và giữ volume database/broker.

Colab có quota/thời lượng và hạn chế proxy/web services, nhất là tài nguyên miễn phí; đọc [FAQ](https://research.google.com/colaboratory/faq.html) và dùng gói/môi trường cho phép. Notebook phục vụ phiên tương tác do bạn chủ động vận hành, không có keepalive hay cơ chế né giới hạn. Nếu Colab không cho phép mục đích sử dụng này, chạy cùng notebook trên Jupyter GPU bạn kiểm soát. Không cam kết Colab/ngrok luôn sẵn sàng.

## Cấu hình và readiness

| Biến | Ý nghĩa |
| --- | --- |
| `AI_SERVICE_TOKEN` / `Ai__ServiceToken` | Token riêng local .NET↔FastAPI, không gửi lên Colab |
| `AI_SEARCH_DSN` | Role runtime `findie_search_app`, không có quyền DB nghiệp vụ |
| `AI_SEARCH_MIGRATION_DSN` | Role migration riêng cho bước DDL; không dùng cho worker |
| `AI_REDIS_URL` | Redis cache ứng viên từ khóa/vị trí; mặc định local `redis://127.0.0.1:6379/0`, để rỗng để tắt; ngoài loopback cần `rediss://` |
| `AI_SEARCH_CACHE_TTL_SECONDS` | TTL cho cache từ khóa/vị trí, mặc định 60 giây, hợp lệ 1–3600 |
| `AI_SEARCH_SEMANTIC_WEIGHT` | Tỷ trọng ngữ nghĩa của hybrid search, mặc định `0.6` (60% ngữ nghĩa / 40% từ khóa), hợp lệ 0–1; từ khóa bằng `1 - giá trị`. Sửa trong `.env` rồi khởi động lại worker. |
| `REDIS_PORT` | Cổng Redis Compose chỉ bind loopback, mặc định 6379 |
| `AI_RABBITMQ_URL` / `RabbitMq__Uri` | Hai tài khoản runtime broker tách biệt |
| `OLLAMA_BASE_URL` / `OLLAMA_API_KEY` | HTTPS gateway ngrok và token riêng của phiên |
| `AI_EMBEDDING_MODEL`, `AI_EMBEDDING_REVISION`, `AI_EMBEDDING_DIMENSIONS` | Model, SHA-256 fingerprint cấu hình Qwen (hoặc manifest Ollama với model cũ) và số chiều; import đồng bộ sang .NET |
| `AI_EMBEDDING_QUERY_INSTRUCTION` | Instruction truy vấn; full notebook để rỗng |
| `AI_REDACTION_MODEL`, `AI_REDACTION_REVISION` | Model vision và digest; đồng bộ `Ai__RedactionModelId`/`Ai__RedactionRevision` |
| `AI_IMAGE_SEARCH_ENABLED` | Bật sau khi xác nhận model embedding nhận ảnh |
| `AI_TEXT_SEARCH_PROFILE`, `AI_IMAGE_SEARCH_PROFILE` | `text-description-v1`, `image-only-v1`, khớp .NET |

Chỉ một Python process, không dùng nhiều Uvicorn workers với queue exclusive. Ngoài loopback cần HTTPS/token cho Ollama và AMQPS cho broker. Token Colab không phải token ngrok hay AI_SERVICE_TOKEN.

Web chờ tối đa 11 phút (660 giây) cho toàn bộ upload. `image.embed` đọc OCR và tạo vector
riêng từ ảnh chưa che, có deadline 300 giây; `image.redact` có deadline riêng 300 giây.
Tìm một ảnh có deadline AI 300 giây; text/index vẫn 30 giây. Tìm nhiều ảnh/mô tả dùng
một RPC `search.hybrid.images`, ngân sách AI chung 940 giây, web chờ 960 giây.
Python chạy tuần tự từng ảnh (tối đa 300 giây/ảnh), mô tả (tối đa 30 giây), rồi gộp RRF.
Việc ghép OCR với mô tả diễn ra trong worker local. Nếu gateway đang hoạt động thì chỉ
cần khởi động lại worker sau khi cập nhật Findie.
Nếu URL ngrok thay đổi, tải JSON mới và import lại bằng `scripts/configure_ollama.py`;
sau đó khởi động lại API/worker để áp dụng cấu hình.

```sh
make local-doctor
```

Doctor kiểm schema hai DB, Hub/staff, các queue có consumer, identity model đang chạy, capability AI và API dependency status. Liveness HTTP 200 không đồng nghĩa model/schema đã sẵn sàng. Google/R2 được ghi rõ chỉ configured; cần flow thật dưới đây để xác minh credential/ACL.

Một lượt readiness của worker có ngân sách tổng 12 giây cho kết nối database tìm kiếm,
kiểm model/capability và embedding kiểm tra khi cần. API chờ tối đa 15 giây khi gọi
health của worker; doctor chờ tối đa 20 giây cho HTTP để không cắt lượt kiểm hợp lệ.
Các giới hạn này dành cho health, không thay deadline của upload, tìm kiếm hay lập chỉ mục.

## Cache từ khóa bằng Redis

Python dùng khóa `findie:search:v1:keyword:<sha256>` để lưu ứng viên FTS và vị trí trước khi hợp nhất thứ hạng bằng RRF. Khóa dùng từ khóa tiếng Việt đã chuẩn hóa và tách theo database, model, phiên bản chỉ mục, bộ lọc ngày và nguồn text/image được phép. Cache lưu tối đa 200 ứng viên cho mỗi danh sách FTS và vị trí, kể cả kết quả rỗng. Mỗi lượt tra cache đọc UUID phiên bản chỉ mục từ PostgreSQL.

Khi trúng cache từ khóa, worker dùng lại hai danh sách này và vẫn chạy truy vấn xếp hạng vector cho nhánh ngữ nghĩa. Tìm bằng ảnh đi thẳng qua nhánh vector.

`ai_search_state` giữ một UUID, thay trong cùng transaction với mỗi upsert/remove chỉ mục, kể cả replay bổ sung vector ảnh. Khóa cũ mất hiệu lực sau commit và tự hết TTL; rollback giữ phiên bản cũ. Cách này vẫn vô hiệu hóa đúng khi Redis bị ngắt, khi nhiều worker dùng chung cache hoặc khi truy vấn cũ hoàn thành sau một lần cập nhật. Không dùng `FLUSHDB` hay quét xóa khóa toàn Redis.

Redis chỉ giữ ID/phiên bản/hash nguồn và tín hiệu vị trí cần cho RRF; không giữ câu tìm kiếm gốc, vector truy vấn, ảnh, OCR, mô tả hay DTO riêng từng người dùng. .NET luôn đọc và kiểm điều kiện hiển thị/quyền hiện tại. Không cache lỗi AI/DB. Redis lỗi, timeout hoặc payload sai thì bỏ qua cache và tìm trong PostgreSQL; cache không quyết định readiness của AI. Client async dùng kết nối chung, timeout hữu hạn và đóng lúc worker dừng theo [hướng dẫn redis-py](https://redis.io/docs/latest/develop/clients/redis-py/async/).

Compose dùng Redis 8.2.3, giới hạn RAM 128 MiB với `allkeys-lru`, tắt snapshot/AOF và không mount volume. Cấu hình này dành cho local; không mở cổng Redis ra Internet.

Với checkout đã cài trước khi có Redis:

```sh
python3 scripts/init_env.py
uv sync --project services/ai --locked
docker compose up -d --wait redis
make ai-migrate
```

Sau đó khởi động lại worker (`make ai` hoặc dừng/chạy lại `make local-run`). Migration thêm `ai_search_state`, không xóa dữ liệu tìm kiếm. `make local-setup` mới tự thực hiện đầy đủ các bước trên.

Kiểm thử cache nhanh và tích hợp hạ tầng thật:

```sh
uv run --project services/ai --locked pytest services/ai/tests/test_search_cache.py -q
make ai-integration
```

Runner tích hợp tự tạo/dọn PostgreSQL, RabbitMQ và Redis riêng với cổng ngẫu nhiên; kiểm TTL thật, hit/miss của cache từ khóa, xếp hạng vector khi trúng cache từ khóa, vô hiệu hóa sau update/tombstone, rollback và Redis mất kết nối. Model là HTTP stub.

## Luồng ảnh và tìm kiếm

Web dùng chung bước [chuẩn bị ảnh](../api/media-search.md) cho upload và mọi truy vấn
ảnh: kiểm file gốc/animation, đọc hướng EXIF, giới hạn cạnh dài 1600 px và tạo JPEG
quality 0.92 với nền trắng, giữ tỷ lệ, không phóng lớn/cắt/làm nét/khử nhiễu. Giữ file
gốc nếu đã trong 1600 px và JPEG không nhỏ hơn; dùng lại cùng bytes theo `File` khi retry.
Bước này giảm tải truyền ảnh; API trực tiếp và kiểm tra server vẫn giữ nguyên.

1. .NET kiểm quyền/byte rồi gửi ảnh chưa che qua `image.embed` tạm, nonpersistent, có TTL,
   không DLQ raw. Khi capability ảnh bật, Python chuẩn hóa, OCR bằng model vision và
   tạo vector riêng từ ảnh chưa che. OCR profile `ocr-v1` trả text tối đa 3000
   ký tự cùng `hasUnclearText`; giữ nguyên số 0 đầu, bỏ chữ không rõ thay vì đoán, không
   giải QR/barcode hoặc làm theo lệnh in trên ảnh.
2. .NET gửi cùng ảnh chưa che qua `image.redact`. Python kiểm JPEG/PNG/WebP, MIME thật,
   tối đa 10 MiB, 40 triệu pixel/cạnh 10000, từ chối animation. Áp dụng EXIF orientation,
   giảm cạnh tối đa 1600px, bỏ EXIF/GPS, flatten alpha và encode PNG mới.
3. Vision model trả bbox/nhãn theo schema, không OCR text; Python validate tọa độ hữu hạn
   0..1000/thứ tự/nhãn/số vùng rồi OpenCV che theo quy tắc `redact-v4` bên dưới.
   Model/JSON lỗi làm cả request thất bại; không dùng raw làm output. Không PII vẫn re-encode.
4. .NET chỉ lưu output hợp lệ lên R2 private và cache vector/model/revision/chiều/hash gốc
   cùng OCR có provenance model/profile riêng trong `item_images.original_embedding`
   jsonb nội bộ. Bytes gốc bị bỏ. Người có quyền
   xem và duyệt bản che; ảnh chưa duyệt không công khai/index. Nội dung tin được giữ khi
   xử lý ảnh lỗi. Cache không được xuất trong DTO và bị bỏ khi từ chối, gỡ ảnh/xóa món đồ.
   Nguồn text ghép tiêu đề, mô tả và khu vực hiện hành với OCR đã lưu của ảnh được duyệt.
   Sửa mô tả lập lại vector text mà không cần giữ ảnh gốc.
5. Worker ghép và kiểm manifest text + tối đa 5 nguồn ảnh đã duyệt theo job/lease, hash
   và deadline. Nguồn có cache dùng `index.source.vector`, kiểm checksum payload và model;
   nguồn cũ/không có cache vẫn dùng `index.source.image` từ bản che. Hash nguồn công khai
   luôn gắn với output đã duyệt, không thay bằng hash ảnh gốc. Ghi các vector được bật và
   watermark/hash của full snapshot trong một transaction, receipt sau commit, ACK sau
   broker confirm/route. Snapshot cũ sau tombstone không phục hồi dữ liệu.
   OCR không nằm trong snapshot outbox; chỉ cache part của ảnh đủ điều kiện mới đưa
   OCR vào vector và từ khóa của hàng `text-v1` nội bộ. Nếu gateway từ chối văn bản
   ghép do quá giới hạn đầu vào, thử lại với văn bản công khai và giữ đủ OCR ở nhánh từ khóa.
   Nguồn ảnh cũ giữ cache hiện có;
   tải lại ảnh gốc để bổ sung OCR còn thiếu hoặc thay vector ảnh/OCR cũ bằng vector ảnh riêng.
6. Text dùng semantic + PostgreSQL FTS + tín hiệu vị trí; khi capability ảnh bật, xét
   cả nguồn mô tả có OCR `text-v1` và nguồn ảnh riêng `image-v1`. Tìm bằng ảnh chỉ tạo
   vector từ ảnh truy vấn. Mô tả tìm kiếm bổ sung vẫn là một nhánh text riêng.
   Với nhóm 1–3 ảnh và mô tả tùy chọn, Python gộp các danh sách bằng weighted RRF:
   mỗi nhánh ảnh hệ số 1, nhánh mô tả hệ số 0.5, nhánh text bên trong vẫn ngữ nghĩa/từ khóa
   mặc định 60/40. Món được cả nhánh ảnh và mô tả tìm thấy xếp trước, rồi chỉ ảnh,
   cuối cùng chỉ mô tả; từng nhóm xếp giảm dần theo tổng điểm/điểm ảnh/điểm mô tả tương ứng.
   Phân nhóm theo nhánh truy vấn, không phải loại nguồn tài liệu; mỗi món chỉ xuất hiện một lần.
   Python giữ tối đa 200 ứng viên mỗi nhánh và trả toàn bộ pool đã gộp, tối đa
   `200 * số nhánh` (không quá 800), cùng ba điểm nội bộ và toàn bộ nguồn góp điểm;
   text/ảnh đơn trả tối đa 200 ứng viên. Body ứng viên AMQP giới hạn 1 MiB.
   API nhận đủ pool để cộng ưu tiên khu vực trước khi cắt kết quả cuối còn tối đa 10 món.
   .NET kiểm nghiệp vụ, bộ lọc ngày và document/source version/hash của từng nguồn;
   nguồn nào không hợp lệ thì loại cả ứng viên. `area` là khu vực ưu tiên cho tìm text/ảnh,
   không lọc cứng: món khớp chuỗi khu vực không phân biệt hoa thường được cộng 5% điểm một lần.
   Bonus khu vực và `lostAt` chỉ đổi thứ tự trong nhóm bằng hệ số `(1 + bonusKhuVuc) * (1 + bonusThoiGian)`.
   HTTP giữ DTO chỉ có rank; `filtersRelaxed:true` khi có món hiển thị ngoài khu vực ưu tiên.
   Khoảng ngày luôn lọc cứng; `GET /api/items?area=...` vẫn lọc cứng khu vực.
   Chưa có điều kiện đối chiếu chính xác toàn bộ số hoặc đuôi CCCD/MSSV: OCR có thể sai,
   và thứ hạng semantic không chứng minh số giấy tờ trùng khớp.

Profile `redact-v4` che khoảng 60% phần đầu của số CCCD/CMND, điện thoại và mã định danh
như MSSV, mã nhân viên, số thẻ/tài khoản, giữ khoảng 40% phần cuối để nhận diện.
Tỷ lệ dựa trên chiều rộng bbox, không OCR/đếm chữ số; chuỗi nghiêng hoặc ký tự không đều
có thể để lại số lượng ký tự khác tỷ lệ này. Khuôn mặt, địa chỉ riêng tư/quê quán, QR và
mã vạch vẫn che toàn bộ như trước; họ tên, ngày sinh, các ngày tháng và thông tin khác
giữ nguyên. Đặt `Ai__RedactionProfile=redact-v4` rồi khởi động lại API/worker sau khi cập
nhật. Prompt/schema được worker gửi trong mỗi request nên không cần tải lại model hoặc
gateway Colab chỉ để đổi cách che. Ảnh đã xử lý giữ nguyên profile và output cũ; muốn
áp dụng cách che mới hoặc tạo lại vector ảnh phải tải lại ảnh gốc. Cache OCR
không tự thay đổi output đã che. Ẩn tin hoặc thu hồi duyệt bỏ cả vector/từ khóa OCR khỏi
chỉ mục; không công khai plaintext OCR trong API, log hay lịch sử query.

Ảnh query và vector query chỉ tồn tại trong RAM/transport tạm, không R2/search DB. OCR của ảnh bài đăng là dữ liệu dẫn xuất nội bộ trong cache và chỉ mục đủ điều kiện, không phải trường mô tả công khai. Broker có thể page message xuống đĩa; TTL/ACK không phải bảo đảm xóa forensic. Chỉ model inference ra khỏi máy local; ảnh gửi model đi qua gateway ngrok/Colab của bạn. Nén JPEG có thể mất chi tiết chữ nhỏ; chưa có benchmark chứng minh tiền xử lý tăng độ chính xác. 1600px và model có thể bỏ sót vùng nhạy cảm nhỏ: phải kiểm output trước duyệt; chưa có cam kết PII recall.

## Hub và nghiệm thu thủ công

Sau lần đăng nhập Google đầu tiên:

```sh
make local-seed STAFF_EMAIL=dia-chi-google-cua-ban
```

CLI Development cấp quyền nhận/trả tại Hub demo cho tài khoản Google đã tồn tại, không đổi hồ sơ hoặc tạo auth bypass. Dùng Google thứ hai để thử claim → duyệt → chat → trao trả; thử riêng intake pending → nhân viên nhận thực tế → trao trả. Dashboard admin đầy đủ và SignalR ngoài phạm vi MVP này.

Để kiểm nhánh ảnh thật: đăng tin có ảnh, kiểm bản che và duyệt, công khai, tìm bằng cả mô tả và ảnh với khu vực ưu tiên và bộ lọc ngày, rồi gỡ ảnh/ẩn tin và xác nhận kết quả cũ không xuất hiện. Kiểm bucket chỉ có output private, không có original. Đây cũng là bước kiểm credential Google/R2 và model thật.

## Đổi model và lập lại chỉ mục

Không trộn vector khác model/digest/chiều/profile. Khi đổi model: dừng `local-run`, import JSON mới, chạy lại, rồi:

```sh
make local-reindex
```

Việc chuyển từ `embeddinggemma-2:440m`/768 sang Qwen/2048 cần chạy lại notebook 04 từ đầu và tải/import JSON mới, không chỉ sửa tên model trong `.env`. Số chiều trùng với model text-only cũ cũng không làm vector tương thích.

Lệnh kiểm worker identity và chỉ phát lại outbox snapshot/tombstone hiện hành, giữ active leases và dữ liệu người dùng; không xóa watermark. Cache embedding ảnh gốc chỉ dùng lại khi model/revision/chiều còn khớp. Nếu thay một trong các giá trị này, lập chỉ mục nguồn có cache sẽ thất bại thay vì âm thầm embed bản che; phải tải lại ảnh gốc để có vector mới. Nguồn cũ không có cache vẫn có thể embed lại từ bản che. Theo dõi trạng thái lập chỉ mục trước dùng kết quả. Nếu job đang có lease, chờ kết thúc/hết hạn rồi chạy lại khi cần. Baseline có cửa sổ bảo trì, không có chuyển model không gián đoạn.
Cache có OCR còn phải khớp model/revision vision và profile OCR hiện hành; không dùng
OCR cũ dưới provenance model mới. Thay model OCR cũng cần tải lại ảnh gốc để tạo cache mới.

## Kiểm chứng

```sh
make check
make api-integration
make ai-integration
```

Test ảnh dùng bytes thật để kiểm mask, metadata/EXIF, MIME, pixel, animation, model failure và digest; DB/broker/Redis tích hợp dùng container tạm, không DB local. Model trong integration là HTTP stub; Google và R2 dùng test double. Notebook được compile/self-check gateway nhưng Colab GPU/ngrok thật cần người sở hữu chạy. Chưa có benchmark chất lượng/VRAM/độ trễ thực tế. Tập dữ liệu có nhãn và `python -m findie_ai.evaluate` vẫn cần trước mọi tuyên bố độ chính xác.
