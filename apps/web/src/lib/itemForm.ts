import type { CustodyKind, Item, Question } from "./api.ts";

export type ItemDraft = {
  title: string;
  description: string;
  area: string;
  precision: Item["foundTimePrecision"];
  date: string;
  from: string;
  until: string;
  questions: string[];
  kind: CustodyKind;
  pointId: string;
  externalName: string;
  address: string;
  instructions: string;
};
export const emptyDraft: ItemDraft = {
  title: "",
  description: "",
  area: "",
  precision: "unknown",
  date: "",
  from: "",
  until: "",
  questions: [],
  kind: "person",
  pointId: "",
  externalName: "",
  address: "",
  instructions: "",
};

export function vietnamLocal(value: string): string {
  return new Date(new Date(value).getTime() + 7 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 16);
}
export function draftFromItem(item: Item, questions: Question[]): ItemDraft {
  return {
    title: item.title,
    description: item.publicDescription,
    area: item.foundArea,
    precision: item.foundTimePrecision,
    date: item.foundOn ?? "",
    from: item.foundFrom ? vietnamLocal(item.foundFrom) : "",
    until: item.foundUntil ? vietnamLocal(item.foundUntil) : "",
    questions: questions.map((question) => question.questionText),
    kind: item.custody.kind,
    pointId: item.custody.pointId ?? "",
    externalName: item.custody.name ?? "",
    address: item.custody.publicAddress ?? "",
    instructions: item.custody.instructions ?? "",
  };
}

function text(value: string, max: number, label: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > max)
    throw new Error(`${label} cần có từ 1 đến ${max} ký tự.`);
  return trimmed;
}

export function itemContent(draft: ItemDraft, now = Date.now()) {
  const content = {
    title: text(draft.title, 200, "Tên món đồ"),
    publicDescription: text(draft.description, 5000, "Mô tả"),
    foundArea: text(draft.area, 200, "Khu vực"),
    foundTimePrecision: draft.precision,
    foundTimezone: "Asia/Ho_Chi_Minh",
    foundOn: null as string | null,
    foundFrom: null as string | null,
    foundUntil: null as string | null,
    verificationQuestions: (draft.kind === "person" ? draft.questions : [])
      .filter((question) => question.trim())
      .map((question) => text(question, 500, "Câu hỏi")),
  };
  if (content.verificationQuestions.length > 3)
    throw new Error("Chỉ đặt tối đa 3 câu hỏi xác minh.");
  if (draft.precision === "date") {
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(draft.date) ||
      Number.isNaN(Date.parse(draft.date)) ||
      new Date(draft.date).toISOString().slice(0, 10) !== draft.date ||
      draft.date > vietnamLocal(new Date(now).toISOString()).slice(0, 10)
    )
      throw new Error("Ngày nhặt được chưa hợp lệ hoặc ở trong tương lai.");
    content.foundOn = draft.date;
  } else if (draft.precision === "exact" || draft.precision === "range") {
    function timestamp(value: string) {
      if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value))
        throw new Error("Vui lòng nhập thời gian nhặt được hợp lệ.");
      const date = new Date(`${value}:00+07:00`);
      if (
        Number.isNaN(date.getTime()) ||
        vietnamLocal(date.toISOString()) !== value ||
        date.getTime() > now
      )
        throw new Error(
          "Thời gian nhặt được chưa hợp lệ hoặc ở trong tương lai.",
        );
      return date.toISOString();
    }
    content.foundFrom = timestamp(draft.from);
    if (draft.precision === "range") {
      content.foundUntil = timestamp(draft.until);
      if (content.foundFrom > content.foundUntil)
        throw new Error("Thời gian kết thúc cần sau thời gian bắt đầu.");
    }
  } else if (draft.precision !== "unknown")
    throw new Error("Vui lòng chọn độ chính xác của thời gian.");
  return content;
}

export function itemCustody(draft: ItemDraft) {
  if (draft.kind === "person") return { kind: "person" };
  if (draft.kind === "point") {
    if (!/^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(draft.pointId))
      throw new Error("Vui lòng chọn một điểm tiếp nhận.");
    return {
      kind: "point",
      pointId: draft.pointId,
      confirmedPhysicalReceipt: false,
    };
  }
  if (draft.kind !== "external") throw new Error("Nơi giữ chưa hợp lệ.");
  if (draft.instructions.trim().length > 2000)
    throw new Error("Hướng dẫn nhận đồ tối đa 2000 ký tự.");
  return {
    kind: "external",
    name: text(draft.externalName, 200, "Tên nơi giữ"),
    address: text(draft.address, 500, "Địa chỉ công khai"),
    instructions: draft.instructions.trim() || null,
  };
}

export function directReturnInput(kind: CustodyKind, rowVersion: number, note: string, confirmed: boolean) {
  if (kind === "person") throw new Error("Hãy trao trả qua yêu cầu nhận đồ đã được chấp thuận.");
  if (!confirmed) throw new Error("Cần xác nhận đã bàn giao món đồ thực tế.");
  const verificationNote = note.trim();
  if ((kind === "point" && !verificationNote) || verificationNote.length > 2000)
    throw new Error("Ghi chú xác minh tại Hub cần có từ 1 đến 2000 ký tự.");
  return { rowVersion, confirmedPhysicalHandover: true, verificationNote: verificationNote || null };
}
