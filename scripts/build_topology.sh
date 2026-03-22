#!/usr/bin/env bash
# Génère les fichiers de topologie LoS pour le plateau 25x21.
# À exécuter après modification de config/board/25x21/walls/*.json
# Durée estimée : ~20 min sur un NAS (CPU limité).
#
# Usage local :
#   ./scripts/build_topology.sh
#
# Puis commiter les fichiers générés pour des builds Docker rapides :
#   git add config/board/25x21/topology_*.npz
#   git commit -m "Update LoS topology (25x21)"
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
echo "Building LoS topology for 25x21 (walls-01 + tutorial_walls-01)..."
python scripts/los_topology_builder.py 25x21
echo "Done. Files: config/board/25x21/topology_*.npz"
echo "Commit them for fast Docker builds: git add config/board/25x21/topology_*.npz"
