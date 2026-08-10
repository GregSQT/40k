"""Deux obstacles que le BFS de mouvement de l'analyzer ne connaissait pas — verts vacants V7 et
V6 de `Documentation/Implémentation/analyzer_couverture.md`.

**V7 — le bord du plateau.** 03.01, mot pour mot : « Its base cannot cross the edge of the
battlefield. » Le champ géodésique du MOTEUR borne ses voisins au plateau
(`geodesic_move_reach`, `shared_utils.py`) ; celui de l'analyzer ne testait que murs, occupation
et bande d'EZ. Un contournement PAR L'EXTÉRIEUR du plateau était donc un chemin valide à ses
yeux : là où le jeu n'offre qu'un détour interminable, l'analyzer trouvait un raccourci
imaginaire et se taisait. C'est un FAUX NÉGATIF — le contrôle de budget rendait « rien à
signaler » sur le seul chemin que la règle interdit.

**V6 — l'exemption 17.01.** « Each time you make a normal or advance move with a unit,
MONSTER/VEHICLE models in that unit can be moved through friendly and enemy models (excluding
other MONSTER/VEHICLE models). » L'analyzer bloquait tout mobile sur toute figurine ennemie :
un Dreadnought qui traverse un écran d'infanterie remontait « au-delà du budget » alors que la
règle l'y autorise. Faux POSITIF, symétrique du précédent.

Les deux se mesurent dans la même fonction (`_bfs_shortest_path_length` /
`_build_move_bfs_blockers`), d'où un seul fichier. Chaque test CONSTRUIT sa géométrie : les
prémisses ci-dessous vérifient que le détour interne existe bien, qu'il est bien hors budget et
que le détour externe, lui, tenait dans le budget — sans elles, « 1 erreur » ne prouverait pas
que c'est le BORD qui l'a produite.
"""
from __future__ import annotations

import pytest

import ai.analyzer as an


# ─── Géométrie V7 ────────────────────────────────────────────────────────────────────────────
# Plateau 6×8 à l'échelle 1 (1 subhex = 1"), donc M=6" d'un Intercessor = 6 pas de BFS.
# Un mur ferme la colonne 2 SAUF sa dernière ligne : le seul passage interne est tout en bas.
BOARD_COLS, BOARD_ROWS = 6, 8
WALL_COL = 2
WALL_GAP_ROW = BOARD_ROWS - 1          # (2,7) reste libre — passage interne, mais très loin
MOVE_BUDGET = 6                        # M=6" × inches_to_subhex=1

EDGE_START = (1, 1)                    # à une ligne du bord haut
EDGE_DEST = (3, 1)                     # de l'autre côté du mur, à la même hauteur
NEAR_DEST = (1, 4)                     # même côté du mur : déplacement banal, dans le budget

# ─── Géométrie V6 ────────────────────────────────────────────────────────────────────────────
# Un écran ennemi ferme la colonne 12 sur toute la hauteur utile. Le mobile part à sa gauche et
# arrive à sa droite : sans l'exemption 17.01, aucun chemin ; avec elle, 2 pas.
MV_COLS, MV_ROWS = 24, 12
SCREEN_COL = 12
MV_START = (11, 5)
MV_DEST = (13, 5)

OBJECTIVES = ";".join(f"({BOARD_COLS - 1},{r})" for r in range(0, 3))


def _xy(p) -> str:
    return f"({p[0]},{p[1]})"


def _models(unit_id: str, positions) -> str:
    return " ".join(f"{unit_id}#{i}@({c},{r},z0)" for i, (c, r) in enumerate(positions))


def _header(*, cols: int, rows: int, walls: str, units: str) -> str:
    return (
        "=== STEP-BY-STEP ACTION LOG ===\n"
        "================================================================================\n\n"
        "[10:00:00] === EPISODE 1 START ===\n"
        "[10:00:00] Scenario: scenario_bot-01\n"
        "[10:00:00] Rosters: scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)\n"
        "[10:00:00] Opponent: SelfplayBot\n"
        f"[10:00:00] Walls: {walls}\n"
        f"[10:00:00] Objectives: rect b NW:{OBJECTIVES}\n"
        f"[10:00:00] Board: cols={cols} rows={rows} inches_to_subhex=1 hex_radius=2.78 margin=1\n"
        "[10:00:00] Run rules: engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 "
        "metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False "
        "move.thru_friendly=True\n"
        f"{units}"
        "[10:00:00] === ACTIONS START ===\n"
    )


