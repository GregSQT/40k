"""Collisions d'ancre inter-escouades : séparation ennemi / allié.

L'analyzer détecte les collisions (2+ unités à la même ancre hex) pour repérer des
erreurs de positionnement. Mais une charge atterrit PAR DÉFINITION dans la zone d'engagement
de la cible, et un move normal peut se retrouver à la même ancre qu'un ennemi déjà engagé.
Dans les deux cas, l'ancre est un centroïde d'escouade — les socles réels (footprints) sont
vérifiés par l'engine via `_charge_model_placement_overlaps`, pas par l'analyzer.

→ Une collision ancre-ancre entre ENNEMIS est un artefact de représentation, pas une faute.
→ Une collision entre ALLIÉS reste une vraie erreur (deux escouades amies au même hex).

Les tests ci-dessous vérifient les deux sens : faux positif supprimé pour les ennemis,
signal conservé pour les alliés.
"""
from __future__ import annotations

import ai.analyzer as an

from tests.unit.ai._fabriques import entete_step_log

OBJECTIVES = ";".join(f"(200,{r})" for r in range(150, 156))

_UNITS = (
    "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 2 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)

# Positions suffisamment éloignées des bords pour ne pas déclencher d'autres erreurs.
P1_START = (50, 50)
P2_START = (50, 70)   # 20 subhex de P1 → hors engagement (EZ=10 à x5)
SHARED = (50, 60)     # destination commune — entre les deux départs
P1_ALLY_START = (80, 50)


def _log(body: str) -> str:
    deploy = (
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({P1_START[0]},{P1_START[1]}) DEPLOYED from (-1,-1) to ({P1_START[0]},{P1_START[1]}) [R:+0.0] [SUCCESS]\n"
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2({P1_ALLY_START[0]},{P1_ALLY_START[1]}) DEPLOYED from (-1,-1) to ({P1_ALLY_START[0]},{P1_ALLY_START[1]}) [R:+0.0] [SUCCESS]\n"
        f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({P2_START[0]},{P2_START[1]}) DEPLOYED from (-1,-1) to ({P2_START[0]},{P2_START[1]}) [R:+0.0] [SUCCESS]\n"
    )
    end = (
        "[10:00:09] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:10] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s\n"
    )
    return entete_step_log(
        deploy + body + end,
        inches_to_subhex=5,
        units=_UNITS,
        objectives=OBJECTIVES,
        ez_vertical_inches=None,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    )


def _move(unit_id: int, frm: tuple, to: tuple, models_tag: str = "", player: int = 1) -> str:
    models = f" [MODELS: {models_tag}]" if models_tag else ""
    return (
        f"[10:00:02] E1 T1 P{player} MOVE : Unit {unit_id}({to[0]},{to[1]}) MOVED from ({frm[0]},{frm[1]}) to ({to[0]},{to[1]})"
        f" [R:+0.0]{models} [SUCCESS]\n"
    )


def _advance(unit_id: int, player: int, frm: tuple, to: tuple) -> str:
    return (
        f"[10:00:02] E1 T1 P{player} SHOOT : Unit {unit_id}({to[0]},{to[1]}) ADVANCED from ({frm[0]},{frm[1]}) to ({to[0]},{to[1]})"
        f" [R:+0.0] [MODELS: {unit_id}#0@({to[0]},{to[1]})] [SUCCESS]\n"
    )


def _charge(unit_id: int, frm: tuple, to: tuple, target_id: int, target_pos: tuple, roll: int = 15) -> str:
    return (
        f"[10:00:03] E1 T1 P1 CHARGE : Unit {unit_id}({frm[0]},{frm[1]}) CHARGED Unit {target_id}({target_pos[0]},{target_pos[1]})"
        f" from ({frm[0]},{frm[1]}) to ({to[0]},{to[1]}) [Roll:{roll}] [R:+0.0]"
        f" [MODELS: {unit_id}#0@({to[0]},{to[1]})] [SUCCESS]\n"
    )


def test_charge_ennemi_au_meme_hex_ne_compte_pas_comme_collision(tmp_path):
    """Une charge qui atterrit à l'ancre de la cible ennemie n'est pas une collision.

    L'engine place le chargeur dans la zone d'engagement de sa cible — le chevauchement d'ancre
    est attendu et validé par footprint. Le décompter comme collision serait un faux positif.
    """
    # P2 (101) bouge à SHARED en T1.
    # P1 (1) charge vers SHARED en T1 — même ancre que 101 après la charge.
    body = (
        _move(101, P2_START, SHARED, player=2, models_tag=f"101#0@({SHARED[0]},{SHARED[1]})")
        + _charge(1, P1_START, SHARED, 101, SHARED)
    )
    log = tmp_path / "charge_enemy.log"
    log.write_text(_log(body))
    stats = an.parse_step_log(str(log))
    assert stats["unit_position_collisions"] == [], (
        f"Charge sur ennemi ne doit pas être une collision : {stats['unit_position_collisions']}"
    )


def test_move_ennemi_au_meme_hex_ne_compte_pas_comme_collision(tmp_path):
    """Un move qui finit à l'ancre d'un ennemi engagé n'est pas une collision.

    Deux escouades engagées peuvent partager le même centroïde hex — leurs socles réels sont
    distincts. L'ancre ne suffit pas à prouver un chevauchement physique.
    """
    # P2 (101) bouge à SHARED. P1 (1) bouge aussi à SHARED.
    body = (
        _move(101, P2_START, SHARED, player=2, models_tag=f"101#0@({SHARED[0]},{SHARED[1]})")
        + _move(1, P1_START, SHARED, models_tag=f"1#0@({SHARED[0]},{SHARED[1]})")
    )
    log = tmp_path / "move_enemy.log"
    log.write_text(_log(body))
    stats = an.parse_step_log(str(log))
    assert stats["unit_position_collisions"] == [], (
        f"Move sur ennemi engagé ne doit pas être une collision : {stats['unit_position_collisions']}"
    )


def test_ally_au_meme_hex_est_toujours_une_collision(tmp_path):
    """Deux unités ALLIÉES à la même ancre restent une vraie erreur de positionnement."""
    # P1 (1) bouge à SHARED. P1 (2) charge aussi à SHARED (allié).
    body = (
        _move(1, P1_START, SHARED, models_tag=f"1#0@({SHARED[0]},{SHARED[1]})")
        + (
            f"[10:00:03] E1 T1 P1 CHARGE : Unit 2({P1_ALLY_START[0]},{P1_ALLY_START[1]}) CHARGED Unit 101({P2_START[0]},{P2_START[1]})"
            f" from ({P1_ALLY_START[0]},{P1_ALLY_START[1]}) to ({SHARED[0]},{SHARED[1]}) [Roll:20] [R:+0.0]"
            f" [MODELS: 2#0@({SHARED[0]},{SHARED[1]})] [SUCCESS]\n"
        )
    )
    log = tmp_path / "ally_collision.log"
    log.write_text(_log(body))
    stats = an.parse_step_log(str(log))
    assert len(stats["unit_position_collisions"]) == 1, (
        f"Deux alliés au même hex doivent déclencher une collision : {stats['unit_position_collisions']}"
    )


def test_ally_move_move_au_meme_hex_est_une_collision(tmp_path):
    """Deux unités alliées qui MOVE toutes les deux au même hex = collision réelle."""
    # P1 (1) bouge à SHARED. P1 (2) bouge aussi à SHARED — même ancre, même camp.
    body = (
        _move(1, P1_START, SHARED, models_tag=f"1#0@({SHARED[0]},{SHARED[1]})")
        + _move(2, P1_ALLY_START, SHARED, models_tag=f"2#0@({SHARED[0]},{SHARED[1]})")
    )
    log = tmp_path / "ally_move_move.log"
    log.write_text(_log(body))
    stats = an.parse_step_log(str(log))
    assert len(stats["unit_position_collisions"]) == 1, (
        f"Deux alliés MOVE au même hex doivent déclencher une collision : {stats['unit_position_collisions']}"
    )


def test_advance_ennemi_au_meme_hex_ne_compte_pas_comme_collision(tmp_path):
    """Un ADVANCE qui finit à l'ancre d'un ennemi engagé n'est pas une collision."""
    # P2 (101) bouge à SHARED. P1 (1) advance à SHARED — ennemi engagé, faux positif.
    body = (
        _move(101, P2_START, SHARED, player=2, models_tag=f"101#0@({SHARED[0]},{SHARED[1]})")
        + _advance(1, 1, P1_START, SHARED)
    )
    log = tmp_path / "advance_enemy.log"
    log.write_text(_log(body))
    stats = an.parse_step_log(str(log))
    assert stats["unit_position_collisions"] == [], (
        f"Advance sur ennemi engagé ne doit pas être une collision : {stats['unit_position_collisions']}"
    )


def test_ally_advance_au_meme_hex_est_une_collision(tmp_path):
    """Un ADVANCE vers l'ancre d'un allié déjà present = collision réelle."""
    # P1 (1) bouge à SHARED. P1 (2) advance à SHARED — allié, vraie erreur.
    body = (
        _move(1, P1_START, SHARED, models_tag=f"1#0@({SHARED[0]},{SHARED[1]})")
        + _advance(2, 1, P1_ALLY_START, SHARED)
    )
    log = tmp_path / "ally_advance.log"
    log.write_text(_log(body))
    stats = an.parse_step_log(str(log))
    assert len(stats["unit_position_collisions"]) == 1, (
        f"Advance allié au même hex doit déclencher une collision : {stats['unit_position_collisions']}"
    )
