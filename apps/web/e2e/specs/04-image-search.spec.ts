import { test, expect } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';
import { HomePage } from '../pages/HomePage';
import { fileURLToPath } from 'node:url';
import { SearchPage } from '../pages/SearchPage';
import { setupDefaultApiMocks } from '../utils/mockApi';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const sampleImage = path.resolve(__dirname, '../fixtures/sample-item.jpg');

test.describe('CUJ-04: Tìm kiếm bằng hình ảnh (Image Search Flow)', () => {
  test.beforeEach(async ({ page }) => {
    await setupDefaultApiMocks(page);
  });

  test('Kịch bản 4.1: Tải ảnh tìm kiếm thành công và nhận gợi ý kết quả', async ({ page }) => {
    const searchPage = new SearchPage(page);

    // 1. Mở trang tìm kiếm
    await searchPage.goto('/search');
    await expect(searchPage.uploadZone).toBeVisible();

    // 2. Tải lên tệp ảnh mẫu
    await searchPage.uploadSearchImage(sampleImage);

    // 3. Kiểm tra ảnh preview hiển thị trong danh sách ảnh đã chọn
    await searchPage.expectImagePreviewsCount(1);
    await expect(searchPage.previewItems.first()).toContainText('sample-item.jpg');

    // 4. Nhấn nút Tìm kiếm
    await searchPage.searchButton.click();

    // 5. Kiểm tra kết quả trả về hiển thị các thẻ đồ vật có thứ tự gợi ý
    await expect(searchPage.itemCards.first()).toBeVisible();
    await expect(searchPage.resultsHeading).toContainText(/Gợi ý theo ảnh/i);
    await expect(searchPage.itemCards.first()).toContainText(/Gợi ý 1/i);
  });

  test('Mở rộng khi tin trong khu vực yếu, giữ khu vực và ngày từ trang chủ', async ({ page }) => {
    const items = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../fixtures/mock-items.json'), 'utf-8')).reverse();
    await setupDefaultApiMocks(page, { items, expandSearchArea: true });
    const requests: URL[] = [];
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname === '/api/search/images') requests.push(url);
    });
    const homePage = new HomePage(page);
    const searchPage = new SearchPage(page);
    await homePage.goto('/');
    await page.locator('.search-images input[type="file"]').setInputFiles(sampleImage);
    await homePage.areaInput.fill('Cơ sở 1 - Khu A');
    await homePage.fromDateInput.fill('2026-11-01');
    await homePage.untilDateInput.fill('2026-11-06');
    await homePage.submitButton.click();

    await expect(searchPage.itemCards).toHaveCount(2);
    await expect(searchPage.areaInput).toHaveValue('Cơ sở 1 - Khu A');
    await expect(page.locator('aside input[name="from"]')).toHaveValue('2026-11-01');
    await expect(page.locator('aside input[name="until"]')).toHaveValue('2026-11-06');
    await expect(searchPage.itemCards.nth(0)).toContainText('Chìa khóa Honda');
    await expect(searchPage.itemCards.nth(1)).toContainText('Ví da nam Pedro màu đen');
    await expect(page.getByText('Chưa có tin đủ phù hợp trong khu vực nên đã tìm thêm ở nơi khác. Tin cùng khu vực vẫn xếp trước; bộ lọc ngày được giữ nguyên.')).toBeVisible();

    await searchPage.searchButton.click();
    await expect.poll(() => requests.length).toBe(2);
    for (const url of requests) {
      expect(url.searchParams.get('area')).toBe('Cơ sở 1 - Khu A');
      expect(url.searchParams.get('from')).toBe('2026-11-01');
      expect(url.searchParams.get('until')).toBe('2026-11-06');
    }
    await expect(searchPage.itemCards).toHaveCount(2);
    await page.getByRole('link', { name: 'Lọc cơ bản theo khu vực và ngày' }).click();
    await expect(searchPage.itemCards).toHaveCount(1);
    await expect(searchPage.itemCards.first()).toContainText('Chìa khóa Honda');
  });

  test('Chỉ hiện trong khu vực khi đã có tin đủ phù hợp', async ({ page }) => {
    const searchPage = new SearchPage(page);
    await searchPage.goto('/search');
    await searchPage.uploadSearchImage(sampleImage);
    await searchPage.areaInput.fill('Cơ sở 1 - Khu A');
    await searchPage.searchButton.click();
    await expect(searchPage.itemCards).toHaveCount(1);
    await expect(searchPage.itemCards.first()).toContainText('Chìa khóa Honda');
    await expect(page.getByText(/Chưa có tin đủ phù hợp trong khu vực nên đã tìm thêm/)).toHaveCount(0);
  });

  test('Tìm ngoài khu vực khi không có tin trong khu vực đã nhập', async ({ page }) => {
    const searchPage = new SearchPage(page);
    await searchPage.goto('/search');
    await searchPage.uploadSearchImage(sampleImage);
    await searchPage.areaInput.fill('Khu vực chưa có tin');
    await searchPage.searchButton.click();
    await expect(searchPage.itemCards).toHaveCount(2);
    await expect(page.getByText(/Chưa có tin đủ phù hợp trong khu vực nên đã tìm thêm/)).toBeVisible();
  });

  test('Kịch bản 4.2: Tải nhiều ảnh cùng lúc và xóa bớt ảnh preview', async ({ page }) => {
    const searchPage = new SearchPage(page);

    // 1. Mở trang tìm kiếm
    await searchPage.goto('/search');

    // 2. Tải lên 2 ảnh
    await searchPage.uploadSearchImage([sampleImage, sampleImage]);

    // 3. Kiểm tra hiển thị đủ 2 thumbnail ảnh xem trước
    await searchPage.expectImagePreviewsCount(2);

    // 4. Nhấn nút xóa ảnh thứ nhất
    await searchPage.removeImagePreview(0);

    // 5. Kiểm tra số lượng ảnh preview giảm xuống còn 1
    await searchPage.expectImagePreviewsCount(1);
  });
});
