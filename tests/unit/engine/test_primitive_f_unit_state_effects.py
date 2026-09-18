"""Primitive F — `unit_state_effects` (chantier 06, passe 6).

Sept capacités couvertes :
- `invul_save_override`              : InSv à toute l'unité via 19.04 (BannerNob 5+, Librarian 4+)
- `toughness_bonus_while_waaagh`     : +1 T sur l'unité cible pendant le Waaagh! (BannerNob)
- `suppress_target_on_shooting`      : pose le statut suppressed sur la cible après tir (WarTrakk)
- `return_destroyed_models`          : 1×/partie, D3 figurines restaurées en phase commandement (PainBoy)
- Finest Hour spent obs              : once_per_battle_melee_buff invisible dans l'obs quand dépensé
- `move_after_shooting` D6           : Purgation Run — distance_dice: "D6" (LandSpeeder)
- Waaagh! Banner clause 2 dans toughness (jumeau tir/mêlée couvert par un point unique)

Plan rouge → vert sur les invariants moteurs.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _rule(rule_id: str, rule_args: Optional[Dict[str, Any]] = None, **kw: Any) -> Dict[str, Any]:
    r: Dict[str, Any] = {"ruleId": rule_id, "displayName": rule_id}
    if rule_args is not None:
        r["rule_args"] = rule_args
    r.update(kw)
    return r


def _unit(uid: str, player: int, unit_rules: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        # Datasheet de l'escouade, comme toute unité de production : la ligne `RETURNED` du
        # journal la lit en repli pour un socle rendu sans type propre.
        "unitType": "Boyz",
        "UNIT_RULES": unit_rules or [],
        "battle_shocked": False,
        "OC": 2,
        "UNIT_KEYWORDS": [],
    }


def _model(uid: str, col: int = 5, row: int = 5, t: int = 4, role: str = "bodyguard",
           hp_cur: int = 3, hp_max: int = 3, invul_save: int = 7,
           armor_save: int = 4, unit_type: str = "Boyz") -> Dict[str, Any]:
    return {
        "squad_id": uid,
        # Identité de PROFIL : la restitution Grot Orderly la lit pour rendre la figurine
        # RÉELLEMENT détruite plutôt qu'un clone d'une survivante.
        "unitType": unit_type,
        "col": col,
        "row": row,
        "level": 0,
        "T": t,
        "role": role,
        "HP_CUR": hp_cur,
        "HP_MAX": hp_max,
        "INVUL_SAVE": invul_save,
        "ARMOR_SAVE": armor_save,
        "OC": 1,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "player": 1,
        "VALUE": 10,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 13,
        "MODEL_HEIGHT": 2.0,  # requis par le moteur
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "UNIT_RULES": [],
    }


def _base_state(
    units: Optional[List[Dict[str, Any]]] = None,
    *,
    current_player: int = 1,
    waaagh_active: bool = False,
    army_faction_orks: bool = False,
    squad_cache: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    units = units or []
    unit_by_id = {str(u["id"]): u for u in units}
    units_cache: Dict[str, Any] = {}
    models_cache: Dict[str, Any] = {}
    sq_models: Dict[str, Any] = {}
    for u in units:
        uid = str(u["id"])
        mid = f"{uid}#0"
        models_cache[mid] = _model(uid)
        sq_models[uid] = [mid]
        units_cache[uid] = {
            "player": u["player"],
            "col": 5,
            "row": 5,
            "HP_CUR": int(models_cache[mid]["HP_CUR"]),
            "OC_TOTAL": int(models_cache[mid]["OC"]),
            "orientation": 0,
            "BASE_SHAPE": "round",
            "BASE_SIZE": 13,
        }
    army_faction_config = {"1": "ORKS", "2": "ORKS"} if army_faction_orks else {"1": "SPACE MARINES", "2": "SPACE MARINES"}
    gs: Dict[str, Any] = {
        "units": units,
        "units_cache": units_cache,
        "models_cache": models_cache,
        "squad_models": sq_models,
        "unit_by_id": unit_by_id,
        "current_player": current_player,
        "turn": 1,
        "phase": "command",
        "action_logs": [],
        "action_log_seq": 0,
        "waaagh_active": {1: waaagh_active, 2: False},
        "suppressed_squads": {},
        "finest_hour_used": set(),
        "squad_cache": dict(squad_cache or {}),
        "_restored_model_counter": 0,
        "config": {
            "game_rules": {
                "engagement_zone": 2,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
                "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
                "bonus_malus_cap": 0,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
            "controlled_player": 1,
            "army_faction": army_faction_config,
        },
    }
    # Construire squad_cache si non fourni
    if not squad_cache:
        for u in units:
            uid = str(u["id"])
            mid_list = sq_models[uid]
            gs["squad_cache"][uid] = {
                "model_count": len(mid_list),
                "model_count_at_start": len(mid_list),
                "is_coherent": True,
                "oc_total": 1,
                "centroid_col": 5,
                "centroid_row": 5,
            }
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# invul_save_override
# ─────────────────────────────────────────────────────────────────────────────

def test_invul_save_override_remplace_base() -> None:
    """La règle confère une InSv 5+ même quand la base est 7+ (aucune InSv)."""
    from engine.game_state import effective_invul_save

    unit = _unit("1", 1, unit_rules=[_rule("invul_save_override", {"value": 5})])
    gs = _base_state([unit])
    assert effective_invul_save(gs, unit, 7) == 5


def test_invul_save_override_prend_le_meilleur() -> None:
    """Deux unités : la meilleure override (valeur min) s'applique."""
    from engine.game_state import effective_invul_save

    unit4 = _unit("1", 1, unit_rules=[_rule("invul_save_override", {"value": 4})])
    gs = _base_state([unit4])
    # base 7+, override 4+ → effective 4+
    assert effective_invul_save(gs, unit4, 7) == 4
    # base 3+ (shield), override 4+ → effective 3+ (shield gagne)
    assert effective_invul_save(gs, unit4, 3) == 3


