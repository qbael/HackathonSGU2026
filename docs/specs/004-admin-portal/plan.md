# Kế hoạch triển khai: Trang Quản trị (Admin Portal)

**Mã phân hệ**: `004-admin-portal` | **Trạng thái**: Bản kế hoạch chính thức | **Ngày tạo**: 2026-11-06  
**Phạm vi**: Xây dựng phân hệ Quản trị viên (Super Admin) tích hợp trong hệ thống Findie.  

---

## 1. Mục tiêu & Nguyên tắc thiết kế

### 1.1. Mục tiêu chính
Cung cấp bảng điều khiển trung tâm cho Quản trị viên (Super Admin) nhằm:
1. Giám sát tổng quan tình trạng hệ thống (số lượng tin đăng, người dùng, điểm tiếp nhận Hub, tỉ lệ trao trả thành công).
2. Quản lý người dùng: Tra cứu thông tin và vô hiệu hóa / kích hoạt lại tài khoản có dấu hiệu vi phạm.
3. Kiểm duyệt nội dung chủ động: Kiểm tra bài đăng và hình ảnh (đặc biệt là nguy cơ lộ lọt PII sau AI Redaction), thực hiện tạm ẩn bài hoặc thu hồi ảnh vi phạm.
4. Quản lý mạng lưới Findie Hub: Khởi tạo điểm tiếp nhận mới, đóng/mở trạm, gán và thu hồi quyền nhân viên trạm (`point_staff`).

### 1.2. Tuân thủ Hiến chương & Ràng buộc cốt lõi
- **Tận dụng 100% Database Schema hiện có**: Không yêu cầu tạo bảng mới hay chạy migration cơ sở dữ liệu. Tất cả trạng thái đều ánh xạ trực tiếp vào các cột có sẵn trong `FindieDbContext` (`disabled_at`, `publication_state`, `lifecycle`, `retired_at`, `active`, `revoked_at`).
- **Không phân xử tranh chấp**: Findie là nền tảng kết nối cộng đồng, không có thẩm quyền tư pháp. Module quản trị chỉ ghi nhận dòng dịch chuyển vật phẩm (`custody_events`) và hỗ trợ can thiệp kỹ thuật (ẩn tin đăng khi có khiếu nại gian lận), không ra phán quyết quyền sở hữu.
- **Không lưu trữ ảnh gốc**: Giữ nguyên nguyên tắc bảo mật ảnh của Findie; chỉ hiển thị và quản trị ảnh đã che mờ (redacted image) từ Cloudflare R2 / Object Storage.
- **Định danh Admin đơn giản & an toàn**: Xác thực qua danh sách email quản trị viên (`ADMIN_EMAILS` trong cấu hình backend), gán claim/role Admin trong phiên làm việc.
- **Tích hợp giao diện gọn nhẹ**: Xây dựng phân hệ `/admin/*` trực tiếp trong ứng dụng web React hiện có (`apps/web`), tái sử dụng phong cách giao diện và component library hiện có.

---

## 2. Kiến trúc & Phân bổ Công nghệ

### 2.1. Backend (.NET 10 Web API - `apps/api`)
- **Tầng xác thực & phân quyền**:
  - Đọc danh sách cấu hình `AdminEmails` (chuỗi phân cách bằng dấu phẩy trong cấu hình / biến môi trường).
  - Viết policy / filter xác thực: `AdminAuthorizeAttribute` hoặc kiểm tra email người dùng hiện tại có nằm trong danh sách Admin hay không.
- **Controllers & DTOs**:
  - `AdminOverviewController`: Thống kê tổng số lượng bài đăng, người dùng, giao dịch custody.
  - `AdminUsersController`: Tìm kiếm, phân trang và chuyển đổi trạng thái người dùng (`DisabledAt`).
  - `AdminItemsController`: Kiểm duyệt bài đăng (`PublicationState = 'hidden'`) và thu hồi ảnh (`RetiredAt = UtcNow`).
  - `AdminPointsController`: Tạo mới trạm tiếp nhận (`ReceptionPoint`), bật/tắt hoạt động, gán quyền nhân sự (`PointStaff`).

