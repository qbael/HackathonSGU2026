import { test, expect } from '@playwright/test';
import { setupDefaultApiMocks } from '../utils/mockApi';

const savedSearch = {
  id: 'saved-1', text: 'Ví da đen', imageCount: 1, area: 'SGU', from: null, until: null,
  lostAt: null, createdAt: '2026-11-01T00:00:00Z', lastCheckedAt: '2026-11-02T00:00:00Z',
  needsRefresh: false,
  matches: [{ itemId: '12345678-1234-1234-1234-123456789012', title: 'Ví nhặt được',
    foundArea: 'SGU', score: 0.9, createdAt: '2026-11-02T00:00:00Z', readAt: null as string | null }],
};

test('saves the submitted search, retries safely and supports keyboard activation', async ({ page }) => {
  await setupDefaultApiMocks(page);
  await page.route('**/api/search', route => route.fulfill({ json: {
    items: [], mode: 'text', searchProfileId: 'text-v1', searchProfileVersion: 1,
    partial: false, filtersRelaxed: false, fallbackUrl: '/api/items',
  } }));
  const keys: string[] = [];
  await page.route(/\/api\/saved-searches(?:\?.*)?$/, async route => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: [] });
      return;
    }
    expect(route.request().method()).toBe('POST');
    expect(route.request().headers()['x-csrf-token']).toBeTruthy();
    keys.push(route.request().headers()['idempotency-key']);
    expect(route.request().postDataBuffer()!.toString()).toContain('Ví da đen');
    expect(route.request().postDataBuffer()!.toString()).not.toContain('Mô tả chưa tìm');
    expect(new URL(route.request().url()).searchParams.get('area')).toBe('SGU');
    await route.fulfill(keys.length === 1 ? { status: 503, json: { title: 'Tạm thời chưa lưu được' } }
      : { json: { ...savedSearch, imageCount: 0, matches: [] } });
  });
  await page.goto('/search?q=Ví%20da%20đen&area=SGU');
  const save = page.getByRole('button', { name: 'Theo dõi tìm kiếm này', exact: true });
  await expect(save).toBeVisible();
  await page.locator('#search-query').fill('Mô tả chưa tìm');
  await save.focus();
  await save.press('Enter');
  await expect(page.getByRole('alert')).toContainText('Tạm thời chưa lưu được');
  await save.click();
  await expect(page.getByText('Đã lưu tin tìm.')).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
});

test('shows match notifications, marks read and stops tracking', async ({ page }) => {
  await setupDefaultApiMocks(page);
  const saved = structuredClone(savedSearch);
  let stopped = false;
  await page.route('**/api/saved-searches', route => route.fulfill({ json: stopped ? [] : [saved] }));
  await page.route('**/api/saved-searches/saved-1/matches/*/read', async route => {
    expect(route.request().method()).toBe('PUT');
    saved.matches[0].readAt = '2026-11-03T00:00:00Z';
    await route.fulfill({ status: 204 });
  });
  await page.route('**/api/saved-searches/saved-1', async route => {
    expect(route.request().method()).toBe('DELETE');
    stopped = true;
    await route.fulfill({ status: 204 });
  });
  await page.goto('/saved-searches');
  await expect(page.getByRole('heading', { name: 'Tin tìm đang theo dõi' })).toBeVisible();
  await expect(page.getByText('Thông báo mới')).toBeVisible();
  await expect(page.locator('.account-menu a[href="/saved-searches"]')).toHaveText('Tin tìm đang theo dõi (1 mới)');
  await expect(page.getByRole('link', { name: 'Xem món đồ' })).toHaveAttribute('href', `/items/${saved.matches[0].itemId}`);
  await page.getByRole('button', { name: 'Đánh dấu đã đọc' }).click();
  await expect(page.getByText('Đã đọc')).toBeVisible();
  await expect(page.locator('.account-menu a[href="/saved-searches"]')).toHaveText('Tin tìm đang theo dõi');
  await expect(page.getByRole('button', { name: 'Đánh dấu đã đọc' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Dừng theo dõi' }).click();
  await expect(page.getByRole('heading', { name: 'Bạn chưa theo dõi tin tìm nào' })).toBeVisible();
});

test('explains when stored search needs refreshing and does not expose original images', async ({ page }) => {
  await setupDefaultApiMocks(page);
  await page.route('**/api/saved-searches', route => route.fulfill({ json: [{ ...savedSearch, text: null, needsRefresh: true, matches: [] }] }));
  await page.goto('/saved-searches');
  await expect(page.getByRole('heading', { name: 'Tìm theo 1 ảnh món đồ' })).toBeVisible();
  await expect(page.getByText('Cần cập nhật tin tìm để tiếp tục đối chiếu.')).toBeVisible();
  await expect(page.locator('main img')).toHaveCount(0);
});

test('refreshes notification counts and page every minute only while visible', async ({ page }) => {
  await page.clock.install();
  await setupDefaultApiMocks(page);
  const saved = structuredClone(savedSearch);
  saved.matches = [];
  let requests = 0;
  await page.route('**/api/saved-searches', route => {
    requests++;
    return route.fulfill({ json: [saved] });
  });
  await page.goto('/saved-searches');
  await expect(page.getByText('Chưa có thông báo phù hợp.')).toBeVisible();
  saved.matches = structuredClone(savedSearch.matches);
  await page.clock.fastForward(60000);
  await expect(page.getByText('Thông báo mới')).toBeVisible();
  await expect(page.locator('.account-menu a[href="/saved-searches"]')).toHaveText('Tin tìm đang theo dõi (1 mới)');
  const beforeHidden = requests;
  await page.evaluate(() => Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }));
  await page.clock.fastForward(120000);
  expect(requests).toBe(beforeHidden);
  saved.matches[0].readAt = '2026-11-03T00:00:00Z';
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.getByText('Đã đọc')).toBeVisible();
  await expect(page.locator('.account-menu a[href="/saved-searches"]')).toHaveText('Tin tìm đang theo dõi');
});

test('does not fetch notification data for signed-out users', async ({ page }) => {
  await page.clock.install();
  await setupDefaultApiMocks(page, { user: null });
  let requests = 0;
  await page.route('**/api/saved-searches', route => {
    requests++;
    return route.fulfill({ json: [] });
  });
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'Đăng nhập', exact: true })).toBeVisible();
  await page.clock.fastForward(120000);
  expect(requests).toBe(0);
});
