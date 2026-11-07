import { test, expect } from '@playwright/test';
import { HomePage } from '../pages/HomePage';
import { SearchPage } from '../pages/SearchPage';
import { ItemDetailPage } from '../pages/ItemDetailPage';
import { setupDefaultApiMocks } from '../utils/mockApi';

test.describe('CUJ-01: Tìm kiếm đồ thất lạc (Search & Filter Flow)', () => {
  test.beforeEach(async ({ page }) => {
    await setupDefaultApiMocks(page);
  });

  test('Người dùng tìm kiếm món đồ từ trang chủ và xem chi tiết đồ vật', async ({ page }) => {
    const homePage = new HomePage(page);
    const searchPage = new SearchPage(page);
    const itemDetailPage = new ItemDetailPage(page);

    // 1. Mở trang chủ
    await homePage.goto('/');
    await homePage.expectPageTitle(/Findie/i);

    // 2. Nhập từ khóa tìm kiếm và khu vực
    await homePage.searchFromHome('Chìa khóa Honda', 'Cơ sở 1 - Khu A');

    // 3. Hệ thống chuyển hướng sang trang /search và hiển thị kết quả
    await expect(page).toHaveURL(/\/search/);
    await expect(searchPage.itemCards.first()).toBeVisible();
    await expect(searchPage.itemCards.first()).toContainText('Chìa khóa Honda');

    // 4. Click vào thẻ kết quả đầu tiên
    await searchPage.clickFirstItem();

    // 5. Trang chi tiết mở ra, xác thực các thông tin cốt lõi
    await expect(page).toHaveURL(/\/items\/[\da-f-]+/i);
    await itemDetailPage.expectItemDetails('Chìa khóa Honda', 'Cơ sở 1 - Khu A');
    await expect(itemDetailPage.claimButton).toBeVisible();
  });
});
