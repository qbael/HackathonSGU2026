import { type Page, type Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class AdminPage extends BasePage {
  readonly pageHeading: Locator;
  readonly navDashboard: Locator;
  readonly navUsers: Locator;
  readonly navItems: Locator;
  readonly navHubs: Locator;
  readonly metricCards: Locator;
  readonly userRows: Locator;
  readonly itemRows: Locator;

  constructor(page: Page) {
    super(page);
    this.pageHeading = page.locator('h1');
    this.navDashboard = page.getByRole('button', { name: 'Tổng quan' });
    this.navUsers = page.getByRole('button', { name: 'Quản lý Người dùng' });
    this.navItems = page.getByRole('button', { name: 'Kiểm duyệt Tin & Ảnh' });
    this.navHubs = page.getByRole('button', { name: 'Mạng lưới Findie Hub' });
    this.metricCards = page.locator('.metric-card');
    this.userRows = page.locator('table tbody tr');
    this.itemRows = page.locator('table tbody tr');
  }

  async gotoAdmin(tab = '') {
    const url = tab ? `/admin/${tab}` : '/admin';
    await this.page.goto(url);
  }

  async expectAccessDenied() {
    await expect(this.page.getByText('Không có quyền truy cập')).toBeVisible();
    await expect(this.page.getByRole('link', { name: 'Về trang chủ' })).toBeVisible();
  }

  async expectDashboardMetrics() {
    await expect(this.metricCards).toHaveCount(7);
    await expect(this.page.getByText('Bảng điều khiển Quản trị viên')).toBeVisible();
  }

  async searchUser(term: string) {
    const searchInput = this.page.locator('.admin-search-box input');
    await searchInput.fill(term);
    await searchInput.press('Enter');
  }

  async toggleUserLock(userName: string) {
    const row = this.userRows.filter({ hasText: userName });
    await expect(row).toBeVisible();
    this.page.once('dialog', async (dialog) => {
      await dialog.accept();
    });
    const actionBtn = row.locator('button.btn-sm');
    await actionBtn.click();
  }

  async toggleItemPublication(itemTitle: string) {
    const row = this.itemRows.filter({ hasText: itemTitle });
    await expect(row).toBeVisible();
    this.page.once('dialog', async (dialog) => {
      await dialog.accept();
    });
    const toggleBtn = row.locator('button.btn-warning, button.btn-success');
    await toggleBtn.click();
  }
}
