"""24.08 Deadly Demise : l'unité qui détruit le porteur et meurt de l'explosion n'est pas un
cadavre qui attaque.

Faits mesurés le 2026-09-13 (step.log de l'éval holdout, E10 T5 P2 FIGHT, lignes 100881-100887) :
`Unit 105 DEAD model=105#0 reason=hazard` puis 5 lignes `Unit 105(17,36) FOUGHT Unit 4(18,36)`.
L'unité 4 (WeirdBoy, Deadly Demise D3) venait d'être tuée par ces attaques ; l'explosion a tué le
WarTrakk 105. Ordre MOTEUR : tous les jets sont faits avant la moindre allocation
(`_build_manual_allocation`), `destroy_model` écrit les DEAD pendant l'allocation et déclenche la
Deadly Demise, `_finalize_manual_allocation` n'émet les FOUGHT qu'à la fin. Le journal inverse
donc l'ordre du jeu, et l'analyzer comptait « Dead unit fighting » : 5, toutes fausses.

Ce qui manquait pour trancher SANS heuristique : la ligne `DEADLY DEMISE` n'atteignait jamais
step.log (type absent de `_STEP_LOG_TYPE_MAP`). Elle y est désormais, écrite AVANT les DEAD qu'elle
cause, et c'est elle qui nomme la cause de la mort (`deadly_demise_deaths`). La garde
`died_in_own_activation` exige cette cause ET l'absence de ligne d'attaque d'une autre unité entre
le DEAD et la ligne lue.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

_UNITS = (
    "[10:00:00] Unit 4 (SternguardVeteranBoltRifle) P1: Starting position (50,50), HP_MAX=1 base=round/6 [MODELS: 4#0@(50,50,z0)]\n"
    "[10:00:00] Unit 5 (SternguardVeteranBoltRifle) P1: Starting position (53,50), HP_MAX=1 base=round/6 [MODELS: 5#0@(53,50,z0)]\n"
    "[10:00:00] Unit 105 (AssaultIntercessor) P2: Starting position (51,50), HP_MAX=2 base=round/6 [MODELS: 105#0@(51,50,z0)]\n"
    "[10:00:00] Unit 106 (AssaultIntercessor) P2: Starting position (52,50), HP_MAX=2 base=round/6 [MODELS: 106#0@(52,50,z0)]\n"
)
_DEPLOIEMENTS = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 4(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [MODELS: 4#0@(50,50,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 5(53,50) DEPLOYED from (-1,-1) to (53,50) [R:+0.0] [MODELS: 5#0@(53,50,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 105(51,50) DEPLOYED from (-1,-1) to (51,50) [R:+0.0] [MODELS: 105#0@(51,50,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 106(52,50) DEPLOYED from (-1,-1) to (52,50) [R:+0.0] [MODELS: 106#0@(52,50,z0)] [SUCCESS]\n"
)

# Bloc DEAD/DEADLY DEMISE tel que le moteur l'écrit : mort du porteur, ligne d'explosion, mort de
# la victime — puis les lignes d'attaque de l'activation.
_DEAD_4 = "[10:00:02] E1 T1 P1 FIGHT : Unit 4 DEAD model=4#0 reason=combat [SUCCESS]\n"
_DD_4_TUE_105 = "[10:00:02] E1 T1 P1 FIGHT : Unit 4 DEADLY DEMISE Roll:6 → Unit 105(51,50) SUFFERS 2 MW [DEADLY DEMISE] [SUCCESS]\n"
_DEAD_105_HAZARD = "[10:00:02] E1 T1 P2 FIGHT : Unit 105 DEAD model=105#0 reason=hazard [SUCCESS]\n"


def _fought(attaquant: str, pos: str, cible: str, pos_cible: str, ts: str, *, dmg: bool) -> str:
    fin = (
        f" - Wound 6(5+) - → {cible}#0 - Save 1(6+) - Dmg:1HP [R:+0.0] [FIGHT_SUBPHASE:fight] "
        f"[SHOOTER_MODELS: {attaquant}#0] [ALLOC_MODEL: {cible}#0] [SUCCESS]\n"
        if dmg else
        f" [R:+0.0] [FIGHT_SUBPHASE:fight] [SHOOTER_MODELS: {attaquant}#0] [SUCCESS]\n"
    )
    return (
        f"[{ts}] E1 T1 P{1 if int(attaquant) < 100 else 2} FIGHT : Unit {attaquant}{pos} FOUGHT "
        f"Unit {cible}{pos_cible} with [Choppa] - Hit {'3' if dmg else '2'}(3+)" + fin
    )


_FOUGHT_105_x2 = (
    _fought("105", "(51,50)", "4", "(50,50)", "10:00:03", dmg=True)
    + _fought("105", "(51,50)", "4", "(50,50)", "10:00:04", dmg=False)
)

# 1. LE cas de production : 105 tue 4, l'explosion tue 105, les FOUGHT de 105 suivent.
DD_TUE_L_ATTAQUANT_LOG = entete_step_log(
    _DEPLOIEMENTS + _DEAD_4 + _DD_4_TUE_105 + _DEAD_105_HAZARD + _FOUGHT_105_x2,
    units=_UNITS, ez_vertical_inches=None,
)

# 2. Même journal SANS la ligne DEADLY DEMISE (journal antérieur à sa journalisation, ou mort par
# [HAZARDOUS] d'une activation précédente) : la cause n'est pas connue, la faute reste comptée.
DEAD_HAZARD_SANS_CAUSE_LOG = entete_step_log(
    _DEPLOIEMENTS + _DEAD_4 + _DEAD_105_HAZARD + _FOUGHT_105_x2,
    units=_UNITS, ez_vertical_inches=None,
)

# 3. Tierce unité : c'est 5 qui tue 4, l'explosion tue 105 pendant l'activation de 5, puis 105
# combat quand même — un vrai cadavre qui attaque, malgré une cause Deadly Demise connue.
DD_PENDANT_ACTIVATION_TIERCE_LOG = entete_step_log(
    _DEPLOIEMENTS + _DEAD_4 + _DD_4_TUE_105 + _DEAD_105_HAZARD
    + _fought("5", "(53,50)", "4", "(50,50)", "10:00:03", dmg=True)
    + _fought("105", "(51,50)", "106", "(52,50)", "10:00:05", dmg=False),
    units=_UNITS, ez_vertical_inches=None,
)

# 4. Mort dans une phase précédente (même bloc DEAD/DEADLY DEMISE, en SHOOT), attaque en FIGHT.
DD_PHASE_PRECEDENTE_LOG = entete_step_log(
    _DEPLOIEMENTS
    + "[10:00:02] E1 T1 P1 SHOOT : Unit 4 DEAD model=4#0 reason=combat [SUCCESS]\n"
    + "[10:00:02] E1 T1 P1 SHOOT : Unit 4 DEADLY DEMISE Roll:6 → Unit 105(51,50) SUFFERS 2 MW [DEADLY DEMISE] [SUCCESS]\n"
    + "[10:00:02] E1 T1 P2 SHOOT : Unit 105 DEAD model=105#0 reason=hazard [SUCCESS]\n"
    + "[10:00:03] E1 T1 P2 SHOOT : Unit 105(51,50) SHOT Unit 4(50,50) with [Slugga] - Hit 4(3+) - Wound 5(4+) - → 4#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [SHOOTER_MODELS: 105#0] [ALLOC_MODEL: 4#0] [SUCCESS]\n"
    + _fought("105", "(51,50)", "106", "(52,50)", "10:00:05", dmg=False),
    units=_UNITS, ez_vertical_inches=None,
)

# 5. Jumeau TIR : le tireur détruit un porteur à ≤ 6" et meurt de l'explosion ; ses SHOT suivent.
DD_TUE_LE_TIREUR_LOG = entete_step_log(
    _DEPLOIEMENTS
    + "[10:00:02] E1 T1 P1 SHOOT : Unit 4 DEAD model=4#0 reason=combat [SUCCESS]\n"
    + "[10:00:02] E1 T1 P1 SHOOT : Unit 4 DEADLY DEMISE Roll:6 → Unit 105(51,50) SUFFERS 2 MW [DEADLY DEMISE] [SUCCESS]\n"
    + "[10:00:02] E1 T1 P2 SHOOT : Unit 105 DEAD model=105#0 reason=hazard [SUCCESS]\n"
    + "[10:00:03] E1 T1 P2 SHOOT : Unit 105(51,50) SHOT Unit 4(50,50) with [Slugga] - Hit 4(3+) - Wound 5(4+) - → 4#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [SHOOTER_MODELS: 105#0] [ALLOC_MODEL: 4#0] [SUCCESS]\n"
    + "[10:00:04] E1 T1 P2 SHOOT : Unit 105(51,50) SHOT Unit 4(50,50) with [Slugga] - Hit 2(3+) [R:+0.0] [SHOOTER_MODELS: 105#0] [SUCCESS]\n",
    units=_UNITS, ez_vertical_inches=None,
)

# 6. Cadavre ATTAQUÉ : 105 tue 4, l'explosion tue 105, les FOUGHT de 105 suivent (ils revendiquent
# la mort de 4) — puis 5 frappe 105, mort depuis le début de la phase. Vraie faute de P1.
# Le contexte de mort de 105 doit nommer 4 (source de la Deadly Demise) et non rester
# « à revendiquer » : sinon le premier FOUGHT tiers de la phase sur ce cadavre passe
# `claim_kill_context` et la faute est masquée.
DD_PUIS_ATTAQUE_SUR_LE_CADAVRE_LOG = entete_step_log(
    _DEPLOIEMENTS + _DEAD_4 + _DD_4_TUE_105 + _DEAD_105_HAZARD + _FOUGHT_105_x2
    + _fought("5", "(53,50)", "105", "(51,50)", "10:00:05", dmg=False),
    units=_UNITS, ez_vertical_inches=None,
)

# 7. Jumeau TIR du cas 6 : le SHOT de 5 sur le cadavre 105 doit être compté.
DD_PUIS_TIR_SUR_LE_CADAVRE_LOG = entete_step_log(
    _DEPLOIEMENTS
    + "[10:00:02] E1 T1 P1 SHOOT : Unit 4 DEAD model=4#0 reason=combat [SUCCESS]\n"
    + "[10:00:02] E1 T1 P1 SHOOT : Unit 4 DEADLY DEMISE Roll:6 → Unit 105(51,50) SUFFERS 2 MW [DEADLY DEMISE] [SUCCESS]\n"
    + "[10:00:02] E1 T1 P2 SHOOT : Unit 105 DEAD model=105#0 reason=hazard [SUCCESS]\n"
    + "[10:00:03] E1 T1 P2 SHOOT : Unit 105(51,50) SHOT Unit 4(50,50) with [Slugga] - Hit 4(3+) - Wound 5(4+) - → 4#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [SHOOTER_MODELS: 105#0] [ALLOC_MODEL: 4#0] [SUCCESS]\n"
    + "[10:00:05] E1 T1 P1 SHOOT : Unit 5(53,50) SHOT Unit 105(51,50) with [Sternguard Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - → 105#0 - Save 2(3+) - Dmg:1HP [R:+0.0] [SHOOTER_MODELS: 5#0] [ALLOC_MODEL: 105#0] [SUCCESS]\n",
    units=_UNITS, ez_vertical_inches=None,
)


def _parse(tmp_path, contenu: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(contenu)
    return an.parse_step_log(str(log))


def test_l_attaquant_tue_par_la_deadly_demise_de_sa_cible_n_est_pas_compte(tmp_path):
    """Le cas de production : 0, et non 2 (une par ligne FOUGHT).

    Mutation : retirer `died_in_own_activation` de fight_handler → 2 fautes P2."""
    stats = _parse(tmp_path, DD_TUE_L_ATTAQUANT_LOG)
    assert stats["fight_dead_unit_attacker"] == {1: 0, 2: 0}, stats["first_error_lines"]["fight_dead_unit_attacker"]
    assert stats["parse_errors"] == [], stats["parse_errors"]


def test_la_ligne_deadly_demise_est_comptee_et_ne_casse_pas_la_sequence_de_phases(tmp_path):
    """La ligne porte le player de la SOURCE dans la phase de l'adversaire : même régime que DEAD."""
    stats = _parse(tmp_path, DD_TUE_L_ATTAQUANT_LOG)
    assert stats["deadly_demise_triggers"][1] == 1
    assert stats["phase_order_violations"] == 0


