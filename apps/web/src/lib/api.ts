import { prepareImage } from "./images.ts";
export { validateImages } from "./images.ts";

export type Page<T> = {
  items: T[];
  page: number;
  pageSize: number;
  hasMore: boolean;
  totalPages: number;
};
export type CustodyKind = "person" | "point" | "external";
export type Item = {
  id: string;
  title: string;
  publicDescription: string;
  foundArea: string;
  foundTimePrecision: "unknown" | "date" | "exact" | "range";
  foundOn: string | null;
  foundFrom: string | null;
  foundUntil: string | null;
  foundTimezone: string;
  custody: {
    kind: CustodyKind;
    displayName: string | null;
    pointId: string | null;
    name: string | null;
    publicAddress: string | null;
    instructions: string | null;
  };
  lifecycle: string;
  publicationState: string;
  canClaim: boolean;
  canDelete: boolean;
  rowVersion: number;
  createdAt: string;
  images: {
    id: string;
    position: number;
    contentVersion: number;
    url: string;
  }[];
};
export type Point = {
  id: string;
  name: string;
  publicAddress: string;
  directions: string | null;
};
export type Question = { slot: number; questionText: string };
export type QuestionSet = { contentVersion: number; questions: Question[] };
export type Claim = {
  id: string;
  itemId: string;
  claimantUserId: string;
  reviewerUserId: string;
  status: string;
  stale: boolean;
  createdAt: string;
  decidedAt: string | null;
  decisionNote: string | null;
  conversationId: string | null;
  answers: { slot: number; questionText: string; answerText: string | null }[];
};
export type Conversation = {
  id: string;
  itemId: string;
  claimantUserId: string;
  reviewerUserId: string;
  canSend: boolean;
  createdAt: string;
};
export type Message = {
  id: string;
  conversationId: string;
  senderUserId: string;
  clientMessageId: string;
  sequence: number;
  body: string;
  createdAt: string;
};
export type MessagePage = {
  items: Message[];
  nextAfter: number;
  hasMore: boolean;
};
export type ItemImage = {
  id: string;
  itemId: string;
  position: number;
  contentVersion: number;
  processingState: string;
  reviewState: string;
  failureCode: string | null;
  previewUrl: string | null;
};
export type Intake = {
  id: string;
  itemId: string;
  requestedBy: string;
  targetPointId: string;
  itemRowVersion: number;
  status: string;
  stale: boolean;
  createdAt: string;
  decidedAt: string | null;
  decisionNote: string | null;
};
export type CustodyEvent = {
  id: string;
  itemId: string;
  eventKind: string;
  custodyVersion: number;
  occurredAt: string;
};

export type ProblemDetails = {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  errors?: Record<string, string[] | string>;
  message?: string;
};

const fieldTranslations: Record<string, string> = {
  TargetPointId: "Điểm tiếp nhận",
  PointId: "Điểm tiếp nhận",
  Title: "Tiêu đề",
  Content: "Nội dung",
  Description: "Mô tả",
  CategoryId: "Danh mục",
  Location: "Địa điểm",
  Phone: "Số điện thoại",
  Email: "Email",
  Reason: "Lý do",
  DecisionNote: "Ghi chú xử lý",
  Message: "Tin nhắn",
  Password: "Mật khẩu",
  Name: "Họ và tên",
};

