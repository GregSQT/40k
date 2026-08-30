"""Tests unitaires — reward_calculator : determine_winner."""

from __future__ import annotations

import pytest
from typing import Any, Dict, List, Optional, Tuple

from engine.reward_calculator import RewardCalculator
from shared.data_validation import ConfigurationError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_calculator() -> RewardCalculator:
    """Instance minimale sans state_manager ni unit_registry."""
    return RewardCalculator(
        config={"quiet": True},
        rewards_config={},
        unit_registry=None,
        state_manager=None,
    )


def _cache_entry(player: int) -> Dict[str, Any]:
    return {"player": player, "col": 0, "row": 0, "HP_CUR": 1}


def _gs_with_cache(entries: Dict[str, Any]) -> Dict[str, Any]:
    return {"units_cache": entries}


# ─────────────────────────────────────────────────────────────────────────────
# _determine_winner (chemin legacy sans state_manager)
# ─────────────────────────────────────────────────────────────────────────────

class TestDetermineWinner:
    def test_only_player1_wins(self):
        """winner_p1 : seul joueur 1 a des unités → winner=1."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(1), "2": _cache_entry(1)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 1

    def test_only_player2_wins(self):
        """winner_p2 : seul joueur 2 a des unités → winner=2."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(2), "2": _cache_entry(2)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 2

    def test_both_players_alive_returns_none(self):
        """winner_none : les deux joueurs ont des unités → None (partie en cours)."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(1), "2": _cache_entry(2)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result is None

    def test_empty_cache_returns_minus_one(self):
        """winner_draw : cache vide → -1 (égalité/élimination mutuelle)."""
        rc = _make_calculator()
        result = rc._determine_winner(_gs_with_cache({}))
        assert result == -1

    def test_multiple_units_same_player(self):
        """winner_multi : 3 unités joueur 1, 0 joueur 2 → winner=1."""
        rc = _make_calculator()
        cache = {"1": _cache_entry(1), "2": _cache_entry(1), "3": _cache_entry(1)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 1

    def test_single_unit_player2_wins(self):
        """winner_single_p2 : 1 unité joueur 2 → winner=2."""
        rc = _make_calculator()
        cache = {"5": _cache_entry(2)}
        result = rc._determine_winner(_gs_with_cache(cache))
        assert result == 2


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_on_objective_reward — cohérence avec le contrôle réel (01.07 + 14.02)
# ─────────────────────────────────────────────────────────────────────────────

def _objective_state(
    models: List[Tuple[int, int]],
    objectives: List[Tuple[str, Tuple[int, int], Optional[int]]],
    *,
    battle_shocked: bool = False,
) -> Dict[str, Any]:
    """État minimal pour ``_calculate_on_objective_reward`` : une escouade, N objectifs à 1 hexe.

    SOURCE UNIQUE de la forme du game_state pour ces tests — les trois caches sont ceux que
    ``iter_living_model_footprints`` exige, et les recopier par test créait autant de points de
    maintenance que de scénarios.

    ``models`` : positions ``(col, row)`` des figurines vivantes. La PREMIÈRE porte aussi l'ancre
    d'escouade, ce qui permet de monter le cas décisif de ce dépôt — ancre HORS de la zone,
    figurine suivante dedans : le bonus se juge par FIGURINE (14.02), et une lecture à l'ancre
    rendrait 0.0 alors que l'escouade est bien sur l'objectif.
    ``objectives`` : ``(id, (col, row), contrôleur)``, ``None`` = zone neutre. L'ORDRE fixe le
    ``zone_idx`` que lit ``get_objective_control``.
    """
    unit: Dict[str, Any] = {"id": "1", "player": 1, "battle_shocked": battle_shocked}
    anchor_col, anchor_row = models[0]
    return {
        "units": [unit],
        "unit_by_id": {"1": unit},
        "units_cache": {
            "1": {
                "player": 1,
                "col": anchor_col,
                "row": anchor_row,
                "HP_CUR": 1,
                "orientation": 0,
            }
        },
        "squad_models": {"1": [f"1#{i}" for i in range(len(models))]},
        "models_cache": {
            f"1#{i}": {
                "col": col,
                "row": row,
                "HP_CUR": 1,
                "BASE_SHAPE": "round",
                "BASE_SIZE": 1,
            }
            for i, (col, row) in enumerate(models)
        },
        "objectives": [
            {"id": obj_id, "hexes": [{"col": col, "row": row}]}
            for obj_id, (col, row), _ in objectives
        ],
        "objective_controllers": {obj_id: ctrl for obj_id, _, ctrl in objectives},
        "current_player": 1,
    }


def _objective_gs(battle_shocked: bool) -> Dict[str, Any]:
    """Escouade de 2 figurines dont l'ANCRE est HORS de la zone et la SECONDE figurine dedans."""
    return _objective_state(
        [(3, 3), (5, 5)], [("obj1", (5, 5), None)], battle_shocked=battle_shocked
    )


