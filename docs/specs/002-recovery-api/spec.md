# API nghiệp vụ Findie

Ngày: 24/10/2026. Nguồn: DAC_TA_FINDIE.md v1.4.0, database-design.md,
system-architecture.md và yêu cầu triển khai .NET, tài liệu từng API, kiểm thử.

## Phạm vi

Hoàn thiện HTTP API đăng/sửa/ẩn tin, danh sách/bộ lọc và chi tiết ba loại nơi giữ,
câu hỏi xác minh, gửi/xét claim, hội thoại/tin nhắn bền vững, gửi/xét tiếp nhận,
lịch sử và xác nhận trao trả. Bổ sung cổng AMQP tìm kiếm/xử lý ảnh, lưu output R2,
duyệt/gỡ ảnh và dispatcher outbox .NET. Worker Python và schema findie_search thuộc
dịch vụ riêng; không giả lập kết quả AI khi worker không hoạt động.

## Chính sách triển khai

- Chủ dự án xác nhận trong chat: **cho phép duyệt nhiều claim; chat chỉ đọc sau đổi
  nơi giữ hoặc trao trả**. Không tự hủy claim/intake cũ; DTO báo stale.
- Giữ yêu cầu đăng nhập cho các API nghiệp vụ. Không mở quyền quản trị/cấp nhân viên.
- Người quản lý hiện tại tạo 0–3 câu hỏi; trả lời không bắt buộc. Snapshot bất biến.
- Chỉ người giữ thực tế/nhân viên điểm được phân công thao tác. Tạo món ở điểm chỉ
  khi nhân viên can_receive xác nhận cầm giữ; người thường chọn điểm tạo intake pending.
- Nơi ngoài hệ thống có địa chỉ công khai; người đăng được ghi nhận đã trả sau xác
  nhận bàn giao thực tế. Không tạo chat/claim tại điểm hoặc nơi ngoài hệ thống.
- Lưu metadata thành bản nháp trước khi upload; công khai cần mô tả hợp lệ và ít nhất một ảnh đã xử lý, được duyệt. Gỡ hoặc từ chối ảnh công khai cuối cùng tự ẩn tin.
- Không hard-delete dữ liệu, không rút/thu hồi claim, không upload attachment chat.

## Nghiệm thu

BR01–BR06: bộ lọc text không cần ảnh; ba nhánh giữ; claim không câu hỏi; approved mới
chat; intake pending/rejected không đổi nơi giữ; nhân viên đúng điểm mới nhận/trả.
Kiểm tra CSRF/401/403/404, chống overposting, dữ liệu riêng không vào DTO/outbox công
khai, phiên bản cũ, replay/key conflict, trả đồng thời, nhận và trả đồng thời,
thứ tự commit tin nhắn, quyền chat sau chuyển/trả, output chưa duyệt và AI không khả dụng.
Không tuyên bố đã đo chất lượng AI hoặc nghiệm thu R2 thật.
