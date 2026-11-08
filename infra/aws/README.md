# Triển khai Findie trên AWS

Kiến trúc lấy từ `docs/architecture/findie-aws-architecture.docx`: CloudFront VPC Origin → EC2 ứng dụng private, EC2 worker private, Amazon MQ, Redis; dùng lại RDS và R2. Không dùng ALB, Nginx hoặc S3. Hai máy đơn lẻ phục vụ bản triển khai đầu tiên, chưa có HA.

## Hạ tầng

`python3 infra/aws/stack.py > /tmp/findie-stack.json` sinh CloudFormation bằng thư viện chuẩn Python. Template không đọc `.env` và không chứa credential. Triển khai bằng `aws cloudformation deploy`, `CAPABILITY_IAM` và các tham số VPC, public subnet, AZ, RDS security group, CloudFront prefix list và AMI Amazon Linux 2023 x86_64. VPC phải có Internet Gateway và bật DNS. CIDR `172.31.64.0/24` phải chưa được sử dụng. OIDC provider `token.actions.githubusercontent.com` phải có sẵn.

Stack tạo NAT Gateway có public IPv4; hai EC2 private không có public IP hoặc cổng SSH. Cổng ứng dụng 8080 chỉ nhận CloudFront prefix list; worker 8000 chỉ nhận application security group; MQ 5671 chỉ nhận hai máy; Redis TLS 6379 chỉ nhận worker. IMDSv2 bắt buộc, hop limit 1 ngăn container lấy instance credentials. RDS chỉ được thêm rule nguồn là hai security group; stack không sửa các rule/public accessibility cũ.

Distribution mặc định tắt. Chỉ đặt `EnableDistribution=true` sau khi hoàn thành secrets, migration, kiểm tra container và callback Google. CloudFront không cache các request, chuyển tiếp cookie, CSRF, query và headers, ghi đè `X-Forwarded-Proto=https`; không bật access log chứa thông tin request. Có thể tối ưu cache riêng tài nguyên build sau khi đo tải.

NAT, EC2, MQ, Redis, EBS và Secrets Manager tính phí kể cả khi distribution đang tắt. Snapshot trước mỗi SHA được giữ lại; quản trị viên cần áp dụng chính sách giữ backup phù hợp.

## Secrets phía server

Điền trực tiếp các JSON secret trong Secrets Manager Singapore:

| Secret | Nội dung |
| --- | --- |
| `findie/production/api` | Npgsql runtime DSN đến `findie_frontend`, Google OAuth, R2, model/revision tương ứng và `RabbitMq__Uri` AMQPS |
| `findie/production/worker` | `AI_SEARCH_DSN` runtime đến `findie_search`, gateway HTTPS/token, model/revision, `AI_RABBITMQ_URL` AMQPS |
| `findie/production/migration` | `ConnectionStrings__Database` và `AI_SEARCH_MIGRATION_DSN` dùng credential migration riêng |
| `findie/production/service-token` | Token chung API/worker, tự sinh bởi stack |
| `findie/production/broker-admin` | Admin MQ tự sinh, chỉ dùng bootstrap |

DSN xác minh TLS/hostname (`SSL Mode=VerifyFull` hoặc `sslmode=verify-full`); CA trong cả hai image là `/usr/local/share/rds-ca.pem`. Không dùng đường dẫn CA trên máy local. Khi RDS xoay mật khẩu quản trị, cập nhật migration secret tương ứng trước release. Role runtime không nhận credential migration; host chỉ assume migration role cho tác vụ một lần. Không đưa migration credentials vào container runtime.

`provision_broker.py` chạy một lần trên app host qua SSM, dùng credential admin từ Secrets Manager để tạo `findie_api`, `findie_worker`, ACL từ cấu hình local và import `docs/api/rabbitmq-definitions.json`. Cần cấp tạm quyền Get/Put đúng hai runtime secrets và Get broker-admin, có điều kiện hết hạn; gỡ policy trong `finally` và xác minh đã gỡ. Role runtime không giữ quyền đọc broker-admin sau bootstrap. Script không nhận hoặc xuất mật khẩu qua SSM.

## Google Cloud

Project hiện có: `findie-512603`, OAuth client tên `Findie`. Giữ callback local và thêm chính xác:

```
https://<CloudFront domain>/api/auth/google/signin
```

Đây là callback middleware, khác với route nội bộ `/api/auth/google/callback`. Ứng dụng dùng OAuth phía server, không cần đưa client ID/secret vào React. Audience hiện ở Testing; luồng chỉ yêu cầu email/profile thuộc ngoại lệ không cần thêm test user ([quy định Google](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview)). Nếu thêm scope khác, phải xét lại Audience và quy trình công bố. Kiểm tra thật bằng trình duyệt: chuyển sang Google đúng callback HTTPS, cookie Secure/HttpOnly, quay về ứng dụng, `/api/users/me` và POST có CSRF.

