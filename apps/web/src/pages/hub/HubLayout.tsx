import { type ReactNode, useEffect, useState } from "react";
import { Icon } from "../../components/ui";
import { type UserProfile, type ManagedPoint } from "../../lib/auth";
import { api, type Point } from "../../lib/api";

export type HubTab = "intakes" | "inventory" | "history";

export default function HubLayout({
  activeTab,
  onTabChange,
  user,
  selectedPointId,
  onPointChange,
  children,
}: {
  activeTab: HubTab;
  onTabChange: (tab: HubTab) => void;
  user: UserProfile;
  selectedPointId: string;
  onPointChange: (pointId: string) => void;
  children: ReactNode;
}) {
  const [pointDetails, setPointDetails] = useState<Point | null>(null);

  // Danh sách các trạm nhân viên phụ trách
  const managedPoints: ManagedPoint[] = user.managedPoints ?? [];
  const currentStationName =
    managedPoints.find((p) => p.id === selectedPointId)?.name ??
    pointDetails?.name ??
    (selectedPointId ? `Trạm #${selectedPointId.slice(0, 8)}` : "Chưa chọn trạm");

  // Tải chi tiết trạm (địa chỉ, hướng dẫn) khi selectedPointId thay đổi
  useEffect(() => {
    if (!selectedPointId) {
      setPointDetails(null);
      return;
    }
    const controller = new AbortController();
    api<Point>(`/api/reception-points/${selectedPointId}`, { signal: controller.signal })
      .then((point) => setPointDetails(point))
      .catch(() => setPointDetails(null));

    return () => controller.abort();
  }, [selectedPointId]);

  const navItems: { tab: HubTab; label: string; icon: "document" | "grid" | "refresh" }[] = [
    { tab: "intakes", label: "Đề nghị tiếp nhận", icon: "document" },
    { tab: "inventory", label: "Kho đồ tại trạm", icon: "grid" },
    { tab: "history", label: "Lịch sử bàn giao", icon: "refresh" },
  ];

  return (
    <div className="hub-shell">
      <aside className="hub-sidebar">
        <div className="hub-brand-tag">
          <span className="hub-dot" />
          <span>Findie Hub Portal</span>
        </div>

        {/* Trình chọn trạm (Hub Selector) */}
        <div className="hub-selector-card">
          <div className="hub-selector-label">
            <Icon name="building" size={15} />
            <span>Trạm trực làm việc</span>
          </div>

          {managedPoints.length > 1 ? (
            <div>
              <select
                className="hub-station-select"
                value={selectedPointId}
                onChange={(e) => onPointChange(e.target.value)}
                aria-label="Chọn trạm đang làm việc"
              >
                {managedPoints.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div className="hub-selector-name">{currentStationName}</div>
          )}

          {pointDetails?.publicAddress && (
            <div className="hub-selector-address">
              📍 {pointDetails.publicAddress}
            </div>
          )}
        </div>

        {/* Menu nghiệp vụ */}
        <nav className="hub-nav" aria-label="Điều hướng không gian làm việc Findie Hub">
          {navItems.map((item) => (
            <button
              key={item.tab}
              type="button"
              className={`hub-nav-item${activeTab === item.tab ? " active" : ""}`}
              onClick={() => onTabChange(item.tab)}
            >
              <Icon name={item.icon} size={18} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        {/* Footer nhân sự */}
        <div className="hub-nav-footer">
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1rem" }}>
            <span
              style={{
                width: 34,
                height: 34,
                borderRadius: "50%",
                background: "#0f172a",
                color: "#ffffff",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 600,
                fontSize: "0.875rem",
              }}
            >
              {user.displayName.charAt(0).toUpperCase()}
            </span>
            <div style={{ overflow: "hidden" }}>
              <div
                style={{
                  fontWeight: 600,
                  fontSize: "0.875rem",
                  color: "#0f172a",
                  whiteSpace: "nowrap",
                  textOverflow: "ellipsis",
                  overflow: "hidden",
                }}
              >
                {user.displayName}
              </div>
              <span
                style={{
                  fontSize: "0.75rem",
                  color: "#0f766e",
                  fontWeight: 600,
                  background: "#e6f4f2",
                  padding: "0.1rem 0.4rem",
                  borderRadius: 4,
                }}
              >
                {user.isStaff ? "Nhân viên Hub" : "Quản trị viên"}
              </span>
            </div>
          </div>
          <a href="/" className="hub-nav-item" style={{ color: "#64748b" }}>
            <Icon name="back" size={17} />
            <span>Về ứng dụng tìm đồ</span>
          </a>
        </div>
      </aside>

      <div className="hub-main">{children}</div>
    </div>
  );
}