def test_invul_save_override_absent_retourne_base() -> None:
    """Sans la règle, la valeur de base est conservée."""
    from engine.game_state import effective_invul_save

    unit = _unit("1", 1)
    gs = _base_state([unit])
    assert effective_invul_save(gs, unit, 6) == 6


def test_invul_save_override_cumule_waaagh() -> None:
    """Waaagh! (5+) + override (4+) : le min (4+) s'applique."""
    from engine.game_state import effective_invul_save

    unit = _unit("1", 1, unit_rules=[
        _rule("invul_save_override", {"value": 4}),
    ])
    unit["FACTION_KEYWORDS"] = [{"keywordId": "ORKS"}]
    gs = _base_state([unit], waaagh_active=True, army_faction_orks=True)
    # Waaagh! accorde 5+, override 4+ → 4+ gagne
    assert effective_invul_save(gs, unit, 7) == 4


def test_invul_save_override_mental_fortress_librarian_19_04() -> None:
    """Mental Fortress : la règle du Librarian se propage au bodyguard via le fold 19.04.

    Scénario : bodyguard sans invul_save_override propre ; Librarian attaché en porte une (4+).
    Vérifie compute_unit_rules_in_effect plutôt qu'un standalone déjà couvert ligne 152.
    """
    from engine.phase_handlers.shared_utils import compute_unit_rules_in_effect

    own_rules: list = []
    lib_rule = _rule("invul_save_override", {"value": 4})
    attached_groups = {"lib": [lib_rule]}

    # Librarian vivant → règle présente dans l'union
    merged = compute_unit_rules_in_effect(
        own_rules, attached_groups, native_alive=True, alive_attached_sources={"lib"}
    )
    rule_ids = [r["ruleId"] for r in merged]
    assert "invul_save_override" in rule_ids
    override = next(r for r in merged if r["ruleId"] == "invul_save_override")
    assert override["rule_args"]["value"] == 4

    # Librarian mort → règle absente (19.04 : éteinte à la mort du porteur)
    merged_dead = compute_unit_rules_in_effect(
        own_rules, attached_groups, native_alive=True, alive_attached_sources=set()
    )
    assert all(r["ruleId"] != "invul_save_override" for r in merged_dead)


