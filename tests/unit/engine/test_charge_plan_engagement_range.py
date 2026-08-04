"""Verrou : le plan de charge du chemin gym vise la ZONE D'ENGAGEMENT, pas la cellule voisine.

Deux defauts fermes ici, tous deux dans `charge_build_valid_plan` — la fonction qu'execute
`w40k_core.squad_charge`, donc l'agent, et que l'observation interroge comme oracle.

1. **Destination**. Les candidats « au contact » etaient les VOISINS HEXAGONAUX du centre d'une
   figurine cible. A `inches_to_subhex = 5` un voisin est a 0,2" quand l'engagement range en
   vaut 2 (03.04) : le plan exigeait ~1,8" de trajet de plus que la regle. Mesure sur le modele
   du 2026-08-01 : **0 charge reussie sur 23 declarations**, alors que l'agent choisissait la
   charge 70 % des fois ou le masque la proposait.

2. **Validation finale**. Elle exigeait que TOUTES les figurines finissent engagees. 11.04
   AFTER MOVING dit « **your unit** must be engaged with all of the charge targets » et 03.04
   « while a friendly model is within engagement range of one or more enemy models, those
   models — **and the units they belong to** — are engaged » : UNE figurine suffit a engager
   l'unite. Aucune formation ne met douze socles au contact du meme ennemi.

Corollaire du point 2, verrouille par `test_trailing_models_follow_the_charge` : les figurines
qui ne peuvent pas engager doivent SUIVRE (le plan avance chacune au plus loin de son budget),
sans quoi la coherency (03.03) rejette le plan et l'escouade nombreuse ne charge jamais.

Geometrie : `inches_to_subhex = 5` (l'echelle d'entrainement), `engagement_zone = 10` subhex
= 2". Cible a 45 subhex = 9" : le trajet vers l'ENGAGEMENT vaut 35 subhex (jet 7), celui vers
la cellule voisine du centre en valait 44 (jet 9).
"""

from typing import Any, Dict, List, Tuple

import pytest

from engine.phase_handlers.shared_utils import (
    calculate_hex_distance,
    charge_build_valid_plan,
    get_engagement_zone,
)
from tests._state_invariants import turn_state_invariants, unit_invariants

ISH = 5
CHARGER_COL = 100
CHARGER_ROW = 84
TARGET = (145, 84)
#: Jet qui couvre le trajet vers l'engagement (45 - 10 = 35 subhex) et pas le trajet vers la
#: cellule voisine du centre ennemi (44 subhex).
ROLL_REACHES_ENGAGEMENT = 7
ROLL_TOO_SHORT = 6


