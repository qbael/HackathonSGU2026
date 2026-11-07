---
name: "security-audit"
description: "Audit project security, scan for secrets with Gitleaks, run SAST with Semgrep, check dependency vulnerabilities (SCA), and review code against Findie privacy and security guidelines."
compatibility: "Cross-platform (Linux/macOS/Windows/WSL/CI)"
metadata:
  author: "Findie Security Team"
  version: "1.0.0"
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider user input/scope (e.g. specific directory, PR diff, or full audit) before proceeding.

---

## Goal

Provide an automated, rigorous security audit and code review for the Findie platform covering:
1. **Secret Detection**: Run/verify Gitleaks scans to ensure no credentials or `.env*` variables leak.
2. **SAST Analysis**: Run/inspect Semgrep rules across ASP.NET Core (`apps/api`), React (`apps/web`), and Python AI service (`services/ai`).
3. **SCA (Dependency Vulnerability)**: Check for known CVEs across NuGet, npm, and PyPI dependencies.
4. **Findie Domain Privacy Checks**: Enforce Zero Raw Image Storage, PII redaction, constant-time token comparison, and rate limiting.

---

## Core Security Rules (Enforced by AGENTS.md)

1. **Tuyệt đối KHÔNG đọc, mở, hiển thị hoặc sửa đổi nội dung của file `.env`** cũng như các file biến môi trường chứa bí mật (`.env.local`, `.env.*.local`, `.env.backup`).
2. **Chỉ được tham khảo file mẫu `.env.example`** để hiểu cấu trúc biến cần thiết.
3. **Không in token, secret, mật khẩu database, OAuth client secret hay private access key** trong chat, logs hoặc artifacts.
4. **Quy tắc cốt lõi Findie**: Không lưu trữ ảnh gốc ra đĩa hoặc storage; không đưa PII vào log hay cơ sở dữ liệu tìm kiếm công khai.

---

## Audit Execution Workflow

### Step 1: Secret & Git Hygiene Scan (Gitleaks)

- **Command (Local / CI)**:
  ```sh
  # Scan uncommitted changes / staged commits:
  gitleaks git --staged --verbose --config=.gitleaks.toml

  # Scan repository history:
  gitleaks detect --verbose --config=.gitleaks.toml
  ```
- **Manual Verification**:
  - Check `.gitignore` ensures all `.env*` patterns (except `.env.example`) are safely ignored.
  - Verify no secret keys, credentials, or private certificates exist in staged files.

---

### Step 2: Static Application Security Testing (Semgrep)

- **Command (Local / CI)**:
  ```sh
  # Full codebase scan with automated rules:
  semgrep scan --config auto --error

  # Target-specific scan using curated rulesets:
  semgrep scan --config "p/csharp" --config "p/owasp-top-ten" apps/api/
  semgrep scan --config "p/python" --config "p/fastapi" services/ai/
  semgrep scan --config "p/typescript" --config "p/react" apps/web/
  semgrep scan --config "p/dockerfile" --config "p/docker-compose" .
  ```
- **Focus Areas**:
  - **SQL Injection**: Check EF Core / Raw SQL queries (ensure all queries use parameterized inputs).
  - **SSRF**: Ensure external URL calls (e.g. `Ai:BaseUrl`) validate scheme, host, and port.
  - **Timing Attacks**: Ensure token checks use constant-time comparison (`secrets.compare_digest` in Python, `CryptographicOperations.FixedTimeEquals` in .NET).
  - **Insecure Deserialization**: Verify JSON deserialization limits and safe types.

---

### Step 3: Software Composition Analysis (SCA)

- **.NET Packages**:
  ```sh
  dotnet list apps/api/Findie.Api.csproj package --vulnerable --include-transitive
  ```
- **NPM Packages**:
  ```sh
  npm audit --prefix apps/web --audit-level=high
  ```
- **Python Packages**:
  ```sh
  uv run --project services/ai pip-audit
  # hoặc: pip-audit -r services/ai/requirements.txt
  ```

---

### Step 4: Findie Privacy & Hardening Review Matrix

Review any changed or newly added code against the following checklist:

| Category | Check Item | Target Files |
| :--- | :--- | :--- |
| **Privacy** | Raw images never stored to disk or R2 | `apps/api/Services/ImageService.cs`, `services/ai/findie_ai/worker.py` |
| **Privacy** | Bounding boxes & PII redacting applied before image visibility | `apps/api/Controllers/ImagesController.cs` |
| **Privacy** | No sensitive data (email, phone, student ID) in vector embeddings or logs | `apps/api/Infrastructure/AiGateway.cs`, `services/ai/findie_ai/ranking.py` |
| **Network** | Security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options) present | `apps/api/Program.cs` |
| **Network** | `XForwardedFor` enabled for trusted reverse proxy | `apps/api/Program.cs` |
| **Auth** | Controller actions require authentication & role checks (`[Authorize]`, `ActiveUserRequirement`) | `apps/api/Controllers/*.cs` |
| **DoS Prevention** | File upload size limits & Image Decompression Bomb protection (`Image.MAX_IMAGE_PIXELS`) | `apps/api/Infrastructure/BoundedImage.cs`, `services/ai/findie_ai/images.py` |
| **Anti-CSRF** | State-changing endpoints require valid Anti-CSRF token | `apps/api/Program.cs` |

---

### Step 5: Generate Security Audit Report

When presenting the results to the user, format the output clearly:

1. **Executive Summary**: Pass/Fail verdict, total findings grouped by severity (Critical / High / Medium / Low).
2. **Secret Scanning Findings**: Gitleaks output and git hygiene state.
3. **SAST Findings**: Semgrep alerts with exact file paths, line numbers, and CWE references.
4. **SCA Vulnerabilities**: Outdated/vulnerable packages and available upgrade versions.
5. **Privacy & Domain Hardening Review**: Conformance to Findie's Zero Raw Image and PII rules.
6. **Remediation Plan**: Concrete, minimal diffs or actions to resolve each identified finding.