def _objective_calculator() -> RewardCalculator:
    rc = RewardCalculator(
        config={"quiet": True, "controlled_player": 1},
        rewards_config={},
        unit_registry=None,
        state_manager=None,
    )
    rc._get_unit_reward_config = lambda unit: {
        "objective_rewards": {"on_objective_bonus": 2.5}
    }
    return rc


class TestOnObjectiveRewardBattleShock:
    """Le bonus paie la progression vers un contrôle (14.02). Une unité battle-shocked a l'OC
    de toutes ses figurines à '-' (01.07) : elle ne peut RIEN prendre, donc rien à payer."""

    def test_bonus_paid_when_not_battle_shocked(self):
        """obj_reward_ok : unité saine sur un objectif non contrôlé → bonus versé."""
        rc = _objective_calculator()
        result = {"unitId": "1", "toCol": 5, "toRow": 5}
        assert rc._calculate_on_objective_reward(_objective_gs(False), result) == 2.5

    def test_no_bonus_when_battle_shocked(self):
        """obj_reward_shock : même mouvement sous battle-shock → aucun bonus."""
        rc = _objective_calculator()
        result = {"unitId": "1", "toCol": 5, "toRow": 5}
        assert rc._calculate_on_objective_reward(_objective_gs(True), result) == 0.0


#: Deux zones à un hexe chacune : l'index 0 est DÉJÀ contrôlé par le joueur 1 (il ne paie plus),
#: l'index 1 est neutre (il paie). C'est le montage qui distingue les zones par leur index :
#: confondre les deux inverse la réponse sur les deux tests ci-dessous.
_ZONE_CONTROLEE = ("obj0", (3, 3), 1)
_ZONE_NEUTRE = ("obj1", (7, 7), None)


class TestOnObjectiveRewardMultiZone:
    """Le bonus se lit ZONE PAR ZONE : seule une zone non contrôlée paie (14.02).

    Le filtre de contrôle précède la traversée des empreintes ; ces tests verrouillent qu'il
    porte bien sur la zone TOUCHÉE et non sur la première de la liste, et qu'il regarde TOUTES
    les figurines et non la seule ancre.
    """

    def test_no_bonus_on_controlled_zone(self):
        """obj_multi_controlled : unité sur la zone déjà contrôlée → rien à payer."""
        rc = _objective_calculator()
        gs = _objective_state([(3, 3)], [_ZONE_CONTROLEE, _ZONE_NEUTRE])
        assert rc._calculate_on_objective_reward(gs, {"unitId": "1", "toCol": 3, "toRow": 3}) == 0.0

    def test_bonus_on_uncontrolled_second_zone(self):
        """obj_multi_uncontrolled : unité sur la zone neutre d'index 1 (pas 0) → bonus versé."""
        rc = _objective_calculator()
        gs = _objective_state([(7, 7)], [_ZONE_CONTROLEE, _ZONE_NEUTRE])
        assert rc._calculate_on_objective_reward(gs, {"unitId": "1", "toCol": 7, "toRow": 7}) == 2.5

    def test_bonus_when_only_second_model_reaches_uncontrolled_zone(self):
        """obj_multi_fig : ancre sur la zone contrôlée, SECONDE figurine sur la zone neutre.

        Non vacant : la lecture s'arrêtant à la première figurine — ou à l'ancre d'escouade,
        l'erreur classique de ce dépôt — rendrait 0.0 alors que l'escouade progresse bien vers
        un contrôle qu'elle n'a pas.
        """
        rc = _objective_calculator()
        gs = _objective_state([(3, 3), (7, 7)], [_ZONE_CONTROLEE, _ZONE_NEUTRE])
        assert rc._calculate_on_objective_reward(gs, {"unitId": "1", "toCol": 7, "toRow": 7}) == 2.5


