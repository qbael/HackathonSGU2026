import { test, expect } from '@playwright/test';
import { ItemDetailPage } from '../pages/ItemDetailPage';
import { setupDefaultApiMocks } from '../utils/mockApi';

test.describe('CUJ-03: Xác minh nhận lại đồ (Claim & Verification Flow)', () => {
  test.beforeEach(async ({ page }) => {
    await setupDefaultApiMocks(page);
  });

  test('Người mất đồ gửi yêu cầu nhận lại đồ và trả lời câu hỏi xác minh', async ({ page }) => {
    const itemDetailPage = new ItemDetailPage(page);
    const itemId = 'e4b2d380-6bc7-4d98-b80c-e2f4a56c0001';

    // 1. Mở trang chi tiết món đồ
    await itemDetailPage.goto(`/items/${itemId}`);
    await itemDetailPage.expectItemDetails('Chìa khóa Honda');

    // 2. Nhấn nút Gửi yêu cầu nhận đồ
    await itemDetailPage.clickClaim();
    await expect(page).toHaveURL(`/items/${itemId}/claim`);

    // 3. Form câu hỏi xác minh hiển thị, nhập câu trả lời
    await itemDetailPage.answerAndSubmitClaim(['Doraemon đeo chuông vàng']);

    // 4. Kiểm tra yêu cầu đã được gửi thành công và chuyển đến trang chi tiết Claim
    await itemDetailPage.expectClaimSubmitted();
    await expect(itemDetailPage.claimDetailHeading).toContainText(/Thông tin bạn đã gửi|Câu trả lời/i);
  });
});