@pytest.mark.parametrize("alive_attached_sources,expected", [
    ({"lib1"}, 4),
    (set(), 7),
], ids=["librarian_vivant", "librarian_mort"])
def test_invul_save_override_19_04_librarian_bodyguard(
    alive_attached_sources: set, expected: int
) -> None:
    """19.04 : effective_invul_save reflète la présence du Librarian.

    Librarian vivant → override (4+) propagé au bodyguard Intercessor (base InSv 7+).
    Librarian mort (alive_attached_sources vide) → règle absente, retour valeur base (7).
    Le fold _fold_attached_characters n'est pas appelé ici — couvert par
    test_invul_save_override_mental_fortress_librarian_19_04.
    """
    from engine.game_state import effective_invul_save
    from engine.phase_handlers.shared_utils import compute_unit_rules_in_effect

    librarian_id = "lib1"
    bodyguard_id = "inter1"

    invul_rule = _rule("invul_save_override", {"value": 4})

    own_rules: List[Dict[str, Any]] = []
    attached_groups: Dict[str, List[Dict[str, Any]]] = {
        librarian_id: [invul_rule],
    }
    unit_rules_in_effect = compute_unit_rules_in_effect(
        own_rules,
        attached_groups,
        native_alive=True,
        alive_attached_sources=alive_attached_sources,
    )

    bodyguard = _unit(bodyguard_id, 1, unit_rules=unit_rules_in_effect)

    gs = _base_state([bodyguard])
    assert effective_invul_save(gs, bodyguard, 7) == expected


# ─────────────────────────────────────────────────────────────────────────────
# toughness_bonus_while_waaagh
# ─────────────────────────────────────────────────────────────────────────────

def test_toughness_bonus_while_waaagh_actif() -> None:
    """+1 T quand le Waaagh! est actif pour l'unité cible portant la règle."""
    from engine.phase_handlers.shared_utils import _target_highest_bodyguard_toughness

    unit = _unit("42", 1, unit_rules=[
        _rule("toughness_bonus_while_waaagh", {"toughness_bonus": 1}),
    ])
    unit["FACTION_KEYWORDS"] = [{"keywordId": "ORKS"}]
    gs = _base_state([unit], waaagh_active=True, army_faction_orks=True)
    gs["models_cache"]["42#0"]["T"] = 5
    assert _target_highest_bodyguard_toughness(gs, "42") == 6  # 5 + 1


def test_toughness_bonus_while_waaagh_inactif() -> None:
    """Pas de bonus quand le Waaagh! n'est pas actif."""
    from engine.phase_handlers.shared_utils import _target_highest_bodyguard_toughness

    unit = _unit("42", 1, unit_rules=[
        _rule("toughness_bonus_while_waaagh", {"toughness_bonus": 1}),
    ])
    unit["FACTION_KEYWORDS"] = [{"keywordId": "ORKS"}]
    gs = _base_state([unit], waaagh_active=False, army_faction_orks=True)
    gs["models_cache"]["42#0"]["T"] = 5
    assert _target_highest_bodyguard_toughness(gs, "42") == 5  # pas de Waaagh!


def test_toughness_bonus_absent_retourne_base_t() -> None:
    """Sans la règle, T de base inchangée."""
    from engine.phase_handlers.shared_utils import _target_highest_bodyguard_toughness

    unit = _unit("42", 1)
    gs = _base_state([unit])
    gs["models_cache"]["42#0"]["T"] = 7
    assert _target_highest_bodyguard_toughness(gs, "42") == 7