# ─────────────────────────────────────────────────────────────────────────────
# desperate_escape_died — chemin gym (w40k_core pipeline squad)
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PENALTIES = {
    "forbidden_action": -1.0,
    "invalid_action": -0.9,
    "generic_error": -0.1,
    "system_response": 0.0,
}

_MINIMAL_GS: Dict[str, Any] = {
    "units_cache": {},
    "unit_by_id": {},
    "phase": "move",
    "turn": 1,
    "current_player": 1,
    "objectives": [],
    "objective_controllers": {},
    "game_over": False,
}


def _rc_desp() -> RewardCalculator:
    rc = _make_minimal_rc()
    rc._get_system_penalties = lambda: _SYSTEM_PENALTIES
    return rc


class TestDesperateEscapeDiedGymPath:
    """Le résultat gym de desperate_escape_died doit retourner 0.0 quelle que soit la forme du payload."""

    @pytest.mark.parametrize("result", [
        {
            "action": "desperate_escape_died",
            "unitId": "1",
            "squad_id": "1",
            "activation_complete": True,
            "waiting_for_player": False,
        },
        {
            "action": "desperate_escape_died",
            "squad_id": "1",
            "activation_complete": True,
        },
    ], ids=["with_unitId_and_waiting", "without_unitId_and_waiting"])
    def test_returns_zero(self, result: dict) -> None:
        """desp_died_zero : routage sur action, indépendant de unitId / waiting_for_player."""
        rc = _rc_desp()
        gs = dict(_MINIMAL_GS)
        reward = rc.calculate_reward(True, result, gs)
        assert reward == 0.0


class TestSelectCoherencyRemovalGymPath:
    """select_coherency_removal doit retourner 0.0 quelle que soit la forme du payload.

    Avant le correctif, calculate_reward levait ValueError : le résultat ne porte
    ni `unitId` ni `shooterId` ni `unit_id`, et l'action n'était pas dans la liste
    d'actions à reward nul. C'est le même raisonnement que select_activation : la
    décision elle-même n'a pas de récompense propre.
    """

    @pytest.mark.parametrize("result", [
        {
            "action": "select_coherency_removal",
            "squad_id": "1",
            "model_id": "1#3",
            "awaiting_coherency_removal": True,
        },
        {
            "action": "select_coherency_removal",
            "squad_id": "2",
            "model_id": "2#0",
        },
    ], ids=["with_awaiting_flag", "without_awaiting_flag"])
    def test_returns_zero(self, result: dict) -> None:
        """coherency_removal_zero : reward nul, aucune ValueError."""
        rc = _rc_desp()
        gs = dict(_MINIMAL_GS)
        reward = rc.calculate_reward(True, result, gs)
        assert reward == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# fight path — all_attack_results manquant → ConfigurationError contextualisé
# ─────────────────────────────────────────────────────────────────────────────

def _fight_calculator() -> RewardCalculator:
    """RewardCalculator minimal câblé pour atteindre la ligne require_key('all_attack_results')."""
    rc = _make_minimal_rc()

    class _FakeMapper:
        def get_combat_priority_reward(self, *a: Any, **kw: Any) -> float:
            return 0.0

    rc._get_system_penalties = lambda: _SYSTEM_PENALTIES  # type: ignore[method-assign]
    rc._get_reward_mapper = lambda: _FakeMapper()  # type: ignore[method-assign]
    rc._enrich_unit_for_reward_mapper = lambda u: u  # type: ignore[method-assign]
    rc._get_all_valid_targets = lambda u, gs: []  # type: ignore[method-assign]
    rc._calculate_objective_reward_per_turn = lambda gs, r: 0.0  # type: ignore[method-assign]
    rc._calculate_coherency_penalty_per_turn = lambda gs, r: 0.0  # type: ignore[method-assign]
    return rc


def _fight_gs() -> Dict[str, Any]:
    attacker: Dict[str, Any] = {"id": "u1", "player": 1}
    target: Dict[str, Any] = {"id": "t1", "player": 2}
    return {
        **_MINIMAL_GS,
        "units": [attacker, target],
        "unit_by_id": {"u1": attacker, "t1": target},
        "units_cache": {},
        "squad_cache": {},
        "squad_models": {},
        "models_cache": {},
    }


