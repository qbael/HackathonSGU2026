import { type Page, type Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class SearchPage extends BasePage {
  readonly queryInput: Locator;
  readonly areaInput: Locator;
  readonly modeSelect: Locator;
  readonly searchButton: Locator;
  readonly resultsHeading: Locator;
  readonly itemCards: Locator;

  // Image search elements
  readonly fileInput: Locator;
  readonly uploadZone: Locator;
  readonly imagePreviews: Locator;
  readonly previewItems: Locator;
  readonly removeImageButtons: Locator;

  // Alerts & Empty state
  readonly noticeWarning: Locator;
  readonly emptyState: Locator;
  readonly fallbackButton: Locator;
  readonly searchImagesError: Locator;

  constructor(page: Page) {
    super(page);
    this.queryInput = page.locator('aside.filter-panel input[name="q"]');
    this.areaInput = page.locator('aside.filter-panel input[name="area"]');
    this.modeSelect = page.locator('aside.filter-panel select[name="mode"]');
    this.searchButton = page.locator('aside.filter-panel button[type="submit"]');
    this.resultsHeading = page.locator('.results-heading');
    this.itemCards = page.locator('.item-card');

    // Image search
    this.fileInput = page.locator('.search-images input[type="file"]');
    this.uploadZone = page.locator('.search-images .upload-zone');
    this.imagePreviews = page.locator('.image-previews');
    this.previewItems = page.locator('.image-previews li');
    this.removeImageButtons = page.locator('.image-previews button');

    // Error & Notice
    this.noticeWarning = page.locator('.notice-warning');
    this.emptyState = page.locator('.empty-state');
    this.fallbackButton = page.locator('a.text-button:has-text("Dùng bộ lọc cơ bản")');
    this.searchImagesError = page.locator('.search-images .notice-error, .search-images [role="alert"]');
  }

  async filter(keyword: string, area?: string) {
    await this.queryInput.fill(keyword);
    if (area) {
      await this.areaInput.fill(area);
    }
    await this.searchButton.click();
  }

  async uploadSearchImage(filePath: string | string[]) {
    await this.fileInput.setInputFiles(filePath);
  }

  async expectImagePreviewsCount(count: number) {
    await expect(this.previewItems).toHaveCount(count);
  }

  async removeImagePreview(index = 0) {
    await this.removeImageButtons.nth(index).click();
  }

  async clickItemByTitle(title: string) {
    const card = this.itemCards.filter({ hasText: title }).first();
    await expect(card).toBeVisible();
    await card.click();
  }

  async clickFirstItem() {
    await expect(this.itemCards.first()).toBeVisible();
    await this.itemCards.first().click();
  }

  async expectAiServiceUnavailableBanner() {
    await expect(this.noticeWarning).toBeVisible();
    await expect(this.noticeWarning).toContainText(/tạm thời chưa sẵn sàng|gián đoạn/i);
  }

  async expectEmptyState() {
    await expect(this.emptyState).toBeVisible();
    await expect(this.emptyState).toContainText(/Chưa thấy món đồ phù hợp|không tìm thấy/i);
  }
}