export function localizeErrorMessage(raw: string): string {
  let msg = raw.trim();

  // Handle ASP.NET required field: "The {Field} field is required."
  const requiredMatch = msg.match(/^The\s+([A-Za-z0-9_]+)\s+field is required\.?$/i);
  if (requiredMatch) {
    const field = requiredMatch[1];
    const fieldName = fieldTranslations[field] ?? field;
    return `Vui lòng nhập hoặc chọn ${fieldName}.`;
  }

  // Handle Concurrency / RowVersion conflict
  if (/rowversion mismatch|concurrency conflict|the record has been modified/i.test(msg)) {
    return "Dữ liệu đã được cập nhật bởi một phiên làm việc khác. Vui lòng tải lại trang để xem dữ liệu mới nhất.";
  }

  // Handle Unauthorized / Forbidden
  if (/unauthorized/i.test(msg)) {
    return "Bạn chưa đăng nhập hoặc phiên làm việc đã hết hạn.";
  }
  if (/forbidden|not allowed to access/i.test(msg)) {
    return "Bạn không có quyền thực hiện thao tác này.";
  }

  // Handle Not Found
  if (/not found/i.test(msg)) {
    return "Không tìm thấy nội dung yêu cầu.";
  }

  return msg;
}

export function extractProblemMessage(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const problem = data as ProblemDetails;

  if (problem.errors && typeof problem.errors === "object") {
    const errorMessages: string[] = [];
    for (const val of Object.values(problem.errors)) {
      if (Array.isArray(val)) {
        for (const msg of val) {
          if (typeof msg === "string" && msg.trim()) {
            errorMessages.push(localizeErrorMessage(msg));
          }
        }
      } else if (typeof val === "string" && val.trim()) {
        errorMessages.push(localizeErrorMessage(val));
      }
    }
    if (errorMessages.length > 0) {
      return errorMessages.join(" ");
    }
  }

  if (typeof problem.detail === "string" && problem.detail.trim()) {
    return localizeErrorMessage(problem.detail.trim());
  }

  if (typeof problem.title === "string" && problem.title.trim()) {
    const trimmed = problem.title.trim();
    if (trimmed !== "One or more validation errors occurred.") {
      return localizeErrorMessage(trimmed);
    }
  }

  if (typeof problem.message === "string" && problem.message.trim()) {
    return localizeErrorMessage(problem.message.trim());
  }

  return null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const failureMessages: Record<number, string> = {
  400: "Thông tin chưa hợp lệ. Vui lòng kiểm tra lại các trường đã nhập.",
  401: "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại để tiếp tục.",
  403: "Bạn không có quyền thực hiện thao tác này với món đồ hiện tại.",
  404: "Nội dung không còn khả dụng hoặc bạn chưa được cấp quyền truy cập.",
  409: "Dữ liệu đã thay đổi hoặc yêu cầu này đã được gửi. Hãy tải lại để xem trạng thái mới.",
  413: "Ảnh vượt quá 10 MB. Vui lòng chọn ảnh nhỏ hơn.",
  415: "Vui lòng dùng ảnh JPEG, PNG hoặc WebP.",
  429: "Bạn thao tác quá nhanh. Vui lòng chờ một lát rồi thử lại.",
  502: "Dịch vụ xử lý ảnh chưa trả về kết quả hợp lệ. Tin đã lưu vẫn được giữ lại.",
  503: "Dịch vụ hiện chưa sẵn sàng. Vui lòng thử lại sau.",
};

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      signal: options.signal ?? AbortSignal.timeout(45000),
    });
  } catch (cause) {
    if (options.signal?.aborted) throw cause;
    throw new Error(
      "Chưa kết nối được máy chủ. Hãy kiểm tra kết nối và thử lại.",
      { cause },
    );
  }
  if (!response.ok) {
    let serverMessage: string | null = null;
    try {
      const data = await response.json();
      serverMessage = extractProblemMessage(data);
    } catch {
      // Body không phải JSON hoặc rỗng, dùng failureMessages dự phòng
    }
    throw new ApiError(
      response.status,
      serverMessage ||
        failureMessages[response.status] ||
        "Máy chủ chưa hoàn tất thao tác. Vui lòng thử lại.",
    );
  }
  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch {
    throw new Error(
      "Phản hồi máy chủ chưa hợp lệ. Vui lòng tải lại và thử lại.",
    );
  }
}

