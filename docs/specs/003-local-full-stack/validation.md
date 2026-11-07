# Kiểm chứng local full stack — 27/10/2026

## Đã chạy

- `make local-setup` trên cấu hình local: PostgreSQL/RabbitMQ healthy; EF schema nghiệp vụ, search DB/role/schema và demo Hub đã tạo, credential có sẵn được giữ.
- `make check`: 30 test bootstrap/script/notebook, 75 test AI, 24 test web PASS; 9 test DB skip trong pytest thường và đã chạy đủ qua integration. API build 0 warning/error, API smoke và React production build PASS.
- `make ai-integration`: PostgreSQL/RabbitMQ thật, 9 store tests PASS; text ranking, xử lý output ảnh, full manifest/parts, image search/provenance/filter/dedupe, replay/tombstone PASS. Ollama là HTTP stub.
- `python3 apps/api/tests/integration.py`: 181 recovery checks, 115 media/search/outbox checks, broker thật, migration/role và Hub seed PASS. Bridge .NET → AMQP → worker Python/OpenCV → search PostgreSQL kiểm hai ảnh, review, full snapshot, text/image search, retire và tombstone. Ollama/R2 là double.
- Chạy thật `make ai`, `make api`, `make web` trên DB local: web proxy tới API, DB ready; OAuth/storage configured; AI báo unavailable đúng vì chưa có phiên Colab. Đã kiểm worker không nhận Google/R2/migration credential và dừng sạch các tiến trình thử.
- Notebook 04: code compile, schema ảnh khớp runtime, cấu hình export/import đồng bộ, gateway copy khớp source đã test, không output/token đã lưu. Kiểm regression token không theo redirect sang host khác và import không làm lệch profile.
- Rà soát độc lập worker/store/scripts đã sửa lỗi bộ đếm RAM khi reconnect, health probe lúc model bận, receipt sau commit và hai lỗi importer. `git diff --check` sạch.

## Ranh giới chưa kiểm chứng

Chủ dự án chưa có phiên Colab/ngrok và không cấp endpoint/token trong phiên triển khai này. Vì vậy chưa chạy inference GPU, kiểm quota/độ trễ/ngrok thật hoặc đo chất lượng tìm kiếm/che PII. Google consent và R2 credential/private ACL thật cần luồng trình duyệt theo hướng dẫn. Không dùng model giả làm runtime mặc định, không báo hệ thống đầy đủ ready khi thiếu các phụ thuộc đó.

## Việc cần người vận hành

1. Chạy notebook 04 bằng tài khoản Colab/ngrok của mình, tải `findie-colab.json`.
2. `python3 scripts/configure_ollama.py /path/findie-colab.json`, nhập token riêng đã dùng ở notebook.
3. `make local-run`, mở `http://127.0.0.1:5173` và đăng nhập Google.
4. `make local-seed STAFF_EMAIL=...`, `make local-doctor`; thử đăng/duyệt/tìm/gỡ ảnh và ba nhánh trao trả.

Không thêm dashboard admin đầy đủ, attachment chat hoặc SignalR vì các hành trình MVP hiện có đã dùng API/CLI và HTTP chat. Chất lượng AI chưa được suy diễn từ test stub; ảnh đầu ra cần con người kiểm trước duyệt.
