"""Le plafond d'attaques se compte PAR GROUPE DE FIGURINES, au tir comme en mêlée.

Une escouade ne dépense pas son pool d'un bloc : elle répartit ses attaques entre plusieurs
cibles, et chaque ligne du journal nomme les socles qui ont RÉELLEMENT frappé
(`[SHOOTER_MODELS:]`). Le plafond de la ligne est calculé sur CE groupe
(`analyzer_perfig.per_model_attack_cap`) — mais le compteur qu'on lui oppose était accumulé sur
`(épisode, tour, unité, arme)`, sans le groupe. Les attaques du deuxième groupe étaient donc
comparées au plafond du deuxième groupe APRÈS avoir hérité du total du premier.

`fight_handler` avait fermé ce défaut ; `shoot_handler` ne l'avait pas suivi — le motif d'échec
n°1 du dépôt, une correction faite d'un seul côté d'un miroir. Mesuré sur le run du 2026-08-11 :
320 fausses « Shots over RNG_NB » sur 23 169 tirs, dont E55 T3 P1 où les 8 Boyz tirent leurs
24 tirs réglementaires puis 2#7 les 3 siens, comptés 25/26/27 contre un plafond de 3.

Les deux moitiés sont ici : le tir verrouille la correction, la mêlée verrouille son jumeau.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

# Escouade de TIR hétérogène (règle 19) : même arme, deux NB — c'est déjà la prémisse de
# `test_analyzer_shoot_cap_perfig`, réutilisée pour que les deux groupes aient des plafonds
# DIFFÉRENTS. Un groupe restreint dont le plafond vaudrait celui de l'escouade ne prouverait rien.
RNG_SQUAD_TYPE = "CaptainPowerWeaponPlasmaPistol"   # Plasma Pistol (Standard) : NB=1
RNG_SERGEANT_TYPE = "AssaultIntercessorSergeant"    # MÊME arme : NB=D3 → 3
RNG_WEAPON = "Plasma Pistol (Standard)"
RNG_CAP_BOTH = 4    # groupe (1#0, 1#1) : 1 + 3
RNG_CAP_ALONE = 3   # groupe (1#1,) seul : 3

# Escouade de MÊLÉE homogène : le plafond du groupe restreint est la moitié de celui du groupe
# entier, ce qui suffit à séparer les deux comptages.
CC_TYPE = "AssaultIntercessor"
CC_WEAPON = "Astartes Chainsword"
CC_CAP_BOTH = 8     # 2 socles × NB 4
CC_CAP_ALONE = 4    # 1 socle × NB 4

A = (50, 50)     # ancre attaquante
B = (50, 51)     # deuxième socle attaquant
T = (50, 56)     # cible : 6 subhex = 1,2", dans la portée du pistolet comme au contact
OBJECTIVES = ";".join(f"(200,{r})" for r in range(150, 156))


def _header(unit_type: str, second_type: str) -> str:
    return entete_step_log(
        units=(
            f"[10:00:00] Unit 1 ({unit_type}) P1: Starting position ({A[0]},{A[1]}), HP_MAX=5 base=round/6"
            f" [MODELS: 1#0@({A[0]},{A[1]},z0) 1#1@({B[0]},{B[1]},z0)]"
            f" [MODEL_TYPES: 1#0={unit_type} 1#1={second_type}]\n"
            f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position ({T[0]},{T[1]}), HP_MAX=2 base=round/6"
            f" [MODELS: 101#0@({T[0]},{T[1]},z0)]\n"
        ),
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
        objectives=OBJECTIVES,
    )


_END = ("[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n")

_MODELS = f"[MODELS: 1#0@({A[0]},{A[1]},z0) 1#1@({B[0]},{B[1]},z0)]"


def _shot(shooters: str) -> str:
    return (
        f"[10:00:02] E1 T1 P1 SHOOT : Unit 1({A[0]},{A[1]}) SHOT Unit 101({T[0]},{T[1]})"
        f" with [{RNG_WEAPON}] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:0HP"
        f" {_MODELS} [SHOOTER_MODELS: {shooters}] [R:+0.0] [SUCCESS]\n"
    )


def _blow(shooters: str) -> str:
    return (
        f"[10:00:04] E1 T1 P1 FIGHT : Unit 1({A[0]},{A[1]}) FOUGHT Unit 101({T[0]},{T[1]})"
        f" with [{CC_WEAPON}] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:0HP"
        f" [FIGHT_SUBPHASE:fight] {_MODELS} [SHOOTER_MODELS: {shooters}] [TARGET_DECL:1] [R:+0.0] [SUCCESS]\n"
    )


def _parse(tmp_path, header: str, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(header + body + _END)
    return an.parse_step_log(str(log))


def test_registry_premise_the_caps_of_the_two_groups_differ():
    """Sans écart entre plafond du groupe entier et plafond du groupe restreint, rien n'est prouvé."""
    from ai.unit_registry import UnitRegistry
    from ai.analyzer import max_dice_value

    units = UnitRegistry().units

    def _nb(unit_type: str, weapon: str, slot: str) -> int:
        w = next(w for w in units[unit_type][slot] if w["display_name"] == weapon)
        return max_dice_value(w["NB"], f"{unit_type}/{weapon}")

    assert _nb(RNG_SQUAD_TYPE, RNG_WEAPON, "RNG_WEAPONS") == 1
    assert _nb(RNG_SERGEANT_TYPE, RNG_WEAPON, "RNG_WEAPONS") == RNG_CAP_ALONE
    assert RNG_CAP_BOTH == 1 + RNG_CAP_ALONE
    assert _nb(CC_TYPE, CC_WEAPON, "CC_WEAPONS") == CC_CAP_ALONE
    assert CC_CAP_BOTH == 2 * CC_CAP_ALONE
    assert RNG_CAP_ALONE != RNG_CAP_BOTH and CC_CAP_ALONE != CC_CAP_BOTH


