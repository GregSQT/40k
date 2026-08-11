"""§1.8 — usage des règles d'armes de MÊLÉE, et la collision de noms qui l'impose.

Le tableau d'usage était bâti sur le seul équipement de TIR : aucune arme de corps à corps n'y
figurait, donc aucune règle propre à la mêlée n'a jamais été comptée. 32 paires (règle, arme)
étaient hors du champ de la mesure, dont les deux armes `[CLEAVE]` dont le moteur écrit
désormais le token. Sur le run du 2026-08-11, le tableau gagne 8 lignes.

⚠️ Ce que ce fichier verrouille avant tout, c'est la CONDITION de justesse du chantier : trois
noms d'affichage désignent DEUX profils selon la phase (`Castellan Axe`, `Guardian Spear`,
`Sentinel Blade`, chez les Custodes). Le `Castellan Axe` de tir déclare `[ASSAULT]`, celui de
mêlée ne déclare rien. Résoudre par le seul nom crédite donc `ASSAULT` à une ligne de COMBAT —
un usage FABRIQUÉ, la faute exactement inverse de celle que ce tableau existe pour corriger.
"""
from __future__ import annotations

import ai.analyzer_config as analyzer_config

# Escouade Boyz avec un Bigboss rattaché (règle 19) : le cas RÉEL du run: l'arme `[CLEAVE]`
# n'est pas déclarée par le type d'escouade, seule la figurine du personnage la porte.
SQUAD_TYPE = "Boyz"
CARRIER_TYPE = "Bigboss"
WEAPON = "Two-Handed Big Choppa"

ATTACKER = (50, 50)
TARGET = (50, 51)
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))


def _log(*, with_cleave_token: bool) -> str:
    a, t = f"({ATTACKER[0]},{ATTACKER[1]})", f"({TARGET[0]},{TARGET[1]})"
    token = " [CLEAVE:1]" if with_cleave_token else ""
    models = (
        f"[MODELS: 1#0@({ATTACKER[0]},{ATTACKER[1]},z0) "
        f"1#1@({ATTACKER[0]},{ATTACKER[1] + 1},z0)]"
    )
    target_models = " ".join(
        f"101#{i}@({TARGET[0]},{TARGET[1] + i},z0)" for i in range(10)
    )
    return f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Rosters: scale=5 AGENT_PLAYER=1 AGENT=ork (ref) OPPONENT=sm (ref)
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Run rules: engagement_zone_subhex=10 engagement_zone_vertical_inches=5.0 metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=10 cohesion.global_subhex=45 cohesion.min_neighbors=1
[10:00:00] Unit 1 ({SQUAD_TYPE}) P1: Starting position {a}, HP_MAX=1 base=round/6 {models} [MODEL_TYPES: 1#0={SQUAD_TYPE} 1#1={CARRIER_TYPE}]
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {t}, HP_MAX=2 base=round/6 [MODELS: {target_models}]
[10:00:00] === ACTIONS START ===
[10:00:02] E1 T1 P1 FIGHT : Unit 1{a} FOUGHT{token} Unit 101{t} with [{WEAPON}] - Hit 4(3+) - Wound 5(3+) - Save 2(3+) - Dmg:2HP [FIGHT_SUBPHASE:fight] {models} [SHOOTER_MODELS: 1#1] [R:+0.0] [SUCCESS]
[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none
[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s
"""


def _stats(tmp_path, *, with_cleave_token=True):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_log(with_cleave_token=with_cleave_token))
    return an.parse_step_log(str(log))


def _cleave_usage(stats):
    return {k: sum(v.values()) for k, v in stats["weapon_rule_usage"].items()
            if k[0] == "CLEAVE"}


# ─────────────────────────────────────────────────────────────────────────────
# Le registre : les armes de mêlée existent enfin pour le rapport
# ─────────────────────────────────────────────────────────────────────────────

def test_les_armes_de_melee_entrent_dans_le_registre(tmp_path):
    """PRÉMISSE du chantier : sans elles, aucune règle de mêlée n'a d'existence mesurable."""
    stats = _stats(tmp_path)

    pairs = stats["weapon_rule_to_weapons"].get("CLEAVE", set())
    assert f"{WEAPON} ({CARRIER_TYPE})" in pairs, (
        "l'arme de mêlée n'est pas dans le registre des paires attendues : le tableau §1.8 "
        f"ne peut donc ni la compter ni la déclarer NOT USED. Paires vues : {sorted(pairs)}"
    )


def test_l_usage_de_cleave_est_credite_a_la_datasheet_porteuse(tmp_path):
    """Le token sur une ligne FOUGHT compte, et sous le nom du PORTEUR (règle 19).

    L'escouade est `Boyz` ; l'arme n'appartient qu'au `Bigboss` rattaché. Créditer l'escouade
    dirait qu'un Boy porte une arme qu'aucun Boy ne déclare.
    """
    usage = _cleave_usage(_stats(tmp_path))

    assert usage == {("CLEAVE", f"{WEAPON} ({CARRIER_TYPE})"): 1}, usage


def test_sans_token_aucun_usage_invente(tmp_path):
    """Contre-épreuve : l'arme DÉCLARE [CLEAVE] mais la règle n'a pas joué (le moteur ne pose
    le token que si elle a ajouté des dés). Le tableau doit dire NOT USED, pas 1."""
    usage = _cleave_usage(_stats(tmp_path, with_cleave_token=False))

    assert sum(usage.values()) == 0, usage


# ─────────────────────────────────────────────────────────────────────────────
# La collision de noms — la raison d'être du drapeau `is_melee`
# ─────────────────────────────────────────────────────────────────────────────

def test_un_nom_porte_par_les_deux_phases_resout_le_bon_profil(tmp_path):
    """`Castellan Axe` : profil de TIR `[ASSAULT]` portée 24", profil de MÊLÉE sans règle.

    Sans le drapeau, la résolution par nom rend le PREMIER trouvé — le profil de tir, puisque
    les armes de tir sont enregistrées en premier. Une ligne de COMBAT créditerait alors
    `ASSAULT` à une arme de mêlée : un usage fabriqué, exactement la faute que ce tableau
    existe pour empêcher. Et le jour où l'ordre d'enregistrement change, c'est le contrôle de
    PORTÉE du tir qui hérite d'une portée nulle.
    """
    from ai.analyzer_perfig import weapon_profile_for_line

    # L'échelle du run conditionne le chargement du registre : la poser explicitement, comme
    # le fait l'entête `Board:` d'un vrai journal.
    analyzer_config.set_run_inches_to_subhex(5)
    cache = analyzer_config.load_analyzer_config().unit_weapons_cache
    unit_type = "CustodianWardenAxe"
    assert unit_type in cache, "prémisse : la datasheet doit être au registre"

    melee, carrier_melee, _ = weapon_profile_for_line(
        (), {}, unit_type, "Castellan Axe", cache, is_melee=True,
    )
    ranged, carrier_ranged, _ = weapon_profile_for_line(
        (), {}, unit_type, "Castellan Axe", cache, is_melee=False,
    )

    assert melee is not None and ranged is not None
    assert carrier_melee == unit_type and carrier_ranged == unit_type
    assert melee["is_melee"] is True and ranged["is_melee"] is False
    assert melee["range"] == 0, f"une arme de mêlée n'a pas de portée : {melee}"
    assert ranged["range"] > 0, f"le profil de tir doit garder sa portée : {ranged}"
    assert "ASSAULT" in ranged["rules"] and "ASSAULT" not in melee["rules"], (
        "les deux profils doivent rester distincts : c'est tout l'objet du drapeau"
    )
