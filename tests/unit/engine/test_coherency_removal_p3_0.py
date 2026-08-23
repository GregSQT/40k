"""P3-0 — Choix de retrait figurine hors cohérence (03.03).

Verrous :
  T1 — layout : TOTAL_ACTION_SIZE=1379, COHERENCY immédiatement après FIGHT_WEAPON.
  T2 — muet/non-muet : queue armée pour sièges actifs, auto-retrait pour sièges muets.
  T3 — masque : seuls les slots COHERENCY sont ouverts quand pending_coherency_removal est armé.
  T4 — décodeur : slot i → alive[i] (invariant D1 côté figurines).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.action_decoder import ActionDecoder
from engine.macro_intents import (
    COHERENCY_SLOT_BASE,
    COHERENCY_SLOT_COUNT,
    FIGHT_WEAPON_SLOT_BASE,
    FIGHT_WEAPON_SLOT_COUNT,
    TOTAL_ACTION_SIZE,
)
from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import (
    _coherency_alive,
    _coherency_seat_is_muet,
    arm_next_coherency_pending,
    end_of_turn_regain_coherency_all_squads,
    validate_squad_coherency,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _model(col: int, row: int, player: int = 1, squad_id: str = "1") -> Dict[str, Any]:
    """Modèle minimal accepté par _squad_models_for_observation."""
    return {
        "col": col, "row": row, "level": 0, "player": player,
        "squad_id": squad_id, "HP_CUR": 1, "HP_MAX": 1,
        "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
    }


def _gs(positions: List[tuple], squad_id: str = "1", player: int = 1) -> Dict[str, Any]:
    """gs minimal pour cohérence + destruction de figurines."""
    mids = [f"{squad_id}#{i}" for i in range(len(positions))]
    models_cache = {mid: _model(*pos, player=player, squad_id=squad_id)
                    for mid, pos in zip(mids, positions)}
    return {
        "models_cache": models_cache,
        "squad_models": {squad_id: list(mids)},
        "units_cache": {
            squad_id: {
                "col": int(positions[0][0]), "row": int(positions[0][1]), "player": player,
                "HP_CUR": len(positions), "BASE_SHAPE": "round", "BASE_SIZE": 1,
                "orientation": 0, "occupied_hexes": set(), "occupied_hexes_by_model": {},
            }
        },
        "board_cols": 44,
        "board_rows": 60,
        "wall_hexes": set(),
        "_unit_move_version": 0,
        "config": {"game_rules": {
            "unit_model_cohesion_range": 2,
            "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1,
            "cohesion_distance_mode": "euclidean",
            "engagement_zone": 1,
        }},
        "action_logs": [],
        "action_log_seq": 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# T1 — Layout de l'espace d'action
# ─────────────────────────────────────────────────────────────────────────────

def test_total_action_size_is_1379():
    """VERROU : TOTAL_ACTION_SIZE = 1379 depuis P3-0. Tout retrain avec un ancien modèle est
    invalide. Ce test DOIT être rouge si P3-0 est annulé (COHERENCY_SLOT_COUNT soustrait)."""
    assert TOTAL_ACTION_SIZE == 1379


def test_coherency_slots_immediately_after_fight_weapon():
    """COHERENCY_SLOT_BASE = FIGHT_WEAPON_SLOT_BASE + FIGHT_WEAPON_SLOT_COUNT : aucun gap,
    aucun chevauchement. C'est l'invariant que `_build_mlp_extractor` vérifie à l'init."""
    assert COHERENCY_SLOT_BASE == FIGHT_WEAPON_SLOT_BASE + FIGHT_WEAPON_SLOT_COUNT


def test_coherency_slots_close_action_space():
    """COHERENCY_SLOT_BASE + COHERENCY_SLOT_COUNT == TOTAL_ACTION_SIZE : les slots COHERENCY
    ferment l'espace. Un gap ici = des logits never reached dans la tête dense."""
    assert COHERENCY_SLOT_BASE + COHERENCY_SLOT_COUNT == TOTAL_ACTION_SIZE


def test_squad_top_k_matches_coherency_slot_count():
    """SQUAD_TOP_K == COHERENCY_SLOT_COUNT : le nombre de slots d'action doit égaler le nombre
    de lignes observées dans le bloc self_models (invariant D1)."""
    assert ObservationBuilder.SQUAD_TOP_K == COHERENCY_SLOT_COUNT


# ─────────────────────────────────────────────────────────────────────────────
# T2 — Muet / non-muet
# ─────────────────────────────────────────────────────────────────────────────

def test_gym_mode_is_never_muet():
    """En gym, les DEUX sièges répondent par le masque : jamais muet."""
    gs = {"gym_training_mode": True}
    assert not _coherency_seat_is_muet(gs, player=1)
    assert not _coherency_seat_is_muet(gs, player=2)


def test_pvp_human_is_never_muet():
    """Un joueur humain PvP répond par clic : jamais muet."""
    gs = {"player_types": {"1": "human", "2": "human"}}
    assert not _coherency_seat_is_muet(gs, player=1)
    assert not _coherency_seat_is_muet(gs, player=2)


