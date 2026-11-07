# Hướng dẫn Kiểm thử E2E (End-to-End) với Playwright cho Findie

Tài liệu này hướng dẫn cách chạy, gỡ lỗi và phát triển thêm các kịch bản kiểm thử E2E trên Findie Web Frontend (`apps/web`).

---

## 1. Cấu trúc Thư mục E2E

Bộ test E2E được tổ chức theo mô hình **Page Object Model (POM)** trong thư mục `apps/web/e2e/`:

```
apps/web/
├── e2e/
│   ├── fixtures/
│   │   ├── mock-items.json         # Dữ liệu tĩnh mẫu cho danh sách món đồ
│   │   ├── sample-item.jpg         # Tệp ảnh mẫu JPEG hợp lệ để test tải ảnh
│   │   └── invalid-file.pdf        # Tệp tin PDF giả lập để kiểm tra xác thực định dạng file
│   ├── pages/                      # Page Object Model (POM)
│   │   ├── BasePage.ts             # Các phần tử chung (Header, Footer, Menu, Auth)
│   │   ├── HomePage.ts             # Trang chủ, Hero section & thanh tìm kiếm
│   │   ├── SearchPage.ts           # Trang tìm kiếm, bộ lọc bên hông, upload ảnh & kết quả
│   │   ├── ItemDetailPage.ts       # Trang chi tiết món đồ & Form gửi yêu cầu nhận đồ
│   │   ├── ItemModal.ts            # Alias tương thích
│   │   ├── PostItemPage.ts         # Wizard 3 bước tạo bài đăng nhặt được đồ
│   │   ├── PostItemModal.ts        # Alias tương thích
│   │   ├── AdminPage.ts            # Portal Quản trị (Super Admin dashboard, users, items)
│   │   └── HubPage.ts              # Workspace Findie Hub (Trạm trực, intakes, kho đồ)
│   ├── specs/                      # Kịch bản kiểm thử (Critical User Journeys)
│   │   ├── 01-search-flow.spec.ts  # CUJ-01: Tìm kiếm & Lọc món đồ
│   │   ├── 02-item-post.spec.ts    # CUJ-02: Đăng bài nhặt được đồ kèm ảnh
│   │   ├── 03-claim-verify.spec.ts # CUJ-03: Gửi yêu cầu nhận lại đồ & câu hỏi xác minh
│   │   ├── 04-image-search.spec.ts # CUJ-04: Tìm kiếm bằng hình ảnh & quản lý ảnh xem trước
│   │   ├── 05-error-handling.spec.ts # CUJ-05: Xử lý ngoại lệ, sự cố 503, form validation & 401
│   │   ├── 06-admin-portal.spec.ts # CUJ-06: Phân hệ Quản trị (Role guard, stats, khóa user, ẩn tin)
│   │   └── 07-hub-workspace.spec.ts# CUJ-07: Không gian Trạm Hub (Role guard, tiếp nhận kho, nhật ký)
│   └── utils/
│       └── mockApi.ts              # Xử lý chặn & giả lập API routes (Network Mocking & Fault Injection)
├── playwright.config.ts            # Cấu hình Playwright
└── package.json
```

---

## 2. Chuẩn bị Môi trường Local

1. Đảm bảo đã cài đặt Node.js:
   ```bash
   node -v
   ```

2. Cài đặt các thư viện phụ thuộc của `apps/web`:
   ```bash
   npm install --prefix apps/web
   ```

3. Cài đặt browser Chromium cho Playwright (chỉ cần chạy lần đầu):
   ```bash
   npx playwright install chromium --prefix apps/web
   ```

---

## 3. Các Lệnh Chạy Kiểm thử

### 3.1 Chạy toàn bộ 7 E2E specs (19 kịch bản kiểm thử)
```bash
npm run test:e2e --prefix apps/web
```

### 3.2 Chạy với Giao diện Trực quan (Playwright UI Mode)
Chế độ này rất hữu ích để xem từng bước thao tác trực quan:
```bash
npx --prefix apps/web playwright test --ui
```

### 3.3 Chạy một file kịch bản cụ thể
```bash
# Ví dụ chạy kịch bản tìm kiếm bằng ảnh:
npx --prefix apps/web playwright test 04-image-search.spec.ts

# Ví dụ chạy kịch bản xử lý ngoại lệ:
npx --prefix apps/web playwright test 05-error-handling.spec.ts
```

### 3.4 Chạy ở chế độ Debug từng bước (Step-by-step Inspector)
```bash
npx --prefix apps/web playwright test --debug
```

### 3.5 Xem báo cáo kết quả chi tiết (HTML Report)
```bash
npx --prefix apps/web playwright show-report apps/web/playwright-report
```

---

## 4. Danh sách các Kịch bản Kiểm thử (CUJs)

