# Kiểm thử API .NET

Chạy từ thư mục gốc:

```sh
dotnet restore apps/api --locked-mode
dotnet restore apps/api/tests/integration --locked-mode
dotnet build Findie.sln --no-restore
make api-integration
make check
```

`api-integration` chạy chương trình assert C# trong `apps/api/tests/integration`, dùng
WebApplicationFactory gọi HTTP thật qua pipeline ứng dụng và PostgreSQL thật.
Không dùng EF InMemory/SQLite để giả lập khóa, constraint hoặc concurrency PostgreSQL.
Đây là chương trình console theo test harness có sẵn; lỗi assert làm lệnh exit khác 0.

Runner `apps/api/tests/integration.py` tự tạo PostgreSQL 17/pgvector và RabbitMQ 4.3.2
dùng một lần, cổng ngẫu nhiên chỉ bind loopback, bí mật tạm sinh ngẫu nhiên, image ghim.
DB test bắt buộc prefix `findie_test_`; sau chạy tự dọn cả hai container kể cả lỗi.
Không áp dụng SQL hoặc migration vào DB `.env`/Compose đang dùng.
Docker có thể cần tải hai image khi chạy lần đầu.

Kết quả ngày 30/10/2026: **215 kiểm tra API nghiệp vụ + 108 kiểm tra xóa bài +
204 kiểm tra ảnh/search/outbox** đều qua, cùng kiểm thử RabbitMQ và xuyên dịch vụ thật.
Đối chiếu tài liệu đủ **29 endpoint**, kể cả `DELETE /api/items/{id}`.
Đã có regression upload → trao trả → replay cùng key, bảo đảm
không gọi AI hoặc ghi R2 thêm. `make check` kiểm tra thêm toàn bộ bootstrap/AI/web.

## Phạm vi kiểm chứng

| Bộ test | Kiểm tra |
| --- | --- |
| `Integration.cs` | Migration khớp model, 22 entity, restrict FK, không original; OAuth state/correlation qua provider giả, provider identity, tài khoản disabled, cookie/CSRF, DTO hồ sơ, điểm active; SQL constraints và concurrency token |
| `RecoveryChecks.cs` | Tất cả item/claim/chat/intake/return endpoints; 0–3 câu hỏi, answer snapshots, nhiều approved, IDOR/overposting, phiên bản cũ, key replay/conflict, concurrent create, thứ tự tin nhắn/đọc bù, phân quyền điểm/thu hồi, nhiều return và receive-vs-return đồng thời, privacy của outbox |
| `ItemDeletionChecks.cs` | Xóa mềm theo quyền quản lý hiện tại, kể cả bài đã trả; CSRF/key/phiên bản, replay/concurrency, loại khỏi mọi scope/chi tiết/search, giữ lịch sử và chặn thao tác claim/intake/chat sau xóa |
| `ImageSearchChecks.cs` | HTTP upload/search/review/retire/content; MIME/byte/hash/provenance, raw buffer cleanup, chỉ output tới R2 double, pending/rejected không public, sai source/version và model, thứ tự/dedup/filter kết quả, AI/R2 lỗi, ảnh bị thu hồi trong khi đọc, canonical jsonb checksum, outbox ACK sau commit, lease cũ, receipt không còn waiter, retry hữu hạn và orphan cleanup |
| `CrossServiceChecks.cs` + `cross_service.py` | .NET gateway/receipt/outbox → RabbitMQ → Python worker → PostgreSQL search thật; upload/review hai output, full manifest/parts, tìm text/ảnh và nhóm ảnh + mô tả được Python gộp, retire và tombstone; Ollama/R2 double |
| `test_search_cache.py` + `test_store.py` + AI integration | Cache từ khóa/vị trí, khóa theo model/bộ lọc/chỉ mục, xếp hạng vector khi trúng cache từ khóa, TTL Redis thật, rollback, update/tombstone và Redis lỗi. Runner tự dọn PostgreSQL/RabbitMQ/Redis riêng |
| `LocalSeedChecks.cs` | Seed Hub/staff idempotent cho Google account đã có; giữ hồ sơ, CLI Development và từ chối Production |
| `BrokerChecks.cs` | RabbitMQ thật: channel/queue lâu dài, confirms + mandatory unrouted, raw binary/nonpersistent/TTL, durable receipt route, requests đồng thời, waiter cancellation, malformed metadata và duplicate/late replies |
| Documentation check | So sánh 29 route/method runtime với tiêu đề tài liệu từng endpoint, gồm DELETE item, không bỏ sót API |
| `smoke.py` | Kestrel không DB, health/status, AI health/token probe, unauthorized và auth routes không hỗ trợ |
| `make check` | Bootstrap/notebooks, FastAPI health, build API, smoke, test TypeScript và build React |

Rate limit cố định: 120 request/phút/tài khoản cho nghiệp vụ; 20 request nặng/phút cho
upload/search. JSON body mặc định tối đa 64 KiB ở Kestrel, raw ảnh tối đa 10 MiB được
kiểm thêm khi đọc stream. TestServer không có feature Kestrel request-size; test upload
quá byte vẫn kiểm nhánh bounded stream của ứng dụng, không phụ thuộc riêng attribute.

## Giới hạn thực tế

- Google trong integration là backchannel giả: không kiểm consent hoặc credential Google thật.
- `ImageSearchChecks.cs` dùng double tại ranh giới Python/R2; bộ xuyên dịch vụ mới chạy .NET, worker Python/OpenCV, PostgreSQL và RabbitMQ thật. Ollama là HTTP stub, R2 là double; chưa chạy Colab/GPU/ngrok hoặc Cloudflare R2 thật.
- Chưa đo Hit@10/Recall@50, khả năng che PII, tốc độ/GPU hoặc tải lớn; không suy diễn từ test.
- Chưa nghiệm thu ACL/AMQPS/retention/reverse proxy/backup ở môi trường triển khai, crash
  đa tiến trình, rebuild search store hoặc phục hồi R2. Hợp đồng/quy trình tại [AMQP](amqp.md).
- Chat qua HTTP và đọc bù; chưa thêm SignalR. Staff được cấp qua CLI local Development; không có public admin API hoặc thao tác hard-delete/thu hồi claim. Không áp dụng schema migration phá dữ liệu.

Trước dữ liệu thật phải kiểm chứng model revision/khả năng che ảnh, R2 private và các
chính sách vận hành/retention trong đặc tả. API cơ bản vẫn dùng được khi AI không khả dụng;
search/upload trả 503 và có `GET /api/items` làm phương án lọc cơ bản.
