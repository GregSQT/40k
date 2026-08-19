"""Lot 3 : contrôles des règles d'unité dont la donnée est déjà au journal.

Couvre :
- PROJ.1.3.charge_impact   — seuil et dégâts MW de l'impact 11.01 (AssaultIntercessorJumpPack)
- PROJ.1.4.reroll_save_fight — relance 1 svg en mêlée (TyranidWarriorMelee côté cible)
- PROJ.1.2.oath_target     — cible blessée = unité jurée 08.04 (Intercessor avec oath_of_moment)
- PROJ.1.2.closest_target_penetration — réduction AP obs_id=3 (AggressorBoltStorm)
- PROJ.1.9.leader / .support — paire Attached: de l'entête (Captain / Ancient)
"""

from __future__ import annotations

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log

OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))
EPISODE_END = (
    "[10:00:09] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 ZONES=rect b NW:Ctrl=none\n"
    "[10:00:10] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s\n"
)


def _parse(log_text: str, tmp_path):
    log = tmp_path / "step.log"
    log.write_text(log_text)
    return an.parse_step_log(str(log))


def _usage(stats, rule_id: str) -> int:
    return sum(stats["rule_usage"][rule_id].values())


# ─── 1. CHARGE IMPACT ────────────────────────────────────────────────────────


def _charge_impact_log(threshold: int, damage: int, tmp_path) -> dict:
    units = (
        "[10:00:00] Unit 1 (AssaultIntercessorJumpPack) P1: Starting position (50,50), HP_MAX=2"
        " base=round/6 [MODELS: 1#0@(50,50,z0)] [MODEL_TYPES: 1#0=AssaultIntercessorJumpPack]\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (90,50), HP_MAX=2"
        " base=round/6 [MODELS: 101#0@(90,50,z0)]\n"
    )
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [SUCCESS]\n"
        f"[10:00:05] E1 T1 P1 CHARGE_IMPACT : Unit 1(50,50) IMPACTED [CHARGE IMPACT]"
        f" Unit 101(90,50) - Hit:{threshold}+:5(HIT) Wound:AUTO Save:NONE[MW] Dmg:{damage}HP"
        " [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(body, units=units, objectives=OBJECTIVES, rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)")
    return _parse(log_text, tmp_path)


def test_verrou_charge_impact_correct_compte_exercice(tmp_path):
    """VERROU : une ligne IMPACTED correcte (seuil=4, dégâts=1) incrémente le compteur d'exercice."""
    stats = _charge_impact_log(4, 1, tmp_path)
    assert _usage(stats, "PROJ.1.3.charge_impact") == 1, "exercice non compté"
    assert stats["charge_impact_wrong_threshold"][1] == 0
    assert stats["charge_impact_wrong_damage"][1] == 0


def test_verrou_charge_impact_mauvais_seuil_detecte(tmp_path):
    """VERROU : seuil != 4 génère charge_impact_wrong_threshold."""
    stats = _charge_impact_log(3, 1, tmp_path)
    assert _usage(stats, "PROJ.1.3.charge_impact") == 1
    assert stats["charge_impact_wrong_threshold"][1] == 1
    assert stats["charge_impact_wrong_damage"][1] == 0


def test_verrou_charge_impact_mauvais_degat_detecte(tmp_path):
    """VERROU : dégâts != 1 génère charge_impact_wrong_damage."""
    stats = _charge_impact_log(4, 2, tmp_path)
    assert _usage(stats, "PROJ.1.3.charge_impact") == 1
    assert stats["charge_impact_wrong_threshold"][1] == 0
    assert stats["charge_impact_wrong_damage"][1] == 1


# ─── 2. REROLL 1 SAVE FIGHT ──────────────────────────────────────────────────


def test_verrou_reroll_save_fight_compte_exercice(tmp_path):
    """VERROU : Save+[REROLLED:] dans un FOUGHT ciblant un TyranidWarriorMelee compte l'exercice."""
    units = (
        "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (50,50), HP_MAX=2"
        " base=round/6 [MODELS: 1#0@(50,50,z0)] [MODEL_TYPES: 1#0=AssaultIntercessor]\n"
        "[10:00:00] Unit 101 (TyranidWarriorMelee) P2: Starting position (50,51), HP_MAX=3"
        " base=round/6 [MODELS: 101#0@(50,51,z0)] [MODEL_TYPES: 101#0=TyranidWarriorMelee]\n"
    )
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(50,51) DEPLOYED from (-1,-1) to (50,51) [R:+0.0] [SUCCESS]\n"
        # Ligne FOUGHT avec Save+[REROLLED:] côté cible (TyranidWarriorMelee = reroll_1_save_fight)
        "[10:00:06] E1 T1 P1 FIGHT : Unit 1(50,50) FOUGHT Unit 101(50,51) with [Close Combat Weapon]"
        " - Hit 4(3+) - Wound 5(4+) - Save 3(3+ AP0 → 3+) [REROLLED:2]"
        " - Dmg:0HP [MODELS: 1#0@(50,50,z0)] [TARGET_MODELS: 101#0@(50,51,z0)]"
        " [SHOOTER_MODELS: 1#0] [TARGET_DECL:1] [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(body, units=units, objectives=OBJECTIVES, rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)")
    stats = _parse(log_text, tmp_path)
    assert _usage(stats, "PROJ.1.4.reroll_save_fight") == 1, "exercice reroll_1_save_fight non compté"


