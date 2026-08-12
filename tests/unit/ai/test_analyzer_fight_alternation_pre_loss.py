"""L'alternance 12.04 se juge AVANT les pertes du coup porté — jumeau mêlée du tir 10.06.

12.04 : tant qu'une unité qui a chargé n'a pas combattu, c'est elle qui doit être activée. Le
contrôle demande donc « existe-t-il une unité ayant chargé, pas encore activée, ENCORE ENGAGÉE ? »

Or `analyzer_core` applique les dégâts d'une ligne avant que le handler ne la voie. Quand l'unité
qui combat hors tour TUE la cible, l'unité chargeuse qu'on venait de sauter n'est plus engagée
avec personne au moment de la mesure : la faute d'alternance devenait invisible — l'exact
symétrique du faux positif de tir mesuré le 2026-08-12 (E422), même cause, même correction
(`AnalyzerState.freeze_select_targets` / `engagement_maps`).
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

# Échelle x5, zone d'engagement du run = 10 subhex. Les deux unités P1 sont engagées avec 101,
# et avec elle SEULEMENT : la tuer les désengage toutes les deux.
TARGET = (100, 100)
CHARGER = (100, 92)
OTHER = (100, 108)

T = f"({TARGET[0]},{TARGET[1]})"
C = f"({CHARGER[0]},{CHARGER[1]})"
OTH = f"({OTHER[0]},{OTHER[1]})"

_SETUP = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{C} DEPLOYED from (-1,-1) to {C} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2{OTH} DEPLOYED from (-1,-1) to {OTH} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P1 CHARGE : Unit 1{C} CHARGED Unit 101{T} from (100,80) to {C} [Roll: 8] [Dist: 2.0\" | Nearest: 2.0\"] [R:+0.0] [SUCCESS]\n"
)
_UNITS = (
    "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 2 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)

# L'unité 2 combat alors que l'unité 1 a chargé et n'a pas encore été activée : faute 12.04.
_FIGHT_NO_KILL = (
    f"[10:00:03] E1 T1 P1 FIGHT : Unit 2{OTH} FOUGHT Unit 101{T} with [Close Combat Weapon]"
    " - Hit 5(3+) - Wound 4(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [FIGHT_SUBPHASE:fight] [SUCCESS]\n"
)
# Le MÊME coup, mortel : la cible disparaît de l'état avant que le contrôle ne mesure.
_FIGHT_KILLS = (
    f"[10:00:03] E1 T1 P1 FIGHT : Unit 2{OTH} FOUGHT Unit 101{T} with [Close Combat Weapon]"
    " - Hit 5(3+) - Wound 4(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [FIGHT_SUBPHASE:fight] [SUCCESS]\n"
)


def _stats(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(_SETUP + body, units=_UNITS, ez_vertical_inches=None))
    return an.parse_step_log(str(log))


def test_alternation_violation_is_detected_when_the_target_survives(tmp_path):
    """Prémisse : sans mort, le contrôle voit la faute. Sinon le test suivant ne prouve rien."""
    stats = _stats(tmp_path, _FIGHT_NO_KILL)
    assert stats["fight_alternation_violations"][1] == 1


def test_alternation_violation_survives_the_kill(tmp_path):
    """Le coup mortel ne doit pas effacer la faute : elle se juge sur l'état d'avant les pertes."""
    stats = _stats(tmp_path, _FIGHT_KILLS)
    assert stats["fight_alternation_violations"][1] == 1
