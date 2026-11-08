import { useEffect, useState, type ReactNode } from "react";
import { loadUser, logout, type UserProfile } from "./lib/auth";
import { useAction, useResource } from "./hooks/hooks";
import { Breadcrumb, EmptyState, ErrorNotice, Icon, Loading, useToast } from "./components/ui";
import SignIn from "./pages/SignIn";
import Profile from "./pages/Profile";
import SavedSearches from "./pages/SavedSearches";
import AdminLayout from "./pages/admin/AdminLayout";
import AdminDashboard from "./pages/admin/AdminDashboard";
import AdminUsers from "./pages/admin/AdminUsers";
import AdminItems from "./pages/admin/AdminItems";
import AdminHubs from "./pages/admin/AdminHubs";
import HubLayout, { type HubTab } from "./pages/hub/HubLayout";
import HubIntakes from "./pages/hub/HubIntakes";
import HubInventory from "./pages/hub/HubInventory";
import HubHistory from "./pages/hub/HubHistory";
import { Intakes, IntakeDetail } from "./pages/Intakes";
import { CustodyHistory, ReturnItem } from "./pages/Custody";
import { Home, Search, ItemDetail, Points, type SearchInput } from "./pages/Explore";
import { PostItem, ReviewImages } from "./pages/Posting";
import {
  ClaimItem,
  Requests,
  ClaimDetail,
  MyPosts,
  TransferItem,
  Messages,
} from "./pages/Recovery";
import { useNotifications } from "./hooks/useNotifications";
import type { SavedSearch } from "./lib/search";

