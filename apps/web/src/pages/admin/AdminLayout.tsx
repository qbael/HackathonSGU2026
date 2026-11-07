import { type ReactNode } from "react";
import { Icon } from "../../components/ui";
import { type UserProfile } from "../../lib/auth";

type AdminTab = "dashboard" | "users" | "items" | "hubs";

export default function AdminLayout({
  activeTab,
  onTabChange,
  user,
  children,
}: {
  activeTab: AdminTab;
  onTabChange: (tab: AdminTab) => void;
  user: UserProfile;
  children: ReactNode;
}) {
  const navItems: { tab: AdminTab; label: string; icon: "grid" | "users" | "document" | "building" }[] = [
    { tab: "dashboard", label: "Tổng quan", icon: "grid" },
    { tab: "users", label: "Quản lý Người dùng", icon: "users" },
    { tab: "items", label: "Kiểm duyệt Tin & Ảnh", icon: "document" },
    { tab: "hubs", label: "Mạng lưới Findie Hub", icon: "building" },
  ];

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-brand-tag">
          <span className="tag-dot" />
          <span>Findie Admin</span>
        </div>

        <nav className="admin-nav" aria-label="Điều hướng trang quản trị">
          {navItems.map((item) => (
            <button
              key={item.tab}
              type="button"
              className={`admin-nav-item${activeTab === item.tab ? " active" : ""}`}
              onClick={() => onTabChange(item.tab)}
            >
              <Icon name={item.icon} size={18} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="admin-nav-footer">
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
                  color: "#2563eb",
                  fontWeight: 600,
                  background: "#dbeafe",
                  padding: "0.1rem 0.4rem",
                  borderRadius: 4,
                }}
              >
                Super Admin
              </span>
            </div>
          </div>
          <a href="/" className="admin-nav-item" style={{ color: "#64748b" }}>
            <Icon name="back" size={17} />
            <span>Về ứng dụng</span>
          </a>
        </div>
      </aside>

      <div className="admin-main">{children}</div>
    </div>
  );
}