| Spec File | Kịch bản | Mô tả kiểm thử |
| :--- | :--- | :--- |
| **`01-search-flow`** | CUJ-01 | Tìm kiếm từ khóa từ trang chủ -> Lọc theo khu vực -> Xem chi tiết món đồ. |
| **`02-item-post`** | CUJ-02 | Tải ảnh lên -> Nhập thông tin Bước 1 -> Chọn nơi lưu giữ Bước 2 -> Cam kết Bước 3 -> Đăng bài thành công. |
| **`03-claim-verify`** | CUJ-03 | Nhấn nhận đồ -> Điền câu trả lời xác minh quyền sở hữu -> Gửi yêu cầu -> Kiểm tra hồ sơ Claim. |
| **`04-image-search`** | 4.1 | Tải ảnh đơn lên `/search` -> Hiển thị thumbnail preview -> Trả về danh sách gợi ý kèm thứ hạng (Rank). |
| | 4.2 | Tải đồng thời nhiều ảnh -> Hiển thị đủ các thumbnail -> Bấm nút xóa từng ảnh xem trước. |
| **`05-error-handling`** | 5.1 (503 Fallback) | AI Service gián đoạn (503) -> Hiển thị banner cảnh báo an toàn -> Nút chuyển về tìm kiếm cơ bản. |
| | 5.2 (Form Validation) | Bỏ trống tiêu đề/ảnh -> Bấm tiếp tục -> Form validation ngăn chuyển sang bước tiếp theo. |
| | 5.3 (Invalid File) | Tải tệp không hợp lệ (`.pdf`) -> Hiển thị thông báo lỗi từ chối định dạng file. |
| | 5.4 (Empty State) | Nhập từ khóa không khớp -> Hiển thị giao diện rỗng (Empty State) thân thiện. |
| | 5.5 (401 Unauthorized)| Khách chưa đăng nhập vào tính năng đăng tin -> Chặn truy cập và yêu cầu đăng nhập tài khoản. |
| **`06-admin-portal`** | 6.1 (Role Guard) | Chặn người dùng thường vào `/admin` -> Hiển thị EmptyState "Không có quyền truy cập". |
| | 6.2 (Dashboard Stats) | Super Admin xem 4 khối thống kê: Tin đăng, Người dùng, Hub, Trao trả thành công. |
| | 6.3 (User Moderation) | Tìm kiếm người dùng khả nghi -> Khóa tài khoản -> Đổi trạng thái sang "Đã bị khóa". |
| | 6.4 (Item Moderation) | Kiểm duyệt tin đăng -> Tạm ẩn bài viết -> Đổi trạng thái sang "Đã ẩn". |
| **`07-hub-workspace`** | 7.1 (Role Guard) | Chặn người dùng thường vào `/hub` -> Hiển thị EmptyState "Không có quyền truy cập". |
| | 7.2 (Station Badge) | Hiển thị đúng tên trạm trực ("Trạm Tiếp Nhận - ĐH Sài Gòn") & Bàn tiếp nhận. |
| | 7.3 (Intake Process) | Tiếp nhận hiện vật vào kho -> Nhập vị trí tủ -> Tích cam kết -> Chuyển vào kho. |
| | 7.4 (Inventory & History)| Điều hướng Kho đồ lưu giữ và Nhật ký lưu chuyển & trao trả tại trạm. |

---

## 5. Chiến lược Giả lập Mạng & Tiêm Lỗi (Fault Injection)

Để đảm bảo các bài test chạy siêu tốc (< 15 giây cho toàn bộ 19 tests), không phụ thuộc vào backend hay database và loại bỏ hoàn toàn hiện tượng flaky test, toàn bộ API calls được xử lý qua helper `setupDefaultApiMocks`:

```typescript
import { setupDefaultApiMocks } from '../utils/mockApi';

// Cấu hình mặc định (Happy path):
await setupDefaultApiMocks(page);

// Giả lập sự cố dịch vụ AI (503 Service Unavailable):
await setupDefaultApiMocks(page, { aiServiceAvailable: false });

// Giả lập phiên làm việc chưa đăng nhập (401 Unauthorized):
await setupDefaultApiMocks(page, { user: null });

// Giả lập độ trễ mạng:
await setupDefaultApiMocks(page, { searchDelayMs: 500 });
```

---

## 6. Tích hợp GitHub Actions CI

Khi tạo Pull Request hoặc Push vào nhánh `main`, pipeline `.github/workflows/ci.yml` tự động chạy 4 Job:
1. `Lint & Typecheck`: Kiểm tra TypeScript và build .NET solution.
2. `Unit & Smoke Tests`: Chạy 40 Web unit tests, Python uv AI tests, root unittests và API smoke tests.
3. `Backend Docker Integration`: Chạy container `pgvector/pgvector`, build API và kiểm tra database migration integrity.
4. `Playwright E2E Tests`: Tự động chạy toàn bộ 19 kịch bản E2E trên Chromium headless. Nếu có lỗi xảy ra, artifact `playwright-report` sẽ tự động được tải lên để xem lại trace và video.
