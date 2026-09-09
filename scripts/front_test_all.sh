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
      # Le GROUPE, pas le seul PID. `npx vite` lance un enfant `node .../vite` qui NE MEURT PAS
      # avec son parent : mesuré le 2026-09-09, un `node .../vite --port 5198` d'un worktree
      # depuis longtemps supprimé squattait encore le port. Le run suivant voyait alors
      # « Port 5198 is already in use », son propre Vite mourait, et Playwright pilotait le
      # serveur de l'AUTRE run — avec l'ancienne configuration de proxy. Les tests mesuraient
      # un serveur fantôme, et rendaient « terrain-list: HTTP 500 » alors que l'API va bien.
      kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT

port_libre_ou_echoue() {
  # Un port occupé n'est JAMAIS une condition à contourner ici : le squatteur répondrait aux
  # tests à la place du serveur qu'on voulait mesurer, et le run entier serait faux sans le dire.
  local port="$1"
  local quoi="$2"
  if curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:$port" \
     || curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:$port/api/health"; then
    echo "ERROR: le port $port ($quoi) est déjà pris. Un run précédent a laissé un serveur :" >&2
    echo "       pkill -f 'vite --port $port' ; pkill -f 'port=$port'" >&2
    return 1
  fi
  return 0
}

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

prerequis_couche_c() {
  # « JE NE PEUX PAS JUGER » N'EST PAS « C'EST CASSÉ ».
  #
  # La couche C exige trois choses que le dépôt ne porte pas : le paquet `@playwright/test`, un
  # navigateur téléchargé, et une SESSION VALIDE dans `config/users.db` — que `global-setup.ts`
  # lit pour construire son `storageState`, et qui n'existe que si quelqu'un s'est connecté au
  # front. Aucune des trois n'est une régression du code.
  #
  # Sans cette distinction, la couche entrait dans la vérification large en rendant un ROUGE sur
  # toute machine neuve : un rouge permanent qu'on apprend à ignorer, puis à contourner. C'est
  # exactement ce que ce dépôt a déjà vécu avec la couche B, rouge par construction pendant des
  # semaines. Un prérequis manquant se DIT, bruyamment, et n'échoue pas.
  local manquant=""
  [ -d "$FRONTEND_DIR/node_modules/@playwright/test" ] || manquant="@playwright/test"
  if [ -z "$manquant" ] && ! ls "$HOME/.cache/ms-playwright"/chromium* >/dev/null 2>&1; then
    manquant="le navigateur Chromium"
  fi
  if [ -z "$manquant" ] && ! "$VENV" -c "
import sqlite3, sys, time
try:
    c = sqlite3.connect('$REPO/config/users.db')
    n = c.execute('SELECT COUNT(*) FROM sessions WHERE expires_at > ?', (int(time.time()),)).fetchone()[0]
except Exception:
    n = 0
sys.exit(0 if n else 1)
" 2>/dev/null; then
    manquant="une session valide dans config/users.db"
  fi

  if [ -n "$manquant" ]; then
    RESULT_C="🟠 PRÉREQUIS ABSENT ($manquant)"
    echo ""
    echo "════════════════════════════════════════════════════════"
    echo "  Couche C — NON JUGÉE : $manquant"
    echo "════════════════════════════════════════════════════════"
    echo "  Ce n'est PAS un échec de test : la couche n'a pas pu s'exécuter."
    echo "    npm --prefix frontend install"
    echo "    npx --prefix frontend playwright install chromium"
    echo "    se connecter une fois au front pour créer une session"
    return 1
  fi
  return 0
}

spawn_backend() {
  local port="$1"
  port_libre_ou_echoue "$port" "backend" || return 1
  if [ ! -x "$VENV" ]; then
    # Diagnostic IMMÉDIAT plutôt que 30 s d'attente d'un serveur qui n'a jamais démarré : c'est
    # le cas dans un worktree, qui n'a pas de `.venv` (mesuré le 2026-09-09).
    echo "ERROR: interpréteur introuvable : $VENV" >&2
    echo "       Ce script se lance depuis la racine du dépôt, pas depuis un worktree." >&2
    return 1
  fi
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

if [ "$SKIP_C" = false ] && prerequis_couche_c; then
  echo ""
  echo "════════════════════════════════════════════════════════"
  echo "  Couche C — playwright test"
  echo "════════════════════════════════════════════════════════"

  cd "$REPO"
  spawn_backend $PORT_C

  cd "$FRONTEND_DIR"

  # Démarrer le frontend Vite avec le hook de test activé.
  #
  # `VITE_API_TARGET` fait pointer le proxy `/api` vers le backend de CETTE couche (port 5098) au
  # lieu du 5001 de développement. Sans lui, le navigateur tapait un port où rien n'écoute pendant
  # les tests : tous les scénarios échouaient sur `ECONNREFUSED 127.0.0.1:5001`, quel que soit
  # l'état de l'application (mesuré le 2026-09-09, première exécution réelle de cette couche).
  # `PW_BASE_URL` ne suffit pas : il ne gouverne que les requêtes émises par Playwright lui-même.
  port_libre_ou_echoue "$FRONT_C" "frontend Vite" || exit 1
  # `setsid` place Vite dans son PROPRE groupe de processus, que `cleanup` sait tuer en entier :
  # `npx` n'est qu'un lanceur, et le `node .../vite` qu'il crée survivait à la mort de son parent.
  VITE_TEST_HOOKS=1 VITE_PORT=$FRONT_C VITE_API_TARGET="http://127.0.0.1:$PORT_C" \
    setsid npx vite --port "$FRONT_C" &
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
