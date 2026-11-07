import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { type Page } from '@playwright/test';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const mockItemsData = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, '../fixtures/mock-items.json'), 'utf-8')
);

export type MockUser = {
  id: string;
  email: string | null;
  displayName: string;
  createdAt: string;
  isAdmin?: boolean;
  isStaff?: boolean;
  managedPoints?: Array<{ id: string; name: string }>;
};

export const defaultMockUser: MockUser = {
  id: 'u-finder-test-01',
  email: 'tester@findie.vn',
  displayName: 'Nguyễn Văn Test',
  createdAt: '2026-11-01T00:00:00Z',
  isAdmin: false,
  isStaff: false,
  managedPoints: [],
};

export const defaultMockAdminUser: MockUser = {
  id: 'u-admin-test-01',
  email: 'admin@findie.vn',
  displayName: 'Super Admin',
  createdAt: '2026-11-01T00:00:00Z',
  isAdmin: true,
  isStaff: false,
  managedPoints: [],
};

export const defaultMockStaffUser: MockUser = {
  id: 'u-staff-test-01',
  email: 'staff@findie.vn',
  displayName: 'Nguyễn Văn Trực Trạm',
  createdAt: '2026-11-01T00:00:00Z',
  isAdmin: false,
  isStaff: true,
  managedPoints: [
    { id: 'point-dh-sgu-01', name: 'Trạm Tiếp Nhận - ĐH Sài Gòn' },
  ],
};

export type MockScenarioOptions = {
  user?: MockUser | null;
  items?: any[];
  aiServiceAvailable?: boolean;       // false: Giả lập AI Service 503 Service Unavailable
  authStatus?: 'authenticated' | 'unauthorized' | 'token-expired';
  searchDelayMs?: number;            // Giả lập độ trễ mạng để test loading spinner
};