# ─────────────────────────────────────────────────────────────────────────────
# suppress_target_on_shooting — « select one enemy unit HIT by one or more of those attacks »
#
# Chaîne RÉELLE : intents → build_manual_shoot_allocation (jets, `_shoot_hit_targets` posée par
# `_finalize_manual_allocation`) → _handle_shooting_end_activation. Avant le 2026-09-18, la cible
# DÉSIGNÉE était supprimée sans contrôle de touche (reproductions 1 et 2 rouges).
# ─────────────────────────────────────────────────────────────────────────────

_SUPPRESS_RULE = _rule("suppress_target_on_shooting")


def _wartrakk_state(n_targets: int) -> Dict[str, Any]:
    """WarTrakk '1' (1 figurine, 2 armes de test) ; cibles '101'… ; un intent par cible."""
    from tests._state_invariants import turn_state_invariants
    from tests.unit.ai._fabriques import units_cache_entry as _uc

    # Une arme (BS 4+) par cible : un lot par arme, résolus dans l'ordre des armes.
    weapons = [
        {"ATK": 4, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 120, "WEAPON_RULES": [],
         "code": f"test_gun_{i}", "display_name": f"Test Gun {i}"}
        for i in range(n_targets)
    ]
    attacker = {"id": "1#0", "squad_id": "1", "player": 1, "T": 6, "SHOOT_LEFT": 1,
                "ATTACK_LEFT": 1, "col": 50, "row": 50, "OC": 3, "VALUE": 60,
                "RNG_WEAPONS": weapons, "CC_WEAPONS": [], "UNIT_RULES": []}
    models_cache: Dict[str, Any] = {"1#0": attacker}
    squad_models: Dict[str, Any] = {"1": ["1#0"]}
    squad_cache: Dict[str, Any] = {"1": {"model_count_at_start": 1}}
    units_cache: Dict[str, Any] = {
        "1": {**_uc(50, 50, player=1, models={"1#0": (50, 50)}), "orientation": 0},
    }
    units: List[Dict[str, Any]] = [{"id": "1", "player": 1, "unitType": "WarTrakk"}]
    unit_by_id: Dict[str, Any] = {
        "1": {"id": "1", "UNIT_RULES": [dict(_SUPPRESS_RULE)], "deployed_on_turn": 0, "player": 1,
              "unit_keywords": [], "UNIT_KEYWORDS": []},
    }
    intents = []
    for i in range(n_targets):
        sid = str(101 + i)
        mid = f"{sid}#0"
        pos = (80, 50 + 10 * i)
        models_cache[mid] = {
            "id": mid, "squad_id": sid, "player": 2, "T": 4, "HP_CUR": 2, "HP_MAX": 2,
            "ARMOR_SAVE": 7, "INVUL_SAVE": 7, "role": None, "unitType": "AssaultIntercessor",
            "points_per_hp": 5.0, "VALUE": 10 + i, "OC": 2, "col": pos[0], "row": pos[1],
            "BASE_SHAPE": "round", "BASE_SIZE": 1,
            "RNG_WEAPONS": [], "CC_WEAPONS": [], "UNIT_RULES": [],
        }
        squad_models[sid] = [mid]
        squad_cache[sid] = {"model_count_at_start": 1}
        units_cache[sid] = {**_uc(*pos, player=2, models={mid: pos}, hp_cur=2), "orientation": 0}
        units.append({"id": sid, "player": 2, "unitType": "AssaultIntercessor"})
        unit_by_id[sid] = {"id": sid, "UNIT_RULES": [], "deployed_on_turn": 0, "player": 2,
                           "unit_keywords": [], "UNIT_KEYWORDS": []}
        intents.append({"model_id": "1#0", "target_unit_id": sid, "weapon_index": i,
                        "n_attacks_resolved": 1, "target_squad_size_at_declaration": 1})
    return {
        **turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot", "current_player": 1,
        "action_logs": [], "action_log_seq": 0,
        "models_cache": models_cache, "squad_models": squad_models, "squad_cache": squad_cache,
        "units_cache": units_cache, "units": units, "unit_by_id": unit_by_id,
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "inches_to_subhex": 5, "moved_distance_by_model": {"1#0": 0.0},
        "board_cols": 200, "board_rows": 100,
        "config": {"game_rules": {"engagement_zone": 5}, "gym_training_mode": True},
        "no_gym_allocation_model": True,
        "pending_squad_shoot_intents": {"1": intents},
        "shoot_activation_pool": ["1"],
        "suppressed_squads": {},
        "player_types": {"1": "ai", "2": "ai"},
    }


