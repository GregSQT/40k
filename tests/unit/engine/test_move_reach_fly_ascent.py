"""21.03 × 13.06 — une figurine qui VOLE finit à l'étage sans payer la montée, et la validation
doit l'admettre là où le pool l'offre.

LE DÉFAUT. Le pool par-figurine du move (`movement_build_model_destinations_pool`) traite le vol
déclaré en planaire : aucun obstacle, aucun coût vertical, les cases dont l'empreinte tient sur le
plancher sont offertes AU NIVEAU de la vue. La validation (`model_reach_predicate`) testait la
montée AVANT la géométrie et sans regarder le vol : elle bornait alors la figurine par le champ de
montée — murs et figurines en obstacle, distance verticale facturée — c'est-à-dire par tout ce que
21.03 lui épargne (« Ignore all vertical distance », « move horizontally and vertically through
all categories of terrain feature »). Le pool offrait la case, le voile rouge la refusait :
masque ⊄ exécutable, en PvP seulement (la déclaration de montée n'est jamais armée pour une unité
qui vole, donc l'IA n'atteignait pas la branche).

Scénario FABRIQUÉ : x5, métrique euclidienne (celle du PvP, lue dans `game_config.json`), unité
FLY au sol, mur infranchissable SUR TOUTE LA HAUTEUR du plateau entre elle et une ruine à étage
(2"). En vol, la case d'étage est à portée en ligne droite ; au sol, elle est injoignable — c'est
le cas témoin, qui prouve que la voie montée reste prise hors vol.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.movement_handlers import (
    _fly_traversal_active,
    movement_build_model_destinations_pool,
)
from engine.phase_handlers.shared_utils import (
    build_enemy_adjacent_hexes,
    get_squad_move_budget,
    model_reach_predicate,
    move_plan_distance_mode,
    move_plan_path_distances,
    validate_move_plan,
)
from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

#: 1" = 5 sous-hexes : la résolution du PvP. À x1 la géométrie est hex et le mode `cube` prend
#: le relais — variante couverte plus bas, ce n'est pas le même chemin.
ISH = 5
DEPART = (20, 30)
#: Colonne de mur d'un bord à l'autre : au sol, RIEN ne passe de l'ouest à l'est.
_MUR_COL = 24
#: Ruine à étage, à l'est du mur. Polygone dérivé des ranges pour ne pas désaccorder hexes/polygone.
_ETAGE_COLS = range(26, 35)
_ETAGE_ROWS = range(25, 36)
_ETAGE_HEXES = [[c, r] for c in _ETAGE_COLS for r in _ETAGE_ROWS]
_ETAGE_POLY = [
    [_ETAGE_COLS.start, _ETAGE_ROWS.start], [_ETAGE_COLS.stop - 1, _ETAGE_ROWS.start],
    [_ETAGE_COLS.stop - 1, _ETAGE_ROWS.stop - 1], [_ETAGE_COLS.start, _ETAGE_ROWS.stop - 1],
]
HAUTEUR_ETAGE = 2.0
#: Case d'étage visée : au cœur de la ruine, 8 colonnes à l'est du départ, même rangée.
CIBLE = (28, 30)
NIVEAU_CIBLE = 1
MOVE_POUCES = 8


def _etat(*, vol_declare: bool, ish: int = ISH, move_pouces: int = MOVE_POUCES) -> Dict[str, Any]:
    """Unité FLY « F » d'une figurine au sol, ennemi « E » loin de tout, mur, ruine à étage."""
    flyer = synthetic_unit(
        "F", 1, [{"col": DEPART[0], "row": DEPART[1]}],
        UNIT_KEYWORDS=[{"keywordId": "FLY"}], MOVE=move_pouces * ish,
    )
    enemy = synthetic_unit("E", 2, [{"col": 55, "row": 55}], UNIT_KEYWORDS=[])
    state = synthetic_state(
        [flyer, enemy],
        inches_to_subhex=ish,
        board_cols=60, board_rows=60,
        terrain_areas=[{
            "id": "ruine",
            "polygon_vertices": _ETAGE_POLY,
            "hexes": _ETAGE_HEXES,
            "floors": [{
                "level": NIVEAU_CIBLE,
                "height_inches": HAUTEUR_ETAGE,
                "hexes": _ETAGE_HEXES,
                "polygon_vertices": _ETAGE_POLY,
            }],
        }],
        game_rules={"engagement_zone": 2 * ish},
        phase="move",
        wall_hexes={(_MUR_COL, r) for r in range(60)},
        units_took_to_skies={"F"} if vol_declare else set(),
        units_took_to_skies_charge=set(),
    )
    build_enemy_adjacent_hexes(state, 1)
    return state


def _budget(gs: Dict[str, Any]) -> int:
    return get_squad_move_budget("F", gs, "normal")


@pytest.fixture
def gs_vol() -> Dict[str, Any]:
    return _etat(vol_declare=True)


@pytest.fixture
def gs_sol() -> Dict[str, Any]:
    return _etat(vol_declare=False)