export async function setupDefaultApiMocks(
  page: Page,
  options?: MockScenarioOptions
) {
  const authStatus = options?.authStatus ?? (options?.user === null ? 'unauthorized' : 'authenticated');
  const user = authStatus === 'authenticated'
    ? (options?.user !== undefined ? options.user : defaultMockUser)
    : null;
  const items = options?.items ?? mockItemsData;
  const aiServiceAvailable = options?.aiServiceAvailable !== false;
  const searchDelayMs = options?.searchDelayMs ?? 0;

  // 1. Auth & Session
  await page.route('**/api/users/me', async (route) => {
    if (authStatus === 'unauthorized' || user === null) {
      await route.fulfill({ status: 401, json: { message: 'Unauthorized' } });
    } else {
      await route.fulfill({ status: 200, json: user });
    }
  });

  await page.route('**/api/auth/csrf', async (route) => {
    if (authStatus === 'token-expired') {
      await route.fulfill({ status: 401, json: { message: 'Token expired' } });
    } else {
      await route.fulfill({
        status: 200,
        json: { token: 'mock-csrf-token-xyz-123' },
      });
    }
  });

  // 2. Search & Items List (Basic Search GET)
  await page.route('**/api/items?*', async (route) => {
    const url = new URL(route.request().url());
    const q = url.searchParams.get('q')?.toLowerCase() ?? '';
    const area = url.searchParams.get('area')?.toLowerCase() ?? '';
    const scope = url.searchParams.get('scope');

    let filtered = items;
    if (scope === 'managed') {
      await route.fulfill({
        status: 200,
        json: {
          items: filtered,
          page: 1,
          pageSize: 12,
          hasMore: false,
        },
      });
      return;
    }

    if (q) {
      filtered = filtered.filter(
        (it: any) =>
          it.title.toLowerCase().includes(q) ||
          it.publicDescription.toLowerCase().includes(q)
      );
    }
    if (area) {
      filtered = filtered.filter((it: any) =>
        it.foundArea.toLowerCase().includes(area)
      );
    }

    await route.fulfill({
      status: 200,
      json: {
        items: filtered,
        page: 1,
        pageSize: 12,
        hasMore: false,
      },
    });
  });

  // 3. Smart Search (POST /api/search)
  await page.route('**/api/search', async (route) => {
    if (route.request().method() !== 'POST') {
      return route.continue();
    }
    if (!aiServiceAvailable) {
      await route.fulfill({
        status: 503,
        json: { message: 'Dịch vụ tìm kiếm AI tạm thời chưa sẵn sàng.' },
      });
      return;
    }
    if (searchDelayMs > 0) {
      await new Promise((res) => setTimeout(res, searchDelayMs));
    }

    const postData = route.request().postDataJSON();
    const text = (postData?.text ?? '').toLowerCase();
    const area = (postData?.area ?? '').toLowerCase();

    let matched = items;
    if (text) {
      matched = matched.filter(
        (it: any) =>
          it.title.toLowerCase().includes(text) ||
          it.publicDescription.toLowerCase().includes(text)
      );
    }

    await route.fulfill({
      status: 200,
      json: {
        items: matched.map((item: any, idx: number) => ({ rank: idx + 1, item })),
        mode: 'text',
        searchProfileId: 'mock-prof-1',
        searchProfileVersion: 1,
        partial: false,
        filtersRelaxed: Boolean(area && matched.some((item: any) => !item.foundArea.toLowerCase().includes(area))),
        fallbackUrl: `/search?mode=basic&q=${encodeURIComponent(postData?.text ?? '')}`,
      },
    });
  });

  // 3b. Multimodal Image Search (POST /api/search/images* and /api/search/image*)
  await page.route(/.*\/api\/search\/images?(\?.*)?$/i, async (route) => {
    if (route.request().method() !== 'POST') {
      return route.continue();
    }
    if (!aiServiceAvailable) {
      await route.fulfill({
        status: 503,
        json: { message: 'Dịch vụ phân tích ảnh AI tạm thời chưa sẵn sàng.' },
      });
      return;
    }
    if (searchDelayMs > 0) {
      await new Promise((res) => setTimeout(res, searchDelayMs));
    }

    const area = new URL(route.request().url()).searchParams.get('area')?.toLowerCase() ?? '';
    await route.fulfill({
      status: 200,
      json: {
        items: items.map((item: any, idx: number) => ({ rank: idx + 1, item })),
        mode: 'image',
        searchProfileId: 'mock-prof-img',
        searchProfileVersion: 1,
        partial: false,
        filtersRelaxed: Boolean(area && items.some((item: any) => !item.foundArea.toLowerCase().includes(area))),
        fallbackUrl: '/search?mode=basic',
      },
    });
  });

  // 4. Item Detail & Verification Questions
  await page.route(/\/api\/items\/([\da-f-]+)$/i, async (route) => {
    const method = route.request().method();
    const match = route.request().url().match(/\/api\/items\/([\da-f-]+)$/i);
    const id = match ? match[1] : '';

    if (method === 'GET') {
      const found = items.find((it: any) => it.id === id) ?? items[0];
      await route.fulfill({ status: 200, json: { ...found, id } });
    } else if (method === 'PUT') {
      const data = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        json: { ...items[0], id, ...data?.content, rowVersion: 2 },
      });
    } else {
      await route.continue();
    }
  });

  await page.route(/\/api\/items\/([\da-f-]+)\/verification-questions$/i, async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        contentVersion: 1,
        questions: [
          {
            slot: 1,
            questionText: 'Móc khóa có hình nhân vật hoạt hình nào?',
          },
        ],
      },
    });
  });

  // 4b. Item Custody Events
  await page.route(/\/api\/items\/([\da-f-]+)\/custody-events(\?.*)?$/i, async (route) => {
    const match = route.request().url().match(/\/api\/items\/([\da-f-]+)\/custody-events(\?.*)?$/i);
    const itemId = match ? match[1] : items[0]?.id ?? 'item-01';
    await route.fulfill({
      status: 200,
      json: {
        items: [
          {
            id: 'evt-01',
            itemId,
            eventKind: 'received',
            custodyVersion: 2,
            actorUserId: user?.id ?? 'u-staff-test-01',
            fromCustody: { kind: 'person' },
            occurredAt: '2026-11-06T11:00:00Z',
          },
        ],
        page: 1,
        pageSize: 20,
        hasMore: false,
      },
    });
  });

  // 5. Post Item Creation
  await page.route('**/api/items', async (route) => {
    if (route.request().method() === 'POST') {
      const postData = route.request().postDataJSON();
      const newItemId = 'e4b2d380-6bc7-4d98-b80c-e2f4a56c9999';
      await route.fulfill({
        status: 201,
        json: {
          id: newItemId,
          title: postData?.content?.title ?? 'Món đồ mới đăng',
          publicDescription: postData?.content?.description ?? 'Mô tả chi tiết',
          foundArea: postData?.content?.area ?? 'Cơ sở 1',
          foundTimePrecision: postData?.content?.precision ?? 'unknown',
          foundOn: null,
          foundFrom: null,
          foundUntil: null,
          foundTimezone: 'Asia/Ho_Chi_Minh',
          custody: postData?.custody ?? { kind: 'person', displayName: user?.displayName ?? 'Tôi' },
          lifecycle: 'active',
          publicationState: 'published',
          canClaim: true,
          canDelete: true,
          rowVersion: 1,
          createdAt: new Date().toISOString(),
          images: [],
        },
      });
    } else {
      await route.continue();
    }
  });

  // 6. Image Upload
  await page.route(/\/api\/items\/([\da-f-]+)\/images\?position=(\d+)$/i, async (route) => {
    const match = route.request().url().match(/\/api\/items\/([\da-f-]+)\/images\?position=(\d+)$/i);
    const itemId = match ? match[1] : '';
    const position = match ? Number(match[2]) : 1;

    await route.fulfill({
      status: 201,
      json: {
        id: `img-${itemId}-${position}`,
        itemId,
        position,
        contentVersion: 1,
        processingState: 'completed',
        reviewState: 'approved',
        failureCode: null,
        previewUrl: '/assets/sample-item.jpg',
      },
    });
  });

  // 7. Reception Points
  await page.route('**/api/reception-points', async (route) => {
    await route.fulfill({
      status: 200,
      json: [
        {
          id: 'point-dh-sgu-01',
          name: 'Trạm Tiếp Nhận - ĐH Sài Gòn',
          publicAddress: '273 An Dương Vương, Phường 3, Quận 5',
          directions: 'Quầy tiếp nhận tại sảnh A',
        },
      ],
    });
  });

  await page.route(/\/api\/reception-points\/([\da-z-]+)$/i, async (route) => {
    const match = route.request().url().match(/\/api\/reception-points\/([\da-z-]+)$/i);
    const id = match ? match[1] : 'point-dh-sgu-01';
    await route.fulfill({
      status: 200,
      json: {
        id,
        name: 'Trạm Tiếp Nhận - ĐH Sài Gòn',
        publicAddress: '273 An Dương Vương, Phường 3, Quận 5',
        directions: 'Quầy tiếp nhận tại sảnh A',
      },
    });
  });

  // 8. Claims (Claim submission & Claim detail)
  await page.route(/\/api\/items\/([\da-f-]+)\/claims$/i, async (route) => {
    const match = route.request().url().match(/\/api\/items\/([\da-f-]+)\/claims$/i);
    const itemId = match ? match[1] : '';
    const postData = route.request().postDataJSON();

    await route.fulfill({
      status: 201,
      json: {
        id: 'c1a2b3c4-d5e6-4a7b-8c9d-0e1f2a3b4c5d',
        itemId,
        claimantUserId: user?.id ?? 'u-claimer-01',
        reviewerUserId: 'u-finder-01',
        status: 'pending',
        stale: false,
        createdAt: new Date().toISOString(),
        decidedAt: null,
        decisionNote: null,
        conversationId: null,
        answers: postData?.answers ?? [],
      },
    });
  });

  await page.route(/\/api\/claims\/([\da-f-]+)$/i, async (route) => {
    const match = route.request().url().match(/\/api\/claims\/([\da-f-]+)$/i);
    const claimId = match ? match[1] : '';

    await route.fulfill({
      status: 200,
      json: {
        id: claimId,
        itemId: items[0].id,
        claimantUserId: user?.id ?? 'u-claimer-01',
        reviewerUserId: 'u-finder-other-02',
        status: 'pending',
        stale: false,
        createdAt: '2026-11-04T09:00:00Z',
        decidedAt: null,
        decisionNote: null,
        conversationId: null,
        answers: [
          {
            slot: 1,
            questionText: 'Móc khóa có hình nhân vật hoạt hình nào?',
            answerText: 'Doraemon đeo chuông vàng',
          },
        ],
      },
    });
  });

  // 9. Admin Portal API Mocks
  let mockAdminUsersList = [
    {
      id: 'u-admin-test-01',
      email: 'admin@findie.vn',
      displayName: 'Super Admin',
      createdAt: '2026-11-01T00:00:00Z',
      disabledAt: null,
      isAdmin: true,
      itemsCount: 5,
    },
    {
      id: 'u-target-02',
      email: 'user.spam@example.com',
      displayName: 'Người Dùng Khả Nghi',
      createdAt: '2026-11-02T10:00:00Z',
      disabledAt: null,
      isAdmin: false,
      itemsCount: 1,
    },
  ];

  let mockAdminItemsList = [
    {
      id: 'item-mod-01',
      title: 'Ví da cá sấu màu nâu',
      publicDescription: 'Ví da rơi tại sảnh B cơ sở 1',
      foundArea: 'Cơ sở 1 - Khu A',
      foundTimePrecision: 'date',
      foundOn: '2026-11-05',
      foundFrom: null,
      foundUntil: null,
      lifecycle: 'active',
      publicationState: 'published',
      rowVersion: 1,
      createdAt: '2026-11-05T08:30:00Z',
      updatedAt: '2026-11-05T08:30:00Z',
      authorId: 'u-author-01',
      authorDisplayName: 'Trần Thị Tìm Thấy',
      authorEmail: 'author@example.com',
      custodyKind: 'person',
      holderPointId: null,
      holderPointName: null,
      images: [
        {
          id: 'img-mod-01',
          position: 1,
          contentVersion: 1,
          processingState: 'completed',
          reviewState: 'approved',
          failureCode: null,
          retiredAt: null,
          previewUrl: '/assets/sample-item.jpg',
          redactionModelId: 'mock-redact',
          redactionProfile: 'standard',
        },
      ],
    },
  ];

  let mockAdminPointsList = [
    {
      id: 'point-dh-sgu-01',
      name: 'Trạm Tiếp Nhận - ĐH Sài Gòn',
      publicAddress: '273 An Dương Vương, Phường 3, Quận 5',
      directions: 'Quầy tiếp nhận tại sảnh A',
      active: true,
      createdAt: '2026-10-01T00:00:00Z',
      staffCount: 1,
      itemsCount: 3,
    },
  ];

  await page.route('**/api/admin/overview', async (route) => {
    if (!user?.isAdmin) {
      await route.fulfill({ status: 403, json: { message: 'Forbidden' } });
      return;
    }
    await route.fulfill({
      status: 200,
      json: {
        totalItems: 42,
        activeItems: 28,
        returnedItems: 12,
        hiddenItems: 2,
        totalUsers: 150,
        activeUsers: 147,
        disabledUsers: 3,
        totalHubs: 5,
        activeHubs: 5,
        totalCustodyEvents: 85,
        totalHandovers: 12,
      },
    });
  });

  await page.route(/\/api\/admin\/users(\?.*)?$/i, async (route) => {
    if (!user?.isAdmin) {
      await route.fulfill({ status: 403, json: { message: 'Forbidden' } });
      return;
    }
    const url = new URL(route.request().url());
    const query = url.searchParams.get('query')?.toLowerCase() ?? '';
    let filtered = mockAdminUsersList;
    if (query) {
      filtered = filtered.filter(
        (u) =>
          u.displayName.toLowerCase().includes(query) ||
          (u.email && u.email.toLowerCase().includes(query))
      );
    }
    await route.fulfill({
      status: 200,
      json: {
        items: filtered,
        page: 1,
        pageSize: 20,
        hasMore: false,
      },
    });
  });

  await page.route(/\/api\/admin\/users\/([\da-z-]+)\/toggle-status$/i, async (route) => {
    if (!user?.isAdmin) {
      await route.fulfill({ status: 403, json: { message: 'Forbidden' } });
      return;
    }
    const match = route.request().url().match(/\/api\/admin\/users\/([\da-z-]+)\/toggle-status$/i);
    const targetId = match ? match[1] : '';
    const found = mockAdminUsersList.find((u) => u.id === targetId);
    if (!found) {
      await route.fulfill({ status: 404, json: { message: 'User not found' } });
      return;
    }
    found.disabledAt = found.disabledAt ? null : new Date().toISOString();
    await route.fulfill({
      status: 200,
      json: found,
    });
  });

  await page.route(/\/api\/admin\/items(\?.*)?$/i, async (route) => {
    if (!user?.isAdmin) {
      await route.fulfill({ status: 403, json: { message: 'Forbidden' } });
      return;
    }
    const url = new URL(route.request().url());
    const query = url.searchParams.get('query')?.toLowerCase() ?? '';
    let filtered = mockAdminItemsList;
    if (query) {
      filtered = filtered.filter(
        (i) =>
          i.title.toLowerCase().includes(query) ||
          i.publicDescription.toLowerCase().includes(query)
      );
    }
    await route.fulfill({
      status: 200,
      json: {
        items: filtered,
        page: 1,
        pageSize: 20,
        hasMore: false,
      },
    });
  });

  await page.route(/\/api\/admin\/items\/([\da-z-]+)\/set-publication$/i, async (route) => {
    if (!user?.isAdmin) {
      await route.fulfill({ status: 403, json: { message: 'Forbidden' } });
      return;
    }
    const match = route.request().url().match(/\/api\/admin\/items\/([\da-z-]+)\/set-publication$/i);
    const targetId = match ? match[1] : '';
    const postData = route.request().postDataJSON();
    const found = mockAdminItemsList.find((i) => i.id === targetId);
    if (found) {
      found.publicationState = postData.publicationState;
      found.rowVersion += 1;
      found.updatedAt = new Date().toISOString();
    }
    await route.fulfill({
      status: 200,
      json: {
        id: targetId,
        publicationState: postData?.publicationState ?? 'hidden',
        rowVersion: found ? found.rowVersion : 2,
        updatedAt: new Date().toISOString(),
      },
    });
  });

  await page.route(/\/api\/admin\/items\/([\da-z-]+)\/images\/([\da-z-]+)\/retire$/i, async (route) => {
    if (!user?.isAdmin) {
      await route.fulfill({ status: 403, json: { message: 'Forbidden' } });
      return;
    }
    const match = route.request().url().match(/\/api\/admin\/items\/([\da-z-]+)\/images\/([\da-z-]+)\/retire$/i);
    await route.fulfill({
      status: 200,
      json: {
        id: match ? match[2] : 'img-retired',
        itemId: match ? match[1] : 'item-mod-01',
        retiredAt: new Date().toISOString(),
        reviewState: 'rejected',
      },
    });
  });

  await page.route(/\/api\/admin\/points(\?.*)?$/i, async (route) => {
    if (!user?.isAdmin) {
      await route.fulfill({ status: 403, json: { message: 'Forbidden' } });
      return;
    }
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        json: mockAdminPointsList,
      });
    } else if (route.request().method() === 'POST') {
      const postData = route.request().postDataJSON();
      const newPoint = {
        id: `point-new-${Date.now()}`,
        name: postData.name,
        publicAddress: postData.publicAddress,
        directions: postData.directions ?? null,
        active: true,
        createdAt: new Date().toISOString(),
        staffCount: 0,
        itemsCount: 0,
      };
      mockAdminPointsList.push(newPoint);
      await route.fulfill({ status: 201, json: newPoint });
    } else {
      await route.continue();
    }
  });

  await page.route(/\/api\/admin\/points\/([\da-z-]+)\/staff$/i, async (route) => {
    if (!user?.isAdmin) {
      await route.fulfill({ status: 403, json: { message: 'Forbidden' } });
      return;
    }
    await route.fulfill({
      status: 200,
      json: [
        {
          pointId: 'point-dh-sgu-01',
          userId: 'u-staff-test-01',
          email: 'staff@findie.vn',
          displayName: 'Nguyễn Văn Trực Trạm',
          canReceive: true,
          canReturn: true,
          assignedAt: '2026-10-15T00:00:00Z',
          revokedAt: null,
        },
      ],
    });
  });

  // 10. Intake Requests (Hub Workspace)
  let mockIntakesList = [
    {
      id: 'intake-req-01',
      itemId: 'e4b2d380-6bc7-4d98-b80c-e2f4a56c0001',
      pointId: 'point-dh-sgu-01',
      senderUserId: 'u-sender-01',
      status: 'pending',
      stale: false,
      itemRowVersion: 1,
      createdAt: '2026-11-06T10:00:00Z',
      decidedAt: null,
      decisionNote: null,
    },
  ];

  await page.route(/\/api\/intake-requests(\?.*)?$/i, async (route) => {
    if (route.request().method() === 'GET') {
      const url = new URL(route.request().url());
      const status = url.searchParams.get('status');
      let filtered = mockIntakesList;
      if (status && status !== 'all') {
        filtered = filtered.filter((i) => i.status === status);
      }
      await route.fulfill({
        status: 200,
        json: {
          items: filtered,
          page: 1,
          pageSize: 12,
          hasMore: false,
        },
      });
    } else {
      await route.continue();
    }
  });

  await page.route(/\/api\/intake-requests\/([\da-z-]+)\/decision$/i, async (route) => {
    const match = route.request().url().match(/\/api\/intake-requests\/([\da-z-]+)\/decision$/i);
    const intakeId = match ? match[1] : '';
    const postData = route.request().postDataJSON();
    const found = mockIntakesList.find((i) => i.id === intakeId);
    if (found) {
      found.status = postData.decision === 'received' ? 'received' : 'rejected';
      found.decidedAt = new Date().toISOString();
      found.decisionNote = postData.note ?? null;
    }
    await route.fulfill({
      status: 200,
      json: {
        id: intakeId,
        status: postData?.decision ?? 'received',
        decidedAt: new Date().toISOString(),
        decisionNote: postData?.note ?? null,
      },
    });
  });
}
