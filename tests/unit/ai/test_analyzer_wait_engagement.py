"""Le classement d'un WAIT en phase de tir doit mesurer l'ENGAGEMENT, pas une adjacence d'ancre.

10.04 NORMAL SHOOTING : « ELIGIBLE IF: Your unit is **unengaged** and did not make an advance move
this turn. » Une unité engagée ne PEUT pas faire de tir normal : son WAIT n'est pas un choix
délibéré de ne pas tirer, c'est un `skip` imposé par la règle (sauf arme [CLOSE-QUARTERS], 10.06).

L'ancien contrôle décidait avec `calculate_hex_distance(ancre, ancre) == 1`. Faux deux fois : ancre
au lieu du par-figurine, et adjacence au lieu de la zone d'engagement du run (ici 10 subhex = 2").
Une unité ENGAGÉE à 8 subhex d'ancre à ancre voyait donc son WAIT compté comme délibéré, et son
ennemi rester dans `wait_with_targets`.

**Quatrième occurrence de la famille « ancre vs par-figurine »**, après le contrôle LoS
([`test_analyzer_no_anchor_los_false_positive`](test_analyzer_no_anchor_los_false_positive.py)), le
fight non-adjacent et le close-quarters
([`test_analyzer_close_quarters_engagement`](test_analyzer_close_quarters_engagement.py)) — dont ce
fichier reprend le montage. `handle_shoot` avait été corrigé, `handle_wait` était resté derrière.
"""
from __future__ import annotations

# Échelle x5 : la zone d'engagement du run vaut 10 subhex (2"). L'unité qui attend et l'ennemi sont
# à 8 subhex d'ancre à ancre — ENGAGÉS au sens du moteur, et pourtant jamais « adjacents ».
WAITER = (50, 50)
ENGAGING_ENEMY = (50, 58)
# Ennemi lointain : ni engagé, ni à portée d'engagement de qui que ce soit. Il sert à prouver
# qu'un WAIT reste compté comme délibéré quand la règle n'impose rien.
FAR_ENEMY = (50, 200)
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

W = f"({WAITER[0]},{WAITER[1]})"
E = f"({ENGAGING_ENEMY[0]},{ENGAGING_ENEMY[1]})"
F = f"({FAR_ENEMY[0]},{FAR_ENEMY[1]})"


def _header(enemy_pos: str) -> str:
    return f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Run rules: engagement_zone_subhex=10 metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=10 cohesion.global_subhex=45 cohesion.min_neighbors=1
