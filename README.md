# Findie

Findie là nền tảng tìm và trao trả đồ thất lạc. Hướng dẫn này đưa bạn từ mã nguồn mới clone đến **chạy đầy đủ các service**, đăng nhập Google, đăng tin có ảnh, tìm kiếm AI, yêu cầu nhận đồ, nhắn tin và bàn giao tại Hub trong môi trường phát triển local.

## Toàn bộ hệ thống sẽ chạy ở đâu?

| Thành phần | Nơi chạy / địa chỉ mặc định | Vai trò |
| --- | --- | --- |
| Web React + Vite | Máy local — [http://127.0.0.1:5173](http://127.0.0.1:5173) | Giao diện; proxy `/api` sang API .NET |
| API .NET | Máy local — `http://127.0.0.1:5080` | Đăng nhập, nghiệp vụ, phân quyền, xử lý yêu cầu ảnh |
| Python AI worker + FastAPI | Máy local — `http://127.0.0.1:8000` | Nhận job qua RabbitMQ, xử lý ảnh, lập chỉ mục và tìm kiếm |
| PostgreSQL 17 + pgvector | Docker — `127.0.0.1:5432` | Database nghiệp vụ `findie` và database tìm kiếm `findie_search` |
| RabbitMQ | Docker — AMQP `127.0.0.1:5672`; [trang quản trị cổng 15672](http://127.0.0.1:15672) | Chuyển job và kết quả giữa .NET/Python |
| Redis | Docker — `127.0.0.1:6379` | Cache ứng viên từ khóa/vị trí (mặc định 60 giây) và embedding theo tài khoản (300 giây) |
| Model embedding và vision | GPU Colab, qua gateway HTTPS ngrok có token | Tạo vector văn bản/ảnh và nhận diện vùng cần che |
| Cloudflare R2 | Bucket private trên tài khoản Cloudflare của bạn | Lưu ảnh đầu ra đã xử lý |
| Google OAuth | Google Cloud project của bạn | Đăng nhập ứng dụng |

**Docker Compose chạy PostgreSQL, RabbitMQ và Redis.** `make local-run` chạy worker, API và web; model AI cần có phiên GPU riêng đang hoạt động. Máy local không cần cài Ollama hoặc có GPU khi dùng notebook 04.

Thứ tự thực hiện: **cài công cụ → tạo `.env` → cấu hình Google/R2 → `make local-setup` → chạy notebook 04 → import cấu hình → `make local-run` → đăng nhập/cấp quyền Hub → kiểm tra hệ thống**.

## 1. Chuẩn bị công cụ và tài khoản

Các lệnh dưới đây dùng shell Linux/macOS. Trên Windows, dùng WSL2, bật Docker integration cho bản phân phối WSL đó và cài các công cụ dòng lệnh trong cùng môi trường WSL.

| Công cụ | Phiên bản / yêu cầu | Hướng dẫn cài |
| --- | --- | --- |
| Git | Để clone repository | [Git](https://git-scm.com/downloads/) |
| Docker và Docker Compose | Docker daemon đang chạy; hỗ trợ `docker compose up --wait` | [Docker](https://docs.docker.com/get-started/get-docker/) |
| Node.js và npm | **Node.js 24.x**, theo `.nvmrc` và `apps/web/package.json` | [Node.js](https://nodejs.org/en/download) |
| .NET SDK | **10.0**, tối thiểu `10.0.100`; `global.json` cho phép feature band mới trong dòng 10.0 | [.NET 10 SDK](https://dotnet.microsoft.com/en-us/download/dotnet/10.0) |
| Python | **3.12** theo `services/ai/.python-version`; có lệnh `python3` trên PATH | [Python](https://www.python.org/downloads/) |
| uv | Quản lý Python và dependency của AI service | [uv](https://docs.astral.sh/uv/getting-started/installation/) |
| Make và curl | Có lệnh `make`, `curl` | Cài qua trình quản lý gói của hệ điều hành |

Kiểm tra trước khi tiếp tục:

```sh
git --version
docker --version
docker compose version
docker info
node --version
npm --version
dotnet --version
python3 --version
uv --version
make --version
curl --version
```

Nếu uv chưa có Python 3.12, chạy `uv python install 3.12`. Vẫn cần `python3` trên PATH để chạy các script trong Makefile. Lần đầu cần kết nối Internet để tải package, Docker image và model.

Chuẩn bị thêm:

- Google Cloud project và OAuth client; dùng **hai tài khoản Google** nếu muốn thử đầy đủ luồng người nhặt/người nhận.
- Tài khoản Cloudflare đã bật R2, một bucket private và credential S3 cho bucket đó.
- Tài khoản ngrok và authtoken; phiên Colab GPU phù hợp để chạy notebook 04.

Colab có giới hạn tài nguyên và hạn chế đối với dịch vụ/proxy; dùng môi trường cho phép mục đích này theo [FAQ của Colab](https://research.google.com/colaboratory/faq.html). Nếu không phù hợp, dùng notebook trên Jupyter GPU bạn kiểm soát theo [hướng dẫn AI](docs/guides/ai-service.md#model-trên-colab-qua-ngrok). Phiên Colab/ngrok cần được duy trì trong lúc dùng AI.

## 2. Lấy mã nguồn và tạo cấu hình local

```sh
git clone https://github.com/qbael/FindieHackathon.git
cd FindieHackathon
```

Nếu đã có mã nguồn, mở terminal tại thư mục chứa `Makefile` và `compose.yaml`. **Tất cả lệnh local trong README chạy từ thư mục gốc này**, kể cả khi mở terminal mới.

Nếu dùng nvm, chọn đúng Node.js:

```sh
nvm install
nvm use
```

Tạo `.env` và cấu hình RabbitMQ:

```sh
make env
```

Lệnh tự sinh mật khẩu PostgreSQL/RabbitMQ và token nội bộ ngẫu nhiên, đồng thời tạo `.cache/rabbitmq/definitions.json`. Chạy lại chỉ bổ sung biến còn thiếu và giữ giá trị đã có. **Không cần chép `.env.example` sang `.env`** vì file mẫu chứa placeholder chưa dùng để chạy được.

Giữ `.env` ở local; file đã được bỏ qua bởi Git. Chỉ source `.env` do bạn kiểm soát vì các script nạp file này như cấu hình shell. Khi sửa các bước tiếp theo, thay giá trị của biến có sẵn, tránh thêm nhiều dòng gán trùng nhau.

## 3. Cấu hình Google OAuth và R2

Cần hoàn tất cả hai phần trước khi dùng `make local-run`; lệnh này yêu cầu cấu hình cho toàn bộ tính năng.

### 3.1. Google OAuth

Ứng dụng chỉ đăng nhập bằng Google, không có tài khoản/mật khẩu demo.

1. Tạo/chọn project trong Google Cloud và cấu hình màn hình chấp thuận OAuth. Nếu ứng dụng ở chế độ Testing, thêm các tài khoản Google dùng để thử vào danh sách test users.
2. Tạo OAuth client loại **Web application** theo [hướng dẫn Google](https://developers.google.com/identity/protocols/oauth2/web-server#creatingcred).
3. Đăng ký **Authorized redirect URI** chính xác:

   ```text
   http://127.0.0.1:5173/api/auth/google/signin
   ```

4. Điền Client ID và Client Secret vào `.env`:

   ```dotenv
   Authentication__Google__ClientId='YOUR_CLIENT_ID.apps.googleusercontent.com'
   Authentication__Google__ClientSecret='YOUR_CLIENT_SECRET'
   ```

Luôn mở web bằng `http://127.0.0.1:5173` khi làm theo hướng dẫn. Callback đi qua Vite ở cổng **5173**; không thay bằng cổng API 5080. Nếu dùng `localhost`, phải đăng ký URI tương ứng và dùng host đó nhất quán.

### 3.2. Cloudflare R2 private

1. Tạo bucket dành cho môi trường local, ví dụ `findie-local`. Giữ bucket **private**, không bật Public Development URL hoặc gắn domain public; xem [cấu hình truy cập public của R2](https://developers.cloudflare.com/r2/buckets/public-buckets/).
2. Tạo R2 API token với quyền **Object Read & Write**, giới hạn vào bucket đó. Lưu **Access Key ID** và **Secret Access Key** theo [hướng dẫn R2](https://developers.cloudflare.com/r2/api/tokens/).
3. Điền đủ bốn biến trong `.env`, dùng S3 API endpoint của bucket:

   ```dotenv
   Storage__Endpoint='https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com'
   Storage__Bucket='findie-local'
   Storage__AccessKeyId='YOUR_ACCESS_KEY_ID'
   Storage__SecretAccessKey='YOUR_SECRET_ACCESS_KEY'
   ```

Endpoint trên dành cho bucket mặc định; bucket có jurisdiction riêng phải dùng endpoint tương ứng trong tài liệu R2. Endpoint phải là HTTPS, không phải URL public của một ảnh. API thực hiện đọc/ghi/xóa object phía server; trình duyệt nhận ảnh qua API, không cần public bucket để hiển thị ảnh.

Google/R2 credential chỉ đặt ở phía backend, không đưa vào biến `VITE_*`, notebook hoặc Git. Nếu chỉ điền một phần cấu hình R2, API sẽ từ chối khởi động.

## 4. Cài dependency và khởi tạo toàn bộ hạ tầng

Đảm bảo `docker info` chạy thành công, sau đó:

```sh
make local-setup
docker compose ps
```

`make local-setup` đã bao gồm `make setup` và thực hiện:

1. Bổ sung cấu hình còn thiếu; cài Python package bằng `uv sync --locked`, restore .NET/package và `dotnet-ef`, cài web bằng `npm ci` theo lockfile.
2. Khởi động PostgreSQL/pgvector và RabbitMQ, chờ healthcheck, nạp các user/quyền/queue của broker.
3. Migrate database nghiệp vụ `findie` bằng EF Core, chuẩn bị role runtime `findie_app`.
4. Tạo database tìm kiếm `findie_search` và role runtime `findie_search_app` riêng, migrate schema và cấp quyền DML. Điền các DSN tìm kiếm và `RabbitMq__Uri` local còn trống trong `.env`.
5. Tạo **Findie Demo Hub**. Chưa tạo tài khoản hoặc cấp quyền nhân viên; thực hiện sau khi đăng nhập Google ở bước 7.

Kết quả: hai container ở trạng thái chạy/healthy; script kết thúc với thông báo `Local infrastructure ready`. Bước này chưa khởi chạy web/API/worker và chưa tải model AI.

Chạy lại không reset dữ liệu hoặc thay credential đã có trong `.env`. Nếu dùng database bootstrap cũ có dữ liệu, migration có thể dừng để bảo toàn dữ liệu; cần kế hoạch chuyển đổi riêng. Không nhập `docs/database/database-schema.sql` thay cho EF migrations. DSN tùy chỉnh được giữ nguyên và `local-setup` sẽ dừng nếu chúng không trỏ đúng database/role local mà script quản lý.

Nếu database đặt trên AWS RDS, xem [hướng dẫn vận hành database AWS](docs/guides/aws-database.md) để dùng đúng kết nối, quản lý truy cập và quay lại bản local khi cần.

## 5. Chạy model AI trên Colab và mở gateway ngrok

Dùng **[04_full_stack_ollama_ngrok.ipynb](notebooks/colab/04_full_stack_ollama_ngrok.ipynb)**. Notebook 01–03 là thử nghiệm riêng, không thay thế notebook 04 cho luồng đầy đủ.

1. Mở [Google Colab](https://colab.research.google.com/), chọn **File → Upload notebook** và upload notebook 04 từ repository.
2. Chọn **Runtime → Change runtime type → GPU** (ví dụ T4), kết nối runtime rồi chạy từng cell từ trên xuống.
3. Nếu cell cài dependency yêu cầu **Runtime → Restart session**, làm đúng yêu cầu rồi chạy lại từ cell đầu. Chạy lại cell trong kernel cũ chưa thay thế được bước restart.
4. Cung cấp hai secret qua Colab Secrets hoặc ô nhập ẩn của notebook:

   | Secret | Lấy từ đâu / dùng để làm gì |
   | --- | --- |
   | `NGROK_AUTHTOKEN` | Authtoken trong tài khoản ngrok, dùng để mở tunnel |
   | `FINDIE_OLLAMA_TOKEN` | Token riêng do bạn tạo, tối thiểu **32 ký tự ASCII không có khoảng trắng**, dùng xác thực gateway |

   Lưu `FINDIE_OLLAMA_TOKEN` để nhập lại trên máy local ở bước 6. Hai token này khác nhau và khác `AI_SERVICE_TOKEN` tự sinh trong `.env`. Không cần đưa credential Google/R2/database hay `AI_SERVICE_TOKEN` lên Colab. `HF_TOKEN` là tùy chọn cho model Qwen công khai.
5. Chờ notebook tải và kiểm hai model:

   | Model | Vai trò |
   | --- | --- |
   | `Qwen/Qwen3-VL-Embedding-2B` qua Transformers | Embedding văn bản và ảnh native, 2048 chiều |
   | `qwen3-vl:4b-instruct` qua Ollama | Gợi ý vùng nhạy cảm để worker local che ảnh |

6. Chỉ tiếp tục khi các cell kiểm embedding text/ảnh, JSON vision và gateway HTTPS hoàn tất. Chạy cell **Tải cấu hình về local** để tải `findie-colab.json` về máy.
7. Giữ runtime đang kết nối trong suốt phiên sử dụng. JSON không chứa token; gateway ngrok yêu cầu Bearer token và chỉ mở các endpoint model cần thiết.

Không tự đổi tên model trong `.env` để bật tìm ảnh: model mặc định `qwen3-embedding:4b` trong file mẫu chỉ hỗ trợ văn bản. JSON của notebook 04 chứa đúng model, revision, số chiều và cấu hình bật tìm ảnh. Chi tiết fingerprint Qwen, GPU và xử lý lỗi ở [hướng dẫn AI service](docs/guides/ai-service.md) và [Colab](docs/guides/colab.md).

## 6. Import model và khởi chạy web/API/worker

Tại máy local, thay đường dẫn bằng file vừa tải:

```sh
python3 scripts/configure_ollama.py "$HOME/Downloads/findie-colab.json"
```

Khi được hỏi, nhập **cùng `FINDIE_OLLAMA_TOKEN` đã dùng trên Colab**, không nhập authtoken ngrok. Lệnh kiểm gateway/token/revision trước khi cập nhật `.env`, đồng bộ cấu hình .NET/Python và lưu token vào `OLLAMA_API_KEY`. Credential Google/R2/database được giữ nguyên.

Khởi chạy toàn bộ ứng dụng trong **terminal 1** và giữ terminal mở:

```sh
make local-run
```

Lệnh kiểm cấu hình đầy đủ và cổng 5173/5080/8000, bật lại database/broker nếu cần, build API, rồi:

1. Chạy worker Python, chờ model/phụ thuộc sẵn sàng với đủ ba capability: tìm văn bản, tìm ảnh và che ảnh.
2. Chạy API .NET, chờ kết nối database sẵn sàng.
3. Chạy web Vite, kiểm đường proxy web → API và trạng thái AI.

Khi thấy `Findie ready: http://127.0.0.1:5173`, mở **[ứng dụng Findie](http://127.0.0.1:5173)**. Không cần kích hoạt virtualenv hoặc source `.env` thủ công để chạy các lệnh `make`.

Nếu cần xem log riêng khi phát triển, sau khi đã cấu hình xong có thể chạy **thay cho `make local-run`** bằng ba terminal: `make ai`, `make api`, `make web` theo thứ tự đó. Các lệnh riêng không có bước chờ/kiểm đủ service như `local-run`. Chỉ chạy **một** worker Python; không chạy đồng thời hai cách hoặc tăng số Uvicorn workers.

## 7. Đăng nhập, cấp quyền Hub và xác nhận service

1. Đăng nhập Google tại [http://127.0.0.1:5173/signin](http://127.0.0.1:5173/signin) để tạo tài khoản thật trong database local.
2. Mở **terminal 2** tại thư mục gốc; thay email ví dụ bằng tài khoản vừa đăng nhập:

   ```sh
   make local-seed STAFF_EMAIL='your-google-email@gmail.com'
   make local-doctor
   ```

`local-seed` chỉ chạy trong Development, cấp quyền nhận/trả tại Demo Hub cho tài khoản Google đã tồn tại; không tạo tài khoản giả. Nếu chưa đăng nhập trước, lệnh báo không tìm thấy tài khoản hợp lệ.

`local-doctor` cần toàn bộ kiểm tra **PASS**: cấu hình, schema hai database, nhân viên Hub, queue có consumer, AI/model identity và API. Google/R2 chỉ được kiểm ở mức **đã cấu hình**; xác minh credential bằng đăng nhập/upload thật ở bước 8.

Kiểm tra thêm các endpoint:

```sh
curl -i http://127.0.0.1:5080/health/live
curl -i http://127.0.0.1:5080/health/ready
curl -i http://127.0.0.1:8000/health/live
curl -sS http://127.0.0.1:5173/api/system/status
```

Ba lệnh đầu cần HTTP 200. Lệnh cuối cần `database: "ready"`, `ai: "ready"`, `features.authentication: true` và `features.storage: true`. Endpoint status vẫn trả HTTP 200 khi phụ thuộc lỗi, nên cần đọc nội dung. `/health/ready` của .NET chỉ kiểm kết nối database, không thay thế kiểm schema của doctor.

Kiểm trạng thái model bằng token nội bộ trong một subshell:

```sh
(
  set -a
  . ./.env_old
  set +a
  curl -sS -H "X-Service-Token: ${AI_SERVICE_TOKEN}" http://127.0.0.1:8000/v1/status
)
```

Kết quả cần `inferenceReady: true` và `capabilities.textSearch`, `imageSearch`, `imageRedaction` đều `true`. `/health/ready` và `/v1/status` của Python yêu cầu header `X-Service-Token`; `/health/live` chỉ xác nhận tiến trình còn chạy.

Đăng nhập [RabbitMQ Management](http://127.0.0.1:15672) bằng `RABBITMQ_ADMIN_USER` / `RABBITMQ_ADMIN_PASSWORD` trong `.env` để xem queue và consumer. Khi đổi cổng trong `.env`, dùng địa chỉ tương ứng.

## 8. Thử đầy đủ luồng nghiệp vụ

Dùng ảnh demo không nhạy cảm cho lần thử đầu. Các bước này xác minh cả OAuth, R2 và model thật:

1. **Người nhặt (tài khoản A):** tạo tin nhặt được, điền tên món đồ, mô tả công khai và khu vực nhặt được; thời gian có thể chọn **Không nhớ chính xác**. Chọn **Tôi đang tự giữ**, bắt buộc đính kèm **1–3 ảnh** JPEG/PNG/WebP (10 MiB/ảnh), rồi bấm **Lưu tin & kiểm tra ảnh**. Tin chỉ được công khai khi có ít nhất một ảnh đã được xử lý và duyệt; gỡ hoặc từ chối ảnh công khai cuối cùng sẽ tự ẩn tin.
2. **Ảnh:** chờ xử lý, xem kỹ bản đã che, tích đủ ba xác nhận cho từng ảnh và bấm **Duyệt ảnh công khai**, rồi **Công khai tin**. Kiểm bucket R2 chỉ có output đã xử lý và vẫn private. Ảnh gốc không được lưu lên R2; nội dung gửi inference đi qua gateway Colab/ngrok của bạn.
3. **Tìm kiếm:** tìm tin vừa công khai bằng mô tả và bằng ảnh, thử thêm bộ lọc. Chờ job lập chỉ mục hoàn tất nếu kết quả chưa xuất hiện ngay; giữ tin công khai để thử yêu cầu nhận đồ ở bước tiếp theo.
4. **Người nhận (tài khoản B):** đăng nhập bằng profile trình duyệt khác hoặc cửa sổ ẩn danh, mở tin và **Gửi yêu cầu nhận đồ**. Tài khoản A vào **Yêu cầu trao trả**, xác nhận đã đối chiếu và **Chấp thuận & mở hội thoại**. Hai bên thử nhắn tin; sau khi bàn giao, tài khoản A bấm **Xác nhận đã trao trả** trong hội thoại.
5. **Hub:** tạo tin khác, chọn **Đề nghị gửi vào Findie Hub** và **Findie Demo Hub**. Tài khoản đã cấp quyền mở **Theo dõi tiếp nhận**, xác nhận đã nhận đồ thực tế rồi **Xác nhận đã tiếp nhận**. Sau đó vào **Đồ đang quản lý → Xác nhận trao trả**, điền ghi chú xác minh và xác nhận bàn giao; xem lại lịch sử. Luồng Hub xác minh tại quầy. Nếu người gửi cũng là nhân viên, mở phần **Dành cho nhân viên điểm tiếp nhận** để xử lý yêu cầu.

Database mới không có tin mẫu hoặc tài khoản demo. AI có thể bỏ sót vùng nhạy cảm; luôn xem lại output trước khi duyệt. Chi tiết API/giới hạn ảnh ở [API ảnh và tìm kiếm](docs/api/media-search.md).

## 9. Dừng, chạy lại và cập nhật cấu hình

### Dừng phiên

Trong terminal chạy `make local-run`, nhấn **Ctrl+C** để dừng web/API/worker do phiên đó tạo. Nếu chạy từng service riêng, nhấn Ctrl+C trong từng terminal. Sau đó:

```sh
make local-stop
```

Lệnh dừng PostgreSQL, RabbitMQ và Redis, **giữ volume dữ liệu**. Khi kết thúc phiên GPU, dùng **Runtime → Disconnect and delete runtime** trên Colab để dừng model/gateway. Không dùng `docker compose down -v` nếu cần giữ dữ liệu.

### Chạy lại những lần sau

1. Khởi động Docker và phiên model Colab/ngrok.
2. Nếu gateway đổi URL, tải JSON mới từ notebook và import lại:

   ```sh
   python3 scripts/configure_ollama.py "$HOME/Downloads/findie-colab.json"
   ```

3. Chạy `make local-run`, sau đó kiểm `make local-doctor` trong terminal khác. Database/broker tự được bật lại; tài khoản, quyền Hub và dữ liệu đã có được giữ nguyên.

Sau khi pull thay đổi dependency, migration hoặc cấu hình mẫu, chạy lại `make local-setup` trước `make local-run`. Nếu chỉ thay OAuth/R2, dừng ứng dụng rồi chạy lại để nạp `.env` mới.

### Đổi model hoặc dùng database đã có tin cũ

Dừng ứng dụng, chạy notebook với cấu hình mới, tải/import JSON và chạy lại `make local-run`. Sau khi worker sẵn sàng, trong terminal khác:

```sh
make local-reindex
```

Lệnh phát lại snapshot/tombstone hiện hành để lập chỉ mục, không xóa dữ liệu người dùng. Chờ lập chỉ mục trước khi kiểm kết quả; job có lease đang chạy được giữ và có thể cần chạy lại sau khi lease kết thúc. Cần reindex khi model/revision/số chiều/profile thay đổi hoặc bật tìm ảnh cho dữ liệu cũ; chỉ đổi URL ngrok với cùng cấu hình model thì không cần. Không dùng lẫn vector từ các model khác nhau dù cùng số chiều.

## 10. Lỗi thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| Thiếu `make`, `uv`, `dotnet`, `python3`, `npm` | Cài công cụ bước 1, kiểm PATH; trên WSL cài trong cùng bản phân phối đang dùng. |
| Node/SDK không đúng phiên bản | Chọn Node 24.x và .NET SDK 10.0; kiểm `.nvmrc` / `global.json`. |
| Docker không kết nối được | Mở Docker Desktop/daemon và kiểm `docker info`; kiểm Docker integration trên WSL. |
| Compose thiếu `.cache/rabbitmq/definitions.json` | Chạy `make env` hoặc `make local-setup` trước khi khởi động broker. |
| `Full local configuration missing` | Hoàn tất Google/R2, chạy `make local-setup` và import JSON **notebook 04**; xem tên biến/nhóm bị thiếu trong lỗi. |
| Cổng 5173/5080/8000 đã được dùng | Dừng phiên web/API/worker cũ trước khi chạy lại; Vite không tự đổi cổng. |
| Cổng PostgreSQL hoặc RabbitMQ bị chiếm | Trước setup lần đầu, đổi `POSTGRES_PORT`, `RABBITMQ_PORT`, `RABBITMQ_MANAGEMENT_PORT` trong `.env`. Nếu đã setup, cập nhật cả DSN/URI đã được lưu bằng cổng cũ; `local-setup` không ghi đè chúng. |
| Sai mật khẩu PostgreSQL sau khi sửa `.env` | Credential trong volume hiện có không tự đổi theo file env. Khôi phục cấu hình đúng hoặc đổi mật khẩu bằng quyền quản trị; không xóa volume có dữ liệu để thử. |
| Google báo `redirect_uri_mismatch` | Kiểm đúng callback bước 3.1 và không trộn `localhost` với `127.0.0.1`; dùng cổng 5173. |
| Không đăng nhập được tài khoản thử | Kiểm OAuth client/secret, consent/test users; khởi động lại API sau khi sửa `.env`. |
| Colab lỗi import Transformers/`GenerationMixin` | Restart session sau cài dependency, chạy lại notebook từ đầu; xem [hướng dẫn Colab](docs/guides/colab.md). |
| Colab thiếu GPU hoặc hết bộ nhớ | Dùng runtime GPU phù hợp, dọn phiên cũ rồi chạy lại; hai model phải nạp và qua kiểm inference trước khi import. |
| Import không xác minh được gateway/token/revision | Giữ notebook/gateway đang chạy, dùng JSON mới nhất và đúng `FINDIE_OLLAMA_TOKEN`; không dùng `NGROK_AUTHTOKEN`. `.env` được giữ nguyên nếu xác minh thất bại. |
| `local-run` chờ worker rồi dừng, AI báo unavailable | Kiểm log Python, runtime Colab/ngrok, schema tìm kiếm và broker; chạy doctor. Model phải đủ cả ba capability. |
| `/v1/status` hoặc readiness Python trả 401 | Thêm `X-Service-Token` bằng `AI_SERVICE_TOKEN` local, không dùng token ngrok/gateway. |
| Upload ảnh lỗi hoặc R2 trả lỗi | Kiểm đủ bốn biến R2, endpoint/bucket, credential và quyền đọc/ghi/xóa; `storage: true` chỉ xác nhận cấu hình. |
| Doctor báo thiếu Demo Hub staff | Đăng nhập Google trước rồi chạy `make local-seed STAFF_EMAIL='email-da-dang-nhap'`. |
| Tin không xuất hiện trong tìm kiếm | Kiểm đã công khai/duyệt ảnh, queue có consumer và trạng thái lập chỉ mục; khi đổi model chạy `make local-reindex`. |
| API nghiệp vụ trả 401 khi dùng curl | Đăng nhập qua web; curl riêng không tự có cookie phiên trình duyệt. |

Xem log web/API/worker trong terminal đang chạy. Log hạ tầng:

```sh
docker compose logs --tail=100 db rabbitmq redis
```

## 11. Các lệnh kiểm thử

Chạy sau khi đã cài dependency bằng `make setup` hoặc `make local-setup`:

| Lệnh | Phạm vi |
| --- | --- |
| `make check` | Test bootstrap/notebook, Python, build/smoke API, test và build web; không cần model thật |
| `make api-integration` hoặc `make db-check` | Migration/API với PostgreSQL/RabbitMQ tạm; cần Docker |
| `make ai-integration` | Worker/kho tìm kiếm với PostgreSQL/RabbitMQ/Redis tạm và model giả lập; cần Docker |

Các bộ integration tạo/dọn container riêng, không ghi vào database local của project. Một số test kho tìm kiếm trong `make check` được bỏ qua nếu thiếu database test; dùng `make ai-integration` để chạy nhóm này. Các test không thay thế bước kiểm OAuth, R2 và inference GPU thật ở bước 8.

## Cấu trúc và tài liệu

```text
apps/web/                   React + TypeScript + Vite + Tailwind
apps/api/                   .NET 10 + EF Core + Identity; kiểm thử tích hợp API
services/ai/                FastAPI, worker RabbitMQ, xử lý ảnh và tìm kiếm
scripts/                    Setup, chạy/dừng, doctor, migration, import model, reindex
notebooks/colab/            Notebook 01–03 thử nghiệm; notebook 04 cho full stack
tests/                      Kiểm thử bootstrap, gateway và notebook
docs/                       Sản phẩm, kiến trúc, database, API và hướng dẫn
compose.yaml                PostgreSQL/pgvector + RabbitMQ
Makefile                    Các lệnh vận hành và kiểm thử
Findie.sln                  Solution .NET
```

- [Mục lục tài liệu](docs/README.md) và [hướng dẫn phát triển](docs/guides/development.md).
- [API .NET](docs/api/README.md), [kiểm thử API](docs/api/testing.md), [API ảnh/tìm kiếm](docs/api/media-search.md).
- [AI service](docs/guides/ai-service.md) và [hướng dẫn Colab](docs/guides/colab.md).
- [Kiến trúc hệ thống](docs/architecture/system-architecture.md) và [thiết kế database](docs/database/database-design.md).
- [Đặc tả sản phẩm](docs/product/DAC_TA_FINDIE.md) và [thiết kế giao diện](docs/design/stitch/README.md).