## CI/CD

Giữ nguyên `.github/workflows/ci.yml`. Sau CI thành công của push `main`, `.github/workflows/deploy.yml` lấy quyền OIDC theo subject đúng repo/main, build và đẩy hai image ECR có tag full commit SHA, rồi gọi `release.py`. PR không có quyền deploy. Đặt GitHub repository variable `AWS_DEPLOY_ROLE_ARN` bằng output `DeployRoleArn`; không lưu AWS access key.

Repository này dùng immutable OIDC subject: `repo:qbael@197704624/HackathonSGU2026@1449042338:ref:refs/heads/main` (đã xác minh qua GitHub API). Không thay bằng subject chỉ chứa tên repo; nếu tái sử dụng cho repository khác, lấy `sub_claim_prefix` tại `/actions/oidc/customization/sub` rồi nối `:ref:refs/heads/main` và truyền tham số `GitHubSubject` phù hợp.

Chủ project chỉ cho phép một snapshot cho lần triển khai đầu. Các release tự động sau đó không tạo snapshot hay chạy migration: API `--check-schema` kiểm tra migration chưa áp dụng và dừng nếu schema chưa khớp. Khi có thay đổi schema, cần phê duyệt backup/migration riêng trước khi chạy `release.py <SHA> --migrate`: snapshot RDS theo SHA và chờ available, .NET `--migrate` có advisory lock, Python search migration. Không reset/seed database. Chỉ áp dụng migration tương thích với bản đang chạy và bản local. Worker có thể live nhưng inference unavailable nếu notebook GPU ngắt; trạng thái này không được coi là AI ready.

`deploy_host.py` lấy secrets vào bộ nhớ, truyền cho Docker qua môi trường tiến trình, không đưa giá trị vào argv hay SSM output. Container read-only, non-root, bỏ capabilities, không có swap/core dump, `/tmp` tmpfs; tắt container log để tránh lưu request riêng tư. Cookie/Data Protection keyring được giữ trên EBS mã hóa giữa các release. Không dùng `docker inspect` với output cấu hình môi trường trong log.

Nếu health check thất bại, host khôi phục container trước. Nếu app thất bại sau khi worker đã cập nhật, `release.py` rollback worker. Không tự đảo migration. Release đầu tiên không có container trước để khôi phục. Có thể chạy lại một release đã kiểm tra bằng `python3 infra/aws/release.py <full SHA>`.

## Ảnh và tác vụ dài

Cloud bật `Ai__PrivateHttpImages=true` và `Ai__AsyncJobs=true`. Ảnh upload/tìm kiếm truyền binary trực tiếp trong VPC từ API đến worker, xác thực bằng token và metadata có giới hạn. Không gửi ảnh gốc tới MQ, Redis, R2, DB, file tạm hay DLQ. MQ vẫn chuyển lệnh chỉ mục và ảnh đã được duyệt từ R2. Gateway AMQPS từ chối các loại lệnh có ảnh gốc khi chưa bật kênh riêng.

Upload, tìm kiếm và lưu tìm kiếm trả `202` cùng `/api/jobs/<id>`, frontend poll cùng origin. Kết quả chỉ trả cho người tạo job, giới hạn bốn job đang chạy và 128 kết quả, hết hạn 35 phút. Raw chỉ giữ trong RAM và bị xóa khi xử lý xong; restart cần tải ảnh lại. Chưa hỗ trợ nhiều app instance hoặc chuyển job giữa instance; cần thiết kế lại trạng thái an toàn trước khi scale out.

## Kiểm chứng và vận hành

- `npm run build --prefix apps/web` và `npm test --prefix apps/web`.
- `uv run --project services/ai --locked pytest services/ai/tests`.
- `python3 apps/api/tests/smoke.py`, `python3 apps/api/tests/integration.py`, `npm run test:e2e --prefix apps/web`.
- Build cả hai Dockerfile từ root; kiểm tra SPA deep link và route API không tồn tại vẫn 404.
- Qua HTTPS kiểm tra health, đăng nhập Google, CSRF, R2 có kiểm quyền, upload/review/search khi GPU chạy; thử mất GPU/broker/Redis và rollback.
- Kiểm tra SG/RDS: cấu hình public database cũ không tự được đóng bởi stack; xử lý riêng nếu vẫn cần cho local.

Theo dõi tình trạng SSM/EC2 và `/api/system/status`. Không bật request-body logging hoặc ghi nguyên lỗi có thể chứa connection string/gateway token. GPU Kaggle/Colab được vận hành riêng, pipeline không tự khởi động hoặc kéo dài phiên notebook.
