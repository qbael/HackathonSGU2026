import { useEffect, useState } from "react";
import {
  fetchAdminItems,
  setPublicationState,
  retireAdminImage,
  type AdminItem,
  type AdminItemImage,
} from "../../lib/adminApi";
import { formatDate, type Page } from "../../lib/api";
import { Badge, ConfirmModal, ErrorNotice, Icon, Loading, useToast } from "../../components/ui";

export default function AdminItems() {
  const toast = useToast();
  const [data, setData] = useState<Page<AdminItem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [query, setQuery] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [publicationState, setPublicationStateFilter] = useState("");
  const [lifecycle, setLifecycleFilter] = useState("");
  const [page, setPage] = useState(1);
  const [inspectItem, setInspectItem] = useState<AdminItem | null>(null);
  const [actionItemId, setActionItemId] = useState<string | null>(null);
  const [actionImageId, setActionImageId] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    title: string;
    message: string;
    danger?: boolean;
    onConfirm: () => Promise<void>;
  } | null>(null);

  const loadItems = () => {
    setLoading(true);
    setError(null);
    fetchAdminItems({
      query: searchTerm,
      publicationState: publicationState || undefined,
      lifecycle: lifecycle || undefined,
      page,
      pageSize: 20,
    })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err : new Error("Chưa tải được danh sách tin đăng.")))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadItems();
  }, [searchTerm, publicationState, lifecycle, page]);

  const handleTogglePublication = (item: AdminItem) => {
    const nextState = item.publicationState === "hidden" ? "published" : "hidden";
    const isHiding = nextState === "hidden";
    setConfirmDialog({
      title: isHiding ? "Tạm ẩn bài đăng" : "Công khai bài đăng",
      message: isHiding
        ? `Tạm ẩn bài viết "${item.title}"? Bài viết sẽ không còn xuất hiện trên trang tìm kiếm công khai.`
        : `Công khai lại bài viết "${item.title}"?`,
      danger: isHiding,
      onConfirm: async () => {
        setActionItemId(item.id);
        try {
          await setPublicationState(item.id, nextState);
          setData((prev) => {
            if (!prev) return null;
            return {
              ...prev,
              items: prev.items.map((i) => (i.id === item.id ? { ...i, publicationState: nextState } : i)),
            };
          });
          if (inspectItem?.id === item.id) {
            setInspectItem((prev) => (prev ? { ...prev, publicationState: nextState } : null));
          }
          toast.success(isHiding ? `Đã tạm ẩn tin "${item.title}".` : `Đã công khai tin "${item.title}".`);
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Thao tác thay đổi trạng thái thất bại.");
        } finally {
          setActionItemId(null);
          setConfirmDialog(null);
        }
      },
    });
  };

  const handleRetireImage = (item: AdminItem, image: AdminItemImage) => {
    setConfirmDialog({
      title: "Thu hồi hình ảnh",
      message: "Bạn có chắc chắn muốn thu hồi ảnh này do phát hiện thông tin nhạy cảm / PII chưa che mờ hết không? Thao tác này không thể hoàn tác.",
      danger: true,
      onConfirm: async () => {
        setActionImageId(image.id);
        try {
          const result = await retireAdminImage(item.id, image.id);
          const updateImages = (imgs: AdminItemImage[]) =>
            imgs.map((img) => (img.id === image.id ? { ...img, retiredAt: result.retiredAt, reviewState: "retired" } : img));

          setData((prev) => {
            if (!prev) return null;
            return {
              ...prev,
              items: prev.items.map((i) => (i.id === item.id ? { ...i, images: updateImages(i.images) } : i)),
            };
          });

          if (inspectItem?.id === item.id) {
            setInspectItem((prev) => (prev ? { ...prev, images: updateImages(prev.images) } : null));
          }
          toast.success("Đã thu hồi hình ảnh vi phạm thành công.");
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Không thể thu hồi ảnh.");
        } finally {
          setActionImageId(null);
          setConfirmDialog(null);
        }
      },
    });
  };

  return (
    <div>
      <div style={{ marginBottom: "1.75rem" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f172a", margin: "0 0 0.5rem" }}>
          Kiểm duyệt Tin đăng & Hình ảnh
        </h1>
        <p style={{ color: "#64748b", margin: 0, fontSize: "0.9375rem" }}>
          Kiểm tra nội dung tin nhặt được, phát hiện nguy cơ lộ lọt PII trong hình ảnh đã AI che mờ, tạm ẩn bài hoặc thu hồi ảnh vi phạm.
        </p>
      </div>

      <div className="admin-toolbar">
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
          <form
            className="admin-search-box"
            onSubmit={(e) => {
              e.preventDefault();
              setPage(1);
              setSearchTerm(query.trim());
            }}
          >
            <Icon name="search" size={18} />
            <input
              type="search"
              placeholder="Tìm theo tiêu đề, mô tả, khu vực…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </form>

          <select
            className="admin-select"
            value={publicationState}
            onChange={(e) => {
              setPublicationStateFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="">Tất cả trạng thái xuất bản</option>
            <option value="published">Đang công khai</option>
            <option value="hidden">Đã tạm ẩn</option>
            <option value="draft">Bản nháp</option>
          </select>

          <select
            className="admin-select"
            value={lifecycle}
            onChange={(e) => {
              setLifecycleFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="">Tất cả vòng đời</option>
            <option value="active">Đang tìm chủ</option>
            <option value="returned">Đã trao trả</option>
            <option value="deleted">Đã xóa</option>
          </select>
        </div>

        {(searchTerm || publicationState || lifecycle) && (
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setQuery("");
              setSearchTerm("");
              setPublicationStateFilter("");
              setLifecycleFilter("");
              setPage(1);
            }}
          >
            Đặt lại bộ lọc
          </button>
        )}
      </div>

      {error && <ErrorNotice error={error} retry={loadItems} />}

      {loading ? (
        <Loading />
      ) : !data || data.items.length === 0 ? (
        <div className="admin-table-container" style={{ padding: "3rem", textAlign: "center", color: "#64748b" }}>
          Không tìm thấy bài viết nào phù hợp với bộ lọc.
        </div>
      ) : (
        <div className="admin-table-container">
          <table className="admin-table">
            <thead>
              <tr>
                <th style={{ width: 64 }}>Ảnh</th>
                <th>Tiêu đề & Khu vực</th>
                <th>Người đăng</th>
                <th>Vòng đời</th>
                <th>Xuất bản</th>
                <th>Ngày tạo</th>
                <th style={{ textAlign: "right" }}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => {
                const firstImage = item.images[0];
                const isHidden = item.publicationState === "hidden";
                return (
                  <tr key={item.id}>
                    <td>
                      {firstImage ? (
                        <img
                          src={firstImage.previewUrl}
                          alt={item.title}
                          style={{
                            width: 48,
                            height: 48,
                            borderRadius: 6,
                            objectFit: "cover",
                            border: "1px solid #e2e8f0",
                          }}
                        />
                      ) : (
                        <div
                          style={{
                            width: 48,
                            height: 48,
                            borderRadius: 6,
                            background: "#f1f5f9",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            color: "#94a3b8",
                          }}
                        >
                          <Icon name="box" size={20} />
                        </div>
                      )}
                    </td>
                    <td>
                      <strong
                        style={{ display: "block", color: "#0f172a", cursor: "pointer" }}
                        onClick={() => setInspectItem(item)}
                      >
                        {item.title}
                      </strong>
                      <span style={{ fontSize: "0.8125rem", color: "#64748b" }}>
                        <Icon name="pin" size={13} /> {item.foundArea}
                        {item.images.length > 0 && ` · ${item.images.length} ảnh`}
                      </span>
                    </td>
                    <td>
                      <div style={{ color: "#1e293b", fontWeight: 500 }}>{item.authorDisplayName}</div>
                      <div style={{ fontSize: "0.75rem", color: "#64748b" }}>{item.authorEmail ?? "—"}</div>
                    </td>
                    <td>
                      <Badge value={item.lifecycle} />
                    </td>
                    <td>
                      <Badge value={item.publicationState} />
                    </td>
                    <td style={{ color: "#64748b", whiteSpace: "nowrap" }}>{formatDate(item.createdAt)}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button
                        type="button"
                        className="btn-sm"
                        style={{ background: "#f1f5f9", border: "1px solid #cbd5e1", color: "#334155", marginRight: "0.5rem" }}
                        onClick={() => setInspectItem(item)}
                      >
                        Chi tiết
                      </button>
                      <button
                        type="button"
                        disabled={actionItemId === item.id}
                        className={`btn-sm ${isHidden ? "btn-success" : "btn-warning"}`}
                        onClick={() => handleTogglePublication(item)}
                      >
                        {actionItemId === item.id ? "…" : isHidden ? "Hiện lại" : "Tạm ẩn"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div className="admin-pagination">
            <span>Trang {page}</span>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                type="button"
                className="btn-sm"
                style={{ background: "#ffffff", border: "1px solid #cbd5e1", color: "#334155" }}
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Trang trước
              </button>
              <button
                type="button"
                className="btn-sm"
                style={{ background: "#ffffff", border: "1px solid #cbd5e1", color: "#334155" }}
                disabled={!data.hasMore}
                onClick={() => setPage((p) => p + 1)}
              >
                Trang sau
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Kiểm duyệt chi tiết bài đăng & Ảnh */}
      {inspectItem && (
        <div className="admin-modal-backdrop" onClick={() => setInspectItem(null)}>
          <div className="admin-modal" style={{ maxWidth: 750 }} onClick={(e) => e.stopPropagation()}>
            <div className="admin-modal-header">
              <h3>Chi tiết kiểm duyệt: {inspectItem.title}</h3>
              <button
                type="button"
                className="text-button"
                onClick={() => setInspectItem(null)}
                style={{ padding: "0.25rem" }}
              >
                <Icon name="close" size={20} />
              </button>
            </div>

            <div className="admin-modal-body">
              <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
                <Badge value={inspectItem.publicationState} />
                <Badge value={inspectItem.lifecycle} />
                <span style={{ fontSize: "0.8125rem", color: "#64748b", alignSelf: "center", marginLeft: "auto" }}>
                  Mã tin: {inspectItem.id}
                </span>
              </div>

              <div style={{ marginBottom: "1rem" }}>
                <h4 style={{ fontSize: "0.875rem", fontWeight: 600, color: "#475569", margin: "0 0 0.25rem" }}>
                  Mô tả công khai
                </h4>
                <p style={{ background: "#f8fafc", padding: "0.75rem", borderRadius: 8, fontSize: "0.875rem", margin: 0, whiteSpace: "pre-wrap" }}>
                  {inspectItem.publicDescription}
                </p>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.25rem", fontSize: "0.875rem" }}>
                <div>
                  <span style={{ color: "#64748b" }}>Khu vực nhặt được:</span> <strong>{inspectItem.foundArea}</strong>
                </div>
                <div>
                  <span style={{ color: "#64748b" }}>Người đăng:</span>{" "}
                  <strong>{inspectItem.authorDisplayName}</strong> ({inspectItem.authorEmail ?? "Không có email"})
                </div>
                <div>
                  <span style={{ color: "#64748b" }}>Nơi giữ hiện tại:</span>{" "}
                  <strong>
                    {inspectItem.custodyKind === "point"
                      ? `Hub: ${inspectItem.holderPointName ?? inspectItem.holderPointId}`
                      : inspectItem.custodyKind === "person"
                        ? "Người nhặt đang giữ"
                        : "Bên thứ ba"}
                  </strong>
                </div>
                <div>
                  <span style={{ color: "#64748b" }}>Ngày đăng:</span> <strong>{formatDate(inspectItem.createdAt, true)}</strong>
                </div>
              </div>

              <div>
                <h4 style={{ fontSize: "0.875rem", fontWeight: 600, color: "#475569", margin: "0 0 0.5rem" }}>
                  Hình ảnh đã qua xử lý AI ({inspectItem.images.length})
                </h4>
                {inspectItem.images.length === 0 ? (
                  <p style={{ color: "#94a3b8", fontSize: "0.875rem", fontStyle: "italic" }}>
                    Bài đăng này không đính kèm hình ảnh.
                  </p>
                ) : (
                  <div className="admin-images-grid">
                    {inspectItem.images.map((img) => {
                      const isRetired = Boolean(img.retiredAt);
                      return (
                        <div key={img.id} className="admin-image-card">
                          <img src={img.previewUrl} alt={`Vị trí ${img.position}`} />
                          <div className="image-meta">
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                              <strong>Vị trí #{img.position}</strong>
                              {isRetired ? (
                                <span style={{ color: "#dc2626", fontWeight: 600 }}>Đã thu hồi</span>
                              ) : (
                                <Badge value={img.reviewState} />
                              )}
                            </div>
                            <div style={{ fontSize: "0.6875rem", color: "#64748b" }}>
                              Model: {img.redactionModelId || "qwen3-vl:4b-instruct"}
                            </div>
                            {!isRetired ? (
                              <button
                                type="button"
                                disabled={actionImageId === img.id}
                                className="btn-sm btn-danger"
                                style={{ marginTop: "0.25rem", width: "100%" }}
                                onClick={() => handleRetireImage(inspectItem, img)}
                              >
                                {actionImageId === img.id ? "Đang xử lý…" : "Thu hồi (Lộ PII)"}
                              </button>
                            ) : (
                              <div style={{ fontSize: "0.6875rem", color: "#94a3b8" }}>
                                Thu hồi: {formatDate(img.retiredAt)}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            <div className="admin-modal-footer">
              <button
                type="button"
                className={`button ${inspectItem.publicationState === "hidden" ? "button-outline" : "button-danger"}`}
                onClick={() => handleTogglePublication(inspectItem)}
                disabled={actionItemId === inspectItem.id}
              >
                {inspectItem.publicationState === "hidden" ? "Công khai lại bài này" : "Tạm ẩn bài này"}
              </button>
              <button type="button" className="button button-outline" onClick={() => setInspectItem(null)}>
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmDialog && (
        <ConfirmModal
          open={Boolean(confirmDialog)}
          title={confirmDialog.title}
          message={confirmDialog.message}
          danger={confirmDialog.danger}
          onConfirm={confirmDialog.onConfirm}
          onCancel={() => setConfirmDialog(null)}
        />
      )}
    </div>
  );
}
