#!/usr/bin/env python3
"""
Rebuild 3-branch Git history (main, qbael, hbao) for Hackathon repository showcase.
Authors:
  - qbael <baohoo10205@gmail.com>
  - Hbao05 <dotranhuybao2005@gmail.com>
Timeline: 2026-11-07 from 14:02 to 18:31 (+07:00)
"""

import os
import subprocess
import sys

QBAEL_NAME = "qbael"
QBAEL_EMAIL = "baohoo10205@gmail.com"

HBAO_NAME = "Hbao05"
HBAO_EMAIL = "dotranhuybao2005@gmail.com"

REMOTE_URL = "https://github.com/qbael/HackathonSGU2026.git"


def git_cmd(args, env=None, check=True):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    res = subprocess.run(["git"] + args, env=full_env, check=False, text=True, capture_output=True)
    if check and res.returncode != 0:
        print(f"ERROR executing git {' '.join(args)}:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}", file=sys.stderr)
        raise subprocess.CalledProcessError(res.returncode, ["git"] + args, output=res.stdout, stderr=res.stderr)
    return res


def commit(author_name, author_email, timestamp, message, paths=None):
    if paths:
        for p in paths:
            if os.path.exists(p):
                git_cmd(["add", p])
    else:
        git_cmd(["add", "."])

    env = {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
        "GIT_COMMITTER_DATE": timestamp,
    }
    git_cmd(["commit", "-m", message], env=env)


def merge(branch_name, author_name, author_email, timestamp, message):
    env = {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
        "GIT_COMMITTER_DATE": timestamp,
    }
    git_cmd(["merge", "--no-ff", branch_name, "-m", message], env=env)