def test_sans_ligne_deadly_demise_la_faute_reste_comptee(tmp_path):
    """Journal sans cause : `reason=hazard` seul ne suffit pas (jet [HAZARDOUS] d'une activation
    antérieure, ou journal antérieur à la ligne). On ne devine pas, on compte."""
    stats = _parse(tmp_path, DEAD_HAZARD_SANS_CAUSE_LOG)
    assert stats["fight_dead_unit_attacker"][2] == 2


def test_l_explosion_pendant_l_activation_d_une_tierce_unite_reste_une_faute(tmp_path):
    """La cause est connue (Deadly Demise, même phase), mais une ligne d'attaque de l'unité 5
    sépare le DEAD de 105 de son FOUGHT : 105 est mort pendant l'activation de 5."""
    stats = _parse(tmp_path, DD_PENDANT_ACTIVATION_TIERCE_LOG)
    assert stats["fight_dead_unit_attacker"][2] == 1


def test_la_mort_dans_une_phase_precedente_reste_une_faute(tmp_path):
    stats = _parse(tmp_path, DD_PHASE_PRECEDENTE_LOG)
    assert stats["shoot_dead_unit"][2] == 0, "le SHOT de la même activation n'est pas une faute"
    assert stats["fight_dead_unit_attacker"][2] == 1, "le FOUGHT de la phase suivante l'est"


