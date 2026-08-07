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
    apply_fly_declaration_decision,
    arm_fly_declaration_decision,
    fly_declaration_decision_is_due,
    movement_build_valid_destinations_pool,
    took_to_the_skies,
)
from engine.phase_handlers.shared_utils import (
    build_enemy_adjacent_hexes,
    build_units_cache,
    charge_build_valid_plan,
    get_squad_move_budget,
)
from tests._state_invariants import turn_state_invariants, unit_invariants


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


@pytest.mark.parametrize("broken", [{}, {"keywordId": None}, {"keyword": "FLY"}])
def test_a_malformed_keyword_entry_raises_instead_of_answering_no(broken):
    """Une entrée sans `keywordId` exploitable est une donnée cassée, pas un keyword absent —
    même traitement que l'entrée non-objet, qui lève déjà. Répondre « cette unité ne vole pas »
    serait une valeur par défaut masquant une erreur."""
    with pytest.raises(ValueError, match="non-null keywordId"):
        _unit_has_keyword({"id": "u", "UNIT_KEYWORDS": [broken]}, "fly")


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
    wall_override: Any = None,
) -> Dict[str, Any]:
    """`game_state` minimal centré sur une unique escouade FLY d'un seul modèle."""
    unit: Dict[str, Any] = {**unit_invariants(),
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
    gs: Dict[str, Any] = {**turn_state_invariants(),
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
        "wall_hexes": (
            set(wall_override) if wall_override is not None
            else (set(_WALL_RING) if walls else set())
        ),
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

    Depuis `L6`, le siège d'entraînement n'a plus de politique moteur : il DÉCLARE PAR UNE ACTION
    (`fly_declaration`), donc `gym` ne change plus rien à cette lecture — c'est exactement ce que
    la paramétrisation croisée vérifie ici.
    """
    move = 10
    gs = _fly_gs(move=move, gym=gym, declared=declared, walls=False)
    unit = gs["unit_by_id"]["1"]

    airborne = took_to_the_skies(gs, unit, "1", charge=False)
    assert airborne is declared, "la déclaration est le SEUL état lu, quel que soit le siège"
    assert _fly_traversal_active(gs, unit, "1") is airborne
    expected_budget = move - 2 if airborne else move
    assert get_squad_move_budget("1", gs, "normal") == expected_budget


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
    """En ENTRAÎNEMENT (chemin de l'agent), la déclaration produit EXACTEMENT le même effet qu'en
    PvP : traversée d'un côté, 2" de l'autre. Depuis `L6` elle vient d'une action de l'agent
    (`fly_declaration`), plus d'une constante moteur — d'où `declared=True` explicite ici."""
    gs = _fly_gs(move=5, gym=True, declared=True)
    assert movement_build_valid_destinations_pool(gs, "1") != []
    assert get_squad_move_budget("1", gs, "normal") == 5 - 2

    # Témoin sol : la même unité SANS le keyword est murée — c'est bien le vol qui franchit.
    grounded = _fly_gs(move=5, gym=True, declared=True)
    grounded["unit_by_id"]["1"]["UNIT_KEYWORDS"] = []
    assert movement_build_valid_destinations_pool(grounded, "1") == []


def test_move_eligibility_is_bounded_by_the_real_budget_not_the_raw_move_stat():
    """Invariant masque ⊆ exécutable (§0.34) : une escouade n'est déclarée ÉLIGIBLE au mouvement
    que si son pool de destinations est non vide.

    Le piège que ce test verrouille : `get_eligible_units` bornait sa recherche sur la
    caractéristique `MOVE` brute, alors que le pool d'une unité volante est construit sur
    `MOVE - 2"` (21.03). Une unité FLY murée jusqu'à la distance `M - 2` et libre au-delà était
    donc annoncée éligible avec un pool VIDE.
    """
    from engine.hex_utils import hex_distance
    from engine.phase_handlers.movement_handlers import get_eligible_units

    move = 5  # budget réel en vol : 5 - 2 = 3
    # Mur plein du disque de rayon 3 autour du départ (départ exclu) : toute destination à portée
    # du budget RÉEL est un mur ; les premières cases libres sont à 4, dans la bande (3, 5].
    walled = {
        (c, r)
        for c in range(25)
        for r in range(21)
        if hex_distance(c, r, _START[0], _START[1]) <= move - 2
        and (c, r) != _START
    }

    gs = _fly_gs(move=move, gym=True, declared=True, wall_override=walled)
    pool = movement_build_valid_destinations_pool(gs, "1")
    assert pool == [], "pré-condition : le budget réel (3) ne sort pas du mur"
    assert "1" not in get_eligible_units(gs), (
        "unité déclarée éligible avec un pool vide — l'éligibilité est bornée par MOVE brut "
        "au lieu du budget réel"
    )

    # Témoin actif : avec 2" de plus, le budget réel franchit le mur et l'unité redevient
    # éligible. Sans ce témoin, l'assertion ci-dessus passerait aussi si `get_eligible_units`
    # ne rendait jamais personne.
    gs_ok = _fly_gs(move=move + 2, gym=True, declared=True, wall_override=walled)
    assert movement_build_valid_destinations_pool(gs_ok, "1") != []
    assert "1" in get_eligible_units(gs_ok)


def test_take_to_the_skies_does_not_leak_outside_the_moves_2103_covers():
    """21.03 énumère « a normal, advance, fall-back or charge move ». Un pile-in ou une
    consolidation (phase fight) n'en font pas partie : pas de traversée hors de ces mouvements."""
    gs = _fly_gs(move=5, gym=True, declared=True, phase="fight")
    assert _fly_traversal_active(gs, gs["unit_by_id"]["1"], "1") is False


def test_a_move_declaration_does_not_grant_traversal_during_the_charge_phase():
    """Les deux déclarations sont DISJOINTES : `units_took_to_skies` vaut pour le move, pas pour
    la charge. Un humain qui a pris les airs en phase de mouvement n'a rien déclaré pour sa charge.

    Verrouille la branche que `_fly_traversal_active` a gagnée : un mutant qui écrirait
    `charge=False` en dur lirait le set du move et accorderait la traversée à tort.
    """
    gs = _fly_gs(move=5, gym=False, declared=True, phase="charge")
    unit = gs["unit_by_id"]["1"]
    assert gs["units_took_to_skies"] == {"1"} and gs["units_took_to_skies_charge"] == set()
    assert _fly_traversal_active(gs, unit, "1") is False

    # Et symétriquement : la déclaration de CHARGE, elle, l'accorde.
    gs["units_took_to_skies_charge"] = {"1"}
    assert _fly_traversal_active(gs, unit, "1") is True


@pytest.mark.parametrize("phase", ["shoot", "charge", "fight"])
def test_the_two_inch_malus_does_not_shrink_the_budget_outside_the_move_phase(phase):
    """21.03 retranche 2" « while resolving THAT move ». Hors phase de mouvement aucun move
    normal/advance/fall-back n'est résolu : le budget interrogé (échelle de la grille égocentrique
    via `grid_half_extent_subhex`, appelée à CHAQUE phase) ne doit pas être amputé.

    Garde symétrique de celle de `_fly_traversal_active` : sans elle, l'échelle de la grille d'une
    unité volante rétrécissait de 2" en tir, charge et combat, là où aucune traversée n'est active.
    """
    move = 10
    in_move = _fly_gs(move=move, gym=True, declared=True, walls=False, phase="move")
    off_move = _fly_gs(move=move, gym=True, declared=True, walls=False, phase=phase)
    assert get_squad_move_budget("1", in_move, "normal") == move - 2
    assert get_squad_move_budget("1", off_move, "normal") == move
    # Le malus et la traversée répondent à la même garde de phase — et au MÊME set : la
    # déclaration de MOVE n'accorde rien hors de la phase de mouvement, pas même en charge, qui
    # a son set dédié (cf. `test_a_move_declaration_does_not_grant_traversal_during_the_charge_phase`).
    assert _fly_traversal_active(off_move, off_move["unit_by_id"]["1"], "1") is False
    if phase == "charge":
        # Témoin actif : c'est bien la déclaration de CHARGE qui ouvre la traversée ici — sans
        # lui, l'assertion ci-dessus passerait aussi si plus rien ne volait jamais.
        off_move["units_took_to_skies_charge"] = {"1"}
        assert _fly_traversal_active(off_move, off_move["unit_by_id"]["1"], "1") is True
        # Et le budget de MOVE reste plein : le malus de charge ne s'y applique pas.
        assert get_squad_move_budget("1", off_move, "normal") == move


# ─────────────────────────────────────────────────────────────────────────────
# 3. 21.03 nomme le CHARGE MOVE : l'IA y a droit, et au même prix
# ─────────────────────────────────────────────────────────────────────────────

_CHARGE_START = (10, 20)
_CHARGE_ENEMY = (14, 20)  # 4 hexes → le B2B le plus proche est à 3 hexes de trajet
_FLOOR_HEIGHT_INCHES = 3.0


def _charge_gs(
    *, fly: bool, level: int = 0, gym: bool = True, declared: bool = False
) -> Dict[str, Any]:
    """`game_state` minimal pour `charge_build_valid_plan` — le chemin d'exécution de l'agent
    (`w40k_core.squad_charge`). `inches_to_subhex = 1`, plancher de niveau 1 haut de 3"."""
    # Casse MAJUSCULE : celle du vrai roster d'ArmageddonAgent.
    keywords = [{"keywordId": "FLY"}] if fly else []
    charger = {**unit_invariants(),
        "id": 1, "player": 1, "col": _CHARGE_START[0], "row": _CHARGE_START[1], "MOVE": 6,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": keywords,
        "level": level,
    }
    target = {**unit_invariants(),
        "id": 2, "player": 2, "col": _CHARGE_ENEMY[0], "row": _CHARGE_ENEMY[1], "MOVE": 6,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [], "level": 0,
    }
    floor_hexes = [
        [_CHARGE_START[0] + dc, _CHARGE_START[1] + dr] for dc in (-1, 0, 1) for dr in (-1, 0, 1)
    ]
    return {**turn_state_invariants(),
        "models_cache": {
            "1#0": {"col": _CHARGE_START[0], "row": _CHARGE_START[1], "level": level,
                    "player": 1, "squad_id": "1", "HP_CUR": 1, "BASE_SHAPE": "round",
                    "BASE_SIZE": 1, "orientation": 0},
            "2#0": {"col": _CHARGE_ENEMY[0], "row": _CHARGE_ENEMY[1], "level": 0,
                    "player": 2, "squad_id": "2", "HP_CUR": 1, "BASE_SHAPE": "round",
                    "BASE_SIZE": 1, "orientation": 0},
        },
        "squad_models": {"1": ["1#0"], "2": ["2#0"]},
        "units_cache": {
            "1": {"col": _CHARGE_START[0], "row": _CHARGE_START[1], "player": 1,
                  "occupied_hexes": {_CHARGE_START}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "2": {"col": _CHARGE_ENEMY[0], "row": _CHARGE_ENEMY[1], "player": 2,
                  "occupied_hexes": {_CHARGE_ENEMY}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
        },
        "units": [charger, target],
        "unit_by_id": {"1": charger, "2": target},
        "board_cols": 44, "board_rows": 60,
        "wall_hexes": set(),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": 1, "unit_model_cohesion_range": 2,
                           "unit_global_cohesion_range": 9,
                           "cohesion_distance_mode": "euclidean", "squad_min_neighbors": 1},
            # 11.04 EFFECT : le charge move borne chaque figurine par son TRAJET, comme le move —
            # les toggles de traversée réels lui sont donc exigés (même helper que la fixture
            # de move ci-dessus, jamais des constantes recopiées).
            "move": build_move_rules(),
        },
        "phase": "charge",
        "gym_training_mode": gym,
        "inches_to_subhex": 1,
        "units_took_to_skies": set(),
        "units_took_to_skies_charge": {"1"} if declared else set(),
        "units_advanced": set(),
        "units_fled": set(),
        "current_player": 1,
        "terrain_areas": [
            {"floors": [{"level": 1, "height_inches": _FLOOR_HEIGHT_INCHES,
                         "hexes": floor_hexes}]},
        ],
    }


def test_ai_flying_unit_can_take_to_the_skies_on_a_charge():
    """21.03 : « Each time a FLYING unit is selected to make a normal, advance, fall-back or
    CHARGE move [...] the active player can declare that it will take to the skies. » Le vol de
    charge était refusé à toute unité pilotée par le modèle ; il lui est ouvert DÈS LORS qu'elle
    l'a déclaré (`L6` : `CHOICE_0` de `fly_declaration`)."""
    from engine.phase_handlers.charge_handlers import _charge_fly_active

    gs = _charge_gs(fly=True, declared=True)
    assert _charge_fly_active(gs, gs["unit_by_id"]["1"], "1") is True

    # Sans le keyword, la déclaration ne donne rien : c'est FLY qui ouvre 21.03.
    grounded = _charge_gs(fly=False, declared=True)
    assert _charge_fly_active(grounded, grounded["unit_by_id"]["1"], "1") is False


def test_ai_charge_flight_pays_the_two_inches_on_the_execution_path():
    """Sur `charge_build_valid_plan` — la fonction qu'exécute `squad_charge`, donc l'agent — le
    vol de charge coûte 2" comme n'importe quelle prise d'altitude. Un jet qui suffit au sol ne
    suffit plus en vol ; il faut 2" de plus."""
    # Trajet requis jusqu'à l'ENGAGEMENT : 2 subhex (03.04 — l'ER est une zone de 2", pas la
    # cellule voisine du centre ennemi ; à `inches_to_subhex = 1` elle porte donc à 2 subhex).
    assert charge_build_valid_plan(_charge_gs(fly=False), "1", ["2"], 2) is not None
    assert charge_build_valid_plan(_charge_gs(fly=True, declared=True), "1", ["2"], 2) is None
    assert charge_build_valid_plan(_charge_gs(fly=True, declared=True), "1", ["2"], 4) is not None


def test_ai_charge_flight_ignores_vertical_distance_but_still_pays():
    """Depuis un étage : le vol supprime le coût de descente (« Ignore all vertical distance »)
    et facture 2". Les deux effets sortent de la MÊME déclaration."""
    # Descente = 3 subhex (plancher de niveau 1 haut de 3"), trajet jusqu'à l'engagement = 2.
    # Au sol : jet 4 → budget 4 - 3 = 1 < 2 → impossible.
    assert charge_build_valid_plan(_charge_gs(fly=False, level=1), "1", ["2"], 4) is None
    # En vol : jet 4 → budget 4 - 2 (skies) - 0 (vertical ignoré) = 2 → possible.
    assert charge_build_valid_plan(_charge_gs(fly=True, level=1, declared=True), "1", ["2"], 4) is not None
    # Mais le vol ne rend pas la charge gratuite : jet 3 → budget 1 < 2.
    assert charge_build_valid_plan(_charge_gs(fly=True, level=1, declared=True), "1", ["2"], 3) is None


def test_human_charge_flight_still_requires_an_explicit_declaration():
    """Le joueur humain, lui, déclare : sans déclaration, pas de vol de charge."""
    from engine.phase_handlers.charge_handlers import _charge_fly_active

    gs = _charge_gs(fly=True, gym=False)
    assert _charge_fly_active(gs, gs["unit_by_id"]["1"], "1") is False
    gs["units_took_to_skies_charge"] = {"1"}
    assert _charge_fly_active(gs, gs["unit_by_id"]["1"], "1") is True


# ─────────────────────────────────────────────────────────────────────────────
# 4. Preuve IN-ENGINE — pas une reconstruction hors moteur
# ─────────────────────────────────────────────────────────────────────────────

_ARMAGEDDON_TRAINING_SCENARIO = (
    "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json"
)


def test_in_engine_armageddon_flying_units_fly_and_pay_for_it():
    """Sur le VRAI chemin : un `W40KEngine` construit sur le scénario d'entraînement
    d'ArmageddonAgent, avec `gym_training_mode=True` — exactement ce que passe
    `ai/training_utils.py`. Aucune reconstruction hors moteur.

    Depuis `L6` la déclaration n'est plus une constante : la sonde passe donc par le POINT DE
    CHOIX réel (`arm_fly_declaration_decision` + `apply_fly_declaration_decision`), et vérifie
    les DEUX candidats — `CHOICE_0` fait voler et facture, `CHOICE_1` laisse l'unité au sol au
    prix plein. C'est ce couple qui prouve que le choix EXISTE, là où l'ancienne sonde ne
    pouvait constater qu'une politique.

    La sonde ÉCHOUE si elle n'a rien vu : « aucune violation » ne peut pas vouloir dire « la
    sonde n'a rien regardé ». Le scénario tire son roster au sort (`training_random`) parmi
    deux ; on rejoue jusqu'à rencontrer celui qui porte les unités à réacteurs.
    """
    from ai.unit_registry import UnitRegistry
    from engine.phase_handlers.charge_handlers import _charge_fly_active
    from engine.w40k_core import W40KEngine

    env = W40KEngine(
        rewards_config="default",
        training_config_name="x1",
        controlled_agent="ArmageddonAgent",
        active_agents=None,
        scenario_file=_ARMAGEDDON_TRAINING_SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )

    inspected = 0
    flying_seen: Dict[str, Tuple[int, int]] = {}
    for _ in range(25):
        if flying_seen:
            break
        env.reset()
        gs = env.game_state
        assert gs["gym_training_mode"] is True, "le flag d'entraînement n'atteint pas game_state"
        ish = int(gs["inches_to_subhex"])
        for unit in gs["units"]:
            inspected += 1
            if not _unit_has_keyword(unit, "fly"):
                continue
            uid = str(unit["id"])
            utype = str(unit["unitType"])

            # 1. AVANT toute déclaration : rien n'est acquis. C'est ce que `L6` change — le
            #    keyword FLY n'emporte plus la traversée, il ouvre seulement le choix.
            for phase, charge in (("move", False), ("charge", True)):
                gs["phase"] = phase
                assert took_to_the_skies(gs, unit, uid, charge=charge) is False, f"{utype}/{phase}"
                assert _fly_traversal_active(gs, unit, uid) is False, f"{utype}/{phase}"
                assert fly_declaration_decision_is_due(gs, uid) is True, f"{utype}/{phase}"

            # 2. CHOICE_1 (« ne pas déclarer ») : toujours au sol, et budget PLEIN.
            gs["phase"] = "move"
            assert arm_fly_declaration_decision(gs, uid) is True, utype
            apply_fly_declaration_decision(gs, uid, False)
            assert took_to_the_skies(gs, unit, uid, charge=False) is False, utype
            assert get_squad_move_budget(uid, gs, "normal") == int(unit["MOVE"]), utype
            # La question est CONSOMMÉE : elle ne se repose pas au masque suivant.
            assert fly_declaration_decision_is_due(gs, uid) is False, utype

            # 3. CHOICE_0 (« déclarer ») en CHARGE — jumeau, set dédié : traversée ET 2".
            gs["phase"] = "charge"
            assert arm_fly_declaration_decision(gs, uid) is True, utype
            apply_fly_declaration_decision(gs, uid, True)
            assert took_to_the_skies(gs, unit, uid, charge=True) is True, utype
            assert _charge_fly_active(gs, unit, uid) is True, utype
            # Le set du move est resté vide : les deux déclarations sont disjointes.
            assert uid not in gs["units_took_to_skies"], utype

            # 4. Et déclarer PAIE : 2 POUCES convertis par `inches_to_subhex`.
            gs["phase"] = "move"
            gs["units_took_to_skies"].add(uid)
            budget = get_squad_move_budget(uid, gs, "normal")
            assert budget == max(0, int(unit["MOVE"]) - 2 * ish), utype
            flying_seen[utype] = (int(unit["MOVE"]), budget)

    assert inspected > 0, "SONDE MUETTE : aucune unité inspectée"
    assert flying_seen, (
        f"SONDE MUETTE : aucune unité volante rencontrée en 25 tirages de roster "
        f"({inspected} unités inspectées)"
    )
