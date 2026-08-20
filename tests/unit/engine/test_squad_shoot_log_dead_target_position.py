"""Le log d'un groupe (arme, cible) doit porter la VRAIE position de la cible, même quand
celle-ci a été détruite pendant l'allocation.

Régression verrouillée (2026-07-23). `_emit_squad_shoot_log` est émis en FIN d'allocation
(`_finalize_manual_allocation`), donc APRÈS le retrait de l'escouade cible détruite du
`units_cache`. Il relisait `units_cache[target].get("col", 0)` → l'escouade absente donnait
un fallback anti-erreur `(0,0)` (ex. « Unit 4(0,0) FOUGHT ... » dans un step.log réel), ce qui
polluait ensuite la cohérence position/log de l'analyzer.

Correctif : la position de l'ancre cible est capturée à la CRÉATION du groupe d'arme (cible
alors vivante) dans `g["target_col"]/g["target_row"]`, et l'émission l'utilise sans relire le
cache — plus aucun fallback masquant.

JUMEAU (2026-07-29). Le même défaut vivait à trois lignes de là pour l'ATTAQUANT :
`game_state.get("units_cache", {}).get(sid, {}).get("col", 0)` — deux `.get` à défaut
enchaînés, donc (0,0) pour une escouade absente du cache. La correction avait été faite d'un
côté et pas de l'autre. L'attaquant est désormais capturé au même endroit, de la même façon
(`g["attacker_col"]/g["attacker_row"]`), et les tests ci-dessous sont symétriques.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.attack_sequence import WeaponAttackProfile
from engine.phase_handlers.shared_utils import SHOOT_CTX, _emit_squad_shoot_log
from tests._state_invariants import turn_state_invariants


TARGET_COL, TARGET_ROW = 5, 7
ATTACKER_COL, ATTACKER_ROW = 3, 3


def _game_state_target_removed() -> Dict[str, Any]:
    """units_cache SANS la cible « 2 » (simule l'escouade détruite et retirée à l'allocation) ;
    l'attaquant « 1 » reste présent avec sa position."""
    return {
        "units": [
            {"id": 1, "unitType": "Intercessor"},
            {"id": 2, "unitType": "AssaultIntercessor"},
        ],
        "units_cache": {
            "1": {"col": ATTACKER_COL, "row": ATTACKER_ROW, "player": 1},
            # "2" absente : c'est précisément l'état qui produisait (0,0).
        },
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
    }


def _game_state_both_removed() -> Dict[str, Any]:
    """units_cache VIDE : ni l'attaquant ni la cible ne sont lisibles à l'émission différée.
    C'est l'état qui produisait « Unit 1(0,0) SHOT at Unit 2(0,0) »."""
    gs = _game_state_target_removed()
    gs["units_cache"] = {}
    return gs


def _weapon_group() -> Dict[str, Any]:
    """Groupe (arme, cible) tel que produit par la couche d'allocation, avec la position cible
    capturée AVANT destruction (le correctif)."""
    return {
        "attacker_squad_id": "1",
        "attacker_col": ATTACKER_COL,
        "attacker_row": ATTACKER_ROW,
        "weapon_name": "Bolt Rifle",
        "weapon_names": ["Bolt Rifle"],
        "target_sid": "2",
        "target_col": TARGET_COL,
        "target_row": TARGET_ROW,
        "bs": 3,
        "display_wth": 4,
        "display_save_th": 5,
        "player": 1,
        "attacks": 2,
        "damage": 3,
        "kills": 1,
        "killed_model_ids": ["2#0"],
        "shooter_mids": ["1#0"],
        "shots": [{"targetCol": TARGET_COL, "targetRow": TARGET_ROW}],
        # [HEAVY] 24.16 / [RAPID FIRE] 24.30 : la couche d'allocation pose ces deux clés sur
        # TOUS les groupes, tir comme mêlée (shared_utils.py, construction de `_grp` :
        # `bool(r["heavy_applied"]) if "heavy_applied" in r else False`) — en mêlée elles
        # valent simplement False/0. Les omettre ici rendait le stub infidèle à son propre
        # docstring et faisait lever l'émission, qui les lit en accès direct à juste titre.
        "heavy_applied": False,
        # Oath of Moment (08.04) : posées sur TOUS les groupes par la même construction, pour la
        # même raison — l'émission les lit en accès direct (`RR` / token du +1 de blessure).
        "oath_hit_reroll": False,
        "oath_wound_bonus": 0,
        # Waaagh! (08.04) : même construction, même lecture en accès direct par l'émission
        # (tokens sur `Shots:`, `Wound:` et `Save:`).
        "waaagh_melee_bonus": False,
        "waaagh_target_invul": False,
        # Arme + profil de règles, gardés par référence par le vrai regroupement : l'émission en
        # tire les tokens de règles. Le Bolt Rifle du stub n'en déclare aucune, donc aucun token
        # — état parfaitement produit par le moteur. Les omettre ferait lever l'émission.
        "weapon": {"display_name": "Bolt Rifle", "WEAPON_RULES": []},
        "attack_profile": WeaponAttackProfile(),
        "additive_rules_applied": {},
        "point_blank_malus": False,
        "dmg_bonus": 0,
        # [PRECISION] 24.28 : posé à l'Allocation Order step, jamais à la déclaration de l'arme.
        "precision_applied": False,
        # [ASSAULT] 24.04 / [CLOSE-QUARTERS] 24.07 : exigées par require_key à l'émission.
        # Bolt Rifle ne déclare ni l'un ni l'autre → False.
        "assault_applied": False,
        "close_quarters_applied": False,
        # [INDIRECT FIRE] 10.07 : posé à la création du groupe ; None si la règle ne joue pas.
        "indirect_fire_fail_below": None,
        "targetAliveCount": 2,
    }


