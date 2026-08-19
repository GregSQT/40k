#!/usr/bin/env bash
# T13 — Orchestration des 3 couches de tests frontend.
#
# Usage : bash scripts/front_test_all.sh [--skip-a] [--skip-b] [--skip-c]
#
# Couche A : pytest tests/integration/pvp/ (backend spawné sur port 5099)
# Couche B : npx vitest run (jsdom, sans backend)
# Couche C : npx playwright test (backend 5098, frontend Vite 5198, VITE_TEST_HOOKS=1)
#
# Garanties :
#   - Aucun process orphelin (trap EXIT)
#   - Aucune écriture dans config/users.db ni ai/models/
#     (backend lancé en lecture seule sur users.db ; les tests ne touchent pas ai/)
#   - Rapport unique : PASS/FAIL par couche à la fin

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO/.venv/bin/python3"
FRONTEND_DIR="$REPO/frontend"

PORT_A=5099   # backend couche A (pytest integration)
PORT_C=5098   # backend couche C (playwright)
FRONT_C=5198  # frontend Vite couche C (VITE_TEST_HOOKS=1)

SKIP_A=false
SKIP_B=false
SKIP_C=false

for arg in "$@"; do
  case "$arg" in
    --skip-a) SKIP_A=true ;;
    --skip-b) SKIP_B=true ;;
    --skip-c) SKIP_C=true ;;
  esac
done

# ---------------------------------------------------------------------------
# Processus à tuer à la sortie (normalement ou sur erreur)
# ---------------------------------------------------------------------------

PIDS_TO_KILL=()

cleanup() {
  for pid in "${PIDS_TO_KILL[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

wait_for_http() {
  local url="$1"
  local max="${2:-30}"
  local i=0
  while ! curl -sf "$url" >/dev/null 2>&1; do
    sleep 1
    i=$((i+1))
    if [ "$i" -ge "$max" ]; then
      echo "ERROR: $url non joignable après ${max}s" >&2
      return 1
    fi
  done
}

spawn_backend() {
  local port="$1"
  "$VENV" -c "
from services.api_server import app
app.run(host='127.0.0.1', port=$port, debug=False, use_reloader=False)
" &
  local pid=$!
  PIDS_TO_KILL+=("$pid")
  wait_for_http "http://127.0.0.1:$port/api/health"
}

# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------

RESULT_A="⚪ skipped"
RESULT_B="⚪ skipped"
RESULT_C="⚪ skipped"
EXIT_CODE=0

# ---------------------------------------------------------------------------
# Couche A — pytest integration PvP
# ---------------------------------------------------------------------------

if [ "$SKIP_A" = false ]; then
  echo ""
  echo "════════════════════════════════════════════════════════"
  echo "  Couche A — pytest tests/integration/pvp/"
  echo "════════════════════════════════════════════════════════"

  cd "$REPO"
  spawn_backend $PORT_A

  set +e
  W40K_API_URL="http://127.0.0.1:$PORT_A" \
    "$VENV" -m pytest tests/integration/pvp/ -q -n 6 --dist load \
    --tb=short 2>&1
  A_EXIT=$?
  set -e

  if [ $A_EXIT -eq 0 ]; then
    RESULT_A="✅ PASS"
  else
    RESULT_A="❌ FAIL (exit $A_EXIT)"
    EXIT_CODE=1
  fi

  # Arrêter le backend couche A
  kill "${PIDS_TO_KILL[-1]}" 2>/dev/null || true
  PIDS_TO_KILL=("${PIDS_TO_KILL[@]::${#PIDS_TO_KILL[@]}-1}")
fi

# ---------------------------------------------------------------------------
# Couche B — vitest (jsdom, sans backend)
# ---------------------------------------------------------------------------

if [ "$SKIP_B" = false ]; then
  echo ""
  echo "════════════════════════════════════════════════════════"
  echo "  Couche B — vitest run"
  echo "════════════════════════════════════════════════════════"

  cd "$FRONTEND_DIR"

  set +e
  npx vitest run 2>&1
  B_EXIT=$?
  set -e

  if [ $B_EXIT -eq 0 ]; then
    RESULT_B="✅ PASS"
  else
    RESULT_B="❌ FAIL (exit $B_EXIT)"
    EXIT_CODE=1
  fi
fi

# ---------------------------------------------------------------------------
# Couche C — Playwright (backend 5098, frontend Vite 5198, VITE_TEST_HOOKS=1)
# ---------------------------------------------------------------------------

if [ "$SKIP_C" = false ]; then
  echo ""
  echo "════════════════════════════════════════════════════════"
  echo "  Couche C — playwright test"
  echo "════════════════════════════════════════════════════════"

  cd "$REPO"
  spawn_backend $PORT_C

  cd "$FRONTEND_DIR"

  # Démarrer le frontend Vite avec le hook de test activé
  VITE_TEST_HOOKS=1 VITE_PORT=$FRONT_C npx vite --port "$FRONT_C" &
  VITE_PID=$!
  PIDS_TO_KILL+=("$VITE_PID")
  wait_for_http "http://localhost:$FRONT_C" 60

  set +e
  PW_FRONTEND_URL="http://localhost:$FRONT_C" \
    PW_BASE_URL="http://127.0.0.1:$PORT_C" \
    npx playwright test 2>&1
  C_EXIT=$?
  set -e

  if [ $C_EXIT -eq 0 ]; then
    RESULT_C="✅ PASS"
  else
    RESULT_C="❌ FAIL (exit $C_EXIT)"
    EXIT_CODE=1
  fi

  # Screenshots des échecs déjà dans playwright-report/ par la config
fi

# ---------------------------------------------------------------------------
# Rapport final
# ---------------------------------------------------------------------------

echo ""
echo "════════════════════════════════════════════════════════"
echo "  RAPPORT front_test_all"
echo "════════════════════════════════════════════════════════"
echo "  Couche A (pytest integration PvP) : $RESULT_A"
echo "  Couche B (vitest jsdom)           : $RESULT_B"
echo "  Couche C (playwright E2E)         : $RESULT_C"
echo "════════════════════════════════════════════════════════"

exit $EXIT_CODE
