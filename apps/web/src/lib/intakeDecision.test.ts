import assert from "node:assert/strict";
import test from "node:test";
import { intakeDecision } from "./intakeDecision.ts";

const pending = { status: "pending", stale: false, itemRowVersion: 7 };

test("receiving requires physical receipt and sends the current item version", () => {
  assert.throws(() => intakeDecision(pending, "received", false, ""));
  assert.deepEqual(intakeDecision(pending, "received", true, " Đã nhận "), {
    decision: "received",
    rowVersion: 7,
    confirmedPhysicalReceipt: true,
    note: "Đã nhận",
  });
});

test("rejection keeps its note without claiming physical receipt", () => {
  assert.deepEqual(intakeDecision(pending, "rejected", true, " Sai điểm "), {
    decision: "rejected",
    rowVersion: 7,
    confirmedPhysicalReceipt: false,
    note: "Sai điểm",
  });
  assert.equal(intakeDecision(pending, "rejected", false, " ").note, null);
});

test("stale requests and invalid item versions cannot change custody", () => {
  for (const intake of [{ ...pending, stale: true }, { ...pending, status: "received" }])
    assert.throws(() => intakeDecision(intake, "received", true, ""));
  for (const itemRowVersion of [0, -1, NaN, Number.MAX_SAFE_INTEGER + 1])
    assert.throws(() => intakeDecision({ ...pending, itemRowVersion }, "rejected", false, ""));
  assert.throws(() => intakeDecision(pending, "rejected", false, "x".repeat(2001)));
});