class TestFightAllAttackResultsRequired:
    """require_key doit lever ConfigurationError avec le nom du champ si all_attack_results absent."""

    def test_missing_all_attack_results_raises_configuration_error(self) -> None:
        """fight_missing_aar : absence de all_attack_results → ConfigurationError, pas KeyError."""
        rc = _fight_calculator()
        gs = _fight_gs()
        result = {"action": "fight", "unitId": "u1", "targetId": "t1"}
        with pytest.raises(ConfigurationError, match="all_attack_results"):
            rc.calculate_reward(True, result, gs)

    def test_present_all_attack_results_does_not_raise(self) -> None:
        """fight_present_aar : all_attack_results vide → pas d'erreur, reward float."""
        rc = _fight_calculator()
        gs = _fight_gs()
        result = {"action": "fight", "unitId": "u1", "targetId": "t1", "all_attack_results": []}
        reward = rc.calculate_reward(True, result, gs)
        assert isinstance(reward, float)


def _make_minimal_rc() -> RewardCalculator:
    """RewardCalculator minimal pour les tests d'idempotence (controlled_player=1, sans registre)."""
    return RewardCalculator(
        config={"quiet": True, "controlled_player": 1},
        rewards_config={},
        unit_registry=None,
        state_manager=None,
    )


_PHASE_MOVE_TRANSITION: Dict[str, Any] = {"phase_transition": True, "next_phase": "move"}


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_coherency_penalty_per_turn — idempotence quand aucune unité active
# ─────────────────────────────────────────────────────────────────────────────

class TestCoherencyPenaltyNoActingUnit:
    """Sans unité contrôlée vivante, la pénalité est 0.0 et ne se recalcule pas au 2e appel."""

    def _gs(self) -> Dict[str, Any]:
        # units_cache vide → _get_controlled_player_unit retourne None (pas d'unité contrôlée)
        return {
            **_MINIMAL_GS,
            "units_cache": {},
            "squad_cache": {},
            "turn": 1,
            "current_player": 1,
        }

    def test_returns_zero_when_no_unit(self) -> None:
        """coherency_no_unit_zero : 0.0 quand aucune unité contrôlée vivante."""
        rc = _make_minimal_rc()
        gs = self._gs()
        penalty = rc._calculate_coherency_penalty_per_turn(gs, _PHASE_MOVE_TRANSITION)
        assert penalty == 0.0

    def test_idempotent_on_second_call(self) -> None:
        """coherency_no_unit_idempotent : once_claim posé au 1er appel → court-circuit au 2e."""
        rc = _make_minimal_rc()
        gs = self._gs()
        result = dict(_PHASE_MOVE_TRANSITION)
        rc._calculate_coherency_penalty_per_turn(gs, result)

        # Après le 1er appel, once_claim doit avoir été posé même si acting_unit est None.
        # On instrument _get_controlled_player_unit pour vérifier qu'il n'est PAS rappelé.
        call_count = 0
        original_get_unit = rc._get_controlled_player_unit

        def counting_get_unit(game_state: Any) -> Dict[str, Any] | None:
            nonlocal call_count
            call_count += 1
            return original_get_unit(game_state)

        rc._get_controlled_player_unit = counting_get_unit  # type: ignore[method-assign]
        penalty2 = rc._calculate_coherency_penalty_per_turn(gs, result)
        assert penalty2 == 0.0
        assert call_count == 0  # once_claim court-circuite avant _get_controlled_player_unit


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_objective_reward_per_turn — idempotence quand aucune unité active
# ─────────────────────────────────────────────────────────────────────────────