def _stats(tmp_path, header: str, body: str):
    log = tmp_path / "step.log"
    log.write_text(header + body)
    return an.parse_step_log(str(log))


# ═════════════════════════════════════════════════════════════════════════════════════════════
# V7 — le bord du plateau (03.01)
# ═════════════════════════════════════════════════════════════════════════════════════════════

_EDGE_WALLS = ";".join(
    f"({WALL_COL},{r})" for r in range(BOARD_ROWS) if r != WALL_GAP_ROW
)

_EDGE_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    "[10:00:00] Unit 101 (Intercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
)

_EDGE_HEADER = _header(cols=BOARD_COLS, rows=BOARD_ROWS, walls=_EDGE_WALLS, units=_EDGE_UNITS)

_EDGE_DEPLOY = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{_xy(EDGE_START)} DEPLOYED from (-1,-1) to "
    f"{_xy(EDGE_START)} [R:+0.0] [MODELS: {_models('1', [EDGE_START])}] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(5,7) DEPLOYED from (-1,-1) to (5,7) "
    f"[R:+0.0] [MODELS: {_models('101', [(5, 7)])}] [SUCCESS]\n"
)


def _moved(unit_id: str, frm, to) -> str:
    return (
        f"[10:00:02] E1 T2 P1 MOVE : Unit {unit_id}{_xy(frm)} MOVED from {_xy(frm)} to {_xy(to)}"
        f"[R:+0.0] [MODELS: {_models(unit_id, [to])}] [SUCCESS]\n"
    )


def test_premise_the_inside_detour_exists_but_is_out_of_budget():
    """Sans cette prémisse, « 1 erreur » pourrait venir d'un plateau simplement infranchissable.

    Le passage interne (2,7) EXISTE — le chemin est donc possible, seulement trop long. C'est
    exactement le cas que le bord doit rendre visible : le jeu impose le grand détour, l'analyzer
    prenait le raccourci extérieur.
    """
    from ai.analyzer import _bfs_shortest_path_length

    an.set_analyzer_board_dims(BOARD_COLS, BOARD_ROWS)
    walls = {(WALL_COL, r) for r in range(BOARD_ROWS) if r != WALL_GAP_ROW}

    assert _bfs_shortest_path_length(
        *EDGE_START, *EDGE_DEST, MOVE_BUDGET, walls, set(), set()
    ) is None, "dans le budget, la destination doit être injoignable une fois le bord respecté"

    # Le même chemin, budget déplafonné : il existe, il est long. Si ce BFS-ci rendait None, le
    # plateau serait coupé en deux et le test ne parlerait plus du bord.
    long_path = _bfs_shortest_path_length(
        *EDGE_START, *EDGE_DEST, 10 * MOVE_BUDGET, walls, set(), set()
    )
    assert long_path is not None and long_path > MOVE_BUDGET, (
        f"le détour interne doit exister et dépasser le budget, mesuré : {long_path}"
    )


def test_premise_the_outside_detour_was_within_budget():
    """Ce que faisait l'ancien BFS : le contournement par les lignes négatives, dans le budget.

    Mesuré ici en élargissant le plateau vers le haut (les lignes hors plateau deviennent des
    lignes ordinaires) — c'est le chemin que le contrôle acceptait, et la raison pour laquelle il
    ne remontait rien.
    """
    from ai.analyzer import _bfs_shortest_path_length

    # Plateau décalé d'une ligne : (c, r) -> (c, r+2), le mur gardant sa forme. Le contournement
    # « par le haut » est alors INTERNE, donc mesurable, et c'est le même détour.
    an.set_analyzer_board_dims(BOARD_COLS, BOARD_ROWS + 2)
    walls = {(WALL_COL, r + 2) for r in range(BOARD_ROWS) if r != WALL_GAP_ROW}
    shifted = _bfs_shortest_path_length(
        EDGE_START[0], EDGE_START[1] + 2, EDGE_DEST[0], EDGE_DEST[1] + 2,
        MOVE_BUDGET, walls, set(), set(),
    )
    assert shifted is not None and shifted <= MOVE_BUDGET, (
        "le contournement par au-dessus du mur doit tenir dans le budget — sinon le bord n'est "
        f"pas ce qui distingue les deux cas (mesuré : {shifted})"
    )