def _resolve_shooting(monkeypatch, gs: Dict[str, Any], hit_rolls: List[int]) -> Dict[str, Any]:
    """Jets forcés — un jet de touche par lot (BS 4+) ; une touche enchaîne blessure 6 puis save
    1 (ratée), un raté ne consomme qu'un dé — puis fin d'activation."""
    import random

    from engine.phase_handlers import shared_utils as _su
    from engine.phase_handlers import shooting_handlers
    from engine.phase_handlers.shared_utils import build_manual_shoot_allocation

    seq: List[int] = []
    for h in hit_rolls:
        seq.extend([h, 6, 1] if h >= 4 else [h])
    monkeypatch.setattr(random, "randint", lambda a, b: seq.pop(0) if seq else 1)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los",
                        lambda gs_, s, t: {"cover": False, "can_see": True})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs_, sid: {"id": sid})
    monkeypatch.setattr(shooting_handlers, "_is_adjacent_to_enemy_within_cc_range",
                        lambda gs_, u: False)
    monkeypatch.setattr(_su, "_squad_is_in_enemy_er", lambda _gs, sid: False)
    monkeypatch.setattr(_su, "_squads_are_engaged", lambda _gs, a, b: False)
    _su.designate_shoot_target(gs, "1", "101")
    alloc = build_manual_shoot_allocation(gs, "1")
    assert alloc["done"] is True
    # Lue AVANT la fin d'activation, qui efface les clés d'activation une fois résolue.
    gs["_test_hit_targets"] = list(gs["unit_by_id"]["1"]["_shoot_hit_targets"])
    from engine.phase_handlers.shooting_handlers import ACTION, SHOOTING, _handle_shooting_end_activation

    _ok, result = _handle_shooting_end_activation(
        gs, gs["unit_by_id"]["1"], ACTION, 1, SHOOTING, SHOOTING, 1, action_type="shoot"
    )
    return result


def test_reproduction_1_cible_designee_ratee_n_est_pas_supprimee(monkeypatch) -> None:
    """REPRODUCTION 1 : WarTrakk tire sur A, tous les jets de touche à 1 → `suppressed_squads`
    vide (avant le fix : A supprimée, la désignée l'était sans touche)."""
    gs = _wartrakk_state(1)
    _resolve_shooting(monkeypatch, gs, hit_rolls=[1])
    assert gs["_test_hit_targets"] == []
    assert gs["suppressed_squads"] == {}


def test_reproduction_2_seule_l_escouade_touchee_est_supprimee(monkeypatch) -> None:
    """REPRODUCTION 2 : A (désignée) ratée, B touchée en split-fire → B supprimée, jamais A."""
    gs = _wartrakk_state(2)
    _resolve_shooting(monkeypatch, gs, hit_rolls=[1, 6])
    assert gs["_test_hit_targets"] == ["102"]
    assert gs["suppressed_squads"] == {"102": 1}


def test_une_seule_touchee_ne_pose_aucune_decision(monkeypatch) -> None:
    """Une seule intention possible = aucune décision posée (§9.0bis)."""
    from engine.agent_decision import read_pending_agent_decision

    gs = _wartrakk_state(2)
    result = _resolve_shooting(monkeypatch, gs, hit_rolls=[6, 1])
    assert gs["suppressed_squads"] == {"101": 1}
    assert read_pending_agent_decision(gs) is None
    assert not result.get("waiting_for_player")


