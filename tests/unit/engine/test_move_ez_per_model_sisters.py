"""09.05/09.06/09.07 — « AFTER MOVING: Your unit must be unengaged », y compris pour les SŒURS.

DÉFAUT VERROUILLÉ (mesuré le 2026-08-09 sur un vrai step.log, E3 T3 P2). L'escouade 105 fait un
move NORMAL vers l'ancre (173,61). Son ancre est propre, mais deux de ses figurines — ``105#5``
et ``105#6`` — finissent dans la zone d'engagement de l'unité 1. Le moteur se contredisait dans
le même tour :

  - ``validate_move_plan`` acceptait le plan : son prédicat d'EZ testait la cellule d'ANCRE de
    chaque figurine contre le set HEX dilaté ``enemy_adjacent_hexes_player_N``, ce qui ignore à
    la fois le rayon du socle posé et la métrique EUCLIDIENNE du plateau (×5) ;
  - puis ``fight_v11_is_pile_in_eligible`` rendait la même escouade éligible au pile-in par la
    seule branche « It is engaged » de 12.03, sans charge déclarée.

Le pool d'ancre filtrait bien en euclidien, mais pour UNE base posée à l'ancre candidate : les
sœurs du bloc rigide n'étaient contrôlées que par le set hex, des deux côtés de l'invariant
« masque ⊆ exécutable » — donc jamais de crash pour le signaler.

Les positions ci-dessous sont celles du journal, pas des valeurs choisies pour faire passer un
test. ``_positions_are_the_measured_witness`` verrouille ce fait.
"""

from typing import Any, Dict, Tuple

import pytest

from engine.hex_utils import compute_occupied_hexes
from engine.phase_handlers.fight_handlers import fight_v11_is_pile_in_eligible
from engine.phase_handlers.shared_utils import (
    build_enemy_adjacent_hexes,
    erode_move_pool_by_squad_block,
    explain_move_plan_rejection,
    move_enemy_ez_forbidden_cells,
)
from engine.spatial_relations import entry_has_vertical_data
from tests._state_invariants import turn_state_invariants, unit_invariants

SHAPE, SIZE = "round", 6
INCHES_TO_SUBHEX = 5
EZ_SUBHEX = 10  # engagement_zone 2" × 5 — cf. l'entête « Run rules: » du journal
MOVE_SUBHEX = 60  # large : ce module teste l'EZ, pas le budget

# Unité 1 (P1), positions après son advance du tour — inchangées quand 105 se déplace.
ENEMY = {"1#0": (144, 59), "1#1": (144, 53), "1#2": (138, 53),
         "1#3": (144, 47), "1#4": (138, 47), "1#5": (142, 40)}
# Unité 105 (P2), destination réellement commitée par le moteur défectueux.
DEST = {"105#0": (173, 61), "105#1": (168, 65), "105#2": (167, 59), "105#3": (164, 55),
        "105#4": (162, 67), "105#5": (159, 60), "105#6": (157, 52)}
ANCHOR_DEST = DEST["105#0"]
# Origine (196,44) → le bloc rigide est la translation de la destination.
_DX, _DY = 196 - ANCHOR_DEST[0], 44 - ANCHOR_DEST[1]
ORIGIN = {mid: (c + _DX, r + _DY) for mid, (c, r) in DEST.items()}
# Les deux figurines dont la mesure a montré qu'elles finissent engagées.
ENGAGED_SISTERS = ("105#5", "105#6")


def _fp(col: int, row: int):
    return set(compute_occupied_hexes(col, row, SHAPE, SIZE, 0))


def _union_fp(positions: Dict[str, Tuple[int, int]]):
    out = set()
    for c, r in positions.values():
        out |= _fp(c, r)
    return out


def _entry(positions: Dict[str, Tuple[int, int]], anchor_mid: str, player: int):
    """Entrée units_cache portant les clés que le PRODUCTEUR écrit.

    ``occupied_hexes_by_model`` / ``floor_height_by_model`` / ``MODEL_HEIGHT`` ne sont pas
    décoratives : sans elles, ``entries_in_engagement_zone`` bascule sur son chemin 2D d'ANCRE
    (un socle unique au centre de l'unité) et rend un verdict d'engagement qui n'est pas celui du
    moteur. Une fixture qui les oublie fait passer le test pour la mauvaise raison — c'est
    exactement ce qui a masqué ce défaut pendant la première mesure.
    """
    col, row = positions[anchor_mid]
    return {
        "col": col, "row": row, "player": player, "HP_CUR": 2,
        "BASE_SHAPE": SHAPE, "BASE_SIZE": SIZE, "orientation": 0,
        "occupied_hexes": _union_fp(positions),
        "occupied_hexes_by_model": dict(positions),
        "floor_height_by_model": {mid: 0.0 for mid in positions},
        "MODEL_HEIGHT": 2.0,
    }