class TestObjectiveRewardPerTurnNoActingUnit:
    """Sans unité contrôlée vivante, le reward est 0.0 et ne se recalcule pas au 2e appel."""

    def _gs(self) -> Dict[str, Any]:
        # units_cache vide → _get_controlled_player_unit retourne None (pas d'unité contrôlée)
        return {
            **_MINIMAL_GS,
            "units_cache": {},
            "turn": 1,
            "current_player": 1,
            "primary_objective": {"scoring": {"start_turn": 1}},
        }

    def test_returns_zero_when_no_unit(self) -> None:
        """objective_reward_no_unit_zero : 0.0 quand aucune unité contrôlée vivante."""
        rc = _make_minimal_rc()
        gs = self._gs()
        reward = rc._calculate_objective_reward_per_turn(gs, _PHASE_MOVE_TRANSITION)
        assert reward == 0.0

    def test_idempotent_on_second_call(self) -> None:
        """objective_reward_no_unit_idempotent : once_claim posé au 1er appel → court-circuit au 2e."""
        rc = _make_minimal_rc()
        gs = self._gs()
        result = dict(_PHASE_MOVE_TRANSITION)
        rc._calculate_objective_reward_per_turn(gs, result)

        # Après le 1er appel, once_claim doit avoir été posé même si acting_unit est None.
        # On instrument _get_controlled_player_unit pour vérifier qu'il n'est PAS rappelé.
        call_count = 0
        original_get_unit = rc._get_controlled_player_unit

        def counting_get_unit(game_state: Any) -> Dict[str, Any] | None:
            nonlocal call_count
            call_count += 1
            return original_get_unit(game_state)

        rc._get_controlled_player_unit = counting_get_unit  # type: ignore[method-assign]
        reward2 = rc._calculate_objective_reward_per_turn(gs, result)
        assert reward2 == 0.0
        assert call_count == 0  # once_claim court-circuite avant _get_controlled_player_unit


# ─────────────────────────────────────────────────────────────────────────────
# P3-8 split-fire — reward_calculator doit gérer tous les états intermédiaires
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitFireRewardPaths:
    """calculate_reward gère les 3 étapes du flux split-fire sans ValueError."""

    @pytest.mark.parametrize("result", [
        {
            "action": "squad_shoot_weapon_sel",
            "squad_id": "1",
            "weapon_slot": 0,
            "weapon_code": "storm_bolter",
            "waiting_for_target_select": True,
        },
        {
            "action": "squad_shoot_split_target",
            "squad_id": "1",
            "weapon_code": "storm_bolter",
            "target_squad_id": "2",
            "waiting_for_next_weapon_sel": True,
        },
    ], ids=["waiting_for_target_select", "waiting_for_next_weapon_sel"])
    def test_intermediate_steps_return_zero(self, result: dict) -> None:
        """split_fire_intermediate_zero : étapes intermédiaires → reward 0, pas de ValueError."""
        rc = _rc_desp()
        gs = dict(_MINIMAL_GS)
        reward = rc.calculate_reward(True, result, gs)
        assert reward == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Exhortation de Rage — mortal_wounds_target (waiting_for_agent_decision)
# ─────────────────────────────────────────────────────────────────────────────

class TestExhortationMortalWoundsTargetRewardPath:
    """calculate_reward retourne 0.0 pour le payload mortal_wounds_target.

    Avant le correctif, calculate_reward levait ValueError : le résultat a
    action='squad_fight' (→ is_action_result=True) mais ne porte ni unitId ni
    shooterId ni unit_id.
    """

    def test_mortal_wounds_target_returns_zero(self) -> None:
        """exhortation_mwt_zero : waiting_for_agent_decision → reward 0, pas de ValueError."""
        rc = _rc_desp()
        gs = dict(_MINIMAL_GS)
        result = {
            "action": "squad_fight",
            "squad_id": "101",
            "waiting_for_agent_decision": True,
            "decision_type": "mortal_wounds_target",
            "exhortation_d6_roll": 6,
            "mw_count": 3,
        }
        reward = rc.calculate_reward(True, result, gs)
        assert reward == 0.0

    def test_mortal_wounds_target_d4_roll_returns_zero(self) -> None:
        """exhortation_mwt_d4_zero : variante D6=4 (mw_count aléatoire) → reward 0."""
        rc = _rc_desp()
        gs = dict(_MINIMAL_GS)
        result = {
            "action": "squad_fight",
            "squad_id": "42",
            "waiting_for_agent_decision": True,
            "decision_type": "mortal_wounds_target",
            "exhortation_d6_roll": 4,
            "mw_count": 2,
        }
        reward = rc.calculate_reward(True, result, gs)
        assert reward == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _fight_lowest_hp_wipe_bonus
# ─────────────────────────────────────────────────────────────────────────────

