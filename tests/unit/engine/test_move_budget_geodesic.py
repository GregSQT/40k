"""Budget de move en distance de CHEMIN (règle 03), pas à vol d'oiseau.

Bug corrigé : le moteur validait le budget par figurine avec ``calculate_hex_distance`` (ligne
droite cube). ``build_rigid_plan`` translatant tout le bloc du même vecteur, chaque figurine a la
même distance à vol d'oiseau que l'ancre — donc le check passait toujours. Mais une figurine
partant derrière un mur a un trajet LÉGAL (contournant le mur, règle 03) qui peut dépasser son
budget : elle était placée illégalement (analyzer : « Advance/Move path blocked (BFS) »).

Fix (deux côtés de l'invariant « masque ⊆ exécutable ») :
  - ``explain_move_plan_rejection`` borne chaque figurine non-FLY par un BFS géodésique (sol) ;
  - ``erode_move_pool_by_squad_block`` retire du masque les ancres où une sœur dépasse ce budget.

Géométrie : escouade "1" = ancre (5,10) + sœur (10,10). Mur vertical colonne 11, rangées 6..14.
Pour l'ancre en (7,10), la sœur translate en (12,10) : distance à vol d'oiseau = 2 (<= budget 3),
mais le seul trajet légal contourne le mur (> 3 pas). Le check ligne-droite historique passait ;
le check géodésique rejette.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple
from unittest.mock import patch

import pytest

from engine.phase_handlers.shared_utils import (
    _squad_is_in_enemy_er,
    build_rigid_plan,
    build_squad_move_cell_map,
    calculate_hex_distance,
    erode_move_pool_by_squad_block,
    explain_move_plan_rejection,
    move_plan_path_distances,
)
from tests._state_invariants import turn_state_invariants, unit_invariants

WALL = {(11, r) for r in range(6, 15)}
ANCHOR_DEST = (7, 10)
BUDGET = 3  # MOVE=3, inches_to_subhex=1 → budget subhex = 3


def _gs(wall: Iterable[Tuple[int, int]], *, fly: bool = False) -> Dict[str, Any]:
    keywords = [{"keywordId": "fly"}] if fly else []
    unit = {**unit_invariants(),
        "id": 1, "player": 1, "col": 5, "row": 10, "MOVE": BUDGET,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": keywords,
    }
    models_cache = {
        "1#0": {"col": 5, "row": 10, "level": 0, "player": 1, "squad_id": "1", "HP_CUR": 1,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0},
        "1#1": {"col": 10, "row": 10, "level": 0, "player": 1, "squad_id": "1", "HP_CUR": 1,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0},
    }
    return {**turn_state_invariants(),
        "models_cache": models_cache,
        "squad_models": {"1": ["1#0", "1#1"]},
        "units_cache": {"1": {"col": 5, "row": 10, "player": 1, "occupied_hexes": set(),
                              "BASE_SHAPE": "round", "BASE_SIZE": 1}},
        "units": [unit],
        "unit_by_id": {"1": unit},
        "board_cols": 44, "board_rows": 60,
        "wall_hexes": set(wall),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": 1},
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
        },
        "phase": "move",
        "gym_training_mode": True,  # → métrique hex (move_gym)
        "inches_to_subhex": 1,
        "units_took_to_skies": set(),
        "terrain_areas": [],
    }


def _rigid_plan(col: int, row: int, gs: Dict[str, Any]) -> List[Tuple[str, int, int, int]]:
    """Plan rigide de l'escouade '1' — ``None`` signifierait une escouade sans figurine vivante,
    ce qu'aucune fixture de ce module ne construit : on échoue au lieu de le propager."""
    plan = build_rigid_plan(col, row, "1", gs)
    assert plan is not None, "escouade '1' sans figurine vivante"
    return plan


def _sister_dest(gs: Dict[str, Any]) -> Tuple[int, int]:
    plan = _rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], gs)
    sister = next(p for p in plan if p[0] == "1#1")
    return int(sister[1]), int(sister[2])


