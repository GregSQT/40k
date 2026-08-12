"""Pile-in / consolidation : l'empreinte d'une figurine se mesure à SON socle, pas à celui du bloc.

LE DÉFAUT. Ces pools sont des mouvements PAR FIGURINE, mais ils préparaient leurs offsets
d'empreinte avec le socle de l'ESCOUADE. Un personnage attaché — socle plus large que la troupe
qu'il rejoint — y était donc SOUS-empreinté : le pool lui proposait des cases calculées sur une
fraction de la place qu'il occupe réellement, et le commit, qui mesure par-figurine, les refusait
ensuite. C'est la divergence pool/commit que ce dépôt a déjà payée plusieurs fois.

MESURÉ sur les scénarios du dépôt avant correction : 67 figurines sur 684 portent un socle
différent de leur escouade, et les 67 étaient sous-empreintées — 19 hexes annoncés contre 43
réels, jusqu'à 61. Onze scénarios sur quatorze sont concernés, dont un scénario d'entraînement.

Aucun test du dépôt ne couvrait ce cas : les 84 tests de pile-in et de combat passaient avec le
défaut en place. D'où ce fichier.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Dict, List

import pytest

from engine.hex_utils import precompute_footprint_offsets

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
SCENARIO = os.path.join(
    PROJECT_ROOT, "config/board/44x60x5/scenario/scenario_attached_unit_test.json"
)


@pytest.fixture(scope="module")
def attached_env():
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
    env.reset(seed=1)
    return env


@pytest.fixture
def personnage_attache(attached_env) -> Dict[str, Any]:
    """La figurine dont le socle DIFFÈRE de celui de son escouade, et les deux tailles d'empreinte.

    Sans cette divergence le test serait vacant : sur une escouade homogène, mesurer au socle du
    bloc ou à celui de la figurine donne exactement la même empreinte.
    """
    gs = attached_env.game_state
    ubi = gs["unit_by_id"]
    for mid, model in gs["models_cache"].items():
        unit = ubi.get(str(model["squad_id"]))
        if unit is None:
            continue
        if (model["BASE_SHAPE"], str(model["BASE_SIZE"])) == (
            unit.get("BASE_SHAPE"), str(unit.get("BASE_SIZE"))
        ):
            continue
        taille = {}
        for nom, porteur in (("figurine", model), ("escouade", unit)):
            off_e, _off_o = precompute_footprint_offsets(
                porteur["BASE_SHAPE"], porteur["BASE_SIZE"], int(porteur.get("orientation", 0))
            )
            taille[nom] = len(off_e)
        assert taille["figurine"] != taille["escouade"], (
            "socles différents mais empreintes de même taille — le cas ne discrimine rien"
        )
        return {
            "gs": gs, "mid": str(mid), "squad_id": str(model["squad_id"]),
            "n_figurine": taille["figurine"], "n_escouade": taille["escouade"],
        }
    raise AssertionError(
        "scénario sans personnage attaché à socle divergent — fixture vacante"
    )


def _tailles_d_empreinte_vues(monkeypatch) -> List[int]:
    """Note la taille de chaque empreinte par-figurine calculée, quelle qu'en soit la source.

    DEUX sources, parce que le combat en a deux et qu'espionner une seule rend un test vacant
    (mesuré : après la bascule de l'engagement vers `_synth_model_entry`, le seul espion
    `_candidate_footprint_charge` ne voyait plus rien du preview de pile-in) :
    - `_candidate_footprint_charge` — empreintes de placement (pools, zone d'objectif) ;
    - `_synth_model_entry` — entrée d'engagement par figurine, qui recalcule l'empreinte au socle
      de la figurine et ne reçoit donc plus la précédente.

    `_candidate_footprint_charge` est patchée sur `charge_handlers` (les pools de combat
    l'importent LOCALEMENT, donc le module source est relu à chaque appel) ; `_synth_model_entry`
    l'est sur les deux modules consommateurs, qui la lient au chargement.
    """
    from engine.phase_handlers import charge_handlers, fight_handlers

    vues: List[int] = []
    original = charge_handlers._candidate_footprint_charge

    def espion(col, row, porteur, game_state, offset_pair):
        fp = original(col, row, porteur, game_state, offset_pair)
        vues.append(len(fp))
        return fp

    monkeypatch.setattr(charge_handlers, "_candidate_footprint_charge", espion)

    original_synth = fight_handlers._synth_model_entry

    def espion_synth(game_state, squad_id, model_entry, col, row, level=None):
        entry = original_synth(game_state, squad_id, model_entry, col, row, level=level)
        vues.append(len(entry["occupied_hexes"]))
        return entry

    monkeypatch.setattr(fight_handlers, "_synth_model_entry", espion_synth)
    monkeypatch.setattr(charge_handlers, "_synth_model_entry", espion_synth)
    return vues


def test_le_pool_de_pile_in_empreinte_le_personnage_attache_a_son_propre_socle(
    personnage_attache, monkeypatch
):
    """VERROU : socle d'escouade remis → les empreintes tombent à la taille du bloc, ROUGE ici."""
    from engine.phase_handlers.fight_handlers import _fight_pile_in_build_model_pool

    gs, mid = personnage_attache["gs"], personnage_attache["mid"]
    ennemis = [
        str(u) for u, e in gs["units_cache"].items()
        if int(e["player"]) != int(gs["models_cache"][mid]["player"])
    ]
    assert ennemis, "scénario sans ennemi — le pile-in n'aurait aucun palier"

    vues = _tailles_d_empreinte_vues(monkeypatch)
    _fight_pile_in_build_model_pool(gs, mid, ennemis, None, view_level=0)

    assert vues, "aucune empreinte calculée — l'espion ne regarde rien"
    assert set(vues) == {personnage_attache["n_figurine"]}, (
        f"empreintes de tailles {sorted(set(vues))} ; attendu {personnage_attache['n_figurine']} "
        f"(socle de la figurine). {personnage_attache['n_escouade']} = socle de l'ESCOUADE, "
        f"c'est-à-dire le personnage attaché sous-empreinté."
    )


def test_le_pool_de_consolidation_empreinte_le_personnage_attache_a_son_propre_socle(
    personnage_attache, monkeypatch
):
    """Jumeau strict du pile-in : fonction dupliquée, même défaut, même verrou."""
    from engine.phase_handlers.fight_handlers import _fight_consolidation_build_model_pool

    gs, mid = personnage_attache["gs"], personnage_attache["mid"]
    ennemis = [
        str(u) for u, e in gs["units_cache"].items()
        if int(e["player"]) != int(gs["models_cache"][mid]["player"])
    ]

    vues = _tailles_d_empreinte_vues(monkeypatch)
    _fight_consolidation_build_model_pool(
        gs, mid, tier_kind="enemy", tier=ennemis, lock_base_contact=False, view_level=0
    )

    assert vues, "aucune empreinte calculée — l'espion ne regarde rien"
    assert set(vues) == {personnage_attache["n_figurine"]}, (
        f"empreintes de tailles {sorted(set(vues))} ; attendu "
        f"{personnage_attache['n_figurine']} (socle de la figurine)"
    )


@contextmanager
def _ennemi_au_contact(gs: Dict[str, Any], mid: str):
    """Colle une figurine ennemie contre ``mid``, puis REMET tout en place.

    Le `game_state` est partagé par le module : une mise en scène non défaite ferait dépendre
    les tests suivants de l'ordre d'exécution, exactement ce qu'un test ne doit jamais faire.
    """
    from engine.phase_handlers.shared_utils import place_model_at_effective_level

    mover = gs["models_cache"][mid]
    ennemi_uid = next(
        u for u, e in gs["units_cache"].items() if int(e["player"]) != int(mover["player"])
    )
    emid = next(m for m in gs["squad_models"][ennemi_uid] if m in gs["models_cache"])
    avant = gs["models_cache"][emid]
    origine = (int(avant["col"]), int(avant["row"]), int(avant["level"]))
    place_model_at_effective_level(gs, emid, int(mover["col"]) + 1, int(mover["row"]), 0)
    try:
        yield
    finally:
        place_model_at_effective_level(gs, emid, origine[0], origine[1], origine[2])


def _plan_complet(gs: Dict[str, Any], squad_id: str) -> List[Any]:
    """Plan « chacun reste où il est » : la forme la plus simple qui couvre TOUTES les figurines."""
    mc = gs["models_cache"]
    return [
        (str(m), int(mc[str(m)]["col"]), int(mc[str(m)]["row"]), int(mc[str(m)]["level"]))
        for m in gs["squad_models"][squad_id] if str(m) in mc
    ]


@pytest.mark.parametrize("phase", ["pile_in", "consolidation"])
def test_le_preview_empreinte_chaque_figurine_a_son_propre_socle(
    personnage_attache, monkeypatch, phase
):
    """Les DEUX preview mesurent le plan par-figurine — le pool n'est pas le seul chemin.

    Ici le plan couvre toute l'escouade : les tailles vues mélangent donc troupe et personnage.
    Ce qui verrouille, c'est que celle du PERSONNAGE apparaisse — avec le socle d'escouade, elle
    n'apparaît jamais.
    """
    from engine.phase_handlers import fight_handlers as fh

    gs, squad_id = personnage_attache["gs"], personnage_attache["squad_id"]
    mid = personnage_attache["mid"]
    ennemis = [
        str(u) for u, e in gs["units_cache"].items()
        if int(e["player"]) != int(gs["models_cache"][mid]["player"])
    ]
    plan = _plan_complet(gs, squad_id)

    vues = _tailles_d_empreinte_vues(monkeypatch)
    if phase == "pile_in":
        fh._fight_pile_in_preview_plan(gs, squad_id, plan, ennemis)
    else:
        # `mode="engaging"` et non `"enemy"` : `tier_kind` est DÉRIVÉ du mode (`zone` pour
        # objective, `enemy` sinon). Avec un mode inconnu, la fonction sort avant tout calcul —
        # l'assertion « aucune empreinte calculée » plus bas l'a attrapé.
        fh._fight_consolidation_preview_plan(
            gs, squad_id, plan, mode="engaging", tier_kind="enemy", tier=ennemis,
            closest_tier_ids=ennemis, lock_base_contact=False,
        )

    assert vues, "aucune empreinte calculée — l'espion ne regarde rien"
    assert personnage_attache["n_figurine"] in set(vues), (
        f"tailles vues {sorted(set(vues))} ; celle du personnage attaché "
        f"({personnage_attache['n_figurine']}) n'apparaît pas — il est empreinté au socle du bloc"
    )


@pytest.mark.parametrize("phase", ["pile_in", "consolidation"])
def test_l_etat_de_plan_empreinte_chaque_figurine_a_son_propre_socle(
    personnage_attache, monkeypatch, phase
):
    """Les DEUX états de plan exposés au front : voile vert et zone d'empreinte du pool."""
    from engine.phase_handlers import fight_handlers as fh

    gs, squad_id = personnage_attache["gs"], personnage_attache["squad_id"]
    mid = personnage_attache["mid"]
    unit = gs["unit_by_id"][squad_id]

    vues = _tailles_d_empreinte_vues(monkeypatch)
    if phase == "pile_in":
        fh._fight_pile_in_model_plan_state(gs, unit, None, selected_model=mid, view_level=0)
    else:
        # La consolidation n'a de mode — donc de calcul — que dans une situation de jeu réelle
        # (12.08 : engagée, ou ennemi/objectif à 3"). Sans mise en scène, elle sort avant toute
        # empreinte et le test serait vacant : c'est l'assertion plus bas qui l'a montré.
        # « ongoing » est la branche la plus simple : il suffit que l'unité soit engagée.
        with _ennemi_au_contact(gs, mid):
            assert fh.fight_v11_consolidation_mode(gs, unit) == "ongoing", (
                "prémisse : l'unité doit être engagée pour que la consolidation ait un mode"
            )
            fh._fight_consolidation_model_plan_state(
                gs, unit, None, selected_model=mid, view_level=0
            )

    assert vues, "aucune empreinte calculée — l'espion ne regarde rien"
    assert personnage_attache["n_figurine"] in set(vues), (
        f"tailles vues {sorted(set(vues))} ; celle du personnage attaché "
        f"({personnage_attache['n_figurine']}) n'apparaît pas"
    )
