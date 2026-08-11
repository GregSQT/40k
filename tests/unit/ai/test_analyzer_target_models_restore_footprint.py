"""Une unité qui perd une figurine ne doit pas être réduite à son ANCRE pour la géométrie.

`_apply_damage_and_handle_death` purge les socles connus de la cible dès qu'une figurine tombe,
avec une raison valable : le journal ne dit pas LAQUELLE tombe, donc la carte des socles devient
fausse. Mais il existe une donnée qui dit qui RESTE — `[TARGET_MODELS:]`, écrit par le moteur sur
la dernière ligne visant cette cible, donc APRÈS résolution des pertes. Elle n'avait qu'un seul
consommateur (le contrôle de portée du tir, en local) et n'était jamais réinjectée dans l'état.

Conséquence : tout contrôle géométrique portant sur une unité entamée mesurait contre UNE ancre
au lieu de son empreinte réelle. C'est la famille de faux positifs déjà purgée trois fois ici
(LoS, fight non-adjacent, close-quarters), sur un quatrième site.

Mesuré sur le run du 2026-08-11, E123 T4 : l'unité 105 fait un fall-back en partant à 1 hex du
socle survivant `1#5` — zone d'engagement de 2, donc un engagement bien réel — et l'analyzer, qui
ne voyait que l'ancre ennemie à 3 hex, comptait « fall-back sans engagement ». Sur le run entier :
4 verdicts de ce type, tous faux, et deux contrôles voisins qui ne voyaient rien.

GÉOMÉTRIE DU TEST : l'ancre de l'unité 1 est à 20 subhex du fugitif (hors zone d'engagement), son
socle survivant à 1 subhex (dedans). Les deux mesures donnent donc des verdicts OPPOSÉS — sans
quoi le test ne prouverait rien.
"""
from __future__ import annotations

ANCHOR_FAR = (70, 50)      # ancre de l'unité 1 : hors de toute zone d'engagement
SURVIVOR = (51, 50)        # son socle survivant : au contact
FLEEING = (50, 50)         # ancre du fugitif au départ
FLED_TO = (44, 50)         # arrivée : hors de portée d'engagement du survivant
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

STEP_LOG = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Rosters: scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Run rules: engagement_zone_subhex=10 engagement_zone_vertical_inches=5.0 metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=10 cohesion.global_subhex=45 cohesion.min_neighbors=1
[10:00:00] Unit 1 (Intercessor) P1: Starting position ({ANCHOR_FAR[0]},{ANCHOR_FAR[1]}), HP_MAX=2 base=round/6 [MODELS: 1#0@({ANCHOR_FAR[0]},{ANCHOR_FAR[1]},z0) 1#1@({SURVIVOR[0]},{SURVIVOR[1]},z0)] [MODEL_TYPES: 1#0=Intercessor 1#1=Intercessor]
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position ({FLEEING[0]},{FLEEING[1]}), HP_MAX=2 base=round/6 [MODELS: 101#0@({FLEEING[0]},{FLEEING[1]},z0)] [MODEL_TYPES: 101#0=AssaultIntercessor]
[10:00:00] === ACTIONS START ===
[10:00:02] E1 T1 P2 SHOOT : Unit 101({FLEEING[0]},{FLEEING[1]}) SHOT Unit 1({ANCHOR_FAR[0]},{ANCHOR_FAR[1]}) with [Bolt Pistol] - Hit 4(3+) - Wound 5(4+) - Save 1(3+) - Dmg:2HP [MODELS: 101#0@({FLEEING[0]},{FLEEING[1]},z0)] [TARGET_MODELS: 1#1@({SURVIVOR[0]},{SURVIVOR[1]},z0)] [SHOOTER_MODELS: 101#0] [R:+0.0] [SUCCESS]
[10:00:03] E1 T2 P2 MOVE : Unit 101({FLED_TO[0]},{FLED_TO[1]}) FLED from ({FLEEING[0]},{FLEEING[1]}) to ({FLED_TO[0]},{FLED_TO[1]}) [R:+0.0] [MODELS: 101#0@({FLED_TO[0]},{FLED_TO[1]},z0)] [SUCCESS]
[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none
[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s
"""


def _stats(tmp_path):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG)
    return an.parse_step_log(str(log))


def test_geometry_premise_anchor_and_footprint_disagree():
    """Prémisse : les deux mesures DOIVENT diverger, sinon le test est inopérant.

    La zone d'engagement du run vaut 10 subhex : le survivant est à 1 subhex du fugitif (dedans),
    l'ancre de son escouade à 20 (dehors, socles compris).
    """
    assert abs(SURVIVOR[0] - FLEEING[0]) == 1
    assert abs(ANCHOR_FAR[0] - FLEEING[0]) >= 20


def test_the_fall_back_is_no_longer_called_unengaged(tmp_path):
    """Le fall-back part d'un engagement réel : le compter fautif est un faux positif.

    C'est le verdict que le run rendait 4 fois, sur des unités qui venaient de combattre.
    """
    stats = _stats(tmp_path)

    assert stats["flee_from_unengaged"][2] == 0, stats["first_error_lines"]["flee_from_unengaged"][2]


def test_a_real_unengaged_fall_back_is_still_caught(tmp_path):
    """Anti-vert-vacant : rendre l'empreinte ne doit pas éteindre le contrôle.

    Même journal, survivant DÉPLACÉ hors de toute zone d'engagement : plus personne n'engage le
    fugitif, et son fall-back devient la violation de 09.07 que le contrôle doit voir.
    """
    import ai.analyzer as an

    far_survivor = (200, 200)
    log = tmp_path / "step.log"
    log.write_text(STEP_LOG.replace(
        f"[TARGET_MODELS: 1#1@({SURVIVOR[0]},{SURVIVOR[1]},z0)]",
        f"[TARGET_MODELS: 1#1@({far_survivor[0]},{far_survivor[1]},z0)]",
    ))
    stats = an.parse_step_log(str(log))

    assert stats["flee_from_unengaged"][2] == 1, (
        "plus personne n'engage le fugitif : son fall-back viole 09.07 et doit être compté"
    )
