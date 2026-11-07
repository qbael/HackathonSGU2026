import { useEffect, useState } from "react";
import {
  fetchAdminPoints,
  createAdminPoint,
  togglePointActive,
  fetchPointStaff,
  assignPointStaff,
  revokePointStaff,
  type AdminPoint,
  type AdminStaff,
} from "../../lib/adminApi";
import { formatDate } from "../../lib/api";
import { ConfirmModal, ErrorNotice, Icon, Loading, Notice, useToast } from "../../components/ui";

export default function AdminHubs() {
  const toast = useToast();
  const [points, setPoints] = useState<AdminPoint[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    title: string;
    message: string;
    danger?: boolean;
    onConfirm: () => Promise<void>;
  } | null>(null);

  // Modal thêm trạm mới
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createAddress, setCreateAddress] = useState("");
  const [createDirections, setCreateDirections] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Modal quản lý nhân viên trạm
  const [selectedPoint, setSelectedPoint] = useState<AdminPoint | null>(null);
  const [staffList, setStaffList] = useState<AdminStaff[] | null>(null);
  const [staffLoading, setStaffLoading] = useState(false);
  const [staffError, setStaffError] = useState<Error | null>(null);

  // Form thêm nhân viên
  const [assignEmail, setAssignEmail] = useState("");
  const [assignCanReceive, setAssignCanReceive] = useState(true);
  const [assignCanReturn, setAssignCanReturn] = useState(true);
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);

  const [togglingPointId, setTogglingPointId] = useState<string | null>(null);

  const loadPoints = () => {
    setLoading(true);
    setError(null);
    fetchAdminPoints()
      .then(setPoints)
      .catch((err) => setError(err instanceof Error ? err : new Error("Chưa tải được danh sách điểm tiếp nhận.")))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadPoints();
  }, []);

  const handleTogglePoint = (point: AdminPoint) => {
    const isDeactivating = point.active;
    setConfirmDialog({
      title: isDeactivating ? "Tạm đóng trạm tiếp nhận" : "Mở lại hoạt động trạm",
      message: isDeactivating
        ? `Tạm đóng trạm "${point.name}"? Người dùng sẽ không thể chọn trạm này làm nơi tiếp nhận mới.`
        : `Mở lại hoạt động cho trạm "${point.name}"?`,
      danger: isDeactivating,
      onConfirm: async () => {
        setTogglingPointId(point.id);
        try {
          const updated = await togglePointActive(point.id);
          setPoints((prev) => prev?.map((p) => (p.id === point.id ? updated : p)) ?? null);
          toast.success(isDeactivating ? `Đã tạm đóng trạm "${point.name}".` : `Đã mở lại hoạt động trạm "${point.name}".`);
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Không thể thay đổi trạng thái trạm.");
        } finally {
          setTogglingPointId(null);
          setConfirmDialog(null);
        }
      },
    });
  };

  const handleCreatePoint = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createName.trim() || !createAddress.trim()) {
      setCreateError("Vui lòng điền tên trạm và địa chỉ công khai.");
      return;
    }

    setCreateBusy(true);
    setCreateError(null);
    try {
      const created = await createAdminPoint({
        name: createName.trim(),
        publicAddress: createAddress.trim(),
        directions: createDirections.trim() || undefined,
      });
      setPoints((prev) => (prev ? [created, ...prev] : [created]));
      setShowCreateModal(false);
      setCreateName("");
      setCreateAddress("");
      setCreateDirections("");
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Không thể tạo trạm mới.");
    } finally {
      setCreateBusy(false);
    }
  };

  const openStaffModal = (point: AdminPoint) => {
    setSelectedPoint(point);
    setStaffList(null);
    setStaffLoading(true);
    setStaffError(null);
    setAssignEmail("");
    setAssignCanReceive(true);
    setAssignCanReturn(true);
    setAssignError(null);

    fetchPointStaff(point.id)
      .then(setStaffList)
      .catch((err) => setStaffError(err instanceof Error ? err : new Error("Chưa tải được danh sách nhân sự.")))
      .finally(() => setStaffLoading(false));
  };

  const handleAssignStaff = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedPoint) return;
    const trimmedEmail = assignEmail.trim();
    if (!trimmedEmail) {
      setAssignError("Vui lòng nhập email nhân viên.");
      return;
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[a-zA-Z]{2,}$/;
    if (!emailRegex.test(trimmedEmail)) {
      setAssignError("Định dạng email không hợp lệ. Vui lòng kiểm tra lại địa chỉ email.");
      return;
    }
    if (trimmedEmail.endsWith(".con")) {
      setAssignError("Đuôi email có thể bị gõ nhầm '.con'. Vui lòng kiểm tra lại địa chỉ email (ví dụ: .com).");
      return;
    }
    if (!assignCanReceive && !assignCanReturn) {
      setAssignError("Nhân viên phải có ít nhất quyền Tiếp nhận hoặc Trao trả.");
      return;
    }

    setAssignBusy(true);
    setAssignError(null);
    try {
      const assigned = await assignPointStaff(selectedPoint.id, {
        userEmail: trimmedEmail,
        canReceive: assignCanReceive,
        canReturn: assignCanReturn,
      });
      setStaffList((prev) => {
        if (!prev) return [assigned];
        const exists = prev.some((s) => s.userId === assigned.userId);
        return exists ? prev.map((s) => (s.userId === assigned.userId ? assigned : s)) : [assigned, ...prev];
      });
      setAssignEmail("");
      // Cập nhật số lượng staff ở danh sách points
      setPoints((prev) =>
        prev?.map((p) =>
          p.id === selectedPoint.id ? { ...p, staffCount: p.staffCount + 1 } : p,
        ) ?? null,
      );
    } catch (err) {
      setAssignError(err instanceof Error ? err.message : "Không thể gán quyền nhân viên.");
    } finally {
      setAssignBusy(false);
    }
  };

  const handleRevokeStaff = (staff: AdminStaff) => {
    if (!selectedPoint) return;
    setConfirmDialog({
      title: "Thu hồi quyền nhân sự",
      message: `Thu hồi quyền nhân sự của "${staff.displayName}" (${staff.email ?? ""}) tại trạm này?`,
      danger: true,
      onConfirm: async () => {
        try {
          await revokePointStaff(selectedPoint.id, staff.userId);
          setStaffList((prev) =>
            prev?.map((s) =>
              s.userId === staff.userId ? { ...s, revokedAt: new Date().toISOString() } : s,
            ) ?? null,
          );
          setPoints((prev) =>
            prev?.map((p) =>
              p.id === selectedPoint.id ? { ...p, staffCount: Math.max(0, p.staffCount - 1) } : p,
            ) ?? null,
          );
          toast.success(`Đã thu hồi quyền của "${staff.displayName}".`);
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Thu hồi quyền thất bại.");
        } finally {
          setConfirmDialog(null);
        }
      },
    });
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.75rem", flexWrap: "wrap", gap: "1rem" }}>
        <div>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f172a", margin: "0 0 0.5rem" }}>
            Mạng lưới Điểm tiếp nhận Findie Hub
          </h1>
          <p style={{ color: "#64748b", margin: 0, fontSize: "0.9375rem" }}>
            Quản trị các trạm trung chuyển đồ thất lạc vật lý và phân quyền nhân viên phụ trách trạm.
          </p>
        </div>
        <button
          type="button"
          className="button button-small"
          onClick={() => setShowCreateModal(true)}
        >
          <Icon name="plus" size={16} />
          <span>Thêm trạm Hub mới</span>
        </button>
      </div>

      {error && <ErrorNotice error={error} retry={loadPoints} />}

      {loading ? (
        <Loading />
      ) : !points || points.length === 0 ? (
        <div className="admin-table-container" style={{ padding: "3rem", textAlign: "center", color: "#64748b" }}>
          Chưa có điểm tiếp nhận nào trong hệ thống.
        </div>
      ) : (
        <div className="admin-table-container">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Tên trạm Findie Hub</th>
                <th>Địa chỉ & Chỉ dẫn</th>
                <th>Nhân sự</th>
                <th>Đồ đang giữ</th>
                <th>Trạng thái</th>
                <th>Ngày tạo</th>
                <th style={{ textAlign: "right" }}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.id}>
                  <td>
                    <strong style={{ display: "block", color: "#0f172a", fontSize: "0.9375rem" }}>{p.name}</strong>
                    <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>ID: {p.id.slice(0, 8)}…</span>
                  </td>
                  <td>
                    <div style={{ color: "#334155" }}>{p.publicAddress}</div>
                    {p.directions && (
                      <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "0.15rem" }}>
                        <em>{p.directions}</em>
                      </div>
                    )}
                  </td>
                  <td>
                    <span style={{ fontWeight: 600, color: "#0f172a" }}>{p.staffCount}</span> nhân viên
                  </td>
                  <td>
                    <span style={{ fontWeight: 600, color: "#0f172a" }}>{p.itemsCount}</span> món đồ
                  </td>
                  <td>
                    {p.active ? (
                      <span
                        style={{
                          display: "inline-block",
                          padding: "0.2rem 0.6rem",
                          borderRadius: "9999px",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                          background: "#dcfce7",
                          color: "#15803d",
                        }}
                      >
                        Đang mở
                      </span>
                    ) : (
                      <span
                        style={{
                          display: "inline-block",
                          padding: "0.2rem 0.6rem",
                          borderRadius: "9999px",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                          background: "#f1f5f9",
                          color: "#64748b",
                        }}
                      >
                        Tạm đóng
                      </span>
                    )}
                  </td>
                  <td style={{ color: "#64748b" }}>{formatDate(p.createdAt)}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button
                      type="button"
                      className="btn-sm"
                      style={{ background: "#eff6ff", border: "1px solid #bfdbfe", color: "#1d4ed8", marginRight: "0.5rem" }}
                      onClick={() => openStaffModal(p)}
                    >
                      Nhân viên ({p.staffCount})
                    </button>
                    <button
                      type="button"
                      disabled={togglingPointId === p.id}
                      className={`btn-sm ${p.active ? "btn-warning" : "btn-success"}`}
                      onClick={() => handleTogglePoint(p)}
                    >
                      {togglingPointId === p.id ? "…" : p.active ? "Tạm đóng" : "Mở trạm"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal Tạo Hub mới */}
      {showCreateModal && (
        <div className="admin-modal-backdrop" onClick={() => setShowCreateModal(false)}>
          <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
            <div className="admin-modal-header">
              <h3>Khởi tạo Điểm tiếp nhận Hub mới</h3>
              <button
                type="button"
                className="text-button"
                onClick={() => setShowCreateModal(false)}
                style={{ padding: "0.25rem" }}
              >
                <Icon name="close" size={20} />
              </button>
            </div>

            <form onSubmit={handleCreatePoint}>
              <div className="admin-modal-body">
                {createError && (
                  <div style={{ marginBottom: "1rem" }}>
                    <Notice tone="error">{createError}</Notice>
                  </div>
                )}

                <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                  <div>
                    <label style={{ display: "block", fontSize: "0.875rem", fontWeight: 600, color: "#334155", marginBottom: "0.35rem" }}>
                      Tên điểm tiếp nhận *
                    </label>
                    <input
                      type="text"
                      required
                      placeholder="Ví dụ: Findie Hub Quận 1 - SGU"
                      value={createName}
                      onChange={(e) => setCreateName(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "0.625rem",
                        border: "1px solid #cbd5e1",
                        borderRadius: 8,
                        fontSize: "0.875rem",
                      }}
                    />
                  </div>

                  <div>
                    <label style={{ display: "block", fontSize: "0.875rem", fontWeight: 600, color: "#334155", marginBottom: "0.35rem" }}>
                      Địa chỉ công khai *
                    </label>
                    <input
                      type="text"
                      required
                      placeholder="Ví dụ: 273 An Dương Vương, Phường 3, Quận 5, TP.HCM"
                      value={createAddress}
                      onChange={(e) => setCreateAddress(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "0.625rem",
                        border: "1px solid #cbd5e1",
                        borderRadius: 8,
                        fontSize: "0.875rem",
                      }}
                    />
                  </div>

                  <div>
                    <label style={{ display: "block", fontSize: "0.875rem", fontWeight: 600, color: "#334155", marginBottom: "0.35rem" }}>
                      Chỉ dẫn đường đi / Vị trí nhận diện (tùy chọn)
                    </label>
                    <textarea
                      rows={3}
                      placeholder="Ví dụ: Bàn trực an ninh sảnh chính, đối diện thang máy."
                      value={createDirections}
                      onChange={(e) => setCreateDirections(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "0.625rem",
                        border: "1px solid #cbd5e1",
                        borderRadius: 8,
                        fontSize: "0.875rem",
                      }}
                    />
                  </div>
                </div>
              </div>

              <div className="admin-modal-footer">
                <button
                  type="button"
                  className="button button-outline"
                  onClick={() => setShowCreateModal(false)}
                  disabled={createBusy}
                >
                  Hủy
                </button>
                <button type="submit" className="button" disabled={createBusy}>
                  {createBusy ? "Đang tạo…" : "Tạo điểm tiếp nhận"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Quản lý nhân viên trạm */}
      {selectedPoint && (
        <div className="admin-modal-backdrop" onClick={() => setSelectedPoint(null)}>
          <div className="admin-modal" style={{ maxWidth: 700 }} onClick={(e) => e.stopPropagation()}>
            <div className="admin-modal-header">
              <div>
                <h3 style={{ margin: 0 }}>Nhân viên trạm: {selectedPoint.name}</h3>
                <span style={{ fontSize: "0.8125rem", color: "#64748b" }}>{selectedPoint.publicAddress}</span>
              </div>
              <button
                type="button"
                className="text-button"
                onClick={() => setSelectedPoint(null)}
                style={{ padding: "0.25rem" }}
              >
                <Icon name="close" size={20} />
              </button>
            </div>

            <div className="admin-modal-body">
              {/* Form gán quyền nhân viên */}
              <div
                style={{
                  background: "#f8fafc",
                  border: "1px solid #e2e8f0",
                  borderRadius: 10,
                  padding: "1rem",
                  marginBottom: "1.5rem",
                }}
              >
                <h4 style={{ margin: "0 0 0.75rem", fontSize: "0.875rem", fontWeight: 600, color: "#1e293b" }}>
                  Cấp quyền nhân viên mới cho Hub này
                </h4>

                {assignError && (
                  <div style={{ marginBottom: "0.75rem" }}>
                    <Notice tone="error">{assignError}</Notice>
                  </div>
                )}

                <form onSubmit={handleAssignStaff}>
                  <div style={{ display: "flex", gap: "0.75rem", marginBottom: "0.75rem", flexWrap: "wrap" }}>
                    <input
                      type="email"
                      required
                      placeholder="Nhập email tài khoản nhân viên…"
                      value={assignEmail}
                      onChange={(e) => setAssignEmail(e.target.value)}
                      style={{
                        flex: 1,
                        minWidth: 240,
                        padding: "0.5rem 0.75rem",
                        border: "1px solid #cbd5e1",
                        borderRadius: 6,
                        fontSize: "0.875rem",
                      }}
                    />
                    <button type="submit" className="button button-small" disabled={assignBusy}>
                      {assignBusy ? "Đang gán…" : "Gán quyền"}
                    </button>
                  </div>

                  <div style={{ display: "flex", gap: "1.5rem", fontSize: "0.8125rem", color: "#334155" }}>
                    <label style={{ display: "flex", alignItems: "center", gap: "0.375rem", cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={assignCanReceive}
                        onChange={(e) => setAssignCanReceive(e.target.checked)}
                      />
                      <span>Quyền tiếp nhận vật phẩm (can_receive)</span>
                    </label>
                    <label style={{ display: "flex", alignItems: "center", gap: "0.375rem", cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={assignCanReturn}
                        onChange={(e) => setAssignCanReturn(e.target.checked)}
                      />
                      <span>Quyền trao trả vật phẩm (can_return)</span>
                    </label>
                  </div>
                </form>
              </div>

              {/* Danh sách nhân viên */}
              <h4 style={{ margin: "0 0 0.75rem", fontSize: "0.875rem", fontWeight: 600, color: "#1e293b" }}>
                Danh sách nhân viên phụ trách
              </h4>

              {staffError && <ErrorNotice error={staffError} />}

              {staffLoading ? (
                <Loading />
              ) : !staffList || staffList.length === 0 ? (
                <p style={{ color: "#94a3b8", fontStyle: "italic", fontSize: "0.875rem", textAlign: "center", padding: "1rem" }}>
                  Chưa có nhân viên nào được gán quyền tại Hub này.
                </p>
              ) : (
                <div style={{ border: "1px solid #e2e8f0", borderRadius: 8, overflow: "hidden" }}>
                  <table className="admin-table">
                    <thead>
                      <tr>
                        <th>Nhân viên</th>
                        <th>Email</th>
                        <th>Quyền hạn</th>
                        <th>Trạng thái</th>
                        <th style={{ textAlign: "right" }}>Thao tác</th>
                      </tr>
                    </thead>
                    <tbody>
                      {staffList.map((s) => {
                        const isRevoked = Boolean(s.revokedAt);
                        return (
                          <tr key={s.userId}>
                            <td>
                              <strong style={{ color: "#0f172a" }}>{s.displayName}</strong>
                            </td>
                            <td style={{ color: "#475569" }}>{s.email ?? "—"}</td>
                            <td>
                              <div style={{ display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                                {s.canReceive && (
                                  <span style={{ fontSize: "0.6875rem", background: "#dbeafe", color: "#1d4ed8", padding: "0.1rem 0.4rem", borderRadius: 4, fontWeight: 500 }}>
                                    Tiếp nhận
                                  </span>
                                )}
                                {s.canReturn && (
                                  <span style={{ fontSize: "0.6875rem", background: "#fef3c7", color: "#92400e", padding: "0.1rem 0.4rem", borderRadius: 4, fontWeight: 500 }}>
                                    Trao trả
                                  </span>
                                )}
                              </div>
                            </td>
                            <td>
                              {isRevoked ? (
                                <span style={{ fontSize: "0.75rem", color: "#94a3b8", fontWeight: 500 }}>
                                  Đã thu hồi ({formatDate(s.revokedAt)})
                                </span>
                              ) : (
                                <span style={{ fontSize: "0.75rem", color: "#16a34a", fontWeight: 600 }}>
                                  Đang phụ trách
                                </span>
                              )}
                            </td>
                            <td style={{ textAlign: "right" }}>
                              {!isRevoked && (
                                <button
                                  type="button"
                                  className="btn-sm btn-danger"
                                  onClick={() => handleRevokeStaff(s)}
                                >
                                  Thu hồi
                                </button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="admin-modal-footer">
              <button type="button" className="button button-outline" onClick={() => setSelectedPoint(null)}>
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
