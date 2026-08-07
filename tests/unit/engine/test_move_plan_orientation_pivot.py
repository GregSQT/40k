"""VERROU : la MESURE du trajet lit l'orientation du PLAN, pas celle encore dans le cache.

Le 5e element d'une entree de plan porte l'orientation VISEE (pivot molette non committe).
`explain_move_plan_rejection` l'honore deja (`_model = {**_model, "orientation": _ori}`), et le
pool par-figurine a offert la case avec elle. Mais `move_plan_path_distances` est appelee par
`commit_move` AVANT les `update_model_position` : `models_cache` porte encore l'ANCIENNE
orientation. Sur socle non rond, le champ euclidien any-angle dilate les obstacles par
l'empreinte ORIENTEE — le goulot que le pivot vient d'ouvrir se refermait donc a la mesure, et
le plan valide ressortait « injoignable » de sa propre mesure : RuntimeError au commit.

Ce n'est pas theorique : 5 datasheets declarent `BASE_SHAPE = "oval"` (WarTrakk, Carnifex,
Psychophage, les deux LandSpeeder), et `scenario_pvp_test_orks_sm.json` en aligne deux.

La situation est CONSTRUITE, pas esperee. Trois conditions doivent tenir ENSEMBLE pour que les
deux lectures soient seulement discernables, et chacune est verifiee par un test de garde :
  - socle NON ROND : une empreinte ronde est invariante par rotation, les deux orientations
    donneraient le meme champ (et a `inches_to_subhex <= 1` le moteur normalise tout socle en
    `round`/1, cf. `game_state._scale_socle` — d'ou l'echelle x5 ici) ;
  - metrique EUCLIDIENNE : c'est la seule ou le trajet est any-angle, donc la seule ou
    l'empreinte orientee entre dans le calcul du chemin (`geometry_is_hex` prime a x1) ;
  - une geometrie ou le goulot ne s'ouvre QUE dans une orientation — mesuree, pas supposee.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from engine.phase_handlers.shared_utils import (
    _euclidean_move_field_for_model,
    _move_distance_field_bound,
    explain_move_plan_rejection,
    move_plan_distance_mode,
    move_plan_path_distances,
)
from tests._state_invariants import turn_state_invariants, unit_invariants

INCHES_TO_SUBHEX = 5
MOVE = 30  # subhexes : `MOVE` est deja scale dans `units` (cf. get_squad_move_budget)
# Socle oval DEJA scale (`_scale_socle` : [grand axe, petit axe] en subhexes).
BASE_SIZE = [8, 4]
START = (10, 30)
# Mur vertical colonne 20 perce d'un seul goulot de 4 cases : le seul passage vers l'est.
WALL = {(20, r) for r in range(20, 41)} - {(20, 30 + k) for k in range(4)}
# Mesuree : joignable a l'orientation 0, injoignable a l'orientation 3.
DEST = (22, 31)
ORIENT_CACHE = 3  # orientation actuelle de la figurine : le goulot est ferme
ORIENT_PLAN = 0  # orientation visee par le pivot : le goulot s'ouvre


def _gs(orientation: int) -> Dict[str, Any]:
    unit = {**unit_invariants(),
        "id": 1, "player": 1, "col": START[0], "row": START[1], "MOVE": MOVE,
        "HP_CUR": 1, "BASE_SIZE": BASE_SIZE, "BASE_SHAPE": "oval", "UNIT_KEYWORDS": [],
    }
    models_cache = {
        "1#0": {"col": START[0], "row": START[1], "level": 0, "player": 1, "squad_id": "1",
                "HP_CUR": 1, "BASE_SHAPE": "oval", "BASE_SIZE": BASE_SIZE,
                "orientation": orientation},
    }
    return {**turn_state_invariants(),
        "models_cache": models_cache,
        "squad_models": {"1": ["1#0"]},
        "units_cache": {"1": {"col": START[0], "row": START[1], "player": 1,
                              "occupied_hexes": set(), "BASE_SHAPE": "oval",
                              "BASE_SIZE": BASE_SIZE}},
        "units": [unit],
        "unit_by_id": {"1": unit},
        "board_cols": 44, "board_rows": 60,
        "wall_hexes": set(WALL),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": 2},
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
        },
        "phase": "move",
        "gym_training_mode": False,  # PvP -> distance_metric["move"] = euclidean
        "inches_to_subhex": INCHES_TO_SUBHEX,
        "units_took_to_skies": set(),
        "terrain_areas": [],
    }


def _plan(orientation: Optional[int]) -> List[Tuple[str, int, int, int, Optional[int]]]:
    return [("1#0", DEST[0], DEST[1], 0, orientation)]


def test_la_fixture_mesure_bien_en_euclidien() -> None:
    """VERT VACANT : en geodesique le chemin est un BFS d'hexes qui ignore l'orientation, et
    les tests suivants passeraient sans jamais toucher le code corrige."""
    assert move_plan_distance_mode(_gs(ORIENT_CACHE), "1") == "euclidean"


def test_la_geometrie_discrimine_bien_les_deux_orientations() -> None:
    """VERT VACANT : sans cet ecart mesure, le verrou observerait deux champs identiques."""
    joignable = {}
    for orientation in (ORIENT_PLAN, ORIENT_CACHE):
        gs = _gs(orientation)
        field = _euclidean_move_field_for_model(
            gs, "1", 1, gs["models_cache"]["1#0"], 0,
            _move_distance_field_bound(gs, "1", "normal"),
        )
        joignable[orientation] = field.get(DEST)
    assert joignable[ORIENT_PLAN] is not None, (
        f"{DEST} devait etre joignable a l'orientation {ORIENT_PLAN} : geometrie a refaire"
    )
    assert joignable[ORIENT_CACHE] is None, (
        f"{DEST} devait etre FERME a l'orientation {ORIENT_CACHE} : geometrie a refaire"
    )


def test_la_validation_accepte_le_plan_pivote() -> None:
    """L'autre moitie de l'invariant : c'est parce que la validation dit OUI que la mesure doit
    dire OUI. Si elle refusait, il n'y aurait aucune divergence a verrouiller.

    VERT VACANT : `budget_per_model` est OBLIGATOIRE ici. Sans lui la validation ne construit
    aucun champ de trajet — elle rend `None` pour les DEUX orientations, y compris celle ou le
    goulot est ferme, et n'atteint donc jamais la lecture du 5e element qu'elle est censee
    verrouiller. Le controle negatif ci-dessous est ce qui le prouve.
    """
    constraints = {"budget_per_model": MOVE, "require_coherency": False}
    assert explain_move_plan_rejection(_plan(ORIENT_PLAN), _gs(ORIENT_CACHE), constraints) is None
    assert explain_move_plan_rejection(
        _plan(ORIENT_CACHE), _gs(ORIENT_CACHE), constraints
    ) is not None, "sans le pivot le goulot est ferme : la validation DOIT refuser"


def test_la_mesure_du_trajet_suit_l_orientation_du_plan() -> None:
    """LE VERROU. Sans le fix : RuntimeError « Incoherence validation/mesure »."""
    distances = move_plan_path_distances(_plan(ORIENT_PLAN), _gs(ORIENT_CACHE), "normal")
    assert distances["1#0"] > 0.0, "trajet de longueur nulle : la mesure n'a rien mesure"
    assert distances["1#0"] <= MOVE, (
        f"trajet {distances['1#0']} au-dela du budget {MOVE} alors que le plan est valide"
    )


def test_sans_orientation_au_plan_la_mesure_garde_celle_du_cache() -> None:
    """Borne l'AUTRE cote du fix : le 5e element absent signifie « orientation inchangee », la
    mesure doit alors lire le cache — sans quoi « suivre le plan » pourrait etre implemente en
    ignorant purement le cache, ce que ce jeu de tests ne verrait pas."""
    with pytest.raises(RuntimeError, match="Incoherence validation/mesure"):
        move_plan_path_distances(_plan(None), _gs(ORIENT_CACHE), "normal")
