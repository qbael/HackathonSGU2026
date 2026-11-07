import { test, expect } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SearchPage } from '../pages/SearchPage';
import { PostItemPage } from '../pages/PostItemPage';
import { setupDefaultApiMocks } from '../utils/mockApi';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const invalidPdfFile = path.resolve(__dirname, '../fixtures/invalid-file.pdf');

test.describe('CUJ-05: Kiểm thử Trường hợp Lỗi & Ngoại lệ (Sad Path & Error Handling)', () => {
  test('Kịch bản 5.1: Xử lý sự cố dịch vụ AI Search gián đoạn (503 Service Unavailable)', async ({ page }) => {
    // Giả lập AI Service gặp sự cố 503
    await setupDefaultApiMocks(page, { aiServiceAvailable: false });

    const searchPage = new SearchPage(page);
    await searchPage.goto('/search');

    // Thực hiện tìm kiếm thông minh kèm khu vực để kích hoạt fallback URL
    await searchPage.filter('Chìa khóa thông minh', 'Cơ sở 1 - Khu A');

    // Kiểm tra không sập ứng dụng và hiển thị banner cảnh báo kèm nút fallback sang tìm kiếm cơ bản
    await searchPage.expectAiServiceUnavailableBanner();
    await expect(searchPage.fallbackButton).toBeVisible();
  });

  test('Kịch bản 5.2: Kiểm tra Form Validation khi Đăng bài (ngăn chuyển bước khi thiếu thông tin)', async ({ page }) => {
    await setupDefaultApiMocks(page);

    const postItemPage = new PostItemPage(page);
    await postItemPage.goto('/post');
    await postItemPage.expectStayOnStep1();

    // Nhấn tiếp tục khi chưa nhập tiêu đề và chưa chọn ảnh
    await postItemPage.clickNext();

    // Xác nhận người dùng vẫn ở Bước 1 và form HTML5 validation ngăn việc submit
    await postItemPage.expectStayOnStep1();
  });

  test('Kịch bản 5.3: Tải lên tệp tin không hợp lệ (PDF thay vì JPEG/PNG/WebP)', async ({ page }) => {
    await setupDefaultApiMocks(page);

    const postItemPage = new PostItemPage(page);
    await postItemPage.goto('/post');

    // Tải lên file PDF không đúng định dạng cho phép
    await postItemPage.uploadFile(invalidPdfFile);

    // Xác nhận hiển thị thông báo lỗi từ chối định dạng tệp tin
    await postItemPage.expectValidationError(/Chỉ nhận ảnh JPEG, PNG hoặc WebP/i);
  });

  test('Kịch bản 5.4: Tìm kiếm không có kết quả phù hợp (Empty State)', async ({ page }) => {
    await setupDefaultApiMocks(page);

    const searchPage = new SearchPage(page);
    await searchPage.goto('/search');

    // Tìm kiếm với từ khóa hoàn toàn không khớp
    await searchPage.filter('xyz999chuatungxuathiencobietdolaai');

    // Xác nhận hiển thị vùng rỗng Empty State
    await searchPage.expectEmptyState();
  });

  test('Kịch bản 5.5: Người dùng chưa đăng nhập truy cập các tính năng yêu cầu tài khoản', async ({ page }) => {
    // Giả lập người dùng chưa đăng nhập (401 Unauthorized)
    await setupDefaultApiMocks(page, { user: null });

    // Cố gắng truy cập trang Đăng tin /post
    await page.goto('/post');

    // Xác nhận hiển thị màn hình yêu cầu đăng nhập
    const emptyState = page.locator('.empty-state');
    await expect(emptyState).toBeVisible();
    await expect(emptyState).toContainText(/Đăng nhập để tiếp tục/i);
    await expect(page.locator('a.button[href*="/signin"]')).toBeVisible();
  });
});
