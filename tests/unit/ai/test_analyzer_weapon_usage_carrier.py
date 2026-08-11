"""L'usage d'une règle d'arme est compté sous la DATASHEET QUI PORTE l'arme (règle 19).

Le profil d'arme d'une ligne était cherché dans le seul équipement du TYPE D'ESCOUADE. Or une
escouade n'est pas homogène : la règle 19 (Attached units) y replie un personnage, et le roster
y met sergents et armes spéciales. L'arme d'un porteur n'étant pas déclarée par l'escouade, elle
ressortait INTROUVABLE — donc sans portée (aucun contrôle de portée possible), et surtout absente
du tableau §1.8, qui annonçait alors « NOT USED » pour une règle réellement exercée.

Mesuré sur le run du 2026-08-11, sur 23 169 tirs :
  - 20 031 lignes où le type d'escouade déclare l'arme  → clé inchangée ;
  - 3 138 lignes (14 %) où seule une figurine la déclare → aujourd'hui comptées, hier perdues.
Dont les 21 blessures dévastatrices d'un `Smite (focused witchfire)` tiré par un Librarian
rattaché à une escouade d'Intercessors : la ligne globale les comptait (336), la ventilation par
arme ne les voyait pas (315).

Même écart, même remède que pour les PLAFONDS d'attaques (`per_model_attack_cap`, 2026-08-09),
qui lisaient déjà `[MODEL_TYPES:]` : c'est le motif d'échec n°1 du dépôt, une correction faite
d'un côté d'un miroir et pas de l'autre.
"""
from __future__ import annotations

SQUAD_TYPE = "Intercessor"          # ne déclare PAS Smite
CARRIER_TYPE = "Librarian"          # le porte, avec DEVASTATING_WOUNDS + PSYCHIC
WEAPON = "Smite (focused witchfire)"

SHOOTER = (50, 50)
TARGET = (50, 80)                   # 30 subhex = 6", dans la portée (24") et hors engagement
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))


def _log(*, with_model_types: bool) -> str:
    s, t = f"({SHOOTER[0]},{SHOOTER[1]})", f"({TARGET[0]},{TARGET[1]})"
    # 1#0 est un Intercessor ordinaire, 1#1 le personnage rattaché qui porte l'arme.
    model_types = (
        f" [MODEL_TYPES: 1#0={SQUAD_TYPE} 1#1={CARRIER_TYPE}]" if with_model_types else ""
    )
    return f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Rosters: scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Run rules: engagement_zone_subhex=10 engagement_zone_vertical_inches=5.0 metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=10 cohesion.global_subhex=45 cohesion.min_neighbors=1
[10:00:00] Unit 1 ({SQUAD_TYPE}) P1: Starting position {s}, HP_MAX=2 base=round/6 [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0) 1#1@({SHOOTER[0]},{SHOOTER[1] + 1},z0)]{model_types}
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {t}, HP_MAX=2 base=round/6 [MODELS: 101#0@({TARGET[0]},{TARGET[1]},z0)]
[10:00:00] === ACTIONS START ===
[10:00:02] E1 T1 P1 SHOOT : Unit 1{s} SHOT Unit 101{t} with [{WEAPON}] - Hit 4(3+) - Wound 6(3+) - Save [DEVASTATING WOUNDS] - Dmg:2HP [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0) 1#1@({SHOOTER[0]},{SHOOTER[1] + 1},z0)] [TARGET_MODELS: 101#0@({TARGET[0]},{TARGET[1]},z0)] [SHOOTER_MODELS: 1#1] [R:+0.0] [SUCCESS]
[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none
[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s
"""


def _stats(tmp_path, *, with_model_types=True):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_log(with_model_types=with_model_types))
    return an.parse_step_log(str(log))


def _dw_usage(stats):
    return {k: sum(v.values()) for k, v in stats["weapon_rule_usage"].items()
            if k[0] == "DEVASTATING_WOUNDS"}


def test_registry_premise_the_squad_type_does_not_carry_the_weapon():
    """Prémisse : sans cet écart le test serait inopérant — l'escouade ne DOIT pas déclarer l'arme."""
    from ai.unit_registry import UnitRegistry

    units = UnitRegistry().units
    squad_weapons = {w["display_name"] for w in units[SQUAD_TYPE]["RNG_WEAPONS"]}
    carrier_weapons = {w["display_name"] for w in units[CARRIER_TYPE]["RNG_WEAPONS"]}
    assert WEAPON not in squad_weapons, "le type d'escouade ne doit pas porter l'arme"
    assert WEAPON in carrier_weapons, "le porteur doit la porter"


def test_usage_is_credited_to_the_carrier_datasheet(tmp_path):
    """Le cœur : la règle est comptée, et sous le PORTEUR — pas sous le type d'escouade."""
    usage = _dw_usage(_stats(tmp_path))

    assert usage == {("DEVASTATING_WOUNDS", f"{WEAPON} ({CARRIER_TYPE})"): 1}, usage


def test_the_per_weapon_split_matches_the_global_line(tmp_path):
    """C'est l'écart 315 / 336 du run : les deux mesures comptent le MÊME fait."""
    stats = _stats(tmp_path)

    assert stats["devastating_wounds_correct"][1] == 1, "prémisse : la règle a bien joué"
    assert sum(_dw_usage(stats).values()) == stats["devastating_wounds_correct"][1]


def test_the_carrier_datasheet_enters_the_expected_pairs(tmp_path):
    """§1.8 n'attend une paire (règle, arme) que pour les types VUS.

    Sans les datasheets des porteurs, la paire du Librarian n'était ni attendue ni comptée :
    invisible des deux côtés à la fois, donc impossible à repérer comme manquante.
    """
    assert CARRIER_TYPE in _stats(tmp_path)["unit_types_seen"]


def test_without_model_types_nothing_is_invented(tmp_path):
    """Anti-devinette : un journal sans `[MODEL_TYPES:]` ne permet pas de nommer le porteur.

    L'analyzer doit alors ne RIEN compter plutôt que créditer le type d'escouade, qui ne porte
    pas cette arme — c'est ce qui produirait une ligne « Smite (Intercessor) » inexistante au
    roster. Un journal antérieur au segment reste analysable, avec la précision qu'il permet.
    """
    assert _dw_usage(_stats(tmp_path, with_model_types=False)) == {}