def _add_other_squad(gs: Dict[str, Any], cells) -> None:
    """Ajoute une escouade adverse '2' occupant `cells` (au niveau 0), lue par
    build_occupied_positions_set (models_cache + squad_models)."""
    cells = list(cells)
    mids = []
    for i, (col, row) in enumerate(cells):
        mid = f"2#{i}"
        mids.append(mid)
        gs["models_cache"][mid] = {
            "col": col, "row": row, "level": 0, "player": 2, "squad_id": "2", "HP_CUR": 1,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        }
    gs["squad_models"]["2"] = mids
    gs["units_cache"]["2"] = {
        "col": cells[0][0], "row": cells[0][1], "player": 2,
        "occupied_hexes": set(cells), "BASE_SHAPE": "round", "BASE_SIZE": 1,
        # Centres PAR FIGURINE : c'est ce que lit la mesure d'engagement euclidienne
        # (`socle_from_cache_entry`) ; sans eux elle retombe sur la seule ancre de l'escouade.
        "occupied_hexes_by_model": {mid: cell for mid, cell in zip(mids, cells)},
    }


def test_advance_block_overlapping_another_squad_is_eroded_not_crashed():
    """Régression §0.18 (crash « incohérence masque/exécution » sur un ADVANCE) : une ancre
    ADVANCE dont le BLOC rigide fait chevaucher une figurine avec une AUTRE escouade DOIT être
    retirée du pool par l'érosion — pas offerte au masque puis rejetée à l'exécution.

    Géométrie : escouade '1' = ancre (5,10) + sœur (10,10) (offset +5 col). Escouade adverse '2'
    en (18,10). Pour l'ancre candidate (13,10) — coût cube 8 > M=6 → régime ADVANCE — la sœur
    translate en (18,10), sur l'escouade '2'. L'érosion au budget advance doit dropper (13,10).
    """
    ADV_BUDGET = 12  # M=6 + jet 6 (subhex, inches_to_subhex=1)
    # Pool d'ancre = ligne row 10, coût = distance cube depuis l'ancre (5,10) — cellules advance incluses.
    pool = {(c, 10): float(abs(c - 5)) for c in range(5, 18) if abs(c - 5) <= ADV_BUDGET}

    gs_free = _gs(set())
    kept_free = erode_move_pool_by_squad_block(gs_free, "1", dict(pool), move_budget=ADV_BUDGET)
    assert (13, 10) in kept_free, "sans obstacle, l'ancre advance (13,10) est légale (sœur en (18,10))"

    gs_occ = _gs(set())
    _add_other_squad(gs_occ, [(18, 10)])
    kept_occ = erode_move_pool_by_squad_block(gs_occ, "1", dict(pool), move_budget=ADV_BUDGET)
    assert (13, 10) not in kept_occ, (
        "ancre advance (13,10) conservée alors que la sœur 1#1 chevauche l'escouade '2' en (18,10) "
        "— le masque l'offrirait puis execute_squad_move lèverait « incohérence masque/exécution »"
    )
    # Et l'invariant : toute ancre conservée produit un plan que validate_move_plan accepte.
    for (cc, rr) in kept_occ:
        plan = _rigid_plan(cc, rr, gs_occ)
        reason = explain_move_plan_rejection(
            plan, gs_occ, {"budget_per_model": ADV_BUDGET, "require_coherency": False},
        )
        assert reason is None, f"ancre {(cc, rr)} conservée mais rejetée : {reason}"


def test_straight_line_within_budget_but_path_exceeds_is_rejected():
    """La sœur a une distance à vol d'oiseau <= budget mais un trajet légal > budget → rejet."""
    gs = _gs(WALL)
    sc, sr = _sister_dest(gs)
    # Garantit qu'on exerce bien le bug : l'ancien check ligne-droite AURAIT accepté.
    assert calculate_hex_distance(10, 10, sc, sr) <= BUDGET
    plan = _rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], gs)
    reason = explain_move_plan_rejection(
        plan, gs, {"budget_per_model": BUDGET, "require_coherency": False}
    )
    assert reason is not None and "injoignable en trajet" in reason, reason


def test_same_plan_without_wall_is_accepted():
    """Sans mur, le trajet == la ligne droite → le plan passe (pas de sur-rejet)."""
    gs = _gs(set())
    plan = _rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], gs)
    reason = explain_move_plan_rejection(
        plan, gs, {"budget_per_model": BUDGET, "require_coherency": False}
    )
    assert reason is None, reason