def _gs(charger_cols: List[int]) -> Dict[str, Any]:
    """`game_state` minimal : escouade « 1 » en file vers l'est, cible « 2 » a l'est.

    Les figurines sont espacees de 10 subhex (= 2", la coherency 03.03) SUR LA MEME LIGNE :
    en geometrie cube, s'etaler en `row` a `col` constante ne change pas la distance a une
    cible situee plein est — les trois figurines seraient alors a egale portee et le test ne
    distinguerait plus « unite engagee » de « toutes les figurines engagees ».
    """
    charger_positions = [(c, CHARGER_ROW) for c in charger_cols]
    unit1 = {**unit_invariants(),
        "id": 1, "player": 1, "col": charger_positions[0][0], "row": charger_positions[0][1],
        "MOVE": 6, "HP_CUR": len(charger_positions), "BASE_SIZE": 1, "BASE_SHAPE": "round",
        "UNIT_KEYWORDS": [], "level": 0,
    }
    unit2 = {**unit_invariants(),
        "id": 2, "player": 2, "col": TARGET[0], "row": TARGET[1], "MOVE": 6,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [], "level": 0,
    }
    models_cache: Dict[str, Any] = {}
    for i, (col, row) in enumerate(charger_positions):
        models_cache[f"1#{i}"] = {
            "col": col, "row": row, "level": 0, "player": 1, "squad_id": "1", "HP_CUR": 1,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        }
    models_cache["2#0"] = {
        "col": TARGET[0], "row": TARGET[1], "level": 0, "player": 2, "squad_id": "2",
        "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
    }
    return {**turn_state_invariants(),
        "models_cache": models_cache,
        "squad_models": {
            "1": [f"1#{i}" for i in range(len(charger_positions))],
            "2": ["2#0"],
        },
        "units_cache": {
            "1": {"col": charger_positions[0][0], "row": charger_positions[0][1], "player": 1,
                  "occupied_hexes": set(charger_positions), "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "2": {"col": TARGET[0], "row": TARGET[1], "player": 2,
                  "occupied_hexes": {TARGET}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
        },
        "units": [unit1, unit2],
        "unit_by_id": {"1": unit1, "2": unit2},
        "board_cols": 200, "board_rows": 160,
        "wall_hexes": set(),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            # Portees DEJA converties en subhex, comme w40k_core les pre-scale a l'init :
            # 2" -> 10, 9" -> 45 (cf. get_coherency_subhex / get_cohesion_max_subhex).
            "game_rules": {"engagement_zone": 10, "unit_model_cohesion_range": 10,
                           "unit_global_cohesion_range": 45,
                           "cohesion_distance_mode": "euclidean", "squad_min_neighbors": 1},
            # Toggles de traversee 03.01, valeurs de `config/game_config.json`. Exiges depuis que
            # la borne de charge passe par le TRAJET (`model_reach_predicate`, 11.04 EFFECT) et
            # non plus par une distance a vol d'oiseau : le champ geodesique a besoin des
            # obstacles de transit.
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
        },
        "phase": "charge",
        "gym_training_mode": True,
        "inches_to_subhex": ISH,
        "current_player": 1,
        "terrain_areas": [],
    }


def _plan_positions(plan: List[Tuple[str, int, int, int]]) -> Dict[str, Tuple[int, int]]:
    return {mid: (col, row) for mid, col, row, _lvl in plan}


def test_fixture_target_is_out_of_neighbour_reach_but_within_engagement_reach():
    """La fixture DOIT etre dans la fenetre qui separe les deux regles, sinon elle ne prouve rien.

    Trajet vers l'engagement = 35 subhex (jet 7 x 5 = 35) ; trajet vers la cellule voisine du
    centre ennemi = 44. Un jet de 7 tranche donc entre les deux lectures.
    """
    gs = _gs([CHARGER_COL])
    assert get_engagement_zone(gs) == 10
    assert calculate_hex_distance(CHARGER_COL, CHARGER_ROW, *TARGET) == 45
    assert ROLL_REACHES_ENGAGEMENT * ISH == 35
    assert 35 < 44  # le voisin du centre reste hors de portee de ce jet


def test_single_model_charge_reaches_engagement_range():
    """Le defaut n°1, isole : une figurine, aucune coherency, aucun obstacle."""
    plan = charge_build_valid_plan(_gs([CHARGER_COL]), "1", ["2"], ROLL_REACHES_ENGAGEMENT)
    assert plan is not None, "charge a portee d'engagement refusee"
    assert len(plan) == 1
    _mid, col, row, _lvl = plan[0]
    assert calculate_hex_distance(CHARGER_COL, CHARGER_ROW, col, row) <= ROLL_REACHES_ENGAGEMENT * ISH


def test_single_model_charge_still_fails_when_the_roll_is_short():
    """Contre-epreuve : la correction n'ouvre pas la charge a n'importe quel jet.

    Jet 6 → budget 30 < 35 : la cible reste hors d'atteinte, meme a l'engagement range.
    """
    assert charge_build_valid_plan(_gs([CHARGER_COL]), "1", ["2"], ROLL_TOO_SHORT) is None


