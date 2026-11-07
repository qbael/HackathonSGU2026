import { useState, useEffect } from "react";
import {
  api,
  formatDate,
  write,
  type Intake,
  type Item,
  type Page,
} from "../../lib/api";
import { intakeDecision } from "../../lib/intakeDecision";
import { type UserProfile } from "../../lib/auth";
import { Badge, EmptyState, ErrorNotice, Icon, Loading, Notice, Pagination, useToast } from "../../components/ui";

export default function HubIntakes({
  user,
  selectedPointId,
}: {
  user: UserProfile;
  selectedPointId: string;
}) {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [intakesPage, setIntakesPage] = useState<Page<Intake> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Thao tác modal
  const [activeModal, setActiveModal] = useState<{
    type: "receive" | "reject";
    intake: Intake;
  } | null>(null);
  const [modalItem, setModalItem] = useState<Item | null>(null);
  const [modalLoadingItem, setModalLoadingItem] = useState(false);
  const [decisionNote, setDecisionNote] = useState("");
  const [confirmedPhysical, setConfirmedPhysical] = useState(false);
  const [modalSubmitting, setModalSubmitting] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  // Modal Chi tiết đề nghị tiếp nhận tại chỗ
  const [previewIntakeItem, setPreviewIntakeItem] = useState<{ intake: Intake; item: Item } | null>(null);
  const [loadingPreviewId, setLoadingPreviewId] = useState<string | null>(null);

  const handleViewIntakeDetail = async (intake: Intake) => {
    setLoadingPreviewId(intake.id);
    try {
      const item = await api<Item>(`/api/items/${intake.itemId}`);
      setPreviewIntakeItem({ intake, item });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Không thể tải thông tin món đồ.");
    } finally {
      setLoadingPreviewId(null);
    }
  };

  // Load danh sách đề nghị
  const loadIntakes = () => {
    if (!selectedPointId) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      pointId: selectedPointId,
      page: String(page),
      pageSize: "12",
    });
    api<Page<Intake>>(`/api/intake-requests?${params}`)
      .then((data) => setIntakesPage(data))
      .catch((err) =>
        setError(
          err instanceof Error
            ? err
            : new Error("Không thể tải danh sách đề nghị tiếp nhận."),
        ),
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    setPage(1);
  }, [selectedPointId, statusFilter]);

  useEffect(() => {
    loadIntakes();
  }, [selectedPointId, page]);

  // Load chi tiết món đồ khi mở modal thao tác
  useEffect(() => {
    if (!activeModal) {
      setModalItem(null);
      setDecisionNote("");
      setConfirmedPhysical(false);
      setModalError(null);
      return;
    }
    setModalLoadingItem(true);
    api<Item>(`/api/items/${activeModal.intake.itemId}`)
      .then(setModalItem)
      .catch(() => setModalItem(null))
      .finally(() => setModalLoadingItem(false));
  }, [activeModal]);

  const handleDecisionSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeModal) return;

    setModalSubmitting(true);
    setModalError(null);
    try {
      const decision = activeModal.type === "receive" ? "received" : "rejected";
      const payload = intakeDecision(
        activeModal.intake,
        decision,
        confirmedPhysical,
        decisionNote,
      );

      await write<Intake>(
        `/api/intake-requests/${activeModal.intake.id}/decision`,
        payload,
      );

      setActiveModal(null);
      loadIntakes();
    } catch (err) {
      setModalError(
        err instanceof Error ? err.message : "Thao tác không thành công.",
      );
    } finally {
      setModalSubmitting(false);
    }
  };

  const filteredItems = intakesPage?.items.filter((item) => {
    if (statusFilter === "all") return true;
    return item.status === statusFilter;
  }) ?? [];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem" }}>
        <div>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f172a", margin: 0 }}>
            Bàn tiếp nhận vật phẩm
          </h1>
          <p style={{ color: "#64748b", marginTop: "0.25rem", fontSize: "0.9375rem" }}>
            Quản lý và tiếp nhận các món đồ do cộng đồng mang tới bàn giao tại trạm.
          </p>
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={loadIntakes}
          disabled={loading}
        >
          <Icon name="refresh" size={16} />
          <span>Làm mới</span>
        </button>
      </div>

      {/* Thanh bộ lọc trạng thái */}
      <div
        style={{
          display: "flex",
          gap: "0.5rem",
          marginBottom: "1.25rem",
          background: "#ffffff",
          padding: "0.5rem",
          borderRadius: 10,
          border: "1px solid #e2e8f0",
          width: "fit-content",
        }}
      >
        {[
          { key: "all", label: "Tất cả đề nghị" },
          { key: "pending", label: "Chờ tiếp nhận" },
          { key: "received", label: "Đã vào kho" },
          { key: "rejected", label: "Đã từ chối" },
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
              background: statusFilter === tab.key ? "#0f172a" : "transparent",
              color: statusFilter === tab.key ? "#ffffff" : "#64748b",
              transition: "all 0.15s",
            }}
            onClick={() => setStatusFilter(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <ErrorNotice error={error} retry={loadIntakes} />

      {loading && <Loading />}

      {!loading && intakesPage && (
        <>
          {filteredItems.length === 0 ? (
            <EmptyState title="Không có đề nghị tiếp nhận nào" icon="document">
              <p>
                {statusFilter === "pending"
                  ? "Hiện không có ai gửi đề nghị mang đồ đến trạm này."
                  : "Chưa có đề nghị nào phù hợp với bộ lọc hiện tại."}
              </p>
            </EmptyState>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "1rem" }}>
              {filteredItems.map((intake) => (
                <div
                  key={intake.id}
                  style={{
                    background: "#ffffff",
                    border: "1px solid #e2e8f0",
                    borderRadius: 12,
                    padding: "1.25rem",
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.75rem",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: "0.75rem", color: "#64748b", fontWeight: 600 }}>
                      MÃ: #{intake.id.slice(0, 8)}
                    </span>
                    <Badge value={intake.status} />
                  </div>

                  <div>
                    <h3 style={{ margin: 0, fontSize: "1.0625rem", fontWeight: 700, color: "#0f172a" }}>
                      Món đồ #{intake.itemId.slice(0, 8)}
                    </h3>
                    <div style={{ fontSize: "0.8125rem", color: "#64748b", marginTop: "0.25rem" }}>
                      Gửi lúc: {formatDate(intake.createdAt, true)}
                    </div>
                  </div>

                  {intake.stale && (
                    <Notice tone="warning">
                      Món đồ đã có thay đổi hoặc đã bị xóa. Đề nghị này không còn hiệu lực.
                    </Notice>
                  )}

                  {intake.decisionNote && (
                    <div
                      style={{
                        fontSize: "0.8125rem",
                        background: "#f8fafc",
                        padding: "0.5rem 0.75rem",
                        borderRadius: 6,
                        border: "1px solid #e2e8f0",
                        color: "#334155",
                      }}
                    >
                      <strong>Ghi chú trạm:</strong> {intake.decisionNote}
                    </div>
                  )}

                  <div style={{ marginTop: "auto", paddingTop: "0.75rem", borderTop: "1px solid #f1f5f9", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="button button-secondary button-small"
                      onClick={() => handleViewIntakeDetail(intake)}
                      disabled={loadingPreviewId === intake.id}
                    >
                      {loadingPreviewId === intake.id ? "Đang tải…" : "Chi tiết món đồ"}
                    </button>

                    {intake.status === "pending" && !intake.stale && (
                      <>
                        <button
                          type="button"
                          className="button button-small"
                          onClick={() => setActiveModal({ type: "receive", intake })}
                        >
                          <Icon name="check" size={15} />
                          <span>Tiếp nhận</span>
                        </button>
                        <button
                          type="button"
                          className="button button-secondary button-small danger-text"
                          onClick={() => setActiveModal({ type: "reject", intake })}
                        >
                          <span>Từ chối</span>
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          <Pagination page={page} totalPages={intakesPage.totalPages} />
        </>
      )}

      {/* Modal Xử lý tiếp nhận hoặc từ chối */}
      {activeModal && (
        <div className="hub-modal-backdrop" onClick={() => !modalSubmitting && setActiveModal(null)}>
          <div className="hub-modal-card" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#0f172a" }}>
                {activeModal.type === "receive"
                  ? "Xác nhận tiếp nhận hiện vật vào kho"
                  : "Từ chối tiếp nhận đề nghị"}
              </h2>
              <button
                type="button"
                style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b" }}
                onClick={() => setActiveModal(null)}
                disabled={modalSubmitting}
              >
                ✕
              </button>
            </div>

            {modalLoadingItem ? (
              <Loading />
            ) : (
              modalItem && (
                <div
                  style={{
                    display: "flex",
                    gap: "0.875rem",
                    padding: "0.75rem",
                    background: "#f8fafc",
                    borderRadius: 8,
                    border: "1px solid #e2e8f0",
                  }}
                >
                  {modalItem.images?.[0] && (
                    <div style={{ width: 64, height: 64, borderRadius: 6, overflow: "hidden", background: "#000", flexShrink: 0 }}>
                      <img
                        src={modalItem.images[0].url}
                        alt=""
                        style={{ width: "100%", height: "100%", objectFit: "cover", filter: "blur(4px)" }}
                      />
                    </div>
                  )}
                  <div>
                    <h4 style={{ margin: 0, fontSize: "0.9375rem", fontWeight: 700, color: "#0f172a" }}>
                      {modalItem.title}
                    </h4>
                    <p style={{ margin: "0.25rem 0 0", fontSize: "0.8125rem", color: "#64748b" }}>
                      Khu vực nhặt: {modalItem.foundArea}
                    </p>
                  </div>
                </div>
              )
            )}

            {modalError && <Notice tone="warning">{modalError}</Notice>}

            <form onSubmit={handleDecisionSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              {activeModal.type === "receive" ? (
                <>
                  <label>
                    <span style={{ fontWeight: 600, fontSize: "0.875rem", color: "#334155" }}>
                      Ghi chú lưu kho / Vị trí ngăn tủ <span className="field-hint">(không bắt buộc)</span>
                    </span>
                    <input
                      type="text"
                      placeholder="Ví dụ: Tủ A - Ngăn 2, đã dán tem mã #..."
                      value={decisionNote}
                      maxLength={2000}
                      onChange={(e) => setDecisionNote(e.target.value)}
                      disabled={modalSubmitting}
                      style={{ marginTop: "0.25rem" }}
                    />
                  </label>

                  <label className="checkbox-field" style={{ alignItems: "flex-start", marginTop: "0.25rem" }}>
                    <input
                      type="checkbox"
                      required
                      checked={confirmedPhysical}
                      onChange={(e) => setConfirmedPhysical(e.target.checked)}
                      disabled={modalSubmitting}
                    />
                    <span style={{ fontSize: "0.875rem", color: "#1e293b", lineHeight: 1.4 }}>
                      Tôi xác nhận đã nhận hiện vật thực tế từ người mang đến và kiểm tra an toàn theo quy định trạm.
                    </span>
                  </label>
                </>
              ) : (
                <label>
                  <span style={{ fontWeight: 600, fontSize: "0.875rem", color: "#334155" }}>
                    Lý do từ chối tiếp nhận <span className="field-hint">(được gửi đến người gửi)</span>
                  </span>
                  <textarea
                    rows={3}
                    required
                    maxLength={2000}
                    placeholder="Nhập lý do (ví dụ: Kho hiện vật đã quá tải, hoặc đồ vật thuộc danh mục không nhận)..."
                    value={decisionNote}
                    onChange={(e) => setDecisionNote(e.target.value)}
                    disabled={modalSubmitting}
                    style={{ marginTop: "0.25rem" }}
                  />
                </label>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "0.5rem" }}>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setActiveModal(null)}
                  disabled={modalSubmitting}
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  className={`button${activeModal.type === "reject" ? " danger-bg" : ""}`}
                  style={
                    activeModal.type === "reject"
                      ? { background: "#dc2626", color: "#ffffff", border: "none" }
                      : undefined
                  }
                  disabled={modalSubmitting || (activeModal.type === "receive" && !confirmedPhysical)}
                >
                  {modalSubmitting
                    ? "Đang lưu..."
                    : activeModal.type === "receive"
                    ? "Xác nhận vào kho"
                    : "Xác nhận từ chối"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Chi tiết Đề nghị tiếp nhận & Hiện vật */}
      {previewIntakeItem && (
        <div className="hub-modal-backdrop" onClick={() => setPreviewIntakeItem(null)}>
          <div className="hub-modal-card" style={{ maxWidth: 680 }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#0f172a" }}>
                Chi tiết đề nghị tiếp nhận vào trạm
              </h3>
              <button
                type="button"
                style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", fontSize: "1.25rem", padding: "0.25rem" }}
                onClick={() => setPreviewIntakeItem(null)}
              >
                ✕
              </button>
            </div>

            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <Badge value={previewIntakeItem.intake.status} />
              <span style={{ fontSize: "0.8125rem", color: "#64748b", marginLeft: "auto" }}>
                Đề nghị: #{previewIntakeItem.intake.id.slice(0, 8)} · Món đồ: #{previewIntakeItem.item.id.slice(0, 8)}
              </span>
            </div>

            <h2 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0, color: "#0f172a" }}>
              {previewIntakeItem.item.title}
            </h2>

            <div>
              <h4 style={{ fontSize: "0.875rem", fontWeight: 600, color: "#475569", margin: "0 0 0.25rem" }}>
                Mô tả công khai
              </h4>
              <p style={{ background: "#f8fafc", padding: "0.75rem", borderRadius: 8, fontSize: "0.875rem", margin: 0, whiteSpace: "pre-wrap", border: "1px solid #e2e8f0" }}>
                {previewIntakeItem.item.publicDescription || "Không có mô tả chi tiết."}
              </p>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", fontSize: "0.875rem" }}>
              <div>
                <span style={{ color: "#64748b" }}>Khu vực nhặt:</span> <strong>{previewIntakeItem.item.foundArea}</strong>
              </div>
              <div>
                <span style={{ color: "#64748b" }}>Thời gian gửi đề nghị:</span> <strong>{formatDate(previewIntakeItem.intake.createdAt, true)}</strong>
              </div>
            </div>

            {previewIntakeItem.intake.decisionNote && (
              <div style={{ fontSize: "0.8125rem", background: "#f8fafc", padding: "0.5rem 0.75rem", borderRadius: 6, border: "1px solid #e2e8f0", color: "#334155" }}>
                <strong>Ghi chú trạm:</strong> {previewIntakeItem.intake.decisionNote}
              </div>
            )}

            {previewIntakeItem.item.images && previewIntakeItem.item.images.length > 0 && (
              <div>
                <h4 style={{ fontSize: "0.875rem", fontWeight: 600, color: "#475569", margin: "0 0 0.5rem" }}>
                  Hình ảnh hiện vật ({previewIntakeItem.item.images.length})
                </h4>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "0.75rem" }}>
                  {previewIntakeItem.item.images.map((img) => (
                    <div key={img.id} style={{ borderRadius: 8, overflow: "hidden", border: "1px solid #e2e8f0", background: "#f1f5f9" }}>
                      <img src={img.url} alt="" style={{ width: "100%", height: 110, objectFit: "cover", filter: "blur(4px)" }} />
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "0.5rem", borderTop: "1px solid #f1f5f9", paddingTop: "0.875rem" }}>
              <button type="button" className="button button-secondary" onClick={() => setPreviewIntakeItem(null)}>
                Đóng
              </button>
              {previewIntakeItem.intake.status === "pending" && !previewIntakeItem.intake.stale && (
                <>
                  <button
                    type="button"
                    className="button button-secondary danger-text"
                    onClick={() => {
                      const intake = previewIntakeItem.intake;
                      setPreviewIntakeItem(null);
                      setActiveModal({ type: "reject", intake });
                    }}
                  >
                    <span>Từ chối</span>
                  </button>
                  <button
                    type="button"
                    className="button"
                    onClick={() => {
                      const intake = previewIntakeItem.intake;
                      setPreviewIntakeItem(null);
                      setActiveModal({ type: "receive", intake });
                    }}
                  >
                    <Icon name="check" size={16} />
                    <span>Tiếp nhận vào kho</span>
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
