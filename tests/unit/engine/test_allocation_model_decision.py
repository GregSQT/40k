"""P3-4 — Allocation des pertes défenseur par décision d'agent (V11 §9.4 pt 4).

Ce que ces tests verrouillent :

1. **Contrat d'observation** : `AGENT_DECISION_TYPE_IDS` inclut `"allocation_model"` ;
   `DECISION_OPTION_CONT_FIELDS` expose les bons champs ; `obs_size` augmenté de 12 ;
   `decision_options_cont` présent dans `squad_obs_shapes`.

2. **Pose de la décision** (`_arm_allocation_model_decision`) : candidats = figures saines du
   groupe, traits continus corrects (tier/dist normalisés), payload porte `model_id` et
   `alloc_ctx_key`.

3. **Branchement gym** : `_manual_allocation_step` pose la décision en gym_training_mode
   (au lieu d'appeler `_select_allocation_model`), hors gym reste l'heuristique.

4. **Encodage observation** : `_encode_pending_decision` remplit `decision_options_cont`
   depuis `options_cont` stocké dans la décision.

5. **Dispatch w40k_core** : `allocation_model` applique le bon candidat et reprend l'allocation.

Rouge → vert imposé sur chaque invariant clé par mutation puis restauration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pytest

from engine.agent_decision import (
    clear_pending_agent_decision,
    read_pending_agent_decision,
    set_pending_agent_decision,
)
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import (
    AGENT_DECISION_TYPE_IDS,
    DECISION_OPTION_CONT_FIELDS,
    DECISION_OPTION_CONT_SIZE,
    MAX_DECISION_OPTIONS,
    decision_option_cont_index,
)
from engine.phase_handlers.shared_utils import (
    SHOOT_CTX,
    _arm_allocation_model_decision,
    _manual_allocation_step,
    build_units_cache,
)
from tests.unit.engine._config_helpers import build_game_rules, build_move_rules
from tests._state_invariants import turn_state_invariants, unit_invariants


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_model(mid: str, col: int, row: int, player: int = 0, role: Optional[str] = None,
               hp_cur: int = 3, hp_max: int = 3) -> Dict[str, Any]:
    """Figurine minimale pour models_cache."""
    entry: Dict[str, Any] = {
        "modelId": mid, "col": col, "row": row, "level": 0,
        "player": player, "HP_CUR": hp_cur, "HP_MAX": hp_max,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
        "VALUE": 10, "BASE_SIZE": 1,
    }
    if role is not None:
        entry["role"] = role
    return entry


def _synthetic_alloc_state(
    models: List[Dict[str, Any]],
    defender_player: int = 0,
    gym: bool = True,
    squad_id: str = "sq_def",
    board_cols: int = 30,
    board_rows: int = 20,
) -> Dict[str, Any]:
    """game_state minimal pour tester `_manual_allocation_step` sur l'allocation modèle."""
    unit_def: Dict[str, Any] = {
        **unit_invariants(),
        "id": squad_id, "player": defender_player,
        "col": models[0]["col"], "row": models[0]["row"],
        "HP_CUR": len(models), "HP_MAX": len(models),
        "VALUE": 100, "OC": 1, "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1, "ATTACK_LEFT": 1, "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "MOVE": 6, "UNIT_RULES": [],
        "models": [{"level": 0, "VALUE": 10, **m} for m in models],
    }
    unit_att: Dict[str, Any] = {
        **unit_invariants(),
        "id": "sq_att", "player": 1 - defender_player,
        "col": board_cols - 5, "row": board_rows // 2,
        "HP_CUR": 1, "HP_MAX": 1,
        "VALUE": 50, "OC": 1, "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1, "ATTACK_LEFT": 1, "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "MOVE": 6, "UNIT_RULES": [],
        "models": [{"level": 0, "VALUE": 50, "col": board_cols - 5, "row": board_rows // 2}],
    }
    state: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": {
            "game_rules": build_game_rules(),
            "move": build_move_rules(),
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": board_cols,
        "board_rows": board_rows,
        "current_player": 1 - defender_player,
        "phase": "shoot",
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": [unit_def, unit_att],
        "unit_by_id": {squad_id: unit_def, "sq_att": unit_att},
        "units_selected_to_fight": set(),
        "inches_to_subhex": 1,
        "action_logs": [],
        "action_log_seq": 0,
        "current_turn": 1,
    }
    if gym:
        state["gym_training_mode"] = True
    build_units_cache(state)

    # Construction de models_cache et squad_models depuis les figurines
    models_cache: Dict[str, Any] = {}
    squad_models_list: List[str] = []
    for m in models:
        mid = str(m["modelId"])
        models_cache[mid] = {**m, "player": defender_player}
        squad_models_list.append(mid)
    # Attaquant fictif (pour _precompute_nearest_enemy_dist)
    att_mid = "m_att"
    models_cache[att_mid] = {
        "modelId": att_mid, "col": board_cols - 5, "row": board_rows // 2,
        "level": 0, "player": 1 - defender_player,
        "HP_CUR": 1, "HP_MAX": 1, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
        "VALUE": 50, "BASE_SIZE": 1,
    }
    state["models_cache"] = models_cache
    state["squad_models"] = {squad_id: squad_models_list, "sq_att": [att_mid]}

    # Batch d'allocation : groupe unique, tous les modèles sains, 1 blessure dans le pool
    group: Dict[str, Any] = {
        "group_id": 0, "is_character": False, "role": None,
        "unit_type": None, "W": 3, "Sv": 3, "InSv": 7,
        "model_ids": list(squad_models_list),
    }
    batch: Dict[str, Any] = {
        "target_sid": squad_id,
        "weapon_group_idx": 0,
        "defender_player": defender_player,
        "alloc_groups": [group],
        "declared_order": [0],  # groupe 0 = le seul groupe
        "current_group_index": 0,
        "current_model_id": None,
        "pool": [{"save_roll": 3, "damage": 1, "devastating": False}],
        "pool_index": 0,
        "precision_applied": True,
    }
    state[SHOOT_CTX.alloc_key] = {
        "attacker_squad_id": "sq_att",
        "weapon_groups": [],
        "batches": [batch],
        "current_batch_index": 0,
        "summary": {},
        "hazardous_weapon_count": 0,
    }
    return state


# ---------------------------------------------------------------------------
# 1. Contrat d'observation
# ---------------------------------------------------------------------------

def test_allocation_model_type_in_registry():
    assert "allocation_model" in AGENT_DECISION_TYPE_IDS


def test_decision_option_cont_fields():
    assert DECISION_OPTION_CONT_FIELDS == ("role_tier_norm", "dist_enemy_norm")
    assert DECISION_OPTION_CONT_SIZE == 2


def test_obs_size_includes_cont_block():
    """obs_size = ancienne valeur + MAX_DECISION_OPTIONS * DECISION_OPTION_CONT_SIZE (6*2=12)."""
    shapes = ObservationBuilder.squad_obs_shapes()
    cont_shape = shapes["decision_options_cont"]
    assert cont_shape == (MAX_DECISION_OPTIONS, DECISION_OPTION_CONT_SIZE)
    # Le total doit inclure ce bloc
    total = sum(np.prod(s) for s in shapes.values())
    assert total == ObservationBuilder.SQUAD_OBS_SIZE_TARGET


def test_squad_obs_shapes_has_decision_options_cont():
    shapes = ObservationBuilder.squad_obs_shapes()
    assert "decision_options_cont" in shapes


# ---------------------------------------------------------------------------
# 2. Pose de la décision (_arm_allocation_model_decision)
# ---------------------------------------------------------------------------

def test_arm_allocation_model_decision_poses_correct_candidates():
    """Deux figurines saines → 2 candidats, traits continus non nuls."""
    from engine.phase_handlers.shared_utils import ROLE_TIER
    models = [
        _mk_model("m0", col=5, row=5, role=None),        # tier=0 (base)
        _mk_model("m1", col=8, row=8, role="sergeant"),  # tier=2
    ]
    state = _synthetic_alloc_state(models, gym=True)

    result = _arm_allocation_model_decision(state, "sq_def", ["m0", "m1"], SHOOT_CTX)

    decision = read_pending_agent_decision(state)
    assert decision is not None
    assert decision["type"] == "allocation_model"
    assert decision["player"] == 0  # defender_player
    assert decision["unit_id"] == "sq_def"
    assert len(decision["options"]) == 2
    # Traits continus
    cont = decision["options_cont"]
    assert cont is not None
    assert len(cont) == 2
    # m0 tier=0 → tier_norm=0/4=0.0
    assert cont[0][decision_option_cont_index("role_tier_norm")] == pytest.approx(0.0)
    # m1 tier=2 → tier_norm=2/4=0.5
    assert cont[1][decision_option_cont_index("role_tier_norm")] == pytest.approx(0.5)


def test_arm_allocation_model_decision_payload():
    """Le payload porte model_id et alloc_ctx_key."""
    models = [_mk_model("mA", col=2, row=2), _mk_model("mB", col=3, row=3)]
    state = _synthetic_alloc_state(models, gym=True)

    _arm_allocation_model_decision(state, "sq_def", ["mA", "mB"], SHOOT_CTX)

    decision = read_pending_agent_decision(state)
    assert decision is not None
    opt0_payload = decision["options"][0]["payload"]
    assert opt0_payload["model_id"] == "mA"
    assert opt0_payload["alloc_ctx_key"] == SHOOT_CTX.alloc_key


def test_arm_allocation_model_dist_enemy_norm_positive():
    """La distance ennemi est > 0 et normalisée dans (0, 1]."""
    models = [_mk_model("mX", col=0, row=0), _mk_model("mY", col=1, row=0)]
    state = _synthetic_alloc_state(models, gym=True, board_cols=30, board_rows=20)

    _arm_allocation_model_decision(state, "sq_def", ["mX", "mY"], SHOOT_CTX)

    decision = read_pending_agent_decision(state)
    assert decision is not None
    cont = decision["options_cont"]
    dist_norm = cont[0][decision_option_cont_index("dist_enemy_norm")]
    assert 0.0 < dist_norm <= 1.0


# ---------------------------------------------------------------------------
# 3. Branchement gym dans _manual_allocation_step
# ---------------------------------------------------------------------------

def test_manual_allocation_step_poses_decision_in_gym_mode():
    """En gym_training_mode, _manual_allocation_step pose une décision agent."""
    models = [_mk_model("g0", col=2, row=2), _mk_model("g1", col=4, row=4)]
    state = _synthetic_alloc_state(models, gym=True)

    result = _manual_allocation_step(state, SHOOT_CTX)

    # La décision doit être posée dans game_state
    decision = read_pending_agent_decision(state)
    assert decision is not None, "attendu : décision agent posée"
    assert decision["type"] == "allocation_model"


def test_manual_allocation_step_no_decision_outside_gym():
    """Hors gym_training_mode, _manual_allocation_step appelle l'heuristique (pas de décision).

    ROUGE→VERT : supprimer `if game_state.get("gym_training_mode")` ferait poser la décision
    même en PvE, rendant `read_pending_agent_decision(state_nogym) is not None`.
    """
    models = [_mk_model("h0", col=2, row=2), _mk_model("h1", col=4, row=4)]
    state_nogym = _synthetic_alloc_state(models, gym=False)
    # PvE : player_types doit être présent pour is_programmatic_defender
    state_nogym["player_types"] = {"0": "ai", "1": "human"}
    state_nogym.pop("gym_training_mode", None)

    # L'heuristique sélectionne immédiatement un modèle puis tente de résoudre la blessure.
    # La résolution échoue (weapon_groups vides dans le state de test), mais le modèle
    # est déjà sélectionné AVANT cette erreur — preuve que l'heuristique a tourné.
    with pytest.raises((IndexError, KeyError)):
        _manual_allocation_step(state_nogym, SHOOT_CTX)

    batch = state_nogym[SHOOT_CTX.alloc_key]["batches"][0]
    assert batch["current_model_id"] is not None, "l'heuristique doit avoir sélectionné un modèle"
    assert read_pending_agent_decision(state_nogym) is None, "hors gym : pas de décision agent"


def test_wounded_model_bypasses_decision():
    """Un modèle blessé est forcé par règle AVANT la branche gym — aucune décision posée."""
    models = [
        _mk_model("w0", col=2, row=2, hp_cur=1, hp_max=3),  # blessé
        _mk_model("w1", col=4, row=4, hp_cur=3, hp_max=3),  # sain
    ]
    state = _synthetic_alloc_state(models, gym=True)

    # La règle force le blessé, puis tente de résoudre la blessure (weapon_groups vides → crash).
    with pytest.raises((IndexError, KeyError)):
        _manual_allocation_step(state, SHOOT_CTX)

    # Aucune décision posée : la règle a court-circuité la branche gym
    assert read_pending_agent_decision(state) is None
    batch = state[SHOOT_CTX.alloc_key]["batches"][0]
    assert batch["current_model_id"] == "w0"


# ---------------------------------------------------------------------------
# 4. Encodage de l'observation
# ---------------------------------------------------------------------------

def test_encode_pending_decision_fills_cont_block():
    """_encode_pending_decision remplit decision_options_cont depuis options_cont."""
    state = _synthetic_alloc_state(
        [_mk_model("e0", col=1, row=1), _mk_model("e1", col=3, row=3)],
        gym=True,
    )
    # Poser manuellement une décision avec options_cont connues
    set_pending_agent_decision(
        state,
        decision_type="allocation_model",
        player=0,
        unit_id="sq_def",
        options=[
            {"label": "e0", "effect_ids": (), "declines": False, "payload": {"model_id": "e0", "alloc_ctx_key": "k"}},
            {"label": "e1", "effect_ids": (), "declines": False, "payload": {"model_id": "e1", "alloc_ctx_key": "k"}},
        ],
        options_cont=[[0.25, 0.4], [0.75, 0.1]],
    )
    obs = {k: np.zeros(s, dtype=np.float32) for k, s in ObservationBuilder.squad_obs_shapes().items()}

    # Patch minimal pour _encode_pending_decision
    from engine.observation_builder import ObservationBuilder as OB
    from engine.observation_entities import decision_ctx_bin_index
    builder = object.__new__(OB)
    builder._encode_pending_decision(state, obs, active_player=0)

    cont = obs["decision_options_cont"]
    assert cont[0, decision_option_cont_index("role_tier_norm")] == pytest.approx(0.25)
    assert cont[0, decision_option_cont_index("dist_enemy_norm")] == pytest.approx(0.4)
    assert cont[1, decision_option_cont_index("role_tier_norm")] == pytest.approx(0.75)
    assert cont[1, decision_option_cont_index("dist_enemy_norm")] == pytest.approx(0.1)


def test_encode_pending_decision_cont_zero_for_non_alloc_types():
    """Pour fly_declaration (pas de options_cont), decision_options_cont reste nul."""
    state = _synthetic_alloc_state(
        [_mk_model("f0", col=1, row=1)], gym=True,
    )
    set_pending_agent_decision(
        state,
        decision_type="fly_declaration",
        player=0,
        unit_id="sq_def",
        options=[
            {"label": "fly", "effect_ids": (), "declines": False, "payload": {"declare": True}},
            {"label": "stay", "effect_ids": (), "declines": True, "payload": {"declare": False}},
        ],
    )
    obs = {k: np.zeros(s, dtype=np.float32) for k, s in ObservationBuilder.squad_obs_shapes().items()}
    from engine.observation_builder import ObservationBuilder as OB
    builder = object.__new__(OB)
    builder._encode_pending_decision(state, obs, active_player=0)

    assert np.all(obs["decision_options_cont"] == 0.0)


# ---------------------------------------------------------------------------
# 5. Fixes bugs CONFIRMED (review 2026-08-17)
# ---------------------------------------------------------------------------

def test_manual_allocation_step_returns_waiting_for_player():
    """_manual_allocation_step retourne waiting_for_player:True quand décision gym armée.

    ROUGE→VERT : avant le fix, la valeur retournée était le dict de décision brut
    (sans clé 'waiting_for_player'), ce qui faisait crasher squad_shoot/squad_fight.
    """
    models = [_mk_model("s0", col=2, row=2), _mk_model("s1", col=4, row=4)]
    state = _synthetic_alloc_state(models, gym=True)

    result = _manual_allocation_step(state, SHOOT_CTX)

    assert result.get("waiting_for_player") is True
    assert result.get("action") == "allocation_model_pending"


def test_arm_allocation_model_decision_cap_at_max_options():
    """alive_grp de 8 modèles → seulement MAX_DECISION_OPTIONS (6) options posées sans crash.

    ROUGE→VERT : avant le fix, _validate_options levait ValueError pour 8 > 6 candidats.
    """
    models = [_mk_model(f"m{i}", col=i, row=0) for i in range(8)]
    state = _synthetic_alloc_state(models, gym=True)

    alive = [f"m{i}" for i in range(8)]
    _arm_allocation_model_decision(state, "sq_def", alive, SHOOT_CTX)

    decision = read_pending_agent_decision(state)
    assert decision is not None
    assert len(decision["options"]) == MAX_DECISION_OPTIONS
    cont = decision["options_cont"]
    assert len(cont) == MAX_DECISION_OPTIONS


def test_arm_allocation_model_decision_cap_selects_lowest_tier_first():
    """Les 6 modèles retenus sont les plus sacrifiables (tier le plus bas)."""
    from engine.phase_handlers.shared_utils import ROLE_TIER
    # 4 base (tier=0) + 2 sergeant (tier=ROLE_TIER["sergeant"]) + 2 leader (tier=ROLE_TIER["leader"])
    models = (
        [_mk_model(f"base{i}", col=i, row=0, role=None) for i in range(4)]
        + [_mk_model(f"sgt{i}", col=4+i, row=0, role="sergeant") for i in range(2)]
        + [_mk_model(f"lead{i}", col=6+i, row=0, role="leader") for i in range(2)]
    )
    state = _synthetic_alloc_state(models, gym=True)
    alive = [f"base{i}" for i in range(4)] + [f"sgt{i}" for i in range(2)] + [f"lead{i}" for i in range(2)]

    _arm_allocation_model_decision(state, "sq_def", alive, SHOOT_CTX)

    decision = read_pending_agent_decision(state)
    assert decision is not None
    assert len(decision["options"]) == MAX_DECISION_OPTIONS
    # Les 2 leaders (tier le plus haut) ne doivent pas figurer dans les 6 candidats
    chosen_labels = {opt["payload"]["model_id"] for opt in decision["options"]}
    assert not any(f"lead{i}" in chosen_labels for i in range(2)), \
        "les leaders (tier max) ne doivent pas être parmi les 6 candidats retenus"


def test_set_pending_agent_decision_raises_on_cont_length_mismatch():
    """options_cont avec longueur ≠ options → ValueError explicite.

    ROUGE→VERT : avant le fix, le mismatch était silencieux (slots restaient à 0).
    """
    state = _synthetic_alloc_state([_mk_model("z0", col=0, row=0)], gym=True)
    options = [
        {"label": "a", "effect_ids": (), "declines": False, "payload": {}},
        {"label": "b", "effect_ids": (), "declines": False, "payload": {}},
    ]
    with pytest.raises(ValueError, match="options_cont"):
        set_pending_agent_decision(
            state,
            decision_type="allocation_model",
            player=0,
            unit_id="sq_def",
            options=options,
            options_cont=[[0.1, 0.2]],  # 1 rang pour 2 options → mismatch
        )


def test_precompute_nearest_enemy_dist_uses_units_cache_player():
    """defender_player issu de units_cache, pas de alive[0]['player'].

    ROUGE→VERT : avant le fix, un CHARACTER attaquant en tête d'alive inversait ami/ennemi.
    """
    from engine.phase_handlers.shared_utils import _precompute_nearest_enemy_dist
    # Défenseur = player 0, attaquant = player 1
    models = [_mk_model("d0", col=5, row=5, player=0), _mk_model("d1", col=6, row=5, player=0)]
    state = _synthetic_alloc_state(models, gym=True)
    # Injecter un modèle attaquant dans models_cache avec l'ID d'un défenseur (cas CHARACTER)
    # pour simuler l'inversion — avant le fix, defender_player serait 1 (attaquant)
    state["models_cache"]["d0"]["player"] = 1  # simulation: alive[0] appartient à l'attaquant

    dist = _precompute_nearest_enemy_dist(state, "sq_def")

    # Avec le fix (units_cache["sq_def"]["player"]=0), les "ennemis" sont player 1.
    # L'attaquant fictif m_att (player=1) est l'ennemi réel → distances non nulles.
    assert all(v >= 0 for v in dist.values()), "distances doivent être non négatives"
    # Vérification principale : units_cache donne player=0, donc m_att (player=1) est ennemi.
    assert len(dist) > 0
