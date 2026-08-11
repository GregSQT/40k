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
        f"[10:00:00] Run rules: engagement_zone_subhex={2 * scale} metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex={2 * scale} cohesion.global_subhex={9 * scale} cohesion.min_neighbors=1\n"
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


def _advance_line(dest: str, models: str) -> str:
    return (
        f"[10:00:02] E1 T1 P1 MOVE : Unit 1({dest[1:-1]}) ADVANCED from (50,50) to {dest} "
        f"[Roll: 3] [R:+0.0] [MODELS: {models}] [SUCCESS]\n"
    )


def test_verrou_le_marqueur_waaagh_ne_rend_pas_la_charge_invisible(tmp_path):
    """VERROU PARSING : `[WAAAGH!]` porte un `!`, que la classe `[A-Za-z0-9_ ]` refusait.

    Une charge sous Waaagh! ne matchait plus AUCUN des deux motifs de charge (branchement dans
    `analyzer_core`, mesures dans `charge_handler`) : elle n'était ni comptée ni contrôlée, et la
    position de l'unité restait figée sur un fantôme pour tout le reste de l'épisode. Le
    symptôme est un SILENCE, donc l'ancre est positive : la charge doit être VUE (`total`).

    Deux marqueurs cumulés, la forme la plus large que le moteur produise.
    """
    body = _charge_line("(70,50)", 7, "1#0@(70,50)", token=" [WAAAGH!] [FLY]")
    log = tmp_path / "charge_waaagh.log"
    log.write_text(_log(body, scale=5))
    stats = an.parse_step_log(str(log))

    assert stats["charge_invalid"][1]["total"] == 1, "charge invisible pour l'analyzer"
    assert stats["charge_invalid"][1]["distance_over_roll"] == 0


def test_verrou_une_charge_apres_advance_sous_waaagh_n_est_pas_une_faute(tmp_path):
    """VERROU RÈGLE : le Waaagh! autorise la charge après Advance (08.04) et ne vit dans AUCUN
    `unit_rules` — c'est une capacité de FACTION. Le seul témoin dans le journal est le marqueur.

    Sans sa lecture, l'Intercessor de la fixture (aucune capacité `charge_after_advance`) fait
    remonter une faute `charge_invalid.advanced` sur un coup parfaitement légal. La
    CONTRE-ÉPREUVE, sans marqueur, doit au contraire compter la faute : sinon ce test passerait
    aussi avec un contrôle désactivé.
    """
    body = _advance_line("(55,50)", "1#0@(55,50)") + _charge_line(
        "(70,50)", 7, "1#0@(70,50)", token=" [WAAAGH!]"
    )
    log = tmp_path / "charge_waaagh_advance.log"
    log.write_text(_log(body, scale=5))
    stats = an.parse_step_log(str(log))

    assert stats["charge_invalid"][1]["total"] == 1, "premisse : la charge doit etre vue"
    assert stats["charge_invalid"][1]["advanced"] == 0, "faute inventee sur une charge legale"
    assert stats["special_rule_usage"][("waaagh", "Intercessor")][1] == 1

    # Contre-épreuve : même charge, marqueur retiré → la faute est bien signalée.
    body_sans = _advance_line("(55,50)", "1#0@(55,50)") + _charge_line(
        "(70,50)", 7, "1#0@(70,50)"
    )
    log_sans = tmp_path / "charge_sans_waaagh.log"
    log_sans.write_text(_log(body_sans, scale=5))
    stats_sans = an.parse_step_log(str(log_sans))

    assert stats_sans["charge_invalid"][1]["advanced"] == 1


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

    # Le socle a un chemin libre, simplement trop long : c'est « distance > roll », PAS un
    # chemin bloqué. Sans marge de recherche le BFS élaguait au budget et les deux causes
    # étaient confondues — « Distance > roll » affichait 0 en permanence.
    assert stats["charge_invalid"][1]["distance_over_roll"] == 1, "socle avancé non mesuré"


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

    assert stats["charge_invalid"][1]["distance_over_roll"] == 1


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

    _kind = "pile_in" if verbe == "PILED IN" else "consolidation"
    assert stats["fight_move_invalid"][_kind][1] == 1
    # Un slot par RÈGLE : l'autre ne doit pas bouger.
    _autre = "consolidation" if _kind == "pile_in" else "pile_in"
    assert stats["fight_move_invalid"][_autre][1] == 0


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

    _fm = stats["fight_move_invalid"]
    assert _fm["pile_in"][1] == 0 and _fm["consolidation"][1] == 0


