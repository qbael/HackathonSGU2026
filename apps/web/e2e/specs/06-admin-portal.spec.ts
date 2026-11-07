import { test, expect } from '@playwright/test';
import { AdminPage } from '../pages/AdminPage';
import {
  setupDefaultApiMocks,
  defaultMockUser,
  defaultMockAdminUser,
} from '../utils/mockApi';

test.describe('CUJ-06: Phân hệ Quản trị Hệ thống (Admin Portal)', () => {
  test('Kịch bản 6.1 (Role Guard): Chặn người dùng thông thường truy cập khu vực Admin', async ({ page }) => {
    // 1. Đăng nhập với tài khoản người dùng bình thường (isAdmin = false)
    await setupDefaultApiMocks(page, { user: defaultMockUser });

    const adminPage = new AdminPage(page);
    await adminPage.gotoAdmin();

    // 2. Xác nhận hiển thị màn hình EmptyState "Không có quyền truy cập"
    await adminPage.expectAccessDenied();
    await expect(page.getByText('Bạn cần tài khoản Quản trị viên (Super Admin) để truy cập khu vực này.')).toBeVisible();

    // 3. Xác nhận Sidebar quản trị không bị render
    await expect(page.locator('.admin-sidebar')).toHaveCount(0);
  });

  test('Kịch bản 6.2 (Dashboard): Super Admin xem các chỉ số vận hành tổng quan', async ({ page }) => {
    // 1. Đăng nhập với tài khoản Super Admin
    await setupDefaultApiMocks(page, { user: defaultMockAdminUser });

    const adminPage = new AdminPage(page);
    await adminPage.gotoAdmin();

    // 2. Xác nhận truy cập thành công và hiển thị Bảng điều khiển
    await adminPage.expectDashboardMetrics();
    await expect(page.getByText('Giám sát tình trạng hệ thống Findie')).toBeVisible();

    // 3. Xác nhận hiển thị các thẻ số liệu
    await expect(page.getByText('TIN ĐĂNG TÌM ĐỒ', { exact: true })).toBeVisible();
    await expect(page.getByText('NGƯỜI DÙNG', { exact: true })).toBeVisible();
    await expect(page.getByText('MẠNG LƯỚI FINDIE HUB', { exact: true })).toBeVisible();
    await expect(page.getByText('TRAO TRẢ THÀNH CÔNG', { exact: true })).toBeVisible();
  });

  test('Kịch bản 6.3 (User Moderation): Quản trị viên tra cứu và khóa tài khoản người dùng', async ({ page }) => {
    await setupDefaultApiMocks(page, { user: defaultMockAdminUser });

    const adminPage = new AdminPage(page);
    await adminPage.gotoAdmin('users');

    // 1. Xác nhận đang ở trang Quản lý Người dùng
    await expect(adminPage.pageHeading).toHaveText('Quản lý Người dùng');
    await expect(adminPage.userRows).toHaveCount(2);

    // 2. Tìm kiếm người dùng khả nghi
    await adminPage.searchUser('Khả Nghi');
    await expect(adminPage.userRows.filter({ hasText: 'Người Dùng Khả Nghi' })).toBeVisible();

    // 3. Thực hiện khóa tài khoản (bấm nút và chấp nhận dialog confirm)
    await adminPage.toggleUserLock('Người Dùng Khả Nghi');

    // 4. Xác nhận trạng thái chuyển thành "Đã bị khóa" và nút đổi thành "Mở khóa"
    const targetRow = adminPage.userRows.filter({ hasText: 'Người Dùng Khả Nghi' });
    await expect(targetRow.getByText('Đã bị khóa')).toBeVisible();
    await expect(targetRow.getByRole('button', { name: 'Mở khóa' })).toBeVisible();
  });

  test('Kịch bản 6.4 (Item Moderation): Quản trị viên kiểm duyệt và tạm ẩn bài đăng', async ({ page }) => {
    await setupDefaultApiMocks(page, { user: defaultMockAdminUser });

    const adminPage = new AdminPage(page);
    await adminPage.gotoAdmin('items');

    // 1. Xác nhận đang ở trang Kiểm duyệt Tin đăng & Hình ảnh
    await expect(adminPage.pageHeading).toHaveText('Kiểm duyệt Tin đăng & Hình ảnh');
    await expect(adminPage.itemRows).toHaveCount(1);

    const itemRow = adminPage.itemRows.filter({ hasText: 'Ví da cá sấu màu nâu' });
    await expect(itemRow).toBeVisible();
    await expect(itemRow.getByText('Đang công khai')).toBeVisible();

    // 2. Bấm "Tạm ẩn" và chấp nhận confirm dialog
    await adminPage.toggleItemPublication('Ví da cá sấu màu nâu');

    // 3. Xác nhận trạng thái tin đăng chuyển sang "Đã ẩn" và nút đổi thành "Hiện lại"
    await expect(itemRow.getByText('Đã ẩn')).toBeVisible();
    await expect(itemRow.getByRole('button', { name: 'Hiện lại' })).toBeVisible();
  });
});
