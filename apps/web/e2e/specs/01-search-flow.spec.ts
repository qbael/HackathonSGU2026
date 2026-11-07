import { test, expect } from '@playwright/test';
import { HomePage } from '../pages/HomePage';
import { SearchPage } from '../pages/SearchPage';
import { ItemDetailPage } from '../pages/ItemDetailPage';
import { setupDefaultApiMocks } from '../utils/mockApi';

test.describe('CUJ-01: Tìm kiếm đồ thất lạc (Search & Filter Flow)', () => {
  test.beforeEach(async ({ page }) => {
    await setupDefaultApiMocks(page);
  });

  for (const url of [
    '/search',
    '/search?mode=text&area=SGU&from=2026-11-01',
    '/search?mode=image&area=SGU&until=2026-11-06',
    '/search?mode=basic',
    '/search?q=%20%20&area=SGU',
  ]) {
    test(`Không tự tìm khi mở hoặc tải lại trang thiếu ảnh và mô tả: ${url}`, async ({ page }) => {
      const requests: string[] = [];
      page.on('request', (request) => {
        if (/\/api\/(search|items)(\?|\/|$)/.test(new URL(request.url()).pathname)) {
          requests.push(request.url());
        }
      });
      await page.goto(url);
      await expect(page.getByRole('heading', { name: 'Bạn còn nhớ điều gì về món đồ?' })).toBeVisible();
      await page.reload();
      await expect(page.getByRole('heading', { name: 'Bạn còn nhớ điều gì về món đồ?' })).toBeVisible();
      await expect(page.locator('.item-card')).toHaveCount(0);
      expect(requests).toEqual([]);
    });
  }

  test('Đặt lại xóa điều kiện và kết quả, không phát sinh tìm kiếm mới', async ({ page }) => {
    const searchPage = new SearchPage(page);
    const requests: string[] = [];
    page.on('request', (request) => {
      if (/\/api\/(search|items)(\?|\/|$)/.test(new URL(request.url()).pathname)) requests.push(request.url());
    });
    await searchPage.goto('/search');
    await searchPage.filter('Chìa khóa Honda', 'Cơ sở 1 - Khu A');
    await expect(searchPage.itemCards.first()).toBeVisible();
    const count = requests.length;
    await page.getByRole('link', { name: 'Đặt lại', exact: true }).click();
    await expect(searchPage.queryInput).toHaveValue('');
    await expect(searchPage.areaInput).toHaveValue('');
    await expect(searchPage.itemCards).toHaveCount(0);
    await expect(page.locator('.search-welcome')).toBeVisible();
    expect(requests).toHaveLength(count);
  });

  test('Không gửi mô tả chỉ có khoảng trắng hoặc bộ lọc cơ bản trống', async ({ page }) => {
    const searchPage = new SearchPage(page);
    const requests: string[] = [];
    page.on('request', (request) => {
      if (/\/api\/(search|items)(\?|\/|$)/.test(new URL(request.url()).pathname)) requests.push(request.url());
    });
    await searchPage.goto('/search');
    await searchPage.filter('   ', 'SGU');
    await expect(page.getByRole('alert')).toContainText('Hãy nhập mô tả hoặc chọn');
    await searchPage.modeSelect.selectOption('basic');
    await searchPage.areaInput.fill('');
    await searchPage.searchButton.click();
    await expect(page.getByRole('alert')).toContainText('Hãy nhập từ khóa, khu vực hoặc khoảng ngày');
    expect(requests).toEqual([]);
  });

  test('Chủ động chọn bộ lọc cơ bản vẫn tìm được theo khu vực', async ({ page }) => {
    const searchPage = new SearchPage(page);
    await searchPage.goto('/search');
    await searchPage.modeSelect.selectOption('basic');
    await searchPage.areaInput.fill('Cơ sở 1 - Khu A');
    await searchPage.searchButton.click();
    await expect(page).toHaveURL(/mode=basic/);
    await expect(searchPage.itemCards).toHaveCount(1);
    await expect(searchPage.itemCards.first()).toContainText('Chìa khóa Honda');
  });

  for (const mode of ['text', 'basic']) {
    test(`Enter tìm kiếm, Shift+Enter xuống dòng trong chế độ ${mode}`, async ({ page }) => {
      const searchPage = new SearchPage(page);
      await searchPage.goto('/search');
      await searchPage.modeSelect.selectOption(mode);
      await searchPage.queryInput.fill('Chìa khóa Honda');
      await searchPage.queryInput.press('End');
      await searchPage.queryInput.press('Shift+Enter');
      await expect(searchPage.queryInput).toHaveValue('Chìa khóa Honda\n');
      await expect(searchPage.itemCards).toHaveCount(0);
      await searchPage.queryInput.press('Enter');
      await expect(searchPage.itemCards.first()).toContainText('Chìa khóa Honda');
    });
  }

  test('Enter từ trang chủ thực hiện tìm kiếm mô tả', async ({ page }) => {
    await page.goto('/');
    await page.locator('#home-query').fill('Chìa khóa Honda');
    await page.locator('#home-query').press('Enter');
    await expect(page).toHaveURL(/\/search/);
    await expect(page.locator('.item-card').first()).toContainText('Chìa khóa Honda');
  });

  test('Enter gửi tìm từ ô nhập và giữ thao tác bàn phím của liên kết', async ({ page }) => {
    const searchPage = new SearchPage(page);
    const requests: string[] = [];
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/search') requests.push(request.url());
    });
    await searchPage.goto('/search');
    await searchPage.queryInput.fill('Chìa khóa Honda');
    await page.locator('.search-options summary').click();
    const targets = [
      '#search-query', 'aside input[name="area"]',
      'aside input[name="from"]', 'aside input[name="until"]', 'aside input[name="lostAt"]',
      'aside button[type="submit"]',
    ];
    for (const [index, target] of targets.entries()) {
      await page.locator(target).focus();
      const response = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/search');
      await page.keyboard.press('Enter');
      await response;
      await expect(searchPage.searchButton).toBeEnabled();
      await expect(searchPage.itemCards.first()).toContainText('Chìa khóa Honda');
      expect(requests, target).toHaveLength(index + 1);
    }
    await page.locator('#search-results-title').focus();
    await page.keyboard.press('Enter');
    await page.evaluate(() => new Promise(requestAnimationFrame));
    expect(requests).toHaveLength(targets.length);
    await page.locator('.main-nav a:first-child').focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator('#home-query')).toBeVisible();
    expect(requests).toHaveLength(targets.length);
  });

  test('Enter ngoài ô nhập không gửi thêm yêu cầu khi đang tìm kiếm', async ({ page }) => {
    await setupDefaultApiMocks(page, { searchDelayMs: 500 });
    const searchPage = new SearchPage(page);
    const requests: string[] = [];
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/search') requests.push(request.url());
    });
    await searchPage.goto('/search');
    await searchPage.queryInput.fill('Chìa khóa Honda');
    await searchPage.areaInput.focus();
    await page.keyboard.press('Enter');
    await expect(searchPage.searchButton).toBeDisabled();
    await page.keyboard.press('Enter');
    await page.keyboard.press('Enter');
    await expect(searchPage.itemCards.first()).toContainText('Chìa khóa Honda');
    expect(requests).toHaveLength(1);
  });

  test('Enter không gửi mô tả trống hoặc ngắt thao tác nhập bằng IME', async ({ page }) => {
    const searchPage = new SearchPage(page);
    const requests: string[] = [];
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/search') requests.push(request.url());
    });
    await searchPage.goto('/search');
    await searchPage.queryInput.press('Enter');
    await expect(page.getByRole('alert')).toContainText('Hãy nhập mô tả hoặc chọn');
    await searchPage.queryInput.fill('Chìa khóa Honda');
    await searchPage.queryInput.dispatchEvent('keydown', { key: 'Enter', isComposing: true });
    await expect(searchPage.itemCards).toHaveCount(0);
    expect(requests).toEqual([]);
  });

  test('Kết quả trên điện thoại hiển thị số lượng, điều kiện và không tràn ngang', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const searchPage = new SearchPage(page);
    await searchPage.goto('/search');
    await page.getByRole('button', { name: 'Thêm mô tả' }).click();
    await expect(searchPage.queryInput).toBeFocused();
    await searchPage.filter('Chìa khóa Honda', 'Cơ sở 1 - Khu A');
    await expect(searchPage.itemCards).toHaveCount(1);
    await expect(page.locator('.results-count')).toContainText('1 gợi ý');
    await expect(page.getByLabel('Điều kiện đã tìm')).toContainText('Cơ sở 1 - Khu A');
    await expect(page.locator('#search-results-title')).toBeFocused();
    await expect(page.locator('#search-results-title')).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole('link', { name: 'Sửa tìm kiếm' }).click();
    await expect(searchPage.queryInput).toBeFocused();
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
