"""VERROU — Da Biggest and da Best : plafond d'attaques du Warboss en WAAAGH!.

melee_attacks_bonus_while_waaagh (+4 A) est DISTINCT du global waaagh_melee_atk (+1) :
  cap = cc_nb_by_weapon[Warboss][Kustom Choppa] + waaagh_melee_atk + da_biggest
      = 6 + 1 + 4 = 11

Sans ce fix, l'analyzer comptait 7 et signalait les attaques 8–11 comme fight_over_cc_nb.
"""
from __future__ import annotations

import pytest

from ai.analyzer_state import AnalyzerState
from ai.analyzer_phases.fight_handler import _cc_cap_for_line
from tests.unit.ai._fabriques import analyzer_config

_LINE = "FOUGHT Unit 6(1,1) with [Kustom Choppa] [SHOOTER_MODELS: 101#10] [TARGET_DECL:1]"
_SHOOTER = ("101#10",)
_UNIT_LIMITS = {"Warboss": {"cc_nb_by_weapon": {"Kustom Choppa": 6}}}


def _state_waaagh_actif() -> AnalyzerState:
    st = AnalyzerState(stats={})
    st.model_types = {"101#10": "Warboss"}
    st.active_effects = {2: {"waaagh": "on", "waaagh_melee_atk": "+1"}}
    return st


def test_warboss_sans_waaagh_cap_est_6() -> None:
    """Hors WAAAGH! : seul cc_nb_by_weapon compte, pas de Da Biggest."""
    st = AnalyzerState(stats={})
    st.model_types = {"101#10": "Warboss"}
    st.active_effects = {}
    cfg = analyzer_config(
        unit_attack_limits=_UNIT_LIMITS,
        melee_atk_bonus_waaagh_by_type={"Warboss": 4},
    )
    cap, _ = _cc_cap_for_line(st, cfg, _LINE, 2, "Warboss", "Kustom Choppa", 6, 1, _SHOOTER, 1)
    assert cap == 6


def test_warboss_waaagh_global_seul_cap_est_7() -> None:
    """Avec waaagh_melee_atk=+1 mais sans Da Biggest déclaré dans la config : cap = 7."""
    cfg = analyzer_config(
        unit_attack_limits=_UNIT_LIMITS,
        melee_atk_bonus_waaagh_by_type={},
    )
    cap, _ = _cc_cap_for_line(
        _state_waaagh_actif(), cfg, _LINE, 2, "Warboss", "Kustom Choppa", 6, 1, _SHOOTER, 1,
    )
    assert cap == 7


def test_warboss_da_biggest_waaagh_cap_est_11() -> None:
    """VERROU principal : Da Biggest (+4) + global (+1) → cap = 11, non 7.

    Cycle T4 ROUGE/VERT :
      - fichier en défaut (melee_atk_bonus_waaagh_by_type vide) → cap == 7 != 11 → ROUGE
      - fix restauré ({"Warboss": 4})                           → cap == 11         → VERT
    """
    cfg = analyzer_config(
        unit_attack_limits=_UNIT_LIMITS,
        melee_atk_bonus_waaagh_by_type={"Warboss": 4},
    )
    cap, _ = _cc_cap_for_line(
        _state_waaagh_actif(), cfg, _LINE, 2, "Warboss", "Kustom Choppa", 6, 1, _SHOOTER, 1,
    )
    assert cap == 11, f"attendu 11 (6 base + 1 waaagh + 4 Da Biggest), obtenu {cap}"


def test_da_biggest_na_pas_deffet_hors_waaagh() -> None:
    """Da Biggest ne s'applique QUE quand waaagh_bonus > 0 (règle `if waaagh_bonus > 0`)."""
    st = AnalyzerState(stats={})
    st.model_types = {"101#10": "Warboss"}
    st.active_effects = {}
    cfg = analyzer_config(
        unit_attack_limits=_UNIT_LIMITS,
        melee_atk_bonus_waaagh_by_type={"Warboss": 4},
    )
    cap, _ = _cc_cap_for_line(st, cfg, _LINE, 2, "Warboss", "Kustom Choppa", 6, 1, _SHOOTER, 1)
    assert cap == 6, "Da Biggest ne doit pas s'activer sans WAAAGH!"


def test_da_biggest_na_pas_deffet_pour_autre_type() -> None:
    """Un type non listé dans melee_atk_bonus_waaagh_by_type ne bénéficie pas de Da Biggest."""
    cfg = analyzer_config(
        unit_attack_limits={"WarTrakk": {"cc_nb_by_weapon": {"Choppa": 4}}},
        melee_atk_bonus_waaagh_by_type={"Warboss": 4},
    )
    st = AnalyzerState(stats={})
    st.model_types = {"88#0": "WarTrakk"}
    st.active_effects = {1: {"waaagh": "on", "waaagh_melee_atk": "+1"}}
    line = "FOUGHT Unit 5(0,0) with [Choppa] [SHOOTER_MODELS: 88#0] [TARGET_DECL:1]"
    cap, _ = _cc_cap_for_line(st, cfg, line, 1, "WarTrakk", "Choppa", 4, 1, ("88#0",), 1)
    assert cap == 5, "WarTrakk ne doit pas recevoir Da Biggest (bonus Warboss uniquement)"
