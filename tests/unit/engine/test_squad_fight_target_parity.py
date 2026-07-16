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

from engine.macro_intents import ACTION_FIGHT  # noqa: E402


def _engine(scenario_file: str, seed: int):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="CoreAgent", training_config_name="x1_debug", controlled_agent="CoreAgent",
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

    # État forcé : plus AUCUN ennemi vivant, mais l'escouade a chargé ce tour.
    for sid in [s for s, e in list(gs["units_cache"].items()) if int(e["player"]) != our_player]:
        for mid in list(gs["squad_models"].get(sid, [])):
            gs["models_cache"].pop(mid, None)
        gs["units_cache"].pop(sid, None)
    gs["phase"] = "fight"
    gs["current_player"] = our_player
    gs["units_charged"] = {squad_id}
    gs["units_fought"] = set()

    empty_slots: List[Optional[str]] = [None] * 5
    mask = build_squad_action_mask(gs, squad_id, enemy_slot_ids=empty_slots)
    assert mask[ACTION_FIGHT] == 1, "12.04 : une escouade qui a chargé reste éligible au combat"

    _enter_fight_phase(eng)
    ok, result = eng._process_squad_action({"action": "squad_fight", "squad_id": squad_id})
    assert ok is True
    assert result["target_squad_id"] is None
    assert result["fight_result"]["attacks_made"] == 0
    assert result["fight_result"]["events"] == []


def test_commit_target_comes_from_engagement_pool(melee_scenario_file):
    """La cible retenue par le commit appartient au pool ER du flux PvP (12.05), jamais à un
    ennemi hors zone d'engagement pêché dans le mapping de slots gelé du tir."""
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
        if _fight_build_valid_target_pool(gs, require_present(get_unit_by_id(str(sid), gs), f"unit {sid}"))
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
        if _fight_build_valid_target_pool(gs, require_present(get_unit_by_id(str(sid), gs), f"unit {sid}"))
    ]
    assert candidates, "au moins une escouade sélectionnable (12.04) a une cible en ER"
    squad_id = str(candidates[0])
    pool_before = set(_fight_build_valid_target_pool(gs, require_present(get_unit_by_id(squad_id, gs), f"unit {squad_id}")))

    ok, result = eng._process_squad_action({"action": "squad_fight", "squad_id": squad_id})
    assert ok is True
    assert result["target_squad_id"] in pool_before