def _rc_with_lowest_hp_bonus(bonus: float) -> RewardCalculator:
    rc = RewardCalculator(
        config={"quiet": True, "controlled_agent": "TestAgent"},
        rewards_config={
            "TestAgent": {
                "squad_shaping": {
                    "hp_damage_weight": 0.1,
                    "model_kill_bonus_factor": 0.1,
                    "squad_kill_bonus_factor": 0.1,
                    "incoherent_weight": 0.0,
                },
                "base_actions": {"ranged_attack": 0.0, "melee_attack": 0.0, "charge_success": 0.0, "charge_fail": 0.0, "wait": 0.0},
                "result_bonuses": {"kill_target": 1.0, "target_lowest_hp": bonus},
                "target_type_bonuses": {},
                "situational_modifiers": {"win": 0, "lose": 0, "draw": 0},
                "objective_rewards": {"objective_reward_factor": 0.0, "reward_per_objective_turn5": 0.0, "on_objective_bonus": 0.0},
                "system_penalties": {"forbidden_action": 0.0, "invalid_action": 0.0, "system_response": 0.0, "generic_error": 0.0},
            }
        },
        unit_registry=None,
        state_manager=None,
    )
    return rc


def _combat_result(squads_wiped: list, targets_meta: dict) -> dict:
    return {
        "events": [],
        "squads_wiped": squads_wiped,
        "targets_meta": targets_meta,
        "damage_total": 0,
        "models_killed": len(squads_wiped),
        "attacks_made": 1,
        "hits": 1,
        "wounds": 1,
        "failed_saves": 1,
    }


def _acting_unit(player: int = 1) -> dict:
    return {"id": "a1", "player": player, "unitType": "TestAgent"}