def test_le_move_reactif_est_journalise_sans_consommer_de_step():
    """Le move réactif est un vrai déplacement, soumis aux mêmes contraintes que les autres —
    il doit donc être journalisé pour être vérifiable. Son formateur existait, seul le mapping
    de `_STEP_LOG_TYPE_MAP` manquait : la ligne n'atteignait jamais step.log et TOUS les
    contrôles réactifs de l'analyzer étaient du code mort.

    Mais il est DÉCLENCHÉ par le déplacement adverse, pas choisi : le compter comme un step
    décalerait `total_actions` et le compte de steps de tous les épisodes.
    """
    import os
    import tempfile

    from engine.w40k_core import W40KEngine
    from ai.step_logger import StepLogger

    assert W40KEngine._STEP_LOG_TYPE_MAP.get("reactive_move") == "reactive_move"
    assert "reactive_move" in W40KEngine._STEP_LOG_NON_INCREMENTING_TYPES

    class _Bridge:
        def _models_segment_for_unit(self, unit_id):
            return ""

    details = W40KEngine._build_step_log_details.__get__(_Bridge())(
        {
            "unitId": "1", "fromCol": 5, "fromRow": 5, "toCol": 7, "toRow": 5, "turn": 1,
            "triggered_by_unit_id": "101", "range_roll": 3,
            "ability_display_name": "Reactive Move", "event_toCol": 9, "event_toRow": 9,
        },
        1,
    )
    out = os.path.join(tempfile.mkdtemp(), "step.log")
    logger = StepLogger(output_file=out, enabled=True, buffer_size=1)
    logger.episode_number = 1
    logger.log_action(
        unit_id="1", action_type="reactive_move", phase="MOVE", player=1, success=True,
        step_increment=False, action_details=details,
    )
    logger._flush_buffer()

    lines = [l for l in open(out, encoding="utf-8").read().splitlines() if "REACTIVE MOVED" in l]
    assert len(lines) == 1, lines
    # Les champs exigés par le formateur (`require_key`) sont bien câblés : sans eux
    # `log_action` avale l'exception et la ligne disparaît en silence.
    assert "[Roll: 3]" in lines[0] and "trigger: Unit 101->(9,9)" in lines[0], lines[0]
    assert logger.step_count == 0, "un move réactif ne consomme pas de step gym"


def test_le_marqueur_fly_de_charge_atteint_bien_step_log():
    """Le formateur du StepLogger RÉÉCRIT intégralement la ligne de charge : le marqueur posé
    sur le `message` de l'action_log moteur ne sert qu'au replay/PvP et n'atteint jamais
    step.log. C'est le champ `is_fly_move` qui doit traverser la chaîne — sans lui, l'analyzer
    jugeait toute charge volante avec un budget faux (2" de 21.03 non retranchés) et un
    pathfinding au sol.

    Verrou de CHAÎNE, pas de site : c'est de ne pas l'avoir posé qu'est venu le défaut.
    """
    import os
    import tempfile

    from engine.w40k_core import W40KEngine
    from ai.step_logger import StepLogger

    class _Bridge:
        def _models_segment_for_unit(self, unit_id):
            return ""

    build = W40KEngine._build_step_log_details.__get__(_Bridge())

    def _line(is_fly: bool) -> str:
        details = build(
            {
                "unitId": "3", "targetId": "101", "fromCol": 5, "fromRow": 5,
                "toCol": 7, "toRow": 5, "targetCol": 7, "targetRow": 6,
                "turn": 1, "charge_roll": 8, "is_fly_move": is_fly,
            },
            1,
        )
        out = os.path.join(tempfile.mkdtemp(), "step.log")
        logger = StepLogger(output_file=out, enabled=True, buffer_size=1)
        logger.episode_number = 1
        logger.log_action(
            unit_id="3", action_type="charge", phase="CHARGE", player=1, success=True,
            step_increment=True, action_details=details,
        )
        logger._flush_buffer()
        lines = [l for l in open(out, encoding="utf-8").read().splitlines() if "CHARGED" in l]
        assert len(lines) == 1, lines
        return lines[0]

    assert "CHARGED [FLY]" in _line(True), _line(True)
    assert "[FLY]" not in _line(False), _line(False)