def test_plusieurs_touchees_posent_la_decision_suppress_target(monkeypatch) -> None:
    """Deux escouades touchées → décision `suppress_target` (candidats = les touchées, dans
    l'ordre des lots, traits continus santé/valeur), fin d'activation DIFFÉRÉE, rien supprimé."""
    from engine.agent_decision import read_pending_agent_decision
    from engine.observation_entities import decision_option_cont_index

    gs = _wartrakk_state(3)
    result = _resolve_shooting(monkeypatch, gs, hit_rolls=[6, 1, 6])
    assert result["waiting_for_player"] is True and result["decision_type"] == "suppress_target"
    decision = read_pending_agent_decision(gs)
    assert decision is not None and decision["type"] == "suppress_target"
    assert decision["unit_id"] == "1" and decision["player"] == 1
    assert [o["payload"]["target_eid"] for o in decision["options"]] == ["101", "103"]
    assert all(o["declines"] is False and o["effect_ids"] == () for o in decision["options"])
    cont = decision["options_cont"]
    assert cont[0][decision_option_cont_index("target_wounded_hp_norm")] == 0.5  # 1/2 PV après le tir
    assert cont[1][decision_option_cont_index("target_value_norm")] == 1.0  # 12 pts = la plus chère
    assert gs["suppressed_squads"] == {}, "rien n'est supprimé avant la réponse"
    assert "1" in gs["shoot_activation_pool"], "l'activation n'est pas close avant la réponse"


def test_la_reponse_applique_la_touchee_choisie_et_clot_l_activation(monkeypatch) -> None:
    """`apply_suppress_target_decision` (les trois sièges y passent) : la touchée choisie est
    supprimée, une non-touchée est refusée, l'activation se termine."""
    from engine.agent_decision import clear_pending_agent_decision
    from engine.phase_handlers.shooting_handlers import apply_suppress_target_decision

    gs = _wartrakk_state(3)
    _resolve_shooting(monkeypatch, gs, hit_rolls=[6, 1, 6])
    unit = gs["unit_by_id"]["1"]
    with pytest.raises(ValueError, match="n'a pas été touchée"):
        apply_suppress_target_decision(gs, unit, {"target_eid": "102"})
    clear_pending_agent_decision(gs)
    ok, result = apply_suppress_target_decision(gs, unit, {"target_eid": "103"})
    assert ok is True and result["suppressedTargetId"] == "103"
    assert gs["suppressed_squads"] == {"103": 1}
    assert "1" not in gs["shoot_activation_pool"]
    assert "_suppress_target_pending" not in unit and "_shoot_hit_targets" not in unit


def test_politique_bot_suppress_target_declaree() -> None:
    """Bot : la désignée si touchée ; sinon, parmi les touchées sur un objectif, la plus haute OC
    vivante ; sinon la plus haute OC, départage par id. Jamais un tirage."""
    from engine.phase_handlers import shooting_handlers as sh

    gs = _wartrakk_state(3)
    unit = gs["unit_by_id"]["1"]
    unit["designated_shoot_target_id"] = "102"
    assert sh.select_bot_suppress_target(gs, unit, ["101", "102", "103"]) == "102"
    # Désignée non touchée : OC — 103 vaut 3 (OC 2 + 1 de bonus), 101 vaut 2.
    gs["unit_by_id"]["103"]["UNIT_RULES"] = [_rule("oc_bonus", {"oc_bonus": 1})]
    assert sh.select_bot_suppress_target(gs, unit, ["101", "103"]) == "103"
    # Objectif : 101 tient un objectif (socle à (80,50)), 103 non → 101 malgré son OC plus bas.
    gs["objectives"] = [{"id": "o1", "hexes": [[80, 50]]}]
    assert sh.select_bot_suppress_target(gs, unit, ["101", "103"]) == "101"


# ─────────────────────────────────────────────────────────────────────────────
# move_after_shooting D6
# ─────────────────────────────────────────────────────────────────────────────

