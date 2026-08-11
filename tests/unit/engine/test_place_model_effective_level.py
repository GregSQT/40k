"""Primitive « poser un plan par figurine » — le niveau ÉCRIT est toujours un niveau RÉSOLU (§13.06).

Poser une figurine issue d'un plan exige deux gestes, dans cet ordre : résoudre le niveau EFFECTIF
(le niveau du plan n'est que le niveau de la VUE au drop — un hint), puis écrire. Cet enchaînement
était réécrit à l'identique par chaque écrivain (déploiement, mouvement, aperçu de tir), et
`commit_move` — l'écrivain des charges, pile-in et consolidations — ne le faisait pas du tout : il
dépendait d'une pré-résolution que seul son appelant `mouvement` appliquait.

C'est ce défaut qui a produit le 500 « figurine marquée à l'étage mais hors empreinte de plancher »
du 2026-08-11, où le client perdait TOUT son calque de ligne de vue. Ce fichier verrouille les trois
garanties qui le rendent impossible :
  1. `place_model_at_effective_level` rabat au sol une empreinte qui déborde, et honore l'étage sinon ;
  2. `update_model_position` REFUSE un niveau non résolu (garde dur) — le prochain écrivain casse à
     la ligne fautive au lieu de produire l'état corrompu ;
  3. `commit_move` résout pour TOUS ses appelants, pas seulement pour le mouvement.

Vrai moteur, vrai scénario d'étages (`scenario_floors_test.json`) : la géométrie de plancher ne se
simule pas, et une empreinte qui déborde d'un bord est exactement ce qu'on doit reproduire.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

import pytest

from engine.phase_handlers.shared_utils import (
    commit_move,
    place_model_at_effective_level,
    resolve_model_effective_level,
    update_model_position,
)
from engine.terrain_utils import floor_hexes_at_level

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
SCENARIO = os.path.join(PROJECT_ROOT, "config/board/44x60x5/scenario/scenario_floors_test.json")


@pytest.fixture(scope="module")
def floors_env():
    from ai.training_utils import setup_imports
    from ai.unit_registry import UnitRegistry
    from services.api_server import get_agents_from_scenario

    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()
    if not os.path.exists(SCENARIO):
        raise FileNotFoundError(SCENARIO)
    env = W40KEngine(
        rewards_config="default",
        training_config_name="x5_new",
        controlled_agent=sorted(get_agents_from_scenario(SCENARIO, ur))[0],
        scenario_file=SCENARIO,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
    )
    env.reset(seed=42)
    return env


@pytest.fixture
def cells(floors_env) -> Dict[str, Any]:
    """Une figurine, une case de L1 qui PORTE son socle, une case de L1 qui le laisse déborder.

    Les deux cases doivent exister pour que ce fichier prouve quoi que ce soit : une ruine dont tout
    hex de plancher porterait n'importe quel socle rendrait les tests de rabattement vacants.
    """
    gs = floors_env.game_state
    mid = next(iter(gs["models_cache"]))
    model = gs["models_cache"][mid]
    fh1 = sorted(floor_hexes_at_level(gs["terrain_areas"], 1))
    assert fh1, "scénario sans plancher L1 rasterisé"

    holding = [c for c in fh1 if resolve_model_effective_level(gs, model, c[0], c[1], 1) == 1]
    spilling = [c for c in fh1 if resolve_model_effective_level(gs, model, c[0], c[1], 1) == 0]
    assert holding, "aucune case de L1 ne porte entièrement ce socle"
    assert spilling, "aucune case de bord de L1 ne fait déborder ce socle — test vacant"
    return {
        "gs": gs,
        "mid": str(mid),
        "squad_id": str(model["squad_id"]),
        "holding": holding[len(holding) // 2],
        "spilling": spilling[0],
    }


def test_place_honore_l_etage_quand_l_empreinte_tient(cells):
    """Le niveau demandé est retenu tel quel quand le socle tient entièrement sur le plancher."""
    gs, mid, (col, row) = cells["gs"], cells["mid"], cells["holding"]
    written = place_model_at_effective_level(gs, mid, col, row, 1)
    assert written == 1
    assert int(gs["models_cache"][mid]["level"]) == 1


def test_place_rabat_au_sol_quand_l_empreinte_deborde(cells):
    """Une figurine dont le socle déborde du plancher est au SOL — pas rejetée, pas à l'étage."""
    gs, mid, (col, row) = cells["gs"], cells["mid"], cells["spilling"]
    written = place_model_at_effective_level(gs, mid, col, row, 1)
    assert written == 0, "le niveau du plan est un HINT : hors empreinte, la figurine est au sol"
    assert int(gs["models_cache"][mid]["level"]) == 0


