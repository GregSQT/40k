"""V11 §9.3 (P2) — mécanisme générique « décision agent », et son pilote `rule_choice`.

Ce que ces tests verrouillent, dans l'ordre de la chaîne :

1. **le contrat** (`engine/agent_decision.py`) : aucun candidat n'est tronqué, aucune décision
   n'en écrase une autre, aucun effet hors du vocabulaire d'observation n'est accepté ;
2. **le masque** : une décision en attente rend `CHOICE_0..n-1` EXCLUSIVES — c'est ce qui arrête
   le moteur sur le point de choix, comme un `waiting_for_player` PvP ;
3. **l'observation** : le bloc décrit le type ET chaque candidat, et reste NUL pour l'autre camp ;
4. **le bout en bout gym** : un prompt de rule choice n'est plus tranché par
   `raw_action_int % len(options)` (§9.4 point 0) — l'agent le voit, le joue, et le moteur
   applique EXACTEMENT le candidat désigné ;
5. **la non-régression PvP/PvE** : hors gym, le flux `waiting_for_rule_choice` est intact.

⚠️ Le test le plus important du fichier est `test_choice_action_applies_the_designated_option` :
il vérifie que `CHOICE_i` applique le candidat `i` — l'alignement obs/action/moteur. Une
permutation ne lèverait nulle part et ferait apprendre à l'agent l'inverse de ce qu'il choisit.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pytest

from engine.action_decoder import ActionDecoder
from engine.agent_decision import (
    clear_pending_agent_decision,
    read_pending_agent_decision,
    set_pending_agent_decision,
)
from engine.macro_intents import CHOICE_BASE, CHOICE_COUNT, TOTAL_ACTION_SIZE
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import (
    MAX_DECISION_OPTIONS,
    decision_ctx_bin_index,
    decision_option_bin_index,
)
from engine.phase_handlers.shared_utils import (
    build_enemy_adjacent_hexes,
    build_units_cache,
    rebuild_choice_timing_index,
)
from engine.w40k_core import W40KEngine

from _config_helpers import build_move_rules
from tests._state_invariants import turn_state_invariants

#: Le SEUL choix de règle du jeu aujourd'hui (Tyranid Warrior mêlée) : `adrenalised_onslaught`
#: accorde `aggression_imperative` (alias de `reroll_1_tohit_fight`) OU `preservation_imperative`
#: (alias de `reroll_1_save_fight`). Les deux effets techniques appartiennent au vocabulaire
#: d'observation `UNIT_RULE_EFFECT_IDS` — c'est ce qui rend les candidats descriptibles.
CHOICE_RULE = {
    "ruleId": "adrenalised_onslaught",
    "displayName": "Adrenalised Onslaught",
    "grants_rule_ids": ["aggression_imperative", "preservation_imperative"],
    "usage": "or",
    "choice_timing": {
        "trigger": "phase_start",
        "phase": "fight",
        "active_player_scope": "both",
    },
}


def _config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "max_turns": 5,
            "engagement_zone": 1,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
            "cover_ratio": 0.0,
        },
        "move": build_move_rules(),
        "charge": {"charge_max_distance": 12},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        "gym_training_mode": True,
        "pve_mode": False,
        "observation_params": {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET},
    }


def _unit(uid: int, player: int, col: int, row: int, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 3,
        "HP_MAX": 3,
        "VALUE": 100,
        "OC": 1,
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": rules,
        # Pose par le moteur au deploiement (clause 2 de [HEAVY] 24.16) ; l'observation en derive
        # le one-hot de mise en place, et l'exige.
        "deployed_on_turn": 0,
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
    }


def _game_state(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": _config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": "fight",
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "episode_number": 1,
        "episode_steps": 0,
        "turn_limit_reached": False,
        "game_over": False,
        "units_moved": set(),
        "units_advanced": set(),
        "units_fled": set(),
        "units_shot": set(),
        "units_charged": set(),
        "units_fought": set(),
        "units_cannot_charge": set(),
        "units_attacked": set(),
        "units_reacted_this_enemy_turn": set(),
        "reaction_window_active": False,
        "_unit_move_version": 0,
        "last_move_event_id": 0,
        "last_move_cause": "normal",
        "reactive_mode": "micro",
        "reactive_macro_order_current_window": [],
        "reactive_decision_mode": "auto",
        "reactive_decision_payload": {},
        "move_activation_pool": [],
        "shoot_activation_pool": [],
        "charge_activation_pool": [],
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "valid_move_destinations_pool": [],
        "preview_hexes": [],
        "move_preview_footprint_span": None,
        "active_movement_unit": None,
        "fight_subphase": None,
        "hex_los_cache": {},
        "los_cache": {},
        "player_types": {"1": "ai", "2": "ai"},
        "gym_training_mode": True,
        "objectives": [{"id": "obj1", "hexes": [[5, 5]]}],
        "inches_to_subhex": 1,
        "victory_points": {1: 0, 2: 0},
        "objective_controllers": {},
        "moved_distance_by_model": {},
    }
    build_units_cache(gs)
    # `build_units_cache` (re)calcule `value_at_start` sur les seuls joueurs presents : on
    # complete APRES, sinon l'observation d'un camp absent leve sur sa force d'usure.
    gs["value_at_start"] = {1: 100.0, 2: 100.0}
    build_enemy_adjacent_hexes(gs, gs["current_player"])
    rebuild_choice_timing_index(gs)
    return gs


def _engine(gs: Dict[str, Any], gym_training_mode: bool = True) -> W40KEngine:
    engine = object.__new__(W40KEngine)
    engine.game_state = gs
    engine.step_logger = None
    engine.gym_training_mode = gym_training_mode
    gs["gym_training_mode"] = gym_training_mode
    gs["config"]["gym_training_mode"] = gym_training_mode
    engine.config = gs["config"]
    engine.is_pve_mode = False
    engine._shooting_phase_initialized = False
    engine._movement_phase_initialized = False
    engine.action_decoder = ActionDecoder(gs["config"])
    engine.obs_builder = ObservationBuilder(gs["config"])
    return engine


def _two_options() -> List[Dict[str, Any]]:
    return [
        {"label": "A", "effect_ids": ("reroll_1_tohit_fight",), "payload": {"display_rule_id": "a"}},
        {"label": "B", "effect_ids": ("reroll_1_save_fight",), "payload": {"display_rule_id": "b"}},
    ]


def _push(gs: Dict[str, Any], player: int = 1, options=None) -> None:
    set_pending_agent_decision(
        gs,
        decision_type="rule_choice",
        player=player,
        unit_id="1",
        options=_two_options() if options is None else options,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Contrat du mécanisme
# ─────────────────────────────────────────────────────────────────────────────


def test_no_pending_decision_by_default():
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    assert read_pending_agent_decision(gs) is None


def test_more_candidates_than_choice_actions_raises():
    """AUCUNE troncature (§9.0bis réserve 2) : un top-K silencieux exclurait l'optimum."""
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    too_many = [
        {"label": f"opt{i}", "effect_ids": ("reroll_1_towound",), "payload": {}}
        for i in range(MAX_DECISION_OPTIONS + 1)
    ]
    with pytest.raises(ValueError, match="intentions scorees"):
        _push(gs, options=too_many)


