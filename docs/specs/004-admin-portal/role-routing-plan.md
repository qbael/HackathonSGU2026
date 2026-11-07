# Kế hoạch điều chỉnh: Phân luồng điều hướng & Nhận diện vai trò sau Đăng nhập

**Mã phân hệ**: `004-role-routing` | **Trạng thái**: Bản kế hoạch triển khai | **Ngày tạo**: 2026-11-07  
**Mục tiêu**: Tự động chuyển hướng đúng không gian làm việc sau đăng nhập và làm rõ danh tính vai trò (Super Admin / Hub Staff / Người dùng thường) trên toàn hệ thống.

---

## 1. Ma trận phân luồng vai trò (Landing Matrix)

Khi đăng nhập thành công:
- Nếu người dùng truy cập từ một liên kết cụ thể (ví dụ: đang xem bài đăng `/items/{id}` rồi mới bấm đăng nhập) $\rightarrow$ **Giữ nguyên liên kết đó** (`returnUrl`).
- Nếu người dùng bấm đăng nhập trực tiếp từ trang chủ (`returnUrl` là `/` hoặc rỗng) $\rightarrow$ **Tự động phân luồng theo cấp độ quyền**:

| Vai trò | Điều kiện nhận diện | Điểm đến sau đăng nhập (Default Landing) | Nhận diện trên Header |
| :--- | :--- | :--- | :--- |
| **Super Admin** | Email nằm trong whitelist `ADMIN_EMAILS` | `/admin` (Bảng điều khiển Quản trị) | Badge đỏ/xanh `[Super Admin]` + Nút chuyển nhanh vào `/admin` ngay trên Header |
| **Admin Hub (Staff)** | Có bản ghi trong `point_staff` (`revoked_at IS NULL`) | `/intakes` (Bàn tiếp nhận & trao trả Hub) | Badge cam `[Findie Hub: Tên trạm]` dẫn thẳng vào `/intakes` |
| **Người dùng thường** | Không thuộc 2 nhóm trên | `/` (Trang tìm kiếm cộng đồng) | Giao diện tìm kiếm và đăng tin tiêu chuẩn |

---

## 2. Chi tiết các bước điều chỉnh kỹ thuật

### Bước 1: Mở rộng Hợp đồng dữ liệu Backend (`apps/api`)

#### 1.1. Cập nhật `UserProfile.cs`
Bổ sung cờ `IsStaff` và danh sách tóm tắt các trạm Hub mà người đó đang phụ trách:

```csharp
namespace Findie.Api.Contracts;

public sealed record ManagedPointSummary(Guid Id, string Name);

public sealed record UserProfile(
    Guid Id,
    string? Email,
    string DisplayName,
    DateTimeOffset CreatedAt,
    bool IsAdmin = false,
    bool IsStaff = false,
    IReadOnlyList<ManagedPointSummary>? ManagedPoints = null
);
```

#### 1.2. Cập nhật `UserService.cs`
Khi truy vấn thông tin người dùng tại `GetProfileAsync`:
1. Kiểm tra quyền `isAdmin`: qua `adminOptions.IsAdmin(user.Email)`.
2. Kiểm tra quyền `isStaff` và lấy danh sách Hub:
   - Truy vấn bảng `database.PointStaff` (kết hợp `ReceptionPoints`) với điều kiện:
     `staff.UserId == userId && staff.RevokedAt == null && staff.Point.Active == true`.
3. Đóng gói vào `UserProfile`.

---

### Bước 2: Tự động chuyển hướng tại Callback đăng nhập (`GoogleAuthController.cs`)