def test_fly_squad_uses_straight_line_even_with_wall():
    """FLY (traversée libre 21.03) : le budget reste à vol d'oiseau, le mur n'ajoute rien."""
    gs = _gs(WALL, fly=True)
    plan = _rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], gs)
    # allow_walls pour que la sœur puisse finir sur/au-delà du mur (FLY franchit) : on isole le budget.
    reason = explain_move_plan_rejection(
        plan, gs, {"budget_per_model": BUDGET, "require_coherency": False, "allow_walls": True},
    )
    assert reason is None, reason


def test_erosion_drops_anchor_whose_sister_path_exceeds_budget():
    """L'érosion retire l'ancre (7,10) : la sœur ne peut pas atteindre (12,10) en <= budget pas."""
    pool = {(c, 10): float(BUDGET) for c in range(5, 12)}
    kept_wall = erode_move_pool_by_squad_block(_gs(WALL), "1", dict(pool))
    kept_open = erode_move_pool_by_squad_block(_gs(set()), "1", dict(pool))
    assert ANCHOR_DEST not in kept_wall, (
        "ancre conservée alors que la sœur dépasse son budget de chemin — le masque offrirait "
        "une destination que explain_move_plan_rejection rejette (incohérence masque/exécution)"
    )
    assert ANCHOR_DEST in kept_open, "sur-filtrage : sans mur cette ancre est parfaitement légale"


def test_erosion_and_validation_agree_on_every_pool_cell():
    """Invariant masque ⊆ exécutable : toute cellule conservée par l'érosion produit un plan
    accepté par la validation (au budget que l'exécution appliquera)."""
    gs = _gs(WALL)
    pool = {(c, 10): float(BUDGET) for c in range(4, 12)}
    kept = erode_move_pool_by_squad_block(gs, "1", dict(pool))
    for (cc, rr) in kept:
        plan = _rigid_plan(cc, rr, gs)
        reason = explain_move_plan_rejection(
            plan, gs, {"budget_per_model": BUDGET, "require_coherency": False}
        )
        assert reason is None, f"ancre {(cc, rr)} conservée mais rejetée : {reason}"


# ─────────────────────────────────────────────────────────────────────────────
# MÉTRIQUE EUCLIDIENNE (PvP) — l'autre moitié de l'invariant
# ─────────────────────────────────────────────────────────────────────────────

# `distance_metric.move` vaut `euclidean` dans la config réelle : c'est le mode de TOUT le PvP.
# Les tests ci-dessus tournent en `hex` (donc `geodesic`). En euclidien, la validation ne bornait
# QUE par la ligne droite cube, au motif que le pool par-figurine
# (`movement_build_model_destinations_pool`) bornait déjà — or ce pool n'est construit que pour la
# figurine SÉLECTIONNÉE, jamais pour les sœurs translatées par le move d'escouade rigide. Une sœur
# posée derrière un obstacle passait donc la validation ET le voile rouge du preview, puis
# `commit_move` levait « injoignable en chemin … Incohérence validation/mesure » (RuntimeError
# non rattrapable, plan déjà accepté par l'UI).


def _euclidean() -> Any:
    return patch(
        "engine.phase_handlers.movement_handlers._move_distance_metric", return_value="euclidean"
    )


def test_euclidean_straight_line_within_budget_but_path_exceeds_is_rejected():
    """PvP : sœur à vol d'oiseau <= budget, trajet any-angle > budget → REJET (plus de crash)."""
    with _euclidean():
        gs = _gs(WALL)
        sc, sr = _sister_dest(gs)
        # Garantit qu'on exerce bien le bug : le check ligne-droite historique AURAIT accepté.
        assert calculate_hex_distance(10, 10, sc, sr) <= BUDGET
        plan = _rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], gs)
        reason = explain_move_plan_rejection(
            plan, gs, {"budget_per_model": BUDGET, "require_coherency": False}
        )
        assert reason is not None and "injoignable en trajet" in reason, reason


def test_euclidean_same_plan_without_wall_is_accepted():
    """Contre-épreuve : le refus vient bien du mur, pas de la métrique euclidienne."""
    with _euclidean():
        gs = _gs(set())
        plan = _rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], gs)
        reason = explain_move_plan_rejection(
            plan, gs, {"budget_per_model": BUDGET, "require_coherency": False}
        )
        assert reason is None, reason