def test_single_candidate_is_not_a_decision():
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    with pytest.raises(ValueError, match="au moins 2 candidats"):
        _push(gs, options=_two_options()[:1])


def test_unknown_decision_type_raises():
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    with pytest.raises(KeyError, match="inconnu"):
        set_pending_agent_decision(
            gs, decision_type="whatever", player=1, unit_id="1", options=_two_options()
        )


def test_effect_outside_the_observation_vocabulary_raises():
    """Un candidat que l'agent ne pourrait pas percevoir LÈVE — il n'est pas décrit par un zéro."""
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    options = _two_options()
    options[0]["effect_ids"] = ("some_unobserved_rule",)
    with pytest.raises(KeyError, match="UNIT_RULE_EFFECT_IDS"):
        _push(gs, options=options)


def test_second_decision_never_overwrites_the_first():
    """Le moteur rend la main après CHAQUE décision : deux à la fois = état incohérent."""
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    _push(gs)
    with pytest.raises(RuntimeError, match="deja en attente"):
        _push(gs)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Masque et décodage
# ─────────────────────────────────────────────────────────────────────────────


def test_pending_decision_masks_everything_but_the_candidates():
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    engine = _engine(gs)
    _push(gs)
    mask, eligible = engine.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert eligible == []
    assert mask.sum() == 2, "seuls les 2 candidats doivent etre jouables"
    assert bool(mask[CHOICE_BASE]) and bool(mask[CHOICE_BASE + 1])
    assert not bool(mask[CHOICE_BASE + 2])
    assert not mask[:CHOICE_BASE].any(), "une action de phase reste jouable pendant une decision"


