import { test, expect } from '@playwright/test';
import { HubPage } from '../pages/HubPage';
import {
  setupDefaultApiMocks,
  defaultMockUser,
  defaultMockStaffUser,
} from '../utils/mockApi';

test.describe('CUJ-07: Không gian làm việc Findie Hub (Hub Workspace)', () => {
  test('Kịch bản 7.1 (Role Guard): Chặn người dùng không có quyền nhân viên Hub', async ({ page }) => {
    // 1. Đăng nhập với tài khoản người dùng bình thường (isStaff = false, isAdmin = false)
    await setupDefaultApiMocks(page, { user: defaultMockUser });

    const hubPage = new HubPage(page);
    await hubPage.gotoHub();

    // 2. Xác nhận hiển thị màn hình EmptyState "Không có quyền truy cập"
    await hubPage.expectAccessDenied();
    await expect(page.getByText('Bạn cần tài khoản Nhân viên Findie Hub được phân công trực trạm để truy cập khu vực này.')).toBeVisible();

    // 3. Xác nhận Sidebar Hub Portal không bị render
    await expect(page.locator('.hub-sidebar')).toHaveCount(0);
  });

  test('Kịch bản 7.2 (Hub Workspace & Station Badge): Hiển thị không gian làm việc và tên trạm trực', async ({ page }) => {
    // 1. Đăng nhập với tài khoản nhân viên Hub
    await setupDefaultApiMocks(page, { user: defaultMockStaffUser });

    const hubPage = new HubPage(page);
    await hubPage.gotoHub();

    // 2. Xác nhận hiển thị Sidebar và đúng tên trạm trực được phân công
    await expect(hubPage.stationName).toBeVisible();
    await expect(hubPage.stationName).toHaveText('Trạm Tiếp Nhận - ĐH Sài Gòn');

    // 3. Xác nhận hiển thị Bàn tiếp nhận vật phẩm và danh sách đề nghị
    await expect(page.locator('h1')).toHaveText('Bàn tiếp nhận vật phẩm');
    await expect(page.getByText('MÃ: #intake-r', { exact: false })).toBeVisible();
  });

  test('Kịch bản 7.3 (Intake Process): Tiếp nhận hiện vật vào kho của trạm', async ({ page }) => {
    await setupDefaultApiMocks(page, { user: defaultMockStaffUser });

    const hubPage = new HubPage(page);
    await hubPage.gotoHub('intakes');

    // 1. Mở modal Tiếp nhận
    await hubPage.openReceiveModal();
    await expect(hubPage.receiveModal).toBeVisible();
    await expect(hubPage.receiveModal.getByText('Xác nhận tiếp nhận hiện vật vào kho')).toBeVisible();

    // 2. Xác nhận nút submit bị vô hiệu hóa khi chưa tích checkbox kiểm tra thực tế
    await expect(hubPage.submitReceiveBtn).toBeDisabled();

    // 3. Nhập ghi chú lưu trữ, tích checkbox và gửi xác nhận
    await hubPage.confirmReceive('Tủ B - Ngăn 3');

    // 4. Modal đóng lại sau khi hoàn tất
    await expect(hubPage.receiveModal).toBeHidden();
  });

  test('Kịch bản 7.4 (Navigation & Views): Điều hướng qua Kho đồ lưu giữ và Nhật ký lưu chuyển', async ({ page }) => {
    await setupDefaultApiMocks(page, { user: defaultMockStaffUser });

    const hubPage = new HubPage(page);
    await hubPage.gotoHub();

    // 1. Chuyển sang tab Kho đồ lưu giữ
    await hubPage.navInventory.click();
    await expect(page).toHaveURL(/\/hub\/inventory/);
    await expect(page.locator('h1')).toHaveText('Kho đồ lưu giữ tại trạm');
    await expect(page.getByText('Chìa khóa Honda')).toBeVisible();

    // 2. Chuyển sang tab Nhật ký lưu chuyển
    await hubPage.navHistory.click();
    await expect(page).toHaveURL(/\/hub\/history/);
    await expect(page.locator('h1')).toHaveText('Nhật ký lưu chuyển & Trao trả tại trạm');
  });
});
