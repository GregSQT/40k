"""Trois verdicts que l'analyzer rendait faux, sur un step.log réel de 6 épisodes (206 erreurs).

1. **Échelle.** L'analyzer prenait `inches_to_subhex` dans le `board_config` COURANT au lieu de
   l'entête `Board:` du log analysé. Un run joué sur `board/44x60x1` relu avec un `config.json`
   pointant `board/44x60x5` mesurait tout ×5 : zone d'engagement à 10 subhex au lieu de 2 (132
   faux « shoot at engaged enemy »), et symétriquement portées, budgets de move et d'advance ×5
   — donc jamais dépassés. Il fabriquait des erreurs ET en masquait.

2. **MONSTER/VEHICLE au contact.** 10.06 rend une unité M/V ENGAGÉE éligible au close-quarters
   shooting avec TOUTES ses armes, sur les unités avec lesquelles elle est engagée (-1 pour
   toucher, que le moteur applique) ; 17.03 autorise réciproquement à prendre pour cible un M/V
   engagé. L'analyzer ignorait les deux : chaque tir d'un LandSpeeder au contact remontait deux
   erreurs.

3. **FLY.** 21.03 : la traversée (murs, figurines) est DÉCLARÉE, et le pipeline squad — le
   chemin de production — ne transmettait pas le drapeau. Aucun `[FLY]` n'apparaissait dans
   step.log, l'analyzer pathfindait les escouades volantes comme de l'infanterie, et un vol
   par-dessus un mur remontait « move path blocked ».
"""
from __future__ import annotations

import pytest

import ai.analyzer as an

OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))


def _pose_regles_du_run(scale: int, *, ez_inches: int = 2, metric: str = "hex") -> int:
    """Hors `parse_step_log`, l'échelle ET les règles du run se posent à la main : les getters
    lèvent plutôt que de retomber sur le config courant. Rend la zone d'engagement en subhex."""
    from ai.analyzer_config import set_run_rules

    an.set_analyzer_board_scale(scale)
    ez = ez_inches * scale
    set_run_rules({
        "engagement_zone_subhex": str(ez),
        "metric.engagement": metric,
        "metric.ranged": "euclidean",
        "move.thru_ez": "True",
        "move.thru_enemy": "False",
        "move.thru_friendly": "True",
    })
    return ez


