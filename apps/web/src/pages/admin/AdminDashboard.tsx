import { useEffect, useState } from "react";
import { fetchAdminOverview, type AdminOverview } from "../../lib/adminApi";
import { ErrorNotice, Icon, Loading, Notice } from "../../components/ui";

export default function AdminDashboard({
  onNavigate,
}: {
  onNavigate: (tab: "users" | "items" | "hubs") => void;
}) {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const loadData = () => {
    setLoading(true);
    setError(null);
    fetchAdminOverview()
      .then(setOverview)
      .catch((err) => setError(err instanceof Error ? err : new Error("Chưa tải được số liệu tổng quan.")))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadData();
  }, []);

  if (loading) return <Loading />;
  if (error) return <ErrorNotice error={error} retry={loadData} />;
  if (!overview) return null;

  return (
    <div>
      <div style={{ marginBottom: "1.75rem" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700, color: "#0f172a", margin: "0 0 0.5rem" }}>
          Bảng điều khiển Quản trị viên
        </h1>
        <p style={{ color: "#64748b", margin: 0, fontSize: "0.9375rem" }}>
          Giám sát tình trạng hệ thống Findie, người dùng, tin đăng và mạng lưới trạm tiếp nhận.
        </p>
      </div>

      <Notice tone="info">
        <strong>Nguyên tắc vận hành:</strong> Findie cam kết bảo vệ quyền riêng tư tuyệt đối — không lưu trữ ảnh gốc
        và không phân xử tranh chấp quyền sở hữu. Quản trị viên thực hiện can thiệp kỹ thuật (ẩn bài, thu hồi ảnh lộ PII,
        quản lý trạm Hub) để đảm bảo môi trường cộng đồng an toàn và tin cậy.
      </Notice>

      <div className="admin-metrics-grid" style={{ marginTop: "1.5rem" }}>
        <div className="metric-card">
          <div>
            <div className="metric-card-top">
              <span>TIN ĐĂNG TÌM ĐỒ</span>
              <div className="metric-card-icon">
                <Icon name="box" size={18} />
              </div>
            </div>
            <div className="metric-value">{overview.totalItems}</div>
          </div>
          <div className="metric-sub">
            <span style={{ color: "#16a34a", fontWeight: 600 }}>{overview.activeItems}</span> đang tìm chủ ·{" "}
            <span style={{ color: "#2563eb", fontWeight: 600 }}>{overview.returnedItems}</span> đã trao trả ·{" "}
            <span style={{ color: "#dc2626", fontWeight: 600 }}>{overview.hiddenItems}</span> bị ẩn
          </div>
        </div>

        <div className="metric-card">
          <div>
            <div className="metric-card-top">
              <span>NGƯỜI DÙNG</span>
              <div className="metric-card-icon">
                <Icon name="users" size={18} />
              </div>
            </div>
            <div className="metric-value">{overview.totalUsers}</div>
          </div>
          <div className="metric-sub">
            <span style={{ color: "#16a34a", fontWeight: 600 }}>{overview.activeUsers}</span> hoạt động ·{" "}
            <span style={{ color: "#dc2626", fontWeight: 600 }}>{overview.disabledUsers}</span> bị khóa
          </div>
        </div>

        <div className="metric-card">
          <div>
            <div className="metric-card-top">
              <span>MẠNG LƯỚI FINDIE HUB</span>
              <div className="metric-card-icon">
                <Icon name="building" size={18} />
              </div>
            </div>
            <div className="metric-value">
              {overview.activeHubs} <span style={{ fontSize: "1rem", color: "#64748b", fontWeight: 400 }}>/ {overview.totalHubs}</span>
            </div>
          </div>
          <div className="metric-sub">Trạm tiếp nhận đang mở trên toàn hệ thống</div>
        </div>

        <div className="metric-card">
          <div>
            <div className="metric-card-top">
              <span>TRAO TRẢ THÀNH CÔNG</span>
              <div className="metric-card-icon">
                <Icon name="check" size={18} />
              </div>
            </div>
            <div className="metric-value" style={{ color: "#16a34a" }}>
              {overview.totalHandovers}
            </div>
          </div>
          <div className="metric-sub">{overview.totalCustodyEvents} lượt chuyển giao vật phẩm đã ghi nhận</div>
        </div>
      </div>

      <div style={{ marginTop: "2rem" }}>
        <h2 style={{ fontSize: "1.125rem", fontWeight: 600, color: "#0f172a", marginBottom: "1rem" }}>
          Lối tắt tác vụ nhanh
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem" }}>
          <div
            className="metric-card"
            style={{ cursor: "pointer", transition: "transform 0.15s ease", borderLeft: "4px solid #2563eb" }}
            onClick={() => onNavigate("items")}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: "1rem", color: "#0f172a", marginBottom: "0.25rem" }}>
                Kiểm duyệt Tin & Ảnh lộ PII
              </div>
              <p style={{ fontSize: "0.875rem", color: "#64748b", margin: 0 }}>
                Tra cứu danh sách bài viết, kiểm tra ảnh đã che mờ của AI, tạm ẩn bài vi phạm hoặc thu hồi ảnh.
              </p>
            </div>
            <div style={{ marginTop: "1rem", color: "#2563eb", fontSize: "0.875rem", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.25rem" }}>
              Xem danh sách tin <Icon name="arrow" size={14} />
            </div>
          </div>

          <div
            className="metric-card"
            style={{ cursor: "pointer", transition: "transform 0.15s ease", borderLeft: "4px solid #10b981" }}
            onClick={() => onNavigate("users")}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: "1rem", color: "#0f172a", marginBottom: "0.25rem" }}>
                Quản lý Người dùng
              </div>
              <p style={{ fontSize: "0.875rem", color: "#64748b", margin: 0 }}>
                Tìm kiếm tài khoản, kiểm tra lịch sử tham gia và thực hiện khóa / mở khóa tài khoản vi phạm.
              </p>
            </div>
            <div style={{ marginTop: "1rem", color: "#10b981", fontSize: "0.875rem", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.25rem" }}>
              Xem người dùng <Icon name="arrow" size={14} />
            </div>
          </div>

          <div
            className="metric-card"
            style={{ cursor: "pointer", transition: "transform 0.15s ease", borderLeft: "4px solid #8b5cf6" }}
            onClick={() => onNavigate("hubs")}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: "1rem", color: "#0f172a", marginBottom: "0.25rem" }}>
                Quản trị Mạng lưới Hub
              </div>
              <p style={{ fontSize: "0.875rem", color: "#64748b", margin: 0 }}>
                Khởi tạo điểm tiếp nhận mới, đóng/mở trạm và gán quyền nhân sự tiếp nhận/trao trả cho Hub.
              </p>
            </div>
            <div style={{ marginTop: "1rem", color: "#8b5cf6", fontSize: "0.875rem", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.25rem" }}>
              Xem các trạm Hub <Icon name="arrow" size={14} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