def test_resolve_move_after_shooting_distance_dice_renvoie_entre_1_et_6() -> None:
    """_resolve_move_after_shooting_distance avec distance_dice='D6' renvoie 1..6."""
    from engine.phase_handlers.shooting_handlers import _resolve_move_after_shooting_distance

    unit = _unit("ls", 1, unit_rules=[
        _rule("move_after_shooting", {"distance_dice": "D6"}),
    ])
    results = set()
    for _ in range(200):
        v = _resolve_move_after_shooting_distance(unit)
        assert 1 <= v <= 6, f"Valeur hors plage : {v}"
        results.add(v)
    # Sur 200 tirages au moins 3 valeurs distinctes
    assert len(results) >= 3


def test_resolve_move_after_shooting_distance_fixe() -> None:
    """distance entière fixe : retourne la valeur exacte."""
    from engine.phase_handlers.shooting_handlers import _resolve_move_after_shooting_distance

    unit = _unit("ls", 1, unit_rules=[
        _rule("move_after_shooting", {"distance": 6}),
    ])
    assert _resolve_move_after_shooting_distance(unit) == 6


def test_resolve_move_after_shooting_distance_absente_leve() -> None:
    """Ni distance ni distance_dice : ValueError."""
    from engine.phase_handlers.shooting_handlers import _resolve_move_after_shooting_distance

    unit = _unit("ls", 1, unit_rules=[
        _rule("move_after_shooting"),  # pas de rule_args
    ])
    with pytest.raises(ValueError):
        _resolve_move_after_shooting_distance(unit)


# ─────────────────────────────────────────────────────────────────────────────
# return_destroyed_models (Grot Orderly)
# ─────────────────────────────────────────────────────────────────────────────

def _state_with_painboy_and_destroyed(n_alive: int = 3, n_destroyed: int = 2) -> Dict[str, Any]:
    """Game state : PainBoy attaché à un squad avec des figurines détruites."""
    unit = _unit("pain", 1, unit_rules=[_rule("return_destroyed_models")])
    # L'appel accepté REPREND 08.04 (Waaagh!/Oath) : la faction déclarée par `_base_state`
    # doit être portée par l'escouade, comme pour toute unité de production.
    unit["FACTION_KEYWORDS"] = ["SPACE MARINES"]
    gs = _base_state([unit])
    gs.update({
        "board_cols": 24,
        "board_rows": 24,
        "wall_hexes": set(),
        "terrain_areas": [],
        "objectives": [],
    })

    # Remplacer les figurines par n_alive figurines
    mids = [f"pain#{i}" for i in range(n_alive)]
    # Supprimer l'entrée par défaut et reconstruire
    for old_mid in list(gs["models_cache"].keys()):
        if old_mid.startswith("pain#"):
            del gs["models_cache"][old_mid]
    for mid in mids:
        gs["models_cache"][mid] = _model("pain", t=5, armor_save=5)
    gs["squad_models"]["pain"] = mids
    gs["squad_cache"]["pain"] = {
        "model_count": n_alive,
        "model_count_at_start": n_alive + n_destroyed,
        "is_coherent": True,
        "oc_total": n_alive,
        "centroid_col": 5,
        "centroid_row": 5,
    }
    gs["units_cache"]["pain"]["HP_CUR"] = n_alive * 3
    # Archive des figurines détruites : c'est ELLE que la restitution rend (REVIVED). Un seul
    # profil ici — le choix « quelles figurines » ne se pose pas, ces tests portent sur le NOMBRE
    # rendu et le « once per battle ».
    gs["destroyed_models"] = {
        "pain": [_model("pain", col=-1, row=-1, t=5, armor_save=5) for _ in range(n_destroyed)]
    }
    return gs


def _accept_grot_orderly(gs: Dict[str, Any]) -> None:
    """08.04 pose l'APPEL Grot Orderly (« you can return ») ; ici le siège l'accepte."""
    from engine.ability_calls import apply_ability_call
    from engine.phase_handlers.command_handlers import _apply_return_destroyed_models

    assert _apply_return_destroyed_models(gs, 1) is True, "aucun appel Grot Orderly posé"
    apply_ability_call(gs, gs["pending_rule_choice_queue"].pop(0), True)


