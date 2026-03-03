#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/volume1/docker/40k/app}"
DOCKER_BIN="/usr/local/bin/docker"

if [[ ! -x "$DOCKER_BIN" ]]; then
  if command -v docker >/dev/null 2>&1; then
    DOCKER_BIN="$(command -v docker)"
  else
    echo "ERROR: docker binary not found." >&2
    exit 1
  fi
fi

cd "$APP_DIR"

echo "==> Check compose services status"
PS_OUTPUT="$(sudo "$DOCKER_BIN" compose ps)"
echo "$PS_OUTPUT"
echo "$PS_OUTPUT" | grep -q "wh40k-backend" || { echo "ERROR: backend service missing" >&2; exit 1; }
echo "$PS_OUTPUT" | grep -q "wh40k-frontend" || { echo "ERROR: frontend service missing" >&2; exit 1; }
echo "$PS_OUTPUT" | grep -q "healthy" || { echo "ERROR: backend is not healthy" >&2; exit 1; }

echo "==> Check backend health endpoint"
HEALTH_JSON="$(curl -fsS http://127.0.0.1:5001/api/health)"
echo "$HEALTH_JSON"
echo "$HEALTH_JSON" | grep -q '"status": "healthy"' || { echo "ERROR: /api/health is not healthy" >&2; exit 1; }

echo "==> Check required backend config files"
for required_file in \
  /app/config/scenario_game.json \
  /app/config/scenario_test.json \
  /app/config/unit_rules.json
do
  sudo "$DOCKER_BIN" exec wh40k-backend test -f "$required_file" || {
    echo "ERROR: missing required file in backend container: $required_file" >&2
    exit 1
  }
  echo "OK: $required_file"
done

echo "==> Check frontend bundle has no localhost API hardcode"
if sudo "$DOCKER_BIN" exec wh40k-frontend sh -lc "grep -RIno 'localhost:5001' /usr/share/nginx/html" >/tmp/localhost_matches.txt 2>/dev/null; then
  if [[ -s /tmp/localhost_matches.txt ]]; then
    echo "ERROR: frontend bundle still contains localhost:5001"
    cat /tmp/localhost_matches.txt
    rm -f /tmp/localhost_matches.txt
    exit 1
  fi
fi
rm -f /tmp/localhost_matches.txt
echo "OK: no localhost:5001 in frontend bundle"

echo "==> Check numpy compatibility for model loading"
sudo "$DOCKER_BIN" exec -i wh40k-backend python - <<'PY'
import importlib
import numpy

print(f"numpy: {numpy.__version__}")
importlib.import_module("numpy._core.numeric")
print("OK: numpy._core.numeric import")
PY

echo "==> All deployment checks passed."
