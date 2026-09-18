"""Verrou grammaire 11 — `[DESIGNATED:<id>]` dans step.log.

Toute ligne SHOT porte l'escouade ennemie DÉSIGNÉE au démarrage de l'activation (cible
prioritaire en gym, première déclarée au siège humain — `designate_shoot_target`). C'est la
clause « that targeted THAT selected unit » de Hail of Bolts / Overlapping Detonations, que
l'analyzer lit pour ne bonifier que les tirs sur la désignée.

Chaîne exercée intégralement :
  unit["designated_shoot_target_id"] (posée par `designate_shoot_target`)
  → _emit_squad_shoot_log (action_log designatedTargetId)
  → _build_shot_details (designated_target_id)
  → StepLogger.log_action → [DESIGNATED:<id>]

Cycle rouge→vert : retirer `shot_tags.append(f"[DESIGNATED:{_designated}]")` dans
ai/step_logger.py fait passer `test_designated_present_sur_la_ligne` en rouge ; retirer la
clé de l'unité fait LEVER l'émetteur (chaîne rompue, jamais une ligne muette).
"""
from __future__ import annotations

import re

import pytest

from engine.phase_handlers import shared_utils as _su
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation, designate_shoot_target
from shared.data_validation import ConfigurationError
from tests.unit.ai.test_step_log_half_range import TARGET_FAR, _game_state, _log_line


def test_designated_present_sur_la_ligne(tmp_path, monkeypatch):
    """La désignée de la fixture est 101 : la ligne porte `[DESIGNATED:101]`, AVANT la cible."""
    line = _log_line(tmp_path, monkeypatch, [], target=TARGET_FAR)
    assert "[DESIGNATED:101]" in line, f"[DESIGNATED:101] absent : {line!r}"
    assert re.search(r"SHOT(?: \[[^\]]+\])* \[DESIGNATED:101\](?: \[[^\]]+\])* Unit 101", line), line


def test_sans_designation_l_emetteur_leve(monkeypatch):
    """Activation résolue sans `designate_shoot_target` : chaîne rompue → l'émetteur LÈVE au
    lieu d'écrire une ligne sans token (que l'analyzer refuserait ensuite en grammaire 11)."""
    import random

    from engine.phase_handlers import shooting_handlers

    seq = [3, 3, 4]  # mêmes jets que la fixture demi-portée
    monkeypatch.setattr(random, "randint", lambda a, b: seq.pop(0) if seq else 1)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los",
                        lambda gs, s, t: {"cover": False, "can_see": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(shooting_handlers, "_is_adjacent_to_enemy_within_cc_range",
                        lambda gs, u: False)
    monkeypatch.setattr(_su, "_squad_is_in_enemy_er", lambda _gs, sid: False)
    monkeypatch.setattr(_su, "_squads_are_engaged", lambda _gs, a, b: False)
    gs = _game_state([], target=TARGET_FAR)
    del gs["unit_by_id"]["1"]["designated_shoot_target_id"]

    with pytest.raises(ConfigurationError, match="designated_shoot_target_id"):
        build_manual_shoot_allocation(gs, "1")


def test_designate_premiere_ecriture_gagnante():
    """Deux déclarations dans la même activation : la première désignée reste (siège humain,
    « première cible déclarée »)."""
    gs = _game_state([], target=TARGET_FAR)
    del gs["unit_by_id"]["1"]["designated_shoot_target_id"]
    designate_shoot_target(gs, "1", "101")
    designate_shoot_target(gs, "1", "7")
    assert gs["unit_by_id"]["1"]["designated_shoot_target_id"] == "101"


def test_designate_ne_refait_pas_de_test_de_ligne_de_vue(monkeypatch):
    """« visible to this unit » est tenu par construction (un intent n'existe que sur une cible
    vue par sa figurine, 06.01) : la désignation n'appelle PAS `compute_unit_los` — un test
    ancre-à-ancre y rendait un faux « invisible » sur une cible vue par trois figurines (roster
    réserves, graine 2, 2026-09-18) et faisait tomber l'épisode."""
    from engine.phase_handlers import shooting_handlers

    def _never(*_a, **_k):
        raise AssertionError("compute_unit_los ne doit pas être consulté à la désignation")

    monkeypatch.setattr(shooting_handlers, "compute_unit_los", _never)
    gs = _game_state([], target=TARGET_FAR)
    del gs["unit_by_id"]["1"]["designated_shoot_target_id"]
    gs["unit_by_id"]["1"]["UNIT_RULES"] = [{
        "ruleId": "weapon_attacks_bonus_vs_designated_target", "displayName": "Hail of Bolts",
        "rule_args": {"weapon_code": "bolt_rifle", "attacks_bonus": 2},
    }]
    designate_shoot_target(gs, "1", "101")
    assert gs["unit_by_id"]["1"]["designated_shoot_target_id"] == "101"
