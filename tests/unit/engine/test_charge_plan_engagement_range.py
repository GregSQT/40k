"""Verrou : le plan de charge du chemin gym vise la ZONE D'ENGAGEMENT, pas la cellule voisine.

Deux defauts fermes ici, tous deux dans `charge_build_valid_plan` — la fonction qu'execute
`w40k_core.squad_charge`, donc l'agent, et que l'observation interroge comme oracle.

1. **Destination**. Les candidats « au contact » etaient les VOISINS HEXAGONAUX du centre d'une
   figurine cible. A `inches_to_subhex = 5` un voisin est a 0,2" quand l'engagement range en
   vaut 2 (03.04) : le plan exigeait ~1,8" de trajet de plus que la regle. Mesure sur le modele
   du 2026-08-01 : **0 charge reussie sur 23 declarations**, alors que l'agent choisissait la
   charge 70 % des fois ou le masque la proposait. Pire sur un socle large, ce que la fixture
   reproduit desormais : les voisins du centre sont A L'INTERIEUR du socle cible, donc occupes,
   donc AUCUNE destination n'existait, quel que soit le jet.

2. **Validation finale**. Elle exigeait que TOUTES les figurines finissent engagees. 11.04
   AFTER MOVING dit « **your unit** must be engaged with all of the charge targets » et 03.04
   « while a friendly model is within engagement range of one or more enemy models, those
   models — **and the units they belong to** — are engaged » : UNE figurine suffit a engager
   l'unite. Aucune formation ne met douze socles au contact du meme ennemi.

Corollaire du point 2, verrouille par `test_trailing_models_follow_the_charge` : les figurines
qui ne peuvent pas engager doivent SUIVRE (le plan avance chacune au plus loin de son budget),
sans quoi la coherency (03.03) rejette le plan et l'escouade nombreuse ne charge jamais.

Geometrie : `inches_to_subhex = 5` (l'echelle d'entrainement), `engagement_zone = 10` subhex
= 2". Cible a 45 subhex de CENTRE a centre, sur un socle de 11 subhex (2,2", un socle de
monstre) : 40 subhex bord a bord, et un trajet de 30 subhex pour venir a l'engagement.

La borne de declaration 11.04 (« within the maximum distance of your unit ») se lit donc
directement sur ces trois nombres : un jet de 8 (40 subhex) couvre la distance BORD A BORD et
la charge est declarable ; un jet de 7 (35) ne la couvre pas — et ce, bien que le trajet de 30
tienne largement dans son budget. C'est exactement ce qui manquait au moteur jusqu'au
2026-08-08 : il ne bornait que le TRAJET, donc acceptait toute cible a jet + ez, soit une
portee de charge doublee.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

from engine.hex_utils import compute_occupied_hexes
from engine.phase_handlers.shared_utils import (
    _synth_model_entry,
    calculate_hex_distance,
    charge_build_valid_plan,
    get_engagement_zone,
)
from engine.spatial_relations import unit_entries_within_engagement_zone
from tests._state_invariants import turn_state_invariants, unit_invariants

ISH = 5
CHARGER_COL = 100
CHARGER_ROW = 84
TARGET = (145, 84)
#: Socle de la cible, en subhex (2,2" a ISH = 5). Large expres : les voisins hexagonaux du
#: centre ennemi tombent alors DANS le socle, donc la lecture « destination = voisin du centre »
#: ne rend aucune cellule legale, quand la lecture ZONE D'ENGAGEMENT en rend un arc entier.
TARGET_BASE_SIZE = 11
#: Jet qui couvre la distance BORD A BORD (40 subhex) : la cible est declarable (11.04) et le
#: trajet vers l'engagement (30 subhex) tient dans le budget.
ROLL_REACHES_ENGAGEMENT = 8
#: Jet dont le budget (35) couvre le TRAJET (30) mais PAS la distance bord a bord (40) : la
#: cible n'est pas selectionnable, la charge echoue. Verrou de la borne 11.04.
ROLL_TOO_SHORT = 7


def _gs(
    charger_cols: List[int], bystander_cells: Optional[List[Tuple[int, int]]] = None
) -> Dict[str, Any]:
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
        "HP_CUR": 1, "BASE_SIZE": TARGET_BASE_SIZE, "BASE_SHAPE": "round",
        "UNIT_KEYWORDS": [], "level": 0,
    }
    target_footprint = set(
        compute_occupied_hexes(TARGET[0], TARGET[1], "round", TARGET_BASE_SIZE, 0)
    )
    models_cache: Dict[str, Any] = {}
    for i, (col, row) in enumerate(charger_positions):
        models_cache[f"1#{i}"] = {
            "col": col, "row": row, "level": 0, "player": 1, "squad_id": "1", "HP_CUR": 1,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        }
    models_cache["2#0"] = {
        "col": TARGET[0], "row": TARGET[1], "level": 0, "player": 2, "squad_id": "2",
        "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": TARGET_BASE_SIZE, "orientation": 0,
    }
    units = [unit1, unit2]
    squad_models = {
        "1": [f"1#{i}" for i in range(len(charger_positions))],
        "2": ["2#0"],
    }
    units_cache: Dict[str, Any] = {
        "1": {"col": charger_positions[0][0], "row": charger_positions[0][1], "player": 1,
              "occupied_hexes": set(charger_positions), "BASE_SHAPE": "round", "BASE_SIZE": 1},
        "2": {"col": TARGET[0], "row": TARGET[1], "player": 2,
              "occupied_hexes": target_footprint, "BASE_SHAPE": "round",
              "BASE_SIZE": TARGET_BASE_SIZE},
    }
    if bystander_cells:
        # Escouade tierce AMIE : la collision physique porte sur TOUTES les escouades, cible ou
        # non. La prendre amie isole ce qu'on verrouille — une escouade ennemie non-ciblee
        # refuserait aussi ces cellules par son ER (11.04), et le test ne distinguerait plus les
        # deux causes. Transit autorise (`can_move_through_friendly_model`), donc seule la case
        # d'ARRIVEE est en jeu.
        for i, (col, row) in enumerate(bystander_cells):
            models_cache[f"3#{i}"] = {
                "col": col, "row": row, "level": 0, "player": 1, "squad_id": "3", "HP_CUR": 1,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            }
        unit3 = {**unit_invariants(),
            "id": 3, "player": 1, "col": bystander_cells[0][0], "row": bystander_cells[0][1],
            "MOVE": 6, "HP_CUR": len(bystander_cells), "BASE_SIZE": 1, "BASE_SHAPE": "round",
            "UNIT_KEYWORDS": [], "level": 0,
        }
        units.append(unit3)
        squad_models["3"] = [f"3#{i}" for i in range(len(bystander_cells))]
        units_cache["3"] = {
            "col": bystander_cells[0][0], "row": bystander_cells[0][1], "player": 1,
            "occupied_hexes": set(bystander_cells), "BASE_SHAPE": "round", "BASE_SIZE": 1,
        }
    return {**turn_state_invariants(),
        "models_cache": models_cache,
        "squad_models": squad_models,
        "units_cache": units_cache,
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
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


def _engaging_cells(gs: Dict[str, Any], roll: int) -> Set[Tuple[int, int]]:
    """TOUTES les cellules d'ou la figurine `1#0` finit engagee avec la cible, dans le budget.

    Enumeration exhaustive du rectangle atteignable, et non une liste ecrite a la main : depuis
    que la borne 11.04 s'applique, le budget depasse TOUJOURS le trajet requis d'au moins un
    engagement range — l'ensemble engageant est un arc de deux cents cellules, pas les sept d'un
    anneau serre. Les deux verrous de collision plus bas s'en servent comme premisse : boucher
    autre chose que la totalite ne prouverait rien.

    Mesure independante du plan : `unit_entries_within_engagement_zone` (le contrat 03.04) et une
    distance de grille, pas le predicat de trajet que `charge_build_valid_plan` utilise.
    """
    budget = roll * ISH
    model = gs["models_cache"]["1#0"]
    return {
        (col, row)
        for col in range(CHARGER_COL, TARGET[0] + 1)
        for row in range(CHARGER_ROW - budget, CHARGER_ROW + budget + 1)
        if calculate_hex_distance(CHARGER_COL, CHARGER_ROW, col, row) <= budget
        and unit_entries_within_engagement_zone(
            _synth_model_entry(gs, "1", model, col, row),
            gs["units_cache"]["2"],
            get_engagement_zone(gs),
        )
    }


def test_fixture_neighbours_of_the_target_centre_are_inside_its_base():
    """Premisse du defaut n°1 : les voisins du centre ennemi sont DANS le socle, donc occupes.

    Sans cela, la lecture « destination = voisin du centre » rendrait des cellules legales et le
    fichier ne distinguerait plus les deux lectures : a socle d'un subhex, toute cible
    declarable (11.04) laisse aussi un voisin de son centre a portee.
    """
    gs = _gs([CHARGER_COL])
    assert get_engagement_zone(gs) == 10
    assert calculate_hex_distance(CHARGER_COL, CHARGER_ROW, *TARGET) == 45
    footprint = gs["units_cache"]["2"]["occupied_hexes"]
    neighbours = {
        (col, row)
        for col in range(TARGET[0] - 1, TARGET[0] + 2)
        for row in range(TARGET[1] - 1, TARGET[1] + 2)
        if calculate_hex_distance(TARGET[0], TARGET[1], col, row) == 1
    }
    assert neighbours, "enumeration cassee : aucun voisin"
    assert neighbours <= footprint


def test_fixture_separates_the_declaration_bound_from_the_travel_bound():
    """Premisse de la borne 11.04 : les deux jets encadrent la distance BORD A BORD.

    `ROLL_TOO_SHORT` est le jet qui rend les deux bornes distinguables : son budget couvre le
    trajet vers l'engagement mais pas la distance a la cible. Si la fixture perdait cet ecart,
    `test_single_model_charge_still_fails_when_the_roll_is_short` ne testerait plus rien.
    """
    gs = _gs([CHARGER_COL])
    charger, target = gs["units_cache"]["1"], gs["units_cache"]["2"]
    assert unit_entries_within_engagement_zone(charger, target, ROLL_REACHES_ENGAGEMENT * ISH)
    assert not unit_entries_within_engagement_zone(charger, target, ROLL_TOO_SHORT * ISH)
    # Le trajet, lui, tient dans le budget du jet trop court : c'est bien la borne de
    # DECLARATION qui tranche ici, pas une cible hors d'atteinte.
    assert min(
        calculate_hex_distance(CHARGER_COL, CHARGER_ROW, col, row)
        for col, row in _engaging_cells(gs, ROLL_REACHES_ENGAGEMENT)
    ) <= ROLL_TOO_SHORT * ISH


def test_single_model_charge_reaches_engagement_range():
    """Le defaut n°1, isole : une figurine, aucune coherency, aucun obstacle."""
    plan = charge_build_valid_plan(_gs([CHARGER_COL]), "1", ["2"], ROLL_REACHES_ENGAGEMENT)
    assert plan is not None, "charge a portee d'engagement refusee"
    assert len(plan) == 1
    _mid, col, row, _lvl = plan[0]
    assert calculate_hex_distance(CHARGER_COL, CHARGER_ROW, col, row) <= ROLL_REACHES_ENGAGEMENT * ISH


def test_single_model_charge_still_fails_when_the_roll_is_short():
    """11.04 BEFORE MOVING : une cible hors de la DISTANCE MAXIMALE n'est pas selectionnable.

    Jet 7 → budget 35 : il couvre le trajet vers l'engagement (30 subhex) mais pas la distance
    bord a bord a la cible (40). La charge doit echouer sur la borne de DECLARATION, alors meme
    que la destination serait atteignable — c'est precisement ce que le moteur ignorait, et ce
    qui lui donnait une portee de charge de jet + engagement range.
    """
    assert charge_build_valid_plan(_gs([CHARGER_COL]), "1", ["2"], ROLL_TOO_SHORT) is None


def test_a_roll_of_two_can_never_produce_a_plan():
    """Encart FAILED CHARGES (PDF 11) : « a result of 2 (a double 1) is never sufficient ».

    Le raisonnement du livre : une unite qui declare une charge n'est jamais engagee, elle est
    donc a PLUS de 2" — soit plus que la distance maximale d'un jet de 2. La cible est ici posee
    juste hors de l'engagement range, le cas le plus favorable qui soit ; le plan doit quand
    meme etre refuse. Verrou de la borne, independant des distances de la fixture.
    """
    gs = _gs([CHARGER_COL])
    ez = get_engagement_zone(gs)
    charger = gs["units_cache"]["1"]
    # Cible ramenee AU PLUS PRES du chargeur, juste au-dela de l'ER : une unite engagee ne
    # declare pas de charge (11.02), donc c'est le cas le plus favorable possible. Balayage
    # depuis le chargeur vers la cible, premiere colonne NON engagee retenue — l'ordre inverse
    # rendrait la position d'origine et le test ne mesurerait plus rien.
    for col in range(CHARGER_COL + 1, TARGET[0] + 1):
        moved = {
            **gs["units_cache"]["2"], "col": col,
            "occupied_hexes": set(
                compute_occupied_hexes(col, TARGET[1], "round", TARGET_BASE_SIZE, 0)
            ),
        }
        if unit_entries_within_engagement_zone(charger, moved, ez):
            continue
        for entry in (gs["units_cache"]["2"], gs["models_cache"]["2#0"], gs["unit_by_id"]["2"]):
            entry["col"] = col
        gs["units_cache"]["2"]["occupied_hexes"] = set(
            compute_occupied_hexes(col, TARGET[1], "round", TARGET_BASE_SIZE, 0)
        )
        break
    else:
        raise AssertionError("fixture cassee : aucune position hors ER trouvee")
    assert not unit_entries_within_engagement_zone(charger, gs["units_cache"]["2"], ez)
    assert charge_build_valid_plan(gs, "1", ["2"], 2) is None
    # Contre-epreuve, sans quoi le refus ci-dessus serait celui d'une cible simplement trop loin :
    # a UN subhex de plus de distance maximale, la meme charge passe.
    assert charge_build_valid_plan(gs, "1", ["2"], 3) is not None


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

def test_a_third_squad_forbids_the_cell_it_occupies() -> None:
    """Collision physique : la case occupee par une escouade tierce n'est pas une destination.

    Contre-epreuve dans le meme test : sans l'escouade tierce, c'est EXACTEMENT cette case que
    le plan retient. Le verrou porte donc sur le refus, pas sur un hasard de tri.
    """
    free_plan = charge_build_valid_plan(_gs([CHARGER_COL]), "1", ["2"], ROLL_REACHES_ENGAGEMENT)
    assert free_plan is not None
    _mid, picked_col, picked_row, _lvl = free_plan[0]

    blocked = charge_build_valid_plan(
        _gs([CHARGER_COL], [(picked_col, picked_row)]), "1", ["2"], ROLL_REACHES_ENGAGEMENT
    )
    assert blocked is not None, "boucher UNE case ne doit pas annuler la charge"
    _mid2, col2, row2, _lvl2 = blocked[0]
    assert (col2, row2) != (picked_col, picked_row)
    assert (col2, row2) in _engaging_cells(_gs([CHARGER_COL]), ROLL_REACHES_ENGAGEMENT)


def test_a_third_squad_covering_every_engaging_cell_cancels_the_charge() -> None:
    """Toutes les destinations engageantes occupees → aucun plan (11.04 AFTER MOVING).

    Contre-epreuve : la meme geometrie sans l'escouade tierce rend un plan.
    """
    assert charge_build_valid_plan(
        _gs([CHARGER_COL]), "1", ["2"], ROLL_REACHES_ENGAGEMENT
    ) is not None
    engaging = sorted(_engaging_cells(_gs([CHARGER_COL]), ROLL_REACHES_ENGAGEMENT))
    assert charge_build_valid_plan(
        _gs([CHARGER_COL], engaging), "1", ["2"], ROLL_REACHES_ENGAGEMENT
    ) is None
