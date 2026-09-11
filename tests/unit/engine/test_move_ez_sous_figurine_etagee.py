"""09.05 — la case AU SOL sous une figurine ennemie à l'ÉTAGE n'est pas une destination légale.

DÉFAUT MESURÉ sur le run holdout du 2026-09-11, deux occurrences sur 9 737 mouvements :

    step.log:101523  E10 T4 P1 MOVE : Unit 5(4,52) MOVED from (10,48) to (4,52) [MOVE_TYPE:normal]
    step.log:119644  E4  T5 P1 MOVE : Unit 5(4,52) MOVED from (9,48) to (4,52) [MOVE_TYPE:normal]

Dans les deux cas l'unité 102 (Boyz) a `102#1@(4,52,z3)` — une figurine à l'étage — et des
figurines AU SOL à 2 hex de (4,52), donc à portée d'engagement. Le moteur se contredisait dans le
même tour : quatre lignes plus bas, `Unit 5(4,52) PILED IN … [targets: 102]` puis `FOUGHT`, sans
aucune ligne CHARGE — l'éligibilité ne pouvait venir que de « It is engaged » (12.03).

Les deux règles, lues avant d'écrire :
  09 Movement phase.pdf §09.05 — « NORMAL MOVE … AFTER MOVING: Your unit must be unengaged. »
  03 Moving.pdf §03.04 — « A model's engagement range is the area of the battlefield within 2"
  horizontally and 5" vertically of it. While a friendly model is within engagement range of one
  or more enemy models, those models – and the units they belong to – are engaged with each
  other. »

CAUSE : `dilate_hex_set` exclut par contrat ses cases sources, et la zone d'engagement du move
en était bâtie sans les réunir. L'écart était couvert par l'occupation ennemie tant qu'elle
vetait en 2D ; il ne l'est plus depuis qu'elle se filtre PAR NIVEAU. Le trou fait exactement la
taille des figurines ennemies posées en hauteur.

ISOLATION (ce que le premier test vérifie dans les deux sens) : retirer la seule figurine à
l'étage suffisait à rendre la case interdite — la présence d'un ennemi en hauteur RETIRAIT sa
propre case de la zone.

POURQUOI UN CAS CONSTRUIT, et pas une partie déroulée. `test_move_mask_is_executable.py` joue de
vraies parties AUX DEUX résolutions (fixture `board`, `board/44x60x1` compris) mais ne peut pas
attraper ce défaut : il vérifie « masque ⊆ exécutable », et les deux côtés lisent le MÊME
ensemble — ils étaient faux ensemble, donc d'accord. Et la configuration (ennemi posé à l'étage
au-dessus d'une case de sol atteignable) n'est pas atteinte de façon fiable par des trajectoires
aléatoires : 2 occurrences sur 9 737 mouvements. Même motif, même réponse que
`test_socle_normalized_at_x1.py` — on construit la configuration au lieu de l'espérer.

La géométrie posée ici est celle de la PRODUCTION, vérifiée sur un moteur réel monté avec
`W40K_BOARD_PATH=board/44x60x1` sur `scenario_bot-04.json` : `inches_to_subhex=1`,
plateau 44×60, `engagement_zone=2`, métrique `hex`, socle WarTrakk normalisé en `round`/1.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from engine.hex_utils import hex_distance
from engine.phase_handlers.shared_utils import (
    build_enemy_adjacent_hexes, move_enemy_ez_forbidden_cells,
)
from engine.spatial_relations import unit_within_engagement_zone_footprints
from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

#: Géométrie du run : x1 → socles normalisés `round`/1 et métrique HEX (`_scale_socle`,
#: `geometry_is_hex`), zone d'engagement 2 sous-hexes, gate vertical 5" (03.04).
ISH = 1
EZ = 2
VERTICAL = 5.0
BOARD = (44, 60)

#: Figurines de l'unité 102 au `T4 STATE` qui précède le mouvement fautif — relevées telles
#: quelles dans le journal, y compris `102#1` à l'étage 3.
ENEMY_MODELS: Tuple[Tuple[int, int, int], ...] = (
    (4, 54, 0), (4, 52, 3), (6, 55, 0), (4, 56, 0), (2, 55, 0), (2, 52, 0),
    (1, 53, 0), (4, 50, 0), (6, 51, 0), (8, 55, 0), (7, 56, 0),
)
DESTINATION = (4, 52)          # la case litigieuse : celle de la figurine à l'étage
DEPART = (10, 48)              # d'où partait le WarTrakk

#: Plancher d'étage sous les figurines élevées. Le POLYGONE est exigé par
#: `resolve_model_floor_level` pour un socle rond (confinement euclidien) : décrit par ses seuls
#: `hexes`, il renverrait toute figurine ronde au sol et le test ne mesurerait rien.
_FLOOR_HEXES = [[c, r] for c in range(1, 10) for r in range(47, 58)]
_FLOOR_POLY = [[1, 47], [9, 47], [9, 57], [1, 57]]
#: 1,5" par niveau : `102#1` est donc à 4,5" du sol, SOUS le gate vertical de 5". L'engagement
#: mesuré ne dépend pourtant pas de cette valeur — cf. `test_isolation_...`, où les figurines au
#: sol à 2 hex suffisent à elles seules.
_TERRAIN = [{
    "id": "ruine", "polygon_vertices": _FLOOR_POLY, "hexes": _FLOOR_HEXES,
    "floors": [
        {"level": lv, "height_inches": 1.5 * lv,
         "hexes": _FLOOR_HEXES, "polygon_vertices": _FLOOR_POLY}
        for lv in (1, 2, 3)
    ],
}]


def _state(mover_pos: Tuple[int, int], enemy_models=ENEMY_MODELS) -> Dict[str, Any]:
    """Mobile joueur 1 en `mover_pos`, escouade ennemie joueur 2 telle que le journal la donne."""
    mover = synthetic_unit(
        "5", 1, [{"col": mover_pos[0], "row": mover_pos[1], "level": 0}], MOVE=12
    )
    enemy = synthetic_unit(
        "102", 2, [{"col": c, "row": r, "level": lv} for c, r, lv in enemy_models]
    )
    return synthetic_state(
        [mover, enemy], phase="move",
        game_rules={"engagement_zone": EZ, "engagement_zone_vertical": VERTICAL},
        inches_to_subhex=ISH, board_cols=BOARD[0], board_rows=BOARD[1],
        terrain_areas=_TERRAIN,
    )


def _engaged_at(cell: Tuple[int, int], enemy_models=ENEMY_MODELS) -> bool:
    """Verdict de la phase de COMBAT pour le mobile posé sur `cell` (primitive canonique 03.04)."""
    gs = _state(cell, enemy_models)
    return unit_within_engagement_zone_footprints(
        gs, gs["unit_by_id"]["5"], EZ, None, VERTICAL
    )


def test_la_case_sous_une_figurine_etagee_est_interdite_au_move():
    """La case de l'occurrence du journal : engagée au combat, donc interdite au mouvement.

    ROUGE sans le correctif : `(4,52)` est absente de la zone (case source retirée par
    `dilate_hex_set`) alors que le prédicat de combat rend `True` — le masque offrait la
    destination que 09.05 interdit.
    """
    gs = _state(DEPART)
    zone = build_enemy_adjacent_hexes(gs, 1)
    assert _engaged_at(DESTINATION), (
        "prémisse du test : le mobile posé en (4,52) DOIT être engagé (figurines ennemies au "
        "sol à 2 hex, plus une à l'étage sur la case même)"
    )
    assert DESTINATION in zone, (
        "une case engagée au combat ne peut pas être offerte au mouvement (09.05)"
    )
    # Le prédicat que lit RÉELLEMENT la validation d'un plan de move (`validate_move_plan` →
    # `build_move_blocked_cells_by_level`) : sans lui, le test verrouillerait un ensemble que le
    # chemin de production ne consulterait pas.
    assert DESTINATION in move_enemy_ez_forbidden_cells(gs, 1, "round", 1, 0), (
        "le prédicat de cellule du move doit refuser l'ancre, pas seulement l'ensemble brut"
    )


def test_isolation_la_figurine_etagee_retirait_sa_propre_case():
    """Sans la figurine à l'étage, la case était DÉJÀ interdite — c'est elle qui ouvrait le trou.

    C'est la mesure qui nomme la cause : l'engagement en (4,52) vient des figurines AU SOL à
    2 hex, indépendamment de toute hauteur de plancher ; seule la présence d'un ennemi SUR la
    case la faisait disparaître de la zone.
    """
    au_sol = tuple(m for m in ENEMY_MODELS if (m[0], m[1]) != DESTINATION)
    assert _engaged_at(DESTINATION, au_sol), (
        "les figurines au sol à 2 hex suffisent à engager : la conclusion ne dépend d'aucune "
        "hypothèse sur la hauteur des étages"
    )
    gs_sans = _state(DEPART, au_sol)
    assert DESTINATION in build_enemy_adjacent_hexes(gs_sans, 1)


def test_aucune_case_engagee_n_est_offerte_au_move():
    """Invariant, pas anecdote : sur tout le voisinage de l'escouade ennemie, « engagé au
    combat » implique « interdit au move ». L'inverse n'est PAS exigé — la zone du move est 2D
    et reste donc plus restrictive à étages, écart préexistant et assumé."""
    gs = _state(DEPART)
    zone = build_enemy_adjacent_hexes(gs, 1)
    cols = range(0, 12)
    rows = range(46, 60)
    manquantes = [
        (c, r) for c in cols for r in rows
        if min(hex_distance(c, r, ec, er) for ec, er, _ in ENEMY_MODELS) <= EZ
        and (c, r) not in zone
    ]
    assert not manquantes, (
        f"cases engagées et pourtant offertes au mouvement : {sorted(manquantes)}"
    )


def test_la_zone_ne_s_elargit_pas_hors_portee():
    """Garde-fou de sens : le correctif RESTREINT, il n'invente pas de zone. Aucune case au-delà
    de `engagement_zone` d'une figurine ennemie ne doit entrer dans l'ensemble."""
    gs = _state(DEPART)
    zone = build_enemy_adjacent_hexes(gs, 1)
    trop_loin = [
        cell for cell in zone
        if min(hex_distance(cell[0], cell[1], ec, er) for ec, er, _ in ENEMY_MODELS) > EZ
    ]
    assert not trop_loin, f"cases hors portée entrées dans la zone : {sorted(trop_loin)[:10]}"