def test_return_destroyed_models_restaure_au_moins_un() -> None:
    """Des figurines détruites existent → l'appel est posé, accepté, D3 sont restaurées (≥ 1)."""
    gs = _state_with_painboy_and_destroyed(n_alive=3, n_destroyed=3)
    mids_before = len(gs["squad_models"]["pain"])

    _accept_grot_orderly(gs)

    mids_after = len(gs["squad_models"]["pain"])
    assert mids_after > mids_before, "Aucune figurine restaurée"
    restored = mids_after - mids_before
    assert 1 <= restored <= 3, f"D3 attendu : {restored}"


def test_return_destroyed_models_une_seule_fois() -> None:
    """Once per battle : après une acceptation, plus aucun appel n'est posé."""
    from engine.phase_handlers.command_handlers import _apply_return_destroyed_models

    gs = _state_with_painboy_and_destroyed(n_alive=2, n_destroyed=4)
    _accept_grot_orderly(gs)
    count_apres_premier = len(gs["squad_models"]["pain"])

    assert _apply_return_destroyed_models(gs, 1) is False, "Second appel ne doit pas être posé"
    assert len(gs["squad_models"]["pain"]) == count_apres_premier


def test_return_destroyed_models_sans_pertes_rien_ne_se_passe() -> None:
    """Aucune figurine détruite → squad_models inchangé."""
    from engine.phase_handlers.command_handlers import _apply_return_destroyed_models

    gs = _state_with_painboy_and_destroyed(n_alive=5, n_destroyed=0)
    mids_before = list(gs["squad_models"]["pain"])

    assert _apply_return_destroyed_models(gs, 1) is False, "à effectif complet, aucun appel"

    assert gs["squad_models"]["pain"] == mids_before


def test_return_destroyed_models_met_a_jour_hp_cur() -> None:
    """Après restauration, HP_CUR de l'escouade en units_cache augmente."""
    gs = _state_with_painboy_and_destroyed(n_alive=2, n_destroyed=3)
    hp_avant = gs["units_cache"]["pain"]["HP_CUR"]

    _accept_grot_orderly(gs)

    assert gs["units_cache"]["pain"]["HP_CUR"] > hp_avant


# ─────────────────────────────────────────────────────────────────────────────
# once_per_battle_melee_buff — observation masquée quand dépensée
# ─────────────────────────────────────────────────────────────────────────────
#
# Les deux tests qui vivaient ici RECOPIAIENT la compréhension du builder, `rule_id ==
# "once_per_battle_melee_buff"` compris, au lieu d'appeler l'observation. Ils sont restés verts
# pendant tout le temps où le filtre laissait `return_destroyed_models` visible après le Grot
# Orderly, et le seraient restés si le filtre avait disparu. Le verrou est désormais
# `test_squad_obs_unit_rules.py::test_once_per_battle_capability_disappears_once_spent`, qui lit
# les `ability_ids` d'une observation réelle, pour CHAQUE effet de
# `ONCE_PER_BATTLE_SPENT_STATE_KEYS`.


# ─────────────────────────────────────────────────────────────────────────────
# Finding F4 — _apply_return_destroyed_models lève si squad_cache absent (T1)
# ─────────────────────────────────────────────────────────────────────────────

def test_return_destroyed_models_leve_si_squad_cache_absent() -> None:
    """Finding F4 : squad_cache obligatoire — require_key doit lever, jamais silencer.

    Avant le fix, game_state.get('squad_cache', {}) retournait {} et faisait croire que
    toutes les unités n'ont pas de cache entry, les ignorant silencieusement (T1).
    """
    from engine.phase_handlers.command_handlers import _apply_return_destroyed_models

    gs = _state_with_painboy_and_destroyed(n_alive=2, n_destroyed=3)
    del gs["squad_cache"]  # simuler l'absence du cache

    from shared.data_validation import ConfigurationError

    with pytest.raises(ConfigurationError):
        _apply_return_destroyed_models(gs, 1)