def test_pve_bot_is_muet():
    """Un siège IA en PvE est muet : retrait géométrique immédiat."""
    gs = {"player_types": {"1": "human", "2": "ai"}}
    assert not _coherency_seat_is_muet(gs, player=1)
    assert _coherency_seat_is_muet(gs, player=2)


def test_no_player_types_no_gym_is_muet_false():
    """Sans player_types ni gym_training_mode, aucun siège n'est muet (no-op → queue)."""
    gs = {}
    assert not _coherency_seat_is_muet(gs, player=1)


def test_non_muet_squad_goes_to_queue():
    """Un siège non-muet (gym) ajoute l'escouade incoherente à la queue, sans la retirer."""
    gs = _gs([(10, 10), (11, 10), (30, 40)])
    gs["gym_training_mode"] = True
    assert not validate_squad_coherency(gs, "1")

    removed = end_of_turn_regain_coherency_all_squads(gs)

    assert removed == {}  # aucun retrait immédiat
    assert "pending_coherency_removal_queue" in gs or "pending_coherency_removal" in gs


def test_muet_squad_is_auto_removed():
    """Un siège muet (bot PvE) résout le retrait immédiatement, sans armer la queue."""
    gs = _gs([(10, 10), (11, 10), (30, 40)])
    gs["player_types"] = {"1": "ai"}

    removed = end_of_turn_regain_coherency_all_squads(gs)

    assert "1" in removed and len(removed["1"]) > 0
    assert "pending_coherency_removal" not in gs
    assert validate_squad_coherency(gs, "1")


# ─────────────────────────────────────────────────────────────────────────────
# T3 — Masque exclusif
# ─────────────────────────────────────────────────────────────────────────────

def _gs_with_pending_cr(positions: List[tuple]) -> Dict[str, Any]:
    """gs avec pending_coherency_removal armé sur squad '1', phase fight."""
    gs = _gs(positions)
    gs["pending_coherency_removal"] = {"squad_id": "1"}
    gs["phase"] = "fight"
    return gs


def test_mask_opens_only_coherency_slots(monkeypatch):
    """Quand pending_coherency_removal est armé, SEULS les slots COHERENCY sont ouverts.

    Invariant D1 : slot i ne peut être ouvert que si alive[i] existe. Les slots au-delà du
    nombre de vivantes restent fermés.
    """
    gs = _gs_with_pending_cr([(10, 10), (11, 10), (30, 40)])
    decoder = ActionDecoder(config={})

    # On force eligible_units non-vide pour passer la garde ligne 471 du masque.
    # La branche pending_cr sort AVANT tout le reste.
    dummy_unit = {"id": "1", "player": 1, "col": 10, "row": 10,
                  "HP_CUR": 3, "HP_MAX": 3, "ATTACK_LEFT": 1, "SHOOT_LEFT": 1}
    monkeypatch.setattr(decoder, "_get_eligible_units_for_current_phase", lambda gs: [dummy_unit])

    mask, eligible = decoder.get_squad_action_mask_and_eligible_units(gs)

    # Eligible retourné vide : la branche pending_cr court-circuite tout
    assert eligible == []
    # Seuls les slots COHERENCY[0:3] sont ouverts (3 figurines vivantes)
    alive_count = len(_coherency_alive(gs, "1"))
    assert alive_count == 3
    for i in range(alive_count):
        assert mask[COHERENCY_SLOT_BASE + i], f"slot COHERENCY[{i}] doit être ouvert"
    for i in range(alive_count, COHERENCY_SLOT_COUNT):
        assert not mask[COHERENCY_SLOT_BASE + i], f"slot COHERENCY[{i}] doit être fermé (hors alive)"
    # Aucune autre tranche n'est ouverte
    non_coherency = list(range(COHERENCY_SLOT_BASE)) + list(range(COHERENCY_SLOT_BASE + COHERENCY_SLOT_COUNT, TOTAL_ACTION_SIZE))
    assert not any(mask[i] for i in non_coherency), "aucun slot hors COHERENCY ne doit être ouvert"


def test_mask_shrinks_after_removal(monkeypatch):
    """Après un retrait, alive_count diminue et le slot suivant se ferme."""
    gs = _gs_with_pending_cr([(10, 10), (11, 10), (30, 40)])
    decoder = ActionDecoder(config={})
    dummy_unit = {"id": "1", "player": 1, "col": 10, "row": 10,
                  "HP_CUR": 3, "HP_MAX": 3, "ATTACK_LEFT": 1, "SHOOT_LEFT": 1}
    monkeypatch.setattr(decoder, "_get_eligible_units_for_current_phase", lambda gs: [dummy_unit])

    # Premier appel : 3 figurines → 3 slots ouverts
    mask1, _ = decoder.get_squad_action_mask_and_eligible_units(gs)
    assert mask1[COHERENCY_SLOT_BASE + 2]  # slot 2 ouvert

    # Retirer une figurine du models_cache (simuler un retrait)
    alive_before = _coherency_alive(gs, "1")
    del gs["models_cache"][alive_before[-1]]

    # Deuxième appel : 2 figurines → seuls 2 slots ouverts
    mask2, _ = decoder.get_squad_action_mask_and_eligible_units(gs)
    assert mask2[COHERENCY_SLOT_BASE + 0]
    assert mask2[COHERENCY_SLOT_BASE + 1]
    assert not mask2[COHERENCY_SLOT_BASE + 2], "slot 2 doit être fermé après retrait"