[10:00:00] Unit 1 (Terminator) P1: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{W} DEPLOYED from (-1,-1) to {W} [R:+0.0] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{enemy_pos} DEPLOYED from (-1,-1) to {enemy_pos} [R:+0.0] [SUCCESS]
"""


# Format EXACT des journaux réels : `Unit 1(50,50)`, SANS espace après la virgule — c'est ce
# qu'écrivent les quatre sites `f"{unit_id}({col},{row})"` de `w40k_core.py`. L'ancien regex de la
# branche WAIT exigeait l'espace et ne matchait donc AUCUNE ligne réelle.
_WAIT = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1({WAITER[0]},{WAITER[1]}) WAIT [R:+0.0] [SUCCESS]\n"
)


def _stats(tmp_path, enemy_pos: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_header(enemy_pos) + _WAIT)
    return an.parse_step_log(str(log))


def test_geometry_premise_engaged_but_never_adjacent():
    """Sans cette prémisse le test ne prouve rien : ancre à 8, engagement à 10, adjacence à 1."""
    import ai.analyzer as an

    d = an.calculate_hex_distance(WAITER[0], WAITER[1], ENGAGING_ENEMY[0], ENGAGING_ENEMY[1])
    assert d == 8, d
    assert d != 1, "l'ancien contrôle ne se serait pas déclenché : test inopérant"
    assert d <= 10, "les deux escouades doivent être dans la zone d'engagement du run"

    far = an.calculate_hex_distance(WAITER[0], WAITER[1], FAR_ENEMY[0], FAR_ENEMY[1])
    assert far > 10, "l'ennemi lointain doit être HORS zone d'engagement pour le contrôle positif"


def test_a_wait_while_engaged_is_a_skip_not_a_deliberate_choice(tmp_path):
    """10.04 : engagée, l'unité ne peut pas faire de tir normal — son WAIT est imposé.

    Le `Terminator` est choisi pour une raison vérifiée ci-dessous : aucune de ses armes de tir
    n'est [CLOSE-QUARTERS], donc l'exemption 10.06 ne s'applique pas et le WAIT doit basculer en
    `skip`. Avec une unité porteuse d'un pistolet (Intercessor), le test ne prouverait rien.
    """
    from ai.analyzer_config import load_analyzer_config

    # `_stats` d'abord : c'est l'entête `Board:` du journal qui pose l'échelle du run, sans
    # laquelle le registre d'armes refuse de se charger (et c'est très bien ainsi).
    stats = _stats(tmp_path, E)
    ranged = [w for w in load_analyzer_config().unit_weapons_cache["Terminator"] if w["range"] > 0]
    assert ranged, "prémisse : le Terminator a bien des armes de tir"
    assert not any(w["is_close_quarters"] for w in ranged), \
        "prémisse : aucune arme [CLOSE-QUARTERS], sinon 10.06 exempterait et le skip n'aurait pas lieu"

    assert stats["shoot_vs_wait"]["skip"] == 1, stats["shoot_vs_wait"]
    assert stats["shoot_vs_wait"]["wait"] == 0, stats["shoot_vs_wait"]
    assert stats["shoot_vs_wait_by_player"][1]["skip"] == 1


def test_a_wait_far_from_every_enemy_stays_a_deliberate_wait(tmp_path):
    """Contrôle anti-vert-vacant : sans lui, « tout est skip » passerait pour une correction.

    Hors de toute zone d'engagement, le WAIT reste un choix du joueur — et l'ennemi étant hors
    de portée, il n'entre pas non plus dans les cibles valides.
    """
    stats = _stats(tmp_path, F)
    assert stats["shoot_vs_wait"]["skip"] == 0, stats["shoot_vs_wait"]
    assert stats["shoot_vs_wait"]["wait"] == 1, stats["shoot_vs_wait"]
    assert stats["shoot_vs_wait_by_player"][1]["wait_no_targets"] == 1


def test_the_real_log_format_reaches_the_measurement_at_all(tmp_path):
    """Le défaut le plus grave du lot : le bloc de mesure n'était JAMAIS atteint.

    Les journaux écrivent `Unit 1(50,50)` — les quatre producteurs de `w40k_core.py` formatent
    `f"{unit_id}({col},{row})"`, sans espace. L'ancien regex de la branche WAIT exigeait
    `Unit 1(50, 50)` : mesuré sur un `step.log` réel, **15 151 lignes WAIT en phase de tir,
    0 matchée**. Toutes tombaient dans le `else` et ressortaient `wait_no_targets` — un verdict
    « aucune cible » rendu sans jamais regarder le plateau.

    Ce test lit le format réel et exige que la mesure ait bien eu lieu (classement en `skip`,
    donc bloc traversé) ET qu'aucune erreur de lecture ne soit remontée.
    """
    stats = _stats(tmp_path, E)
    assert stats["shoot_vs_wait"]["skip"] == 1, "la ligne réelle doit atteindre la mesure"
    wait_errors = [e for e in stats["parse_errors"] if "WAIT line without" in e["error"]]
    assert wait_errors == [], wait_errors


def test_a_wait_line_without_position_is_reported_not_counted_as_no_targets(tmp_path):
    """Illisible ⇒ on remonte l'erreur, on ne classe pas. Un compartiment faux ne se voit pas."""
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(
        _header(E) + "[10:00:02] E1 T1 P1 SHOOT : Unit 1 WAIT [R:+0.0] [SUCCESS]\n"
    )
    stats = an.parse_step_log(str(log))

    assert [e["error"] for e in stats["parse_errors"] if "WAIT line without" in e["error"]], \
        "l'illisibilité doit être remontée"
    assert stats["shoot_vs_wait_by_player"][1]["wait_no_targets"] == 0, \
        "sans position, affirmer « aucune cible » est un verdict rendu sans mesure"


def test_an_engaged_vehicle_keeps_its_wait_it_is_allowed_to_shoot(tmp_path):
    """10.06 ELIGIBLE IF : « ... OR is a MONSTER/VEHICLE unit ».

    Le `DreadnoughtRedemptor` n'a aucune arme [CLOSE-QUARTERS] (vérifié ci-dessous) : sans le
    volet M/V, son WAIT au contact était requalifié en `skip`, comme si la règle lui avait
    interdit de tirer. Elle l'autorise — c'était un choix du joueur, effacé.
    """
    from ai.analyzer_config import load_analyzer_config

    log = tmp_path / "step.log"
    log.write_text(
        _header(E).replace("Unit 1 (Terminator) P1:", "Unit 1 (DreadnoughtRedemptor) P1:")
        + _WAIT
    )
    import ai.analyzer as an
    stats = an.parse_step_log(str(log))

    cfg = load_analyzer_config()
    ranged = [w for w in cfg.unit_weapons_cache["DreadnoughtRedemptor"] if w["range"] > 0]
    assert not any(w["is_close_quarters"] for w in ranged), \
        "prémisse : sans arme [CLOSE-QUARTERS], seul le volet M/V peut le sauver du skip"
    assert cfg.unit_is_monster_or_vehicle_by_type["DreadnoughtRedemptor"], \
        "prémisse : l'unité doit bien être un MONSTER/VEHICLE"

    assert stats["shoot_vs_wait"]["skip"] == 0, stats["shoot_vs_wait"]
    assert stats["shoot_vs_wait"]["wait"] == 1, stats["shoot_vs_wait"]