def test_jumeau_tir_le_tireur_tue_par_la_deadly_demise_n_est_pas_compte(tmp_path):
    """Mutation : retirer `died_in_own_activation` de shoot_handler → 2 fautes P2."""
    stats = _parse(tmp_path, DD_TUE_LE_TIREUR_LOG)
    assert stats["shoot_dead_unit"] == {1: 0, 2: 0}, stats["first_error_lines"]["shoot_dead_unit"]
    assert stats["parse_errors"] == [], stats["parse_errors"]


def test_une_attaque_tierce_sur_la_victime_de_la_deadly_demise_reste_une_faute(tmp_path):
    """Mutation : écrire `(None, turn, phase)` dans unit_kill_context pour la victime DD malgré
    une source connue → 0 (le FOUGHT de 5 revendique la mort de 105 et est excusé)."""
    stats = _parse(tmp_path, DD_PUIS_ATTAQUE_SUR_LE_CADAVRE_LOG)
    assert stats["fight_dead_unit_attacker"] == {1: 0, 2: 0}, stats["first_error_lines"]["fight_dead_unit_attacker"]
    assert stats["fight_dead_unit_target"] == {1: 1, 2: 0}, stats["first_error_lines"]["fight_dead_unit_target"]
    assert stats["parse_errors"] == [], stats["parse_errors"]


def test_jumeau_tir_un_tir_tiers_sur_la_victime_de_la_deadly_demise_reste_une_faute(tmp_path):
    stats = _parse(tmp_path, DD_PUIS_TIR_SUR_LE_CADAVRE_LOG)
    assert stats["shoot_dead_unit"] == {1: 0, 2: 0}, stats["first_error_lines"]["shoot_dead_unit"]
    assert stats["shoot_at_dead_unit"] == {1: 1, 2: 0}, stats["first_error_lines"]["shoot_at_dead_unit"]
    assert stats["parse_errors"] == [], stats["parse_errors"]
