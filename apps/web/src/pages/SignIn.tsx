import { useEffect, useState } from "react";
import { loadUser, logout, resolveReturnUrl, type UserProfile } from "../lib/auth";
import { readSystemStatus } from "../lib/status";
import { safeReturnUrl } from "../lib/api";
import identityShield from "../assets/login/identity-shield.svg";
import protectionShield from "../assets/login/protection-shield.svg";
import chevronRight from "../assets/login/chevron-right.svg";
import google from "../assets/login/google.svg";

export default function SignIn() {
  const returnUrl = safeReturnUrl(
    new URLSearchParams(window.location.search).get("returnUrl"),
  );
  const [loading, setLoading] = useState(true);
  const [enabled, setEnabled] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [user, setUser] = useState<UserProfile | null>(null);

  useEffect(() => {
    document.title = "Đăng nhập · Findie";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);
    let active = true;
    setLoading(true);
    setEnabled(false);
    setError("");

    async function checkSession() {
      try {
        const profile = await loadUser(controller.signal);
        if (!active) return;
        setUser(profile);
        if (profile) return;
        const response = await fetch("/api/system/status", {
          signal: controller.signal,
          credentials: "same-origin",
        });
        if (!response.ok)
          throw new Error(
            "Chưa kết nối được dịch vụ đăng nhập. Vui lòng thử lại.",
          );
        const status = readSystemStatus(await response.json());
        if (active) setEnabled(status.features.authentication);
      } catch (cause) {
        if (active)
          setError(
            cause instanceof Error && cause.name === "AbortError"
              ? "Dịch vụ đăng nhập phản hồi quá lâu. Vui lòng thử lại."
              : "Chưa kiểm tra được phiên đăng nhập. Hãy kiểm tra kết nối và thử lại.",
          );
      } finally {
        clearTimeout(timeout);
        if (active) setLoading(false);
      }
    }

    void checkSession();
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  async function handleLogout() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);
    setLoading(true);
    setError("");
    try {
      await logout(controller.signal);
      setAttempt((value) => value + 1);
    } catch (cause) {
      setError(
        cause instanceof Error && cause.name !== "AbortError"
          ? cause.message
          : "Đăng xuất chưa hoàn tất trong thời gian chờ. Hãy thử lại.",
      );
    } finally {
      clearTimeout(timeout);
      setLoading(false);
    }
  }

  const providerClass =
    "flex min-h-11 w-full items-center justify-between gap-3 rounded-lg border border-solid border-outline/60 bg-white px-4 py-3 font-login text-sm font-semibold leading-5 tracking-[0.14px] text-ink no-underline transition-colors hover:border-primary hover:bg-protection focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-outline/60 disabled:hover:bg-white";
  const providerContent = (
    <>
      <span className="flex items-center gap-3 text-left">
        <img src={google} alt="" className="block shrink-0" />
        <span>
          {loading
            ? "Đang kiểm tra phiên đăng nhập…"
            : "Tiếp tục với Tài khoản Google"}
        </span>
      </span>
      <img src={chevronRight} alt="" className="block shrink-0" />
    </>
  );

  return (
    <main className="flex min-h-svh w-full items-center justify-center bg-canvas px-4 py-14 font-login text-ink">
      <div className="flex w-full max-w-[520px] flex-col gap-4">
        <a
          href="/"
          className="brand self-center mb-5"
          aria-label="Findie — Trang chủ"
        >
          findie<span>.</span>
        </a>
        <section
          aria-labelledby="login-title"
          aria-busy={loading}
          className="relative flex w-full flex-col gap-6 overflow-hidden rounded-xl border border-solid border-outline/40 bg-white p-6 shadow-[0px_1px_3px_0px_rgba(15,118,110,0.04),0px_1px_2px_-1px_rgba(0,0,0,0.05)] sm:p-8"
        >
          <div
            aria-hidden="true"
            className="absolute inset-x-0 top-0 h-1 bg-linear-to-r from-brand via-primary to-[#fd6b36]"
          />

          <div className="flex flex-col items-center gap-1 text-center">
            <div className="flex w-12 items-center justify-center rounded-full bg-primary/10 py-2">
              <img src={identityShield} alt="" className="block shrink-0" />
            </div>
            <h1
              id="login-title"
              className="m-0 pt-2 text-xl font-semibold leading-7 tracking-[-0.5px]"
            >
              {user
                ? "Bạn đã đăng nhập Findie"
                : "Đăng nhập để xác thực tiếp tục"}
            </h1>
            <p className="m-0 text-sm leading-5 text-muted">
              Bước bảo vệ cộng đồng từ hệ sinh thái{" "}
              <span className="font-semibold text-brand">findie.</span>
            </p>
          </div>

          <div className="flex items-start gap-3 rounded-lg border border-solid border-[#99f6e4]/70 bg-protection p-[14px]">
            <img src={protectionShield} alt="" className="block shrink-0" />
            <p className="m-0 min-w-0 text-sm leading-[22.75px] text-muted">
              Để bảo vệ quyền riêng tư và ngăn ngừa mạo danh nhận đồ của người
              khác, vui lòng đăng nhập tài khoản trước khi tiếp tục gửi yêu cầu
              đối chiếu.
            </p>
          </div>

          <div className="flex flex-col gap-3">
            {user ? (
              <>
                <p className="m-0 wrap-anywhere text-center text-sm leading-5 text-muted">
                  Xin chào,{" "}
                  <span className="font-semibold text-brand">
                    {user.displayName}
                  </span>
                </p>
                <a className={providerClass} href={resolveReturnUrl(returnUrl, user)}>
                  Tiếp tục với Findie <img src={chevronRight} alt="" />
                </a>
                <button
                  type="button"
                  className={providerClass}
                  disabled={loading}
                  onClick={() => void handleLogout()}
                >
                  {loading ? "Đang đăng xuất…" : "Đăng xuất"}
                </button>
              </>
            ) : enabled && !loading ? (
              <a
                className={providerClass}
                href={`/api/auth/google?returnUrl=${encodeURIComponent(returnUrl)}`}
              >
                {providerContent}
              </a>
            ) : (
              <button type="button" className={providerClass} disabled>
                {providerContent}
              </button>
            )}
            <div aria-live="polite" aria-atomic="true" className="empty:hidden">
              {loading && (
                <p className="sr-only">Đang kiểm tra phiên đăng nhập.</p>
              )}
              {!loading && (error || (!user && !enabled)) && (
                <div className="rounded-lg bg-[#fff3e9] p-3 text-sm leading-5 text-[#844719]">
                  <p className="m-0" role="alert">
                    {error ||
                      "Đăng nhập Google chưa được cấu hình trên máy chủ. Vui lòng thử lại sau."}
                  </p>
                  <button
                    type="button"
                    className="mt-2 cursor-pointer border-0 bg-transparent p-0 font-login text-sm font-semibold text-brand underline underline-offset-4 focus-visible:outline-primary"
                    onClick={() => setAttempt((value) => value + 1)}
                  >
                    Thử lại
                  </button>
                </div>
              )}
            </div>
          </div>
        </section>
        <a
          href="/"
          className="text-center text-sm text-muted underline underline-offset-4"
        >
          Quay lại trang tìm đồ
        </a>
      </div>
    </main>
  );
}