def test_log_uses_captured_target_position_not_zero_zero() -> None:
    gs = _game_state_target_removed()
    _emit_squad_shoot_log(gs, _weapon_group(), SHOOT_CTX)

    assert len(gs["action_logs"]) == 1
    msg = gs["action_logs"][0]["message"]
    # La position de la cible dans le message est celle capturée, jamais le fallback (0,0).
    assert f"({TARGET_COL},{TARGET_ROW})" in msg
    assert "(0,0)" not in msg
    # Le raw_log porte aussi les bonnes coordonnées (consommées par le StepLogger).
    assert gs["action_logs"][0]["targetCol"] == TARGET_COL
    assert gs["action_logs"][0]["targetRow"] == TARGET_ROW


def test_missing_captured_position_raises_instead_of_silent_zero() -> None:
    """Sans position capturée, on veut une erreur explicite (CLAUDE.md : aucun fallback
    masquant), pas un retour silencieux à (0,0)."""
    gs = _game_state_target_removed()
    g = _weapon_group()
    del g["target_col"]
    with pytest.raises(Exception):
        _emit_squad_shoot_log(gs, g, SHOOT_CTX)


def test_log_uses_captured_attacker_position_not_zero_zero() -> None:
    """JUMEAU : l'attaquant non plus n'est relu dans units_cache à l'émission."""
    gs = _game_state_both_removed()
    _emit_squad_shoot_log(gs, _weapon_group(), SHOOT_CTX)

    msg = gs["action_logs"][0]["message"]
    assert f"({ATTACKER_COL},{ATTACKER_ROW})" in msg
    assert "(0,0)" not in msg
    assert gs["action_logs"][0]["shooterCol"] == ATTACKER_COL
    assert gs["action_logs"][0]["shooterRow"] == ATTACKER_ROW


def test_missing_captured_attacker_position_raises_instead_of_silent_zero() -> None:
    """Symétrique du test cible : sans position d'attaquant capturée, on lève."""
    gs = _game_state_target_removed()
    g = _weapon_group()
    del g["attacker_col"]
    with pytest.raises(Exception):
        _emit_squad_shoot_log(gs, g, SHOOT_CTX)


# --------------------------------------------------------------------------------------
# Bout-en-bout : la capture a bien lieu à la création du groupe, et le journal la porte
# --------------------------------------------------------------------------------------

ATK_ANCHOR = (2, 2)
TGT_ANCHOR = (2, 4)