### 2.2. Frontend (React 19 / Vite - `apps/web`)
- **Định tuyến & Bảo vệ (Route Guard)**:
  - Route `/admin`: Bọc bởi `AdminGuard` kiểm tra quyền admin của tài khoản hiện tại trước khi render; nếu không đủ quyền, điều hướng về `/` hoặc thông báo lỗi 403.
- **Giao diện & Thành phần**:
  - `AdminLayout`: Sidebar quản trị (Dashboard, Người dùng, Bài đăng & Ảnh, Điểm tiếp nhận Hub).
  - 4 Trang nghiệp vụ:
    1. `AdminDashboard.tsx`: Bảng số liệu thống kê & biểu đồ trạng thái.
    2. `AdminUsers.tsx`: Danh sách người dùng, tìm kiếm theo email/tên, nút Khóa / Kích hoạt tài khoản.
    3. `AdminItems.tsx`: Danh sách bài viết & ảnh đã qua AI xử lý; thao tác Ẩn bài / Khôi phục bài, Thu hồi ảnh vi phạm.
    4. `AdminHubs.tsx`: Danh sách Hub, form tạo Hub mới, modal cấp quyền nhân viên cho Hub (`can_receive`, `can_return`).

---

## 3. Ánh xạ Dữ liệu (Database Mapping)

Mọi thao tác quản trị viên đều cập nhật trực tiếp vào cấu trúc cơ sở dữ liệu hiện có:

| Hành động của Admin | Bảng Database | Cột & Giá trị cập nhật |
| :--- | :--- | :--- |
| **Khóa tài khoản** | `app_users` | `disabled_at = DateTimeOffset.UtcNow` |
| **Mở khóa tài khoản** | `app_users` | `disabled_at = null` |
| **Ẩn bài viết vi phạm** | `items` | `publication_state = 'hidden'`, tăng `row_version` |
| **Khôi phục bài viết** | `items` | `publication_state = 'published'`, tăng `row_version` |
| **Xóa bài viết** | `items` | `lifecycle = 'deleted'`, tăng `row_version` |
| **Thu hồi ảnh lộ PII** | `item_images` | `retired_at = DateTimeOffset.UtcNow`, `reviewed_by = AdminId` |
| **Tạo điểm tiếp nhận** | `reception_points` | Insert bản ghi mới với `active = true` |
| **Đóng/Mở điểm tiếp nhận** | `reception_points` | `active = true/false` |
| **Cấp quyền nhân viên Hub**| `point_staff` | Insert bản ghi `(point_id, user_id, can_receive, can_return)` |
| **Hủy quyền nhân viên Hub**| `point_staff` | `revoked_at = DateTimeOffset.UtcNow` |

---

## 4. Chi tiết API Backend cần xây dựng

Tất cả các API dưới đây đều yêu cầu quyền Quản trị viên:

### 4.1. Thống kê & Tổng quan
- `GET /api/admin/overview`
  - **Mô tả**: Trả về số liệu thống kê: tổng bài viết theo trạng thái (`active`, `returned`), tổng số người dùng, tổng số Hub đang mở, số lượt bàn giao thành công.

### 4.2. Quản lý Người dùng
- `GET /api/admin/users?query=...&page=1&pageSize=20`
  - **Mô tả**: Danh sách người dùng hệ thống, hỗ trợ tìm kiếm theo tên hiển thị hoặc email.
- `POST /api/admin/users/{id}/toggle-status`
  - **Mô tả**: Khóa (đặt `DisabledAt`) hoặc mở khóa (xóa `DisabledAt`) tài khoản.

### 4.3. Kiểm duyệt Bài đăng & Hình ảnh
- `GET /api/admin/items?status=...&page=1&pageSize=20`
  - **Mô tả**: Danh sách tin đăng thất lạc, lọc theo trạng thái (`published`, `hidden`, `deleted`).
