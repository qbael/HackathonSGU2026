import { useState, useEffect } from "react";
import {
  api,
  formatDate,
  write,
  type CustodyEvent,
  type Item,
  type Page,
} from "../../lib/api";
import { directReturnInput } from "../../lib/itemForm";
import { type UserProfile } from "../../lib/auth";
import { Badge, EmptyState, ErrorNotice, Icon, Loading, Notice, Pagination, SafetyNote } from "../../components/ui";

export default function HubInventory({
  user,
  selectedPointId,
}: {
  user: UserProfile;
  selectedPointId: string;
}) {
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [lifecycleFilter, setLifecycleFilter] = useState<"all" | "active" | "returned">("active");
  const [itemsPage, setItemsPage] = useState<Page<Item> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Modal Trao trả
  const [returnItem, setReturnItem] = useState<Item | null>(null);
  const [verificationNote, setVerificationNote] = useState("");
  const [confirmedHandover, setConfirmedHandover] = useState(false);
  const [returnBusy, setReturnBusy] = useState(false);
  const [returnError, setReturnError] = useState<string | null>(null);
  const [returnSuccess, setReturnSuccess] = useState<string | null>(null);

  // Modal Chi tiết hiện vật tại chỗ
  const [inspectItem, setInspectItem] = useState<Item | null>(null);

  const loadInventory = () => {
    if (!selectedPointId) return;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams({
      scope: "managed",
      pointId: selectedPointId,
      page: String(page),
      pageSize: "12",
    });
    if (appliedSearch.trim()) {
      params.set("q", appliedSearch.trim());
    }

    api<Page<Item>>(`/api/items?${params}`)
      .then((data) => setItemsPage(data))
      .catch((err) =>
        setError(
          err instanceof Error ? err : new Error("Không thể tải danh sách kho đồ."),
        ),
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    setPage(1);
  }, [selectedPointId, appliedSearch, lifecycleFilter]);

  useEffect(() => {
    loadInventory();
  }, [selectedPointId, page, appliedSearch]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setAppliedSearch(searchQuery);
  };

  const handleOpenReturnModal = (item: Item) => {
    setReturnItem(item);
    setVerificationNote("");
    setConfirmedHandover(false);
    setReturnError(null);
    setReturnSuccess(null);
  };

  const handleExecuteReturn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!returnItem) return;

    setReturnBusy(true);
    setReturnError(null);
    try {
      const payload = directReturnInput(
        returnItem.custody.kind,
        returnItem.rowVersion,
        verificationNote,
        confirmedHandover,
      );

      await write<CustodyEvent>(`/api/items/${returnItem.id}/return`, payload);
      setReturnSuccess(`Đã ghi nhận trao trả thành công món đồ "${returnItem.title}".`);
      loadInventory();
      setTimeout(() => {
        setReturnItem(null);
        setReturnSuccess(null);
      }, 1500);
    } catch (err) {
      setReturnError(err instanceof Error ? err.message : "Không thể thực hiện trao trả.");
    } finally {
      setReturnBusy(false);
    }
  };

  const filteredItems = itemsPage?.items.filter((item) => {
    if (lifecycleFilter === "all") return true;
    return item.lifecycle === lifecycleFilter;
  }) ?? [];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem" }}>
        <div>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f172a", margin: 0 }}>
            Kho đồ lưu giữ tại trạm
          </h1>
          <p style={{ color: "#64748b", marginTop: "0.25rem", fontSize: "0.9375rem" }}>
            Quản lý hiện vật đang được lưu trữ an toàn tại trạm và thực hiện thủ tục trao trả cho chủ sở hữu.
          </p>
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={loadInventory}
          disabled={loading}
        >
          <Icon name="refresh" size={16} />
          <span>Làm mới</span>
        </button>
      </div>

      {/* Thanh tìm kiếm & bộ lọc */}
      <div
        style={{
          display: "flex",
          gap: "1rem",
          alignItems: "center",
          flexWrap: "wrap",
          marginBottom: "1.25rem",
        }}
      >
        <form onSubmit={handleSearchSubmit} style={{ display: "flex", gap: "0.5rem", flex: 1, minWidth: 260 }}>
          <input
            type="search"
            placeholder="Tìm theo tên đồ vật, đặc điểm..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{ flex: 1, padding: "0.5rem 0.75rem", borderRadius: 8, border: "1px solid #cbd5e1" }}
          />
          <button type="submit" className="button button-secondary">
            Tìm
          </button>
          {appliedSearch && (
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                setSearchQuery("");
                setAppliedSearch("");
              }}
            >
              Xóa tìm
            </button>
          )}
        </form>

        <div
          style={{
            display: "flex",
            gap: "0.375rem",
            background: "#ffffff",
            padding: "0.375rem",
            borderRadius: 8,
            border: "1px solid #e2e8f0",
          }}
        >
          {[
            { key: "active", label: "Đang lưu giữ" },
            { key: "returned", label: "Đã trao trả" },
            { key: "all", label: "Tất cả" },
          ].map((tab) => (
            <button
              key={tab.key}
              type="button"
              style={{
                padding: "0.375rem 0.75rem",
                borderRadius: 6,
                border: "none",
                fontSize: "0.8125rem",
                fontWeight: 600,
                cursor: "pointer",
                background: lifecycleFilter === tab.key ? "#0f172a" : "transparent",
                color: lifecycleFilter === tab.key ? "#ffffff" : "#64748b",
              }}
              onClick={() => setLifecycleFilter(tab.key as any)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <ErrorNotice error={error} retry={loadInventory} />

      {loading && <Loading />}

      {!loading && itemsPage && (
        <>
          {filteredItems.length === 0 ? (
            <EmptyState title="Kho hiện vật trống" icon="grid">
              <p>
                {appliedSearch
                  ? `Không tìm thấy món đồ nào khớp với từ khóa "${appliedSearch}".`
                  : lifecycleFilter === "active"
                  ? "Hiện không có món đồ nào đang lưu giữ trong kho tại trạm này."
                  : "Không có món đồ nào trong danh mục này."}
              </p>
            </EmptyState>
          ) : (
            <div className="hub-inventory-grid">
              {filteredItems.map((item) => {
                const coverImage = item.images?.[0];
                const isReturned = item.lifecycle === "returned";

                return (
                  <article key={item.id} className="hub-inventory-card">
                    <div className="hub-item-thumb">
                      {coverImage ? (
                        <img src={coverImage.url} alt={item.title} loading="lazy" />
                      ) : (
                        <div style={{ color: "#64748b", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                          <Icon name="document" size={24} />
                          <span>Không có ảnh</span>
                        </div>
                      )}
                      <div className="hub-thumb-overlay">
                        <Badge value={item.lifecycle} />
                      </div>
                    </div>

                    <div className="hub-item-body">
                      <h3 className="hub-item-title">{item.title}</h3>

                      <div className="hub-item-meta">
                        <div>
                          <strong>Khu vực nhặt:</strong> {item.foundArea}
                        </div>
                        <div>
                          <strong>Nhập kho:</strong> {formatDate(item.createdAt, false)}
                        </div>
                        <div>
                          <strong>Mã món đồ:</strong> #{item.id.slice(0, 8)}
                        </div>
                      </div>

                      <div className="hub-item-actions">
                        <button
                          type="button"
                          className="button button-secondary button-small"
                          onClick={() => setInspectItem(item)}
                          style={{ flex: 1, textAlign: "center" }}
                        >
                          Xem chi tiết
                        </button>

                        {!isReturned && (
                          <button
                            type="button"
                            className="button button-small"
                            onClick={() => handleOpenReturnModal(item)}
                            title="Bàn giao đồ cho chủ sở hữu"
                          >
                            <Icon name="check" size={15} />
                            <span>Trao trả</span>
                          </button>
                        )}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}

          <Pagination page={page} totalPages={itemsPage.totalPages} />
        </>
      )}

      {/* Modal Trao trả cho chủ sở hữu */}
      {returnItem && (
        <div className="hub-modal-backdrop" onClick={() => !returnBusy && setReturnItem(null)}>
          <div className="hub-modal-card" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#0f172a" }}>
                Thủ tục Trao trả đồ cho chủ sở hữu
              </h2>
              <button
                type="button"
                style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b" }}
                onClick={() => setReturnItem(null)}
                disabled={returnBusy}
              >
                ✕
              </button>
            </div>

            <div
              style={{
                padding: "0.875rem",
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 8,
              }}
            >
              <h3 style={{ margin: "0 0 0.25rem", fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>
                {returnItem.title}
              </h3>
              <p style={{ margin: 0, fontSize: "0.8125rem", color: "#64748b" }}>
                Mã đồ vật: #{returnItem.id} · Nơi tìm thấy: {returnItem.foundArea}
              </p>
            </div>

            <SafetyNote />

            {returnError && <Notice tone="warning">{returnError}</Notice>}
            {returnSuccess && <Notice tone="success">{returnSuccess}</Notice>}

            <form onSubmit={handleExecuteReturn} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <label>
                <span style={{ fontWeight: 600, fontSize: "0.875rem", color: "#334155" }}>
                  Ghi chú xác minh danh tính người nhận <span style={{ color: "#e11d48" }}>* (bắt buộc tại Hub)</span>
                </span>
                <textarea
                  rows={4}
                  required
                  maxLength={2000}
                  placeholder="Ghi rõ thông tin đối chiếu thực tế (ví dụ: Đã kiểm tra CCCD số ... khớp họ tên, người nhận mở khóa màn hình đúng mật khẩu, số điện thoại liên hệ...)"
                  value={verificationNote}
                  onChange={(e) => setVerificationNote(e.target.value)}
                  disabled={returnBusy}
                  style={{ marginTop: "0.375rem" }}
                />
              </label>

              <label className="checkbox-field" style={{ alignItems: "flex-start" }}>
                <input
                  type="checkbox"
                  required
                  checked={confirmedHandover}
                  onChange={(e) => setConfirmedHandover(e.target.checked)}
                  disabled={returnBusy}
                />
                <span style={{ fontSize: "0.875rem", color: "#1e293b", lineHeight: 1.4 }}>
                  Tôi đã trực tiếp đối chiếu danh tính, bằng chứng sở hữu và đã bàn giao hiện vật thực tế cho người nhận tại trạm.
                </span>
              </label>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "0.5rem" }}>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setReturnItem(null)}
                  disabled={returnBusy}
                >
                  Đóng
                </button>
                <button
                  type="submit"
                  className="button"
                  disabled={returnBusy || !confirmedHandover || !verificationNote.trim()}
                >
                  {returnBusy ? "Đang ghi nhận..." : "Xác nhận đã trao trả"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Chi tiết Hiện vật lưu kho */}
      {inspectItem && (
        <div className="hub-modal-backdrop" onClick={() => setInspectItem(null)}>
          <div className="hub-modal-card" style={{ maxWidth: 680 }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#0f172a" }}>
                Chi tiết hiện vật lưu kho
              </h3>
              <button
                type="button"
                style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", fontSize: "1.25rem", padding: "0.25rem" }}
                onClick={() => setInspectItem(null)}
              >
                ✕
              </button>
            </div>

            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <Badge value={inspectItem.lifecycle} />
              <span style={{ fontSize: "0.8125rem", color: "#64748b", marginLeft: "auto" }}>
                Mã đồ: #{inspectItem.id.slice(0, 8)}
              </span>
            </div>

            <h2 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0, color: "#0f172a" }}>
              {inspectItem.title}
            </h2>

            <div>
              <h4 style={{ fontSize: "0.875rem", fontWeight: 600, color: "#475569", margin: "0 0 0.25rem" }}>
                Mô tả công khai
              </h4>
              <p style={{ background: "#f8fafc", padding: "0.75rem", borderRadius: 8, fontSize: "0.875rem", margin: 0, whiteSpace: "pre-wrap", border: "1px solid #e2e8f0" }}>
                {inspectItem.publicDescription || "Không có mô tả chi tiết."}
              </p>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", fontSize: "0.875rem" }}>
              <div>
                <span style={{ color: "#64748b" }}>Khu vực nhặt:</span> <strong>{inspectItem.foundArea}</strong>
              </div>
              <div>
                <span style={{ color: "#64748b" }}>Ngày tạo bài:</span> <strong>{formatDate(inspectItem.createdAt, true)}</strong>
              </div>
            </div>

            {inspectItem.images && inspectItem.images.length > 0 && (
              <div>
                <h4 style={{ fontSize: "0.875rem", fontWeight: 600, color: "#475569", margin: "0 0 0.5rem" }}>
                  Hình ảnh hiện vật ({inspectItem.images.length})
                </h4>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "0.75rem" }}>
                  {inspectItem.images.map((img) => (
                    <div key={img.id} style={{ borderRadius: 8, overflow: "hidden", border: "1px solid #e2e8f0", background: "#f1f5f9" }}>
                      <img src={img.url} alt="" style={{ width: "100%", height: 110, objectFit: "cover", filter: "blur(4px)" }} />
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "0.5rem", borderTop: "1px solid #f1f5f9", paddingTop: "0.875rem" }}>
              <button type="button" className="button button-secondary" onClick={() => setInspectItem(null)}>
                Đóng
              </button>
              {inspectItem.lifecycle !== "returned" && (
                <button
                  type="button"
                  className="button"
                  onClick={() => {
                    const target = inspectItem;
                    setInspectItem(null);
                    handleOpenReturnModal(target);
                  }}
                >
                  <Icon name="check" size={16} />
                  <span>Tiến hành trao trả cho chủ</span>
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
