import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { setupDefaultApiMocks } from '../utils/mockApi';

const item = JSON.parse(readFileSync(new URL('../fixtures/mock-items.json', import.meta.url), 'utf8'))[0];
const imageId = '11111111-1111-4111-8111-111111111111';
const imagePath = `/api/items/${item.id}/images/${imageId}/content`;

test.describe('Duyệt ảnh và công khai tin', () => {
  test.beforeEach(async ({ page }) => {
    await setupDefaultApiMocks(page);
    let approved = false;
    const image = () => ({ id: imageId, itemId: item.id, position: 1, contentVersion: 1,
      processingState: approved ? 'ready' : 'needs_review', reviewState: approved ? 'approved' : 'pending',
      failureCode: null, previewUrl: imagePath });
    await page.route(`**/api/items/${item.id}`, (route) => route.fulfill({ json: {
      ...item, publicationState: 'draft', images: approved ? [{ id: imageId, position: 1, contentVersion: 1, url: imagePath }] : [],
    } }));
    await page.route(`**/api/items/${item.id}/images`, (route) => route.fulfill({ json: [image()] }));
    await page.route(`**${imagePath}`, (route) => route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64') }));
    await page.route(`**/api/items/${item.id}/images/${imageId}/review`, (route) => {
      approved = route.request().postDataJSON().decision === 'approved';
      return route.fulfill({ json: image() });
    });
    await page.route(`**/api/items/${item.id}/publication`, (route) => route.fulfill({ json: { ...item, publicationState: 'published' } }));
  });

  test('Chỉ cho công khai sau khi kiểm tra đủ ba mục và duyệt ảnh', async ({ page }) => {
    await page.goto(`/items/${item.id}/review`);
    await expect(page.locator('.stepper li')).toHaveCount(4);
    await expect(page.locator('.stepper [aria-current="step"]')).toContainText('Duyệt ảnh & công khai');
    const approve = page.getByRole('button', { name: 'Duyệt ảnh công khai', exact: true });
    const publish = page.getByRole('button', { name: 'Công khai tin', exact: true });
    await expect(approve).toBeDisabled();
    await expect(publish).toBeDisabled();
    const checks = page.locator('.safety-check input');
    await expect(checks.first()).toBeEnabled();
    await checks.nth(0).check();
    await checks.nth(1).check();
    await expect(approve).toBeDisabled();
    await checks.nth(2).check();
    await expect(page.locator('.review-check-progress')).toContainText('3/3');
    await approve.click();
    await expect(page.getByText('Ảnh này đã được duyệt.', { exact: true })).toBeVisible();
    await expect(publish).toBeEnabled();
    await publish.click();
    await expect(page).toHaveURL(/\/posts$/);
  });

  test('Ảnh không tải được vẫn khóa kiểm tra, duyệt và công khai', async ({ page }) => {
    await page.route(`**${imagePath}`, (route) => route.abort());
    await page.goto(`/items/${item.id}/review`);
    await expect(page.getByRole('alert')).toContainText('Chưa tải được bản ảnh đã xử lý');
    await expect(page.locator('.safety-check input').first()).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Duyệt ảnh công khai', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Công khai tin', exact: true })).toBeDisabled();
  });

  test('Trang duyệt ảnh trên điện thoại không tràn ngang', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/items/${item.id}/review`);
    await expect(page.getByRole('button', { name: 'Xem ảnh 1' })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.safety-check input').first()).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });

  test('Bốn bước luôn nằm cùng một hàng trên trang đăng tin và duyệt ảnh', async ({ page }) => {
    for (const path of ['/post', `/items/${item.id}/review`]) {
      await page.goto(path);
      const steps = page.locator('.stepper > li');
      await expect(steps).toHaveCount(4);
      for (const width of [1440, 1024, 768, 390, 320]) {
        await page.setViewportSize({ width, height: 900 });
        const boxes = await steps.evaluateAll((elements) => elements.map((element) => {
          const { top, left, right, width } = element.getBoundingClientRect();
          return { top, left, right, width };
        }));
        expect(boxes.every((box) => Math.abs(box.top - boxes[0].top) < 1), `${path} at ${width}px`).toBe(true);
        expect(boxes.every((box, index) => box.width > 0 && (index === 0 || box.left >= boxes[index - 1].right))).toBe(true);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
    }
  });
});