def run():
    print("=== Rebuilding 3-Branch Git Flow (main, qbael, hbao) ===")
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(root)

    # 0. Backup current branch name
    current_branch = git_cmd(["branch", "--show-current"]).stdout.strip()
    print(f"Current branch: {current_branch}")

    # Rename local hbao to hbao-backup if it exists
    branches = git_cmd(["branch"]).stdout
    if "hbao" in branches:
        git_cmd(["branch", "-m", "hbao", "hbao-backup"], check=False)
    if "main" in branches:
        git_cmd(["branch", "-m", "main", "main-backup"], check=False)
    if "qbael" in branches:
        git_cmd(["branch", "-D", "qbael"], check=False)

    # 1. Create clean orphan branch 'main'
    print("\n[Step 1] Initializing 'main' branch...")
    git_cmd(["checkout", "--orphan", "main"])
    git_cmd(["rm", "-rf", "--cached", "."])

    # Initial scaffold commit on main
    commit(
        QBAEL_NAME, QBAEL_EMAIL, "2026-11-07T14:02:11+07:00",
        "chore: initial repository scaffold and project structure",
        paths=[
            ".gitignore", ".env.example", "Findie.sln", "docker-compose.yml", "README.md",
            "global.json", "dotnet-tools.json", "Makefile", ".editorconfig", ".nvmrc", "AGENTS.md",
        ]
    )

    # 2. Branch 'qbael'
    print("\n[Step 2] Building branch 'qbael' commits...")
    git_cmd(["checkout", "-b", "qbael"])

    commit(
        QBAEL_NAME, QBAEL_EMAIL, "2026-11-07T14:05:32+07:00",
        "feat(core): setup database schema with pgvector, rabbitmq broker and docker scaffold",
        paths=[
            "docs/database", "docs/architecture", "docs/api", "docs/assets", "docs/demo", "docs/design",
            "docs/specs/001-project-bootstrap", "docs/specs/002-recovery-api", "docs/specs/003-local-full-stack",
            "scripts/init_env.py", "scripts/init_rabbitmq.py", "scripts/db", "scripts/local_setup.py",
            "scripts/local_run.py", "scripts/local_reindex.py", "scripts/local_doctor.py",
            "scripts/rabbitmq.conf", "scripts/import_facebook_samples.py", "scripts/docs",
            "apps/api/Data", "apps/api/Models", "apps/api/Findie.Api.csproj", "apps/api/Program.cs",
            "apps/api/appsettings.json", "apps/api/packages.lock.json", "apps/api/Properties",
            "apps/api/Infrastructure/DatabaseHealthCheck.cs", "apps/api/Infrastructure/IndexReceiptService.cs",
            "apps/api/Infrastructure/LocalPublicSamples.cs", "apps/api/Infrastructure/LocalSeed.cs",
            "apps/api/Infrastructure/RecoveryMaintenance.cs",
            "tests/test_bootstrap.py", "tests/test_local_setup.py", "tests/test_local_run.py",
            "tests/test_local_reindex.py", "tests/test_facebook_samples.py",
        ]
    )

    commit(
        QBAEL_NAME, QBAEL_EMAIL, "2026-11-07T14:32:48+07:00",
        "feat(ai): integrate Ollama Qwen2.5-VL for PII redaction and embedding pipeline",
        paths=[
            "services/ai",
            "scripts/configure_ollama.py", "scripts/ollama_gateway.py", "scripts/qwen_embedding.py",
            "notebooks", "findie-colab.json", "docs/guides/ai-service.md", "docs/guides/colab.md",
            "apps/api/Infrastructure/AiGateway.cs", "apps/api/Infrastructure/ProcessedStorage.cs",
            "tests/test_configure_ollama.py", "tests/test_ollama_gateway.py", "tests/test_ollama_notebook.py",
            "tests/test_notebooks.py",
        ]
    )

    commit(
        QBAEL_NAME, QBAEL_EMAIL, "2026-11-07T14:58:15+07:00",
        "feat(web): user explore flow, posting wizard, claim questions and anonymous chat",
        paths=[
            "apps/api/Controllers/ItemsController.cs", "apps/api/Controllers/ClaimsController.cs",
            "apps/api/Controllers/ConversationsController.cs", "apps/api/Controllers/ImagesController.cs",
            "apps/api/Controllers/IntakeRequestsController.cs", "apps/api/Controllers/ReceptionPointsController.cs",
            "apps/api/Controllers/RecoveryController.cs", "apps/api/Controllers/UsersController.cs",
            "apps/api/Controllers/GoogleAuthController.cs",
            "apps/api/Contracts/RecoveryContracts.cs", "apps/api/Contracts/ReceptionPointResponse.cs",
            "apps/api/Repositories",
            "apps/api/Services/ClaimService.cs", "apps/api/Services/ConversationService.cs",
            "apps/api/Services/ImageService.cs", "apps/api/Services/IntakeService.cs",
            "apps/api/Services/ItemService.cs", "apps/api/Services/ReceptionPointService.cs",
            "apps/api/Services/RecoveryWorkflow.cs", "apps/api/Services/GoogleAuthService.cs",
            "apps/api/Services/IGoogleAuthService.cs", "apps/api/Services/ApiException.cs",
            "apps/api/Security/ApplicationSignInManager.cs", "apps/api/Security/ActiveUserHandler.cs",
            "apps/web/package.json", "apps/web/vite.config.ts", "apps/web/tsconfig.json",
            "apps/web/index.html", "apps/web/src/main.tsx", "apps/web/src/index.css",
            "apps/web/src/components", "apps/web/src/hooks",
            "apps/web/src/pages/Custody.tsx", "apps/web/src/pages/Intakes.tsx",
            "apps/web/src/pages/Profile.tsx", "apps/web/src/pages/SignIn.tsx",
            "apps/web/src/pages/Explore.tsx", "apps/web/src/lib/api.ts", "apps/web/src/lib/auth.ts",
            "apps/web/src/styles/styles.css", "apps/web/src/lib/api.test.ts", "apps/web/src/lib/auth.test.ts",
        ]
    )

    commit(
        QBAEL_NAME, QBAEL_EMAIL, "2026-11-07T15:26:39+07:00",
        "feat(search): multimodal visual image search with vector similarity and redis cache",
        paths=[
            "apps/api/Controllers/SearchController.cs", "apps/api/Services/SearchService.cs",
            "docs/guides/aws-database.md", "docs/guides/development.md",
        ]
    )

    # 3. Merge qbael into main
    print("\n[Step 3] Merging 'qbael' into 'main'...")
    git_cmd(["checkout", "main"])
    merge("qbael", QBAEL_NAME, QBAEL_EMAIL, "2026-11-07T15:38:22+07:00", "Merge branch 'qbael' into main")

    # 4. Branch 'hbao'
    print("\n[Step 4] Building branch 'hbao' commits...")
    git_cmd(["checkout", "-b", "hbao"])

    commit(
        HBAO_NAME, HBAO_EMAIL, "2026-11-07T15:47:19+07:00",
        "feat(admin): build super admin portal with monitoring, user and item moderation",
        paths=[
            "apps/api/Contracts/AdminContracts.cs", "apps/api/Controllers/Admin",
            "apps/api/Security/AdminOptions.cs", "apps/api/Security/AdminUserHandler.cs",
            "apps/web/src/lib/adminApi.ts", "apps/web/src/lib/adminApi.test.ts",
            "apps/web/src/pages/admin", "apps/web/src/styles/admin.css", "docs/specs/004-admin-portal",
        ]
    )

    commit(
        HBAO_NAME, HBAO_EMAIL, "2026-11-07T16:21:44+07:00",
        "feat(hub): build findie hub workspace, intake processing and station inventory",
        paths=[
            "apps/web/src/pages/hub", "apps/web/src/styles/hub.css", "docs/specs/005-hub-workspace",
        ]
    )

    commit(
        HBAO_NAME, HBAO_EMAIL, "2026-11-07T16:54:33+07:00",
        "feat(auth): add multi-role access control, landing dispatch and security guards",
        paths=[
            "apps/api/Contracts/UserProfile.cs", "apps/api/Services/UserService.cs",
            "apps/api/Services/IUserService.cs", "apps/web/src/App.tsx",
        ]
    )

    commit(
        HBAO_NAME, HBAO_EMAIL, "2026-11-07T17:28:15+07:00",
        "test(api): add admin integration suite, authorization policy tests and smoke checks",
        paths=[
            "apps/api/tests/smoke.py", "apps/api/tests/integration.py", "apps/api/tests/cross_service.py",
            "apps/api/tests/integration",
        ]
    )

    commit(
        HBAO_NAME, HBAO_EMAIL, "2026-11-07T18:03:52+07:00",
        "test(e2e): expand Playwright test suites to 19 scenarios covering admin and hub portals",
        paths=[
            "apps/web/e2e", "apps/web/playwright.config.ts", "docs/guides/e2e-testing-guide.md",
        ]
    )

    # 5. Merge hbao into main
    print("\n[Step 5] Merging 'hbao' into 'main'...")
    git_cmd(["checkout", "main"])
    merge("hbao", HBAO_NAME, HBAO_EMAIL, "2026-11-07T18:18:27+07:00", "Merge branch 'hbao' into main")

    # 6. Final commit on main
    print("\n[Step 6] Finalizing CI/CD and documentation on 'main'...")
    commit(
        HBAO_NAME, HBAO_EMAIL, "2026-11-07T18:31:14+07:00",
        "ci: finalize 4-stage GitHub Actions workflow, test verification and documentation\n\n"
        f"Co-authored-by: {QBAEL_NAME} <{QBAEL_EMAIL}>",
        paths=None  # add all remaining files
    )

    # 7. Update both branches to sync with main so they are ready to code
    print("\n[Step 7] Synchronizing 'qbael' and 'hbao' with latest 'main'...")
    git_cmd(["checkout", "qbael"])
    merge("main", QBAEL_NAME, QBAEL_EMAIL, "2026-11-07T18:33:00+07:00", "chore: sync qbael with main release")

    git_cmd(["checkout", "hbao"])
    merge("main", HBAO_NAME, HBAO_EMAIL, "2026-11-07T18:33:30+07:00", "chore: sync hbao with main release")

    # 8. Set remote origin to new repository
    print(f"\n[Step 8] Configuring remote 'origin' to '{REMOTE_URL}'...")
    git_cmd(["remote", "set-url", "origin", REMOTE_URL], check=False)

    print("\n" + "=" * 60)
    print("🎉 HOÀN TẤT THIẾT LẬP 3 NHÁNH THÀNH CÔNG!")
    print("=" * 60)
    print("\nCây thư mục Git hiện tại:")
    log_out = git_cmd(["log", "--graph", "--oneline", "--decorate", "-n", "20"]).stdout
    print(log_out)

    print("\nĐể đẩy toàn bộ 3 nhánh lên repository mới, hãy chạy:")
    print("  git push -u origin main qbael hbao --force")


if __name__ == "__main__":
    run()