def test_shooting_two_groups_of_the_same_squad_are_counted_apart(tmp_path):
    """Le cœur du lot : l'escouade tire son pool entier, puis un seul socle tire le sien.

    Les deux salves sont réglementaires. Sur l'ancien code, les 3 tirs de la seconde étaient
    comptés 5, 6 et 7 contre un plafond de 3 → 3 fausses erreurs.
    """
    body = _shot("1#0 1#1") * RNG_CAP_BOTH + _shot("1#1") * RNG_CAP_ALONE
    stats = _parse(tmp_path, _header(RNG_SQUAD_TYPE, RNG_SERGEANT_TYPE), body)
    assert stats["shoot_over_rng_nb"][1] == 0, stats["first_error_lines"]["shoot_over_rng_nb"][1]


def test_shooting_a_real_overshoot_by_the_second_group_is_still_caught(tmp_path):
    """Anti-vert-vacant : séparer les groupes ne doit pas éteindre le contrôle."""
    body = _shot("1#0 1#1") * RNG_CAP_BOTH + _shot("1#1") * (RNG_CAP_ALONE + 2)
    stats = _parse(tmp_path, _header(RNG_SQUAD_TYPE, RNG_SERGEANT_TYPE), body)
    assert stats["shoot_over_rng_nb"][1] == 2


def test_melee_two_groups_of_the_same_squad_are_counted_apart(tmp_path):
    """JUMEAU : la mêlée porte déjà la correction, ce test la verrouille contre une régression."""
    body = _blow("1#0 1#1") * CC_CAP_BOTH + _blow("1#0") * CC_CAP_ALONE
    stats = _parse(tmp_path, _header(CC_TYPE, CC_TYPE), body)
    assert stats["fight_over_cc_nb"][1] == 0, stats["first_error_lines"]["fight_over_cc_nb"][1]


def test_melee_a_real_overshoot_by_the_second_group_is_still_caught(tmp_path):
    """Anti-vert-vacant, côté mêlée."""
    body = _blow("1#0 1#1") * CC_CAP_BOTH + _blow("1#0") * (CC_CAP_ALONE + 2)
    stats = _parse(tmp_path, _header(CC_TYPE, CC_TYPE), body)
    assert stats["fight_over_cc_nb"][1] == 2
