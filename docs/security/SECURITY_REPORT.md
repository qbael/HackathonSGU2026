# Báo Cáo Chức Năng Bảo Mật Dự Án Findie (Security Report)

> **Dự án:** Findie – Nền tảng tìm và trao trả đồ thất lạc  
> **Cập nhật lần cuối:** 2026-11-08  
> **Tiêu chuẩn áp dụng:** OWASP Top 10, Zero Raw Image Persistence, PII Protection, DevSecOps Multi-Layer Defense.

---

## I. Tổng Quan Kiến Trúc An Ninh (Security Overview)

Dự án Findie áp dụng mô hình bảo vệ đa tầng (**Defense-in-Depth**), kết hợp giữa việc tối ưu hóa mã nguồn tại runtime, kiểm soát mã tĩnh trong quá trình phát triển (Local & Pre-commit), và tự động hóa kiểm thử an ninh trong đường ống CI/CD.

```mermaid
graph TD
    subgraph Client_Access["1. Truy cập & Mạng"]
        User[Người dùng / Trình duyệt] --> ReverseProxy[Reverse Proxy / Cloudflare]
        ReverseProxy --> HSTS[HSTS & Security Headers]
        ReverseProxy --> CORS[CORS Whitelist]
        ReverseProxy --> RateLimit[Rate Limiting theo IP & User]
    end

    subgraph Auth_Identity["2. Xác thực & Phân quyền"]
        HSTS --> GoogleAuth[Google OAuth 2.0]
        GoogleAuth --> SessionCookie[HttpOnly / SameSite Cookie]
        SessionCookie --> CSRF[Anti-CSRF Token (IAntiforgery)]
        CSRF --> RBAC[Role-based Access Control: Active & Admin]
    end

    subgraph Core_Privacy["3. Quyền riêng tư & Xử lý Ảnh (Core Privacy)"]
        RBAC --> MemoryFilter[Magic Bytes Check & Bounded Buffer]
        MemoryFilter --> Redaction[AI Vision Masking: Mặt, CCCD, PII]
        Redaction --> ZeroRaw[Zero Raw Image Storage]
        ZeroRaw --> R2Storage[Cloudflare R2: Chỉ lưu ảnh đã che]
    end

    subgraph DevSecOps_Gate["4. Giám sát & Quét mã (DevSecOps)"]
        PreCommit[Pre-commit Hook: Gitleaks & Anti-Disk-Write]
        CI[GitHub Actions Security Scan]
        Semgrep[Semgrep SAST Multi-Language]
        SCA[Dependency Audit: NuGet, NPM, PyPI]
    end
```

---

## II. Danh Mục Chức Năng Bảo Mật Đã Triển Khai

### 1. Bảo vệ Quyền riêng tư & Dữ liệu Hình ảnh (Privacy & PII Protection)
- **Quy tắc Cốt lõi (Zero Raw Image Persistence):** Hệ thống không bao giờ ghi ảnh gốc của người dùng ra đĩa hoặc storage vĩnh viễn. Ảnh được đọc vào RAM qua bộ nhớ đệm an toàn (`MemoryStream`), sau khi xử lý sẽ được xóa trắng bộ nhớ (`Array.Clear`).
- **Tự động nhận diện và làm mờ thông tin nhạy cảm:**
  - Model AI tự động phát hiện và che mờ (redact): Khuôn mặt (`face`), Số căn cước công dân (`identity_number`), Số điện thoại (`phone`), Địa chỉ (`address`), Mã QR / Barcode.
  - Ảnh chỉ được phép lưu vào Cloudflare R2 sau khi đã qua bước che mờ và được xác nhận.
- **Xác thực định dạng ảnh bằng Magic Bytes (`BoundedImage.Signature`):** Ngăn chặn kỹ thuật tấn công đổi đuôi file (chỉ chấp nhận `image/jpeg`, `image/png`, `image/webp` khớp với signature byte nhị phân thực tế).
- **Phòng chống tấn công Decompression Bomb (DoS):**
  - Giới hạn dung lượng tải lên tối đa **10 MiB** (`BoundedImage.MaxBytes`).
  - Thiết lập chặn tràn bộ nhớ trong thư viện Pillow: `Image.MAX_IMAGE_PIXELS = 25_000_000` và kiểm tra `width * height <= 25_000_000`.

### 2. Xác thực & Quản lý Phiên (Authentication & Session)
- **Đăng nhập Google OAuth 2.0:** Không lưu mật khẩu người dùng trong cơ sở dữ liệu, loại bỏ hoàn toàn nguy cơ rò rỉ cơ sở dữ liệu mật khẩu (Credential Stuffing).
- **Bảo mật Cookie Phiên (`Findie.GoogleSession`):**
  - `HttpOnly = true`: Chống tấn công XSS đánh cắp session.
  - `SameSite = SameSiteMode.Lax`: Phòng vệ chống Cross-Site Request Forgery (CSRF).
  - `SecurePolicy = CookieSecurePolicy.Always`: Bắt buộc chỉ truyền cookie qua HTTPS trên môi trường Production.
