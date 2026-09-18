"""Grammaire 15 (producteur) — 14.03 : la ligne « SECURES <zone> [<CAPACITE>] » et le champ
`Sec=` par zone de l'instantané OBJECTIVE CONTROL, depuis le VRAI moteur (Primitive E).

`apply_secure_objective_on_control` (fin de phase de commandement) marque l'objectif contrôlé par
une escouade porteuse de `secure_objective_on_control` : l'action_log `secure_objective` qu'elle
écrit (zone, capacité, position) est formaté par `StepLogger` en une ligne datée, non-incrémentante,
et l'instantané suivant porte `:Sec=<joueur>` — sans quoi la sécurisation PAR OBJECTIF n'était
écrite nulle part (`Mthd=` est la méthode de mission, commune à tous les objectifs).
"""
from __future__ import annotations

from pathlib import Path

from ai.step_logger import StepLogger
from engine.game_state import apply_secure_objective_on_control
from engine.w40k_core import W40KEngine
from tests.unit.engine.test_primitive_e_objective_effects import OBJ_ID, ZONE_HEX, _state, _unit


def _engine_with_logger(gs, log: Path) -> tuple[W40KEngine, StepLogger]:
    eng = object.__new__(W40KEngine)
    eng.game_state = gs
    logger = StepLogger(output_file=str(log), enabled=True, buffer_size=50)
    logger.episode_number = 1
    eng.step_logger = logger
    return eng, logger


def test_la_securisation_laisse_une_ligne_secures_et_un_sec_dans_l_instantane(tmp_path: Path) -> None:
    u = _unit("1", 1, *ZONE_HEX, oc=2, unit_rules=[
        {"ruleId": "secure_objective_on_control", "displayName": "Get da Good Bitz"},
    ])
    u["col"], u["row"] = ZONE_HEX
    gs = _state([u], objective_controllers={str(OBJ_ID): 1})
    gs["objectives"][0]["name"] = "Alpha"
    log = tmp_path / "step.log"
    eng, logger = _engine_with_logger(gs, log)

    secured = apply_secure_objective_on_control(gs)
    assert secured, "prémisse : l'escouade porteuse contrôle l'objectif et le sécurise"
    eng._flush_squad_action_logs_to_step_logger(pre_action_turn=int(gs["turn"]))
    eng._log_objective_control_snapshot_if_changed()
    logger._flush_buffer()

    text = log.read_text(encoding="utf-8")
    secures = [l for l in text.splitlines() if " SECURES " in l]
    assert len(secures) == 1, text
    assert "COMMAND : Unit 1(5,5) SECURES Alpha [GET DA GOOD BITZ]" in secures[0], secures[0]
    snapshots = [l for l in text.splitlines() if "OBJECTIVE CONTROL:" in l]
    assert snapshots and ":Sec=1" in snapshots[-1], snapshots