def test_le_vol_declare_retranche_deux_pouces_au_budget_de_move(tmp_path):
    """21.03 : le vol DÉCLARÉ retranche 2" à la distance max — `get_squad_move_budget` côté
    moteur. Le contrôle de la charge retranchait déjà ces 2" ; move et advance ne le faisaient
    pas, donc les trois contrôles « mutualisés » ne mesuraient pas la même chose et aucun vol
    hors budget n'était remonté.
    """
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T1 P1 MOVE : Unit 1(50,50) MOVED from (50,50) to (50,50)"
        "[R:+0.0] [MODELS: 1#0@(50,50)] [SUCCESS]\n"
        # Intercessor : MOVE 6. Vol déclaré → budget 4. Un déplacement de 5 cases dépasse.
        "[10:00:03] E1 T1 P1 MOVE : Unit 1(55,50) MOVED [FLY] from (50,50) to (55,50)"
        "[R:+0.0] [MODELS: 1#0@(55,50)] [SUCCESS]\n"
    )
    log = tmp_path / "move_fly_budget.log"
    log.write_text(_log(body, scale=1))
    stats = an.parse_step_log(str(log))

    assert stats["move_distance_over_limit"]["move"][1] == 1, "les 2\" de 21.03 non retranchés"


def test_les_regles_du_run_viennent_du_log_pas_du_config_courant(tmp_path):
    """`config/game_config.json` s'édite entre deux runs. Relire `engagement_zone`, les métriques
    de distance ou les toggles de traversée au moment de l'ANALYSE, c'est juger un vieux journal
    avec les règles du jour — et contrairement à l'échelle, rien ne le signalait.
    """
    import ai.analyzer_config as ac

    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [SUCCESS]\n"
    )
    # Valeurs VOLONTAIREMENT différentes de celles de `config/game_config.json` : si l'analyzer
    # relisait le config, aucune de ces trois assertions ne passerait.
    entete = (
        "[10:00:00] Run rules: engagement_zone_subhex=7 metric.engagement=euclidean "
        "metric.ranged=hex move.thru_ez=False move.thru_enemy=True move.thru_friendly=False"
    )
    brut = _log(body, scale=1).split("\n")
    log_txt = "\n".join([l for l in brut if "Run rules:" not in l])
    log_txt = log_txt.replace("[10:00:00] === ACTIONS START ===", entete + "\n[10:00:00] === ACTIONS START ===")
    log = tmp_path / "regles.log"
    log.write_text(log_txt)
    an.parse_step_log(str(log))

    assert an._get_engagement_zone_for_analyzer() == 7
    assert ac.get_run_rule("metric.engagement") == "euclidean"
    assert ac.get_run_rule("metric.ranged") == "hex"
    assert an._move_rules_for_analyzer() == (False, True, False)


def test_un_log_sans_entete_de_regles_est_refuse(tmp_path):
    """Même refus explicite que pour l'échelle : sans les règles, le verdict serait faux en
    silence. Un journal produit avant cette ligne n'est plus analysable — c'est voulu."""
    import pytest as _pytest

    body = "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
    sans_regles = "\n".join(
        l for l in _log(body, scale=1).split("\n") if "Run rules:" not in l
    )
    log = tmp_path / "sans_regles.log"
    log.write_text(sans_regles)

    with _pytest.raises(ValueError, match=r"Run rules"):
        an.parse_step_log(str(log))
