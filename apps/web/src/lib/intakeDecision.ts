import type { Intake } from "./api";

export function intakeDecision(
  intake: Pick<Intake, "status" | "stale" | "itemRowVersion">,
  decision: "received" | "rejected",
  confirmedPhysicalReceipt: boolean,
  note: string,
) {
  if (intake.status !== "pending" || intake.stale)
    throw new Error("Đề nghị đã thay đổi hoặc đã được xử lý. Hãy tải lại.");
  if (!Number.isSafeInteger(intake.itemRowVersion) || intake.itemRowVersion < 1)
    throw new Error("Chưa đọc được phiên bản món đồ. Hãy tải lại trước khi xác nhận.");
  if (decision === "received" && !confirmedPhysicalReceipt)
    throw new Error("Chỉ xác nhận sau khi đã nhận món đồ thực tế tại Hub.");
  if (note.trim().length > 2000)
    throw new Error("Ghi chú cần có tối đa 2.000 ký tự.");
  return {
    decision,
    rowVersion: intake.itemRowVersion,
    confirmedPhysicalReceipt: decision === "received" && confirmedPhysicalReceipt,
    note: note.trim() || null,
  };
}