def test_la_mise_en_scene_tient(gs_vol: Dict[str, Any]) -> None:
    """Garde-fou : vol actif, mode euclidien, budget amputé des 2" de 21.03, montée réelle."""
    unit = gs_vol["unit_by_id"]["F"]
    assert _fly_traversal_active(gs_vol, unit, "F"), "vol non actif : le test n'exercerait rien"
    assert move_plan_distance_mode(gs_vol, "F") == "euclidean", (
        "la métrique du PvP n'est pas euclidienne : ce n'est pas le chemin du bug"
    )
    assert _budget(gs_vol) == (MOVE_POUCES - 2) * ISH
    assert int(gs_vol["models_cache"]["F#0"]["level"]) < NIVEAU_CIBLE


def test_le_pool_offre_la_case_d_etage_en_vol(gs_vol: Dict[str, Any]) -> None:
    """Côté MASQUE : le pool par-figurine, en vue étage, offre la cible AU NIVEAU 1.

    C'est la moitié « offert » de l'invariant — sans elle, le test suivant pourrait passer au vert
    sur une case que personne n'a proposée.
    """
    pool = movement_build_model_destinations_pool(gs_vol, "F#0", level=NIVEAU_CIBLE)
    offered = {(int(c), int(r)): int(lv) for c, r, lv in pool["destinations"]}
    assert offered.get(CIBLE) == NIVEAU_CIBLE, (
        f"la case {CIBLE} n'est pas offerte à l'étage {NIVEAU_CIBLE} par le pool en vol : "
        f"{offered.get(CIBLE)!r}"
    )


def test_la_validation_admet_la_montee_en_vol(gs_vol: Dict[str, Any]) -> None:
    """Côté EXÉCUTABLE : le prédicat de portée puis `validate_move_plan` admettent la case offerte.

    ROUGE avant correction : la voie montée bornait la figurine par le champ multi-niveaux (mur en
    obstacle, 2" de montée facturés), et refusait une case que le pool venait d'offrir.
    """
    budget = _budget(gs_vol)
    model = gs_vol["models_cache"]["F#0"]
    assert model_reach_predicate(gs_vol, "F", 1, model, budget, NIVEAU_CIBLE)(*CIBLE), (
        f"{CIBLE} niveau {NIVEAU_CIBLE} refusée par model_reach_predicate à une figurine qui "
        f"vole (budget {budget}) — la voie montée est prise malgré 21.03"
    )
    plan = [("F#0", CIBLE[0], CIBLE[1], NIVEAU_CIBLE)]
    assert validate_move_plan(
        plan, gs_vol, {"budget_per_model": budget, "require_coherency": False}
    ), "validate_move_plan refuse la case d'étage offerte au vol"
    # La MESURE au commit lit le même champ : un plan validé ne peut pas ressortir injoignable,
    # et sa distance tient dans le budget (aucun terme vertical en vol).
    distances = move_plan_path_distances(plan, gs_vol, "normal")
    assert distances["F#0"] <= budget, distances


def test_sans_vol_la_voie_montee_reste_prise(gs_sol: Dict[str, Any]) -> None:
    """TÉMOIN : la même unité FLY, SANS déclaration, est bornée par le champ de montée.

    Le mur barre tout le plateau au sol et la figurine ne vole pas : la case d'étage est
    injoignable, et le prédicat doit la refuser. Un correctif qui aurait simplement supprimé la
    voie montée passerait le test précédent et échouerait ici.
    """
    unit = gs_sol["unit_by_id"]["F"]
    assert not _fly_traversal_active(gs_sol, unit, "F")
    budget = _budget(gs_sol)
    assert budget == MOVE_POUCES * ISH, "sans déclaration, pas de malus 21.03"
    model = gs_sol["models_cache"]["F#0"]
    assert not model_reach_predicate(gs_sol, "F", 1, model, budget, NIVEAU_CIBLE)(*CIBLE), (
        f"{CIBLE} niveau {NIVEAU_CIBLE} acceptée au sol malgré le mur : la voie montée n'est "
        "plus prise hors vol"
    )


def test_en_geometrie_hex_le_vol_est_borne_par_le_cube() -> None:
    """x1 : la métrique est hex et le vol déclaré donne le mode `cube` — la ligne d'hexes borne,
    jamais le champ de montée. Même invariant, autre géométrie."""
    # À x1 un hex vaut 1" : 8 colonnes = 8 subhex, il faut 8 + 2 (21.03) de MOVE pour y aller.
    gs = _etat(vol_declare=True, ish=1, move_pouces=10)
    assert move_plan_distance_mode(gs, "F") == "cube"
    budget = _budget(gs)
    assert budget == 8
    model = gs["models_cache"]["F#0"]
    assert model_reach_predicate(gs, "F", 1, model, budget, NIVEAU_CIBLE)(*CIBLE), (
        f"{CIBLE} niveau {NIVEAU_CIBLE} refusée en mode cube (budget {budget}) — la voie "
        "montée est prise malgré le vol"
    )
