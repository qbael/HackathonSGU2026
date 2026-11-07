import { type Page, type Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class PostItemPage extends BasePage {
  readonly pageHeading: Locator;

  // Step 1: Info & Photo
  readonly titleInput: Locator;
  readonly fileInput: Locator;
  readonly imagePreviews: Locator;
  readonly previewItems: Locator;
  readonly removeImageButtons: Locator;
  readonly descriptionInput: Locator;
  readonly areaInput: Locator;
  readonly nextButton: Locator;

  // Error & notices
  readonly errorNotice: Locator;

  // Step 2: Custody
  readonly personRadio: Locator;

  // Step 3: Verification & Confirm
  readonly confirmCheckbox: Locator;
  readonly submitFinalButton: Locator;

  // Success panel / redirect
  readonly savedPanel: Locator;

  constructor(page: Page) {
    super(page);
    this.pageHeading = page.locator('#post-heading');

    // Step 1
    this.titleInput = page.locator('label:has-text("Tên món đồ") input');
    this.fileInput = page.locator('input[type="file"]');
    this.imagePreviews = page.locator('.image-previews');
    this.previewItems = page.locator('.image-previews li');
    this.removeImageButtons = page.locator('.image-previews button');
    this.descriptionInput = page.locator('label:has-text("Mô tả công khai") textarea');
    this.areaInput = page.locator('label:has-text("Khu vực nhặt được") input');
    this.nextButton = page.locator('.form-actions button[type="submit"]');

    // Error & alerts
    this.errorNotice = page.locator('.notice-error, [role="alert"]');

    // Step 2
    this.personRadio = page.locator('input[name="custody"][value="person"], label:has-text("Tôi đang tự giữ") input');

    // Step 3
    this.confirmCheckbox = page.locator('input[type="checkbox"]');
    this.submitFinalButton = page.locator('.form-actions button[type="submit"]');

    // Result
    this.savedPanel = page.locator('.saved-panel');
  }

  async uploadFile(filePath: string | string[]) {
    await this.fileInput.setInputFiles(filePath);
  }

  async expectImagePreviewsCount(count: number) {
    await expect(this.previewItems).toHaveCount(count);
  }

  async removeImagePreview(index = 0) {
    await this.removeImageButtons.nth(index).click();
  }

  async clickNext() {
    await this.nextButton.click();
  }

  async fillStep1(data: {
    title: string;
    description: string;
    area: string;
    filePath?: string;
  }) {
    await this.titleInput.fill(data.title);
    if (data.filePath) {
      await this.fileInput.setInputFiles(data.filePath);
    }
    await this.descriptionInput.fill(data.description);
    await this.areaInput.fill(data.area);
    await this.clickNext();
  }

  async passStep2() {
    // Step 2 defaults to "Tôi đang tự giữ", click Tiếp tục
    await expect(this.pageHeading).toContainText(/Bạn đang giữ món đồ ở đâu/i);
    await this.clickNext();
  }

  async finishStep3() {
    await expect(this.pageHeading).toContainText(/Thiết lập câu hỏi xác minh/i);
    await this.confirmCheckbox.check();
    await this.submitFinalButton.click();
  }

  async expectSavedSuccessfully() {
    // Either on review page or saved panel visible
    await expect(
      this.page.locator('.saved-panel, .review-panel, h1:has-text("Kiểm tra ảnh trước khi công khai")').first()
    ).toBeVisible({ timeout: 10000 });
  }

  async expectValidationError(message?: RegExp | string) {
    await expect(this.errorNotice).toBeVisible();
    if (message) {
      await expect(this.errorNotice).toContainText(message);
    }
  }

  async expectStayOnStep1() {
    await expect(this.pageHeading).toContainText(/Kể một chút về món đồ/i);
  }
}