class TestFightLowestHpWipeBonus:
    """_fight_lowest_hp_wipe_bonus : bonus target_lowest_hp quand escouade wipée était la plus faible."""

    def test_no_wiped_squads_returns_zero(self) -> None:
        """no_wipe_zero : aucune escouade wipée → 0.0."""
        rc = _rc_with_lowest_hp_bonus(0.3)
        combat = _combat_result(squads_wiped=[], targets_meta={})
        gs = {"units_cache": {}}
        assert rc._fight_lowest_hp_wipe_bonus(combat, _acting_unit(), 1, gs) == 0.0

    def test_bonus_zero_in_config_returns_zero(self) -> None:
        """config_zero : target_lowest_hp=0 → 0.0 sans lecture du cache."""
        rc = _rc_with_lowest_hp_bonus(0.0)
        meta = {"e1": {"value": 10.0, "player": 2, "model_count_at_start": 1, "hp_before": 3}}
        combat = _combat_result(squads_wiped=["e1"], targets_meta=meta)
        gs = {"units_cache": {}}
        assert rc._fight_lowest_hp_wipe_bonus(combat, _acting_unit(), 1, gs) == 0.0

    def test_bonus_granted_when_killed_was_lowest(self) -> None:
        """lowest_hp_bonus : cible wipée (hp=3) seule ennemie vivante → bonus accordé."""
        rc = _rc_with_lowest_hp_bonus(0.3)
        meta = {"e1": {"value": 10.0, "player": 2, "model_count_at_start": 1, "hp_before": 3}}
        combat = _combat_result(squads_wiped=["e1"], targets_meta=meta)
        gs = {"units_cache": {}}
        assert rc._fight_lowest_hp_wipe_bonus(combat, _acting_unit(), 1, gs) == pytest.approx(0.3)

    def test_no_bonus_when_living_enemy_has_lower_hp(self) -> None:
        """not_lowest : ennemi vivant avec HP=2 < hp_before=5 → bonus refusé."""
        rc = _rc_with_lowest_hp_bonus(0.3)
        meta = {"e1": {"value": 10.0, "player": 2, "model_count_at_start": 1, "hp_before": 5}}
        combat = _combat_result(squads_wiped=["e1"], targets_meta=meta)
        gs = {"units_cache": {"e2": {"player": 2, "HP_CUR": 2, "col": 10, "row": 100}}}
        assert rc._fight_lowest_hp_wipe_bonus(combat, _acting_unit(), 1, gs) == 0.0

    def test_bonus_granted_when_other_enemy_has_equal_hp(self) -> None:
        """equal_hp : ennemi vivant avec HP=3 == hp_before=3 → bonus accordé (pas strictement inférieur)."""
        rc = _rc_with_lowest_hp_bonus(0.3)
        meta = {"e1": {"value": 10.0, "player": 2, "model_count_at_start": 1, "hp_before": 3}}
        combat = _combat_result(squads_wiped=["e1"], targets_meta=meta)
        gs = {"units_cache": {"e2": {"player": 2, "HP_CUR": 3, "col": 10, "row": 100}}}
        assert rc._fight_lowest_hp_wipe_bonus(combat, _acting_unit(), 1, gs) == pytest.approx(0.3)

    def test_friendly_wipe_ignored(self) -> None:
        """friendly_wipe : escouade alliée wipée (player=1) → bonus ignoré."""
        rc = _rc_with_lowest_hp_bonus(0.3)
        meta = {"a2": {"value": 10.0, "player": 1, "model_count_at_start": 1, "hp_before": 2}}
        combat = _combat_result(squads_wiped=["a2"], targets_meta=meta)
        gs = {"units_cache": {}}
        assert rc._fight_lowest_hp_wipe_bonus(combat, _acting_unit(player=1), 1, gs) == 0.0

    def test_hp_before_missing_raises(self) -> None:
        """no_hp_before : hp_before absent dans targets_meta → ConfigurationError (T1)."""
        rc = _rc_with_lowest_hp_bonus(0.3)
        meta = {"e1": {"value": 10.0, "player": 2, "model_count_at_start": 1}}
        combat = _combat_result(squads_wiped=["e1"], targets_meta=meta)
        gs = {"units_cache": {}}
        with pytest.raises(ConfigurationError, match="hp_before"):
            rc._fight_lowest_hp_wipe_bonus(combat, _acting_unit(), 1, gs)

    def test_player_absent_in_cache_raises(self) -> None:
        """player_absent : entrée units_cache sans clé 'player' → ConfigurationError (T1)."""
        rc = _rc_with_lowest_hp_bonus(0.3)
        meta = {"e1": {"value": 10.0, "player": 2, "model_count_at_start": 1, "hp_before": 3}}
        combat = _combat_result(squads_wiped=["e1"], targets_meta=meta)
        gs = {"units_cache": {"e2": {"HP_CUR": 5, "col": 10}}}  # pas de "player"
        with pytest.raises(ConfigurationError, match="player"):
            rc._fight_lowest_hp_wipe_bonus(combat, _acting_unit(), 1, gs)

    def test_dead_enemy_in_cache_does_not_block_bonus(self) -> None:
        """dead_in_cache : ennemi mort (HP_CUR=0) dans units_cache ne bloque pas le bonus."""
        rc = _rc_with_lowest_hp_bonus(0.3)
        meta = {"e1": {"value": 10.0, "player": 2, "model_count_at_start": 1, "hp_before": 3}}
        combat = _combat_result(squads_wiped=["e1"], targets_meta=meta)
        # e2 est mort (HP_CUR=0) — hp=0 < hp_before=3 sans le garde hp>0 → faux blocage
        gs = {"units_cache": {"e2": {"player": 2, "HP_CUR": 0, "col": 10, "row": 100}}}
        assert rc._fight_lowest_hp_wipe_bonus(combat, _acting_unit(), 1, gs) == pytest.approx(0.3)

    def test_multi_wipe_only_lowest_gets_bonus(self) -> None:
        """multi_wipe : A(hp=3) + B(hp=5) wipés — seul A reçoit le bonus, pas B."""
        rc = _rc_with_lowest_hp_bonus(0.3)
        meta = {
            "e1": {"value": 10.0, "player": 2, "model_count_at_start": 1, "hp_before": 3},
            "e2": {"value": 10.0, "player": 2, "model_count_at_start": 1, "hp_before": 5},
        }
        combat = _combat_result(squads_wiped=["e1", "e2"], targets_meta=meta)
        gs = {"units_cache": {}}
        assert rc._fight_lowest_hp_wipe_bonus(combat, _acting_unit(), 1, gs) == pytest.approx(0.3)

    def test_multi_wipe_equal_hp_both_get_bonus(self) -> None:
        """multi_wipe_equal : A(hp=3) + B(hp=3) wipés — aucun n'est strictement inférieur à l'autre → les deux reçoivent le bonus."""
        rc = _rc_with_lowest_hp_bonus(0.3)
        meta = {
            "e1": {"value": 10.0, "player": 2, "model_count_at_start": 1, "hp_before": 3},
            "e2": {"value": 10.0, "player": 2, "model_count_at_start": 1, "hp_before": 3},
        }
        combat = _combat_result(squads_wiped=["e1", "e2"], targets_meta=meta)
        gs = {"units_cache": {}}
        assert rc._fight_lowest_hp_wipe_bonus(combat, _acting_unit(), 1, gs) == pytest.approx(0.6)