def test_euclidean_validation_and_measure_agree_on_the_same_plan():
    """L'invariant lui-même : ce que la validation ACCEPTE, la mesure du commit sait le MESURER.

    Le plan rigide sur mur est exactement celui qui levait au commit. On vérifie les deux côtés
    sur le MÊME plan : la validation le refuse, et la mesure (qui, elle, n'a jamais menti)
    confirme l'injoignabilité en levant. Tant que les deux côtés s'accordent, le refus arrive
    dans l'UI (voile rouge) au lieu d'une RuntimeError après acceptation.
    """
    with _euclidean():
        gs = _gs(WALL)
        plan = _rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], gs)
        assert explain_move_plan_rejection(
            plan, gs, {"budget_per_model": BUDGET, "require_coherency": False}
        ) is not None
        with pytest.raises(RuntimeError, match="Incoherence validation/mesure"):
            move_plan_path_distances(plan, gs, "normal")

        gs_open = _gs(set())
        plan_open = _rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], gs_open)
        assert explain_move_plan_rejection(
            plan_open, gs_open, {"budget_per_model": BUDGET, "require_coherency": False}
        ) is None
        assert move_plan_path_distances(plan_open, gs_open, "normal"), "mesure vide"


def test_euclidean_erosion_and_validation_agree_on_every_pool_cell():
    """JUMEAU de `test_erosion_and_validation_agree_on_every_pool_cell`, côté euclidien.

    L'érosion excluait la métrique euclidienne (« traité comme cube-exact »), ce qui n'était vrai
    que tant que la validation s'accordait le même raccourci ligne droite. La validation bornant
    maintenant le TRAJET, une ancre conservée dont une sœur est injoignable ferait lever
    `execute_squad_move` (« incohérence masque/exécution », ValueError qui tue le run).
    """
    with _euclidean():
        gs = _gs(WALL)
        pool = {(c, 10): float(BUDGET) for c in range(4, 12)}
        kept = erode_move_pool_by_squad_block(gs, "1", dict(pool))
        for (cc, rr) in kept:
            plan = _rigid_plan(cc, rr, gs)
            reason = explain_move_plan_rejection(
                plan, gs, {"budget_per_model": BUDGET, "require_coherency": False}
            )
            assert reason is None, f"ancre {(cc, rr)} conservée mais rejetée : {reason}"
        # VERT VACANT : une érosion qui viderait tout satisferait la boucle ci-dessus sans rien
        # prouver. L'ancre (7,10) est celle dont la sœur ne passe pas ; les ancres dégagées, elles,
        # DOIVENT survivre.
        assert ANCHOR_DEST not in kept, "l'ancre dont la sœur est injoignable doit être érodée"
        assert (5, 10) in kept, "sur-érosion : l'ancre d'origine est trivialement légale"


def test_euclidean_erosion_drops_anchor_whose_sister_path_exceeds_budget():
    """Jumeau euclidien de `test_erosion_drops_anchor_whose_sister_path_exceeds_budget` : c'est
    bien le MUR qui retire l'ancre (7,10), pas un sur-filtrage de la métrique."""
    pool = {(c, 10): float(BUDGET) for c in range(5, 12)}
    with _euclidean():
        kept_wall = erode_move_pool_by_squad_block(_gs(WALL), "1", dict(pool))
        kept_open = erode_move_pool_by_squad_block(_gs(set()), "1", dict(pool))
    assert ANCHOR_DEST not in kept_wall, (
        "ancre conservée alors que la sœur ne peut pas l'atteindre en trajet any-angle — le masque "
        "l'offrirait puis execute_squad_move lèverait « incohérence masque/exécution »"
    )
    assert ANCHOR_DEST in kept_open, "sur-filtrage : sans mur cette ancre est parfaitement légale"


# ─────────────────────────────────────────────────────────────────────────────
# EXEMPTIONS DU TRAJET — ce que le pool autorise, la validation doit l'autoriser
# ─────────────────────────────────────────────────────────────────────────────