def _state(mover_positions: Dict[str, Tuple[int, int]]) -> Dict[str, Any]:
    models_cache: Dict[str, Any] = {}
    for mid, (c, r) in ENEMY.items():
        models_cache[mid] = {"col": c, "row": r, "level": 0, "player": 1, "squad_id": "1",
                             "HP_CUR": 2, "BASE_SHAPE": SHAPE, "BASE_SIZE": SIZE,
                             "orientation": 0}
    for mid, (c, r) in mover_positions.items():
        models_cache[mid] = {"col": c, "row": r, "level": 0, "player": 2, "squad_id": "105",
                             "HP_CUR": 2, "BASE_SHAPE": SHAPE, "BASE_SIZE": SIZE,
                             "orientation": 0}
    enemy_unit = {**unit_invariants(), "id": "1", "player": 1,
                  "col": ENEMY["1#0"][0], "row": ENEMY["1#0"][1], "MOVE": MOVE_SUBHEX,
                  "HP_CUR": 2, "BASE_SHAPE": SHAPE, "BASE_SIZE": SIZE, "UNIT_KEYWORDS": []}
    mover_unit = {**unit_invariants(), "id": "105", "player": 2,
                  "col": mover_positions["105#0"][0], "row": mover_positions["105#0"][1],
                  "MOVE": MOVE_SUBHEX, "HP_CUR": 2, "BASE_SHAPE": SHAPE, "BASE_SIZE": SIZE,
                  "UNIT_KEYWORDS": []}
    gs = {
        **turn_state_invariants(),
        "models_cache": models_cache,
        "squad_models": {"1": list(ENEMY), "105": list(DEST)},
        "units_cache": {"1": _entry(ENEMY, "1#0", 1),
                        "105": _entry(mover_positions, "105#0", 2)},
        "units": [enemy_unit, mover_unit],
        "unit_by_id": {"1": enemy_unit, "105": mover_unit},
        "board_cols": 240, "board_rows": 320,
        "wall_hexes": set(),
        "config": {
            "game_rules": {"engagement_zone": EZ_SUBHEX, "max_base_size_hex": 12},
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
        },
        "phase": "move",
        "inches_to_subhex": INCHES_TO_SUBHEX,
        "units_took_to_skies": set(),
        "terrain_areas": [],
        "units_charged": set(),
        "units_selected_to_fight": set(),
        "engaged_at_fight_step_start": {},
    }
    build_enemy_adjacent_hexes(gs, 1)
    build_enemy_adjacent_hexes(gs, 2)
    return gs


@pytest.fixture
def euclidean(monkeypatch):
    """Épingle la métrique d'engagement.

    ``engagement_distance_metric`` lit le config-loader GLOBAL, pas ``game_state`` : sans cet
    épinglage le test observerait la config du jour au lieu de construire sa situation.
    """
    monkeypatch.setattr(
        "engine.spatial_relations.engagement_distance_metric",
        lambda *args, **kwargs: "euclidean",
    )


def _plan(positions: Dict[str, Tuple[int, int]]):
    return [(mid, c, r, 0) for mid, (c, r) in positions.items()]


_CONSTRAINTS = {"budget_per_model": None, "require_coherency": False, "forbid_enemy_er": True}


# ─────────────────────────────────────────────────────────────────────────────────────────
# Contrôles de la fixture : sans eux, un vert ne prouverait rien (« vert vacant »).
# ─────────────────────────────────────────────────────────────────────────────────────────

def test_fixture_carries_the_producer_keys():
    gs = _state(DEST)
    for uid in ("1", "105"):
        assert entry_has_vertical_data(gs["units_cache"][uid]), (
            f"entrée {uid} sans données par-figurine : la primitive d'engagement basculerait sur "
            "son chemin d'ANCRE et le test mesurerait autre chose que le moteur"
        )


def test_positions_are_the_measured_witness():
    """L'ancre est LOIN, les sœurs sont PRÈS : c'est tout le sujet du défaut."""
    from engine.hex_utils import min_distance_between_sets
    enemy_cells = _union_fp(ENEMY)
    d_anchor = min_distance_between_sets(_fp(*ANCHOR_DEST), enemy_cells, max_distance=99)
    assert d_anchor > EZ_SUBHEX, (
        f"ancre à {d_anchor} de l'ennemi : le témoin exige une ancre HORS zone, sinon le test "
        "passerait déjà avec l'ancien prédicat d'ancre et ne verrouillerait rien"
    )


