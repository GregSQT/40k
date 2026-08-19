"""DEAD lines avant fight → effectif cible sous-évalué → [CLEAVE] dés à 0 → faux CC_NB.

Régression verrouillée (2026-08-19). Même artifact d'ordonnancement que §2.8 et §1.2 :
le moteur flush les lignes DEAD AVANT la ligne d'attaque qui les a causées.

Pour [CLEAVE] 24.06, le nombre de dés additionnels = ΣX_porteurs × (effectif_cible_au_ST // 5).
Si les DEAD lines réduisent l'effectif de la cible de 6 à 1 AVANT que le gel du Select
Targets step ne soit construit, `models_alive = 1 < 5` → `cleave_dice = 0`. L'analyzer
plafonne alors à NB=6, alors que le moteur autorisait NB=6+1=7 (6÷5=1 tranche → 1 dé
additionnel). Il compte le 7e jet comme une attaque au-dessus du plafond — fight_over_cc_nb.

AVANT le fix : dead_model_positions_episode absent du gel → models_alive=1 → cleave=0 → ROUGE.
APRÈS le fix : 5 socles réintégrés → models_alive=6 → cleave=1 → cap=7 → VERT.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

OBJECTIVES = ";".join(f"(60,{r})" for r in range(40, 46))
ATTACKER = (10, 10)
TARGET_ANCHOR = (10, 11)

# 6 modèles de la cible, tous à ≤ 2 hex de l'attaquant (EZ=2 à x1).
# Le DEPLOYMENT les liste tous pour que positions_by_model["101"] les connaisse AVANT les DEAD.
_M0 = (10, 11)
_M1 = (10, 12)
_M2 = (11, 11)
_M3 = ( 9, 11)
_M4 = (11, 12)
_M5 = ( 9, 12)
_ALL_101 = (
    f"101#0@({_M0[0]},{_M0[1]},z0) 101#1@({_M1[0]},{_M1[1]},z0) "
    f"101#2@({_M2[0]},{_M2[1]},z0) 101#3@({_M3[0]},{_M3[1]},z0) "
    f"101#4@({_M4[0]},{_M4[1]},z0) 101#5@({_M5[0]},{_M5[1]},z0)"
)

A = f"({ATTACKER[0]},{ATTACKER[1]})"
T = f"({TARGET_ANCHOR[0]},{TARGET_ANCHOR[1]})"

# 5 DEAD lines (reason=combat) précèdent les jets FIGHT.
# Chacune [MODELS:] ne liste que les survivants restants.
_DEAD_LINES = (
    f"[10:00:03] E1 T1 P2 FIGHT : Unit 101{T} DEAD model=101#1 reason=combat "
    f"[MODELS: 101#0@({_M0[0]},{_M0[1]},z0) 101#2@({_M2[0]},{_M2[1]},z0) "
    f"101#3@({_M3[0]},{_M3[1]},z0) 101#4@({_M4[0]},{_M4[1]},z0) "
    f"101#5@({_M5[0]},{_M5[1]},z0)] [SUCCESS]\n"
    f"[10:00:04] E1 T1 P2 FIGHT : Unit 101{T} DEAD model=101#2 reason=combat "
    f"[MODELS: 101#0@({_M0[0]},{_M0[1]},z0) 101#3@({_M3[0]},{_M3[1]},z0) "
    f"101#4@({_M4[0]},{_M4[1]},z0) 101#5@({_M5[0]},{_M5[1]},z0)] [SUCCESS]\n"
    f"[10:00:05] E1 T1 P2 FIGHT : Unit 101{T} DEAD model=101#3 reason=combat "
    f"[MODELS: 101#0@({_M0[0]},{_M0[1]},z0) 101#4@({_M4[0]},{_M4[1]},z0) "
    f"101#5@({_M5[0]},{_M5[1]},z0)] [SUCCESS]\n"
    f"[10:00:06] E1 T1 P2 FIGHT : Unit 101{T} DEAD model=101#4 reason=combat "
    f"[MODELS: 101#0@({_M0[0]},{_M0[1]},z0) 101#5@({_M5[0]},{_M5[1]},z0)] [SUCCESS]\n"
    f"[10:00:07] E1 T1 P2 FIGHT : Unit 101{T} DEAD model=101#5 reason=combat "
    f"[MODELS: 101#0@({_M0[0]},{_M0[1]},z0)] [SUCCESS]\n"
)

# 7 jets de Kustom Choppa (NB=6 + 1 dé CLEAVE pour 6 modèles ÷ 5 = 1 tranche).
# Dmg:0HP → 101#0 ne meurt pas, fights=7 à la fin.
_FIGHT_LINES = "".join(
    f"[10:00:{8 + i:02d}] E1 T1 P1 FIGHT : Unit 1{A} FOUGHT [CLEAVE:1] Unit 101{T} "
    f"with [Kustom Choppa] - Hit 4(2+) - Wound 5(2+) - Save 2(3+) - Dmg:0HP [R:+0.0] "
    f"[FIGHT_SUBPHASE:fight] [MODELS: 1#0@({ATTACKER[0]},{ATTACKER[1]},z0)] "
    f"[SHOOTER_MODELS: 1#0] [ALLOC_MODEL: 101#0] [SUCCESS]\n"
    for i in range(7)
)

STEP_LOG = entete_step_log(
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{A} DEPLOYED from (-1,-1) to {A} [R:+0.0] "
    f"[MODELS: 1#0@({ATTACKER[0]},{ATTACKER[1]},z0)] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] "
    f"[MODELS: {_ALL_101}] [SUCCESS]\n"
    + _DEAD_LINES
    + _FIGHT_LINES,
    inches_to_subhex=1,
    board="cols=44 rows=60",
    hex_radius="13.9",
    margin=5,
    objectives=OBJECTIVES,
    metric_engagement="hex",
    metric_ranged="hex",
    log_grammar=2,
    units=(
        "[10:00:00] Unit 1 (BoyzNobKustomShoota) P1: Starting position (-1,-1), HP_MAX=5 "
        "base=round/1\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=1 "
        "base=round/1\n"
    ),
)


def test_dead_avant_fight_n_est_pas_fight_over_cc_nb(tmp_path):
    """VERROU : DEAD lines (reason=combat) avant fight ne doivent pas causer fight_over_cc_nb.

    Sans dead_model_positions_episode : models_alive gelé = 1 < 5 → cleave_dice = 0 →
    cap = NB=6 → fights=7 > 6 → fight_over_cc_nb=1. Avec le fix : models_alive = 1 + 5 = 6 →
    cleave_dice = 1 × (6//5) = 1 → cap = 7 → 7 ≤ 7 → fight_over_cc_nb=0.

    Verrou prouvé : supprimer dead_model_positions_episode du gel → ROUGE (1 CC_NB).
    """
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG)
    stats = an.parse_step_log(str(log))
    assert stats["fight_over_cc_nb"][1] == 0, (
        "les 5 DEAD lines précèdent le fight (artifact d'ordonnancement) : l'effectif de la "
        "cible au Select Targets step était 6, les 7 jets [CLEAVE:1] sont donc légaux"
    )
