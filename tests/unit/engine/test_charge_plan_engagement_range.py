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


# ─────────────────────────────────────────────────────────────────────────────
# 11.04 WHILE MOVING — « within 1" … must do so » : contact si possible (A2, 2026-09-18)
# Géométrie HEX x1 (échelle d'entraînement) : contact = case adjacente, EZ = 2 cases.
# ─────────────────────────────────────────────────────────────────────────────

from tests.unit.engine._state_builders import synthetic_state, synthetic_unit  # noqa: E402

X1_TARGET = (20, 20)


def _x1_charge_state(charger_cells: List[Tuple[int, int]]) -> Dict[str, Any]:
    """Escouade « 1 » aux cases données, cible « 2 » mono-figurine en X1_TARGET, plateau nu."""
    units = [
        synthetic_unit("1", 1, [{"col": c, "row": r} for c, r in charger_cells]),
        synthetic_unit("2", 2, [{"col": X1_TARGET[0], "row": X1_TARGET[1]}]),
    ]
    return synthetic_state(
        units, phase="charge", game_rules={}, inches_to_subhex=1, board_cols=44, board_rows=60,
        _unit_move_version=0, charge_roll_values={}, charge_target_selections={},
        charge_activation_pool=[], enemy_adjacent_hexes_player_1=set(), gym_training_mode=True,
    )


def _d_to_x1_target(cell: Tuple[int, int]) -> int:
    return calculate_hex_distance(cell[0], cell[1], X1_TARGET[0], X1_TARGET[1])


def test_x1_every_model_that_can_reach_contact_ends_in_contact():
    """Cinq figurines à 4 cases, jet 11 : les six cases de contact sont libres et atteignables,
    donc les CINQ finissent au contact (distance 1), pas à 2.

    ROUGE avant A2 : la clé d'intention 0 (« Serré » = plus proche du départ) retenait la case
    engagée la plus proche de l'origine, à 2 cases de la cible — mesuré bot contre bot :
    118 figurines au contact sur 516 après charge.
    """
    chargers = [(16, 18), (16, 19), (16, 20), (16, 21), (16, 22)]
    assert all(_d_to_x1_target(c) == 4 for c in chargers), [_d_to_x1_target(c) for c in chargers]
    gs = _x1_charge_state(chargers)

    plan = charge_build_valid_plan(gs, "1", ["2"], 11, intent=0)

    assert plan is not None
    dists = sorted(_d_to_x1_target((c, r)) for _m, c, r, _lv in plan)
    assert dists == [1, 1, 1, 1, 1], f"11.04 : contact atteignable → contact ; obtenu {dists}"
    cells = {(c, r) for _m, c, r, _lv in plan}
    assert len(cells) == 5, "cinq cases distinctes"


def test_x1_when_contact_is_full_the_next_model_ends_engaged_and_the_rest_follow():
    """Sept figurines, six cases de contact : six au contact, la septième ENGAGÉE (distance 2) —
    « engaged with one or more charge targets must do so » — jamais plus loin.

    Verrouille aussi l'ORDRE : les figurines les plus proches sont placées en premier, si bien
    qu'une figurine du fond ne prend pas la seule case de contact d'une figurine de front.
    """
    chargers = [(16, 17), (16, 18), (16, 19), (16, 20), (16, 21), (16, 22), (16, 23)]
    gs = _x1_charge_state(chargers)

    plan = charge_build_valid_plan(gs, "1", ["2"], 11, intent=0)

    assert plan is not None
    dists = sorted(_d_to_x1_target((c, r)) for _m, c, r, _lv in plan)
    assert dists == [1, 1, 1, 1, 1, 1, 2], dists


