import { useEffect, useState } from "react";
import { fetchAdminUsers, toggleUserStatus, type AdminUser } from "../../lib/adminApi";
import { formatDate, type Page } from "../../lib/api";
import { type UserProfile } from "../../lib/auth";
import { ErrorNotice, Icon, Loading } from "../../components/ui";

export default function AdminUsers({ currentUser }: { currentUser: UserProfile }) {
  const [data, setData] = useState<Page<AdminUser> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [query, setQuery] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [page, setPage] = useState(1);
  const [actionUserId, setActionUserId] = useState<string | null>(null);

  const loadUsers = () => {
    setLoading(true);
    setError(null);
    fetchAdminUsers({ query: searchTerm, page, pageSize: 20 })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err : new Error("Chưa tải được danh sách người dùng.")))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadUsers();
  }, [searchTerm, page]);

  const handleToggleStatus = async (user: AdminUser) => {
    const isLocking = !user.disabledAt;
    const confirmMsg = isLocking
      ? `Bạn có chắc chắn muốn KHÓA tài khoản "${user.displayName}" (${user.email ?? "Không có email"}) không? Người dùng này sẽ không thể đăng nhập hoặc thao tác.`
      : `Bạn có muốn MỞ KHÓA tài khoản "${user.displayName}" không?`;

    if (!window.confirm(confirmMsg)) return;

    setActionUserId(user.id);
    try {
      const updated = await toggleUserStatus(user.id);
      setData((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          items: prev.items.map((u) => (u.id === user.id ? updated : u)),
        };
      });
    } catch (err) {
      alert(err instanceof Error ? err.message : "Thao tác không thành công.");
    } finally {
      setActionUserId(null);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: "1.75rem" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f172a", margin: "0 0 0.5rem" }}>
          Quản lý Người dùng
        </h1>
        <p style={{ color: "#64748b", margin: 0, fontSize: "0.9375rem" }}>
          Tra cứu thông tin, giám sát hoạt động và chuyển đổi trạng thái tài khoản người dùng hệ thống.
        </p>
      </div>

      <div className="admin-toolbar">
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
            placeholder="Tìm theo tên hiển thị hoặc email…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </form>
        {searchTerm && (
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setQuery("");
              setSearchTerm("");
              setPage(1);
            }}
          >
            Xóa tìm kiếm
          </button>
        )}
      </div>

      {error && <ErrorNotice error={error} retry={loadUsers} />}

      {loading ? (
        <Loading />
      ) : !data || data.items.length === 0 ? (
        <div className="admin-table-container" style={{ padding: "3rem", textAlign: "center", color: "#64748b" }}>
          Không tìm thấy người dùng nào phù hợp.
        </div>
      ) : (
        <div className="admin-table-container">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Người dùng</th>
                <th>Email</th>
                <th>Ngày tham gia</th>
                <th>Số tin đăng</th>
                <th>Trạng thái</th>
                <th style={{ textAlign: "right" }}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((u) => {
                const isCurrent = u.id === currentUser.id;
                const isDisabled = Boolean(u.disabledAt);
                return (
                  <tr key={u.id}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                        <span
                          style={{
                            width: 32,
                            height: 32,
                            borderRadius: "50%",
                            background: u.isAdmin ? "#1e293b" : "#e2e8f0",
                            color: u.isAdmin ? "#ffffff" : "#334155",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            fontWeight: 600,
                            fontSize: "0.8125rem",
                          }}
                        >
                          {u.displayName.charAt(0).toUpperCase()}
                        </span>
                        <div>
                          <strong style={{ display: "block", color: "#0f172a" }}>{u.displayName}</strong>
                          {u.isAdmin && (
                            <span
                              style={{
                                fontSize: "0.6875rem",
                                color: "#2563eb",
                                fontWeight: 600,
                                background: "#eff6ff",
                                padding: "0.1rem 0.35rem",
                                borderRadius: 4,
                              }}
                            >
                              Admin
                            </span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td style={{ color: "#475569" }}>{u.email ?? <span style={{ color: "#94a3b8" }}>Chưa có email</span>}</td>
                    <td style={{ color: "#64748b" }}>{formatDate(u.createdAt)}</td>
                    <td style={{ fontWeight: 600, color: "#334155" }}>{u.itemsCount}</td>
                    <td>
                      {isDisabled ? (
                        <span
                          style={{
                            display: "inline-block",
                            padding: "0.2rem 0.6rem",
                            borderRadius: "9999px",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                            background: "#fee2e2",
                            color: "#b91c1c",
                          }}
                        >
                          Đã bị khóa
                        </span>
                      ) : (
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
                          Hoạt động
                        </span>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {isCurrent ? (
                        <span style={{ fontSize: "0.8125rem", color: "#94a3b8", fontStyle: "italic" }}>
                          (Tài khoản của bạn)
                        </span>
                      ) : (
                        <button
                          type="button"
                          disabled={actionUserId === u.id}
                          className={`btn-sm ${isDisabled ? "btn-success" : "btn-danger"}`}
                          onClick={() => handleToggleStatus(u)}
                        >
                          {actionUserId === u.id
                            ? "Đang lưu…"
                            : isDisabled
                              ? "Mở khóa"
                              : "Khóa tài khoản"}
                        </button>
                      )}
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
    </div>
  );
}
