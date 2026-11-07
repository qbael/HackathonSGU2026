# Kế hoạch API nghiệp vụ

## Kiểm tra hiến chương trước thiết kế

Tái dùng .NET 10/EF Core/Npgsql/Identity, controller → service → repository, schema
hiện có. Không truy cập findie_search từ .NET. Không inference HTTP, không lưu original.
Tài khoản/quyền điểm kiểm lại mỗi request. Quyết định nhiều claim/chat đã chốt ở spec.

## Triển khai

1. DTO giới hạn đầu vào, ProblemDetails và repository truy vấn/khóa PostgreSQL.
2. Giao dịch có idempotency và thứ tự khóa item → request/conversation; event/outbox
   ghi nguyên tử. Nội dung chat/answer không xuất hiện trong snapshot tìm kiếm.
3. API theo nhóm; phân trang tối đa 100, rate limit theo tài khoản, CSRF cho ghi.
4. AMQP lâu dài, confirms/mandatory, waiter deadline và output R2 private. Upload body
   nhị phân đọc trực tiếp vào RAM tối đa 10 MiB; không model-bind IFormFile/spool tệp.
5. Dispatcher lease/retry hữu hạn; snapshot/tombstone full version. Không giữ transaction
   trong khi gọi broker/R2. Dọn object dự trữ/tháo liên kết có kiểm tra lại DB.
6. Test HTTP qua WebApplicationFactory + PostgreSQL thật dùng một lần; Google/broker/R2
   ở ranh giới có test double. Smoke, build và kiểm tra consumer web khi đổi status.

## Kiểm tra hiến chương sau thiết kế

Schema EF hiện tại đủ cho nghiệp vụ/outbox/output, không cần phá hoặc thay migration cũ.
Raw không vào object/outbox/log. Output cần provenance/hash/byte/dimensions hợp lệ và duyệt
đúng version. Kết quả search kiểm lại eligibility/document/source trước DTO. Claim nhiều
approved không biến thành nhiều lần return; item lock + unique event bảo vệ lần cuối.
Giới hạn demo: một instance .NET, HTTP chat polling; chưa thêm SignalR khi API HTTP đã
đáp ứng nhắn tin/đọc bù và không cần quản lý nhóm nhận sự kiện có thể mất quyền.
