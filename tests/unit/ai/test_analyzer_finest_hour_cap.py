"""Finest Hour (once_per_battle_melee_buff) : le token [FINEST HOUR] lève le plafond d'attaques.

Root cause : `_cc_cap_for_line` ne lisait que `waaagh_melee_atk` depuis EFFECTS pour ajuster le
cap. Le bonus de Finest Hour (+3A sur CaptainRelicShield) n'y apparaissait jamais — il est posé
par le moteur directement sur les caractéristiques de l'intent, sans passer par EFFECTS. Résultat :
chaque ligne d'attaque de Finest Hour comptait 3 de trop, soit 37 faux positifs surcharge_atk.

Fix : le token [FINEST HOUR] est maintenant émis sur CHAQUE ligne FOUGHT de l'activation ;
`_cc_cap_for_line` le détecte et ajoute `attacks_bonus` par figurine portant la règle, en lisant
le type réel de chaque socle depuis `state.model_types` (pas le type d'escouade) — miroir exact
du Waaagh! dont le bonus s'ajoute à toutes les figurines portant la capacité.
"""
from __future__ import annotations

import pytest

from ai.analyzer_state import AnalyzerState
from tests.unit.ai._fabriques import analyzer_config

# CaptainRelicShield — porteur de once_per_battle_melee_buff (attacks_bonus=3, vérifié registre).
CAPTAIN_TYPE = "CaptainRelicShield"
CC_WEAPON = "Relic Shield"
CC_NB = 4      # NB de base de l'arme (valeur test, pas datasheet réelle)
FH_BONUS = 3   # attacks_bonus de once_per_battle_melee_buff (vérifié registre)


def _cap(
    state: AnalyzerState,
    config,
    action_desc: str,
    fighter_unit_type: str = CAPTAIN_TYPE,
    weapon: str = CC_WEAPON,
    cc_nb_single: int = CC_NB,
    n_models: int = 1,
    target_count: int = 1,
) -> int:
    from ai.analyzer_perfig import parse_shooter_models_segment
    from ai.analyzer_phases.fight_handler import _cc_cap_for_line
    cap, _ = _cc_cap_for_line(
        state, config, action_desc, 1, fighter_unit_type, weapon,
        cc_nb_single, n_models, parse_shooter_models_segment(action_desc), target_count,
    )
    return cap


def test_sans_finest_hour_plafond_inchange() -> None:
    """Sans [FINEST HOUR] sur la ligne, le plafond reste NB de base."""
    st = AnalyzerState(stats={})
    st.model_types = {"1#0": CAPTAIN_TYPE}
    cfg = analyzer_config(
        unit_attack_limits={CAPTAIN_TYPE: {"cc_nb_by_weapon": {CC_WEAPON: CC_NB}}},
        once_per_battle_melee_bonus_by_type={CAPTAIN_TYPE: FH_BONUS},
    )
    assert _cap(st, cfg, "[SHOOTER_MODELS: 1#0]") == CC_NB


def test_finest_hour_leve_le_plafond_par_figurine() -> None:
    """[FINEST HOUR] sur la ligne : le plafond inclut attacks_bonus pour le Captain."""
    st = AnalyzerState(stats={})
    st.model_types = {"1#0": CAPTAIN_TYPE}
    cfg = analyzer_config(
        unit_attack_limits={CAPTAIN_TYPE: {"cc_nb_by_weapon": {CC_WEAPON: CC_NB}}},
        once_per_battle_melee_bonus_by_type={CAPTAIN_TYPE: FH_BONUS},
    )
    assert _cap(st, cfg, "[SHOOTER_MODELS: 1#0] [FINEST HOUR]") == CC_NB + FH_BONUS


def test_finest_hour_captain_attache_squad_type_distinct() -> None:
    """Captain attaché : fighter_unit_type est le type d'escouade, pas le type Captain.

    Le bonus doit quand même s'appliquer — le lookup utilise model_types[mid], pas fighter_unit_type.
    """
    SQUAD_TYPE = "AssaultIntercessor"
    st = AnalyzerState(stats={})
    st.model_types = {"1#0": CAPTAIN_TYPE}   # model 1#0 = Captain, pas Intercessor
    cfg = analyzer_config(
        unit_attack_limits={
            CAPTAIN_TYPE: {"cc_nb_by_weapon": {CC_WEAPON: CC_NB}},
            SQUAD_TYPE: {"cc_nb_by_weapon": {CC_WEAPON: 3}},
        },
        once_per_battle_melee_bonus_by_type={CAPTAIN_TYPE: FH_BONUS},
    )
    # Avec fighter_unit_type = SQUAD_TYPE (comme en production pour une unité fusionnée),
    # le bonus doit quand même apparaître parce que le MODÈLE est le Captain.
    assert _cap(
        st, cfg, "[SHOOTER_MODELS: 1#0] [FINEST HOUR]",
        fighter_unit_type=SQUAD_TYPE, cc_nb_single=3,
    ) == CC_NB + FH_BONUS


def test_finest_hour_repli_sans_shooter_models() -> None:
    """Sans [SHOOTER_MODELS:] : Finest Hour s'ajoute UNE FOIS (once per battle, pas par figurine).

    Le Waaagh! est +1 par figurine (caractéristique d'arme modifiée) ; Finest Hour est
    once_per_battle_melee_buff — déclenchée une fois par activation, pas par modèle.
    n_fighter_models=3 ne doit pas tripler le bonus.
    """
    st = AnalyzerState(stats={})   # model_types vide → repli
    cfg = analyzer_config(
        unit_attack_limits={CAPTAIN_TYPE: {"cc_nb_by_weapon": {CC_WEAPON: CC_NB}}},
        once_per_battle_melee_bonus_by_type={CAPTAIN_TYPE: FH_BONUS},
    )
    # n_models=1 : plafond = NB × 1 + FH_BONUS (once)
    assert _cap(st, cfg, "[FINEST HOUR]", n_models=1) == CC_NB + FH_BONUS
    # n_models=3 : plafond = NB × 3 + FH_BONUS (toujours once, pas × 3)
    assert _cap(st, cfg, "[FINEST HOUR]", n_models=3) == CC_NB * 3 + FH_BONUS


def test_finest_hour_unité_sans_règle_pas_de_bonus() -> None:
    """Unité sans once_per_battle_melee_buff : [FINEST HOUR] sur la ligne ne change rien."""
    OTHER_TYPE = "AssaultIntercessor"
    st = AnalyzerState(stats={})
    st.model_types = {"1#0": OTHER_TYPE}
    cfg = analyzer_config(
        unit_attack_limits={OTHER_TYPE: {"cc_nb_by_weapon": {"Astartes Chainsword": 4}}},
        once_per_battle_melee_bonus_by_type={CAPTAIN_TYPE: FH_BONUS},  # seul Captain a la règle
    )
    assert _cap(
        st, cfg, "[SHOOTER_MODELS: 1#0] [FINEST HOUR]",
        fighter_unit_type=OTHER_TYPE, weapon="Astartes Chainsword",
    ) == 4  # pas de bonus