def _live_shoot_state() -> Dict[str, Any]:
    """Tir résolu par le moteur (mode gym auto), pour vérifier ce que le journal reçoit
    RÉELLEMENT — le stub ci-dessus ne prouve que l'émission, pas la capture."""
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
              "WEAPON_RULES": [], "display_name": "Bolter"}
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                "col": ATK_ANCHOR[0], "row": ATK_ANCHOR[1], "RNG_WEAPONS": [weapon]}
    target = {"id": "T1", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 20, "HP_MAX": 20,
              "ARMOR_SAVE": 7, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
              "points_per_hp": 5.0, "VALUE": 10.0,
              "col": TGT_ANCHOR[0], "row": TGT_ANCHOR[1]}

    def _uc(col, row, player):
        return {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": col, "row": row,
                "occupied_hexes": {(col, row)}, "VALUE": 10.0, "player": player}

    return {**turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, "T1": target},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(*ATK_ANCHOR, 0), "2": _uc(*TGT_ANCHOR, 1)},
        "units": [{"id": "1", "player": 0}, {"id": "2", "player": 1}],
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": []}, "2": {"id": "2", "UNIT_RULES": []}},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "pending_squad_shoot_intents": {
            "1": [{"model_id": "A1", "target_unit_id": "2", "weapon_index": 0,
                   "n_attacks_resolved": 1, "target_squad_size_at_declaration": 1}]
        },
    }


def test_journal_porte_les_deux_positions_reelles_bout_en_bout(monkeypatch) -> None:
    """Le log émis par une vraie résolution porte l'ancre de l'attaquant ET celle de la cible,
    plus la position de la figurine touchée dans le détail de tir (`shootDetails`)."""
    import random

    from engine.phase_handlers import shooting_handlers
    from engine.phase_handlers.shared_utils import build_manual_shoot_allocation

    rolls = [4, 5, 1]  # touche, blesse, sauvegarde ratée
    monkeypatch.setattr(random, "randint", lambda a, b: rolls.pop(0))
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(shooting_handlers, "_ranged_distance_metric", lambda *args, **kwargs: "euclidean")

    gs = _live_shoot_state()
    build_manual_shoot_allocation(gs, "1")

    log = next(l for l in gs["action_logs"] if l["type"] == "shoot")
    assert (log["shooterCol"], log["shooterRow"]) == ATK_ANCHOR
    assert (log["targetCol"], log["targetRow"]) == TGT_ANCHOR
    assert log["player"] == 0
    # Détail de tir : position de la FIGURINE touchée, jamais None.
    detail = log["shootDetails"][0]
    assert (detail["targetCol"], detail["targetRow"]) == TGT_ANCHOR


def _manual_wound_fixture(gs):
    """Structures minimales attendues par `_resolve_one_manual_wound` (une blessure allouée
    sur T1, sauvegarde ratée), telles que la couche d'allocation les construit."""
    rec: Dict[str, Any] = {}
    alloc = {
        "summary": {"damage_total": 0, "models_killed": 0, "events": [], "failed_saves": 0},
        "weapon_groups": [{
            "ap": 0, "dmg_raw": 1, "dmg_bonus": 0,
            "damage": 0, "kills": 0, "killed_model_ids": [],
        }],
    }
    batch = {
        "current_model_id": "T1",
        "weapon_group_idx": 0,
        "pool_index": 0,
        "target_sid": "2",
        "pool": [{"rec": rec, "save_roll": 1, "attacker_mid": "A1"}],
    }
    return alloc, batch, rec


def test_position_de_la_figurine_touchee_requise() -> None:
    """`rec["targetCol"]` venait de `m.get("col")` : un `None` silencieux dans `shootDetails`,
    c'est-à-dire une position d'analyse absente au lieu d'une erreur."""
    from engine.phase_handlers.shared_utils import SHOOT_CTX, _resolve_one_manual_wound

    gs = _live_shoot_state()
    del gs["models_cache"]["T1"]["col"]
    alloc, batch, _rec = _manual_wound_fixture(gs)

    with pytest.raises(Exception) as exc:
        _resolve_one_manual_wound(gs, alloc, batch, SHOOT_CTX)

    assert "col" in str(exc.value)


def test_position_de_la_figurine_touchee_reportee_telle_quelle() -> None:
    """Contre-épreuve : la position réelle part dans le détail de tir."""
    from engine.phase_handlers.shared_utils import SHOOT_CTX, _resolve_one_manual_wound

    gs = _live_shoot_state()
    gs["models_cache"]["T1"].update({"col": 8, "row": 12})
    alloc, batch, rec = _manual_wound_fixture(gs)

    _resolve_one_manual_wound(gs, alloc, batch, SHOOT_CTX)

    assert (rec["targetCol"], rec["targetRow"]) == (8, 12)