def test_choice_action_decodes_to_agent_decision():
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    engine = _engine(gs)
    _push(gs)
    semantic = engine.action_decoder.convert_squad_action(CHOICE_BASE + 1, gs)
    assert semantic == {"action": "agent_decision", "option_index": 1}


def test_choice_action_without_pending_decision_raises():
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    engine = _engine(gs)
    with pytest.raises(ValueError, match="sans decision en attente"):
        engine.action_decoder.convert_squad_action(CHOICE_BASE, gs)


def test_choice_action_beyond_the_candidate_count_raises():
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    engine = _engine(gs)
    _push(gs)
    with pytest.raises(ValueError, match="inexistant"):
        engine.action_decoder.convert_squad_action(CHOICE_BASE + 2, gs)


def test_choice_actions_are_inside_the_action_space():
    # Les CHOICE ne ferment plus l'action space depuis le chantier 01 : les 20 slots d'Oath of
    # Moment les suivent. Ce qui compte ici reste vrai — elles sont dans l'espace, et il y en a
    # exactement autant que de candidats observables.
    assert CHOICE_BASE + CHOICE_COUNT <= TOTAL_ACTION_SIZE
    assert CHOICE_COUNT == MAX_DECISION_OPTIONS


# ─────────────────────────────────────────────────────────────────────────────
# 3. Observation du contexte de décision
# ─────────────────────────────────────────────────────────────────────────────


def test_observation_describes_the_type_and_every_candidate():
    gs = _game_state([_unit(1, 1, 5, 10, []), _unit(2, 2, 15, 10, [])])
    engine = _engine(gs)
    _push(gs)
    obs = engine.obs_builder.build_squad_observation(gs, "1")
    ctx = obs["decision_ctx_bin"]
    assert ctx[decision_ctx_bin_index("decision_pending")] == 1.0
    assert ctx[decision_ctx_bin_index("decision_type_rule_choice")] == 1.0

    options = obs["decision_options_bin"]
    assert options[0, decision_option_bin_index("grants_reroll_1_tohit_fight")] == 1.0
    assert options[1, decision_option_bin_index("grants_reroll_1_save_fight")] == 1.0
    # Un candidat ne porte QUE son propre effet.
    assert options[0, decision_option_bin_index("grants_reroll_1_save_fight")] == 0.0
    # Le masque `present` porte le NOMBRE de candidats.
    present = options[:, decision_option_bin_index("present")]
    assert list(present) == [1.0, 1.0] + [0.0] * (MAX_DECISION_OPTIONS - 2)


def test_observation_of_the_other_camp_stays_empty():
    """Décrire à un joueur un choix qui n'est pas le sien lui montrerait des candidats injouables."""
    gs = _game_state([_unit(1, 1, 5, 10, []), _unit(2, 2, 15, 10, [])])
    engine = _engine(gs)
    _push(gs, player=2)
    obs = engine.obs_builder.build_squad_observation(gs, "1")
    assert obs["decision_ctx_bin"].sum() == 0.0
    assert obs["decision_options_bin"].sum() == 0.0


def test_observation_is_empty_without_a_decision():
    gs = _game_state([_unit(1, 1, 5, 10, []), _unit(2, 2, 15, 10, [])])
    engine = _engine(gs)
    obs = engine.obs_builder.build_squad_observation(gs, "1")
    assert obs["decision_ctx_bin"].sum() == 0.0
    assert obs["decision_options_bin"].sum() == 0.0


def test_observation_shapes_are_part_of_the_contract():
    shapes = ObservationBuilder.squad_obs_shapes()
    assert shapes["decision_options_bin"][0] == MAX_DECISION_OPTIONS
    total = sum(int(np.prod(shape)) for shape in shapes.values())
    assert total == ObservationBuilder.SQUAD_OBS_SIZE_TARGET


# ─────────────────────────────────────────────────────────────────────────────
# 4. Bout en bout : le pilote `rule_choice` (§9.4 point 0)
# ─────────────────────────────────────────────────────────────────────────────