- **Bảo vệ Chống CSRF Toàn diện (`IAntiforgery`):**
  - Mọi yêu cầu thay đổi trạng thái (`POST`, `PUT`, `DELETE`) từ người dùng đã đăng nhập đều bắt buộc phải mang theo header `X-CSRF-TOKEN` hợp lệ.
- **Timing Attack Defense:**
  - Token giao tiếp nội bộ giữa ASP.NET Core API và Python AI Worker (`X-Service-Token`) được xác thực bằng `secrets.compare_digest` (so sánh thời gian hằng số - constant time comparison).

### 3. Ủy quyền & Kiểm soát Truy cập (Authorization & Rate Limiting)
- **Kiểm soát quyền chặt chẽ:** Sử dụng chính sách xác thực `ActiveUserRequirement` và `AdminUserRequirement` cho các API quản trị và nghiệp vụ.
- **Kiểm tra quyền sở hữu đối tượng (`RequireManagerAsync`):** Đảm bảo người dùng chỉ có thể chỉnh sửa/thu hồi hình ảnh của món đồ do chính mình quản lý.
- **Giới hạn Tần suất Truy cập (Rate Limiting):**
  - Nhánh nghiệp vụ (`business`): Tối đa 120 yêu cầu / phút.
  - Nhánh tải ảnh (`images`): Tối đa 20 yêu cầu / phút.
  - Phân vùng rate limit theo User ID (khi đã đăng nhập) hoặc Remote IP (với khách vãng lai).

### 4. Gia cố Mạng & HTTP Security Headers (Network Hardening)
- **Bộ Security Headers chuẩn OWASP trong ASP.NET Core:**
  - `X-Frame-Options: DENY`: Chống Clickjacking.
  - `X-Content-Type-Options: nosniff`: Chống tấn công MIME-sniffing.
  - `Referrer-Policy: strict-origin-when-cross-origin`: Giới hạn rò rỉ URL chứa ID nội bộ.
  - `X-XSS-Protection: 0`: Tắt bộ lọc XSS cũ của trình duyệt để tránh tạo ra lỗ hổng mới theo khuyến cáo OWASP.
  - `Permissions-Policy: camera=(), microphone=(), geolocation=()`: Chặn các tính năng phần cứng nhạy cảm.
  - `Strict-Transport-Security (HSTS)`: Bắt buộc HTTPS 365 ngày kèm preload và includeSubDomains.
- **Cấu hình CORS Tường Minh (`FindieCors`):**
  - Chặn hoàn toàn wildcard origin (`*`) khi bật `AllowCredentials()`.
  - Môi trường Development: Cho phép `http://localhost:5173` và `http://127.0.0.1:5173`.
  - Môi trường Production: Yêu cầu định cấu hình danh sách domain qua `Cors:AllowedOrigins`.
- **Hỗ trợ Reverse Proxy Chính xác (`X-Forwarded-For`):** Bật cờ phục hồi IP gốc giúp Rate Limiter không bị khóa nhầm toàn bộ người dùng sau Cloudflare hoặc Nginx.

### 5. Kiểm thử Mã Nguồn Tĩnh & Quản lý Bí mật (SAST & Secret Detection)
- **Gitleaks:** Quét phát hiện lộ lọt API key, secret token, password, private key trước khi commit và trong CI.
- **Semgrep SAST:** Quét lỗ hổng logic trên C#, Python, TypeScript, React và Dockerfile.
  - Bổ sung rule đặc thù: Cảnh báo ngay nếu có đoạn code cố tình ghi byte ảnh ra đĩa (`findie-prevent-raw-image-disk-write`).
- **Frontend Security Linting:** Cấu hình ESLint với `eslint-plugin-security` trong `apps/web` để kiểm tra các nguy cơ DOM XSS, Regex injection (ReDoS).
- **Pre-commit Hook Tự Động:** Chặn lập tức các thao tác stage file `.env*` và quét vi phạm trực tiếp trên máy lập trình viên.

---

## III. Bảng Lệnh Thực Thi Các Tác Vụ An Ninh (Command Reference)

Dưới đây là các lệnh dòng lệnh dùng để cài đặt hook, kiểm tra bảo mật, quét lỗ hổng và chạy audit:

### 1. Cài Đặt Git Security Hook Trên Máy Local