export default function App() {
  const [path, setPath] = useState(() => window.location.pathname.replace(/\/$/, "") || "/");
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(path !== "/signin");
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [imageSearch, setImageSearch] = useState<SearchInput | null>(null);
  const [selectedHubPointId, setSelectedHubPointId] = useState<string>("");
  const [navKey, setNavKey] = useState(0);
  const action = useAction();
  const toast = useToast();

  const currentParams = new URLSearchParams(window.location.search);
  const activeConversationId =
    path === "/messages" ? currentParams.get("conversation") : null;
  const notifications = useNotifications(user, activeConversationId);
  const savedSearches = useResource<SavedSearch[]>(
    user ? "/api/saved-searches" : null,
  );
  const unreadSavedMatchesCount = (savedSearches.data ?? []).reduce(
    (sum, search) =>
      sum + search.matches.filter((match) => !match.readAt).length,
    0,
  );

  useEffect(() => {
    if (!user) return;
    const refresh = () => {
      if (document.visibilityState === "visible") savedSearches.reload();
    };
    const interval = window.setInterval(refresh, 60_000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [user, savedSearches.reload]);

  useEffect(() => {
    if (action.error) {
      toast.error(action.error.message);
    }
  }, [action.error]);

  useEffect(() => {
    if (user?.managedPoints?.length && !selectedHubPointId) {
      setSelectedHubPointId(user.managedPoints[0].id);
    }
  }, [user, selectedHubPointId]);

  useEffect(() => {
    const navigate = () => {
      const nextPath = window.location.pathname.replace(/\/$/, "") || "/";
      setPath(nextPath);
      setImageSearch(null);
      setNavKey((k) => k + 1);
      window.scrollTo(0, 0);
    };
    window.addEventListener("popstate", navigate);
    return () => window.removeEventListener("popstate", navigate);
  }, []);

  useEffect(() => {
    const handleLinkClick = (event: MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }

      const target = (event.target as HTMLElement).closest("a");
      if (!target || !(target instanceof HTMLAnchorElement)) return;

      if (target.target && target.target !== "_self") return;
      if (target.hasAttribute("download")) return;

      const href = target.getAttribute("href");
      if (!href || href.startsWith("#")) return;

      if (
        href.startsWith("http://") ||
        href.startsWith("https://") ||
        href.startsWith("mailto:") ||
        href.startsWith("tel:")
      ) {
        try {
          const url = new URL(href, window.location.origin);
          if (url.origin !== window.location.origin) return;
        } catch {
          return;
        }
      }

      const nextUrl = new URL(href, window.location.href);
      if (nextUrl.origin !== window.location.origin) return;

      if (
        nextUrl.pathname.startsWith("/api/") ||
        nextUrl.pathname.startsWith("/auth/")
      ) {
        return;
      }

      event.preventDefault();
      const nextPath = nextUrl.pathname.replace(/\/$/, "") || "/";
      const nextFullPath = nextUrl.pathname + nextUrl.search + nextUrl.hash;
      const currentFullPath =
        window.location.pathname + window.location.search + window.location.hash;

      if (nextFullPath !== currentFullPath) {
        window.history.pushState(null, "", nextFullPath);
      }
      setImageSearch(null);
      setPath(nextPath);
      setNavKey((k) => k + 1);
      window.scrollTo(0, 0);
    };

    document.addEventListener("click", handleLinkClick);
    return () => document.removeEventListener("click", handleLinkClick);
  }, [path]);

  useEffect(() => {
    if (path === "/signin") return;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);
    let active = true;
    if (!user) setLoading(true);
    setError(null);
    loadUser(controller.signal)
      .then((value) => {
        if (active) setUser(value);
      })
      .catch(() => {
        if (active && !user)
          setError(
            new Error(
              "Chưa kiểm tra được phiên đăng nhập. Hãy kiểm tra kết nối và thử lại.",
            ),
          );
      })
      .finally(() => {
        clearTimeout(timeout);
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt, path]);

  const itemRoute = path.match(
    /^\/items\/([\da-f-]{36})(?:\/(claim|review|transfer|edit|history|return))?$/i,
  );
  const claimRoute = path.match(/^\/claims\/([\da-f-]{36})$/i);
  const intakeRoute = path.match(/^\/intakes\/([\da-f-]{36})$/i);
  const titles: Record<string, string> = {
    "/": "Kết nối để tìm lại",
    "/search": "Tìm đồ thất lạc",
    "/saved-searches": "Tin tìm đang theo dõi",
    "/post": "Đăng tin nhặt được",
    "/requests": "Yêu cầu trao trả",
    "/messages": "Tin nhắn",
    "/posts": "Bài đăng của tôi",
    "/hubs": "Điểm tiếp nhận Findie Hub",
    "/intakes": "Theo dõi tiếp nhận",
    "/profile": "Hồ sơ cá nhân",
    "/admin": "Bảng điều khiển Quản trị",
    "/admin/users": "Quản lý Người dùng · Quản trị",
    "/admin/items": "Kiểm duyệt Tin & Ảnh · Quản trị",
    "/admin/hubs": "Quản lý Findie Hub · Quản trị",
    "/hub": "Không gian làm việc Hub",
    "/hub/intakes": "Bàn tiếp nhận · Findie Hub",
    "/hub/inventory": "Kho đồ lưu giữ · Findie Hub",
    "/hub/history": "Nhật ký lưu chuyển · Findie Hub",
  };
  useEffect(() => {
    if (path !== "/signin")
      document.title = `${titles[path] ?? "Thông tin trao trả"} · Findie`;
  }, [path]);

  if (path === "/signin") return <SignIn />;
  function protect(content: () => ReactNode) {
    if (loading) return <Loading />;
    if (error)
      return (
        <ErrorNotice
          error={error}
          retry={() => setAttempt((value) => value + 1)}
        />
      );
    if (!user)
      return (
        <EmptyState title="Đăng nhập để tiếp tục" icon="document">
          <p>
            Dùng tài khoản Google để bảo vệ quyền riêng tư và kết nối trao trả
            đồ.
          </p>
          <a
            className="button"
            href={`/signin?returnUrl=${encodeURIComponent(path + window.location.search)}`}
          >
            Tiếp tục với Findie
            <Icon name="arrow" size={17} />
          </a>
        </EmptyState>
      );
    return content();
  }
  let content: ReactNode;
  if (path === "/") content = <Home signedIn={Boolean(user)} onImageSearch={(input) => {
    const query = new URLSearchParams({ mode: "image" });
    if (input.text) query.set("q", input.text);
    for (const [key, value] of Object.entries(input.filters))
      if (value) query.set(key, value);
    window.history.pushState(null, "", `/search?${query}`);
    setImageSearch(input);
    setLoading(true);
    setPath("/search");
  }} />;
  else if (path === "/search") content = protect(() => <Search key={`${window.location.search}-${navKey}`} initialRequest={imageSearch} />);
  else if (path === "/saved-searches") content = protect(() => <SavedSearches searches={savedSearches} />);
  else if (path === "/post") content = protect(() => <PostItem />);
  else if (path === "/posts") content = protect(() => <MyPosts />);
  else if (path === "/requests")
    content = protect(() => (
      <Requests user={user!} onSeen={notifications.markRequestsSeen} />
    ));
  else if (path === "/messages")
    content = protect(() => (
      <Messages
        user={user!}
        unreadByConversation={notifications.unreadByConversation}
        onReadConversation={notifications.markConversationRead}
      />
    ));
  else if (path === "/hubs") content = protect(() => <Points />);
  else if (path === "/profile") content = protect(() => <Profile user={user!} onUpdate={setUser} />);
  else if (path === "/intakes") content = protect(() => <Intakes user={user!} />);
  else if (intakeRoute) content = protect(() => <IntakeDetail id={intakeRoute[1]} user={user!} />);
  else if (itemRoute) {
    const [, id, view] = itemRoute;
    content = protect(() =>
      view === "claim" ? (
        <ClaimItem id={id} />
      ) : view === "review" ? (
        <ReviewImages id={id} />
      ) : view === "transfer" ? (
        <TransferItem id={id} />
      ) : view === "edit" ? (
        <PostItem id={id} />
      ) : view === "history" ? (
        <CustodyHistory id={id} />
      ) : view === "return" ? (
        <ReturnItem id={id} />
      ) : (
        <ItemDetail id={id} />
      ),
    );
  } else if (claimRoute)
    content = protect(() => <ClaimDetail id={claimRoute[1]} user={user!} />);
  else if (path.startsWith("/admin"))
    content = protect(() => {
      if (!user?.isAdmin) {
        return (
          <EmptyState title="Không có quyền truy cập" icon="document">
            <p>Bạn cần tài khoản Quản trị viên (Super Admin) để truy cập khu vực này.</p>
            <a className="button" href="/">
              Về trang chủ
            </a>
          </EmptyState>
        );
      }
      const adminTab =
        path === "/admin/users"
          ? "users"
          : path === "/admin/items"
            ? "items"
            : path === "/admin/hubs"
              ? "hubs"
              : "dashboard";
      return (
        <AdminLayout
          activeTab={adminTab}
          user={user}
          onTabChange={(tab) => {
            const nextPath = tab === "dashboard" ? "/admin" : `/admin/${tab}`;
            window.history.pushState(null, "", nextPath);
            setPath(nextPath);
          }}
        >
          {adminTab === "dashboard" && (
            <AdminDashboard
              onNavigate={(tab) => {
                const nextPath = `/admin/${tab}`;
                window.history.pushState(null, "", nextPath);
                setPath(nextPath);
              }}
            />
          )}
          {adminTab === "users" && <AdminUsers currentUser={user} />}
          {adminTab === "items" && <AdminItems />}
          {adminTab === "hubs" && <AdminHubs />}
        </AdminLayout>
      );
    });
  else if (path.startsWith("/hub"))
    content = protect(() => {
      if (!user?.isStaff && !user?.isAdmin) {
        return (
          <EmptyState title="Không có quyền truy cập" icon="building">
            <p>Bạn cần tài khoản Nhân viên Findie Hub được phân công trực trạm để truy cập khu vực này.</p>
            <a className="button" href="/">
              Về trang chủ
            </a>
          </EmptyState>
        );
      }
      const activePointId =
        selectedHubPointId || (user.managedPoints?.[0]?.id ?? "");

      const hubTab: HubTab =
        path === "/hub/inventory"
          ? "inventory"
          : path === "/hub/history"
            ? "history"
            : "intakes";

      return (
        <HubLayout
          activeTab={hubTab}
          user={user}
          selectedPointId={activePointId}
          onPointChange={(newPointId) => setSelectedHubPointId(newPointId)}
          onTabChange={(tab) => {
            const nextPath = tab === "intakes" ? "/hub/intakes" : `/hub/${tab}`;
            window.history.pushState(null, "", nextPath);
            setPath(nextPath);
          }}
        >
          {hubTab === "intakes" && (
            <HubIntakes user={user} selectedPointId={activePointId} />
          )}
          {hubTab === "inventory" && (
            <HubInventory user={user} selectedPointId={activePointId} />
          )}
          {hubTab === "history" && (
            <HubHistory user={user} selectedPointId={activePointId} />
          )}
        </HubLayout>
      );
    });
  else
    content = (
      <EmptyState title="Không tìm thấy trang">
        <p>Đường dẫn có thể đã thay đổi.</p>
        <a className="button" href="/">
          Về trang chủ
        </a>
      </EmptyState>
    );

  const isAdminMode = path.startsWith("/admin");
  const isHubMode = path.startsWith("/hub");
  const isPortalMode = isAdminMode || isHubMode;

  const active =
    isAdminMode
      ? "admin"
      : isHubMode
        ? "hub"
        : path === "/search" ||
            path === "/saved-searches" ||
            path === "/" ||
            (itemRoute && !itemRoute[2])
        ? "search"
        : path === "/post" ||
            path === "/posts" ||
            itemRoute?.[2] === "edit" ||
            itemRoute?.[2] === "review" ||
            itemRoute?.[2] === "history" ||
            itemRoute?.[2] === "return" ||
            itemRoute?.[2] === "transfer"
          ? "posts"
          : path === "/requests" || claimRoute || itemRoute?.[2] === "claim"
            ? "requests"
            : path === "/messages"
              ? "messages"
              : "hubs";
  const hubNames = user?.isStaff ? (user.managedPoints ?? []).map((point) => point.name) : [];
  const hubDuty = hubNames.length
    ? `Trực trạm ${hubNames[0]}${hubNames.length > 1 ? ` +${hubNames.length - 1}` : ""}`
    : null;
  const currentHubStationName =
    user?.managedPoints?.find((p) => p.id === selectedHubPointId)?.name ??
    user?.managedPoints?.[0]?.name ??
    null;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Chuyển đến nội dung
      </a>

      {/* Header phân hệ Quản trị (Admin Portal) */}
      {isAdminMode ? (
        <header className="site-header portal-header portal-header-admin">
          <div className="header-inner">
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <a href="/" className="brand" aria-label="Findie — Trang chủ">
                findie<span>.</span>
              </a>
              <div className="portal-header-badge">
                <span className="tag-dot" />
                <span>Hệ thống Quản trị</span>
              </div>
            </div>
            <div className="header-actions">
              <a href="/" className="button button-secondary button-small" aria-label="Về trang người dùng">
                <Icon name="back" size={16} />
                <span>Về ứng dụng tìm đồ</span>
              </a>
              {user?.isStaff && (
                <a href="/hub" className="button button-secondary button-small">
                  <Icon name="building" size={16} />
                  <span>Khu vực Hub</span>
                </a>
              )}
              {user && (
                <details className="account-menu">
                  <summary aria-label={`Tài khoản ${user.displayName}`}>
                    <span className="avatar">
                      {user.displayName.charAt(0).toLocaleUpperCase("vi")}
                    </span>
                  </summary>
                  <div>
                    <strong>{user.displayName}</strong>
                    <span className="role-badge role-badge-admin">Super Admin</span>
                    <a href="/profile">Hồ sơ cá nhân</a>
                    <button
                      type="button"
                      disabled={action.busy}
                      onClick={() =>
                        void action.run(async () => {
                          await logout(AbortSignal.timeout(6000));
                          window.location.assign("/");
                        })
                      }
                    >
                      {action.busy ? "Đang đăng xuất…" : "Đăng xuất"}
                    </button>
                  </div>
                </details>
              )}
            </div>
          </div>
        </header>
      ) : isHubMode ? (
        /* Header phân hệ Findie Hub (Hub Portal) */
        <header className="site-header portal-header portal-header-hub">
          <div className="header-inner">
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <a href="/" className="brand" aria-label="Findie — Trang chủ">
                findie<span>.</span>
              </a>
              <div className="portal-header-badge">
                <span className="tag-dot" />
                <span>Findie Hub Workspace</span>
              </div>
              {currentHubStationName && (
                <span className="portal-header-station">
                  <Icon name="building" size={15} />
                  <span>Trực: <strong>{currentHubStationName}</strong></span>
                </span>
              )}
            </div>
            <div className="header-actions">
              <a href="/" className="button button-secondary button-small" aria-label="Về trang người dùng">
                <Icon name="back" size={16} />
                <span>Về ứng dụng tìm đồ</span>
              </a>
              {user?.isAdmin && (
                <a href="/admin" className="button button-secondary button-small">
                  <Icon name="shield" size={16} />
                  <span>Trang Quản trị</span>
                </a>
              )}
              {user && (
                <details className="account-menu">
                  <summary aria-label={`Tài khoản ${user.displayName}`}>
                    <span className="avatar">
                      {user.displayName.charAt(0).toLocaleUpperCase("vi")}
                    </span>
                  </summary>
                  <div>
                    <strong>{user.displayName}</strong>
                    <span className="role-badge role-badge-staff">Nhân viên Hub</span>
                    <a href="/profile">Hồ sơ cá nhân</a>
                    <button
                      type="button"
                      disabled={action.busy}
                      onClick={() =>
                        void action.run(async () => {
                          await logout(AbortSignal.timeout(6000));
                          window.location.assign("/");
                        })
                      }
                    >
                      {action.busy ? "Đang đăng xuất…" : "Đăng xuất"}
                    </button>
                  </div>
                </details>
              )}
            </div>
          </div>
        </header>
      ) : (
        /* Header giao diện người dùng cộng đồng */
        <header className="site-header">
          <div className="header-inner">
            <a href="/" className="brand" aria-label="Findie — Trang chủ">
              findie<span>.</span>
            </a>
            <nav className="main-nav" aria-label="Điều hướng chính">
              {[
                { key: "search", href: "/", label: "Tìm đồ", count: 0 },
                { key: "posts", href: "/posts", label: "Bài đăng của tôi", count: 0 },
                {
                  key: "requests",
                  href: "/requests",
                  label: "Yêu cầu trao trả",
                  count: notifications.pendingRequestsCount,
                },
                {
                  key: "messages",
                  href: "/messages",
                  label: "Tin nhắn",
                  count: notifications.unreadMessagesCount,
                },
              ].map(({ key, href, label, count }) => (
                <a
                  key={key}
                  href={href}
                  aria-current={active === key ? "page" : undefined}
                >
                  <span>{label}</span>
                  {count > 0 && (
                    <span
                      className="nav-badge"
                      aria-label={`${count} thông báo mới`}
                    >
                      {count > 99 ? "99+" : count}
                    </span>
                  )}
                </a>
              ))}
            </nav>
            <div className="header-actions">
              {user?.isStaff ? (
                <a
                  className="button button-secondary button-small"
                  href="/hub"
                  aria-label={hubDuty ? `Không gian Hub: ${hubDuty}` : "Không gian Hub"}
                >
                  <Icon name="building" size={16} />
                  <span>{hubDuty ?? "Không gian Hub"}</span>
                </a>
              ) : (
                <a
                  className="hub-link"
                  href="/hubs"
                  aria-label="Điểm tiếp nhận Findie Hub"
                  aria-current={active === "hubs" ? "page" : undefined}
                >
                  <Icon name="building" size={18} />
                  <span>Findie Hub</span>
                </a>
              )}
              <a href="/post" className="button button-small" aria-label="Đăng tin">
                <Icon name="plus" size={17} />
                <span>Đăng tin</span>
              </a>
              {user?.isAdmin && (
                <a
                  href="/admin"
                  className="button button-secondary button-small"
                >
                  <Icon name="shield" size={17} />
                  <span>Trang Quản trị</span>
                </a>
              )}
              {user ? (
                <details className="account-menu">
                  <summary aria-label={`Tài khoản ${user.displayName}`}>
                    <span className="avatar">
                      {user.displayName.charAt(0).toLocaleUpperCase("vi")}
                      {notifications.pendingRequestsCount +
                        notifications.unreadMessagesCount >
                        0 && <span className="avatar-dot" />}
                    </span>
                  </summary>
                  <div>
                    <strong>{user.displayName}</strong>
                    {user.isAdmin && (
                      <span className="role-badge role-badge-admin">Super Admin</span>
                    )}
                    {user.isStaff && (
                      <span className="role-badge role-badge-staff">
                        Nhân viên Findie Hub
                      </span>
                    )}
                    {user.isStaff && (
                      <a href="/hub" style={{ fontWeight: 600 }}>
                        Không gian làm việc Hub
                      </a>
                    )}
                    <a href="/profile">Hồ sơ cá nhân</a>
                    <a href="/saved-searches">
                      {unreadSavedMatchesCount > 0
                        ? `Tin tìm đang theo dõi (${unreadSavedMatchesCount} mới)`
                        : "Tin tìm đang theo dõi"}
                    </a>
                    <a href="/posts">Bài đăng của tôi</a>
                    <a
                      href="/requests"
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <span>Yêu cầu trao trả</span>
                      {notifications.pendingRequestsCount > 0 && (
                        <span className="unread-badge">
                          {notifications.pendingRequestsCount}
                        </span>
                      )}
                    </a>
                    <a
                      href="/messages"
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <span>Tin nhắn</span>
                      {notifications.unreadMessagesCount > 0 && (
                        <span className="unread-badge">
                          {notifications.unreadMessagesCount}
                        </span>
                      )}
                    </a>
                    <a href="/posts?scope=managed">Đồ đang quản lý</a>
                    <a href="/intakes">Theo dõi tiếp nhận</a>
                    <button
                      type="button"
                      disabled={action.busy}
                      onClick={() =>
                        void action.run(async () => {
                          await logout(AbortSignal.timeout(6000));
                          window.location.assign("/");
                        })
                      }
                    >
                      {action.busy ? "Đang đăng xuất…" : "Đăng xuất"}
                    </button>
                  </div>
                </details>
              ) : (
                <a
                  className="signin-link"
                  href={`/signin?returnUrl=${encodeURIComponent(path + window.location.search)}`}
                >
                  Đăng nhập
                </a>
              )}
            </div>
          </div>
        </header>
      )}

      <main
        id="main"
        className={`main-content${path === "/" ? " main-home" : ""}${isAdminMode ? " main-admin" : ""}${isHubMode ? " main-hub" : ""}`}
      >
        {path !== "/" && !isPortalMode && (
          <Breadcrumb current={titles[path] ?? "Thông tin trao trả"} />
        )}
        {content}
      </main>

      {!isPortalMode && (
        <footer className="site-footer">
          <div className="footer-inner">
            <div>
              <a href="/" className="brand">
                findie<span>.</span>
              </a>
              <p>Kết nối để tìm lại. Trao trả bằng sự tử tế.</p>
            </div>
            <div className="footer-links">
              <a href="/">Tìm đồ thất lạc</a>
              <a href="/post">Đăng tin nhặt được</a>
              <a href="/hubs">Mạng lưới Findie Hub</a>
            </div>
            <span className="footer-note">
              <Icon name="shield" size={16} />
              Vì một cộng đồng tin cậy
            </span>
          </div>
        </footer>
      )}
    </div>
  );
}
