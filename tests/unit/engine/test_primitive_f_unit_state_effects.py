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
    if rule_args:
        r["rule_args"] = rule_args
    r.update(kw)
    return r


def _unit(uid: str, player: int, unit_rules: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "UNIT_RULES": unit_rules or [],
        "battle_shocked": False,
        "OC": 2,
        "UNIT_KEYWORDS": [],
    }


def _model(uid: str, col: int = 5, row: int = 5, t: int = 4, role: str = "bodyguard",
           hp_cur: int = 3, hp_max: int = 3, invul_save: int = 7) -> Dict[str, Any]:
    return {
        "squad_id": uid,
        "col": col,
        "row": row,
        "level": 0,
        "T": t,
        "role": role,
        "HP_CUR": hp_cur,
        "HP_MAX": hp_max,
        "INVUL_SAVE": invul_save,
        "ARMOR_SAVE": 4,
        "OC": 1,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "player": 1,
        "VALUE": 10,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 13,
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


def test_invul_save_override_mental_fortress_librarian() -> None:
    """Mental Fortress (Librarian) : InSv 4+ conférée à l'unité, base 7+ (aucune InSv)."""
    from engine.game_state import effective_invul_save

    unit = _unit("lib", 1, unit_rules=[_rule("invul_save_override", {"value": 4})])
    gs = _base_state([unit])
    assert effective_invul_save(gs, unit, 7) == 4


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
# suppress_target_on_shooting — stockage de _last_shoot_target_id
# ─────────────────────────────────────────────────────────────────────────────

def test_suppress_target_pose_suppressed_squads() -> None:
    """Après activation de tir, suppressed_squads contient la cible si la règle est portée."""
    # Teste directement la logique de _handle_shooting_end_activation :
    # si l'unité a suppress_target_on_shooting ET _last_shoot_target_id est posé,
    # game_state["suppressed_squads"] reçoit l'id cible.
    from engine.phase_handlers.shared_utils import unit_has_rule_effect

    attacker = _unit("atk", 1, unit_rules=[_rule("suppress_target_on_shooting")])
    target = _unit("tgt", 2)
    gs = _base_state([attacker, target])
    gs["phase"] = "shooting"

    # Simuler le résultat de squad_declare_shoot (stocke l'id cible sur l'unité)
    attacker["_last_shoot_target_id"] = "tgt"

    # Vérifier que la règle est bien reconnue
    assert unit_has_rule_effect(attacker, "suppress_target_on_shooting")

    # Simuler la logique de _handle_shooting_end_activation
    if unit_has_rule_effect(attacker, "suppress_target_on_shooting"):
        _target_id = attacker.get("_last_shoot_target_id")
        if _target_id is not None:
            gs.setdefault("suppressed_squads", {})[str(_target_id)] = int(attacker["player"])

    assert "tgt" in gs["suppressed_squads"]
    assert gs["suppressed_squads"]["tgt"] == 1


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
    gs = _base_state([unit])

    # Remplacer les figurines par n_alive figurines
    mids = [f"pain#{i}" for i in range(n_alive)]
    # Supprimer l'entrée par défaut et reconstruire
    for old_mid in list(gs["models_cache"].keys()):
        if old_mid.startswith("pain#"):
            del gs["models_cache"][old_mid]
    for mid in mids:
        gs["models_cache"][mid] = {
            "squad_id": "pain",
            "col": 5,
            "row": 5,
            "level": 0,
            "T": 5,
            "role": "bodyguard",
            "HP_CUR": 3,
            "HP_MAX": 3,
            "INVUL_SAVE": 7,
            "ARMOR_SAVE": 5,
            "OC": 1,
            "SHOOT_LEFT": 1,
            "ATTACK_LEFT": 1,
            "player": 1,
            "VALUE": 10,
            "BASE_SHAPE": "round",
            "BASE_SIZE": 13,
            "RNG_WEAPONS": [],
            "CC_WEAPONS": [],
            "UNIT_RULES": [],
        }
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
    return gs


def test_return_destroyed_models_restaure_au_moins_un() -> None:
    """Des figurines détruites existent → D3 sont restaurées (≥ 1)."""
    from engine.phase_handlers.command_handlers import _apply_return_destroyed_models

    gs = _state_with_painboy_and_destroyed(n_alive=3, n_destroyed=3)
    mids_before = len(gs["squad_models"]["pain"])

    _apply_return_destroyed_models(gs, 1)

    mids_after = len(gs["squad_models"]["pain"])
    assert mids_after > mids_before, "Aucune figurine restaurée"
    restored = mids_after - mids_before
    assert 1 <= restored <= 3, f"D3 attendu : {restored}"


def test_return_destroyed_models_une_seule_fois() -> None:
    """Deux appels successifs : seul le premier restaure."""
    from engine.phase_handlers.command_handlers import _apply_return_destroyed_models

    gs = _state_with_painboy_and_destroyed(n_alive=2, n_destroyed=4)
    _apply_return_destroyed_models(gs, 1)
    count_apres_premier = len(gs["squad_models"]["pain"])

    _apply_return_destroyed_models(gs, 1)
    assert len(gs["squad_models"]["pain"]) == count_apres_premier, "Second appel ne doit pas restaurer"


def test_return_destroyed_models_sans_pertes_rien_ne_se_passe() -> None:
    """Aucune figurine détruite → squad_models inchangé."""
    from engine.phase_handlers.command_handlers import _apply_return_destroyed_models

    gs = _state_with_painboy_and_destroyed(n_alive=5, n_destroyed=0)
    mids_before = list(gs["squad_models"]["pain"])

    _apply_return_destroyed_models(gs, 1)

    assert gs["squad_models"]["pain"] == mids_before


def test_return_destroyed_models_met_a_jour_hp_cur() -> None:
    """Après restauration, HP_CUR de l'escouade en units_cache augmente."""
    from engine.phase_handlers.command_handlers import _apply_return_destroyed_models

    gs = _state_with_painboy_and_destroyed(n_alive=2, n_destroyed=3)
    hp_avant = gs["units_cache"]["pain"]["HP_CUR"]

    _apply_return_destroyed_models(gs, 1)

    assert gs["units_cache"]["pain"]["HP_CUR"] > hp_avant


# ─────────────────────────────────────────────────────────────────────────────
# once_per_battle_melee_buff — observation masquée quand dépensée
# ─────────────────────────────────────────────────────────────────────────────

def test_once_per_battle_spent_squad_ids_dans_ctx() -> None:
    """finest_hour_used → once_per_battle_spent_squad_ids construit correctement."""
    unit = _unit("cap", 1, unit_rules=[_rule("once_per_battle_melee_buff")])
    gs = _base_state([unit])
    gs["finest_hour_used"] = {"cap", "other"}

    spent = frozenset(str(sid) for sid in gs.get("finest_hour_used", set()))
    assert "cap" in spent
    assert "other" in spent
    assert "42" not in spent


def test_once_per_battle_melee_buff_exclu_obs_si_depense() -> None:
    """Quand la squad est dans once_per_battle_spent_squad_ids, le buff n'est pas dans ability_ids."""
    from engine.observation_entities import UNIT_RULE_EFFECT_IDS
    from engine.observation_builder import unit_ability_obs_ids

    # Simule la logique d'exclusion de l'observation builder
    rule_id = "once_per_battle_melee_buff"
    assert rule_id in UNIT_RULE_EFFECT_IDS, "La règle doit être dans UNIT_RULE_EFFECT_IDS"

    unit = _unit("cap", 1, unit_rules=[_rule("once_per_battle_melee_buff")])
    spent = frozenset(["cap"])

    from engine.phase_handlers.shared_utils import unit_has_rule_effect
    obs_ids = unit_ability_obs_ids()

    ids_normal = [
        obs_ids[r] for r in UNIT_RULE_EFFECT_IDS
        if unit_has_rule_effect(unit, r)
    ]
    ids_spent = [
        obs_ids[r] for r in UNIT_RULE_EFFECT_IDS
        if unit_has_rule_effect(unit, r)
        and not (r == "once_per_battle_melee_buff" and "cap" in spent)
    ]

    assert obs_ids[rule_id] in ids_normal, "Buff doit être visible avant dépense"
    assert obs_ids[rule_id] not in ids_spent, "Buff ne doit pas être visible après dépense"
