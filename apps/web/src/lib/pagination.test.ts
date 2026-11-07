import assert from "node:assert/strict";
import test from "node:test";
import { paginationPages } from "./pagination.ts";

test("short pagination lists show every page without duplicates", () => {
  assert.deepEqual(paginationPages(1, 1), [1]);
  assert.deepEqual(paginationPages(2, 3), [1, 2, 3]);
  assert.deepEqual(paginationPages(7, 7), [1, 2, 3, 4, 5, 6, 7]);
});

test("long pagination lists keep the first, last and nearby pages visible", () => {
  assert.deepEqual(paginationPages(1, 20), [1, 2, 3, 4, "ellipsis", 20]);
  assert.deepEqual(paginationPages(10, 20), [1, "ellipsis", 9, 10, 11, "ellipsis", 20]);
  assert.deepEqual(paginationPages(20, 20), [1, "ellipsis", 17, 18, 19, 20]);
  assert.deepEqual(paginationPages(4, 10), [1, 2, 3, 4, 5, "ellipsis", 10]);
  assert.deepEqual(paginationPages(7, 10), [1, "ellipsis", 6, 7, 8, 9, 10]);
  assert.deepEqual(paginationPages(100, 20), [1, "ellipsis", 17, 18, 19, 20]);
});

test("page buttons stay ordered, in range and bounded for large result sets", () => {
  for (const totalPages of [1, 2, 7, 8, 20, 10000]) {
    for (let page = 1; page <= totalPages; page++) {
      const pages = paginationPages(page, totalPages);
      const numbers = pages.filter((value) => typeof value === "number");
      assert.equal(numbers[0], 1);
      assert.equal(numbers.at(-1), totalPages);
      assert.ok(numbers.includes(page));
      assert.ok(pages.length <= 7);
      assert.ok(numbers.every((value, index) => value >= 1 && value <= totalPages
        && (index === 0 || value > numbers[index - 1])));
    }
  }
});
