import { type Page, type Locator, expect } from '@playwright/test';
import { BasePage } from './BasePage';

export class HubPage extends BasePage {
  readonly stationName: Locator;
  readonly navIntakes: Locator;
  readonly navInventory: Locator;
  readonly navHistory: Locator;
  readonly receiveModal: Locator;
  readonly confirmCheckbox: Locator;
  readonly submitReceiveBtn: Locator;
  readonly decisionNoteInput: Locator;

  constructor(page: Page) {
    super(page);
    this.stationName = page.locator('.hub-selector-name');
    this.navIntakes = page.getByRole('button', { name: 'Đề nghị tiếp nhận' });
    this.navInventory = page.getByRole('button', { name: 'Kho đồ tại trạm' });
    this.navHistory = page.getByRole('button', { name: 'Lịch sử bàn giao' });
    this.receiveModal = page.locator('.hub-modal-card');
    this.confirmCheckbox = page.locator('input[type="checkbox"]');
    this.submitReceiveBtn = page.getByRole('button', { name: 'Xác nhận vào kho' });
    this.decisionNoteInput = page.locator('input[placeholder*="Ví dụ: Tủ A"]');
  }

  async gotoHub(tab = '') {
    const url = tab ? `/hub/${tab}` : '/hub';
    await this.page.goto(url);
  }

  async expectAccessDenied() {
    await expect(this.page.getByText('Không có quyền truy cập')).toBeVisible();
    await expect(this.page.getByRole('link', { name: 'Về trang chủ' })).toBeVisible();
  }

  async openReceiveModal() {
    const receiveBtn = this.page.getByRole('button', { name: 'Tiếp nhận', exact: true }).first();
    await receiveBtn.click();
    await expect(this.receiveModal).toBeVisible();
  }

  async confirmReceive(note = 'Tủ A - Ngăn 1') {
    await this.decisionNoteInput.fill(note);
    await this.confirmCheckbox.check();
    await this.submitReceiveBtn.click();
    await expect(this.receiveModal).toBeHidden();
  }
}