def _emit_fight_phase_choice(engine: W40KEngine) -> Dict[str, Any]:
    engine._initialize_rule_choice_runtime_state()
    engine._enqueue_rule_choice_candidates(
        trigger="phase_start", event_phase="fight", event_player=1
    )
    result = engine._emit_next_rule_choice_prompt_if_needed()
    assert result is not None, "le prompt de choix n'a pas ete emis"
    return result


def test_gym_emits_a_decision_instead_of_deciding_for_the_agent():
    """Le moteur rend la main — il ne tranche plus `raw_action_int % len(options)`."""
    gs = _game_state([_unit(1, 1, 5, 10, [dict(CHOICE_RULE)])])
    engine = _engine(gs)
    result = _emit_fight_phase_choice(engine)

    assert result["action"] == "waiting_for_agent_decision"
    assert result["waiting_for_player"] is True
    decision = read_pending_agent_decision(gs)
    assert decision is not None
    assert decision["type"] == "rule_choice"
    assert decision["unit_id"] == "1"
    assert [option["label"] for option in decision["options"]] == [
        "Aggression Imperative", "Preservation Imperative",
    ]
    # Les candidats sont décrits par l'effet TECHNIQUE que leur alias résout.
    assert [option["effect_ids"] for option in decision["options"]] == [
        ("reroll_1_tohit_fight",), ("reroll_1_save_fight",),
    ]
    # Rien n'a encore été appliqué : c'est l'agent qui choisit.
    assert "_selected_granted_rule_id" not in gs["units"][0]["UNIT_RULES"][0]


@pytest.mark.parametrize(
    "option_index,expected_rule",
    [(0, "aggression_imperative"), (1, "preservation_imperative")],
)
def test_choice_action_applies_the_designated_option(option_index: int, expected_rule: str):
    """⚠️ ALIGNEMENT `CHOICE_i` -> candidat `i` -> règle appliquée. Le test central du chantier."""
    gs = _game_state([_unit(1, 1, 5, 10, [dict(CHOICE_RULE)])])
    engine = _engine(gs)
    _emit_fight_phase_choice(engine)

    mask, _eligible = engine.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    action_int = CHOICE_BASE + option_index
    assert bool(mask[action_int])
    semantic = engine.action_decoder.convert_squad_action(action_int, gs)
    success, result = engine._process_squad_action(semantic)

    assert success is True
    assert result["selectedRuleId"] == expected_rule
    assert gs["units"][0]["UNIT_RULES"][0]["_selected_granted_rule_id"] == expected_rule
    # La décision est consommée, la file avance, le moteur repart.
    assert read_pending_agent_decision(gs) is None
    assert gs["pending_rule_choice_queue"] == []
    mask_after, _ = engine.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert not mask_after[CHOICE_BASE:TOTAL_ACTION_SIZE].any()


def test_two_queued_prompts_are_decided_one_after_the_other():
    """Un même événement peut empiler plusieurs prompts : chacun rend la main à son tour."""
    gs = _game_state(
        [_unit(1, 1, 5, 10, [dict(CHOICE_RULE)]), _unit(2, 1, 7, 10, [dict(CHOICE_RULE)])]
    )
    engine = _engine(gs)
    _emit_fight_phase_choice(engine)
    first = read_pending_agent_decision(gs)
    assert first is not None and first["unit_id"] == "1"

    success, result = engine._process_squad_action(
        engine.action_decoder.convert_squad_action(CHOICE_BASE, gs)
    )
    assert success is True
    # Le second prompt a REPOSÉ une décision au lieu de laisser le moteur repartir.
    assert result["action"] == "waiting_for_agent_decision"
    second = read_pending_agent_decision(gs)
    assert second is not None and second["unit_id"] == "2"

    engine._process_squad_action(engine.action_decoder.convert_squad_action(CHOICE_BASE + 1, gs))
    assert read_pending_agent_decision(gs) is None
    assert gs["units"][0]["UNIT_RULES"][0]["_selected_granted_rule_id"] == "aggression_imperative"
    assert gs["units"][1]["UNIT_RULES"][0]["_selected_granted_rule_id"] == "preservation_imperative"


def test_agent_decision_action_without_pending_decision_is_refused():
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    engine = _engine(gs)
    success, result = engine._process_squad_action(
        {"action": "agent_decision", "option_index": 0}
    )
    assert success is False
    assert result["error"] == "no_pending_agent_decision"