# ─── 3. OATH TARGET MISMATCH ─────────────────────────────────────────────────


def test_verrou_oath_target_match_pas_erreur(tmp_path):
    """VERROU : cible blessée == unité jurée → exercice compté, 0 erreur."""
    # AssaultIntercessor porte oath_of_moment (faction ADEPTUS ASTARTES)
    units = (
        "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (50,50), HP_MAX=2"
        " base=round/6 [MODELS: 1#0@(50,50,z0)] [MODEL_TYPES: 1#0=AssaultIntercessor]\n"
        "[10:00:00] Unit 101 (Boyz) P2: Starting position (90,50), HP_MAX=1"
        " base=round/6 [MODELS: 101#0@(90,50,z0)]\n"
    )
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [SUCCESS]\n"
        # EFFECTS avec oath_target=101 pour P1
        "[10:00:02] T1 EFFECTS: P1 oath_target=101 oath_wound=+1 | P2 none\n"
        # SHOT avec [OATH OF MOMENT] dans segment Wound, cible = 101 (correspond à oath_target)
        "[10:00:03] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(90,50) with [Bolt Pistol]"
        " - Hit 5(3+) - Wound 5(4+) [OATH OF MOMENT] - Save 2(3+) - Dmg:0HP"
        " [MODELS: 1#0@(50,50,z0)] [TARGET_MODELS: 101#0@(90,50,z0)]"
        " [SHOOTER_MODELS: 1#0] [TARGET_DECL:1] [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(body, units=units, objectives=OBJECTIVES, rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)")
    stats = _parse(log_text, tmp_path)
    assert _usage(stats, "PROJ.1.2.oath_target") == 1, "exercice oath_target non compté"
    assert stats["oath_target_mismatch"][1] == 0


def test_verrou_oath_target_mismatch_detecte(tmp_path):
    """VERROU : cible blessée != unité jurée → oath_target_mismatch incrémenté."""
    # AssaultIntercessor porte oath_of_moment ; oath_target=101 mais tir vers 102
    units = (
        "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (50,50), HP_MAX=2"
        " base=round/6 [MODELS: 1#0@(50,50,z0)] [MODEL_TYPES: 1#0=AssaultIntercessor]\n"
        "[10:00:00] Unit 101 (Boyz) P2: Starting position (90,50), HP_MAX=1"
        " base=round/6 [MODELS: 101#0@(90,50,z0)]\n"
        "[10:00:00] Unit 102 (Boyz) P2: Starting position (92,50), HP_MAX=1"
        " base=round/6 [MODELS: 102#0@(92,50,z0)]\n"
    )
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(92,50) DEPLOYED from (-1,-1) to (92,50) [R:+0.0] [SUCCESS]\n"
        # EFFECTS avec oath_target=101 mais on tire sur 102
        "[10:00:02] T1 EFFECTS: P1 oath_target=101 oath_wound=+1 | P2 none\n"
        "[10:00:03] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 102(92,50) with [Bolt Pistol]"
        " - Hit 5(3+) - Wound 5(4+) [OATH OF MOMENT] - Save 2(3+) - Dmg:0HP"
        " [MODELS: 1#0@(50,50,z0)] [TARGET_MODELS: 102#0@(92,50,z0)]"
        " [SHOOTER_MODELS: 1#0] [TARGET_DECL:1] [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(body, units=units, objectives=OBJECTIVES, rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)")
    stats = _parse(log_text, tmp_path)
    assert _usage(stats, "PROJ.1.2.oath_target") == 1, "exercice non compté"
    assert stats["oath_target_mismatch"][1] == 1, "mismatch non détecté"


# ─── 4. CLOSEST TARGET PENETRATION ───────────────────────────────────────────


