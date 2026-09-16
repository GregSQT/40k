#!/usr/bin/env bash
# Lance ai/train.py avec nice -n 15 pour laisser le serveur de jeu réactif en parallèle.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec nice -n 15 python3 "$PROJECT_ROOT/ai/train.py" "$@"
