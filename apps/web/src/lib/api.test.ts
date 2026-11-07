import assert from "node:assert/strict";
import { afterEach, mock, test } from "node:test";
import {
  api,
  ApiError,
  imageUrl,
  pageNumber,
  safeReturnUrl,
  validateImages,
  write,
} from "./api.ts";

afterEach(() => mock.restoreAll());

test("return URLs and image sources stay on trusted local routes", () => {
  for (const value of [
    null,
    "//example.test",
    "/\\example.test",
    "https://example.test",
    "/\t/example.test",
    "/signin?returnUrl=/post",
    "/post\n",
  ])
    assert.equal(safeReturnUrl(value), "/");
  assert.equal(
    safeReturnUrl("/items/abc/claim?q=key"),
    "/items/abc/claim?q=key",
  );
  assert.equal(imageUrl("https://example.test/private.png"), undefined);
  assert.equal(imageUrl("/api/items/../images/a/content"), undefined);
  assert.equal(
    imageUrl("/api/items/ab-cd/images/ef-12/content"),
    "/api/items/ab-cd/images/ef-12/content",
  );
  for (const value of [null, "-1", "NaN", "1.5", "10001"])
    assert.equal(pageNumber(value), 1);
  assert.equal(pageNumber("2"), 2);
});

test("image constraints match the upload API before sending private bytes", () => {
  validateImages([{ type: "image/jpeg", size: 10 * 1024 * 1024 }]);
  validateImages(Array(3).fill({ type: "image/webp", size: 100 }));
  for (const files of [
    [{ type: "image/svg+xml", size: 50 }],
    [{ type: "image/png", size: 0 }],
    [{ type: "image/png", size: 10 * 1024 * 1024 + 1 }],
    Array(4).fill({ type: "image/webp", size: 100 }),
  ])
    assert.throws(() => validateImages(files));
});

test("writes attach CSRF and preserve idempotency after an uncertain network failure", async () => {
  const requests: RequestInit[] = [];
  mock.method(globalThis, "fetch", async (path: string, init?: RequestInit) => {
    if (path === "/api/auth/csrf")
      return Response.json({ token: "csrf-value" });
    requests.push(init!);
    if (requests.length === 1)
      throw new TypeError("network failed after commit");
    return Response.json({ id: "saved-once" });
  });
  await assert.rejects(write("/api/items", { title: "test-key-retry" }));
  assert.deepEqual(await write("/api/items", { title: "test-key-retry" }), {
    id: "saved-once",
  });
  const first = requests[0].headers as Record<string, string>;
  const second = requests[1].headers as Record<string, string>;
  assert.equal(first["Idempotency-Key"], second["Idempotency-Key"]);
  assert.equal(first["X-CSRF-TOKEN"], "csrf-value");
  assert.equal(requests[0].credentials, "same-origin");
  await write("/api/items", { title: "test-key-retry" });
  assert.notEqual(
    (requests[2].headers as Record<string, string>)["Idempotency-Key"],
    first["Idempotency-Key"],
  );
});

test("deleting a post sends its version with CSRF and accepts an empty response", async () => {
  let deletion: RequestInit | undefined;
  mock.method(globalThis, "fetch", async (path: string, init?: RequestInit) => {
    if (path === "/api/auth/csrf")
      return Response.json({ token: "csrf-delete" });
    assert.equal(path, "/api/items/delete-post");
    deletion = init;
    return new Response(null, { status: 204 });
  });
  assert.equal(
    await write<void>("/api/items/delete-post", { rowVersion: 7 }, "DELETE"),
    undefined,
  );
  assert.equal(deletion?.method, "DELETE");
  assert.equal(deletion?.body, JSON.stringify({ rowVersion: 7 }));
  assert.equal(
    (deletion?.headers as Record<string, string>)["X-CSRF-TOKEN"],
    "csrf-delete",
  );
  assert.equal(deletion?.credentials, "same-origin");
});

test("failed sessions and malformed CSRF prevent writes; response failures stay actionable", async () => {
  let calls = 0;
  mock.method(globalThis, "fetch", async () => {
    calls++;
    return Response.json({ token: "" });
  });
  await assert.rejects(write("/api/items", { title: "invalid-csrf" }));
  assert.equal(calls, 1);
  mock.restoreAll();
  mock.method(globalThis, "fetch", async () => Response.json(null));
  await assert.rejects(
    write("/api/items", { title: "null-csrf" }),
    /Mã xác nhận phiên không hợp lệ/,
  );
  mock.restoreAll();
  mock.method(
    globalThis,
    "fetch",
    async () => new Response(null, { status: 409 }),
  );
  await assert.rejects(
    api("/api/items"),
    (error) => error instanceof ApiError && error.status === 409,
  );
  mock.restoreAll();
  mock.method(
    globalThis,
    "fetch",
    async () => new Response("not json", { status: 200 }),
  );
  await assert.rejects(api("/api/items"), /Phản hồi máy chủ chưa hợp lệ/);
});

test("server ProblemDetails errors extract title, detail, or validation errors cleanly", async () => {
  // Test with title
  mock.restoreAll();
  mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        JSON.stringify({
          status: 404,
          title: "Không tìm thấy người dùng với email 'oanhtran01011971@gmail.con'.",
        }),
        { status: 404, headers: { "Content-Type": "application/problem+json" } },
      ),
  );
  await assert.rejects(
    api("/api/admin/points/p1/staff"),
    (error) =>
      error instanceof ApiError &&
      error.status === 404 &&
      error.message === "Không tìm thấy người dùng với email 'oanhtran01011971@gmail.con'.",
  );

  // Test with detail
  mock.restoreAll();
  mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        JSON.stringify({
          status: 400,
          title: "Bad Request",
          detail: "Nhân viên trạm phải có ít nhất quyền Tiếp nhận hoặc Trao trả.",
        }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      ),
  );
  await assert.rejects(
    api("/api/admin/points/p1/staff"),
    (error) =>
      error instanceof ApiError &&
      error.status === 400 &&
      error.message === "Nhân viên trạm phải có ít nhất quyền Tiếp nhận hoặc Trao trả.",
  );

  // Test with validation errors
  mock.restoreAll();
  mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        JSON.stringify({
          status: 400,
          title: "One or more validation errors occurred.",
          errors: {
            UserEmail: ["Email không đúng định dạng."],
          },
        }),
        { status: 400, headers: { "Content-Type": "application/problem+json" } },
      ),
  );
  await assert.rejects(
    api("/api/admin/points/p1/staff"),
    (error) =>
      error instanceof ApiError &&
      error.status === 400 &&
      error.message === "Email không đúng định dạng.",
  );
  mock.restoreAll();
});
