import { test, expect } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PostItemPage } from '../pages/PostItemPage';
import { setupDefaultApiMocks } from '../utils/mockApi';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test.describe('CUJ-02: Đăng bài nhặt được đồ (Item Ingestion Flow)', () => {
  test.beforeEach(async ({ page }) => {
    await setupDefaultApiMocks(page);
  });

  test('Người dùng đăng tin nhặt được đồ với ảnh và thông tin đầy đủ', async ({ page }) => {
    const postItemPage = new PostItemPage(page);
    const sampleImagePath = path.resolve(__dirname, '../fixtures/sample-item.jpg');

    // 1. Mở trang tạo bài đăng
    await postItemPage.goto('/post');
    await expect(postItemPage.pageHeading).toContainText(/Kể một chút về món đồ/i);

    // 2. Điền Bước 1: Thông tin và tải ảnh
    await postItemPage.fillStep1({
      title: 'Chùm chìa khóa xe máy',
      filePath: sampleImagePath,
      description: 'Nhặt được tại bàn ghế đá sân trước khu A, có gắn móc khóa Doraemon.',
      area: 'Cơ sở 1 - Khu A',
    });

    // 3. Bước 2: Nơi lưu giữ (chọn Tôi đang tự giữ)
    await postItemPage.passStep2();

    // 4. Bước 3: Xác nhận cam kết và gửi bài
    await postItemPage.finishStep3();

    // 5. Kiểm tra bài đăng đã lưu thành công
    await postItemPage.expectSavedSuccessfully();
  });

  test('Người dùng có thể gỡ ảnh đã chọn bằng dấu x khi đăng tin nhặt được đồ', async ({ page }) => {
    const postItemPage = new PostItemPage(page);
    const sampleImagePath = path.resolve(__dirname, '../fixtures/sample-item.jpg');

    await postItemPage.goto('/post');
    await postItemPage.uploadFile([sampleImagePath, sampleImagePath]);
    await postItemPage.expectImagePreviewsCount(2);

    await postItemPage.removeImagePreview(0);
    await postItemPage.expectImagePreviewsCount(1);
  });
});
