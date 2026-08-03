"""Les déplacements de CHARGE, de pile-in et de consolidation n'étaient pas contrôlés comme
ceux de move et d'advance — c'est le motif d'échec n°1 de ce dépôt, appliqué au 3ᵉ membre du
miroir move/advance/charge.

- La charge comparait une distance d'ANCRE À ANCRE, en subhex, au jet 2D6 brut en POUCES, sans
  pathfinding. Trois défauts cumulés : à x5 un jet de 7 devenait un plafond de 7 subhex au lieu
  de 35 et TOUTE charge réussie remontait en faute ; l'ancre d'escouade peut bondir plus loin
  qu'aucun socle (reformation) ou moins loin que l'un d'eux ; et une charge traversant un mur
  n'était jamais signalée.
- Pile-in (12.03) et consolidation (12.08) — MAXIMUM DISTANCE 3", « moves as described in
  Moving (03) » — n'étaient contrôlés par RIEN : la branche se contentait de recaler l'ancre.
"""
from __future__ import annotations

import pytest

import ai.analyzer as an

OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))
_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2\n"
)


def _log(body: str, *, scale: int, walls: str = "") -> str:
    return (
        "=== STEP-BY-STEP ACTION LOG ===\n"
        "[10:00:00] === EPISODE 1 START ===\n"
        "[10:00:00] Scenario: scenario_bot-01\n"
        "[10:00:00] Opponent: SelfplayBot\n"
        f"[10:00:00] Walls: {walls}\n"
        f"[10:00:00] Objectives: rect b NW:{OBJECTIVES}\n"
        f"[10:00:00] Board: cols=220 rows=300 inches_to_subhex={scale} hex_radius=2.78 margin=1\n"
        f"{_UNITS}"
        "[10:00:00] === ACTIONS START ===\n"
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [SUCCESS]\n"
        f"{body}"
    )


def _charge_line(dest: str, roll: int, models: str, token: str = "") -> str:
    return (
        f"[10:00:03] E1 T1 P1 CHARGE : Unit 1(50,50) CHARGED{token} Unit 101(90,50) "
        f"from (50,50) to {dest} [Roll:{roll}] [R:+0.0] [MODELS: {models}] [SUCCESS]\n"
    )


def test_le_jet_de_charge_est_converti_a_l_echelle_du_run(tmp_path):
    """Le jet 2D6 est en POUCES, la distance en subhex : à x5 un jet de 7 vaut 35 subhex.
    Sans conversion, ce déplacement de 20 subhex depassait « 7 » et toute charge etait fautive."""
    body = _charge_line("(70,50)", 7, "1#0@(70,50)")
    log = tmp_path / "charge_x5.log"
    log.write_text(_log(body, scale=5))
    stats = an.parse_step_log(str(log))

    assert stats["charge_invalid"][1]["distance_over_roll"] == 0, "jet non converti en subhex"


def test_une_charge_qui_depasse_vraiment_le_jet_reste_signalee(tmp_path):
    """Contre-épreuve : sans elle, la conversion pourrait désarmer le contrôle."""
    body = _charge_line("(130,50)", 7, "1#0@(130,50)")
    log = tmp_path / "charge_over.log"
    log.write_text(_log(body, scale=5))
    stats = an.parse_step_log(str(log))

    assert stats["charge_invalid"][1]["distance_over_roll"] == 1


def test_la_charge_mesure_chaque_figurine_et_non_l_ancre(tmp_path):
    """L'ancre bouge de 2 cases, mais un socle en parcourt 40 : c'est LUI qui viole le jet.
    Le contrôle ancre-à-ancre ne voyait rien."""
    body = (
        "[10:00:02] E1 T1 P1 MOVE : Unit 1(50,50) MOVED from (50,50) to (50,50)"
        "[R:+0.0] [MODELS: 1#0@(50,50) 1#1@(52,50)] [SUCCESS]\n"
        + _charge_line("(52,50)", 2, "1#0@(52,50) 1#1@(92,50)")
    )
    log = tmp_path / "charge_perfig.log"
    log.write_text(_log(body, scale=1))
    stats = an.parse_step_log(str(log))

    # `_bfs_shortest_path_length` élague à `max_steps` : un trajet hors budget revient « sans
    # chemin » plutôt que « trop long ». Les deux comptent comme une charge invalide, et c'est
    # leur somme que le récapitulatif additionne.
    assert (
        stats["charge_invalid"][1]["distance_over_roll"] + stats["charge_path_blocked"][1]
    ) == 1, "socle avancé non mesuré"