def test_update_model_position_refuse_un_niveau_non_resolu(cells):
    """GARDE DUR : écrire un étage sous une figurine qui n'y tient pas lève à la ligne fautive.

    Sans lui, l'état corrompu se propage et c'est `floor_height_at` qui lève, très loin de
    l'écriture — le 500 du 2026-08-11, où l'erreur remontait dans un `catch` client.

    Le refus doit être ATOMIQUE, et c'est la moitié du test qui compte : vérifier le seul
    `raises` laissait passer un garde qui levait APRÈS avoir écrit `col`/`row`. La figurine se
    retrouvait alors déplacée sous son ancien niveau d'étage — exactement l'état que le garde
    existe pour empêcher. Le `game_state` PvP survivant à la requête en 500, toutes les
    requêtes suivantes de la session levaient à leur tour.
    """
    gs, mid, (col, row) = cells["gs"], cells["mid"], cells["spilling"]
    # Départ posé au SOL, à une case DIFFÉRENTE de la destination refusée : sans cet écart, une
    # écriture de `col`/`row` avant la levée serait indétectable.
    depart = (int(col) + 3, int(row) + 3)
    place_model_at_effective_level(gs, mid, depart[0], depart[1], 0)
    avant = dict(gs["models_cache"][mid])

    with pytest.raises(ValueError, match="NON RÉSOLU"):
        update_model_position(gs, mid, col, row, level=1)

    apres = gs["models_cache"][mid]
    assert (int(apres["col"]), int(apres["row"])) == depart, (
        "refus non atomique : la figurine a été DÉPLACÉE avant que le garde ne lève"
    )
    assert int(apres["level"]) == int(avant["level"])


def test_update_model_position_refuse_une_orientation_invalide_sans_rien_ecrire(cells):
    """Le contrôle d'orientation est lui aussi une PRÉ-condition, pas une post-écriture.

    Il vivait après l'écriture de `col`/`row` ET de `level` : une orientation hors bornes levait
    en laissant la figurine déplacée ET remontée d'étage. Ce test est le seul à couvrir ce
    réordonnancement — celui du niveau ne passe pas d'`orientation`, donc il ne l'exerce jamais.
    """
    gs, mid, (col, row) = cells["gs"], cells["mid"], cells["holding"]
    depart = (int(col) + 3, int(row) + 3)
    place_model_at_effective_level(gs, mid, depart[0], depart[1], 0)
    avant = dict(gs["models_cache"][mid])

    with pytest.raises(ValueError, match="orientation must be an int"):
        update_model_position(gs, mid, col, row, level=1, orientation=99)

    apres = gs["models_cache"][mid]
    assert (int(apres["col"]), int(apres["row"])) == depart, (
        "refus non atomique : la figurine a été DÉPLACÉE avant le contrôle d'orientation"
    )
    assert int(apres["level"]) == int(avant["level"]), (
        "refus non atomique : le NIVEAU a été écrit avant le contrôle d'orientation"
    )
    assert int(apres["orientation"]) == int(avant["orientation"])


def test_update_model_position_accepte_un_niveau_resolu(cells):
    """Le garde ne bloque QUE l'incohérent : un étage réellement tenu s'écrit toujours."""
    gs, mid, (col, row) = cells["gs"], cells["mid"], cells["holding"]
    update_model_position(gs, mid, col, row, level=1)
    assert int(gs["models_cache"][mid]["level"]) == 1


def test_commit_move_resout_le_niveau_pour_tous_ses_appelants(cells):
    """`commit_move` (charge, pile-in, consolidation, gym) résout, il n'écrit pas le niveau brut.

    La résolution vivait chez son seul appelant `mouvement` : un plan de charge visant une case de
    bord d'étage aurait écrit l'étage tel quel. Ici le plan demande L1 sur une case qui fait
    déborder le socle — le commit doit poser au SOL, sans lever.
    """
    gs, mid, (col, row) = cells["gs"], cells["mid"], cells["spilling"]
    plan: List[Tuple[str, int, int, int]] = [(mid, col, row, 1)]
    commit_move(plan, gs, "charge")
    assert int(gs["models_cache"][mid]["level"]) == 0
    assert int(gs["units_cache"][cells["squad_id"]]["level"]) == 0, (
        "le niveau de l'ancre doit suivre celui de la figurine, pas le niveau demandé"
    )
