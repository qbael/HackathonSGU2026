# Kế hoạch nâng cấp: Thông báo lỗi thân thiện & Không gian làm việc riêng cho Findie Hub (Hub Portal)

**Mã phân hệ**: `005-hub-workspace` | **Trạng thái**: Bản kế hoạch triển khai | **Ngày tạo**: 2026-11-07  
**Mục tiêu**:
1. Chuẩn hóa cơ chế xử lý lỗi frontend: Bắt và hiển thị chính xác thông điệp lỗi chi tiết từ máy chủ (`ProblemDetails`), thay thế hoàn toàn các thông báo lỗi chung chung (như 404/400).
2. Tách biệt hoàn toàn phân hệ **Findie Hub** thành một không gian làm việc chuyên nghiệp riêng biệt (`Hub Portal`), thay vì một tab lẻ tẻ nằm trong giao diện người dùng phổ thông.

---

## 1. Cải tiến Cơ chế Thông báo lỗi thân thiện (Friendly Error Handling)

### 1.1. Vấn đề hiện tại
Trong [`apps/web/src/lib/api.ts`](apps/web/src/lib/api.ts#L123-L158), khi máy chủ trả về mã lỗi (`!response.ok`), hàm `api<T>` vứt bỏ toàn bộ nội dung JSON phản hồi và thay bằng chuỗi tĩnh:
```typescript
// Hiện tại: Luôn ép lỗi 404 thành câu tĩnh này:
404: "Nội dung không còn khả dụng hoặc bạn chưa được cấp quyền truy cập."
```
Trong khi Backend trả về rất cụ thể:
```json
{ "status": 404, "title": "Không tìm thấy người dùng với email 'oanhtran01011971@gmail.con'." }
```

### 1.2. Giải pháp nâng cấp
1. **Nâng cấp `apps/web/src/lib/api.ts`**:
   - Khi `!response.ok`, hàm `api()` sẽ đọc `response.json()` để trích xuất `title`, `detail` hoặc `errors` từ cấu trúc RFC 7807 `ProblemDetails`.
   - Nếu có thông điệp cụ thể từ máy chủ $\rightarrow$ Hiển thị thông điệp đó cho người dùng.
   - Nếu không có hoặc phản hồi không phải JSON $\rightarrow$ Mới dùng câu dự phòng trong `failureMessages`.
2. **Bổ sung Client Validation tại Modal cấp quyền nhân sự ([`AdminHubs.tsx`](apps/web/src/pages/admin/AdminHubs.tsx))**:
   - Kiểm tra định dạng email cơ bản qua regex trước khi gửi request.
   - Bắt các lỗi phổ biến (như gõ nhầm đuôi `.con`, khoảng trắng đầu/cuối).

---

## 2. Xây dựng Không gian làm việc riêng cho Findie Hub (Findie Hub Portal)

### 2.1. Định vị kiến trúc mới
Tương tự như phân hệ Super Admin có `AdminLayout` và đường dẫn `/admin/*`, **Findie Hub** sẽ trở thành một Portal độc lập dành riêng cho nhân viên trạm:
- **Đường dẫn riêng**: `/hub/*` (bao gồm `/hub`, `/hub/intakes`, `/hub/inventory`, `/hub/history`).
- **Bảo vệ truy cập (`HubGuard`)**: Chỉ tài khoản có `user.isStaff === true` mới được phép truy cập.

```
Giao diện Findie Hub Portal (/hub/*)
├── HubHeader / HubSidebar (Nhận diện Hub: Màu Cam/Teal, Badge trạm đang trực, Hub Selector)
├── Tab 1: Đề nghị tiếp nhận (/hub/intakes) - Quản lý duyệt/từ chối người dân mang đồ đến trạm
├── Tab 2: Kho đồ tại trạm (/hub/inventory) - Quản lý hiện vật trong kho trạm, nút "Trao trả đồ"
└── Tab 3: Lịch sử bàn giao (/hub/history) - Lịch sử các lần nhập kho và trả đồ cho chủ
```

### 2.2. Các thành phần giao diện cần xây dựng

#### 1. `HubLayout.tsx` (Khung giao diện chung cho Hub)
- **Nhận diện thương hiệu trạm**: Logo Findie Hub với biểu tượng tòa nhà màu cam/xanh chuyên dụng cho quản trị kho.
- **Trình chọn trạm (Hub Selector)**:
  - Nếu nhân viên chỉ trực 1 trạm: Hiển thị cố định `Tên trạm` + `Địa chỉ công khai`.
  - Nếu nhân viên phụ trách nhiều trạm: Dropdown cho phép chuyển đổi nhanh trạm đang làm việc.
- **Thanh điều hướng nghiệp vụ**:
  - `Đề nghị tiếp nhận` (Badge số lượng đơn chờ duyệt).
  - `Kho đồ lưu giữ` (Số lượng hiện vật đang có trong kho).
  - `Lịch sử & Trao trả`.
- **Nút "Về ứng dụng tìm đồ"**: Cho phép nhân viên chuyển về giao diện người dùng cộng đồng bất cứ lúc nào.

#### 2. `HubIntakes.tsx` (Bàn tiếp nhận vật phẩm)
- Hiển thị danh sách các yêu cầu gửi đồ vào trạm từ người nhặt (`/api/intake-requests?pointId={selectedPointId}`).
- Thẻ thông tin trực quan: Người gửi, thời gian gửi, hình ảnh đồ vật, ghi chú.
- Thao tác 1 chạm:
  - Nút xanh: **"Tiếp nhận vào kho"** (Nhập ghi chú vị trí kho/tủ).
  - Nút xám: **"Từ chối tiếp nhận"** (Nhập lý do từ chối).

#### 3. `HubInventory.tsx` (Quản lý kho đồ thất lạc tại trạm)
- Gọi API: `GET /api/items?scope=managed&pointId={selectedPointId}` (đã có sẵn trong backend).
- Tìm kiếm nhanh đồ vật trong kho theo tên, đặc điểm, vị trí.
- Thao tác nhanh:
  - Xem chi tiết món đồ, ảnh đã che mờ.
  - Nút **"Tiến hành trao trả cho chủ sở hữu"** $\rightarrow$ Mở modal xác nhận trao trả tận tay tại trạm ([`Custody.tsx:ReturnItem`](apps/web/src/pages/Custody.tsx#L30)).

#### 4. `HubHistory.tsx` (Nhật ký lưu chuyển trạm)
- Hiển thị lịch sử các lần tiếp nhận thành công (`received`) và các lần bàn giao trả đồ cho khách (`returned`) tại trạm này.

---

## 3. Điều hướng & Tích hợp hệ thống

### 3.1. Cập nhật `App.tsx`
1. **Định tuyến mới**:
   - Khai báo các route: `/hub`, `/hub/intakes`, `/hub/inventory`, `/hub/history`.
   - Bọc bởi `protect()` và kiểm tra điều kiện `user.isStaff`.
2. **Thanh Header chính của ứng dụng**:
   - Khi nhân viên Hub đăng nhập: Nút trên Header hiển thị dạng nút công việc nổi bật:  
     `🏢 Không gian làm việc Hub (Trạm [Tên])` $\rightarrow$ Nhấp vào sẽ mở Portal `/hub`.

### 3.2. Cập nhật `landingPath` trong `apps/web/src/lib/auth.ts`
- Nhân viên trạm khi đăng nhập sẽ tự động chuyển hướng về:  
  `landingPath(user)` $\rightarrow$ **`/hub`** (thay vì `/intakes` trơ trọi như trước).

---

## 4. Kế hoạch triển khai từng giai đoạn

### Giai đoạn 1: Nâng cấp Cơ chế Thông báo lỗi (30 phút)
- [ ] Chỉnh sửa `api.ts` để đọc và ưu tiên `ProblemDetails.title` / `detail`.
- [ ] Cập nhật `adminApi.ts` và `AdminHubs.tsx` để hiển thị lỗi chi tiết khi gán email nhân viên.
- [ ] Chạy kiểm thử unit test `apps/web` đảm bảo không gãy các test cũ.

### Giai đoạn 2: Xây dựng Layout & Khung Portal Hub (45 phút)
- [ ] Tạo CSS giao diện riêng cho Hub trong `apps/web/src/styles/hub.css` (nhận diện màu cam/teal đặc trưng của trạm tiếp nhận).
- [ ] Tạo component `HubLayout.tsx` với Hub Selector và thanh điều hướng.

### Giai đoạn 3: Hiện thực các trang nghiệp vụ Hub (60 phút)
- [ ] Tích hợp màn hình `HubIntakes.tsx` (kế thừa từ `Intakes.tsx` nhưng tối ưu cho Hub Portal).
- [ ] Xây dựng màn hình `HubInventory.tsx` (quản lý kho và nút thao tác trao trả đồ).
- [ ] Xây dựng `HubHistory.tsx` (nhật ký tiếp nhận và trao trả).

### Giai đoạn 4: Hoàn thiện Điều hướng & Kiểm thử End-to-End (30 phút)
- [ ] Cập nhật định tuyến trong `App.tsx` và `SignIn.tsx`.
- [ ] Thử nghiệm đăng nhập bằng tài khoản Staff $\rightarrow$ Vào thẳng `/hub`.
- [ ] Thử nghiệm tiếp nhận đồ và trả đồ tại Hub.