def test_desperate_escape_crosses_enemy_models():
    """Desperate Escape (09.07) : une escouade battle-shocked qui fuit TRAVERSE les ennemis.

    Le pool par-figurine retire les ennemis de ses obstacles dans ce cas
    (`movement_build_model_destinations_pool`, `not (desperate_escape or thru_enemy)`). La borne de
    trajet de la validation lit le MÊME set (`build_move_transit_blocked`) : sans l'exemption, elle
    refuse en voile rouge une destination que le pool vient d'offrir — et le masque gym lève
    « incohérence masque/exécution ».
    """
    ENEMY_LINE = [(11, r) for r in range(6, 15)]

    def _state(*, shocked: bool) -> Dict[str, Any]:
        gs = _gs(set())
        _add_other_squad(gs, ENEMY_LINE)
        gs["unit_by_id"]["1"]["battle_shocked"] = shocked
        # L'engagement se mesure sur les EMPREINTES (unit_within_engagement_zone_footprints) :
        # sans les hexes occupés, l'escouade n'est engagée avec personne et 09.07 ne s'applique pas.
        gs["units_cache"]["1"]["occupied_hexes"] = {(5, 10), (10, 10)}
        gs["units_cache"]["1"]["occupied_hexes_by_model"] = {"1#0": (5, 10), "1#1": (10, 10)}
        return gs

    plan = _rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], _state(shocked=False))
    # Non shocked : les figurines ennemies bloquent le trajet, la sœur ne passe pas (contrôle).
    assert explain_move_plan_rejection(
        plan, _state(shocked=False), {"budget_per_model": BUDGET, "require_coherency": False}
    ) is not None, "sans Desperate Escape, la ligne ennemie DOIT bloquer (sinon le test ne prouve rien)"
    # Battle-shocked ET dans l'ER ennemie : 09.07 autorise la traversée.
    gs_de = _state(shocked=True)
    assert _squad_is_in_enemy_er(gs_de, "1"), "fixture : l'escouade doit être engagée pour que 09.07 s'applique"
    assert explain_move_plan_rejection(
        plan, gs_de, {"budget_per_model": BUDGET, "require_coherency": False}
    ) is None, "Desperate Escape (09.07) : la traversée des figurines ennemies est autorisée"


def test_desperate_escape_does_not_leak_into_pile_in():
    """09.07 est un mode du FALL-BACK MOVE : l'exemption ne vaut QUE dans la phase de mouvement.

    Le même prédicat de transit borne le pile-in et la consolidation (12.03), et une escouade qui
    pile-in est TOUJOURS dans l'ER ennemie. Sans garde de phase, toute escouade battle-shocked
    traverserait les figurines ennemies en phase de combat — 12.03 ne le permet nulle part.
    """
    from engine.phase_handlers.shared_utils import build_move_transit_blocked

    ENEMY_LINE = {(11, r) for r in range(6, 15)}
    gs = _gs(set())
    _add_other_squad(gs, sorted(ENEMY_LINE))
    gs["unit_by_id"]["1"]["battle_shocked"] = True
    gs["units_cache"]["1"]["occupied_hexes"] = {(5, 10), (10, 10)}
    gs["units_cache"]["1"]["occupied_hexes_by_model"] = {"1#0": (5, 10), "1#1": (10, 10)}

    gs["phase"] = "move"
    assert not (build_move_transit_blocked(gs, "1", 1, 0) & ENEMY_LINE), (
        "phase de mouvement + battle-shocked + engagée = fall-back Desperate Escape (09.07)"
    )
    gs["phase"] = "fight"
    assert build_move_transit_blocked(gs, "1", 1, 0) & ENEMY_LINE == ENEMY_LINE, (
        "12.03 (pile-in / consolidation) n'a AUCUNE exemption de traversée : les ennemis bloquent"
    )


