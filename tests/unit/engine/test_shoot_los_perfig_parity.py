"""LoS de tir — la règle 06.01 est PER-FIGURINE (socle entier), jamais ancre-à-ancre.

Contexte (2026-07-16). `ai/analyzer.py` signalait « 1.2 Erreurs en phase de shooting : 12 » sur un
run réel : 6 `shoot_through_wall` + 6 `shoot_invalid.no_los` = les mêmes 6 tirs. Verdict après
enquête : **faux positifs de l'analyzer, aucune violation moteur**. Le contrôle testait la LoS
ANCRE-A-ANCRE (`has_line_of_sight(shooter_col, shooter_row, ...)`), un point contre un point.

Règle 06.01 (« 06 Other concepts.pdf ») : « For an observing model to have line of sight, it must
be possible to draw an imaginary straight line, 1 mm wide, **from any part of that model to any
part of the model being observed** ». La LoS est donc socle-à-socle. Un test ancre-à-ancre est
strictement plus restrictif que la règle → il invente des blocages.

Le contrôle de l'analyzer a été SUPPRIMÉ (il n'était pas réparable : reproduire fidèlement le
prédicat moteur exige `game_state` — empreintes, terrain obscurcissant 13.10, LoS 3D — que
step.log ne porte pas). La vérification est déplacée ICI, où `game_state` existe.

Ce que ce fichier verrouille :
- l'écart ancre↔per-figurine est RÉEL et non nul (sinon le test ne prouverait rien) ;
- sur cette géométrie, l'ancre est bloquée et le moteur voit quand même — comportement 06.01 ;
- une régression du moteur vers un test ancre-à-ancre casse ce test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Géométrie minimale reproduisant le faux positif observé sur le run réel : un mur plein devant
# le tireur, troué d'une seule cellule (row 49) décalée de l'ancre (row 50). La ligne
# ancre→cible tape le mur ; une cellule haute de l'empreinte du socle enfile le trou.
SHOOTER_ANCHOR = (50, 50)
TARGET_ANCHOR = (80, 50)
WALL_COL = 60
WALL_GAP_ROW = 49
WALL_ROWS = range(40, 61)

# Socle round/6 = 19 hexes (rayon 2) sur le board actif 44x60x5 (engagement_zone=2 > 1, donc les
# empreintes multi-hex sont bien calculées — cf. _compute_unit_occupied_hexes).
BASE_ROUND_6 = {"BASE_SHAPE": "round", "BASE_SIZE": 6}


@pytest.fixture
def game_state():
    """game_state minimal. `_compute_visibility_with_obscuring` n'y touche PAS quand `wall_set` et
    `obscuring_by_hex` sont fournis explicitement ; seul `_compute_unit_occupied_hexes` lit
    game_rules (engagement_zone) pour dimensionner l'empreinte."""
    game_config = json.loads((PROJECT_ROOT / "config" / "game_config.json").read_text())
    return {"config": {"game_rules": game_config["game_rules"]}, "inches_to_subhex": 5}


@pytest.fixture
def walls():
    return {(WALL_COL, r) for r in WALL_ROWS if r != WALL_GAP_ROW}


def _footprint(game_state, anchor):
    from engine.phase_handlers.shared_utils import _compute_unit_occupied_hexes

    return sorted(_compute_unit_occupied_hexes(anchor[0], anchor[1], dict(BASE_ROUND_6), game_state))


def test_footprint_is_multi_hex(game_state):
    """Garde-fou : si l'empreinte retombait à 1 hex, per-fig == ancre et les tests suivants
    passeraient pour de mauvaises raisons (cf. `engagement_zone <= 1` → mono-cellule)."""
    footprint = _footprint(game_state, SHOOTER_ANCHOR)
    assert len(footprint) == 19, f"socle round/6 attendu à 19 hexes, obtenu {len(footprint)}"
    assert SHOOTER_ANCHOR in footprint


def test_anchor_to_anchor_los_is_blocked(game_state, walls):
    """Prémisse du faux positif : le contrôle ancre-à-ancre de l'analyzer refusait ce tir."""
    from engine.hex_utils import compute_los_state

    _, can_see = compute_los_state(
        SHOOTER_ANCHOR[0], SHOOTER_ANCHOR[1], TARGET_ANCHOR[0], TARGET_ANCHOR[1], walls
    )
    assert can_see is False, "géométrie invalide : l'ancre doit être bloquée pour que le test prouve quelque chose"


def test_engine_sees_target_from_footprint_edge_rule_06_01(game_state, walls):
    """Règle 06.01 : « any part of that model to any part of the model being observed ».

    L'ancre du socle est masquée, mais une cellule de l'empreinte enfile le trou du mur → le
    moteur DOIT voir. C'est précisément le tir que l'analyzer comptait comme
    « shoot_through_wall ». Une régression vers un test ancre-à-ancre rendrait visible == 0.
    """
    from engine.phase_handlers.shooting_handlers import _compute_visibility_with_obscuring

    shooter_hexes = _footprint(game_state, SHOOTER_ANCHOR)
    target_hexes = [TARGET_ANCHOR]

    visible, total, _ = _compute_visibility_with_obscuring(
        game_state, SHOOTER_ANCHOR, shooter_hexes, TARGET_ANCHOR, target_hexes,
        wall_set=walls, obscuring_by_hex={},
    )

    assert total == 1
    assert visible == 1, (
        "06.01 violé : l'empreinte du socle voit la cible (une cellule enfile le trou du mur) "
        "mais le moteur la déclare masquée — régression vers une LoS ancre-à-ancre ?"
    )


def test_wall_without_gap_blocks_even_per_figurine(game_state):
    """Contre-épreuve : sans le trou, AUCUNE cellule de l'empreinte ne voit. Sans ce test, une
    implémentation qui rendrait toujours `visible > 0` passerait le test précédent."""
    from engine.phase_handlers.shooting_handlers import _compute_visibility_with_obscuring

    solid_wall = {(WALL_COL, r) for r in WALL_ROWS}
    shooter_hexes = _footprint(game_state, SHOOTER_ANCHOR)

    visible, total, _ = _compute_visibility_with_obscuring(
        game_state, SHOOTER_ANCHOR, shooter_hexes, TARGET_ANCHOR, [TARGET_ANCHOR],
        wall_set=solid_wall, obscuring_by_hex={},
    )

    assert total == 1
    assert visible == 0, "un mur plein doit bloquer la LoS de TOUTES les cellules du socle"