// shortcut: retry keys live only on this page; persist opaque keys if retries must survive navigation.
const pendingWrites = new Map<string, string>();
export async function write<T>(
  path: string,
  body: unknown,
  method = "POST",
): Promise<T> {
  const serialized = JSON.stringify(body);
  const operation = `${method}:${path}:${serialized}`;
  const key = pendingWrites.get(operation) ?? crypto.randomUUID();
  pendingWrites.set(operation, key);
  const value = await api<T>(path, {
    method,
    body: serialized,
    headers: {
      ...(await writeHeaders()),
      "Content-Type": "application/json",
      "Idempotency-Key": key,
    },
  });
  pendingWrites.delete(operation);
  return value;
}

export async function writeHeaders(): Promise<Record<string, string>> {
  const csrf = await api<unknown>("/api/auth/csrf");
  if (
    !csrf ||
    typeof csrf !== "object" ||
    !("token" in csrf) ||
    typeof csrf.token !== "string" ||
    !csrf.token.trim()
  )
    throw new Error("Mã xác nhận phiên không hợp lệ. Hãy đăng nhập lại.");
  return { "X-CSRF-TOKEN": csrf.token };
}

export async function uploadImage(
  itemId: string,
  file: File,
  position: number,
): Promise<ItemImage> {
  const prepared = await prepareImage(file);
  // Reuse the key for this exact File object while a failed upload remains in memory.
  let key = uploadKeys.get(file);
  if (!key) {
    key = crypto.randomUUID();
    uploadKeys.set(file, key);
  }
  const value = await api<ItemImage>(
    `/api/items/${itemId}/images?position=${position}`,
    {
      method: "POST",
      body: prepared,
      headers: {
        ...(await writeHeaders()),
        "Content-Type": prepared.type,
        "Idempotency-Key": key,
      },
      signal: AbortSignal.timeout(660000),
    },
  );
  uploadKeys.delete(file);
  return value;
}
const uploadKeys = new WeakMap<File, string>();

export function safeReturnUrl(value: string | null): string {
  return value &&
    /^\/(?![/\\])/.test(value) &&
    !/[\\\u0000-\u0020]/.test(value) &&
    !/^\/signin(?:[/?#]|$)/.test(value)
    ? value
    : "/";
}

export function imageUrl(value: string | null | undefined): string | undefined {
  return value &&
    /^\/api\/items\/[\da-f-]+\/images\/[\da-f-]+\/content$/.test(value)
    ? value
    : undefined;
}

export function pageNumber(value: string | null): number {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 && number <= 10000 ? number : 1;
}

export function formatDate(
  value: string | null | undefined,
  withTime = false,
): string {
  if (!value) return "Chưa xác định";
  const date = new Date(
    value.length === 10 ? `${value}T00:00:00+07:00` : value,
  );
  return Number.isNaN(date.getTime())
    ? "Chưa xác định"
    : new Intl.DateTimeFormat("vi-VN", {
        timeZone: "Asia/Ho_Chi_Minh",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
      }).format(date);
}

export function foundTime(item: Item): string {
  if (item.foundTimePrecision === "date") return formatDate(item.foundOn);
  if (item.foundTimePrecision === "unknown") return "Chưa rõ thời gian";
  return (
    formatDate(item.foundFrom, true) +
    (item.foundTimePrecision === "range"
      ? ` – ${formatDate(item.foundUntil, true)}`
      : "")
  );
}

export const custodyLabels: Record<CustodyKind, string> = {
  person: "Cá nhân đang giữ",
  point: "Tại Findie Hub",
  external: "Nơi ngoài hệ thống",
};
export const statusLabels: Record<string, string> = {
  pending: "Chờ xét duyệt",
  approved: "Đã chấp thuận",
  rejected: "Đã từ chối",
  active: "Đang tìm chủ",
  returned: "Đã trao trả",
  published: "Đang công khai",
  draft: "Bản nháp",
  hidden: "Đã ẩn",
  received: "Đã tiếp nhận",
  needs_review: "Chờ duyệt ảnh",
  ready: "Ảnh đã duyệt",
};
