import { useState, useEffect } from "react";
import {
  api,
  formatDate,
  type CustodyEvent,
  type Intake,
  type Item,
  type Page,
} from "../../lib/api";
import { type UserProfile } from "../../lib/auth";
import { Badge, EmptyState, ErrorNotice, Icon, Loading, Pagination } from "../../components/ui";

type HistoryFilter = "all" | "intakes" | "returns";

export default function HubHistory({
  user,
  selectedPointId,
}: {
  user: UserProfile;
  selectedPointId: string;
}) {
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const [receivedIntakes, setReceivedIntakes] = useState<Intake[]>([]);
  const [returnedItems, setReturnedItems] = useState<Item[]>([]);

  // Modal xem dòng thời gian lưu chuyển
  const [timelineEvents, setTimelineEvents] = useState<{ itemId: string; events: CustodyEvent[] } | null>(null);
  const [loadingTimelineId, setLoadingTimelineId] = useState<string | null>(null);

  const handleViewCustodyHistory = async (itemId: string) => {
    setLoadingTimelineId(itemId);
    try {
      const res = await api<Page<CustodyEvent>>(`/api/items/${itemId}/custody-events?page=1&pageSize=20`);
      setTimelineEvents({ itemId, events: res.items });
    } catch (err) {
      alert(err instanceof Error ? err.message : "Không thể tải lịch sử bàn giao.");
    } finally {
      setLoadingTimelineId(null);
    }
  };

  const loadHistory = async () => {
    if (!selectedPointId) return;
    setLoading(true);
    setError(null);
    try {
      // 1. Tải các đề nghị tiếp nhận tại trạm (đã tiếp nhận hoặc từ chối)
      const intakeRes = await api<Page<Intake>>(
        `/api/intake-requests?pointId=${selectedPointId}&page=1&pageSize=50`,
      );
      setReceivedIntakes(intakeRes.items.filter((i) => i.status === "received"));

      // 2. Tải các đồ vật tại trạm đã trao trả
      const itemsRes = await api<Page<Item>>(
        `/api/items?scope=managed&pointId=${selectedPointId}&page=1&pageSize=50`,
      );
      setReturnedItems(itemsRes.items.filter((item) => item.lifecycle === "returned"));
    } catch (err) {
      setError(
        err instanceof Error ? err : new Error("Không thể tải nhật ký lưu chuyển trạm."),
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, [selectedPointId]);

  // Hợp nhất và sắp xếp theo thời gian mới nhất
  type HistoryEntry =
    | {
        kind: "intake";
        id: string;
        itemId: string;
        occurredAt: string;
        note: string | null;
      }
    | {
        kind: "return";
        id: string;
        itemId: string;
        title: string;
        occurredAt: string;
      };

  const entries: HistoryEntry[] = [];
  if (filter === "all" || filter === "intakes") {
    for (const intake of receivedIntakes) {
      entries.push({
        kind: "intake",
        id: intake.id,
        itemId: intake.itemId,
        occurredAt: intake.decidedAt ?? intake.createdAt,
        note: intake.decisionNote,
      });
    }
  }
  if (filter === "all" || filter === "returns") {
    for (const item of returnedItems) {
      entries.push({
        kind: "return",
        id: item.id,
        itemId: item.id,
        title: item.title,
        occurredAt: item.createdAt, // item có rowVersion & lifecycle returned
      });
    }
  }

  entries.sort((a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime());

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem" }}>
        <div>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f172a", margin: 0 }}>
            Nhật ký lưu chuyển & Trao trả tại trạm
          </h1>
          <p style={{ color: "#64748b", marginTop: "0.25rem", fontSize: "0.9375rem" }}>
            Lịch sử toàn bộ các lần hiện vật được nhập kho và bàn giao trao trả thành công cho người dân.
          </p>
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={loadHistory}
          disabled={loading}
        >
          <Icon name="refresh" size={16} />
          <span>Làm mới</span>
        </button>
      </div>

      {/* Tabs lọc loại giao dịch */}
      <div
        style={{
          display: "flex",
          gap: "0.5rem",
          marginBottom: "1.25rem",
          background: "#ffffff",
          padding: "0.375rem",
          borderRadius: 8,
          border: "1px solid #e2e8f0",
          width: "fit-content",
        }}
      >
        {[
          { key: "all", label: `Tất cả (${receivedIntakes.length + returnedItems.length})` },
          { key: "intakes", label: `Nhập kho (${receivedIntakes.length})` },
          { key: "returns", label: `Trao trả (${returnedItems.length})` },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            style={{
              padding: "0.4rem 0.875rem",
              borderRadius: 6,
              border: "none",
              fontSize: "0.875rem",
              fontWeight: 600,
              cursor: "pointer",
              background: filter === tab.key ? "#0f172a" : "transparent",
              color: filter === tab.key ? "#ffffff" : "#64748b",
            }}
            onClick={() => setFilter(tab.key as HistoryFilter)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <ErrorNotice error={error} retry={loadHistory} />

      {loading && <Loading />}

      {!loading && (
        <>
          {entries.length === 0 ? (
            <EmptyState title="Chưa có nhật ký lưu chuyển" icon="document">
              <p>Các giao dịch tiếp nhận hiện vật vào kho và trao trả cho chủ sở hữu sẽ được lưu vết tại đây.</p>
            </EmptyState>
          ) : (
            <div className="hub-history-timeline">
              {entries.map((entry) => (
                <div
                  key={`${entry.kind}-${entry.id}`}
                  className={`hub-history-item ${entry.kind === "return" ? "return-event" : ""}`}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <span
                        style={{
                          fontSize: "0.75rem",
                          fontWeight: 700,
                          textTransform: "uppercase",
                          padding: "0.2rem 0.5rem",
                          borderRadius: 4,
                          background: entry.kind === "return" ? "#dbeafe" : "#f1f5f9",
                          color: entry.kind === "return" ? "#1d4ed8" : "#334155",
                        }}
                      >
                        {entry.kind === "return" ? "Bàn giao trao trả" : "Tiếp nhận vào kho"}
                      </span>
                      <span style={{ fontSize: "0.8125rem", color: "#64748b" }}>
                        {formatDate(entry.occurredAt, true)}
                      </span>
                    </div>

                    <button
                      type="button"
                      className="button button-secondary button-small"
                      onClick={() => handleViewCustodyHistory(entry.itemId)}
                      disabled={loadingTimelineId === entry.itemId}
                    >
                      <span>{loadingTimelineId === entry.itemId ? "Đang tải…" : "Lịch sử bàn giao"}</span>
                      <Icon name="arrow" size={14} />
                    </button>
                  </div>

                  <div>
                    <h3 style={{ margin: "0.25rem 0 0", fontSize: "1.0625rem", fontWeight: 700, color: "#0f172a" }}>
                      {entry.kind === "return"
                        ? `Đã trao trả: ${entry.title}`
                        : `Món đồ #${entry.itemId.slice(0, 8)}`}
                    </h3>
                    {entry.kind === "intake" && entry.note && (
                      <p style={{ margin: "0.375rem 0 0", fontSize: "0.875rem", color: "#475569" }}>
                        <strong>Ghi chú lưu kho:</strong> {entry.note}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Modal Dòng thời gian Luân chuyển / Lịch sử bàn giao */}
      {timelineEvents && (
        <div className="hub-modal-backdrop" onClick={() => setTimelineEvents(null)}>
          <div className="hub-modal-card" style={{ maxWidth: 620 }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#0f172a" }}>
                Chuỗi lưu vết & Lịch sử bàn giao
              </h3>
              <button
                type="button"
                style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", fontSize: "1.25rem", padding: "0.25rem" }}
                onClick={() => setTimelineEvents(null)}
              >
                ✕
              </button>
            </div>

            <div style={{ fontSize: "0.875rem", color: "#64748b" }}>
              Mã món đồ: <strong>#{timelineEvents.itemId.slice(0, 8)}</strong> ({timelineEvents.itemId})
            </div>

            {timelineEvents.events.length === 0 ? (
              <EmptyState title="Chưa có sự kiện lưu vết" icon="document">
                <p>Các mốc đăng ký, tiếp nhận và trao trả sẽ hiển thị tại đây.</p>
              </EmptyState>
            ) : (
              <ol className="timeline" style={{ margin: "0.5rem 0 1rem", paddingLeft: "1.25rem" }}>
                {timelineEvents.events.map((ev) => {
                  const eventLabels: Record<string, string> = {
                    registered: "Đăng ký món đồ trên Findie",
                    received: "Hub xác nhận tiếp nhận vật phẩm vào kho",
                    returned: "Đã hoàn tất trao trả cho chủ sở hữu",
                  };
                  return (
                    <li key={ev.id} style={{ marginBottom: "1rem" }}>
                      <strong style={{ color: "#0f172a", fontSize: "0.9375rem" }}>
                        {eventLabels[ev.eventKind] ?? ev.eventKind}
                      </strong>
                      <p style={{ margin: "0.25rem 0 0", fontSize: "0.8125rem", color: "#64748b" }}>
                        <time dateTime={ev.occurredAt}>{formatDate(ev.occurredAt, true)}</time> · Lần giữ đồ #{ev.custodyVersion}
                      </p>
                    </li>
                  );
                })}
              </ol>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "0.5rem", borderTop: "1px solid #f1f5f9", paddingTop: "0.875rem" }}>
              <button type="button" className="button button-secondary" onClick={() => setTimelineEvents(null)}>
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
