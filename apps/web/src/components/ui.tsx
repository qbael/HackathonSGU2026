import { useRef, useState, type ReactNode } from "react";
import {
  ApiError,
  custodyLabels,
  imageUrl,
  statusLabels,
  type Item,
} from "../lib/api";
import { paginationPages } from "../lib/pagination";

const paths = {
  search: "m21 21-4.4-4.4M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0Z",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  back: "M19 12H5m6-6-6 6 6 6",
  pin: "M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Zm-5 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  shield: "m12 2 8 3v6c0 5-8 11-8 11S4 16 4 11V5l8-3Zm-4 9 3 3 5-5",
  lock: "M6 10h12v11H6V10Zm3 0V6a3 3 0 0 1 6 0v4m-3 5v2",
  plus: "M12 5v14M5 12h14",
  check: "m5 12 4 4L19 6",
  box: "m12 3 9 5-9 5-9-5 9-5ZM3 8v10l9 5 9-5V8m-9 5v10M7.5 5.5l9 5",
  chat: "M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z",
  user: "M20 21v-2a7 7 0 0 0-14 0v2M17 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  clock: "M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z",
  close: "m6 6 12 12M6 18 18 6",
  upload: "M12 16V3m-5 5 5-5 5 5M3 15v5h18v-5",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  send: "m22 2-7 20-4-9-9-4 20-7ZM11 13 22 2",
  document: "M14 2H5v20h14V7l-5-5Zm0 0v6h5M8 12h8m-8 4h6",
  building: "M3 21h18M5 21V3h14v18M9 7h1m4 0h1M9 11h1m4 0h1m-4 10v-5h2v5",
  refresh: "M20 7a9 9 0 1 0 1 8M20 2v6h-6",
  users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm13 10v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  grid: "M3 3h7v7H3zm11 0h7v7h-7zm0 11h7v7h-7zM3 14h7v7H3z",
  trash: "M3 6h18m-2 0v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6m3 0V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2",
} as const;
export function Icon({
  name,
  size = 20,
}: {
  name: keyof typeof paths;
  size?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}

export function Notice({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: "info" | "warning" | "error" | "success";
}) {
  return (
    <div
      className={`notice notice-${tone}`}
      role={tone === "error" ? "alert" : undefined}
    >
      <Icon name={tone === "success" ? "check" : "shield"} size={20} />
      <div>{children}</div>
    </div>
  );
}

export function ErrorNotice({
  error,
  retry,
}: {
  error: Error | null;
  retry?: () => void;
}) {
  if (!error) return null;
  return (
    <Notice tone="error">
      <p>{error.message}</p>
      <div className="inline-actions">
        {error instanceof ApiError && error.status === 401 ? (
          <a
            href={`/signin?returnUrl=${encodeURIComponent(window.location.pathname + window.location.search)}`}
          >
            Đăng nhập lại <Icon name="arrow" size={15} />
          </a>
        ) : (
          retry && (
            <button className="text-button" type="button" onClick={retry}>
              Thử lại <Icon name="refresh" size={15} />
            </button>
          )
        )}
      </div>
    </Notice>
  );
}

export function Loading() {
  return (
    <div className="loading" role="status">
      <span className="spinner" /> Đang tải thông tin…
    </div>
  );
}

export function EmptyState({
  title,
  children,
  icon = "box",
}: {
  title: string;
  children: ReactNode;
  icon?: keyof typeof paths;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <Icon name={icon} size={30} />
      </span>
      <h2>{title}</h2>
      <div>{children}</div>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  children,
  action,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {children && <p className="muted">{children}</p>}
      </div>
      {action}
    </div>
  );
}

export function Breadcrumb({ current }: { current: string }) {
  return (
    <nav className="breadcrumb" aria-label="Đường dẫn">
      <a href="/">Trang chủ</a>
      <span>/</span>
      <span>{current}</span>
    </nav>
  );
}

export function Badge({
  value,
  children,
}: {
  value?: string;
  children?: ReactNode;
}) {
  return (
    <span className={`badge badge-${value ?? "neutral"}`}>
      {children ?? statusLabels[value ?? ""] ?? value}
    </span>
  );
}

export function ItemPhoto({
  item,
  large = false,
  index = 0,
}: {
  item: Item;
  large?: boolean;
  index?: number;
}) {
  const source = imageUrl(item.images[index]?.url);
  const [failedSource, setFailedSource] = useState<string>();
  return (
    <div className={`item-photo${large ? " item-photo-large" : ""}`}>
      {source && source !== failedSource ? (
        <img
          src={source}
          alt={item.title}
          loading={large ? "eager" : "lazy"}
          onError={() => setFailedSource(source)}
        />
      ) : (
        <div className="photo-placeholder">
          <Icon name="box" size={large ? 66 : 44} />
          <span>
            {source ? "Ảnh tạm thời chưa khả dụng" : "Chưa có ảnh công khai"}
          </span>
        </div>
      )}
    </div>
  );
}

export function ItemSummary({ item }: { item: Item }) {
  return (
    <a className="item-summary" href={`/items/${item.id}`}>
      <ItemPhoto item={item} />
      <div>
        <span className="eyebrow">Món đồ · {item.id.slice(0, 8)}</span>
        <h3>{item.title}</h3>
        <p className="muted">
          <Icon name="pin" size={15} />
          {item.foundArea}
        </p>
        <Badge value={item.custody.kind}>
          {custodyLabels[item.custody.kind]}
        </Badge>
      </div>
    </a>
  );
}

export function SafetyNote() {
  return (
    <Notice tone="warning">
      <strong>Trao trả an toàn, không chuyển tiền trước.</strong>
      <p>
        Hẹn gặp tại nơi công cộng. Đối chiếu trực tiếp món đồ và giấy tờ trước
        khi bàn giao.
      </p>
    </Notice>
  );
}

export function Pagination({
  page,
  totalPages,
}: {
  page: number;
  totalPages: number;
}) {
  function href(value: number) {
    const query = new URLSearchParams(window.location.search);
    query.set("page", String(value));
    return `${window.location.pathname}?${query}`;
  }
  return (
    <nav className="pagination" aria-label="Phân trang">
      <span className="pagination-summary">
        {page <= totalPages ? `Trang ${page} / ${totalPages}` : `Tổng ${totalPages} trang`}
      </span>
      <div className="pagination-controls">
        <a className="button button-secondary" href={page > 1 ? href(1) : undefined} aria-disabled={page <= 1}>
          Trang đầu
        </a>
        <a className="button button-secondary" href={page > 1 ? href(Math.min(page - 1, totalPages)) : undefined} aria-disabled={page <= 1} rel="prev">
          <Icon name="back" size={16} />
          Trang trước
        </a>
      </div>
      <div className="pagination-pages">
        {paginationPages(page, totalPages).map((value, index) => value === "ellipsis" ? (
          <span className="pagination-ellipsis" key={`ellipsis-${index}`} aria-hidden="true">…</span>
        ) : (
          <a
            className={`button pagination-page${value === page ? "" : " button-secondary"}`}
            key={value}
            href={href(value)}
            aria-label={`Trang ${value}`}
            aria-current={value === page ? "page" : undefined}
          >
            {value}
          </a>
        ))}
      </div>
      <div className="pagination-controls">
        <a className="button button-secondary" href={page < totalPages ? href(page + 1) : undefined} aria-disabled={page >= totalPages} rel="next">
          Trang tiếp
          <Icon name="arrow" size={16} />
        </a>
        <a className="button button-secondary" href={page !== totalPages ? href(totalPages) : undefined} aria-disabled={page === totalPages}>
          Trang cuối
        </a>
      </div>
    </nav>
  );
}

export function ConfirmDialog({
  trigger,
  title,
  children,
  busy,
  onConfirm,
}: {
  trigger: ReactNode;
  title: string;
  children: ReactNode;
  busy: boolean;
  onConfirm: () => Promise<boolean>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  return (
    <>
      <button
        className="button button-secondary"
        type="button"
        onClick={() => ref.current?.showModal()}
      >
        {trigger}
      </button>
      <dialog
        ref={ref}
        className="confirm-dialog"
        aria-labelledby="confirm-title"
        onCancel={(event) => {
          if (busy) event.preventDefault();
        }}
      >
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (await onConfirm()) ref.current?.close();
          }}
        >
          <span className="empty-icon">
            <Icon name="shield" size={28} />
          </span>
          <h2 id="confirm-title">{title}</h2>
          <div>{children}</div>
          <label className="checkbox-field">
            <input type="checkbox" required disabled={busy} />
            Tôi xác nhận đã đối chiếu và bàn giao món đồ thực tế.
          </label>
          <div className="form-actions">
            <button
              className="button button-secondary"
              type="button"
              disabled={busy}
              onClick={() => ref.current?.close()}
            >
              Để sau
            </button>
            <button className="button" disabled={busy}>
              {busy ? "Đang xác nhận…" : "Xác nhận hoàn tất"}
              <Icon name="check" size={17} />
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
