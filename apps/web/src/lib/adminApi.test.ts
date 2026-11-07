import assert from "node:assert/strict";
import { afterEach, mock, test } from "node:test";
import {
  fetchAdminOverview,
  fetchAdminUsers,
  toggleUserStatus,
  fetchAdminItems,
  setPublicationState,
  retireAdminImage,
  fetchAdminPoints,
  createAdminPoint,
  togglePointActive,
  fetchPointStaff,
  assignPointStaff,
  revokePointStaff,
} from "./adminApi.ts";

afterEach(() => mock.restoreAll());

test("fetchAdminOverview calls /api/admin/overview", async () => {
  const overview = {
    totalItems: 10,
    activeItems: 8,
    returnedItems: 2,
    hiddenItems: 0,
    totalUsers: 25,
    activeUsers: 24,
    disabledUsers: 1,
    totalHubs: 3,
    activeHubs: 3,
    totalCustodyEvents: 15,
    totalHandovers: 2,
  };
  mock.method(globalThis, "fetch", async (url: unknown) => {
    assert.equal(url, "/api/admin/overview");
    return Response.json(overview);
  });
  const result = await fetchAdminOverview();
  assert.deepEqual(result, overview);
});

test("fetchAdminUsers serializes query parameters accurately", async () => {
  const usersPage = {
    items: [],
    page: 2,
    pageSize: 15,
    hasMore: false,
  };
  mock.method(globalThis, "fetch", async (url: unknown) => {
    assert.equal(url, "/api/admin/users?query=alice&page=2&pageSize=15");
    return Response.json(usersPage);
  });
  const result = await fetchAdminUsers({ query: "alice", page: 2, pageSize: 15 });
  assert.deepEqual(result, usersPage);
});

test("toggleUserStatus makes POST to toggle-status endpoint with CSRF", async () => {
  const calls: Array<[unknown, RequestInit | undefined]> = [];
  mock.method(globalThis, "fetch", async (url: unknown, options?: RequestInit) => {
    calls.push([url, options]);
    if (url === "/api/auth/csrf") return Response.json({ token: "csrf-test" });
    return Response.json({ id: "user-1", disabledAt: "2026-11-06T00:00:00Z" });
  });
  const result = await toggleUserStatus("user-1");
  assert.equal(result.id, "user-1");
  assert.equal(calls[1][0], "/api/admin/users/user-1/toggle-status");
  assert.equal(calls[1][1]?.method, "POST");
  assert.equal((calls[1][1]?.headers as Record<string, string>)["X-CSRF-TOKEN"], "csrf-test");
});

test("setPublicationState sets published or hidden state", async () => {
  const calls: Array<[unknown, RequestInit | undefined]> = [];
  mock.method(globalThis, "fetch", async (url: unknown, options?: RequestInit) => {
    calls.push([url, options]);
    if (url === "/api/auth/csrf") return Response.json({ token: "csrf-test" });
    return Response.json({ id: "item-1", publicationState: "hidden" });
  });
  const result = await setPublicationState("item-1", "hidden");
  assert.equal(result.publicationState, "hidden");
  assert.equal(calls[1][0], "/api/admin/items/item-1/set-publication");
  assert.deepEqual(JSON.parse(calls[1][1]?.body as string), { publicationState: "hidden" });
});

test("retireAdminImage makes POST to retire endpoint with CSRF", async () => {
  const calls: Array<[unknown, RequestInit | undefined]> = [];
  mock.method(globalThis, "fetch", async (url: unknown, options?: RequestInit) => {
    calls.push([url, options]);
    if (url === "/api/auth/csrf") return Response.json({ token: "csrf-test" });
    return Response.json({ id: "img-1", itemId: "item-1", retiredAt: "2026-11-06T00:00:00Z", reviewState: "approved" });
  });
  const result = await retireAdminImage("item-1", "img-1");
  assert.equal(result.id, "img-1");
  assert.equal(result.itemId, "item-1");
  assert.equal(result.reviewState, "approved");
  assert.equal(calls[1][0], "/api/admin/items/item-1/images/img-1/retire");
  assert.equal(calls[1][1]?.method, "POST");
  assert.equal((calls[1][1]?.headers as Record<string, string>)["X-CSRF-TOKEN"], "csrf-test");
});

test("revokePointStaff sends DELETE with CSRF", async () => {
  const calls: Array<[unknown, RequestInit | undefined]> = [];
  mock.method(globalThis, "fetch", async (url: unknown, options?: RequestInit) => {
    calls.push([url, options]);
    if (url === "/api/auth/csrf") return Response.json({ token: "csrf-test" });
    return new Response(null, { status: 204 });
  });
  await revokePointStaff("hub-1", "user-1");
  assert.equal(calls[1][0], "/api/admin/points/hub-1/staff/user-1");
  assert.equal(calls[1][1]?.method, "DELETE");
  assert.equal((calls[1][1]?.headers as Record<string, string>)["X-CSRF-TOKEN"], "csrf-test");
});
