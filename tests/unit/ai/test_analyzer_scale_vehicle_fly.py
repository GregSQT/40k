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


def test_la_zone_d_engagement_suit_l_echelle_du_run():
    """`engagement_zone` est stocké EN POUCES et converti ×inches_to_subhex, exactement comme
    le moteur le fait au chargement. C'est ce facteur qui valait 5 fois trop."""
    an.set_analyzer_board_scale(1)
    ez_x1 = an._get_engagement_zone_for_analyzer()
    an.set_analyzer_board_scale(5)
    ez_x5 = an._get_engagement_zone_for_analyzer()

    assert ez_x5 == 5 * ez_x1, (ez_x1, ez_x5)


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

    assert stats["shoot_invalid"][1]["adjacent_non_close_quarters"] == 0
    assert stats["shoot_at_engaged_enemy"][1] == 0


def test_la_meme_arme_reste_fautive_pour_de_l_infanterie(tmp_path):
    """Contre-épreuve : sans le keyword, 10.06 ne s'applique pas — seules les armes
    [CLOSE_QUARTERS] tirent au contact. Sans elle, l'exemption désarmerait le contrôle."""
    stats = _adjacent_shot_stats(tmp_path, "2", "Bolt Rifle", "infantry.log")

    assert stats["shoot_invalid"][1]["adjacent_non_close_quarters"] == 1


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

    assert stats["move_path_blocked"]["move"][1] == 0


def test_sans_marqueur_le_meme_deplacement_est_bien_signale(tmp_path):
    """Contre-épreuve, et raison de ne PAS exempter sur le keyword du registre : une unité
    volante qui n'a pas déclaré marche, paie les murs, et doit être signalée si elle les
    traverse quand même."""
    stats = _fly_move_stats(tmp_path, "", "walk.log")

    assert stats["move_path_blocked"]["move"][1] == 1


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
    an.set_analyzer_board_scale(1)
    ez = an._get_engagement_zone_for_analyzer()
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
    an.set_analyzer_board_scale(1)
    ez = an._get_engagement_zone_for_analyzer()
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
    an.set_analyzer_board_scale(5)
    ez = an._get_engagement_zone_for_analyzer()
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
    an.set_analyzer_board_scale(1)
    ez = an._get_engagement_zone_for_analyzer()
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
