# Vận hành database trên AWS

**Đã chuyển database Findie sang Amazon RDS thành công ngày 03/11/2026.** Cấu hình `.env` đã đổi sang RDS, API và AI worker đã được khởi động lại. Bản PostgreSQL local và backup trước chuyển vẫn được giữ để khôi phục khi cần.

Các kiểm tra tại thời điểm chuyển:

- **51 bảng public** trên ba database `findie` (23), `findie_frontend` (23), `findie_search` (5) khớp chính xác số hàng và hash từng bảng với nguồn; trạng thái **6 sequence** cũng khớp trước khi đổi kết nối.
- Hai role runtime kết nối qua TLS xác minh chứng chỉ/hostname, không được `CONNECT` vào database của nhau; thao tác ghi thử trong transaction đã đạt và được rollback.
- API `/health/ready` trả HTTP `200`, database sẵn sàng. Python `Store.check()` kết nối thật đến RDS với `verify-full`; dữ liệu tìm kiếm có 205 `ai_items` và 4 `ai_documents`.
- Phiên đăng nhập hiện có trên Chrome vẫn hợp lệ; danh sách Hub và 3 tin của tài khoản mở được. Hai ảnh được kiểm tra trên trang đã tải thành công, không có ảnh lỗi trong lần kiểm tra đó.

**AI đã báo `unavailable` trước khi chuyển và vẫn giữ trạng thái này sau chuyển.** Kết nối database tìm kiếm trên RDS đã được xác minh thành công; chưa chẩn đoán các phụ thuộc AI còn lại, gồm RabbitMQ và gateway model. Snapshot thủ công `findie-postgres-after-migration-20261103` đã ở trạng thái **`available`**, được mã hóa và sẵn sàng phục hồi.

## Cấu hình đích

| Thành phần | Giá trị |
| --- | --- |
| AWS Region | Singapore — `ap-southeast-1` |
| RDS instance | `findie-postgres` |
| Endpoint / cổng | `findie-postgres.c7qgaem64gqm.ap-southeast-1.rds.amazonaws.com:5432` |
| Engine | PostgreSQL `17.11` |
| Máy chủ / ổ đĩa | `db.t4g.micro`, Single-AZ, `20 GiB gp3`, mã hóa ổ đĩa |
| Bảo vệ dữ liệu | Automated backup giữ 7 ngày, bật deletion protection |
| Database nghiệp vụ có dữ liệu | `findie_frontend` |
| Database tìm kiếm | `findie_search`, gồm pgvector và các bảng tìm kiếm hiện có |
| Role runtime | `findie_app` cho nghiệp vụ; `findie_search_app` cho tìm kiếm |
| Kết nối | TCP `5432`, TLS xác minh chứng chỉ và hostname, security group cho phép mọi IPv4 `0.0.0.0/0` từ 07/11/2026 |
| Security group | `findie-postgres-client` — `sg-09b9d228f04045e51` |
| Mật khẩu quản trị | RDS quản lý qua AWS Secrets Manager |

Lần kiểm tra nguồn PostgreSQL `17.10` trước chuyển có **205 tin, 2 người dùng, 15 ảnh** trong `findie_frontend`; `findie_search` có **205 `ai_items`, 4 `ai_documents`**, cùng các bảng tìm kiếm cũ. Đây là mốc đối chiếu dữ liệu nguồn. Database `findie` của bộ cài mặc định có schema nghiệp vụ rỗng; cấu hình ứng dụng đang dùng dữ liệu phải trỏ đúng `findie_frontend`.

Ảnh đã xử lý vẫn nằm trong bucket **Cloudflare R2 hiện có**. Giữ các biến `Storage__*`; chuyển database chỉ chuyển metadata và tham chiếu object. Web, API, AI worker, RabbitMQ và model tiếp tục chạy ở môi trường hiện tại.

## Xem endpoint và thông tin quản trị