def test_x1_intent_only_breaks_ties_inside_the_tightest_tier():
    """L'intention L10 « Pénétration » (3, avancer au maximum) ne peut pas faire dépasser le
    contact : à contact atteignable, elle départage ENTRE cases de contact."""
    chargers = [(16, 20)]
    gs = _x1_charge_state(chargers)

    plan_tight = charge_build_valid_plan(gs, "1", ["2"], 11, intent=0)
    plan_deep = charge_build_valid_plan(gs, "1", ["2"], 11, intent=3)

    assert plan_tight is not None and plan_deep is not None
    assert _d_to_x1_target(plan_tight[0][1:3]) == 1
    assert _d_to_x1_target(plan_deep[0][1:3]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Le disque de candidats doit COUVRIR l'engagement (`_charge_engage_reach`)
# ─────────────────────────────────────────────────────────────────────────────
#
# `charge_build_valid_plan` n'énumère ses destinations engageantes QUE dans le disque hexagonal
# de rayon `_charge_engage_reach` (branche (a)). Le fichier vérifiait déjà l'autre moitié du
# contrat — le balayage carré de `_hex_cells_within_radius` couvre bien tout le disque — mais
# jamais que le DISQUE couvre l'engagement. Il ne le couvrait pas : à ez = 10 et deux socles
# round/6, la borne valait 15 quand les cellules engageantes vont jusqu'à 16, soit 6 cellules
# retirées de l'énumération sur 691. Cause : la borne additionnait des rayons d'empreinte
# DISCRÈTE alors que le prédicat euclidien soustrait les rayons CONTINUS des socles, plus grands
# d'un subhex par socle (round/6 : 3 contre 2), quand la borne n'ajoutait qu'un `+ 1` pour les
# deux. Une borne trop étroite refuse des charges sans rien signaler.

REACH_EZ_SUBHEX = 10  #: 2" à ISH = 5 — même valeur que le `game_rules` de `_gs`.
REACH_ROW = 62


#: Socles du roster Armageddon (`frontend/src/roster/`, `BASE_SIZE` en dixièmes de pouce) passés
#: par `_scale_socle` à ISH = 5 : 13 (32 mm, 27 datasheets) → `round`/6, 16 (40 mm, 58 datasheets)
#: → `round`/8, 20 → `round`/10, 35 → `round`/18, l'ovale [41, 21] → `oval`/[20, 10]. Trois de ces
#: cinq socles ont un écart rayon continu / rayon discret non nul — le socle d'infanterie standard
#: en fait partie. Les tailles testées ici sont donc celles du jeu, pas un échantillon inventé.
ROSTER_SIZES_X5 = (6, 8, 10, 18)


def _reach_state(
    self_size: Any, target_size: Any, target_col: int,
    self_shape: str = "round", target_shape: str = "round",
    self_orientation: int = 0, target_orientation: int = 0,
) -> Dict[str, Any]:
    """Duel mono-figurine à ISH = 5, socles paramétrés des deux côtés.

    La TAILLE est la variable du défaut : l'écart entre rayon continu et rayon discret vaut 0 ou
    1 subhex selon elle (round/8 : 4 et 4 ; round/6 : 3 et 2), donc une borne fausse ne l'est pas
    pour tous les socles. La FORME l'est aussi, pour une autre raison : `euclidean_edge_distance`
    traite une paire ronde↔ronde par un clearance analytique et toute paire non ronde par des
    contours polygonaux — deux chemins distincts, dont un seul serait exercé sans ce paramètre.
    """
    charger = (10, REACH_ROW)
    target = (target_col, REACH_ROW)
    unit1 = {**unit_invariants(),
        "id": 1, "player": 1, "col": charger[0], "row": charger[1], "MOVE": 6, "HP_CUR": 1,
        "BASE_SIZE": self_size, "BASE_SHAPE": self_shape, "UNIT_KEYWORDS": [], "level": 0,
    }
    unit2 = {**unit_invariants(),
        "id": 2, "player": 2, "col": target[0], "row": target[1], "MOVE": 6, "HP_CUR": 1,
        "BASE_SIZE": target_size, "BASE_SHAPE": target_shape, "UNIT_KEYWORDS": [], "level": 0,
    }
    return {**turn_state_invariants(),
        "models_cache": {
            "1#0": {"col": charger[0], "row": charger[1], "level": 0, "player": 1,
                    "squad_id": "1", "HP_CUR": 1, "BASE_SHAPE": self_shape,
                    "BASE_SIZE": self_size, "orientation": self_orientation},
            "2#0": {"col": target[0], "row": target[1], "level": 0, "player": 2,
                    "squad_id": "2", "HP_CUR": 1, "BASE_SHAPE": target_shape,
                    "BASE_SIZE": target_size, "orientation": target_orientation},
        },
        "squad_models": {"1": ["1#0"], "2": ["2#0"]},
        "units_cache": {
            "1": {"col": charger[0], "row": charger[1], "player": 1,
                  "occupied_hexes": set(compute_occupied_hexes(
                      charger[0], charger[1], self_shape, self_size, self_orientation)),
                  "BASE_SHAPE": self_shape, "BASE_SIZE": self_size,
                  "orientation": self_orientation},
            "2": {"col": target[0], "row": target[1], "player": 2,
                  "occupied_hexes": set(compute_occupied_hexes(
                      target[0], target[1], target_shape, target_size, target_orientation)),
                  "BASE_SHAPE": target_shape, "BASE_SIZE": target_size,
                  "orientation": target_orientation},
        },
        "units": [unit1, unit2],
        "unit_by_id": {"1": unit1, "2": unit2},
        "board_cols": 200, "board_rows": 160,
        "wall_hexes": set(),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": REACH_EZ_SUBHEX, "unit_model_cohesion_range": 10,
                           "unit_global_cohesion_range": 45,
                           "cohesion_distance_mode": "euclidean", "squad_min_neighbors": 1},
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


def _engaging_cells_around(
    gs: Dict[str, Any], target: Tuple[int, int], span: int
) -> Set[Tuple[int, int]]:
    """Toutes les cellules du carré de demi-côté `span` autour de `target` d'où `1#0` engage `2`.

    Force brute par la primitive d'engagement (03.04), sans aucune borne de trajet : c'est la
    RÉFÉRENCE que le disque de candidats doit contenir, mesurée indépendamment de lui.
    """
    model = gs["models_cache"]["1#0"]
    target_entry = gs["units_cache"]["2"]
    ez = get_engagement_zone(gs)
    return {
        (col, row)
        for col in range(target[0] - span, target[0] + span + 1)
        for row in range(target[1] - span, target[1] + span + 1)
        if unit_entries_within_engagement_zone(
            _synth_model_entry(gs, "1", model, col, row), target_entry, ez, game_state=gs
        )
    }


@pytest.mark.parametrize("target_col", [40, 41])
@pytest.mark.parametrize(
    "self_size, target_size",
    [(1, 1), (4, 4), (5, 5)] + [(a, b) for a in ROSTER_SIZES_X5 for b in ROSTER_SIZES_X5],
)
def test_engage_reach_covers_every_engaging_cell(
    self_size: int, target_size: int, target_col: int
) -> None:
    """Le disque de candidats contient TOUTE cellule d'où la figurine finit engagée.

    ROUGE avec la borne d'avant (`ez + rayons d'empreinte + 1`) sur les socles 6/6, 6/18 et
    18/18 : distance engageante maximale 16, 22 et 28 pour une borne de 15, 21 et 27.

    Colonnes PAIRE et IMPAIRE : la forme d'une empreinte dépend de la parité de sa colonne, et
    une borne juste sur l'une peut amputer l'autre.
    """
    from engine.phase_handlers.shared_utils import _charge_engage_reach

    gs = _reach_state(self_size, target_size, target_col)
    target = (target_col, REACH_ROW)
    reach = _charge_engage_reach(
        gs, "1", [gs["models_cache"]["1#0"]], [gs["units_cache"]["2"]], [target],
        get_engagement_zone(gs),
    )
    engaging = _engaging_cells_around(gs, target, reach + 6)

    assert engaging, "aucune cellule engageante : le balayage ne prouverait rien"
    farthest = max(calculate_hex_distance(c, r, *target) for c, r in engaging)
    assert farthest <= reach, (
        f"cellules engageantes jusqu'a {farthest} pour une borne de {reach} : "
        f"{sorted(c for c in engaging if calculate_hex_distance(c[0], c[1], *target) > reach)}"
    )
    # Contre-épreuve : une borne élargie « au cas où » (par exemple un facteur 1,155 appliqué à
    # l'ancienne) passerait l'assertion ci-dessus tout en gonflant le disque — 817 cellules au
    # lieu de 721 à ez = 10. Le disque est le domaine d'énumération de la branche (a) ET la
    # borne d'arrêt du BFS d'intention : il se paie à chaque construction de plan.
    assert reach <= farthest + 1, (
        f"borne {reach} trop large pour une distance engageante maximale de {farthest}"
    )


#: Socles NON RONDS, orientations comprises. Les orientations impaires sont là parce que
#: l'empreinte discrète d'un ovale y perd un subhex de rayon (mesuré : `oval`/[21, 14] rend 10 aux
#: orientations paires, 9 aux impaires) alors que son rayon circonscrit, lui, ne tourne pas.
NON_ROUND_PAIRS = [
    ("oval", [20, 10], 0, "round", 6, 0),
    ("oval", [20, 10], 1, "round", 6, 0),
    ("oval", [21, 14], 2, "oval", [18, 10], 2),
    ("oval", [21, 14], 3, "oval", [18, 10], 3),
    ("round", 6, 0, "oval", [21, 14], 5),
    ("square", 6, 0, "round", 6, 0),
    ("square", 10, 2, "square", 10, 3),
]


@pytest.mark.parametrize("target_col", [40, 41])
@pytest.mark.parametrize(
    "self_shape, self_size, self_or, target_shape, target_size, target_or", NON_ROUND_PAIRS
)
def test_engage_reach_covers_every_engaging_cell_for_non_round_bases(
    self_shape: str, self_size: Any, self_or: int,
    target_shape: str, target_size: Any, target_or: int, target_col: int,
) -> None:
    """Même contrat sur l'AUTRE chemin du prédicat : les contours polygonaux.

    `euclidean_edge_distance` n'emprunte le clearance analytique que pour une paire
    ronde↔ronde ; toute paire impliquant un `oval` ou un `square` passe par
    `_socle_edge_primitives`. La borne, elle, s'écrit dans les deux cas avec
    `bounding_radius_norm` — ce test est ce qui prouve que ce rayon majore bien ces contours-là,
    au lieu de le supposer depuis la formule.

    La borne n'est PAS serrée ici, et ne peut pas l'être : le rayon circonscrit d'un ovale vaut
    son demi-grand-axe quelle que soit son orientation, alors que l'engagement le plus lointain
    dépend de l'axe présenté. Marge mesurée sur 42 configurations : 0 à 2 subhexes. Le plafond de
    2 est là pour qu'un élargissement au-delà se voie.

    CE QUE CE TEST NE VERROUILLE PAS : l'ancienne borne (rayons d'empreinte + 1) passe ces sept
    paires — mesuré en la réintroduisant, 18 rouges sur la paramétrisation ronde et 0 ici. C'est
    un verrou de CONTRAT, pas de régression sur le défaut de la suite 168.
    """
    from engine.phase_handlers.shared_utils import _charge_engage_reach

    gs = _reach_state(
        self_size, target_size, target_col,
        self_shape=self_shape, target_shape=target_shape,
        self_orientation=self_or, target_orientation=target_or,
    )
    target = (target_col, REACH_ROW)
    reach = _charge_engage_reach(
        gs, "1", [gs["models_cache"]["1#0"]], [gs["units_cache"]["2"]], [target],
        get_engagement_zone(gs),
    )
    engaging = _engaging_cells_around(gs, target, reach + 6)

    assert engaging, "aucune cellule engageante : le balayage ne prouverait rien"
    farthest = max(calculate_hex_distance(c, r, *target) for c, r in engaging)
    assert farthest <= reach, (
        f"cellules engageantes jusqu'a {farthest} pour une borne de {reach} : "
        f"{sorted(c for c in engaging if calculate_hex_distance(c[0], c[1], *target) > reach)}"
    )
    assert reach <= farthest + 2, (
        f"borne {reach} pour une distance engageante maximale de {farthest}"
    )


def test_engage_reach_follows_the_hex_metric_when_the_metric_is_hex(monkeypatch) -> None:
    """La borne doit SUIVRE la métrique : épinglée en `hex`, elle repasse aux rayons d'empreinte.

    Le test se joue à ISH = 5 avec des socles `round`/6, pas à x1 : à x1 les socles sont
    normalisés en `round`/1 et les deux branches rendent la même valeur (3), donc rien n'y
    distingue la métrique — un vert vacant. Ici les deux branches divergent : empreintes
    discrètes 10 + 2 + 2 + 1 = 15, rayons continus 10 + 3 + 3 = 16.

    La seconde assertion est celle qui verrouille la bascule : sous métrique `hex` les cellules
    engageantes ne vont qu'à 14, donc la borne euclidienne (16) y serait trop LARGE de deux.
    """
    monkeypatch.setattr(
        "engine.spatial_relations.engagement_distance_metric", lambda *a, **k: "hex"
    )
    from engine.phase_handlers.shared_utils import _charge_engage_reach

    gs = _reach_state(6, 6, 40)
    target = (40, REACH_ROW)
    reach = _charge_engage_reach(
        gs, "1", [gs["models_cache"]["1#0"]], [gs["units_cache"]["2"]], [target],
        get_engagement_zone(gs),
    )
    engaging = _engaging_cells_around(gs, target, reach + 6)

    assert engaging, "aucune cellule engageante : le balayage ne prouverait rien"
    farthest = max(calculate_hex_distance(c, r, *target) for c, r in engaging)
    assert farthest <= reach, f"cellules engageantes jusqu'a {farthest} pour une borne de {reach}"
    assert reach <= farthest + 1, (
        f"borne {reach} pour une distance engageante maximale de {farthest} : la branche "
        f"euclidienne a mange la metrique hex"
    )
