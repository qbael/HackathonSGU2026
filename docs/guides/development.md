# Findie

Nền tảng tìm và trao trả đồ thất lạc. Đã khởi tạo môi trường phát triển dựa trên
[đặc tả](../product/DAC_TA_FINDIE.md), [kiến trúc](../architecture/system-architecture.md) và
[hiến chương](../../.specify/memory/constitution.md). Đây là bộ khung có thể chạy;
API .NET đã có đăng/sửa/ẩn tin, bộ lọc, claim/chat, tiếp nhận/trao trả, adapter AMQP/R2,
outbox và cleanup theo controller → service → repository. Từng endpoint, cấu hình và
kiểm thử tại [API](../api/README.md). Worker Python và search database đã có cho văn bản và ảnh qua Ollama; xem [AI service](ai-service.md).
Kiến trúc đích v1.4.0 ngày 23/10/2026 dùng Python cho toàn bộ AI/ảnh, lưu embedding và
hybrid search; .NET giữ nghiệp vụ, R2, job/outbox, quyền hiện tại và DTO cuối. RabbitMQ/AMQP
lâu dài truyền lệnh/kết quả, lập/xóa chỉ mục và truy vấn/ứng viên. Một PostgreSQL instance
có hai database logic: `findie` chỉ .NET truy cập; `findie_search` dùng pgvector, FTS và bản
chiếu tìm kiếm công khai chỉ Python truy cập. Python dùng FTS PostgreSQL + cosine chính
xác + weighted RRF theo profile cấu hình từng trường hợp; ảnh không có văn bản chỉ dùng
vector và bộ lọc. Chất lượng cần được đo theo từng trường hợp trước nghiệm thu.
Ảnh gốc chỉ tạm trong RAM .NET/Python, không lưu R2. Python phát hiện PII thì che/mờ;
không có PII vẫn chuẩn hóa và mã hóa lại ảnh sạch. .NET chỉ lưu ảnh đầu ra vào R2 riêng
tư; con người duyệt trước công khai. Dữ liệu gốc bị bỏ sau xử lý/lỗi/deadline, mất payload
phải tải lại. Outbox bền vững giữ metadata/chỉ mục, không giữ bytes gốc; payload ảnh tạm
qua RabbitMQ có TTL và quy trình dọn riêng, không đồng nghĩa broker chỉ dùng RAM.
Hướng dẫn dưới đây mô tả bộ khung đang chạy: Compose có PostgreSQL 17 và RabbitMQ 4.3.2, lược đồ .NET tạo bằng EF migrations,
HTTP tới FastAPI chỉ kiểm tra trạng thái; migration tạo schema `findie` với role runtime
giới hạn quyền. Adapter RabbitMQ/consumer .NET đã có; database Python `findie_search`, worker text/ảnh và tìm ảnh native đã có; .NET/Python chỉ giao tiếp AI qua AMQP. Chạy đầy đủ bằng `make local-setup`, import notebook 04 rồi `make local-run`; chi tiết ở [hướng dẫn AI](ai-service.md).
schema mới chưa đồng nghĩa các worker đã hoạt động. Xem [kiến trúc mới](../architecture/system-architecture.md#21-rabbitmq-và-kết-nối-lâu-dài).

## Cấu trúc

```text
apps/
  web/src/             App.tsx và main.tsx là điểm vào; proxy /api trong vite.config.ts
    pages/             Các màn hình nghiệp vụ
    components/        Thành phần giao diện dùng chung
    hooks/             React hooks dùng chung
    lib/               API, xác thực, xử lý dữ liệu và test tương ứng
    styles/, assets/   CSS, font và hình ảnh
  api/                 .NET 10 + EF Core/Npgsql + Identity; model/repository/service/controller
    tests/integration/ Kiểm thử API, xác thực, nghiệp vụ, ảnh và broker
services/
  ai/                  FastAPI nội bộ và worker tìm kiếm văn bản qua Ollama
notebooks/
  colab/               Ba notebook standalone: Qwen Embedding, Instruct/OpenCV và Ollama
docs/                  Toàn bộ tài liệu, hồ sơ triển khai và tư liệu demo
  product/, architecture/, database/, api/, guides/
  design/, specs/, assets/, demo/
scripts/init_env.py     Tạo .env riêng, không ghi đè cấu hình đã có
scripts/db/            Migration .NET có kiểm tra dữ liệu cũ; provisioning DB tìm kiếm/role
tests/                 Kiểm tra bootstrap và notebook
compose.yaml           PostgreSQL 17 + pgvector và RabbitMQ; volume dữ liệu, chỉ bind loopback
Makefile               Lệnh cài đặt, chạy và kiểm tra
```

## Chạy local

Cần Docker Engine + Compose, Node.js 24 (`nvm use`), .NET SDK 10, Python 3.12,
[uv](https://docs.astral.sh/uv/getting-started/installation/) và Make.
Các lệnh trong tài liệu chạy từ thư mục gốc dự án. `uv` dùng Python 3.12 cho dịch vụ AI; nếu thiếu, dùng
`uv python install 3.12` trước khi setup.

```sh
make setup
make db-up
make rabbitmq-up
make db-migrate   # Database mới/EF hoặc bootstrap cũ hoàn toàn rỗng
make db-check
```

`make setup` sinh mật khẩu DB và token nội bộ ngẫu nhiên trong `.env` (quyền `0600`),
cài gói theo lockfile, sinh cấu hình RabbitMQ local và khôi phục công cụ `dotnet-ef`. Chạy lại bổ sung biến còn thiếu,
giữ các bí mật đã có; cấu hình kết nối bootstrap chuẩn được chuyển sang role runtime.
Không đưa tệp này vào Git.
Hai biến `AI_SERVICE_TOKEN` và `Ai__ServiceToken` dùng chung một giá trị qua nội suy;
chỉ cần đổi `AI_SERVICE_TOKEN`. Không dùng biến `VITE_*` cho bí mật.

Mở ba terminal tại thư mục gốc:

```sh
make ai       # Terminal 1: http://127.0.0.1:8000
make api      # Terminal 2: http://127.0.0.1:5080
make web      # Terminal 3: http://127.0.0.1:5173
```

Mở [giao diện local](http://127.0.0.1:5173). React gọi `/api` qua proxy Vite tới .NET;
trình duyệt không gọi FastAPI hay DB trực tiếp. API/FastAPI bind loopback cho local;
chưa cấu hình triển khai internet/HTTPS.

| Endpoint | Ý nghĩa |
| --- | --- |
| `.NET GET /health/live` | Tiến trình API đang chạy |
| `.NET GET /health/ready` | `SELECT 1` DB thành công; lỗi trả 503 |
| `.NET GET /api/system/status` | Trạng thái DB/FastAPI; authentication theo Google, business=true, storage theo cấu hình R2 |
| `.NET /api/auth/google*` | Chỉ đăng nhập Google; xem [API](../api/README.md) |
| `.NET GET /api/auth/csrf`, `POST /api/auth/logout` | CSRF và kết thúc phiên cookie |
| `.NET GET/PUT /api/users/me` | Hồ sơ chính chủ, bắt buộc xác thực |
| `.NET GET /api/reception-points` | Danh sách điểm đang hoạt động, bắt buộc xác thực |
| `FastAPI GET /health/live` | Tiến trình Python đang chạy |
| `FastAPI GET /health/ready` | Cần `X-Service-Token`; kiểm broker, kho tìm kiếm và inference Ollama; thiếu cấu hình/phụ thuộc trả 503 |
| `FastAPI GET /v1/status` | Cần token; model ID, số chiều và `inferenceReady: false` |

AI mặc định chưa sẵn sàng cho đến khi cấp broker, search DSN và digest model. Worker văn bản gọi Ollama qua endpoint cấu hình; notebook 03 thử Ollama loopback trong Colab. Không tự động duyệt ảnh; xem [cấu hình và giới hạn](ai-service.md).

Không dùng Make thì chạy từng lệnh tương ứng trong `Makefile`. Trước chạy API/AI,
nạp cấu hình vào shell: `set -a; . ./.env; set +a`. Chỉ source `.env` do mình kiểm soát.

## Đăng nhập Google

Tạo OAuth client loại **Web application** trong Google Cloud, cấu hình consent screen
và tài khoản thử nghiệm nếu ứng dụng ở chế độ Testing. Thêm authorized redirect URI:

```text
http://127.0.0.1:5173/api/auth/google/signin
```

Điền hai giá trị server trong `.env`, rồi khởi động lại `make api`:

```dotenv
Authentication__Google__ClientId='YOUR_CLIENT_ID.apps.googleusercontent.com'
Authentication__Google__ClientSecret='YOUR_CLIENT_SECRET'
```

Mở đúng `http://127.0.0.1:5173` để đăng nhập; Vite chuyển toàn bộ `/api` tới .NET.
Trang `/` là giao diện tìm đồ; `/search`, `/post`, `/posts`, `/requests`, `/messages`,
`/hubs` và các màn hình chi tiết kết nối với API nghiệp vụ hiện có. Giao diện dùng
Tailwind CSS, font Be Vietnam Pro lưu cục bộ và [bộ màn hình Stitch](../design/stitch/README.md); mã giao diện hiện hành nằm trong `apps/web/src/`.
Đăng nhập tại `/signin` vẫn chỉ dùng Google; không có OTP hoặc định danh công dân giả lập.
Các màn hình nghiệp vụ yêu cầu phiên đăng nhập. Sau OAuth, ứng dụng quay lại đường dẫn
nội bộ đã yêu cầu; menu tài khoản có nút đăng xuất. Trang chủ không cần đăng nhập.
Triển khai production cần cấu hình fallback `index.html` cho đường dẫn ứng dụng.
Proxy giữ nguyên Host của trình duyệt (`changeOrigin: false`) để callback OAuth quay về cổng 5173.
Nếu chọn `localhost`, thêm URI `http://localhost:5173/api/auth/google/signin` và dùng
host đó xuyên suốt. Scheme, host, port và path phải khớp URI đã đăng ký theo
[tài liệu Google](https://developers.google.com/identity/protocols/oauth2/web-server#creatingcred).
Không dùng URL callback port 5080 cho phiên bắt đầu tại 5173.

Ứng dụng chỉ cho Google đăng nhập; không có đăng ký/mật khẩu/refresh của Identity.
Máy chủ cấp cookie `HttpOnly`, `SameSite=Lax`; React lấy hồ sơ và CSRF qua cùng origin,
không giữ token trong localStorage. Client secret không dùng tiền tố `VITE_*` và không
đưa vào mã React. Khi chưa điền đủ hai giá trị, giao diện báo chưa cấu hình và endpoint
bắt đầu đăng nhập trả 503; `authentication: true` chỉ xác nhận đã có cấu hình.

Development cho phép HTTP loopback. Production cần HTTPS, URI callback public chính xác,
Data Protection keys bền vững và dùng chung giữa các instance; triển khai sau reverse proxy
phải cấu hình scheme/host được chuyển tiếp từ proxy tin cậy.

## Database Docker

Compose dùng project `hackathon-findie` và volume `hackathon-findie_postgres_data`,
tách với volume Findie PostgreSQL 16 có sẵn trên máy. Compose không còn tự nạp SQL snapshot.
`make db-migrate` chạy migration tại `apps/api/Data/Migrations`, tạo 22 bảng Identity/nghiệp vụ
(kể cả `index_outbox`), lịch sử EF và role runtime .NET.
Model .NET chỉ lưu tham chiếu processed output, không có bảng vector.
Nguồn lược đồ runtime là EF migrations; [SQL cũ](../database/database-schema.sql) là snapshot đối chiếu.

```sh
docker compose ps
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
make db-check
make db-down
```

`db-check` (cũng là `api-integration`) build API và dùng PostgreSQL **tạm riêng** trong Docker
và RabbitMQ thật để kiểm migration/Google OAuth giả lập/cookie, toàn bộ API nghiệp vụ,
ảnh/search/outbox, concurrency và request/reply broker; tự dọn sau chạy, không ghi DB Compose.
R2/Python trong kiểm thử dùng adapter double; xem [phạm vi kiểm chứng](../api/testing.md).
`db-down` dừng cả PostgreSQL/RabbitMQ/Redis và giữ volume. API không tự chạy migration lúc startup.
Nếu volume có 16 bảng bootstrap cũ, script chỉ thay schema khi đã kiểm tra tất cả bảng rỗng.
Nếu có dữ liệu, lệnh dừng và giữ nguyên DB; cần migration chuyển đổi dữ liệu riêng.
Đổi mật khẩu trong `.env` cũng không tự đổi mật khẩu DB đã tồn tại.

`POSTGRES_USER` là role quản trị dùng cho provisioning/migration; API runtime dùng
`POSTGRES_APP_USER`/`POSTGRES_APP_PASSWORD` trong `ConnectionStrings__Database`.
`SEARCH_POSTGRES_DB`, `SEARCH_POSTGRES_USER`, `SEARCH_POSTGRES_PASSWORD` mô tả database và role tìm kiếm. Provision riêng theo [AI service](ai-service.md), áp schema bằng `make ai-migrate`; runtime dùng `AI_SEARCH_DSN`, chỉ có DML và không truy cập DB nghiệp vụ. FastAPI nạp worker khi đủ DSN/broker/model digest. Trước dùng dữ liệu thật cần
quy trình backup/restore. DDL/ERD bootstrap giữ nguyên để đối chiếu; dữ liệu schema cũ có
phát sinh chưa được chuyển tự động. Không cấp Python quyền DB nghiệp vụ hoặc R2.
Hành vi init và lưu volume theo [tài liệu Docker PostgreSQL](https://docs.docker.com/guides/postgresql/);
image từ [pgvector chính thức](https://github.com/pgvector/pgvector).

## RabbitMQ Docker

RabbitMQ 4.3.2 dùng image management ghim digest trong `compose.yaml`, có volume
`rabbitmq_data`, hostname ổn định và healthcheck kiểm ứng dụng/alarm. Chỉ hai cổng
loopback được publish: AMQP `5672`, Management UI `15672`. Không cần cài RabbitMQ trên host.

```sh
make rabbitmq-up
docker compose ps rabbitmq
docker compose logs --tail=100 rabbitmq
```

`make rabbitmq-up` chạy `make env` để sinh các mật khẩu còn thiếu và file
`.cache/rabbitmq/definitions.json` chứa password hash cùng topology lấy từ
`docs/api/rabbitmq-definitions.json`. File được bỏ qua bởi Git và mount read-only.
Broker tự import khi khởi động: queue quorum `findie.ai.commands`, `findie.api.results`,
queue dead-letter `findie.ai.dead`, exchange và bindings tương ứng. Python tự tạo
query/image queue tạm khi worker chạy; không tạo sẵn hai queue exclusive này.

Nếu chạy trực tiếp bằng Compose, chuẩn bị cấu hình trước:

```sh
make env
docker compose up -d --wait rabbitmq
```

Mở [Management UI](http://127.0.0.1:15672), dùng `RABBITMQ_ADMIN_USER` và
`RABBITMQ_ADMIN_PASSWORD` trong `.env`. API/Python dùng hai user không có tag quản trị,
cấu hình qua `RabbitMq__Uri` và `AI_RABBITMQ_URL` riêng. Python có URI loopback và vhost
`/` (`/%2F` trong URL). `RabbitMq__Uri` mặc định trống: chỉ bật sau khi worker AI đã trả
readiness HTTP 200, tránh các job chỉ mục hết lượt retry khi mới có broker mà thiếu AI.
Sửa dòng sau trong `.env`, đặt sau các biến credential `RABBITMQ_*`, rồi khởi động lại API:

```dotenv
RabbitMq__Uri=amqp://${RABBITMQ_API_USER}:${RABBITMQ_API_PASSWORD}@127.0.0.1:${RABBITMQ_PORT}/%2F
```

URI tùy chỉnh đã có được giữ khi cập nhật `.env`.
Đổi cổng host bằng `RABBITMQ_PORT`/`RABBITMQ_MANAGEMENT_PORT`, chạy lại lệnh up và
khởi động lại API/Python. Credential tự sinh là hex; nếu thay bằng ký tự đặc biệt,
cần URL-encode credential trong URI AMQP.

```sh
make rabbitmq-down
```

Lệnh trên chỉ dừng broker và giữ dữ liệu. `make db-down` dừng toàn bộ Compose, giữ
cả hai volume; `docker compose down -v` sẽ xóa chúng. Không xóa volume để sửa lỗi
credential/queue khi còn dữ liệu cần giữ. Thay `.env` không tự bảo đảm đổi mật khẩu
đã tồn tại trong broker; thực hiện đổi mật khẩu bằng công cụ quản trị nếu cần.

Broker local sẵn sàng chưa đồng nghĩa AI đã sẵn sàng: worker vẫn cần search database
và Ollama/model digest theo [hướng dẫn AI](ai-service.md). Nếu đã bật kết nối API mà worker
không sẵn sàng, job có thể hết retry; quy trình reindex có chủ đích nằm trong tài liệu AI.
Cấu hình này dành cho local;
kết nối broker ngoài loopback phải dùng AMQPS theo [hợp đồng AMQP](../api/amqp.md).

## Thử model trên Google Colab Free

Xem [hướng dẫn notebook](colab.md). Mở từng `.ipynb` bằng
Colab → **Upload notebook**, chọn GPU và chạy cell theo thứ tự:

1. [Qwen Embedding 2B](../../notebooks/colab/01_qwen_embedding.ipynb): mô tả tiếng Việt,
   ảnh, vector 2048 chiều chuẩn hóa và thử xếp hạng cosine trong từng chế độ.
2. [Qwen Instruct 4B + OpenCV](../../notebooks/colab/02_qwen_redaction.ipynb): nạp 4-bit,
   gợi ý vùng nhạy cảm, kiểm tra tọa độ và tạo bản che/mờ để con người duyệt.

Chạy một model mỗi lần, giải phóng/xóa runtime trước đổi notebook. GPU và thời gian chạy
miễn phí không được đảm bảo; xem [Colab FAQ](https://research.google.com/colaboratory/faq.html).
Chỉ dùng ảnh tổng hợp hoặc dữ liệu được phép thử. Không tải credential DB/R2 vào Colab,
không mở API/tunnel công khai. Kết quả là thử nghiệm, chưa xác nhận chất lượng trên dữ liệu Findie.

## Cấu hình và kiểm tra

`.env.example` có DB, AI endpoint/token và cấu hình R2 server. Khi chọn tài khoản R2,
điền `Storage__Endpoint`, `Storage__Bucket`, `Storage__AccessKeyId`, `Storage__SecretAccessKey`;
các giá trị này bật adapter lưu output đã xử lý. Cấu hình thêm `RabbitMq__Uri`,
`Ai__RedactionRevision`, `Ai__EmbeddingRevision` và worker Python theo
[hợp đồng AMQP](../api/amqp.md) để xử lý ảnh/tìm kiếm. Metadata và API nghiệp vụ vẫn chạy
khi AI chưa sẵn sàng. Xác thực dùng Google
OAuth và ASP.NET Core Identity cookie; không có đăng nhập bằng mật khẩu hoặc token bearer.
Các dependency được ghi trong `package-lock.json`, `packages.lock.json`, `uv.lock`;
revision/model inference và gói Colab nằm trong notebook.

```sh
make check       # Bootstrap, notebook, API build/smoke, AI tests, web tests/build
make db-check    # Migration/API/SQL trên PostgreSQL tạm và AMQP trên RabbitMQ tạm; cần Docker
make ai-integration  # Worker Python + PostgreSQL/RabbitMQ/Redis thật, Ollama giả lập, tự dọn containers
```

Kiểm tra notebook local chỉ xác nhận cấu trúc/cú pháp và logic không cần model. Chạy cell
cài gói, tải trọng số, GPU inference và benchmark Colab cần phiên GPU thực tế.

Tài liệu và tư liệu demo được tập trung tại [mục lục tài liệu](../README.md). Trạng thái triển khai
nằm trong tài liệu này và [hồ sơ bootstrap](../specs/001-project-bootstrap/spec.md); không coi
toàn bộ bản thiết kế là đã hoàn thành.

Kiểm chứng 24/10/2026: build API, smoke dependency/401, tích hợp PostgreSQL/Identity,
web tests và production build. Phạm vi endpoint cụ thể trong [tài liệu API](../api/README.md).

Đã kiểm chứng local ngày 2026-10-22: `make setup`, kiểm tra bootstrap/notebook,
2 kiểm thử FastAPI, build .NET (0 warning/error), smoke dependency lỗi/token,
2 kiểm thử web và production build đều qua. DB Docker khởi tạo đủ 16 bảng, UTC,
pgvector 0.8.2; SQL check qua dữ liệu hợp lệ và 15 trường hợp sai. Luồng web → .NET → DB
đã trả trạng thái sẵn sàng; AI trả chưa sẵn sàng đúng cấu hình Colab. Bốn kiểm thử CPU
notebook qua schema/cú pháp, vector, EXIF/GPS, JSON/tọa độ và pixel che/mờ.
Chưa chạy tải trọng số hoặc inference trên GPU Colab thực tế.