| Hệ điều hành | Lệnh thực thi | Mục đích |
| :--- | :--- | :--- |
| **Windows (PowerShell)** | `.\scripts\security\install-hooks.ps1` | Cài pre-commit hook chặn lộ file `.env` và quét Gitleaks |
| **Linux / macOS / WSL** | `./scripts/security/install-hooks.sh` | Cài pre-commit hook và cấp quyền thực thi `chmod +x` |

---

### 2. Quét Lộ Lọt Bí Mật (Secret Scanning với Gitleaks)

| Tác vụ | Lệnh thực thi |
| :--- | :--- |
| **Quét các file đã `git add` (staged)** | `gitleaks git --staged --verbose --config=.gitleaks.toml` |
| **Quét toàn bộ lịch sử commit của repo** | `gitleaks detect --verbose --config=.gitleaks.toml` |

---

### 3. Phân Tích Mã Nguồn Tĩnh (SAST với Semgrep)

| Tác vụ | Lệnh thực thi |
| :--- | :--- |
| **Quét toàn bộ dự án với rule Findie + OWASP** | `semgrep scan --config .semgrep/findie-rules.yml --config "p/owasp-top-ten" --error` |
| **Quét chuyên biệt .NET API (`apps/api`)** | `semgrep scan --config "p/csharp" --config "p/owasp-top-ten" apps/api/` |
| **Quét chuyên biệt Python AI (`services/ai`)** | `semgrep scan --config "p/python" --config "p/fastapi" services/ai/` |
| **Quét chuyên biệt Web Frontend (`apps/web`)** | `semgrep scan --config "p/typescript" --config "p/react" apps/web/` |
| **Quét file cấu hình Docker & Compose** | `semgrep scan --config "p/dockerfile" --config "p/docker-compose" .` |

---

### 4. Quét Lỗ Hổng Thư Viện Phụ Thuộc (SCA - Dependency Vulnerabilities)

| Nền tảng | Lệnh thực thi |
| :--- | :--- |
| **.NET API (NuGet)** | `dotnet list apps/api/Findie.Api.csproj package --vulnerable --include-transitive` |
| **Web Frontend (NPM)** | `npm audit --prefix apps/web --audit-level=high` |
| **Python AI Worker (PyPI)** | `uv run --project services/ai --with pip-audit pip-audit` |

---

### 5. Kiểm Tra Mã Nguồn Frontend (Lint & Typecheck)

| Tác vụ | Lệnh thực thi |
| :--- | :--- |
| **Chạy ESLint Security kiểm tra an ninh code** | `npm run lint --prefix apps/web` |
| **Kiểm tra kiểu dữ liệu TypeScript** | `npm run typecheck --prefix apps/web` |
| **Chạy toàn bộ build kiểm thử Frontend** | `npm run build --prefix apps/web` |

---

### 6. Kiểm Tra Môi Trường & Kết Nối Hệ Thống

| Tác vụ | Lệnh thực thi |
| :--- | :--- |
| **Chạy script chẩn đoán trạng thái hệ thống Findie** | `python3 scripts/local_doctor.py` |

---

## IV. Tóm Tắt Trạng Thái Đáp Ứng An Ninh (Compliance Matrix)

| Tiêu chuẩn an ninh | Mức độ đáp ứng | Cơ chế bảo vệ |
| :--- | :---: | :--- |
| **A01: Broken Access Control** | ✅ Đạt | RBAC (`ActiveUserRequirement`, `AdminUserRequirement`), `RequireManagerAsync` |
| **A02: Cryptographic Failures** | ✅ Đạt | HTTPS/HSTS, Constant-time token check, Không lưu trữ secret dạng plain-text |
| **A03: Injection** | ✅ Đạt | Parameterized queries qua EF Core / Npgsql, Safe Regex |
| **A04: Insecure Design** | ✅ Đạt | Zero Raw Image Storage, Bounded buffers, Privacy Redaction luồng kín |
| **A05: Security Misconfiguration** | ✅ Đạt | Global Security Headers, CORS policy tường minh, `nosniff`, `DENY` |
| **A06: Vulnerable & Outdated Components**| ✅ Đạt | Tích hợp SCA (NuGet audit, npm audit, pip-audit) trong CI Pipeline |
| **A07: Identification & Auth Failures** | ✅ Đạt | Google OAuth 2.0, Secure Session Cookies, Rate Limiting chống Brute-force |
| **A08: Software & Data Integrity Failures**| ✅ Đạt | Anti-CSRF Token bắt buộc, Magic Bytes signature validation |
| **A09: Security Logging & Monitoring** | ✅ Đạt | Health check endpoints (`/health/live`, `/health/ready`), Giới hạn rò rỉ log |
| **A10: Server-Side Request Forgery (SSRF)**| ✅ Đạt | URL validation nghiêm ngặt trên `Ai:BaseUrl` (không query, không credential) |
