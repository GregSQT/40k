"""Pile-in / consolidation / champs multi-niveaux : le NIVEAU d'une figurine se résout sur SON
orientation, jamais sur celle de l'escouade.

LE DÉFAUT. Ces chemins résolvaient le niveau EFFECTIF (§13.06) du mover et de ses sœurs avec
``unit["orientation"]`` — l'orientation de l'ESCOUADE — pendant que le socle du même couple
``(niveau, socle)`` était construit sur celle de la FIGURINE. Or `update_model_position` écrit
``model["orientation"]`` lors d'un pivot par-figurine et ne resynchronise JAMAIS celle de
l'escouade : après un pivot en phase de mouvement, les deux divergent.

Effet MESURÉ sur `scenario_floors_test.json` (socle oval 8×4 : 206 cases de plancher concernées) :
une même figurine, à la même case, est **au sol dans une orientation et à l'étage dans une autre**.
Le pool la traitait comme au sol pendant que l'autoplace (`_fight_effective_level_at`,
par-figurine) la traitait comme à l'étage — l'autoplace proposait des cases que la validation
refuse, et le coût de descente §13.06 n'était pas facturé.

POURQUOI CE TEST ESPIONNE LE RÉSOLVEUR AU LIEU DE COMPARER DES POOLS.
La forme évidente — « le pool doit être identique quand seule l'orientation d'escouade change » —
a été essayée et REJETÉE : sur ce scénario le pool de pile-in ressort VIDE (budget 3", socle
large, palier hors de portée), et deux ensembles vides sont égaux quoi qu'il arrive. Vérifié comme
tel : défaut remis, le test restait VERT. Une sentinelle empoisonnée sur ``unit["orientation"]``
a ensuite été essayée puis rejetée à son tour — elle attrape AUSSI
``_charge_prepare_footprint_offsets``, qui lit le socle d'ESCOUADE pour l'empreinte des
candidats. C'est un sujet distinct du niveau, et le mélanger ferait échouer ce test pour une
raison qu'il n'a pas vocation à couvrir.

L'espion, lui, porte exactement sur le sujet : quelle orientation part au résolveur de niveau.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

import pytest

from engine.phase_handlers.shared_utils import (
    place_model_at_effective_level,
    resolve_model_effective_level,
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
        training_config_name="x1",
        controlled_agent=sorted(get_agents_from_scenario(SCENARIO, ur))[0],
        scenario_file=SCENARIO,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
    )
    env.reset(seed=42)
    return env


@pytest.fixture
def pivote(floors_env) -> Dict[str, Any]:
    """Une figurine à socle NON ROND, à l'étage, dont le niveau DÉPEND de son orientation.

    Le socle oval est POSÉ par le test : le roster du scénario n'en porte qu'un, trop large pour
    qu'un pile-in le déplace. Construire la situation plutôt que l'espérer d'un roster (T4).
    L'escouade reçoit une orientation DIFFÉRENTE de celle de la figurine — c'est la divergence
    qu'un pivot par-figurine produit en jeu, et le défaut ne s'observe que là.
    """
    gs = floors_env.game_state
    mid = next(m for m, e in gs["models_cache"].items() if e["BASE_SHAPE"] == "round")
    model = gs["models_cache"][mid]
    squad_id = str(model["squad_id"])
    unit = next(u for u in gs["units"] if str(u["id"]) == squad_id)
    for cible in (model, unit, gs["units_cache"][squad_id]):
        cible["BASE_SHAPE"] = "oval"
        cible["BASE_SIZE"] = [8, 4]

    discriminantes = [
        ((c, r), niveaux)
        for (c, r) in sorted(floor_hexes_at_level(gs["terrain_areas"], 1))
        for niveaux in [
            {o: resolve_model_effective_level(gs, {**model, "orientation": o}, c, r, 1)
             for o in range(6)}
        ]
        if 1 in niveaux.values() and 0 in niveaux.values()
    ]
    assert discriminantes, "aucune case où le niveau dépend de l'orientation — fixture vacante"
    (col, row), niveaux = discriminantes[len(discriminantes) // 2]
    orientation_etage = next(o for o, lv in niveaux.items() if lv == 1)
    orientation_sol = next(o for o, lv in niveaux.items() if lv == 0)

    place_model_at_effective_level(gs, mid, col, row, 1, orientation=orientation_etage)
    assert int(gs["models_cache"][mid]["level"]) == 1, (
        "prémisse : la figurine doit être À L'ÉTAGE dans son orientation propre"
    )
    # L'escouade garde l'orientation qui donnerait SOL : lue par erreur, elle change le verdict.
    unit["orientation"] = orientation_sol
    gs["units_cache"][squad_id]["orientation"] = orientation_sol

    ennemi = next(
        u for u, e in gs["units_cache"].items() if int(e["player"]) != int(model["player"])
    )
    emid = next(m for m in gs["squad_models"][ennemi] if m in gs["models_cache"])
    place_model_at_effective_level(gs, emid, col + 3, row + 3, 0)
    return {
        "gs": gs, "mid": str(mid), "unit": unit, "ennemi": str(ennemi), "cell": (col, row),
        "orientation_figurine": orientation_etage, "orientation_escouade": orientation_sol,
    }


def _orientations_vues_par_le_resolveur(monkeypatch, module: str) -> List[Tuple[int, int]]:
    """Espionne `resolve_model_effective_level` DANS ``module`` : (orientation passée, celle du modèle).

    ``orientation=None`` (le contrat « celle de la figurine ») est normalisé en l'orientation du
    modèle : c'est la forme correcte, et elle doit rester indiscernable d'un passage explicite de
    la bonne valeur.
    """
    import importlib

    vues: List[Tuple[int, int]] = []
    cible = importlib.import_module(module)
    original = cible.resolve_model_effective_level

    def espion(game_state, model, col, row, requested_level, orientation=None):
        effective = int(model["orientation"]) if orientation is None else int(orientation)
        vues.append((effective, int(model["orientation"])))
        return original(game_state, model, col, row, requested_level, orientation)

    monkeypatch.setattr(cible, "resolve_model_effective_level", espion)
    return vues


def test_le_pool_de_pile_in_resout_le_niveau_sur_l_orientation_de_la_figurine(pivote, monkeypatch):
    """VERROU : défaut remis (`_orient` = orientation d'escouade) → cet écart devient ROUGE."""
    from engine.phase_handlers.fight_handlers import _fight_pile_in_build_model_pool

    vues = _orientations_vues_par_le_resolveur(monkeypatch, "engine.phase_handlers.fight_handlers")
    _fight_pile_in_build_model_pool(
        pivote["gs"], pivote["mid"], [pivote["ennemi"]], None, view_level=1
    )

    assert vues, "le pool n'a résolu aucun niveau — l'espion ne regarde rien"
    divergents = [(u, m) for u, m in vues if u != m]
    assert divergents == [], (
        f"niveau résolu sur une orientation qui n'est pas celle de la figurine : {divergents} "
        f"(escouade={pivote['orientation_escouade']}, figurine={pivote['orientation_figurine']})"
    )


def test_le_pool_de_consolidation_resout_le_niveau_sur_l_orientation_de_la_figurine(
    pivote, monkeypatch
):
    """Jumeau strict du pile-in : fonction dupliquée, même défaut, même verrou."""
    from engine.phase_handlers.fight_handlers import _fight_consolidation_build_model_pool

    vues = _orientations_vues_par_le_resolveur(monkeypatch, "engine.phase_handlers.fight_handlers")
    _fight_consolidation_build_model_pool(
        pivote["gs"], pivote["mid"],
        tier_kind="enemy", tier=[pivote["ennemi"]], lock_base_contact=False, view_level=1,
    )

    assert vues, "le pool n'a résolu aucun niveau — l'espion ne regarde rien"
    assert [(u, m) for u, m in vues if u != m] == []