def test_a_path_that_leaves_the_battlefield_is_counted(tmp_path):
    """Le correctif : ce move n'est légal qu'en sortant du plateau, il est donc compté."""
    stats = _stats(tmp_path, _EDGE_HEADER, _EDGE_DEPLOY + _moved("1", EDGE_START, EDGE_DEST))
    assert stats["move_distance_over_limit"]["move"][1] == 1, (
        "le BFS a de nouveau accepté un chemin passant hors plateau (03.01)"
    )


def test_a_path_that_stays_on_the_battlefield_is_not_counted(tmp_path):
    """Le cas sain, même plateau et même mur : rien ne doit être compté."""
    stats = _stats(tmp_path, _EDGE_HEADER, _EDGE_DEPLOY + _moved("1", EDGE_START, NEAR_DEST))
    assert stats["move_distance_over_limit"]["move"][1] == 0


def test_a_log_without_board_dimensions_is_refused(tmp_path):
    """Même contrat que l'échelle : sans l'entête, on n'invente pas un plateau."""
    log = tmp_path / "step.log"
    log.write_text(
        "=== STEP-BY-STEP ACTION LOG ===\n"
        "[10:00:00] === EPISODE 1 START ===\n"
        "[10:00:00] Board: inches_to_subhex=1 hex_radius=2.78 margin=1\n"
    )
    with pytest.raises(ValueError, match=r"cols"):
        an.parse_step_log(str(log))


# ═════════════════════════════════════════════════════════════════════════════════════════════
# V6 — l'exemption 17.01 MONSTER/VEHICLE
# ═════════════════════════════════════════════════════════════════════════════════════════════

_SCREEN = [(SCREEN_COL, r) for r in range(MV_ROWS)]


def _mv_header(mover_type: str, screen_type: str) -> str:
    units = (
        f"[10:00:00] Unit 1 ({mover_type}) P1: Starting position (-1,-1), HP_MAX=12 base=round/1\n"
        f"[10:00:00] Unit 101 ({screen_type}) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    )
    return _header(cols=MV_COLS, rows=MV_ROWS, walls="none", units=units)


def _mv_deploy() -> str:
    return (
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{_xy(MV_START)} DEPLOYED from (-1,-1) to "
        f"{_xy(MV_START)} [R:+0.0] [MODELS: {_models('1', [MV_START])}] [SUCCESS]\n"
        f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{_xy(_SCREEN[0])} DEPLOYED from (-1,-1) to "
        f"{_xy(_SCREEN[0])} [R:+0.0] [MODELS: {_models('101', _SCREEN)}] [SUCCESS]\n"
    )


def test_premise_the_screen_really_blocks_a_non_mv_mover(tmp_path):
    """Sans ça, le test suivant afficherait 0 parce que rien ne bloque, pas grâce à 17.01.

    Un Intercessor traverse le même écran : l'exemption ne le couvre pas, la faute est comptée.
    """
    stats = _stats(
        tmp_path, _mv_header("Intercessor", "Intercessor"),
        _mv_deploy() + _moved("1", MV_START, MV_DEST),
    )
    assert stats["move_distance_over_limit"]["move"][1] == 1, (
        "l'écran ennemi ne bloque plus personne : la géométrie ne démontre plus rien"
    )


def test_a_vehicle_moves_through_enemy_infantry(tmp_path):
    """17.01 : le Dreadnought traverse l'écran, plus aucune faute."""
    stats = _stats(
        tmp_path, _mv_header("DreadnoughtRedemptor", "Intercessor"),
        _mv_deploy() + _moved("1", MV_START, MV_DEST),
    )
    assert stats["move_distance_over_limit"]["move"][1] == 0, (
        "le mobile MONSTER/VEHICLE est de nouveau bloqué par de l'infanterie (17.01)"
    )


def test_a_vehicle_does_not_move_through_another_vehicle(tmp_path):
    """« excluding other MONSTER/VEHICLE models » : l'exemption s'arrête aux autres M/V."""
    stats = _stats(
        tmp_path, _mv_header("DreadnoughtRedemptor", "DreadnoughtRedemptor"),
        _mv_deploy() + _moved("1", MV_START, MV_DEST),
    )
    assert stats["move_distance_over_limit"]["move"][1] == 1, (
        "un M/V a traversé un autre M/V : l'exclusion de 17.01 n'est plus appliquée"
    )