def test_transit_cache_invalidates_when_battle_shock_flips():
    """`battle_shocked` bascule SANS qu'une figurine bouge (01.07 / force_battle_shock).

    Le transit est mémoïsé par un fingerprint d'état : s'il ignore ce drapeau, la validation
    continue de lire le transit d'AVANT le test de commandement pendant que le pool par-figurine,
    lui, recalcule — la divergence masque/exécution que ce cache existe pour ne pas créer.
    """
    from engine.phase_handlers.shared_utils import build_move_transit_blocked

    ENEMY_LINE = {(11, r) for r in range(6, 15)}
    gs = _gs(set())
    _add_other_squad(gs, sorted(ENEMY_LINE))
    gs["units_cache"]["1"]["occupied_hexes"] = {(5, 10), (10, 10)}
    gs["units_cache"]["1"]["occupied_hexes_by_model"] = {"1#0": (5, 10), "1#1": (10, 10)}

    gs["unit_by_id"]["1"]["battle_shocked"] = False
    assert build_move_transit_blocked(gs, "1", 1, 0) & ENEMY_LINE == ENEMY_LINE  # chauffe le cache
    gs["unit_by_id"]["1"]["battle_shocked"] = True  # aucune figurine n'a bougé
    assert not (build_move_transit_blocked(gs, "1", 1, 0) & ENEMY_LINE), (
        "transit périmé servi après le test de commandement (fingerprint aveugle à battle_shocked)"
    )


# Socle OVAL : l'empreinte orientée décide du passage. Couloir vertical de 3 colonnes (9,10,11)
# dans un mur horizontal — l'ovale « debout » (orientation 3, 3 colonnes de large) passe, l'ovale
# « couché » (orientation 0, 5 colonnes) ne passe pas. Géométrie vérifiée dans les deux sens
# ci-dessous : sans ça, un test qui ne discriminerait rien afficherait « tout va bien ».
OVAL_WALL = {(c, 25) for c in range(0, 44) if c not in (9, 10, 11)}
OVAL_BUDGET = 20


def _oval_state(committed_orientation: int) -> Dict[str, Any]:
    unit = {**unit_invariants(),
        "id": 1, "player": 1, "col": 10, "row": 20, "MOVE": OVAL_BUDGET, "HP_CUR": 1,
        "BASE_SIZE": [6, 3], "BASE_SHAPE": "oval", "UNIT_KEYWORDS": [],
    }
    return {**turn_state_invariants(),
        "models_cache": {
            "1#0": {"col": 10, "row": 20, "level": 0, "player": 1, "squad_id": "1", "HP_CUR": 1,
                    "BASE_SHAPE": "oval", "BASE_SIZE": [6, 3],
                    "orientation": committed_orientation},
        },
        "squad_models": {"1": ["1#0"]},
        "units_cache": {"1": {"col": 10, "row": 20, "player": 1, "occupied_hexes": set(),
                              "BASE_SHAPE": "oval", "BASE_SIZE": [6, 3]}},
        "units": [unit],
        "unit_by_id": {"1": unit},
        "board_cols": 44, "board_rows": 60,
        "wall_hexes": set(OVAL_WALL),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": 1},
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
        },
        "phase": "move",
        # x5 : à x1 la géométrie est hex quoi qu'en dise la métrique (geometry_is_hex), et un socle
        # oval y est normalisé en round/1 — l'orientation n'aurait alors aucun effet.
        "inches_to_subhex": 5,
        "units_took_to_skies": set(),
        "terrain_areas": [],
    }


def _oval_verdict(committed: int, planned: Optional[int]) -> Optional[str]:
    entry = ("1#0", 10, 30, 0) if planned is None else ("1#0", 10, 30, 0, planned)
    with _euclidean():
        return explain_move_plan_rejection(
            [entry], _oval_state(committed),
            {"budget_per_model": OVAL_BUDGET, "require_coherency": False},
        )


def test_oval_reach_follows_the_planned_orientation_not_the_committed_one():
    """Pivot molette non committé : la validation borne le trajet à l'orientation du PLAN.

    Le pool par-figurine construit son champ avec l'orientation EN COURS (`mover_orient`) ; la
    validation lisait celle de `models_cache`. Un socle non rond pivoté pour enfiler un passage
    étroit voyait donc sa case refusée par le voile rouge alors que le pool venait de l'offrir.
    """
    # La géométrie discrimine réellement (anti « vert vacant ») : même socle, même destination,
    # seule l'orientation change le verdict.
    assert _oval_verdict(committed=3, planned=0) is not None, "ovale couché : le couloir est trop étroit"
    assert _oval_verdict(committed=0, planned=3) is None, "ovale debout : le couloir passe"
    # Et l'orientation du plan prime bien sur celle du models_cache, dans les deux sens.
    assert _oval_verdict(committed=0, planned=0) is not None
    assert _oval_verdict(committed=3, planned=3) is None
    # Orientation absente du plan (None = inchangée) → celle de la figurine, comme avant.
    assert _oval_verdict(committed=3, planned=None) is None
    assert _oval_verdict(committed=0, planned=None) is not None


