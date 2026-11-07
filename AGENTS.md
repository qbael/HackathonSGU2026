# Antigravity Agent Workspace Rules

## 1. Security & Secret Protection
- **Tuyệt đối KHÔNG đọc, mở, hiển thị hoặc sửa đổi nội dung của file `.env`** cũng như các file biến môi trường chứa bí mật (ví dụ: `.env.local`, `.env.*.local`, `.env.backup`).
- Chỉ được phép tham khảo file mẫu công khai **`.env.example`** để hiểu cấu trúc các biến cần thiết.
- Không bao giờ in ra token bí mật, mật khẩu database, OAuth client secret hay private access key trong chat, logs hoặc artifacts.

## 2. Privacy & Data Handling
- Tuân thủ nguyên tắc cốt lõi của Findie: không lưu trữ ảnh gốc ra đĩa hoặc storage; không đưa thông tin cá nhân (PII) hoặc dữ liệu nhạy cảm vào log hay cơ sở dữ liệu tìm kiếm công khai.