def test_observation_follows_the_unit_of_the_decision():
    """L'observateur est l'unité SUR LAQUELLE porte le choix, pas la première venue."""
    gs = _game_state([_unit(1, 1, 5, 10, []), _unit(2, 1, 7, 10, [])])
    engine = _engine(gs)
    # Sourdine assumee : `state_manager` est declare `GameStateManager` sur W40KEngine, et ce
    # test substitue une doublure qui n'expose QUE `refresh_objective_control_on_boundary` —
    # la seule methode que `_build_observation` appelle ici. Construire un vrai
    # GameStateManager (config + registre + plateau) pour ce seul appel rendrait le test
    # dependant de tout l'etat qu'il n'observe pas. pyright signale donc un ecart reel et
    # voulu, pas un defaut du code de production.
    engine.state_manager = _StubStateManager()  # pyright: ignore[reportAttributeAccessIssue]
    set_pending_agent_decision(
        gs, decision_type="rule_choice", player=1, unit_id="2", options=_two_options()
    )
    obs = engine._build_observation()
    reference = engine.obs_builder.build_squad_observation(gs, "2")
    assert np.array_equal(obs["allies_cont"], reference["allies_cont"])


class _StubStateManager:
    """`_build_observation` ne rafraîchit le contrôle d'objectif que sur frontière de phase."""

    def refresh_objective_control_on_boundary(self, game_state: Dict[str, Any]) -> None:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Non-régression PvP / PvE
# ─────────────────────────────────────────────────────────────────────────────


def test_human_flow_is_untouched():
    """Hors gym, un joueur humain reçoit toujours `waiting_for_rule_choice` — pas de décision."""
    gs = _game_state([_unit(1, 1, 5, 10, [dict(CHOICE_RULE)])])
    gs["player_types"] = {"1": "human", "2": "ai"}
    engine = _engine(gs, gym_training_mode=False)
    engine._initialize_rule_choice_runtime_state()
    engine._enqueue_rule_choice_candidates(
        trigger="phase_start", event_phase="fight", event_player=1
    )
    result = engine._emit_next_rule_choice_prompt_if_needed()
    assert result is not None
    assert result["action"] == "waiting_for_rule_choice"
    assert read_pending_agent_decision(gs) is None
    assert gs["active_rule_choice_prompt"] is not None


def test_clearing_a_decision_reopens_the_normal_mask():
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    engine = _engine(gs)
    _push(gs)
    clear_pending_agent_decision(gs)
    mask, _eligible = engine.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert not mask[CHOICE_BASE:TOTAL_ACTION_SIZE].any()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Effets de bord vérifiés par mesure : grille de move, et journal step.log
# ─────────────────────────────────────────────────────────────────────────────


def test_move_cost_channel_is_empty_while_a_decision_is_pending():
    """En phase move, une décision en attente laisse le canal de coût à ZÉRO.

    Le canal est peint depuis la carte de cellules MÉMOÏSÉE par le masque. Pendant une décision,
    le masque n'expose que les `CHOICE_i` : aucune carte n'existe, et il n'y en a pas à
    construire (aucune activation de move n'est en cours). En redemander une relancerait un BFS
    pour peindre des destinations que l'agent ne peut pas jouer.
    """
    from engine.spatial_grid import GRID_CH_MOVE_COST

    gs = _game_state([_unit(1, 1, 5, 10, []), _unit(2, 2, 15, 10, [])])
    gs["phase"] = "move"
    engine = _engine(gs)
    _push(gs)
    grid = engine.obs_builder.build_squad_grid(gs, "1")
    assert float(np.abs(grid[GRID_CH_MOVE_COST]).sum()) == 0.0