def _log(body: str, *, inches_to_subhex: int = 5, walls: str = "", board: str = "cols=220 rows=300",
         units: str = "") -> str:
    return (
        "=== STEP-BY-STEP ACTION LOG ===\n"
        "================================================================================\n\n"
        "[10:00:00] === EPISODE 1 START ===\n"
        "[10:00:00] Scenario: scenario_bot-01\n"
        "[10:00:00] Opponent: SelfplayBot\n"
        f"[10:00:00] Walls: {walls}\n"
        f"[10:00:00] Objectives: rect b NW:{OBJECTIVES}\n"
        f"[10:00:00] Board: {board} inches_to_subhex={inches_to_subhex} hex_radius=2.78 margin=1\n"
        f"[10:00:00] Run rules: engagement_zone_subhex={2 * inches_to_subhex} metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex={2 * inches_to_subhex} cohesion.global_subhex={9 * inches_to_subhex} cohesion.min_neighbors=1\n"
        f"{units}"
        "[10:00:00] === ACTIONS START ===\n"
        f"{body}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Échelle : elle vient de l'entête du log, pas du config courant
# ─────────────────────────────────────────────────────────────────────────────

def test_un_log_sans_entete_board_est_refuse(tmp_path):
    """Sans l'entête, l'échelle du run est indéterminable. Analyser quand même reviendrait à
    prendre celle du prochain run — c'est exactement le défaut d'origine, silencieux."""
    log = tmp_path / "step.log"
    log.write_text(
        "=== STEP-BY-STEP ACTION LOG ===\n"
        "[10:00:00] === EPISODE 1 START ===\n"
        "[10:00:00] Walls: none\n"
    )
    with pytest.raises(ValueError, match=r"inches_to_subhex"):
        an.parse_step_log(str(log))


def test_l_echelle_lue_est_celle_du_log_pas_celle_du_config(tmp_path):
    """Le même fichier, deux entêtes : la valeur retenue suit le log."""
    for scale in (1, 5, 10):
        log = tmp_path / f"step_{scale}.log"
        log.write_text(_log("", inches_to_subhex=scale))
        assert an.parse_board_scale_from_log(str(log)) == scale


def test_la_zone_d_engagement_est_celle_du_journal(tmp_path):
    """La zone d'engagement vient de l'entête `Run rules:`, déjà EN SUBHEXES — le moteur la
    convertit au chargement et journalise ce qu'il applique.

    Ce test comparait auparavant deux appels de son propre helper : il vérifiait l'arithmétique
    de la fixture, pas le code. Il lit maintenant un vrai journal et interroge la fonction.
    """
    from ai.analyzer_config import set_run_rules

    an.set_analyzer_board_scale(1)
    # Valeur qu'aucune combinaison config × échelle ne produirait par hasard.
    set_run_rules({
        "engagement_zone_subhex": "13",
        "metric.engagement": "hex",
        "metric.ranged": "euclidean",
        "move.thru_ez": "True",
        "move.thru_enemy": "False",
        "move.thru_friendly": "True",
    })

    assert an._get_engagement_zone_for_analyzer() == 13


# ─────────────────────────────────────────────────────────────────────────────
# 2. MONSTER/VEHICLE : 10.06 et 17.03
# ─────────────────────────────────────────────────────────────────────────────

# Deux positions ADJACENTES (distance 1) : le tireur est donc engagé avec sa cible.
V = "(50,50)"
E = "(51,50)"
_MV_UNITS = (
    "[10:00:00] Unit 1 (LandSpeederOnslaughtGatlingCannon) P1: Starting position (-1,-1), HP_MAX=9\n"
    "[10:00:00] Unit 2 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2\n"
)


def _adjacent_shot_stats(tmp_path, shooter_id: str, weapon: str, name: str):
    body = (
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit {shooter_id}{V} DEPLOYED from (-1,-1) to {V} [R:+0.0] [SUCCESS]\n"
        f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{E} DEPLOYED from (-1,-1) to {E} [R:+0.0] [SUCCESS]\n"
        f"[10:00:02] E1 T1 P1 SHOOT : Unit {shooter_id}{V} SHOT Unit 101{E} with [{weapon}] "
        f"- Hit 4(4+) - Wound 5(3+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
    )
    log = tmp_path / name
    log.write_text(_log(body, units=_MV_UNITS))
    return an.parse_step_log(str(log))


def test_un_vehicule_engage_tire_avec_une_arme_non_close_quarters(tmp_path):
    """10.06 : « Has one or more [CLOSE-QUARTERS] weapons **or is a MONSTER/VEHICLE unit** ».
    Le LandSpeeder au contact tire son Multi-Melta — légal, et le moteur applique bien le -1."""
    stats = _adjacent_shot_stats(tmp_path, "1", "Multi-Melta", "vehicle.log")

    assert stats["shoot_invalid"][1]["engaged_non_close_quarters"] == 0
    assert stats["shoot_at_engaged_enemy"][1] == 0


def test_la_meme_arme_reste_fautive_pour_de_l_infanterie(tmp_path):
    """Contre-épreuve : sans le keyword, 10.06 ne s'applique pas — seules les armes
    [CLOSE_QUARTERS] tirent au contact. Sans elle, l'exemption désarmerait le contrôle."""
    stats = _adjacent_shot_stats(tmp_path, "2", "Bolt Rifle", "infantry.log")

    assert stats["shoot_invalid"][1]["engaged_non_close_quarters"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. FLY : le marqueur du log, et lui seul, atteste la déclaration 21.03
# ─────────────────────────────────────────────────────────────────────────────

# Mur PLEIN sur la colonne 60 : aucun contournement n'existe dans le budget, donc un chemin au
# sol est réellement impossible — la seule explication d'un déplacement réussi est le vol.
_FLY_WALLS = ";".join(f"({60},{r})" for r in range(0, 300))
_FLY_UNITS = (
    "[10:00:00] Unit 1 (VanguardVeteranSquadJumpPack) P1: Starting position (-1,-1), HP_MAX=2\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2\n"
)
_FROM = "(55,50)"
_TO = "(65,50)"


def _fly_move_stats(tmp_path, fly_token: str, name: str):
    body = (
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{_FROM} DEPLOYED from (-1,-1) to {_FROM} [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(200,200) DEPLOYED from (-1,-1) to (200,200) [R:+0.0] [SUCCESS]\n"
        f"[10:00:02] E1 T1 P1 MOVE : Unit 1{_TO} MOVED{fly_token} from {_FROM} to {_TO}"
        f"[R:+0.0] [MODELS: 1#0@(65,50)] [SUCCESS]\n"
    )
    log = tmp_path / name
    log.write_text(_log(body, walls=_FLY_WALLS, units=_FLY_UNITS))
    return an.parse_step_log(str(log))


def test_un_vol_par_dessus_un_mur_n_est_pas_un_chemin_bloque(tmp_path):
    """Avec le marqueur, l'analyzer mesure une distance à vol d'oiseau (21.03) au lieu de
    pathfinder. C'est ce marqueur que le pipeline squad n'émettait pas."""
    stats = _fly_move_stats(tmp_path, " [FLY]", "fly.log")

    assert stats["move_distance_over_limit"]["move"][1] == 0


def test_sans_marqueur_le_meme_deplacement_est_bien_signale(tmp_path):
    """Contre-épreuve, et raison de ne PAS exempter sur le keyword du registre : une unité
    volante qui n'a pas déclaré marche, paie les murs, et doit être signalée si elle les
    traverse quand même."""
    stats = _fly_move_stats(tmp_path, "", "walk.log")

    assert stats["move_distance_over_limit"]["move"][1] == 1


@pytest.mark.parametrize("verbe,action_key,ligne", [
    ("MOVED", "move", "Unit 1(65,50) MOVED [FLY] from (55,50) to (65,50)"),
    ("FLED", "fled", "Unit 1(65,50) FLED [FLY] from (55,50) to (65,50)"),
    ("ADVANCED", "advance", "Unit 1(65,50) ADVANCED [FLY] from (55,50) to (65,50) [Roll: 3]"),
])
def test_le_token_fly_ne_casse_l_aiguillage_d_aucun_type_de_move(verbe, action_key, ligne, tmp_path):
    """Le token s'insère entre le verbe et `from`. Les aiguillages sur la chaîne littérale
    « <VERBE> from » laissaient ces lignes SANS branche : l'action n'était pas traitée, la
    position de l'unité restait figée, et toutes les adjacences calculées ensuite l'étaient
    contre un fantôme. Mesuré : 3 lignes non parsées fabriquaient 3 fausses erreurs."""
    body = (
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{_FROM} DEPLOYED from (-1,-1) to {_FROM} [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(200,200) DEPLOYED from (-1,-1) to (200,200) [R:+0.0] [SUCCESS]\n"
        f"[10:00:02] E1 T1 P1 MOVE : {ligne} [R:+0.0] [MODELS: 1#0@(65,50)] [SUCCESS]\n"
    )
    log = tmp_path / f"{verbe}.log"
    log.write_text(_log(body, units=_FLY_UNITS))
    stats = an.parse_step_log(str(log))

    assert not stats["parse_errors"], stats["parse_errors"]
    # Le vrai enjeu : la ligne a été AIGUILLÉE vers son handler, pas seulement non signalée.
    assert stats["action_phase_accuracy"][action_key]["total"] == 1, stats["action_phase_accuracy"]


def test_le_step_logger_ecrit_le_marqueur_sur_les_trois_types_de_move(tmp_path):
    """Maillon moteur → log : sans ce rendu, l'analyzer n'a rien à lire."""
    from ai.step_logger import StepLogger

    out = tmp_path / "step.log"
    logger = StepLogger(output_file=str(out), enabled=True, buffer_size=1)
    logger.episode_number = 1
    for action_type, extra in (("move", {}), ("flee", {}), ("advance", {"advance_range": 3})):
        logger.log_action(
            unit_id="1", action_type=action_type, phase="move", player=1, success=True,
            step_increment=True,
            action_details={
                "current_turn": 1, "start_pos": (55, 50), "end_pos": (65, 50),
                "unit_with_coords": "1(65,50)", "is_fly_move": True, **extra,
            },
        )
    logger._flush_buffer()
    lines = [l for l in out.read_text().splitlines() if " MOVE : " in l]

    assert len(lines) == 3, lines
    assert all("[FLY]" in l for l in lines), lines


def test_le_moteur_transmet_le_drapeau_de_vol_au_formateur():
    """Maillon action_log moteur → action_details. C'est CE mapping qui manquait : le drapeau
    était produit par les handlers de move et jeté ici."""
    from engine.w40k_core import W40KEngine

    class _Bridge:
        """Le segment per-figurine n'est pas le sujet ici : seul le mapping du drapeau l'est."""
        def _models_segment_for_unit(self, unit_id):
            return ""

    build = W40KEngine._build_step_log_details.__get__(_Bridge())
    raw = {"unitId": "1", "fromCol": 55, "fromRow": 50, "toCol": 65, "toRow": 50,
           "turn": 1, "is_fly_move": True}

    assert build(raw, 1)["is_fly_move"] is True
    raw["is_fly_move"] = False
    assert build(raw, 1)["is_fly_move"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Engagement : une escouade n'est pas son ancre (03.04)
# ─────────────────────────────────────────────────────────────────────────────

def test_l_engagement_voit_tous_les_socles_pas_seulement_l_ancre():
    """Ancre du sujet LOIN de l'ennemi, un de ses socles au contact. Réduire l'escouade à son
    ancre — ce que faisait ce contrôle — déclarait l'unité libre de tout engagement."""
    ez = _pose_regles_du_run(1)
    unit_player = {"a1": 1, "e1": 2}
    unit_hp = {"a1": 1, "e1": 1}
    unit_positions = {"a1": (10, 10), "e1": (30, 10)}
    # a1#3 est collé à l'ennemi ; l'ancre a1#0 en est à 20 cases.
    models = {"a1": {"a1#0": (10, 10), "a1#3": (30 - ez, 10)}, "e1": {"e1#0": (30, 10)}}

    assert an.is_within_engine_engagement_zone(
        "a1", unit_player, unit_positions, unit_hp, engagement_zone=ez,
        positions_by_model=models, unit_base={},
    ) is True
    # Sans les socles, le même état est déclaré non engagé — c'est le défaut d'origine.
    assert an.is_within_engine_engagement_zone(
        "a1", unit_player, unit_positions, unit_hp, engagement_zone=ez,
    ) is False


def test_l_engagement_voit_tous_les_socles_de_l_ENNEMI_aussi():
    """Symétrique : c'est un socle ENNEMI avancé qui engage, pas son ancre."""
    ez = _pose_regles_du_run(1)
    unit_player = {"a1": 1, "e1": 2}
    unit_hp = {"a1": 1, "e1": 1}
    unit_positions = {"a1": (10, 10), "e1": (30, 10)}
    models = {"a1": {"a1#0": (10, 10)}, "e1": {"e1#0": (30, 10), "e1#4": (10 + ez, 10)}}

    assert an.is_within_engine_engagement_zone(
        "a1", unit_player, unit_positions, unit_hp, engagement_zone=ez,
        positions_by_model=models, unit_base={},
    ) is True


def test_la_taille_de_socle_declaree_dans_le_log_est_respectee():
    """À x5/x10 le socle occupe plusieurs cases : deux escouades hors de portée d'ancre à
    ancre peuvent être bord à bord. Le socle vient de l'entête du log (`base=`), donc déjà à
    l'échelle du board — jamais reconstruit ici."""
    ez = _pose_regles_du_run(5, metric="euclidean")
    unit_player = {"a1": 1, "e1": 2}
    unit_hp = {"a1": 1, "e1": 1}
    gap = ez + 6  # ancres hors zone d'engagement pour des socles ponctuels
    unit_positions = {"a1": (10, 10), "e1": (10 + gap, 10)}
    models = {"a1": {"a1#0": (10, 10)}, "e1": {"e1#0": (10 + gap, 10)}}

    assert an.is_within_engine_engagement_zone(
        "a1", unit_player, unit_positions, unit_hp, engagement_zone=ez,
        positions_by_model=models, unit_base={},
    ) is False
    # Mêmes positions, socles ronds de 8 cases de diamètre : les bords se touchent.
    assert an.is_within_engine_engagement_zone(
        "a1", unit_player, unit_positions, unit_hp, engagement_zone=ez,
        positions_by_model=models, unit_base={"a1": ("round", 8), "e1": ("round", 8)},
    ) is True


def test_un_allie_n_engage_jamais():
    """Contre-épreuve : sans le filtre de camp, la mesure d'empreintes rendrait tout le monde
    engagé en permanence (les socles alliés sont les plus proches voisins)."""
    ez = _pose_regles_du_run(1)
    unit_player = {"a1": 1, "a2": 1}
    unit_hp = {"a1": 1, "a2": 1}
    unit_positions = {"a1": (10, 10), "a2": (11, 10)}

    assert an.is_within_engine_engagement_zone(
        "a1", unit_player, unit_positions, unit_hp, engagement_zone=ez,
        positions_by_model={"a1": {"a1#0": (10, 10)}, "a2": {"a2#0": (11, 10)}}, unit_base={},
    ) is False


def test_les_socles_de_depart_excluent_les_figurines_mortes_entre_temps():
    """`positions_by_model` porte le dernier `[MODELS:]` où l'unité était ACTRICE : une escouade
    fauchée pendant le tir adverse y garde ses socles morts jusqu'à sa prochaine action. Mesurer
    l'engagement de départ dessus fabriquait un « advance from adjacent » sur des figurines
    retirées du plateau (mesuré sur un run réel)."""
    from ai.analyzer_perfig import surviving_start_models

    avant = {"101#1": (10, 45), "101#3": (10, 43), "101#5": (14, 45)}
    ligne = {"101#5": (18, 36)}  # seul survivant, déjà à sa destination

    assert surviving_start_models(avant, ligne) == {"101#5": (14, 45)}
    # Sans `[MODELS:]` sur la ligne : rien à croiser, on garde l'état connu.
    assert surviving_start_models(avant, None) == avant
    # Aucun survivant commun : None → l'appelant retombe sur l'ancre plutôt que sur des morts.
    assert surviving_start_models(avant, {"101#9": (1, 1)}) is None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Socles périmés : une escouade qui PERD une figurine sans agir
# ─────────────────────────────────────────────────────────────────────────────

_STALE_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2\n"
    "[10:00:00] Unit 2 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2\n"
    # 3 = tireur de la seconde activation (cf. Tir 3).
    "[10:00:00] Unit 3 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2\n"
)

_STALE_SETUP = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(10,10) DEPLOYED from (-1,-1) to (10,10) [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2(30,10) DEPLOYED from (-1,-1) to (30,10) [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 3(45,10) DEPLOYED from (-1,-1) to (45,10) [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(50,10) DEPLOYED from (-1,-1) to (50,10) [R:+0.0] [SUCCESS]\n"
    # 101 agit : ses DEUX socles sont connus, dont 101#1 collé à l'unité 2.
    "[10:00:02] E1 T1 P2 MOVE : Unit 101(50,10) MOVED from (50,10) to (50,10)"
    "[R:+0.0] [MODELS: 101#0@(50,10) 101#1@(31,10)] [SUCCESS]\n"
)
# Tir 1 : une figurine de 101 tombe. Laquelle ? le log ne le dit pas.
_STALE_TIR_1 = (
    "[10:00:03] E1 T1 P1 SHOOT : Unit 1(10,10) SHOT Unit 101(50,10) with [Bolt Rifle] "
    "- Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [SUCCESS]\n"
)
# Tir 2 : même tireur, même cible, donc même activation — l'ancre loguée est déjà celle du survivant.
_STALE_TIR_2 = (
    "[10:00:04] E1 T1 P1 SHOOT : Unit 1(10,10) SHOT Unit 101(50,10) with [Bolt Rifle] "
    "- Hit 4(3+) - Wound 5(4+) - Save 2(3+) [R:+0.0] [SUCCESS]\n"
)
# Tir 3 : activation SUIVANTE, tireur non engagé (l'unité 2, elle, serait exemptée par 10.06).
_STALE_TIR_3 = (
    "[10:00:05] E1 T1 P1 SHOOT : Unit 3(45,10) SHOT Unit 101(50,10) with [Bolt Rifle] "
    "- Hit 4(3+) - Wound 5(4+) - Save 2(3+) [R:+0.0] [SUCCESS]\n"
)


def test_les_socles_d_une_cible_fauchee_ne_hantent_pas_le_plateau(tmp_path):
    """`positions_by_model` n'est réécrit que quand l'unité AGIT : une cible qui perd une
    figurine garde ses socles morts jusqu'à sa prochaine action, et le log ne dit pas LAQUELLE
    est tombée (allocation « front », pas nominative). Ces socles périmés ne doivent pas fabriquer
    d'engagement — mais ils ne doivent pas non plus en effacer un qui existait au ciblage.

    LA FRONTIÈRE EST L'ACTIVATION (04.02 : « Select Weapons, Select Targets, Resolve Attacks »
    — les cibles de TOUTES les armes sont choisies avant la première résolution). Le socle 101#1
    collé à l'unité 2 était vivant au ciblage de l'unité 1 : ses deux lignes sont fautives, et
    les juger après les pertes était le faux négatif fermé le 2026-08-12. L'activation suivante,
    elle, se juge sur un plateau où ce socle n'est plus — c'est le sujet de ce test.

    DEUX MESURES, PAS UN TOTAL : un seul compteur agrégé se laisse satisfaire par la compensation
    (gel qui régresse ET socle qui hante ⇒ même somme). Le second journal ne diffère du premier
    que par le tir de l'unité 3, donc son apport se lit à l'unité près.
    """
    def _erreurs(*lignes: str) -> int:
        log = tmp_path / f"stale_{len(lignes)}.log"
        log.write_text(_log(
            "".join((_STALE_SETUP,) + lignes),
            inches_to_subhex=1, board="cols=60 rows=60", units=_STALE_UNITS,
        ))
        return an.parse_step_log(str(log))["shoot_at_engaged_enemy"][1]

    activation_fautive = _erreurs(_STALE_TIR_1, _STALE_TIR_2)
    assert activation_fautive == 2, (
        f"les deux lignes d'un ciblage fautif se comptent, pertes comprises : {activation_fautive}"
    )
    assert _erreurs(_STALE_TIR_1, _STALE_TIR_2, _STALE_TIR_3) == activation_fautive, (
        "l'activation suivante vise un survivant à 20 cases : le socle mort est encore mesuré"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. HORS TABLE : la sentinelle (-1,-1) n'est pas une position (20.01, 03.04)
# ─────────────────────────────────────────────────────────────────────────────
#
# L'entête déclare TOUTES les escouades à `(-1,-1)`, et `unit_positions` les y garde jusqu'à leur
# mise en place (réserves stratégiques : jusqu'à leur ingress move, 20.04). Toute énumération
# géométrique qui les garde mesure contre le coin du plateau : la sentinelle est adjacente à
# `(0,0)` et à portée de n'importe quelle arme. Un verdict inventé, jamais une erreur.

# Le WAITer est un `Terminator` : sa seule arme de tir (Storm Bolter, 24") n'est PAS
# [CLOSE_QUARTERS]. Avec un Intercessor — qui porte un Bolt Pistol — la requalification en `skip`
# n'a jamais lieu, et le test de l'adjacence à la sentinelle serait vert sans rien verrouiller
# (constaté par contre-épreuve : la garde retirée, la suite restait verte).
_OFF_TABLE_UNITS = (
    "[10:00:00] Unit 1 (Terminator) P1: Starting position (-1,-1), HP_MAX=2\n"
    "[10:00:00] Unit 2 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2\n"
)


def test_la_sentinelle_est_bien_adjacente_a_l_origine_du_plateau():
    """Montage des deux tests suivants : sans cette adjacence, ils seraient verts sans rien
    construire. `(0,0)` est le SEUL hexe réel voisin de `(-1,-1)`."""
    assert an.is_adjacent(0, 0, -1, -1) is True
    assert (0, 0) in an.get_hex_neighbors(-1, -1)


def _wait_stats(tmp_path, name: str, body: str):
    log = tmp_path / name
    log.write_text(_log(body, inches_to_subhex=1, board="cols=60 rows=60", units=_OFF_TABLE_UNITS))
    return an.parse_step_log(str(log))


def test_un_ennemi_en_reserves_n_est_pas_une_cible_valide_pour_un_wait(tmp_path):
    """101 n'est jamais mise en place : elle reste à la sentinelle. Mesurée depuis là, elle est à
    portée du Bolt Rifle de n'importe où — tout WAIT légal ressortait `wait_with_los`."""
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(10,10) DEPLOYED from (-1,-1) to (10,10) [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T1 P1 SHOOT : Unit 1(10, 10) WAIT [R:+0.0] [SUCCESS]\n"
    )
    stats = _wait_stats(tmp_path, "reserve_target.log", body)

    assert stats["wait_by_phase"][1]["wait_with_los"] == 0
    assert stats["wait_by_phase"][1]["wait_no_los"] == 1
    # Contre-épreuve : la MÊME unité posée à 3 cases EST une cible — sans quoi le filtre
    # ci-dessus désarmerait le contrôle au lieu de le corriger.
    body_posee = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(10,10) DEPLOYED from (-1,-1) to (10,10) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(13,10) DEPLOYED from (-1,-1) to (13,10) [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T1 P1 SHOOT : Unit 1(10, 10) WAIT [R:+0.0] [SUCCESS]\n"
    )
    stats = _wait_stats(tmp_path, "posee.log", body_posee)
    assert stats["wait_by_phase"][1]["wait_with_los"] == 1


def test_une_escouade_ARRIVEE_des_reserves_quitte_la_sentinelle(tmp_path):
    """Contrepartie indispensable des filtres : l'ingress move (20.04) est journalisé par le
    formateur `deploy_unit` — « DEPLOYED from (-1,-1) to … » — mais dans la phase de MOUVEMENT.
    La regex de mise en place étant épinglée sur `DEPLOYMENT`, l'arrivée n'était lue par AUCUNE
    branche et l'escouade restait à la sentinelle tout l'épisode. Écarter les unités hors table
    aurait alors rendu une unité RÉELLEMENT posée invisible : un angle mort au lieu d'un verdict
    faux."""
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(10,10) DEPLOYED from (-1,-1) to (10,10) [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T2 P2 MOVE : Unit 101(13,10) DEPLOYED from (-1,-1) to (13,10) [R:+0.0] [SUCCESS]\n"
        "[10:00:03] E1 T2 P1 SHOOT : Unit 1(10, 10) WAIT [R:+0.0] [SUCCESS]\n"
    )
    stats = _wait_stats(tmp_path, "ingress.log", body)

    assert stats["wait_by_phase"][1]["wait_with_los"] == 1, (
        "l'escouade arrivée des réserves est restée à la sentinelle : elle n'est plus une cible"
    )
    # L'ingress reste une ACTION de la phase de mouvement — un step gym. Lire sa position ne doit
    # pas l'absorber : la ligne doit continuer vers le parseur d'action, qui la compte et porte
    # les remises à zéro de tour et de phase. La ligne de DÉPLOIEMENT, elle, n'est pas comptée.
    assert stats["actions_by_phase"]["MOVE"] == 1
    assert stats["total_actions"] == 2


def test_l_ingress_est_une_activation_et_une_seconde_en_est_une_double(tmp_path):
    """20.04 : l'ingress EST le mouvement du tour, le moteur termine l'activation. Une escouade
    qui arrive PUIS se déplace dans la même phase double son activation — invisible tant que la
    ligne d'arrivée n'était pas un marqueur d'activation."""
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(10,10) DEPLOYED from (-1,-1) to (10,10) [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T2 P2 MOVE : Unit 101(13,10) DEPLOYED from (-1,-1) to (13,10) [R:+0.0] [SUCCESS]\n"
        "[10:00:03] E1 T2 P2 MOVE : Unit 101(14,10) MOVED from (13,10) to (14,10)"
        " [R:+0.0] [MODELS: 101#0@(14,10)] [SUCCESS]\n"
    )
    stats = _wait_stats(tmp_path, "ingress_double.log", body)

    assert stats["double_activation_by_phase"]["MOVE"] == 1


def test_une_unite_arrivee_des_reserves_compte_dans_les_collisions(tmp_path):
    """L'entrée d'historique de l'arrivée porte `turn` et `episode`, sans quoi les détecteurs de
    collision ne la retiennent jamais : deux escouades sur le MÊME hexe passaient inaperçues."""
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(10,10) DEPLOYED from (-1,-1) to (10,10) [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T2 P2 MOVE : Unit 101(13,10) DEPLOYED from (-1,-1) to (13,10) [R:+0.0] [SUCCESS]\n"
        # L'unité 1 vient se poser sur l'hexe déjà tenu par l'arrivante.
        "[10:00:03] E1 T2 P1 MOVE : Unit 1(13,10) MOVED from (10,10) to (13,10)"
        " [R:+0.0] [MODELS: 1#0@(13,10)] [SUCCESS]\n"
    )
    stats = _wait_stats(tmp_path, "ingress_collision.log", body)

    collisions = stats["unit_position_collisions"]
    assert len(collisions) == 1, collisions
    assert set(collisions[0]["units"]) == {"1", "101"}


def test_un_ennemi_en_reserves_ne_transforme_pas_un_wait_en_skip(tmp_path):
    """Jumeau adjacence du précédent : le tireur posé en `(0,0)` touche la sentinelle. Sans le
    filtre, son WAIT — sans arme [CLOSE_QUARTERS] — était requalifié en `skip`."""
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(0,0) DEPLOYED from (-1,-1) to (0,0) [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T1 P1 SHOOT : Unit 1(0, 0) WAIT [R:+0.0] [SUCCESS]\n"
    )
    stats = _wait_stats(tmp_path, "reserve_adjacence.log", body)

    assert stats["shoot_vs_wait"]["skip"] == 0
    assert stats["shoot_vs_wait"]["wait"] == 1


def test_un_ALLIE_en_reserves_ne_met_pas_la_cible_au_contact(tmp_path):
    """Troisième énumération du même bloc, côté ami (10.05 : une cible au contact d'un ami ne se
    tire pas). L'ennemi posé en `(0,0)` est voisin de la sentinelle : un ami PAS ENCORE POSÉ le
    déclarait « au contact », et le WAIT ne voyait plus aucune cible."""
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(0,3) DEPLOYED from (-1,-1) to (0,3) [R:+0.0] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(0,0) DEPLOYED from (-1,-1) to (0,0) [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T1 P1 SHOOT : Unit 1(0, 3) WAIT [R:+0.0] [SUCCESS]\n"
    )
    stats = _wait_stats(tmp_path, "allie_reserve.log", body)

    assert stats["wait_by_phase"][1]["wait_with_los"] == 1


def test_la_bande_d_ez_du_bfs_ignore_les_unites_hors_table():
    """`_build_enemy_adjacent_hexes` alimente la bande d'EZ qui bloque le BFS de move et de
    charge. Un ennemi en réserves y versait les six voisins de la sentinelle, dont `(0,0)`."""
    unit_player = {"101": 2, "102": 2}
    unit_hp = {"101": 1, "102": 1}

    hors_table = an._build_enemy_adjacent_hexes({"101": (-1, -1)}, unit_player, unit_hp, player=1)
    assert hors_table == set()
    # Contre-épreuve : une unité POSÉE verse bien ses voisins.
    posee = an._build_enemy_adjacent_hexes({"102": (10, 10)}, unit_player, unit_hp, player=1)
    assert posee == set(an.get_hex_neighbors(10, 10))


def test_les_cases_occupees_du_bfs_ignorent_les_unites_hors_table():
    """Jumeau VIVANT du précédent : avec la config par défaut (`move.thru_ez=True`,
    `move.thru_enemy=False`) la bande d'EZ est vide et seule cette boucle bloque le BFS. Une
    escouade en réserves y versait l'empreinte de la sentinelle — à x5 un socle de 32 mm couvre
    des dizaines d'hexes RÉELS autour de `(0,0)` — et le BFS refusait des chemins légaux."""
    _pose_regles_du_run(5)
    unit_player = {"a1": 1, "e1": 2}
    unit_hp = {"a1": 1, "e1": 1}
    base = {"e1": ("round", 16)}

    occupied, ez_band = an._build_move_bfs_blockers(
        {"e1": {"e1#0": (-1, -1)}}, {"a1": (50, 50), "e1": (-1, -1)}, base,
        unit_player, unit_hp, "a1",
    )
    assert occupied == set(), sorted(h for h in occupied if h[0] >= 0)[:10]
    assert ez_band == set()
    # Contre-épreuve : la MÊME escouade posée bloque bien, et son empreinte déborde de son ancre.
    occupied, _ = an._build_move_bfs_blockers(
        {"e1": {"e1#0": (30, 30)}}, {"a1": (50, 50), "e1": (30, 30)}, base,
        unit_player, unit_hp, "a1",
    )
    assert len(occupied) > 1 and (30, 30) in occupied


def test_un_ennemi_hors_table_n_est_adjacent_a_personne():
    """`get_adjacent_enemies` nomme l'ennemi dans les lignes d'erreur et les traces de
    charge/advance. Une escouade en réserves y apparaissait pour toute unité en `(0,0)`."""
    unit_player = {"101": 2}
    unit_hp = {"101": 1}
    unit_types = {"101": "AssaultIntercessor"}

    assert an.get_adjacent_enemies(0, 0, unit_player, {"101": (-1, -1)}, unit_hp, unit_types, 1) == []
    # Contre-épreuve : posée sur un hexe voisin, elle est bien nommée.
    voisin = sorted(an.get_hex_neighbors(0, 0))[-1]
    assert an.get_adjacent_enemies(
        0, 0, unit_player, {"101": voisin}, unit_hp, unit_types, 1
    ) == ["101"]
