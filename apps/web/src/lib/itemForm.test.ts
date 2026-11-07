import assert from "node:assert/strict";
import test from "node:test";
import {
  emptyDraft,
  itemContent,
  itemCustody,
  vietnamLocal,
  directReturnInput,
} from "./itemForm.ts";

const now = Date.parse("2026-10-24T02:00:00Z");

test("direct handovers require physical confirmation, use the latest version and verify Hub recipients", () => {
  assert.throws(() => directReturnInput("person", 2, "", true));
  assert.throws(() => directReturnInput("external", 2, "", false));
  assert.throws(() => directReturnInput("point", 2, "   ", true));
  assert.throws(() => directReturnInput("point", 2, "x".repeat(2001), true));
  assert.deepEqual(directReturnInput("point", 7, "  Đã đối chiếu trực tiếp  ", true), {
    rowVersion: 7, confirmedPhysicalHandover: true, verificationNote: "Đã đối chiếu trực tiếp",
  });
  assert.deepEqual(directReturnInput("external", 3, "", true), {
    rowVersion: 3, confirmedPhysicalHandover: true, verificationNote: null,
  });
});
const draft = {
  ...emptyDraft,
  title: "  Ví da đen  ",
  description: "Ví gập khóa vàng",
  area: "Thủ Đức",
  questions: [" Có móc khóa hình gì? ", ""],
};

test("item metadata trims text, omits empty questions and does not submit stale time fields", () => {
  const content = itemContent(
    { ...draft, date: "2027-01-01", from: "invalid" },
    now,
  );
  assert.equal(content.title, "Ví da đen");
  assert.deepEqual(content.verificationQuestions, ["Có móc khóa hình gì?"]);
  assert.equal(content.foundOn, null);
  assert.equal(content.foundFrom, null);
  assert.equal(content.foundUntil, null);
});

test("only personal custody submits verification questions", () => {
  for (const kind of ["point", "external"] as const)
    assert.deepEqual(
      itemContent({ ...draft, kind, questions: ["x".repeat(501), "a", "b", "c"] }, now)
        .verificationQuestions,
      [],
    );
  assert.deepEqual(itemContent(draft, now).verificationQuestions, ["Có móc khóa hình gì?"]);
});

test("found times use Vietnam time even when the browser or host has another timezone", () => {
  assert.equal(
    itemContent({ ...draft, precision: "exact", from: "2026-10-24T08:30" }, now)
      .foundFrom,
    "2026-10-24T01:30:00.000Z",
  );
  assert.equal(vietnamLocal("2026-10-23T18:30:00Z"), "2026-10-24T01:30");
  assert.equal(
    itemContent(
      { ...draft, precision: "date", date: "2026-10-24" },
      Date.parse("2026-10-23T18:00:00Z"),
    ).foundOn,
    "2026-10-24",
  );
});

test("invalid, future or backwards found times cannot be submitted", () => {
  for (const fields of [
    { precision: "date" as const, date: "2026-02-30" },
    { precision: "date" as const, date: "2026-10-25" },
    { precision: "exact" as const, from: "2026-10-24T10:00" },
    { precision: "exact" as const, from: "2026-02-30T10:00" },
    {
      precision: "range" as const,
      from: "2026-10-24T08:00",
      until: "2026-10-24T07:00",
    },
  ])
    assert.throws(() => itemContent({ ...draft, ...fields }, now));
  assert.throws(() => itemContent({ ...draft, title: "  " }, now));
  assert.throws(() =>
    itemContent({ ...draft, questions: ["a", "b", "c", "d"] }, now),
  );
});

test("custody payload never claims physical receipt and strips fields from other branches", () => {
  const pointId = "00000000-0000-4000-8000-000000000001";
  assert.deepEqual(itemCustody({ ...draft, pointId, address: "not public" }), {
    kind: "person",
  });
  assert.deepEqual(
    itemCustody({ ...draft, kind: "point", pointId, externalName: "unused" }),
    { kind: "point", pointId, confirmedPhysicalReceipt: false },
  );
  assert.throws(() => itemCustody({ ...draft, kind: "point", pointId: "" }));
  assert.throws(() =>
    itemCustody({ ...draft, kind: "external", address: "Địa chỉ" }),
  );
  assert.deepEqual(
    itemCustody({
      ...draft,
      kind: "external",
      externalName: " Quầy bảo vệ ",
      address: " Địa chỉ công khai ",
    }),
    {
      kind: "external",
      name: "Quầy bảo vệ",
      address: "Địa chỉ công khai",
      instructions: null,
    },
  );
});