def _gym_state_for_cellmap() -> Dict[str, Any]:
    """État gym complet pour build_squad_move_cell_map : squad '1' mono-fig en (10,10), MOVE 3."""
    unit = {**unit_invariants(),
        "id": 1, "player": 1, "col": 10, "row": 10, "MOVE": 3, "HP_CUR": 1,
        "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [],
    }
    return {**turn_state_invariants(),
        "models_cache": {
            "1#0": {"col": 10, "row": 10, "level": 0, "player": 1, "squad_id": "1",
                    "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0},
        },
        "squad_models": {"1": ["1#0"]},
        "units_cache": {"1": {"col": 10, "row": 10, "player": 1, "HP_CUR": 1,
                              "occupied_hexes": set(), "BASE_SHAPE": "round", "BASE_SIZE": 1}},
        "units": [unit],
        "unit_by_id": {"1": unit},
        "board_cols": 44, "board_rows": 60,
        "current_player": 1,
        "wall_hexes": set(),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": 1},
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
        },
        "phase": "move",
        "gym_training_mode": True,
        "inches_to_subhex": 1,
        "units_took_to_skies": set(),
        "terrain_areas": [],
        "units_moved": set(),
        "_unit_move_version": 0,
    }


def _occupy_cell(gs: Dict[str, Any], col: int, row: int) -> None:
    """Pose une escouade adverse '2' en (col,row) SANS toucher `_unit_move_version` — reproduit
    le bypass qui a causé la régression §0.18 (occupation changée, compteur non bumpé)."""
    gs["models_cache"]["2#0"] = {
        "col": col, "row": row, "level": 0, "player": 2, "squad_id": "2", "HP_CUR": 1,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
    }
    gs["squad_models"]["2"] = ["2#0"]
    gs["units_cache"]["2"] = {
        "col": col, "row": row, "player": 2, "HP_CUR": 1,
        "occupied_hexes": {(col, row)}, "BASE_SHAPE": "round", "BASE_SIZE": 1,
    }


def test_cell_map_cache_invalidates_on_occupation_change_without_version_bump():
    """RÉGRESSION §0.18 : le cache de build_squad_move_cell_map NE DOIT PAS servir une carte
    périmée quand l'occupation change, même si `_unit_move_version` n'est pas bumpé. Sinon le
    masque offre une cellule d'ancre déjà occupée → crash « incohérence masque/exécution ».

    La clé de cache étant un fingerprint LU de l'occupation réelle (pas le compteur), le simple
    ajout d'une escouade sur une cellule offerte invalide l'entrée."""
    gs = _gym_state_for_cellmap()
    first = build_squad_move_cell_map(gs, "1", advance_roll=None)
    offered = {cell for (cell, _cost) in first.values()}
    assert offered, "le pool devrait offrir des cellules"
    # Choisit une cellule offerte et l'occupe (sans bumper la version).
    target = sorted(offered)[0]
    _occupy_cell(gs, target[0], target[1])

    second = build_squad_move_cell_map(gs, "1", advance_roll=None)
    offered2 = {cell for (cell, _cost) in second.values()}
    assert target not in offered2, (
        f"cellule occupée {target} encore offerte après changement d'occupation — cache périmé "
        f"(la clé fingerprint doit capturer l'occupation, indépendamment de _unit_move_version)"
    )


def test_cell_map_cache_serves_identical_result_when_state_unchanged():
    """Non-régression perf : à état inchangé, le 2e appel renvoie l'objet mémoïsé (même identité)."""
    gs = _gym_state_for_cellmap()
    first = build_squad_move_cell_map(gs, "1", advance_roll=None)
    second = build_squad_move_cell_map(gs, "1", advance_roll=None)
    assert first is second, "état inchangé → la carte doit être servie depuis le cache (même objet)"
