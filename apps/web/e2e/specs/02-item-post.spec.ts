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
    await page.route(/\/api\/items\/[\da-f-]+\/images$/i, (route) => route.fulfill({ json: [] }));
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

  test('Tiến trình bốn bước, tóm tắt tin và quay lại chỉnh sửa giữ nguyên dữ liệu', async ({ page }) => {
    const post = new PostItemPage(page);
    await post.goto('/post');
    await expect(page.locator('.stepper li')).toHaveCount(4);
    await post.fillStep1({ title: 'Chùm chìa khóa', description: 'Chìa khóa có móc màu xanh.', area: 'Sảnh A', filePath: path.resolve(__dirname, '../fixtures/sample-item.jpg') });
    await expect(page.locator('.stepper [aria-current="step"]')).toContainText('Nơi lưu giữ');
    await expect(page.getByLabel('Tóm tắt tin đăng')).toContainText('Chùm chìa khóa');
    await post.passStep2();
    await expect(page.getByLabel('Thông tin trước khi lưu')).toContainText('Chìa khóa có móc màu xanh.');
    await page.getByRole('button', { name: 'Thêm câu hỏi xác minh' }).click();
    await page.locator('.question-field textarea').fill('Chi tiết bí mật trên móc khóa là gì?');
    await expect(page.getByLabel('Thông tin trước khi lưu')).not.toContainText('Chi tiết bí mật');
    await page.getByRole('button', { name: 'Chỉnh sửa', exact: true }).click();
    await expect(post.titleInput).toHaveValue('Chùm chìa khóa');
    await expect(post.descriptionInput).toHaveValue('Chìa khóa có móc màu xanh.');
    await post.expectImagePreviewsCount(1);
    await post.clickNext();
    await post.passStep2();
    await expect(page.locator('.question-field textarea')).toHaveValue('Chi tiết bí mật trên móc khóa là gì?');
    await post.submitFinalButton.click();
    await expect(post.pageHeading).toContainText('Thiết lập câu hỏi xác minh');
    await expect(post.confirmCheckbox).not.toBeChecked();
  });

  test('Giao diện điện thoại cho nhánh gửi ngoài hệ thống không tràn ngang', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const post = new PostItemPage(page);
    await post.goto('/post');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await post.fillStep1({ title: 'Bình nước xanh', description: 'Bình nước nhặt tại sảnh.', area: 'Sảnh A', filePath: path.resolve(__dirname, '../fixtures/sample-item.jpg') });
    await page.getByRole('radio', { name: /Đã gửi tại nơi ngoài hệ thống/ }).check();
    await page.getByLabel('Tên nơi đang giữ').fill('Quầy bảo vệ');
    await page.getByLabel('Địa chỉ công khai', { exact: true }).fill('Sảnh A, cơ sở 1');
    await post.clickNext();
    await expect(post.pageHeading).toContainText('Kiểm tra trước khi đăng');
    await expect(page.getByLabel('Thông tin trước khi lưu')).toContainText('Quầy bảo vệ');
    await expect(page.getByRole('button', { name: 'Thêm câu hỏi xác minh' })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });

  test('Nhánh gửi Findie Hub hiển thị đề nghị tiếp nhận trước khi công khai', async ({ page }) => {
    const post = new PostItemPage(page);
    await page.route('**/api/reception-points', (route) => route.fulfill({ json: [{ id: '11111111-1111-4111-8111-111111111111', name: 'Findie Hub A', publicAddress: 'Sảnh A', directions: null }] }));
    await post.goto('/post');
    await post.fillStep1({ title: 'Bình nước xanh', description: 'Bình nước nhặt tại sảnh.', area: 'Sảnh A', filePath: path.resolve(__dirname, '../fixtures/sample-item.jpg') });
    await page.getByRole('radio', { name: /Đề nghị gửi vào Findie Hub/ }).check();
    await page.getByLabel('Chọn điểm tiếp nhận').selectOption('11111111-1111-4111-8111-111111111111');
    await expect(page.locator('.post-form .notice-warning')).toContainText('nơi giữ chỉ thay đổi sau khi nhân viên nhận đồ');
    await post.clickNext();
    await expect(page.getByLabel('Thông tin trước khi lưu')).toContainText('Đề nghị gửi vào Findie Hub');
  });
});
