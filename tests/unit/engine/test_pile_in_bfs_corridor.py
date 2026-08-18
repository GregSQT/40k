"""Pile-in AUTO BFS 12.03 : les hexes intermédiaires sans cand_fp ne bloquent pas l'exploration.

LE DÉFAUT. ``pile_in_move_destinations_12_03`` explore les ancres candidates par BFS.
Quand ``cand_fp`` était vide à un hex intermédiaire, ``if not cand_fp: continue`` sautait
le bloc d'expansion des voisins (lignes 2574-2578), écrêtant tout le sous-arbre au-delà.
Un hex uniquement atteignable via ce passage n'apparaissait jamais dans ``valid``.

LE FIX. Remplacer ``if not cand_fp: continue`` par ``if cand_fp:`` autour du seul bloc de
validation, en laissant l'expansion des voisins toujours s'exécuter.

PROTOCOLE. ``_fight_synth_cache_entries_at_footprint`` est patché pour retourner ``[]`` sur
tous les hexes ring-1 (distance 1 de l'ancre). Le ring-2 est réel. Sans le fix, la BFS
s'arrête au ring-1 et ``valid`` est vide ; avec le fix, le ring-2 est exploré et des hexes
plus proches de l'ennemi y sont trouvés.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

import pytest

from engine.combat_utils import get_hex_neighbors
from engine.phase_handlers.fight_handlers import pile_in_move_destinations_12_03
from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

SQUAD_ANCHOR = (10, 20)
ENEMY_POS = (10, 10)


@pytest.fixture
def gs() -> Dict[str, Any]:
    """État minimal : escouade S (1 figurine) + ennemi E, hors engagement mutuel."""
    return synthetic_state(
        [
            synthetic_unit("S", 1, [{"col": SQUAD_ANCHOR[0], "row": SQUAD_ANCHOR[1]}]),
            synthetic_unit("E", 2, [{"col": ENEMY_POS[0], "row": ENEMY_POS[1]}]),
        ],
        phase="fight",
        game_rules={"engagement_zone": 1},
    )


def test_bfs_traverse_intermediate_hex_with_empty_cand_fp(gs, monkeypatch):
    """Les hexes à cand_fp vide ne bloquent pas l'expansion BFS — le ring-2 est bien exploré."""
    import engine.phase_handlers.fight_handlers as fh

    ring1: frozenset[Tuple[int, int]] = frozenset(get_hex_neighbors(*SQUAD_ANCHOR))
    _orig = fh._fight_synth_cache_entries_at_footprint

    def _patched(
        unit: Any,
        game_state: Any,
        anchor_col: int,
        anchor_row: int,
        model_placements: Optional[Mapping[str, Tuple[int, int, int]]] = None,
    ) -> List[Dict[str, Any]]:
        if (int(anchor_col), int(anchor_row)) in ring1:
            return []
        return _orig(unit, game_state, anchor_col, anchor_row, model_placements=model_placements)

    monkeypatch.setattr(fh, "_fight_synth_cache_entries_at_footprint", _patched)

    valid = pile_in_move_destinations_12_03(gs, gs["unit_by_id"]["S"], ["E"])

    # Le ring-2 contient des hexes plus proches de l'ennemi (ex. (10,18)).
    # Sans le fix, le BFS s'arrête au ring-1 et valid est vide.
    assert valid, (
        "BFS écrêté au ring-1 : aucun hex valide trouvé bien que le ring-2 soit accessible "
        "et plus proche de l'ennemi. Le fix ``if cand_fp:`` est manquant."
    )
