"""Parité masque/commit de `squad_fight` (régression : « aucune cible pour squad N »).

Rupture corrigée (2026-07-16) : le MASQUE gym (`build_squad_action_mask` → `_squad_is_in_fight`)
rend l'action 25 disponible pour une escouade qui a chargé ce tour, même si elle n'est plus
engagée — c'est la règle 12.04 (« It made a charge move this turn ») et c'est aussi ce que fait
le flux PvP V11 (`fight_v11_is_eligible_to_fight`, explicitement « indépendant de la présence de
cibles »). Le COMMIT gym (`_process_squad_action`, branche `squad_fight`), lui, sélectionnait sa
cible dans le mapping de slots ennemis GELÉ du tir (`get_enemy_slot_mapping`) scoré par menace
globale, SANS filtre de zone d'engagement, et levait `ValueError` quand ce mapping ne contenait
plus aucun vivant → crash d'épisode alors que l'action était légale.

Le fix aligne le commit sur le prédicat du flux PvP (`_fight_build_valid_target_pool` +
`_ai_select_fight_target`, cf. `_fight_v11_resolve_attacks`) : pool d'ennemis en zone
d'engagement, et pool vide = fight « à vide » (0 attaque), comme en PvP.

Deux verrous :
- **Parité** : toute escouade pour laquelle le masque autorise l'action 25 est commitée par le
  moteur sans exception (chargeur dont toutes les cibles sont mortes inclus).
- **Prédicat** : la cible retenue par le commit appartient au pool ER du flux PvP (jamais un
  ennemi hors zone d'engagement pêché dans le mapping de slots).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from smoke_t5_bare import MELEE_SCENARIO  # noqa: E402

from engine.macro_intents import ACTION_FIGHT_NO_TARGET  # noqa: E402


def _engine(scenario_file: str, seed: int):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug", controlled_agent="ArmageddonAgent",
        scenario_file=scenario_file, unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    eng.reset(seed=seed)
    return eng


def _enter_fight_phase(eng):
    """Entre en phase de combat par le VRAI chemin gym, pas en forçant `game_state["phase"]`.

    `squad_fight` est une sélection de l'étape FIGHT (12.04) : elle suppose la machine V11
    déroulée jusque-là (pile-in groupé 12.02 résolu, snapshot `engaged_at_fight_step_start`
    pris). Poser `phase = "fight"` à la main laisse `fight_subphase` à None — un état que le
    moteur n'atteint jamais en vrai, et où le commit doit lever plutôt que deviner.
    """
    from engine.phase_handlers import fight_handlers

    res = fight_handlers.fight_phase_start(eng.game_state)
    return eng._fight_v11_gym_after_phase_start(res)


def _setup_fight_phase_charged(
    gs: dict,
    squad_id: str,
    our_player: int,
    *,
    with_settle_keys: bool = False,
) -> None:
    """Pose l'état minimal pour l'étape FIGHT d'une escouade ayant chargé ce tour.

    Usage : tests qui patchent des helpers internes et ne peuvent pas emprunter
    `_enter_fight_phase` (chemin réel). `with_settle_keys=True` ajoute `pile_in_done`
    et `consolidation_done` requis par `_fight_v11_gym_settle` post-fight.
    """
    gs["phase"] = "fight"
    gs["fight_subphase"] = "fight"
    gs["current_player"] = our_player
    gs["fight_step"] = "fights_first"
    gs["fight_selector"] = our_player
    gs["engaged_at_fight_step_start"] = {}
    gs["units_charged"] = {squad_id}
    gs["units_selected_to_fight"] = set()
    gs["units_fought"] = set()
    if with_settle_keys:
        gs["pile_in_done"] = set()
        gs["consolidation_done"] = set()


@pytest.fixture()
def melee_scenario_file():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "melee.json"
        path.write_text(json.dumps(MELEE_SCENARIO))
        yield str(path)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_squad_fight_mask_offers_only_committable_actions(melee_scenario_file, seed):
    """Repro exacte du bug : seed=1 levait `squad_fight: aucune cible pour squad 3`.

    Aucune action proposée par le masque ne doit faire échouer le commit.
    """
    eng = _engine(melee_scenario_file, seed)
    for i in range(400):
        if eng.game_state.get("game_over"):
            break
        mask = eng.get_action_mask()
        if not mask.any():
            break
        action = int(np.random.default_rng(seed * 777 + i).choice(np.flatnonzero(mask)))
        eng.step(action)


def test_charged_squad_without_target_fights_empty(melee_scenario_file):
    """Escouade qui a chargé + tous ses ennemis morts : le masque l'autorise (12.04), le commit
    la résout à vide (0 attaque) au lieu de lever — miroir de `_fight_v11_resolve_attacks`."""
    from engine.phase_handlers.shared_utils import build_squad_action_mask

    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    squad_id = next(iter(gs["units_cache"]))
    our_player = int(gs["units_cache"][squad_id]["player"])

    # État forcé : plus AUCUN ennemi vivant, mais l'escouade a chargé ce tour. On pose une étape
    # FIGHT réelle (sous-phase + snapshot + machine de sélection) car le masque dérive désormais
    # du pool 12.04 (`fight_v11_current_pool`), qui n'a de sens que dans la sous-phase "fight".
    for sid in [s for s, e in list(gs["units_cache"].items()) if int(e["player"]) != our_player]:
        for mid in list(gs["squad_models"].get(sid, [])):
            gs["models_cache"].pop(mid, None)
        gs["units_cache"].pop(sid, None)
    _setup_fight_phase_charged(gs, squad_id, our_player)

    empty_slots: List[Optional[str]] = [None] * 5
    mask = build_squad_action_mask(gs, squad_id, enemy_slot_ids=empty_slots)
    assert mask[ACTION_FIGHT_NO_TARGET] == 1, "12.04 : chargeuse sans cible -> combat à vide"

    _enter_fight_phase(eng)
    ok, result = eng._process_squad_action({"action": "squad_fight", "squad_id": squad_id})
    assert ok is True
    assert result["target_squad_id"] is None
    assert result["fight_result"]["attacks_made"] == 0
    assert result["fight_result"]["events"] == []


def test_commit_target_comes_from_engagement_pool(melee_scenario_file):
    """La cible commitée est CELLE que désigne le slot joué, et elle appartient au pool ER 12.05.

    ⚠️ Depuis V11 §9 P3-1 la cible n'est plus choisie par le moteur (`_ai_select_fight_target`)
    mais portée par l'action (`target_slot`, index du mapping de slots ennemis). Le test vérifie
    donc les deux bouts : le slot joué désigne bien la cible attendue, ET cette cible est dans le
    pool d'engagement — l'ancienne rupture (cible pêchée dans le mapping du tir, hors ER) reste
    impossible parce que le moteur refuse tout slot hors pool.
    """
    from engine.game_utils import get_unit_by_id

    from shared.data_validation import require_present
    from engine.phase_handlers.fight_handlers import (
        _fight_build_valid_target_pool,
        fight_v11_current_pool,
    )

    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    gs["phase"] = "fight"
    engaged = [
        sid for sid in gs["units_cache"]
        if _fight_build_valid_target_pool(gs, require_present(get_unit_by_id(gs, str(sid)), f"unit {sid}"))
    ]
    assert engaged, "le scénario mêlée est pré-engagé : au moins une escouade a une cible ER"
    gs["current_player"] = int(gs["units_cache"][str(engaged[0])]["player"])
    gs["units_fought"] = set()

    _enter_fight_phase(eng)

    # Le squad doit venir du pool de sélection 12.04 : c'est celui que le masque propose, donc
    # le seul que le commit accepte. Le pile-in groupé est déjà résolu à ce stade, `pool_before`
    # est donc l'ER réelle au moment de la sélection.
    candidates = [
        sid for sid in fight_v11_current_pool(gs)
        if _fight_build_valid_target_pool(gs, require_present(get_unit_by_id(gs, str(sid)), f"unit {sid}"))
    ]
    assert candidates, "au moins une escouade sélectionnable (12.04) a une cible en ER"
    squad_id = str(candidates[0])
    pool_before = set(
        str(t)
        for t in _fight_build_valid_target_pool(
            gs, require_present(get_unit_by_id(gs, squad_id), f"unit {squad_id}")
        )
    )

    # Le masque n'ouvre que les slots dont la cible est dans le pool 12.05 : on joue l'un d'eux.
    from engine.macro_intents import FIGHT_SLOT_BASE
    from engine.phase_handlers.shared_utils import build_squad_action_mask, get_enemy_slot_mapping

    our_player = int(gs["units_cache"][squad_id]["player"])
    slot_map = get_enemy_slot_mapping(gs, our_player)
    mask = build_squad_action_mask(gs, squad_id, enemy_slot_ids=slot_map)
    open_slots = [i for i, sid in enumerate(slot_map) if mask[FIGHT_SLOT_BASE + i] == 1]
    assert open_slots, "le masque doit ouvrir un slot par cible 12.05"
    assert {str(slot_map[i]) for i in open_slots} == pool_before, (
        "les slots ouverts décrivent EXACTEMENT le pool d'engagement 12.05"
    )

    chosen_slot = open_slots[0]
    expected_target = str(slot_map[chosen_slot])
    ok, result = eng._process_squad_action(
        {"action": "squad_fight", "squad_id": squad_id, "target_slot": chosen_slot}
    )
    assert ok is True
    assert result["target_squad_id"] == expected_target, "le commit frappe la cible du slot joué"
    assert result["target_squad_id"] in pool_before


def test_commit_refuses_slot_outside_engagement_pool(melee_scenario_file):
    """Un slot ennemi HORS pool 12.05 est refusé — jamais absorbé par un repli sur l'heuristique.

    C'est la garde qui rend la nouvelle dimension d'action sûre : sans elle, un slot pointant un
    ennemi hors zone d'engagement ferait combattre à distance (violation 12.05) sans rien lever.
    """
    from engine.game_utils import get_unit_by_id
    from shared.data_validation import require_present
    from engine.phase_handlers.fight_handlers import (
        _fight_build_valid_target_pool,
        fight_v11_current_pool,
    )
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    gs["phase"] = "fight"
    gs["units_fought"] = set()
    _enter_fight_phase(eng)

    candidates = [
        sid for sid in fight_v11_current_pool(gs)
        if _fight_build_valid_target_pool(gs, require_present(get_unit_by_id(gs, str(sid)), f"unit {sid}"))
    ]
    assert candidates
    squad_id = str(candidates[0])
    pool = {str(t) for t in _fight_build_valid_target_pool(
        gs, require_present(get_unit_by_id(gs, squad_id), f"unit {squad_id}")
    )}
    our_player = int(gs["units_cache"][squad_id]["player"])
    slot_map = get_enemy_slot_mapping(gs, our_player)
    bad_slots = [i for i, sid in enumerate(slot_map) if sid is None or str(sid) not in pool]
    assert bad_slots, "le mapping compte au moins un slot vide ou hors ER"

    with pytest.raises(ValueError, match="hors du pool de combat 12.05"):
        eng._process_squad_action(
            {"action": "squad_fight", "squad_id": squad_id, "target_slot": bad_slots[0]}
        )


def test_commit_refuses_empty_fight_when_targets_exist(melee_scenario_file):
    """`ACTION_FIGHT_NO_TARGET` avec un pool 12.05 NON vide est une rupture masque/commit.

    Sans cette garde, l'agent pourrait esquiver le combat en se déclarant « sans cible » alors
    qu'il est engagé — 12.04 l'oblige à combattre, et le masque ne lui offre pas ce choix.
    """
    from engine.game_utils import get_unit_by_id
    from shared.data_validation import require_present
    from engine.phase_handlers.fight_handlers import (
        _fight_build_valid_target_pool,
        fight_v11_current_pool,
    )

    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    gs["phase"] = "fight"
    gs["units_fought"] = set()
    _enter_fight_phase(eng)

    candidates = [
        sid for sid in fight_v11_current_pool(gs)
        if _fight_build_valid_target_pool(gs, require_present(get_unit_by_id(gs, str(sid)), f"unit {sid}"))
    ]
    assert candidates
    with pytest.raises(ValueError, match="combat a vide"):
        eng._process_squad_action({"action": "squad_fight", "squad_id": str(candidates[0])})


def test_snapshot_engaged_unit_with_dead_enemy_offers_fight_and_breaks_loop(melee_scenario_file):
    """Régression du crash `BotControlledEnv infinite loop … phase=fight`.

    Scénario exact : une escouade ENGAGÉE AU DÉBUT de l'étape FIGHT (snapshot
    `engaged_at_fight_step_start` = True), sans avoir chargé, dont l'unique ennemi est mort
    pendant l'étape → elle n'est plus engagée MAINTENANT. 12.04 la garde éligible (snapshot),
    donc `fight_v11_current_pool` la contient. L'ancien masque (`_squad_is_in_fight`, engaged-now
    + charge, sans le snapshot) n'offrait que WAIT → WAIT ne clôt pas l'éligibilité → boucle.

    Le fix aligne le masque sur le pool : FIGHT est offert, le commit résout à vide (0 attaque),
    l'unité est enregistrée `units_selected_to_fight` → elle sort du pool → la boucle se termine.
    """
    from engine.macro_intents import ACTION_WAIT
    from engine.phase_handlers.shared_utils import build_squad_action_mask
    from engine.phase_handlers.fight_handlers import fight_v11_current_pool

    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    squad_id = next(iter(gs["units_cache"]))
    our_player = int(gs["units_cache"][squad_id]["player"])

    # Tous les ennemis meurent (modèles retirés) : l'escouade n'est plus engagée MAINTENANT.
    for sid in [s for s, e in list(gs["units_cache"].items()) if int(e["player"]) != our_player]:
        for mid in list(gs["squad_models"].get(sid, [])):
            gs["models_cache"].pop(mid, None)
        gs["units_cache"].pop(sid, None)

    # Étape FIGHT réelle avec le snapshot qui la marque engagée AU DÉBUT (mais pas chargée).
    gs["phase"] = "fight"
    gs["fight_subphase"] = "fight"
    gs["current_player"] = our_player
    gs["fight_step"] = "fights_first"
    gs["fight_selector"] = our_player
    gs["engaged_at_fight_step_start"] = {squad_id: True}
    gs["units_charged"] = set()
    gs["units_selected_to_fight"] = set()
    gs["units_fought"] = set()
    gs["pile_in_done"] = set()          # posés par fight_v11_start ; requis par le settle post-fight
    gs["consolidation_done"] = set()

    # Le pool 12.04 la contient (via le snapshot), le masque DOIT offrir FIGHT — pas seulement WAIT.
    assert squad_id in fight_v11_current_pool(gs)
    slots: List[Optional[str]] = [None] * 5
    mask = build_squad_action_mask(gs, squad_id, enemy_slot_ids=slots)
    assert mask[ACTION_FIGHT_NO_TARGET] == 1, "12.04 : engagée au snapshot, sans cible -> combat à vide"
    assert mask[ACTION_WAIT] == 0, "une escouade actionnable au FIGHT ne reçoit pas WAIT"

    # Commit : résolution à vide (aucun ennemi), sélection enregistrée, sortie du pool.
    ok, result = eng._process_squad_action({"action": "squad_fight", "squad_id": squad_id})
    assert ok is True
    assert result["target_squad_id"] is None
    assert result["fight_result"]["attacks_made"] == 0
    assert squad_id in gs["units_selected_to_fight"], "l'unité est enregistrée -> clôt son éligibilité"
    assert squad_id not in fight_v11_current_pool(gs), "hors du pool -> plus de re-sélection -> pas de boucle"


def test_overrun_pile_in_called_when_unengaged(melee_scenario_file):
    """OVERRUN 12.06 : une escouade non engagée au moment de son fight tente le pile-in par-figurine.

    État forcé (miroir de test_charged_squad_without_target_fights_empty) : tous les ennemis
    supprimés, escouade chargée mais non engagée. Verrou : _fight_overrun_pile_in_plan est
    invoquée car la condition «not _fight_v11_engaged_now» est vraie (aucun ennemi vivant).
    """
    import engine.phase_handlers.shared_utils as su_module

    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    squad_id = next(iter(gs["units_cache"]))
    our_player = int(gs["units_cache"][squad_id]["player"])

    # Supprime tous les ennemis (pool vide → fight à vide, unité non engagée).
    for sid in [s for s, e in list(gs["units_cache"].items()) if int(e["player"]) != our_player]:
        for mid in list(gs["squad_models"].get(sid, [])):
            gs["models_cache"].pop(mid, None)
        gs["units_cache"].pop(sid, None)

    _setup_fight_phase_charged(gs, squad_id, our_player, with_settle_keys=True)

    calls: List[str] = []
    orig = su_module._fight_overrun_pile_in_plan

    def _spy(game_state, sid):
        calls.append(str(sid))
        return None  # bloque le move effectif — le verrou porte sur l'APPEL, pas l'effet

    su_module._fight_overrun_pile_in_plan = _spy
    try:
        eng._process_squad_action({"action": "squad_fight", "squad_id": squad_id})
    finally:
        su_module._fight_overrun_pile_in_plan = orig

    assert squad_id in calls, "overrun pile-in doit être tenté pour une escouade non engagée"


def test_overrun_mask_opens_fight_slot_not_no_target():
    """Rupture masque/commit overrun 12.06 : pool pré-pile-in vide → FIGHT_NO_TARGET → crash commit.

    Unité non engagée qui a chargé, ennemi à 3" (>EZ=2, ≤pile_in=5). Avant le fix, le masque
    ouvrait ACTION_FIGHT_NO_TARGET (pool 12.05 vide SUR la position actuelle). Au commit, le
    moteur exécutait la pile-in overrun AVANT de tester le pool : l'ennemi devenait atteignable
    et le commit levait « action combat a vide reçue … alors que le pool 12.05 offre ».

    Après fix : le masque simule la pile-in overrun et ouvre le slot fight de l'ennemi accessible
    post-pile-in → parité masque/commit rétablie.
    """
    from engine.macro_intents import ACTION_FIGHT_NO_TARGET
    from engine.phase_handlers.shared_utils import (
        SQUAD_ACTION_FIGHT_SLOT_BASE,
        SQUAD_ACTION_FIGHT_SLOT_COUNT,
        build_squad_action_mask,
        get_enemy_slot_mapping,
        init_enemy_slot_mapping,
    )
    from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

    # Attaquant P1 à (10,10), ennemi P2 à (10,13). dist=3 > EZ=2 → non engagé ; ≤5 → pile-in.
    attacker = synthetic_unit("1", 1, [{"col": 10, "row": 10}])
    enemy = synthetic_unit("2", 2, [{"col": 10, "row": 13}])

    gs = synthetic_state(
        [attacker, enemy],
        phase="fight",
        game_rules={},
        fight_subphase="fight",
        current_player=1,
        fight_step="fights_first",
        fight_selector=1,
        engaged_at_fight_step_start={},
        units_charged={"1"},
        units_selected_to_fight=set(),
        units_fought=set(),
        pile_in_done=set(),
        consolidation_done=set(),
    )

    init_enemy_slot_mapping(gs, 1)
    enemy_slots = get_enemy_slot_mapping(gs, 1)
    mask = build_squad_action_mask(gs, "1", enemy_slot_ids=enemy_slots)

    fight_bits = [mask[SQUAD_ACTION_FIGHT_SLOT_BASE + i] for i in range(SQUAD_ACTION_FIGHT_SLOT_COUNT)]
    assert any(fight_bits), (
        "Le slot fight de l'ennemi doit être ouvert : la pile-in overrun l'amène en zone d'engagement"
    )
    assert mask[ACTION_FIGHT_NO_TARGET] == 0, (
        "FIGHT_NO_TARGET ne doit pas être ouvert quand une cible est atteignable post-pile-in"
    )


def test_overrun_pile_in_plan_returns_none_when_no_enemy_in_range(melee_scenario_file):
    """_fight_overrun_pile_in_plan retourne None si aucun ennemi à ≤5" (12.03 BEFORE MOVING).

    Test direct de la fonction (pas via le moteur) : ennemi à 8", hors portée → plan None.
    """
    from engine.phase_handlers.shared_utils import _fight_overrun_pile_in_plan

    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    ish = int(gs["inches_to_subhex"])

    all_ids = list(gs["units_cache"])
    our_id = all_ids[0]
    our_player = int(gs["units_cache"][our_id]["player"])
    foe_ids = [s for s in all_ids if int(gs["units_cache"][s]["player"]) != our_player]
    assert foe_ids
    foe_id = foe_ids[0]

    # Positionne l'ennemi à 8" (> 5" pile_in_target_range)
    for mid in gs["squad_models"].get(our_id, []):
        gs["models_cache"][mid]["col"] = 10
        gs["models_cache"][mid]["row"] = 10
    gs["units_cache"][our_id]["col"] = 10
    gs["units_cache"][our_id]["row"] = 10
    for mid in gs["squad_models"].get(foe_id, []):
        gs["models_cache"][mid]["col"] = 10
        gs["models_cache"][mid]["row"] = 10 + 8 * ish
    gs["units_cache"][foe_id]["col"] = 10
    gs["units_cache"][foe_id]["row"] = 10 + 8 * ish

    gs["phase"] = "fight"
    gs["fight_subphase"] = "fight"
    gs["current_player"] = our_player
    gs["engaged_at_fight_step_start"] = {}
    gs["units_charged"] = {our_id}
    gs["units_selected_to_fight"] = set()
    gs["units_fought"] = set()
    gs["pile_in_done"] = set()
    gs["consolidation_done"] = set()

    plan = _fight_overrun_pile_in_plan(gs, our_id)
    assert plan is None, "ennemi a 8\" hors portee overrun : aucun plan attendu"


def test_overrun_mask_no_crash_with_off_table_enemy_in_slot():
    """Régression : ValueError dans build_squad_action_mask quand un ennemi hors table (réserves,
    sentinelle (-1,-1)) est présent dans les slots ennemis lors du path overrun 12.06.

    Scénario : attaquant P1 non-engagé qui a chargé ; ennemi A P2 sur table à portée pile-in ;
    ennemi B P2 en réserve stratégique (hors table) dans les slots. Avant le fix, le masque
    appelait `unit_entries_within_engagement_zone` sur l'ennemi hors table → crash. Après le fix,
    l'ennemi hors table est sauté silencieusement, le slot de l'ennemi A sur table est ouvert.
    """
    from engine.phase_handlers.shared_utils import (
        SQUAD_ACTION_FIGHT_SLOT_BASE,
        SQUAD_ACTION_FIGHT_SLOT_COUNT,
        build_squad_action_mask,
        get_enemy_slot_mapping,
        init_enemy_slot_mapping,
    )
    from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

    # Attaquant P1 à (10,10), ennemi A P2 à (10,13) sur table (dist=3 > EZ=2, ≤pile-in=5).
    attacker = synthetic_unit("1", 1, [{"col": 10, "row": 10}])
    enemy_a = synthetic_unit("2", 2, [{"col": 10, "row": 13}])

    gs = synthetic_state(
        [attacker, enemy_a],
        phase="fight",
        game_rules={},
        fight_subphase="fight",
        current_player=1,
        fight_step="fights_first",
        fight_selector=1,
        engaged_at_fight_step_start={},
        units_charged={"1"},
        units_selected_to_fight=set(),
        units_fought=set(),
        pile_in_done=set(),
        consolidation_done=set(),
    )

    # Injecter ennemi B hors table dans units_cache (sentinelle (-1,-1) = réserve stratégique).
    gs["units_cache"]["3"] = {
        "id": "3",
        "col": -1,
        "row": -1,
        "player": 2,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "orientation": 0,
        "occupied_hexes": set(),
        "models": [],
        "HP_CUR": 1,
        "HP_MAX": 1,
    }

    init_enemy_slot_mapping(gs, 1)
    # Injecter '3' dans le tableau brut : simule un ennemi affecté à un slot PUIS sorti de la table
    # (réserve stratégique après déploiement). _refresh ne libère pas ce slot tant que l'unité est
    # dans units_cache ; la régression survient précisément dans cet état.
    raw_mapping: list = gs["enemy_slot_mapping_p1"]
    free_slot = next(i for i, sid in enumerate(raw_mapping) if sid is None)
    raw_mapping[free_slot] = "3"
    enemy_slots = get_enemy_slot_mapping(gs, 1)

    # Vérifier que l'ennemi hors table a bien un slot (racine du crash).
    assert "3" in enemy_slots, "l'ennemi hors table doit avoir un slot pour déclencher la régression"

    # Avant fix : crash ValueError. Après fix : pas de crash.
    mask = build_squad_action_mask(gs, "1", enemy_slot_ids=enemy_slots)

    fight_bits = [mask[SQUAD_ACTION_FIGHT_SLOT_BASE + i] for i in range(SQUAD_ACTION_FIGHT_SLOT_COUNT)]
    assert any(fight_bits), "le slot de l'ennemi A sur table doit être ouvert après pile-in overrun"
    # Le slot de l'ennemi hors table doit rester fermé.
    off_table_slot = enemy_slots.index("3")
    assert mask[SQUAD_ACTION_FIGHT_SLOT_BASE + off_table_slot] == 0, (
        "l'ennemi hors table ne doit jamais ouvrir un slot fight"
    )


def test_overrun_post_pilin_uses_per_model_base_size_x5():
    """Bug 12.06 : post-overrun, le pool de cibles doit utiliser le socle PAR FIGURINE.

    Rupture masque/commit quand un personnage attaché a un socle plus grand que son escouade :
    le masque utilise _synth_model_entry (socle modèle), l'ancien commit utilisait
    _fight_build_valid_target_pool (socle escouade). Delta de 2 subhexes → zone de crash de
    4 subhexes à x5 (euclidien).

    Setup géométrique à x5 :
    - Personnage à (17,10) BASE_SIZE=10, escouade BASE_SIZE=6.
    - Ennemi à (0,10) BASE_SIZE=6.
    - center_dist ≈ 25.5 (hex_center units) ; EZ seuil = 10 × 1.5 = 15.0.
    - Socle escouade (base=6) : edge ≈ 25.5 - 4.5 - 4.5 = 16.5 > 15.0 → hors EZ (bug).
    - Socle personnage (base=10) : edge ≈ 25.5 - 7.5 - 4.5 = 13.5 ≤ 15.0 → dans EZ (fix).

    RED (avant fix) : _fight_build_valid_target_pool retourne [] → pool vide.
    GREEN (après fix) : _model_can_fight_target pour le personnage retourne True.
    """
    from engine.phase_handlers.fight_handlers import (
        _fight_build_valid_target_pool,
        _model_can_fight_target,
    )
    from engine.game_utils import get_unit_by_id
    from shared.data_validation import require_present
    from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

    # Escouade P1 : un modèle (personnage) BASE_SIZE=10 ; escouade de BASE_SIZE=6.
    atk = synthetic_unit("atk", 1, [{"col": 17, "row": 10, "BASE_SIZE": 10}], BASE_SIZE=6)
    enemy = synthetic_unit("enemy", 2, [{"col": 0, "row": 10}], BASE_SIZE=6)

    gs = synthetic_state(
        [atk, enemy],
        phase="fight",
        game_rules={"engagement_zone": 10},   # 2" × 5 subhex/inch = 10 subhexes
        inches_to_subhex=5,
        fight_subphase="fight",
        current_player=1,
        fight_step="fights_first",
        fight_selector=1,
        engaged_at_fight_step_start={},
        units_charged={"atk"},
        units_selected_to_fight=set(),
        units_fought=set(),
        pile_in_done=set(),
        consolidation_done=set(),
    )

    unit = require_present(get_unit_by_id(gs, "atk"), "unit atk")

    # RED : ancienne branche commit (socle escouade=6) → pool vide — racine du crash bot.
    assert _fight_build_valid_target_pool(gs, unit) == [], (
        "socle escouade=6 hors EZ à x5 (edge≈16.5>15.0) : pool doit être vide — racine du bug"
    )

    # GREEN : nouvelle branche post-overrun (socle par-figurine) → cible trouvée via personnage.
    mc = gs["models_cache"]
    alive_mids = [m for m in gs["squad_models"].get("atk", []) if m in mc]
    assert any(_model_can_fight_target(gs, mc[m], "atk", "enemy") for m in alive_mids), (
        "personnage socle=10 dans EZ à x5 (edge≈13.5≤15.0) : pool doit être non vide après fix"
    )


def test_fight_no_target_not_opened_when_all_slots_exhausted_by_out_of_ez(melee_scenario_file):
    """Débordement de slots : fight_targets non-vide mais AUCUN slot ne désigne une cible EZ.

    Scénario : K=20 slots mappés sur des ennemis HORS EZ, mais _fight_build_valid_target_pool
    retourne un ennemi EN EZ qui n'a pas de slot (>K escouades ennemies). Avant le fix, le masque
    ouvrait FIGHT_NO_TARGET (aucun slot ouvert → inner guard sans filtre fight_targets). Le commit
    (_process_squad_action) trouvait ces cibles et levait 'combat a vide' → rupture masque/commit.

    Fix : FIGHT_NO_TARGET n'est ouvert que si fight_targets est vide (pool vraiment vide).
    """
    from unittest.mock import patch
    from engine.phase_handlers.shared_utils import (
        build_squad_action_mask,
        SQUAD_ACTION_FIGHT_SLOT_BASE,
        SQUAD_ACTION_FIGHT_SLOT_COUNT,
    )

    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    squad_id = next(iter(gs["units_cache"]))
    our_player = int(gs["units_cache"][squad_id]["player"])

    _setup_fight_phase_charged(gs, squad_id, our_player)

    # K slots occupés par des ennemis hors EZ ; "ez-only" est en EZ mais n'a pas de slot.
    out_of_ez_slots: List[Optional[str]] = [f"out-of-ez-{i}" for i in range(SQUAD_ACTION_FIGHT_SLOT_COUNT)]

    with patch(
        "engine.phase_handlers.fight_handlers._fight_build_valid_target_pool",
        return_value=["ez-only"],
    ):
        mask = build_squad_action_mask(gs, squad_id, enemy_slot_ids=out_of_ez_slots)

    assert mask[ACTION_FIGHT_NO_TARGET] == 0, (
        "fight_targets non-vide : FIGHT_NO_TARGET ne doit PAS s'ouvrir — "
        "le commit trouverait des cibles et lèverait 'combat a vide'"
    )
    fight_range = mask[SQUAD_ACTION_FIGHT_SLOT_BASE: SQUAD_ACTION_FIGHT_SLOT_BASE + SQUAD_ACTION_FIGHT_SLOT_COUNT]
    assert not any(fight_range), "Aucun slot ne doit s'ouvrir : 'ez-only' absent du mapping de slots"