def test_une_charge_a_travers_un_mur_est_signalee(tmp_path):
    """11.04 renvoie à Moving (03) : la charge ne traverse ni mur ni ennemi. Le contrôle
    n'avait aucun pathfinding — une charge par-dessus un mur passait inapercue."""
    walls = ";".join(f"(60,{r})" for r in range(0, 300))
    body = (
        "[10:00:02] E1 T1 P1 MOVE : Unit 1(50,50) MOVED from (50,50) to (50,50)"
        "[R:+0.0] [MODELS: 1#0@(50,50)] [SUCCESS]\n"
        + _charge_line("(70,50)", 30, "1#0@(70,50)")
    )
    log = tmp_path / "charge_wall.log"
    log.write_text(_log(body, scale=1, walls=walls))
    stats = an.parse_step_log(str(log))

    assert stats["charge_path_blocked"][1] == 1


def test_le_vol_declare_retranche_deux_pouces_au_budget(tmp_path):
    """21.03 : le moteur retranche 2" au budget de charge quand le vol est déclaré
    (`_charge_budget_subhex`). À x1, un jet de 5 laisse 3 cases, pas 5."""
    body = (
        "[10:00:02] E1 T1 P1 MOVE : Unit 1(50,50) MOVED from (50,50) to (50,50)"
        "[R:+0.0] [MODELS: 1#0@(50,50)] [SUCCESS]\n"
        + _charge_line("(54,50)", 5, "1#0@(54,50)", token=" [FLY]")
    )
    log = tmp_path / "charge_fly.log"
    log.write_text(_log(body, scale=1))
    stats = an.parse_step_log(str(log))

    assert stats["charge_invalid"][1]["distance_over_roll"] == 1, "les 2\" de 21.03 non retranchés"


@pytest.mark.parametrize("verbe", ["PILED IN", "CONSOLIDATED"])
def test_pile_in_et_consolidation_sont_bornes_a_trois_pouces(verbe, tmp_path):
    """12.03 et 12.08 : MAXIMUM DISTANCE 3". Ces deux déplacements n'étaient contrôlés par rien."""
    body = (
        "[10:00:02] E1 T1 P1 MOVE : Unit 1(50,50) MOVED from (50,50) to (50,50)"
        "[R:+0.0] [MODELS: 1#0@(50,50)] [SUCCESS]\n"
        f"[10:00:04] E1 T1 P1 FIGHT : Unit 1(70,50) {verbe} from (50,50) to (70,50)"
        "[R:+0.0] [MODELS: 1#0@(70,50)] [SUCCESS]\n"
    )
    log = tmp_path / f"{verbe.replace(' ', '_')}.log"
    log.write_text(_log(body, scale=1))
    stats = an.parse_step_log(str(log))

    _fm = stats["fight_move_invalid"]
    assert (_fm["over_budget"][1] + _fm["path_blocked"][1]) == 1


@pytest.mark.parametrize("verbe", ["PILED IN", "CONSOLIDATED"])
def test_un_pile_in_dans_les_trois_pouces_ne_remonte_rien(verbe, tmp_path):
    """Contre-épreuve : le contrôle ne doit pas se déclencher sur un déplacement légal."""
    body = (
        "[10:00:02] E1 T1 P1 MOVE : Unit 1(50,50) MOVED from (50,50) to (50,50)"
        "[R:+0.0] [MODELS: 1#0@(50,50)] [SUCCESS]\n"
        f"[10:00:04] E1 T1 P1 FIGHT : Unit 1(52,50) {verbe} from (50,50) to (52,50)"
        "[R:+0.0] [MODELS: 1#0@(52,50)] [SUCCESS]\n"
    )
    log = tmp_path / f"{verbe.replace(' ', '_')}_ok.log"
    log.write_text(_log(body, scale=1))
    stats = an.parse_step_log(str(log))

    assert stats["fight_move_invalid"]["over_budget"][1] == 0
    assert stats["fight_move_invalid"]["path_blocked"][1] == 0
