"""05 Attack sequence — attaque non allouée : ce qui est légitime, et ce qui ne l'est pas.

`Save [NOT ALLOCATED]` dit qu'aucune allocation n'a eu lieu pour cette attaque (le seuil de
sauvegarde n'est écrit qu'à l'allocation). Deux lectures, une seule est une faute :

  - cible DÉTRUITE avant la fin du pool → « excess attacks lost », la règle elle-même ;
  - cible ENCORE VIVANTE → des attaques dont la blessure a réussi sont perdues sans raison.

⚠️ Ce fichier existe parce qu'un contrôle qui ne regarde rien affiche « tout va bien ». Le
premier test construit la faute et exige qu'elle soit VUE ; le second construit le cas
légitime et exige le silence. Sans les deux, un compteur à zéro ne prouve rien.
"""
from __future__ import annotations

SHOOTER = (50, 50)
TARGET = (50, 80)
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))


def _log(*, kill_target: bool, kill_after: bool = False) -> str:
    s, t = f"({SHOOTER[0]},{SHOOTER[1]})", f"({TARGET[0]},{TARGET[1]})"
    # La cible a UNE figurine à 2 PV. `kill_target` la tue d'abord (4 PV), ce qui rend
    # légitime la non-allocation de l'attaque suivante ; sinon elle encaisse 0 et reste vive.
    killing_shot = (
        f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{s} SHOT Unit 101{t} with [Bolt Rifle] "
        f"- Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:4HP "
        f"[MODELS: 1#0@{SHOOTER[0]},{SHOOTER[1]}] [SUCCESS]\n"
    ).replace(f"[MODELS: 1#0@{SHOOTER[0]},{SHOOTER[1]}]",
              f"[MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)]") if kill_target else ""
    # Ligne SANS degat intercalee avant le coup fatal : sans elle, le verdict immediat et le
    # verdict differe tombent au meme endroit (les degats de la ligne suivante sont deja
    # appliques quand le handler la voit) et le test ne distingue plus les deux — vert vacant.
    filler_shot = (
        f"[10:00:04] E1 T1 P1 SHOOT : Unit 1{s} SHOT Unit 101{t} with [Bolt Rifle] "
        f"- Hit 2(3+) [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]\n"
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
[10:00:00] Unit 1 (Intercessor) P1: Starting position {s}, HP_MAX=2 base=round/6 [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)]
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {t}, HP_MAX=2 base=round/6 [MODELS: 101#0@({TARGET[0]},{TARGET[1]},z0)]
[10:00:00] === ACTIONS START ===
{'' if kill_after else killing_shot}[10:00:03] E1 T1 P1 SHOOT : Unit 1{s} SHOT Unit 101{t} with [Bolt Rifle] - Hit 4(3+) - Wound 5(4+) - Save [NOT ALLOCATED] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]
{filler_shot if kill_after else ''}{killing_shot if kill_after else ''}[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none
[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s
"""


def _stats(tmp_path, *, kill_target, kill_after=False):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_log(kill_target=kill_target, kill_after=kill_after))
    return an.parse_step_log(str(log))


def test_cible_vivante_l_attaque_perdue_est_une_faute(tmp_path):
    """LA faute : la blessure a réussi, la cible vit, et rien n'a été alloué."""
    stats = _stats(tmp_path, kill_target=False)

    assert stats["shoot_not_allocated_target_alive"][1] == 1, (
        "l'attaque perdue contre une cible VIVANTE doit être comptée ; 0 signifie que le "
        "contrôle ne regarde rien"
    )


def test_cible_detruite_rien_a_signaler(tmp_path):
    """Le cas légitime — « excess attacks lost » (05). Compter ici noierait la faute sous
    1 429 lignes normales, ce qui revient à ne rien mesurer."""
    stats = _stats(tmp_path, kill_target=True)

    assert stats["shoot_not_allocated_target_alive"][1] == 0, (
        stats["first_error_lines"]["shoot_not_allocated_target_alive"][1]
    )


def test_la_cible_tuee_APRES_la_ligne_perdue_reste_legitime(tmp_path):
    """LE cas qui a produit 334 fausses erreurs le 2026-08-11.

    L'ordre des LIGNES n'est pas l'ordre d'ALLOCATION : le pool d'un lot est trie par jet de
    sauvegarde croissant (05.04) et les lots s'enchainent par profil d'arme (04.03). Une attaque
    loguee AVANT le coup fatal peut donc avoir ete resolue APRES lui — et etre perdue a bon
    droit. Juger la cible au moment de LIRE la ligne la voyait vivante, et criait a tort.

    Le verdict est rendu a la fin de l'activation, quand toute la casse est appliquee.
    """
    stats = _stats(tmp_path, kill_target=True, kill_after=True)

    assert stats["shoot_not_allocated_target_alive"][1] == 0, (
        "l'attaque perdue est legitime : la cible meurt dans la MEME activation, meme si la "
        "ligne qui la tue est journalisee apres. "
        f"{stats['first_error_lines']['shoot_not_allocated_target_alive'][1]}"
    )
