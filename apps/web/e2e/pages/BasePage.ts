import { type Page, type Locator, expect } from '@playwright/test';

export class BasePage {
  readonly page: Page;
  readonly brandLink: Locator;
  readonly navSearchLink: Locator;
  readonly navPostButton: Locator;
  readonly navHubsLink: Locator;
  readonly accountMenu: Locator;
  readonly signinLink: Locator;

  constructor(page: Page) {
    this.page = page;
    this.brandLink = page.getByRole('link', { name: /Findie — Trang chủ/i });
    this.navSearchLink = page.getByRole('link', { name: 'Tìm đồ', exact: true });
    this.navPostButton = page.getByRole('link', { name: 'Đăng tin', exact: true });
    this.navHubsLink = page.getByRole('link', { name: 'Findie Hub', exact: true });
    this.accountMenu = page.locator('details.account-menu');
    this.signinLink = page.locator('a.signin-link');
  }

  async goto(path = '/') {
    await this.page.goto(path);
  }

  async expectPageTitle(titleMatch: RegExp | string) {
    await expect(this.page).toHaveTitle(titleMatch);
  }

  async expectUserSignedIn(displayName: string) {
    await expect(this.accountMenu).toBeVisible();
    await expect(this.accountMenu).toContainText(displayName.charAt(0).toUpperCase());
  }
}