def test_verrou_ctp_detecte_quand_eff_meilleure_que_ap(tmp_path):
    """VERROU : eff < base - ap_val → CTP exercée (AggressorBoltStorm, obs_id=3)."""
    units = (
        "[10:00:00] Unit 1 (AggressorBoltStorm) P1: Starting position (50,50), HP_MAX=2"
        " base=round/6 [MODELS: 1#0@(50,50,z0)] [MODEL_TYPES: 1#0=AggressorBoltStorm]\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (60,50), HP_MAX=2"
        " base=round/6 [MODELS: 101#0@(60,50,z0)]\n"
    )
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(60,50) DEPLOYED from (-1,-1) to (60,50) [R:+0.0] [SUCCESS]\n"
        # Save format : base=3, AP=-1, eff=3 → eff(3) < base-ap_val(3-(-1)=4) → CTP appliqué
        "[10:00:03] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(60,50) with [Boltstorm Gauntlet]"
        " - Hit 5(3+) - Wound 5(4+) - Save 3(3+ AP-1 → 3+) - Dmg:0HP"
        " [MODELS: 1#0@(50,50,z0)] [TARGET_MODELS: 101#0@(60,50,z0)]"
        " [SHOOTER_MODELS: 1#0] [TARGET_DECL:1] [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(body, units=units, objectives=OBJECTIVES, rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)")
    stats = _parse(log_text, tmp_path)
    assert _usage(stats, "PROJ.1.2.closest_target_penetration") == 1, "exercice CTP non compté"


def test_verrou_ctp_non_compte_sans_amelioration(tmp_path):
    """CONTRE-ÉPREUVE : eff == base - ap_val (pas de CTP) → exercice = 0."""
    units = (
        "[10:00:00] Unit 1 (AggressorBoltStorm) P1: Starting position (50,50), HP_MAX=2"
        " base=round/6 [MODELS: 1#0@(50,50,z0)] [MODEL_TYPES: 1#0=AggressorBoltStorm]\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (60,50), HP_MAX=2"
        " base=round/6 [MODELS: 101#0@(60,50,z0)]\n"
    )
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(60,50) DEPLOYED from (-1,-1) to (60,50) [R:+0.0] [SUCCESS]\n"
        # base=3, AP=-1, eff=4 → eff(4) == base-ap_val(4) → pas de CTP
        "[10:00:03] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(60,50) with [Boltstorm Gauntlet]"
        " - Hit 5(3+) - Wound 5(4+) - Save 4(3+ AP-1 → 4+) - Dmg:0HP"
        " [MODELS: 1#0@(50,50,z0)] [TARGET_MODELS: 101#0@(60,50,z0)]"
        " [SHOOTER_MODELS: 1#0] [TARGET_DECL:1] [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(body, units=units, objectives=OBJECTIVES, rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)")
    stats = _parse(log_text, tmp_path)
    assert _usage(stats, "PROJ.1.2.closest_target_penetration") == 0


# ─── 5. LEADER / SUPPORT ─────────────────────────────────────────────────────


def test_verrou_leader_support_comptes_depuis_attached(tmp_path):
    """VERROU : lignes Attached: dans l'entête → exercices leader et support comptés.

    CaptainPowerWeaponBolter (leader), Ancient (support) — paire réelle du roster SM.
    """
    units = (
        # leader
        "[10:00:00] Unit 1 (CaptainPowerWeaponBolter) P1: Starting position (50,50), HP_MAX=5"
        " base=round/6 [MODELS: 1#0@(50,50,z0)] [MODEL_TYPES: 1#0=CaptainPowerWeaponBolter]\n"
        # bodyguard
        "[10:00:00] Unit 2 (Ancient) P1: Starting position (51,50), HP_MAX=4"
        " base=round/6 [MODELS: 2#0@(51,50,z0)] [MODEL_TYPES: 2#0=Ancient]\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (90,50), HP_MAX=2"
        " base=round/6 [MODELS: 101#0@(90,50,z0)]\n"
    )
    # Attached: avant les lignes Starting position dans le flux réel
    # Dans la fabrique, units est inséré après Board:, donc on l'injecte dans le rosters
    # Pour ce test : injecter Attached: comme ligne séparée dans units (avant Starting pos)
    units_with_attached = (
        "[10:00:00] Attached: 1→2\n"
        + units
    )
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2(51,50) DEPLOYED from (-1,-1) to (51,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(body, units=units_with_attached, objectives=OBJECTIVES, rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)")
    stats = _parse(log_text, tmp_path)
    assert _usage(stats, "PROJ.1.9.leader") == 1, "exercice leader non compté"
    assert _usage(stats, "PROJ.1.9.support") == 1, "exercice support non compté"