def test_squad_charges_when_a_single_model_can_engage():
    """Le defaut n°2 : l'UNITE est engagee des qu'UNE figurine l'est (11.04 + 03.04)."""
    gs = _gs([CHARGER_COL, CHARGER_COL - 10, CHARGER_COL - 20])
    plan = charge_build_valid_plan(gs, "1", ["2"], ROLL_REACHES_ENGAGEMENT)
    assert plan is not None, "charge d'escouade refusee alors qu'une figurine peut engager"
    assert len(plan) == 3

    from engine.spatial_relations import unit_entries_within_engagement_zone
    from engine.phase_handlers.shared_utils import _synth_model_entry

    ez = get_engagement_zone(gs)
    target_entry = gs["units_cache"]["2"]
    engaged = [
        mid for mid, col, row, _lvl in plan
        if unit_entries_within_engagement_zone(
            _synth_model_entry(gs, "1", gs["models_cache"][mid], col, row), target_entry, ez
        )
    ]
    assert engaged, "aucune figurine engagee : la charge ne serait pas legale"
    assert len(engaged) < 3, (
        "fixture invalide : si les trois figurines engagent, ce test ne distingue pas "
        "« unite engagee » de « toutes les figurines engagees »"
    )


def test_trailing_models_follow_the_charge():
    """Les figurines qui ne peuvent pas engager avancent au plus loin de leur budget.

    Sans cela, elles restent sur place pendant que la premiere bondit au contact : la coherency
    (03.03) rejette le plan et l'escouade ne charge jamais. On verifie donc les deux bornes de
    11.04 : chaque figurine finit PLUS PRES d'une cible (WHILE MOVING) et dans le budget
    (MAXIMUM DISTANCE = le jet).
    """
    gs = _gs([CHARGER_COL, CHARGER_COL - 10, CHARGER_COL - 20])
    plan = charge_build_valid_plan(gs, "1", ["2"], ROLL_REACHES_ENGAGEMENT)
    assert plan is not None
    budget = ROLL_REACHES_ENGAGEMENT * ISH
    for mid, col, row, _lvl in plan:
        origin = gs["models_cache"][mid]
        moved = calculate_hex_distance(int(origin["col"]), int(origin["row"]), col, row)
        assert moved <= budget, f"{mid} a parcouru {moved} > {budget} (11.04 MAXIMUM DISTANCE)"
        before = calculate_hex_distance(int(origin["col"]), int(origin["row"]), *TARGET)
        after = calculate_hex_distance(col, row, *TARGET)
        assert after < before, f"{mid} ne finit pas plus pres de la cible (11.04 WHILE MOVING)"

    from engine.phase_handlers.shared_utils import _validate_plan_coherency

    assert _validate_plan_coherency(_plan_positions(plan), gs), "plan hors coherency (03.03)"


@pytest.mark.parametrize("roll", [1, 2, 3, 4, 5])
def test_short_rolls_never_produce_a_plan(roll: int) -> None:
    """Aucun jet inferieur au trajet requis ne doit produire de plan (borne basse du verrou)."""
    assert charge_build_valid_plan(_gs([CHARGER_COL]), "1", ["2"], roll) is None


@pytest.mark.parametrize("radius", [0, 1, 2, 5, 10, 13])
@pytest.mark.parametrize("origin", [(100, 84), (101, 84), (100, 85), (7, 3)])
def test_the_engagement_disc_is_a_complete_superset(
    radius: int, origin: Tuple[int, int]
) -> None:
    """`_hex_cells_within_radius` doit rendre TOUTES les cellules du disque, pas presque.

    C'est la primitive qui borne la recherche de destinations : une cellule oubliee est une
    charge refusee en silence, jamais une erreur. La borne sur `d_row` est large expres (la
    conversion offset -> cube decale la ligne d'environ `d_col / 2`) ; on la confronte ici a
    une enumeration par force brute, sur des colonnes PAIRES et IMPAIRES — le decalage depend
    de la parite, et une borne juste sur l'une peut amputer l'autre.
    """
    from engine.phase_handlers.shared_utils import _hex_cells_within_radius

    col, row = origin
    span = 3 * radius + 4
    expected = {
        (col + dc, row + dr)
        for dc in range(-span, span + 1)
        for dr in range(-span, span + 1)
        if calculate_hex_distance(col, row, col + dc, row + dr) <= radius
    }

    assert set(_hex_cells_within_radius(col, row, radius)) == expected


def test_the_engagement_disc_is_empty_for_a_negative_radius() -> None:
    """Rayon negatif : aucune cellule (et surtout pas la cellule d'origine)."""
    from engine.phase_handlers.shared_utils import _hex_cells_within_radius

    assert list(_hex_cells_within_radius(100, 84, -1)) == []