def test_a_decision_writes_exactly_one_step_log_line(tmp_path):
    """Une décision jouée = UNE ligne de step.log, et aucune erreur avalée.

    `_record_rule_choice_action_log` écrit la ligne directement ; le flush T6-c ne doit PAS la
    réécrire. Quand `rule_choice` était dans `_STEP_LOG_TYPE_MAP`, la seconde tentative échouait
    en silence (`selectedRuleName` vs `selected_rule_name`) — mesuré : une erreur avalée par
    choix. La corriger telle quelle aurait produit un doublon.
    """
    from ai.step_logger import StepLogger

    gs = _game_state([_unit(1, 1, 5, 10, [dict(CHOICE_RULE)])])
    engine = _engine(gs)
    log_path = tmp_path / "step.log"
    engine.step_logger = StepLogger(output_file=str(log_path), enabled=True, buffer_size=1)
    _emit_fight_phase_choice(engine)
    engine._process_squad_action(engine.action_decoder.convert_squad_action(CHOICE_BASE, gs))
    engine.step_logger._flush_buffer()

    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if "chose [" in line]
    assert len(lines) == 1, f"attendu UNE ligne de choix, trouve {len(lines)} : {lines}"
    assert "AGGRESSION IMPERATIVE" in lines[0]
    assert "rule_choice" not in W40KEngine._STEP_LOG_TYPE_MAP, (
        "le flush journaliserait une seconde fois un choix deja ecrit en direct"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Ce que la décision coûte au reste du pipeline : reward et compteur de steps
# ─────────────────────────────────────────────────────────────────────────────


def _reward_calculator():
    """`RewardCalculator` sur la config d'agent REELLE : `system_penalties` en vient."""
    from config_loader import get_config_loader
    from engine.reward_calculator import RewardCalculator

    rewards_config = get_config_loader().load_agent_rewards_config("ArmageddonAgent")
    return RewardCalculator(
        {"controlled_agent": "ArmageddonAgent", "controlled_player": 1, "quiet": True},
        rewards_config,
    )


def test_a_decision_earns_no_reward_of_its_own():
    """Jouer `CHOICE_i` ne rapporte RIEN par soi-même — explicitement, pas par accident.

    Le crédit d'un choix vient de ses conséquences ; une prime à l'acte de choisir serait du
    reward shaping introduit en silence, ce que §9.6 interdit. Avant cette branche explicite, la
    neutralité tenait à la seule présence de `waiting_for_player` dans le payload.
    """
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    calculator = _reward_calculator()
    # 0.0 EN DUR des deux côtés : la neutralité ne doit dépendre d'AUCUNE clé de config tunable
    # (un `system_response` retouché rendrait les décisions coûteuses en silence).
    for payload in (
        {"action": "agent_decision", "unitId": "1", "player": 1, "option_index": 0},
        {"action": "waiting_for_agent_decision", "unitId": "1", "player": 1},
    ):
        assert calculator.calculate_reward(True, payload, gs) == 0.0


def test_a_decision_reward_does_not_depend_on_the_waiting_flag():
    """Mutation de contrôle : sans `waiting_for_player`, le reward reste nul.

    C'est ce test qui distingue « neutre par conception » de « neutre par effet de bord » : sur
    l'ancien code, retirer la clé faisait tomber le payload dans le chemin « unité agissante ».
    """
    gs = _game_state([_unit(1, 1, 5, 10, [])])
    calculator = _reward_calculator()
    payload = {"action": "agent_decision", "unitId": "1", "player": 1, "option_index": 1}
    assert "waiting_for_player" not in payload
    assert calculator.calculate_reward(True, payload, gs) == 0.0


def test_a_decision_increments_the_step_counter_of_the_log(tmp_path):
    """Une décision consomme un step gym : la ligne de step.log doit l'incrémenter.

    Sinon `Steps=` (compteur StepLogger) et `Total=` (compteur moteur) divergent en fin
    d'épisode d'exactement le nombre de décisions — l'écart qui a servi à diagnostiquer T6-c.
    Les chemins PvP/PvE, eux, ne consomment aucun step gym.
    """
    from ai.step_logger import StepLogger

    gs = _game_state([_unit(1, 1, 5, 10, [dict(CHOICE_RULE)])])
    engine = _engine(gs)
    engine.step_logger = StepLogger(
        output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=1
    )
    _emit_fight_phase_choice(engine)
    before = engine.step_logger.episode_step_count
    engine._process_squad_action(engine.action_decoder.convert_squad_action(CHOICE_BASE, gs))
    assert engine.step_logger.episode_step_count == before + 1


def test_the_pvp_path_does_not_consume_a_gym_step(tmp_path):
    """Le choix d'un joueur HUMAIN ne consomme aucun step gym : le compteur ne bouge pas."""
    from ai.step_logger import StepLogger

    gs = _game_state([_unit(1, 1, 5, 10, [dict(CHOICE_RULE)])])
    gs["player_types"] = {"1": "human", "2": "ai"}
    engine = _engine(gs, gym_training_mode=False)
    engine.step_logger = StepLogger(
        output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=1
    )
    engine._initialize_rule_choice_runtime_state()
    engine._enqueue_rule_choice_candidates(
        trigger="phase_start", event_phase="fight", event_player=1
    )
    engine._emit_next_rule_choice_prompt_if_needed()
    before = engine.step_logger.episode_step_count
    success, _result = engine._process_squad_action(
        {"action": "select_rule_choice", "unitId": "1", "selectedRuleId": "aggression_imperative"}
    )
    assert success is True
    assert engine.step_logger.episode_step_count == before


# ─────────────────────────────────────────────────────────────────────────────
# 8. Purge d'épisode — le mécanisme doit rester VIVANT après le premier épisode
# ─────────────────────────────────────────────────────────────────────────────


def _full_engine_config() -> Dict[str, Any]:
    """Config d'un W40KEngine COMPLET (le harnais `object.__new__` ne sait pas `reset()`)."""
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    model = {
        "id": "m1", "col": 10, "row": 20, "HP_CUR": 1, "HP_MAX": 1, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0, "VALUE": 7,
    }
    unit = {
        "id": 1, "player": 1, "col": 10, "row": 20,
        "unitType": "TestUnit", "DISPLAY_NAME": "Unit 1",
        "HP_CUR": 1, "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "UNIT_RULES": [dict(CHOICE_RULE)], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 7,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": [dict(model)],
    }
    enemy = dict(unit)
    enemy.update({"id": 2, "player": 2, "col": 60, "row": 20, "UNIT_RULES": [],
                  "models": [dict(model, id="m2", col=60)]})
    return {
        "board": {"default": {"cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [], "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                       "max_base_size_hex": 35, "unit_model_cohesion_range": 2,
                       "unit_global_cohesion_range": 9, "squad_min_neighbors": 1,
                       "cohesion_distance_mode": "euclidean"},
        "charge": {"charge_max_distance": 12},
        "move": {"can_move_through_enemy_engagement_zone": True,
                 "can_move_through_enemy_model": False,
                 "can_move_through_friendly_model": True},
        "pve_mode": False,
        "controlled_player": 1,
        "controlled_agent": "ArmageddonAgent",
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [unit, enemy],
    }


def test_the_choice_mechanism_survives_the_first_episode():
    """⚠️ Le prompt DOIT être ré-émis à l'épisode suivant.

    `_choice_timing_fired_events` indexe `(trigger, tour, phase, joueur, unité, règle)` — SANS le
    numéro d'épisode. Sans purge au `reset()`, l'événement du tour 1 de l'épisode 1 fait passer
    pour « déjà tiré » celui du tour 1 de l'épisode 2, et plus aucune décision n'est jamais
    exposée. MESURÉ avant correction sur 3 épisodes enchaînés : 16 décisions, puis 2, puis 0 —
    le mécanisme entier devenait inerte après le premier épisode d'un run, et aucun smoke à un
    seul épisode ne pouvait le voir.
    """
    from unittest.mock import patch

    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=_full_engine_config(), gym_training_mode=True)

    emitted = []
    for _episode in range(3):
        engine.reset()
        # L'état de choix de l'épisode précédent ne survit à AUCUN titre. Lecture par `get`
        # (et non par `[]`) VOLONTAIRE : sous mutation du correctif, le test doit échouer sur
        # l'assertion FONCTIONNELLE du bas (le prompt n'est plus émis), pas sur un KeyError qui
        # ne prouverait rien du comportement.
        assert engine.game_state.get("_choice_timing_fired_events", set()) == set()
        assert engine.game_state.get("pending_rule_choice_queue", []) == []
        assert engine.game_state.get("active_rule_choice_prompt") is None
        assert read_pending_agent_decision(engine.game_state) is None

        engine._enqueue_rule_choice_candidates(
            trigger="phase_start", event_phase="fight", event_player=1
        )
        result = engine._emit_next_rule_choice_prompt_if_needed()
        emitted.append(result is not None and result["action"] == "waiting_for_agent_decision")
        # On consomme la décision pour repartir d'un état propre au prochain tour de boucle.
        if result is not None:
            engine._process_squad_action(
                engine.action_decoder.convert_squad_action(CHOICE_BASE, engine.game_state)
            )

    assert emitted == [True, True, True], (
        f"le prompt n'est pas ré-émis à chaque épisode : {emitted}"
    )