1. Mở [RDS Console tại Singapore](https://ap-southeast-1.console.aws.amazon.com/rds/home?region=ap-southeast-1#databases:), chọn **Databases → findie-postgres**.
2. Trong **Connectivity & security**, lấy **Endpoint** và **Port**, kiểm tra security group đang gắn với instance. Dùng DNS endpoint khi kết nối.
3. Trong **Configuration → Master Credentials ARN**, chọn **Manage in Secrets Manager**. Chỉ người có quyền IAM phù hợp mới được mở **Retrieve secret value**; dùng giao diện này khi cần credential quản trị, giữ giá trị trong trình quản lý mật khẩu hoặc môi trường làm việc riêng. Không đưa mật khẩu vào Git, chat hay lệnh có thể lưu vào shell history. Xem [hướng dẫn RDS quản lý secret](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html).

Ứng dụng dùng role runtime giới hạn quyền trong `.env`; credential master dành cho quản trị và migration. `AI_SEARCH_MIGRATION_DSN` lưu bản mật khẩu master hiện hành tại lúc chuyển. Khi secret được RDS xoay vòng, cần lấy mật khẩu mới và cập nhật biến này trước lần `make ai-migrate` tiếp theo. Các role runtime có mật khẩu riêng nên không bị ảnh hưởng bởi việc xoay vòng secret master.

## Cấu hình và chạy ứng dụng

Ba biến kết nối cần nhất quán với RDS:

| Biến `.env` | Mục đích |
| --- | --- |
| `ConnectionStrings__Database` | API .NET kết nối `findie_frontend` bằng role runtime nghiệp vụ |
| `AI_SEARCH_DSN` | AI worker kết nối `findie_search` bằng role runtime tìm kiếm |
| `AI_SEARCH_MIGRATION_DSN` | Migration schema tìm kiếm bằng credential quản trị, không truyền cho worker |

File CA đang dùng là `/home/bael/Projects/Hackathon/.cache/db-backups/aws-rds-20261102T173702Z/global-bundle.pem`. **Giữ file này và thư mục cha sau migration** vì cấu hình kết nối đang tham chiếu đến nó. Với Npgsql, dùng `SSL Mode=VerifyFull` và `Root Certificate`; với PostgreSQL URI, dùng `sslmode=verify-full` và `sslrootcert`. Khi chuyển ứng dụng hoặc di chuyển file CA sang máy/thư mục khác, cập nhật đường dẫn trong cả ba biến kết nối trước khi khởi động lại. Xem [TLS cho RDS PostgreSQL](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html).

Dừng các tiến trình đang chạy rồi khởi động lại để nạp `.env` mới. Có thể chạy `make api`, `make ai`, `make web` ở các terminal riêng. `make local-run` cũng đọc các DSN này, nhưng vẫn khởi động thêm container PostgreSQL local và RabbitMQ.

Các lệnh quản trị local có giới hạn cần nhớ:

- `make local-setup` chỉ provision database Docker local và sẽ từ chối DSN tìm kiếm trên RDS.
- `make db-migrate`, phần kiểm tra schema của `make local-doctor` và `make local-reindex` vẫn thao tác database Docker local; chúng không chứng minh dữ liệu RDS đã được kiểm tra.
- `make ai-migrate` dùng `AI_SEARCH_MIGRATION_DSN`, nên có thể thay đổi schema RDS khi biến này trỏ đến RDS. Chỉ chạy khi chủ đích nâng cấp schema.
- `make local-stop` dừng container database/broker; dừng riêng API và worker để ngăn background job tiếp tục ghi dữ liệu.

Kiểm tra `/health/ready` của API sau khi khởi động lại, rồi kiểm tra đăng nhập, danh sách tin và ảnh. Trạng thái AI còn phụ thuộc phiên model và RabbitMQ; giữ nguyên model/revision để dùng các vector đã chuyển.

## Truy cập từ mọi IPv4

Ngày **07/11/2026**, theo yêu cầu của chủ project, security group **findie-postgres-client (`sg-09b9d228f04045e51`)** đã được thêm inbound rule **`sgr-05012ba7aae957015`**: PostgreSQL TCP `5432`, source **`0.0.0.0/0`**. Instance đã bật `PubliclyAccessible` và dùng `NetworkType=IPV4`; rule này cho phép mọi IPv4 kết nối đến cổng database, kể cả sau khi máy đổi mạng hoặc VPN. Kết nối vẫn cần credential hợp lệ và ứng dụng tiếp tục xác minh TLS. Cổng database hiện phơi ra Internet và có thể bị dò quét hoặc thử mật khẩu.

Để quay lại giới hạn IP, mở **RDS → findie-postgres → Connectivity & security → VPC security groups → findie-postgres-client → Edit inbound rules**, thêm các rule `/32` cho máy cần truy cập rồi xóa rule `sgr-05012ba7aae957015` có source `0.0.0.0/0`. Các rule `/32` cũ đã được xóa ngày 07/11/2026. Xem [cách security group kiểm soát truy cập RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Overview.RDSSecurityGroups.html).

## Quay lại database local

Thư mục của lần chuyển là `/home/bael/Projects/Hackathon/.cache/db-backups/aws-rds-20261102T173702Z/`. Bước cutover ghi các bản dump `findie.dump`, `findie_frontend.dump`, `findie_search.dump`, bản cấu hình `env.before` và kết quả đối chiếu `validation.json` vào thư mục con `final/`. Chỉ coi việc chuyển hoàn tất sau khi đối chiếu dữ liệu thành công. Giữ volume PostgreSQL local và các bản sao này; thư mục `.cache/db-backups/` đã được Git bỏ qua và có thể chứa dữ liệu cá nhân, credential.

1. Dừng API và AI worker trước khi đổi kết nối.
2. Nếu đã có ghi mới trên RDS, sao lưu cả hai database RDS và đối chiếu phần thay đổi trước. Chuyển ngay về bản local cũ sẽ bỏ sót các ghi phát sinh sau thời điểm chuyển.
3. Khôi phục `.env` từ `final/env.before` trong thư mục trên, giữ quyền `600`, kiểm tra cả ba biến kết nối database đều trở về local.
4. Khởi động database/broker local, rồi API và worker. Kiểm tra dữ liệu trước khi cho phép ghi trở lại; chỉ chạy một bộ API/worker với RabbitMQ và R2 dùng chung.

Giữ RDS và backup cho đến khi xác minh xong. Khi cần khôi phục từ backup RDS, chọn **Actions → Restore to point in time** hoặc restore snapshot để tạo instance mới, đối chiếu dữ liệu rồi mới chuyển endpoint ứng dụng.

## Chi phí

Theo dõi trong **Billing and Cost Management → Bills / Cost Explorer** và đặt AWS Budget phù hợp. Các khoản cần tính gồm thời gian chạy instance, dung lượng gp3, backup vượt mức miễn phí áp dụng, truyền dữ liệu, public IPv4 nếu sử dụng và Secrets Manager. Free Tier hoặc credit phụ thuộc tài khoản; xem [giá RDS PostgreSQL](https://aws.amazon.com/rds/postgresql/pricing/) và [giá Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/) tại thời điểm sử dụng.

Giá niêm yết đã tra qua AWS Pricing API cho Singapore ngày **03/11/2026**: `db.t4g.micro` Single-AZ **0,025 USD/giờ**, gp3 **0,138 USD/GB-tháng**. Với 730 giờ và 20 GB, phần máy chủ + ổ đĩa khoảng **21,01 USD/tháng** (`0,025 × 730 + 0,138 × 20`), trước các khoản bổ sung, thuế và credit/Free Tier.

Dừng instance tạm thời vẫn có thể phát sinh phí lưu trữ, backup và public IPv4; RDS tự khởi động lại sau tối đa 7 ngày. Xem [quy định dừng RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_StopInstance.html). Khi kết thúc sử dụng, chủ tài khoản cần quyết định thời gian giữ backup, tạo final snapshot và tắt deletion protection trước khi xóa instance; snapshot giữ lại vẫn có thể phát sinh phí.