- `POST /api/admin/items/{id}/set-publication`
  - **Body**: `{ "publicationState": "hidden" | "published" }`
  - **Mô tả**: Tạm ẩn bài viết khi có dấu hiệu vi phạm thông tin hoặc gian lận.
- `POST /api/admin/items/{itemId}/images/{imageId}/retire`
  - **Mô tả**: Thu hồi hình ảnh nếu phát hiện thông tin nhạy cảm chưa được che mờ hết.

### 4.4. Quản lý Điểm tiếp nhận Findie Hub
- `GET /api/admin/points`
  - **Mô tả**: Lấy toàn bộ danh sách điểm tiếp nhận (cả đang hoạt động và đã đóng).
- `POST /api/admin/points`
  - **Body**: `{ "name": "...", "publicAddress": "...", "directions": "..." }`
  - **Mô tả**: Tạo một điểm tiếp nhận mới.
- `PATCH /api/admin/points/{id}/toggle`
  - **Mô tả**: Đổi trạng thái hoạt động của trạm (`active = !active`).
- `GET /api/admin/points/{id}/staff`
  - **Mô tả**: Danh sách nhân viên được gán quyền tại Hub này.
- `POST /api/admin/points/{id}/staff`
  - **Body**: `{ "userEmail": "...", "canReceive": true, "canReturn": true }`
  - **Mô tả**: Gán quyền nhân sự tiếp nhận/trao trả cho một tài khoản tại Hub.
- `DELETE /api/admin/points/{id}/staff/{userId}`
  - **Mô tả**: Thu hồi quyền nhân sự tại Hub (`revoked_at = UtcNow`).

---

## 5. Lộ trình thực hiện (Implementation Roadmap)

### Giai đoạn 1: Backend Foundation & API Quản trị
1. **Admin Authorization**: Thêm kiểm tra quyền Admin vào cấu hình và tạo attribute/middleware kiểm tra quyền dựa trên email.
2. **Admin Controllers**: Hiện thực các Controller: `AdminOverviewController`, `AdminUsersController`, `AdminItemsController`, `AdminPointsController`.
3. **Kiểm thử API**: Viết test hoặc kiểm thử HTTP đảm bảo các thao tác cập nhật DB chính xác và chặn người dùng thường truy cập.

### Giai đoạn 2: Frontend Layout & Route Guard
1. **Auth Context Extension**: Cập nhật thông tin profile người dùng để nhận diện cờ `isAdmin`.
2. **Admin Guard & Navigation**: Tạo `AdminGuard` và liên kết điều hướng vào trang Admin từ Menu người dùng (chỉ hiển thị khi `isAdmin === true`).
3. **Admin Layout**: Xây dựng thanh điều hướng sidebar và khung giao diện chung của trang quản trị.

### Giai đoạn 3: Hiện thực các Màn hình Quản trị (Frontend)
1. **Màn hình Tổng quan (`AdminDashboard`)**: Hiển thị các thẻ thống kê trực quan.
2. **Màn hình Người dùng (`AdminUsers`)**: Tìm kiếm người dùng, bảng danh sách có badge trạng thái và nút Khóa/Mở tài khoản.
3. **Màn hình Kiểm duyệt (`AdminItems`)**: Lưới danh sách bài đăng & ảnh, nút Xem chi tiết, Ẩn bài viết, Thu hồi ảnh.
4. **Màn hình Quản lý Hub (`AdminHubs`)**: Bảng danh sách Hub, popup thêm Hub mới, modal quản lý nhân sự từng Hub.

### Giai đoạn 4: Kiểm thử đầu-cuối & Nghiệm thu
1. Kiểm tra kịch bản Quản trị viên đăng nhập -> Tạo Hub -> Gán nhân viên.
2. Kiểm tra tài khoản nhân viên được gán quyền đăng nhập và thao tác bình thường tại `/intakes` và `/items/:id/return`.
3. Kiểm tra kịch bản ẩn bài viết vi phạm -> Đảm bảo bài viết biến mất khỏi trang tìm kiếm công khai.
4. Đảm bảo toàn bộ quy trình không vi phạm quyền riêng tư và quy tắc không lưu ảnh gốc.