# ─────────────────────────────────────────────────────────────────────────────
# T4 — Décodeur slot → model_id (invariant D1)
# ─────────────────────────────────────────────────────────────────────────────

def test_decoder_slot0_maps_to_alive0():
    """COHERENCY_SLOT_BASE + 0 → alive[0] : invariant D1 (slot i = ligne i obs)."""
    gs = _gs_with_pending_cr([(10, 10), (11, 10), (30, 40)])
    decoder = ActionDecoder(config={})
    alive = _coherency_alive(gs, "1")
    assert len(alive) == 3

    result = decoder.convert_squad_action(COHERENCY_SLOT_BASE + 0, gs)

    assert result["action"] == "select_coherency_removal"
    assert result["squad_id"] == "1"
    assert result["model_id"] == alive[0]


def test_decoder_slot2_maps_to_alive2():
    """COHERENCY_SLOT_BASE + 2 → alive[2] : le mapping est linéaire, jamais décalé."""
    gs = _gs_with_pending_cr([(10, 10), (11, 10), (30, 40)])
    decoder = ActionDecoder(config={})
    alive = _coherency_alive(gs, "1")

    result = decoder.convert_squad_action(COHERENCY_SLOT_BASE + 2, gs)

    assert result["model_id"] == alive[2]


def test_decoder_raises_without_pending():
    """Jouer un slot COHERENCY sans pending_coherency_removal doit lever ValueError."""
    gs = _gs([(10, 10), (11, 10)])
    gs["phase"] = "fight"
    decoder = ActionDecoder(config={})

    with pytest.raises(ValueError, match="pending_coherency_removal absent"):
        decoder.convert_squad_action(COHERENCY_SLOT_BASE + 0, gs)


def test_decoder_raises_on_out_of_range_slot():
    """Un slot COHERENCY[len(alive)] (hors plage) doit lever ValueError — rupture masque/commit."""
    gs = _gs_with_pending_cr([(10, 10), (11, 10)])  # 2 figurines
    decoder = ActionDecoder(config={})
    alive = _coherency_alive(gs, "1")
    assert len(alive) == 2

    with pytest.raises(ValueError, match="hors plage"):
        decoder.convert_squad_action(COHERENCY_SLOT_BASE + 2, gs)


# ─────────────────────────────────────────────────────────────────────────────
# T5 — Queue multi-escouade
# ─────────────────────────────────────────────────────────────────────────────

def test_queue_multi_squad_arms_first():
    """Deux escouades incoherentes non-muetes → la queue contient les deux, le pending arme la 1ère."""
    gs = _gs([(10, 10), (11, 10), (30, 40)], squad_id="1", player=1)
    gs2_pos = [(20, 20), (21, 20), (5, 50)]
    mids2 = ["2#0", "2#1", "2#2"]
    gs["models_cache"].update({mid: _model(*pos, player=2, squad_id="2")
                                for mid, pos in zip(mids2, gs2_pos)})
    gs["squad_models"]["2"] = list(mids2)
    gs["units_cache"]["2"] = {
        "col": 20, "row": 20, "player": 2, "HP_CUR": 3,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        "occupied_hexes": set(), "occupied_hexes_by_model": {},
    }
    gs["gym_training_mode"] = True  # sièges non-muets

    end_of_turn_regain_coherency_all_squads(gs)

    # Les deux escouades incoherentes sont en queue ou armées
    pending = gs.get("pending_coherency_removal")
    queue = gs.get("pending_coherency_removal_queue", [])
    all_pending = ([pending["squad_id"]] if pending else []) + list(queue)
    assert "1" in all_pending and "2" in all_pending, (
        f"les deux escouades doivent être en queue, got pending={pending}, queue={queue}"
    )


def test_arm_next_skips_already_coherent():
    """arm_next_coherency_pending saute une escouade devenue cohérente entre-temps."""
    gs = _gs([(10, 10), (11, 10), (30, 40)], squad_id="1")  # incoherente
    gs2_pos = [(20, 20), (21, 20), (22, 20)]  # cohérente
    mids2 = ["2#0", "2#1", "2#2"]
    gs["models_cache"].update({mid: _model(*pos, squad_id="2")
                                for mid, pos in zip(mids2, gs2_pos)})
    gs["squad_models"]["2"] = list(mids2)
    gs["units_cache"]["2"] = {
        "col": 20, "row": 20, "player": 1, "HP_CUR": 3,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        "occupied_hexes": set(), "occupied_hexes_by_model": {},
    }
    gs["gym_training_mode"] = True

    # Simule une queue avec "2" devant "1"
    gs["pending_coherency_removal_queue"] = ["2", "1"]
    result = arm_next_coherency_pending(gs)

    # "2" est cohérente → sautée ; "1" est incoherente → armée
    assert result is True
    assert gs["pending_coherency_removal"]["squad_id"] == "1"
