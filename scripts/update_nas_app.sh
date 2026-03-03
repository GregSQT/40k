#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/volume1/docker/40k/app"
DOCKER_BIN="/usr/local/bin/docker"
STASH_MSG="auto-stash-before-update"
BRANCH="main"
USE_STASH=1
CREATED_STASH_REF=""
CREATED_STASH=0

usage() {
  cat <<'EOF'
Usage: update_nas_app.sh [--branch <name>] [--no-stash] [--app-dir <path>]

Options:
  --branch <name>   Git branch to pull (default: main)
  --no-stash        Skip automatic git stash before pull
  --app-dir <path>  Override app directory (default: /volume1/docker/40k/app)
  -h, --help        Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)
      BRANCH="${2:-}"
      if [[ -z "$BRANCH" ]]; then
        echo "ERROR: --branch requires a value" >&2
        exit 2
      fi
      shift 2
      ;;
    --no-stash)
      USE_STASH=0
      shift
      ;;
    --app-dir)
      APP_DIR="${2:-}"
      if [[ -z "$APP_DIR" ]]; then
        echo "ERROR: --app-dir requires a value" >&2
        exit 2
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

cd "$APP_DIR"

if [[ ! -x "$DOCKER_BIN" ]]; then
  echo "ERROR: Docker binary not executable at $DOCKER_BIN" >&2
  exit 1
fi

echo "==> Git status"
git status -sb

if [[ "$USE_STASH" -eq 1 ]]; then
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "==> Drop previous auto stashes"
    while read -r ref _; do
      [[ -z "${ref:-}" ]] && continue
      git stash drop "$ref" >/dev/null || true
    done < <(git stash list --format='%gd %gs' | awk -v msg="$STASH_MSG" '$0 ~ msg {print $1}')

    echo "==> Stash local changes (tracked + untracked)"
    git stash push -u -m "$STASH_MSG"
    CREATED_STASH_REF="$(git stash list --format='%gd %gs' | awk -v msg="$STASH_MSG" '$0 ~ msg {print $1; exit}')"
    if [[ -n "$CREATED_STASH_REF" ]]; then
      CREATED_STASH=1
      echo "Created stash: $CREATED_STASH_REF"
    fi
  else
    echo "==> No local changes to stash"
  fi
else
  echo "==> Skipping stash (--no-stash)"
fi

echo "==> Pull latest $BRANCH"
git pull --rebase origin "$BRANCH"

echo "==> Validate compose configuration"
sudo "$DOCKER_BIN" compose config >/dev/null

echo "==> Rebuild and restart containers"
sudo "$DOCKER_BIN" compose up -d --build

echo "==> Health checks"
sudo "$DOCKER_BIN" compose ps
curl -fsS http://127.0.0.1:5001/api/health || true
curl -I http://127.0.0.1:8081 || true

echo "==> Recent stash entries"
git stash list | head -n 3 || true

if [[ "$CREATED_STASH" -eq 1 && -n "$CREATED_STASH_REF" ]]; then
  echo "==> Auto-clean created stash: $CREATED_STASH_REF"
  git stash drop "$CREATED_STASH_REF" >/dev/null || true
fi

echo "Done."