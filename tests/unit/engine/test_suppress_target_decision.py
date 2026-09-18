"""`suppress_target` (Indiscriminate Detonations, Primitive F) — les TROIS sièges répondent.

La décision est posée par `_handle_shooting_end_activation` quand PLUSIEURS escouades ont été
touchées (cf. test_primitive_f_unit_state_effects.py pour la chaîne de pose). Ici : gym
(`CHOICE_k` → `_dispatch_agent_decision_action`), bot PvE (`_resolve_suppress_target_decision_for_ai_seat`,
politique déclarée), bot adversaire du gym (`env_wrappers.bot_action_for_pending_choice`, même
politique), humain (décision visible, toute autre action refusée `suppress_target_pending`).
"""
from __future__ import annotations

import pytest

from engine.agent_decision import read_pending_agent_decision
from engine.macro_intents import CHOICE_BASE
from tests.unit.engine.test_agent_decision_mechanism import _engine
from tests.unit.engine.test_primitive_f_unit_state_effects import _resolve_shooting, _wartrakk_state


def _posed(monkeypatch, **overrides):
    gs = _wartrakk_state(3)
    gs.update(overrides)
    result = _resolve_shooting(monkeypatch, gs, hit_rolls=[6, 1, 6])  # 101 et 103 touchées
    assert result["decision_type"] == "suppress_target"
    return gs


def test_gym_choice_k_supprime_la_touchee_designee_par_le_candidat(monkeypatch):
    gs = _posed(monkeypatch)
    engine = _engine(gs)
    mask, _ = engine.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert bool(mask[CHOICE_BASE]) and bool(mask[CHOICE_BASE + 1]) and not bool(mask[CHOICE_BASE + 2])

    success, result = engine._process_squad_action(
        engine.action_decoder.convert_squad_action(CHOICE_BASE + 1, gs)
    )
    assert success is True and result["suppressedTargetId"] == "103"
    assert gs["suppressed_squads"] == {"103": 1}
    assert read_pending_agent_decision(gs) is None
    assert "1" not in gs["shoot_activation_pool"], "la fin d'activation différée a repris"


def test_bot_pve_repond_par_la_politique_declaree(monkeypatch):
    """Bot PvE : désignée (101) touchée → 101, résolu dans la même requête."""
    gs = _posed(monkeypatch, player_types={"1": "ai", "2": "human"})
    engine = _engine(gs, gym_training_mode=False)
    engine.is_pve_mode = True
    settled = engine._resolve_suppress_target_decision_for_ai_seat()
    assert settled is not None and settled["suppressedTargetId"] == "101"
    assert gs["suppressed_squads"] == {"101": 1}
    assert read_pending_agent_decision(gs) is None


def test_bot_adversaire_du_gym_joue_le_choice_de_la_politique(monkeypatch):
    from ai.env_wrappers import bot_action_for_pending_choice

    gs = _posed(monkeypatch)
    engine = _engine(gs)
    mask, _ = engine.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    # Désignée 101 touchée → candidat 0.
    assert bot_action_for_pending_choice(gs, mask, "test") == CHOICE_BASE


def test_siege_humain_voit_la_decision_et_toute_autre_action_est_refusee(monkeypatch):
    gs = _posed(monkeypatch, player_types={"1": "human", "2": "ai"})
    engine = _engine(gs, gym_training_mode=False)
    assert engine._resolve_suppress_target_decision_for_ai_seat() is None, "siège humain : posée, pas tranchée"
    decision = read_pending_agent_decision(gs)
    assert decision is not None and decision["player"] == 1
    blocked = engine._reject_action_while_exhortation_pending({"action": "wait", "unitId": "1"})
    assert blocked is not None and blocked[1]["error"] == "suppress_target_pending"
    assert blocked[1]["phase"] == "shoot"
    # La réponse humaine passe par `agent_decision` (panneau) — même dispatch que le gym.
    success, result = engine._handle_agent_decision_action({"action": "agent_decision", "option_index": 0})
    assert success is True and gs["suppressed_squads"] == {"101": 1}


def test_la_suppression_laisse_sa_ligne_step_log(monkeypatch, tmp_path):
    """Grammaire 12 : « Unit N(c,r) SUPPRESSES Unit M(c,r) [SUPPRESSED→M] », non-incrémentante,
    écrite APRÈS les lignes SHOT de l'activation (même flush)."""
    from ai.step_logger import StepLogger

    gs = _wartrakk_state(2)
    _resolve_shooting(monkeypatch, gs, hit_rolls=[1, 6])  # 102 seule touchée → supprimée
    logs = [l for l in gs["action_logs"] if l["type"] == "suppress_target"]
    assert len(logs) == 1 and logs[0]["targetId"] == "102"
    assert logs[0]["message"] == "Unit 1(50,50) SUPPRESSES Unit 102(80,60) [SUPPRESSED→102]"

    engine = _engine(gs)
    out = tmp_path / "step.log"
    engine.step_logger = StepLogger(output_file=str(out), enabled=True, buffer_size=1)
    engine.step_logger.episode_number = 1
    gs["episode_number"] = 1
    engine._flush_squad_action_logs_to_step_logger(1)
    engine.step_logger._flush_buffer()
    lines = out.read_text().splitlines()
    shot = [i for i, l in enumerate(lines) if " SHOT " in l]
    sup = [i for i, l in enumerate(lines) if "SUPPRESSES Unit 102(80,60) [SUPPRESSED→102]" in l]
    assert len(sup) == 1 and shot and sup[0] > max(shot), lines
    assert lines[sup[0]].endswith("[MODELS: 1#0@(50,50,z0)] [SUCCESS]")


def test_une_escouade_detruite_par_le_tir_n_est_jamais_candidate(monkeypatch):
    """« That enemy unit is suppressed » suppose qu'elle existe : 103 touchée et DÉTRUITE (PV 2,
    deux touches), 101 touchée et vivante → une seule candidate, supprimée sans décision."""
    from engine.agent_decision import read_pending_agent_decision

    gs = _wartrakk_state(3)
    gs["models_cache"]["103#0"]["HP_CUR"] = 1
    gs["units_cache"]["103"]["HP_CUR"] = 1
    result = _resolve_shooting(monkeypatch, gs, hit_rolls=[6, 1, 6])
    assert "103" not in gs["models_cache"] or gs["models_cache"].get("103#0") is None
    assert read_pending_agent_decision(gs) is None and not result.get("waiting_for_player")
    assert gs["suppressed_squads"] == {"101": 1}