def test_mover_ez_set_depends_on_the_base_size(euclidean):
    """Le set interdit est fonction du SOCLE POSÉ — c'est la moitié du correctif."""
    gs = _state(ORIGIN)
    small = move_enemy_ez_forbidden_cells(gs, 2, SHAPE, 2, 0)
    big = move_enemy_ez_forbidden_cells(gs, 2, SHAPE, 12, 0)
    assert small < big, (
        "un socle plus grand doit interdire STRICTEMENT plus de cases ; sets identiques = le "
        "prédicat ignore encore la géométrie du mover"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────
# Le verrou
# ─────────────────────────────────────────────────────────────────────────────────────────

def test_normal_move_refused_when_a_sister_ends_engaged(euclidean):
    """09.05 : le plan du témoin doit être REFUSÉ, et pour la bonne figurine."""
    gs = _state(ORIGIN)
    reason = explain_move_plan_rejection(_plan(DEST), gs, _CONSTRAINTS)
    assert reason is not None, (
        "plan accepté alors que deux figurines finissent dans l'EZ ennemie — 09.05 « AFTER "
        "MOVING: Your unit must be unengaged » violé (témoin E3 T3 du 2026-08-09)"
    )
    assert "ER ennemie" in reason, f"refusé pour une autre raison que l'EZ : {reason}"
    assert any(sister in reason for sister in ENGAGED_SISTERS), (
        f"le refus doit nommer une des sœurs engagées {ENGAGED_SISTERS}, pas l'ancre : {reason}"
    )


def test_anchor_alone_would_have_been_accepted(euclidean):
    """Contre-épreuve : l'ANCRE seule est légale. Le refus vient bien des SŒURS."""
    gs = _state(ORIGIN)
    reason = explain_move_plan_rejection(
        [("105#0", ANCHOR_DEST[0], ANCHOR_DEST[1], 0)], gs, _CONSTRAINTS
    )
    assert reason is None, (
        f"l'ancre du témoin devrait rester légale ; refusée pour : {reason} — si elle ne l'est "
        "pas, le correctif sur-filtre et le test ne prouve plus rien sur les sœurs"
    )


def test_engine_no_longer_contradicts_itself(euclidean):
    """La position que le move refuse est bien celle que la phase de combat juge engagée.

    C'est la contradiction d'origine : accepté au move (09.05), engagé au fight (12.03).
    """
    gs_after = _state(DEST)
    mover = gs_after["unit_by_id"]["105"]
    assert fight_v11_is_pile_in_eligible(gs_after, mover), (
        "sans engagement au fight, le témoin ne démontrerait aucune contradiction"
    )
    gs_before = _state(ORIGIN)
    assert explain_move_plan_rejection(_plan(DEST), gs_before, _CONSTRAINTS) is not None, (
        "le move accepte une position que le fight juge engagée : le moteur se contredit encore"
    )


def test_mask_and_execution_agree(euclidean):
    """« masque ⊆ exécutable » : l'érosion doit retirer l'ancre que la validation refuse.

    Les deux côtés lisent le même helper ; ce test échoue si l'un des deux est recâblé seul.
    """
    gs = _state(ORIGIN)
    pool = {ANCHOR_DEST: 1.0}
    kept = erode_move_pool_by_squad_block(gs, "105", dict(pool))
    assert ANCHOR_DEST not in kept, (
        "le masque offre encore une ancre que validate_move_plan refuse — l'agent dépenserait "
        "son activation sur un move rejeté (incohérence masque/exécution)"
    )


def test_hex_metric_also_counts_the_mover_footprint(monkeypatch):
    """Métrique hex : l'ancre est interdite dès que SON EMPREINTE touche le set dilaté.

    Miroir de la branche ``metric == "hex"`` de ``move_anchor_violates_engagement_clearance``,
    que le pool interroge déjà. No-op à ×1 (un socle y tient dans une case) ; ce qui se joue ici
    est un plateau ×N configuré en ``engagement:"hex"``.
    """
    monkeypatch.setattr(
        "engine.spatial_relations.engagement_distance_metric",
        lambda *args, **kwargs: "hex",
    )
    gs = _state(ORIGIN)
    dilated = gs["enemy_adjacent_hexes_player_2"]
    forbidden = move_enemy_ez_forbidden_cells(gs, 2, SHAPE, SIZE, 0)
    touching = [a for a in forbidden if a not in dilated and _fp(*a) & dilated]
    assert touching, (
        "aucune ancre interdite par la seule empreinte : le prédicat hex teste encore la cellule "
        "d'ancre nue, donc il rate les socles multi-cases"
    )
