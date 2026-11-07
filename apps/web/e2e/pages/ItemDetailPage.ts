import { type Page, type Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class ItemDetailPage extends BasePage {
  readonly titleHeading: Locator;
  readonly locationFact: Locator;
  readonly descriptionParagraph: Locator;
  readonly claimButton: Locator;
  readonly backToSearchLink: Locator;

  // Claim Form elements (on /items/:id/claim)
  readonly claimFormHeading: Locator;
  readonly answerInputs: Locator;
  readonly submitClaimButton: Locator;

  // Claim Status / Detail elements (on /claims/:id)
  readonly claimDetailHeading: Locator;
  readonly claimStatusBadge: Locator;

  constructor(page: Page) {
    super(page);
    this.titleHeading = page.locator('.item-description h1');
    this.locationFact = page.locator('.item-facts');
    this.descriptionParagraph = page.locator('.item-description p.preserve-lines');
    this.claimButton = page.getByRole('link', { name: /Gửi yêu cầu nhận đồ/i });
    this.backToSearchLink = page.getByRole('link', { name: /Quay lại tìm kiếm/i });

    this.claimFormHeading = page.getByRole('heading', { name: /Đây có phải món đồ của bạn/i });
    this.answerInputs = page.locator('.answer-field textarea');
    this.submitClaimButton = page.getByRole('button', { name: /Gửi yêu cầu nhận đồ/i });

    this.claimDetailHeading = page.locator('.claim-form h2');
    this.claimStatusBadge = page.locator('.claim-form .badge');
  }

  async expectItemDetails(title: string, area?: string) {
    await expect(this.titleHeading).toHaveText(title);
    if (area) {
      await expect(this.locationFact).toContainText(area);
    }
  }

  async clickClaim() {
    await expect(this.claimButton).toBeVisible();
    await this.claimButton.click();
  }

  async answerAndSubmitClaim(answers: string[]) {
    await expect(this.claimFormHeading).toBeVisible();
    const count = await this.answerInputs.count();
    for (let i = 0; i < count && i < answers.length; i++) {
      await this.answerInputs.nth(i).fill(answers[i]);
    }
    await this.submitClaimButton.click();
  }

  async expectClaimSubmitted() {
    await expect(this.claimStatusBadge).toBeVisible();
    await expect(this.page).toHaveURL(/\/claims\/[\da-f-]+/i);
  }
}
