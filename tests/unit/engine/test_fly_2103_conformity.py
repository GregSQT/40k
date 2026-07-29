#!/usr/bin/env python3
"""Conformité « Take to the skies » (Règles 21.03, PDF `21 Flying and surging`).

Texte de référence (21.03 FLYING MODELS) :

    « Each time a FLYING unit is selected to make a normal, advance, fall-back or charge move,
      before moving any models in that unit, the active player can declare that it will take to
      the skies. If it does, while resolving that move:
        - Subtract 2" from the maximum distance.
        - Each time a FLYING model moves:
            - Ignore all vertical distance for the purposes of how far it has moved.
            - It can move through all types of model (including enemy models and
              MONSTER/VEHICLE models).
            - It can move horizontally and vertically through all categories of terrain feature. »

Trois défauts sont verrouillés ici :

1. **Casse du keyword** — la reconnaissance du keyword FLY doit être insensible à la casse : le
   corpus de rosters écrit `"fly"` (16 fichiers) ET `"FLY"` (6 fichiers), dont cinq types du
   roster d'entraînement d'ArmageddonAgent.
2. **Traversée gratuite en entraînement** — la traversée (murs/figurines/vertical) est la
   CONTREPARTIE d'une déclaration qui coûte 2". Sans déclaration : aucune traversée.
3. **Vol de charge inaccessible à l'IA** — 21.03 nomme explicitement le *charge move*.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pytest

from _config_helpers import build_move_rules
from engine.phase_handlers.movement_handlers import (
    _fly_traversal_active,
    _unit_has_keyword,
    movement_build_valid_destinations_pool,
    took_to_the_skies,
)
from engine.phase_handlers.shared_utils import (
    build_enemy_adjacent_hexes,
    build_units_cache,
    get_squad_move_budget,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARMAGEDDON_ROSTERS = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "rosters" / "500pts"
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Casse du keyword — sur le VRAI roster, chargé par le VRAI chargeur
# ─────────────────────────────────────────────────────────────────────────────


def _armageddon_unit_types() -> List[str]:
    """Tous les `unit_type` cités par les rosters d'ArmageddonAgent (training + holdout)."""
    types: Set[str] = set()
    roster_files = sorted(ARMAGEDDON_ROSTERS.rglob("*.json"))
    assert roster_files, f"aucun roster ArmageddonAgent sous {ARMAGEDDON_ROSTERS}"
    for path in roster_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for entry in payload["composition"]:
            types.add(str(entry["unit_type"]))
            for model in entry.get("models", []):
                # Une figurine s'écrit soit `{"unit_type": ...}`, soit directement son type.
                types.add(str(model["unit_type"]) if isinstance(model, dict) else str(model))
    return sorted(types)


@pytest.fixture(scope="module")
def registry():
    from ai.unit_registry import UnitRegistry

    return UnitRegistry()


def test_armageddon_roster_flying_units_are_recognised_as_flying(registry):
    """Les unités FLY du roster d'ArmageddonAgent, chargées par `UnitRegistry` (le vrai chargeur,
    pas une fixture écrite à la main), DOIVENT être reconnues volantes par le moteur.

    Le chargeur rend la casse telle qu'écrite dans le `.ts` — ici `"FLY"`. Une comparaison stricte
    perdait le keyword en silence : l'agent s'entraînait avec des réacteurs dorsaux qui ne volaient
    pas. On ne code PAS la liste en dur : elle est dérivée du roster réel.
    """
    flying = []
    for unit_type in _armageddon_unit_types():
        data = registry.get_unit_data(unit_type)
        assert data is not None, f"{unit_type} introuvable dans UnitRegistry"
        keywords = data["UNIT_KEYWORDS"]
        raw_has_fly = any(
            str(kw["keywordId"]).strip().lower() == "fly" for kw in keywords
        )
        engine_has_fly = _unit_has_keyword({"id": unit_type, "UNIT_KEYWORDS": keywords}, "fly")
        assert engine_has_fly == raw_has_fly, (
            f"{unit_type}: la donnée porte fly={raw_has_fly} "
            f"(keywords={keywords}) mais le moteur lit {engine_has_fly} — "
            "la reconnaissance du keyword dépend de la casse"
        )
        if raw_has_fly:
            flying.append(unit_type)

    # Sonde : prouve que le test a réellement VU des unités volantes (un roster sans FLY
    # rendrait l'assertion ci-dessus vide de sens).
    assert len(flying) >= 5, (
        f"sonde : seulement {len(flying)} type(s) FLY trouvé(s) dans les rosters "
        f"d'ArmageddonAgent ({flying}) — attendu >= 5"
    )