Tại endpoint `Callback` của [`GoogleAuthController.cs`](file:///mnt/d/CNTT-SGU/HK7/Hackathon/FindieHackathon/apps/api/Controllers/GoogleAuthController.cs):
- Sau khi `CompleteSignInAsync()` thành công:
  - Nếu `returnUrl` là `"/"` hoặc rỗng:
    - Đọc profile của user vừa đăng nhập.
    - Nếu `user.IsAdmin` $\rightarrow$ Chuyển hướng `LocalRedirect("/admin")`.
    - Nếu `user.IsStaff` $\rightarrow$ Chuyển hướng `LocalRedirect("/intakes")`.
    - Ngược lại $\rightarrow$ Chuyển hướng `LocalRedirect("/")`.
  - Nếu `returnUrl` khác `"/"` (người dùng chủ động truy cập trước đó) $\rightarrow$ Giữ nguyên `LocalRedirect(returnUrl)`.

---

### Bước 3: Cập nhật Hợp đồng Frontend (`apps/web`)

#### 3.1. Cập nhật Type trong `apps/web/src/lib/auth.ts`
```typescript
export type ManagedPoint = {
  id: string;
  name: string;
};

export type UserProfile = {
  id: string;
  email: string | null;
  displayName: string;
  createdAt: string;
  isAdmin?: boolean;
  isStaff?: boolean;
  managedPoints?: ManagedPoint[];
};
```
*Cập nhật hàm kiểm tra `loadUser()` đảm bảo xác thực an toàn các trường mới này.*

#### 3.2. Cập nhật trang `SignIn.tsx`
Khi người dùng đã đăng nhập sẵn mà mở trang `/signin`:
- Nút *"Tiếp tục với Findie"* sẽ ưu tiên dẫn về trang làm việc tương ứng:
  - Admin $\rightarrow$ `/admin`
  - Staff $\rightarrow$ `/intakes`
  - User thường $\rightarrow$ `/`

---

### Bước 4: Tối ưu thanh điều hướng Header (`apps/web/src/App.tsx`)

Thay vì giấu các lối tắt trong menu con:
1. **Đối với Super Admin**:
   - Thêm nút màu xanh thương hiệu **"Trang Quản trị"** ngay cạnh Avatar trên Header để chuyển đổi 1 chạm giữa khu vực Quản trị và Giao diện người dùng.
2. **Đối với Nhân viên trạm (Hub Staff)**:
   - Mục **"Findie Hub"** trên Header sẽ hiển thị trạng thái đang trực trạm (ví dụ: `Trực trạm Hub Tân Bình`) và dẫn thẳng tới `/intakes`.
3. **Menu tài khoản (Dropdown)**:
   - Phân định rõ ràng vai trò tài khoản: hiển thị thẻ Badge `Super Admin` hoặc `Nhân viên Findie Hub` ngay dưới tên người dùng.

---

## 3. Danh sách tệp cần chỉnh sửa & Kiểm thử

### Các tệp thay đổi:
1. [`apps/api/Contracts/UserProfile.cs`](file:///mnt/d/CNTT-SGU/HK7/Hackathon/FindieHackathon/apps/api/Contracts/UserProfile.cs)
2. [`apps/api/Services/UserService.cs`](file:///mnt/d/CNTT-SGU/HK7/Hackathon/FindieHackathon/apps/api/Services/UserService.cs)
3. [`apps/api/Controllers/GoogleAuthController.cs`](file:///mnt/d/CNTT-SGU/HK7/Hackathon/FindieHackathon/apps/api/Controllers/GoogleAuthController.cs)
4. [`apps/web/src/lib/auth.ts`](file:///mnt/d/CNTT-SGU/HK7/Hackathon/FindieHackathon/apps/web/src/lib/auth.ts)
5. [`apps/web/src/lib/auth.test.ts`](file:///mnt/d/CNTT-SGU/HK7/Hackathon/FindieHackathon/apps/web/src/lib/auth.test.ts)
6. [`apps/web/src/pages/SignIn.tsx`](file:///mnt/d/CNTT-SGU/HK7/Hackathon/FindieHackathon/apps/web/src/pages/SignIn.tsx)
7. [`apps/web/src/App.tsx`](file:///mnt/d/CNTT-SGU/HK7/Hackathon/FindieHackathon/apps/web/src/App.tsx)

### Kịch bản kiểm thử (Verification Checklist):
- [ ] **Kịch bản 1 (Super Admin)**: Đăng nhập bằng email trong `ADMIN_EMAILS` $\rightarrow$ Tự động vào `/admin`, thấy badge `Super Admin`.
- [ ] **Kịch bản 2 (Hub Staff)**: Dùng Admin gán quyền nhân viên cho 1 email $\rightarrow$ Dùng tài khoản đó đăng nhập $\rightarrow$ Tự động vào `/intakes`, thấy tên Hub đang trực.
- [ ] **Kịch bản 3 (Người dùng thường)**: Đăng nhập tài khoản mới $\rightarrow$ Vào `/`, giao diện tìm kiếm tiêu chuẩn.
- [ ] **Kịch bản 4 (Deep Link)**: Đang ở trang chi tiết `/items/{id}` rồi mới bấm đăng nhập $\rightarrow$ Đăng nhập xong quay đúng lại trang chi tiết `/items/{id}` (không bị ghi đè bởi trang mặc định).
- [ ] **Kịch bản 5 (Unit Tests)**: Toàn bộ test của `auth.test.ts` và `adminApi.test.ts` chạy đạt 100%.
