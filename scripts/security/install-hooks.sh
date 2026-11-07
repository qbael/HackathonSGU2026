#!/usr/bin/env sh
# Install pre-commit hook for POSIX/WSL/macOS/Linux
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HOOK_TARGET="$REPO_ROOT/.git/hooks/pre-commit"

if [ -d "$REPO_ROOT/.git/hooks" ]; then
    cp "$SCRIPT_DIR/pre-commit" "$HOOK_TARGET"
    chmod +x "$HOOK_TARGET"
    echo "✅ Pre-commit hook installed to $HOOK_TARGET"
else
    echo "❌ Error: Not a git repository or .git/hooks directory not found."
    exit 1
fi
