import { type Page, type Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class HomePage extends BasePage {
  readonly heroTitle: Locator;
  readonly queryInput: Locator;
  readonly areaInput: Locator;
  readonly fromDateInput: Locator;
  readonly untilDateInput: Locator;
  readonly submitButton: Locator;

  constructor(page: Page) {
    super(page);
    this.heroTitle = page.locator('#home-title');
    this.queryInput = page.locator('#home-query');
    this.areaInput = page.locator('input[name="area"]');
    this.fromDateInput = page.locator('input[name="from"]');
    this.untilDateInput = page.locator('input[name="until"]');
    this.submitButton = page.getByRole('button', { name: /Tìm kiếm món đồ/i });
  }

  async searchFromHome(keyword: string, area?: string) {
    await this.queryInput.fill(keyword);
    if (area) {
      await this.areaInput.fill(area);
    }
    await this.submitButton.click();
  }
}