@pytest.mark.parametrize("written_case", ["fly", "FLY", "Fly", " FLY "])
def test_fly_keyword_recognition_is_case_insensitive(written_case):
    """Le corpus de rosters est mixte ; la LECTURE normalise, comme partout ailleurs dans le
    moteur (`game_state.py`, `shared_utils.compute_hideable`, `attack_sequence`, le front)."""
    unit = {"id": "u", "UNIT_KEYWORDS": [{"keywordId": written_case}]}
    assert _unit_has_keyword(unit, "fly") is True


def test_absent_fly_keyword_is_not_invented():
    """La normalisation ne doit pas rendre le prédicat permissif : sans keyword, pas de vol."""
    assert _unit_has_keyword({"id": "u", "UNIT_KEYWORDS": []}, "fly") is False
    assert (
        _unit_has_keyword({"id": "u", "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}]}, "fly")
        is False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. La traversée est la CONTREPARTIE d'une déclaration qui coûte 2"
# ─────────────────────────────────────────────────────────────────────────────

_START = (5, 10)
#: Anneau de murs autour de `_START` : hors des airs, l'unité est murée.
_WALL_RING = {(5, 9), (6, 10), (6, 11), (5, 11), (4, 11), (4, 10)}


def _fly_gs(
    *,
    move: int,
    gym: bool,
    declared: bool,
    inches_to_subhex: int = 1,
    walls: bool = True,
    phase: str = "move",
) -> Dict[str, Any]:
    """`game_state` minimal centré sur une unique escouade FLY d'un seul modèle."""
    unit: Dict[str, Any] = {
        "id": 1, "player": 1, "col": _START[0], "row": _START[1], "MOVE": move,
        "HP_CUR": 2, "HP_MAX": 2, "VALUE": 50, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SIZE": 1, "BASE_SHAPE": "round", "MODEL_HEIGHT": 2.5,
        # Casse volontairement MAJUSCULE : celle que le vrai chargeur rend pour les unités
        # d'ArmageddonAgent. Un test écrit en minuscules validerait du code que la production
        # n'atteint pas.
        "UNIT_KEYWORDS": [{"keywordId": "FLY"}],
        "UNIT_RULES": [],
    }
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {
                "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            },
            "move": build_move_rules(),
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": phase,
        "wall_hexes": set(_WALL_RING) if walls else set(),
        "units": [unit],
        "unit_by_id": {"1": unit},
        "move_activation_pool": [],
        "units_moved": set(),
        "units_fled": set(),
        "console_logs": [],
        "gym_training_mode": gym,
        "inches_to_subhex": inches_to_subhex,
        "units_took_to_skies": {"1"} if declared else set(),
        "units_took_to_skies_charge": set(),
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, 1)
    return gs


@pytest.mark.parametrize("inches_to_subhex", [1, 2, 4, 5])
def test_taking_to_the_skies_costs_exactly_two_inches_in_subhex(inches_to_subhex):
    """21.03 : « Subtract 2" from the maximum distance. » — 2 POUCES convertis en subhex par
    `inches_to_subhex`, jamais 2 subhexes en dur."""
    move = 20 * inches_to_subhex
    grounded = _fly_gs(
        move=move, gym=False, declared=False, inches_to_subhex=inches_to_subhex, walls=False
    )
    airborne = _fly_gs(
        move=move, gym=False, declared=True, inches_to_subhex=inches_to_subhex, walls=False
    )
    assert get_squad_move_budget("1", grounded, "normal") == move
    assert get_squad_move_budget("1", airborne, "normal") == move - 2 * inches_to_subhex


@pytest.mark.parametrize("gym", [False, True])
@pytest.mark.parametrize("declared", [False, True])
def test_traversal_and_the_two_inch_cost_are_never_dissociated(gym, declared):
    """INVARIANT anti-régression : traverser murs/figurines et payer les 2" sont la MÊME
    déclaration. Le défaut d'origine les avait dissociés en entraînement — le gym traversait
    toujours, sans jamais figurer dans `units_took_to_skies`, donc sans jamais payer.

    En entraînement l'unité déclare systématiquement (politique moteur explicite en attendant
    que la décision soit offerte à l'agent) ; ce qui est verrouillé ici, c'est qu'elle PAIE.
    """
    move = 10
    gs = _fly_gs(move=move, gym=gym, declared=declared, walls=False)
    unit = gs["unit_by_id"]["1"]

    airborne = took_to_the_skies(gs, unit, "1", charge=False)
    assert _fly_traversal_active(gs, unit, "1") is airborne
    expected_budget = move - 2 if airborne else move
    assert get_squad_move_budget("1", gs, "normal") == expected_budget
    if gym:
        assert airborne is True, "une unité FLY pilotée par le modèle déclare (politique moteur)"


def test_without_declaration_a_cell_behind_a_wall_is_unreachable():
    """Sans déclaration, une unité FLY reste une unité au sol : l'anneau de murs l'enferme."""
    gs = _fly_gs(move=5, gym=False, declared=False)
    assert movement_build_valid_destinations_pool(gs, "1") == []


def test_with_declaration_the_wall_is_crossed_and_the_budget_paid_for_it():
    """Avec déclaration : traversée de l'anneau, mais sur un budget amputé de 2"."""
    declared = _fly_gs(move=5, gym=False, declared=True)
    pool_declared = movement_build_valid_destinations_pool(declared, "1")
    assert len(pool_declared) > 0

    # Sonde de coût : à MOVE augmenté de 2", le pool est STRICTEMENT plus large. Si les deux
    # pools étaient égaux, les 2" ne coûteraient rien et le test ne prouverait rien.
    unpaid = _fly_gs(move=5 + 2, gym=False, declared=True)
    assert len(movement_build_valid_destinations_pool(unpaid, "1")) > len(pool_declared)


def test_training_flight_crosses_the_wall_and_pays_for_it():
    """En ENTRAÎNEMENT (chemin de l'agent) : la traversée existe toujours, et elle est facturée."""
    gs = _fly_gs(move=5, gym=True, declared=False)
    assert movement_build_valid_destinations_pool(gs, "1") != []
    assert get_squad_move_budget("1", gs, "normal") == 5 - 2

    # Témoin sol : la même unité SANS le keyword est murée — c'est bien le vol qui franchit.
    grounded = _fly_gs(move=5, gym=True, declared=False)
    grounded["unit_by_id"]["1"]["UNIT_KEYWORDS"] = []
    assert movement_build_valid_destinations_pool(grounded, "1") == []


def test_take_to_the_skies_does_not_leak_outside_the_moves_2103_covers():
    """21.03 énumère « a normal, advance, fall-back or charge move ». Un pile-in ou une
    consolidation (phase fight) n'en font pas partie : pas de traversée hors de ces mouvements."""
    gs = _fly_gs(move=5, gym=True, declared=True, phase="fight")
    assert _fly_traversal_active(gs, gs["unit_by_id"]["1"], "1") is False
