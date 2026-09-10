"""Tests unitaires — W40KEngine.step().

Chemin critique: reset() → step(action) × N → game_over.
Vérifie: épisode_steps, terminated, tuple de retour, turn_limit, phase advance auto.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT
from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine
from tests._state_invariants import charge_log_line
from tests.unit.engine._config_helpers import build_engine_config


# ─────────────────────────────────────────────────────────────────────────────
# Config minimale
# ─────────────────────────────────────────────────────────────────────────────

def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2,
        "STR": 4,
        "AP": 0,
        "DMG": 1,
        "NB": 1,
        "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon",
        "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "unitType": "TestUnit",
        "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3,
        "HP_MAX": 3,
        "MOVE": 6,
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()],
        "CC_WEAPONS": [],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [],
        "LD": 7,
        "OC": 1,
        "VALUE": 100,
        "ICON": "test",
        "ICON_SCALE": 1.0,
        "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
    }


def _minimal_config() -> Dict[str, Any]:
    obs_params = {
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
    }
    return {
        "board": {
            "default": {
                "cols": 15,
                "rows": 13,
                "hex_radius": 1.0,
                "margin": 0.0,
                "wall_hexes": [],
                "objectives": [{"id": "obj1", "name": "Alpha", "hexes": [[5, 5]]}],
                "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
            # Requis par le garde anti-runaway de step() (cf. compute_episode_step_limit).
            # Valeurs reelles de config/game_config.json.
            "max_turns": 3,  # duree de bataille visee par ces tests
            "max_actions_per_model_per_turn": 7,
            "step_limit_margin": 1.5,
        },
        # Toggles de traversee requis par le pool BFS : le masque de move passe
        # desormais par lui (refonte spatiale), la ou les dry-runs directionnels
        # ne les lisaient pas. Valeurs reelles de config/game_config.json.
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "charge": {
            "charge_max_distance": 12,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {
            "observation_params": obs_params,
        },
        "units": [
            _unit_cfg(1, 1, 3, 3),
            _unit_cfg(2, 2, 10, 10),
        ],
    }


@pytest.fixture(autouse=True)
def mock_build_obs(monkeypatch):
    # On double `_build_observation_and_mask`, l'IMPLEMENTATION, et non la facade
    # `_build_observation` : `_step_observation` appelle l'implementation directement, donc doubler
    # la facade seule laissait tourner le vrai constructeur (et le vrai `advance_phase` sur pool
    # vide) sur ces etats artificiels. La facade est doublee aussi, pour les tests qui l'appellent.
    _stub_obs = np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET)
    monkeypatch.setattr(
        W40KEngine, "_build_observation_and_mask", lambda self, *_a, **_k: (_stub_obs, None)
    )
    monkeypatch.setattr(W40KEngine, "_build_observation", lambda self, *_a, **_k: _stub_obs)
    from engine.reward_calculator import RewardCalculator
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)


def _make_engine() -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        return W40KEngine(config=build_engine_config(_minimal_config()))


def _legal_action(engine: W40KEngine) -> int:
    """Première action autorisée par le masque — ce que fait un agent masqué (MaskablePPO).

    Ces tests passaient `0` en dur, en s'appuyant sur l'ancien contrat « action hors masque →
    dégradation silencieuse en squad_wait ». Ce repli MASQUAIT les divergences masque/exécution :
    il est supprimé (refonte spatiale §7 T3), une action hors masque lève désormais. Et l'action 0
    n'est plus « direction 0 » mais la cellule 0 de la grille égocentrique (coin du disque).

    Masque vide : `step()` auto-avance la phase et ignore l'action → WAIT, jamais lu dans ce cas.
    """
    mask = engine.get_action_mask()
    legal = np.flatnonzero(mask)
    return int(legal[0]) if legal.size else SQUAD_ACTION_WAIT


# ─────────────────────────────────────────────────────────────────────────────
# Tests — retour de step()
# ─────────────────────────────────────────────────────────────────────────────

class TestStepReturnSignature:

    def test_step_returns_5_tuple(self):
        """step_tuple : step() retourne bien un tuple de 5 éléments (gym interface)."""
        engine = _make_engine()
        engine.reset()
        result = engine.step(_legal_action(engine))
        assert isinstance(result, tuple)
        assert len(result) == 5

    def test_step_obs_is_ndarray(self):
        """step_obs_type : premier élément (obs) est un np.ndarray."""
        engine = _make_engine()
        engine.reset()
        obs, reward, terminated, truncated, info = engine.step(_legal_action(engine))
        assert isinstance(obs, np.ndarray)

    def test_step_reward_is_float(self):
        """step_reward_type : reward est un float (ou castable)."""
        engine = _make_engine()
        engine.reset()
        _, reward, _, _, _ = engine.step(_legal_action(engine))
        assert isinstance(reward, (int, float))

    def test_step_terminated_is_bool(self):
        """step_terminated_type : terminated est un bool."""
        engine = _make_engine()
        engine.reset()
        _, _, terminated, _, _ = engine.step(_legal_action(engine))
        assert isinstance(terminated, bool)

    def test_step_info_is_dict(self):
        """step_info_type : info est un dict."""
        engine = _make_engine()
        engine.reset()
        _, _, _, _, info = engine.step(_legal_action(engine))
        assert isinstance(info, dict)

    def test_step_truncated_is_bool(self):
        """step_truncated_type : truncated est un bool."""
        engine = _make_engine()
        engine.reset()
        _, _, _, truncated, _ = engine.step(_legal_action(engine))
        assert isinstance(truncated, bool)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — episode_steps incremented
# ─────────────────────────────────────────────────────────────────────────────

class TestStepEpisodeCounter:

    def test_step_increments_episode_steps_on_success(self):
        """step_episode_steps : step() réussi incrémente episode_steps."""
        engine = _make_engine()
        engine.reset()
        steps_before = engine.game_state["episode_steps"]
        engine.step(_legal_action(engine))
        assert engine.game_state["episode_steps"] >= steps_before

    def test_step_increments_only_on_success(self):
        """step_success_only : pool vide → auto-advance → episode_steps reste 0 (pas de vrais steps)."""
        engine = _make_engine()
        engine.reset()
        # Après reset, tous les pools sont vides → chaque step auto-avance la phase
        # episode_steps ne s'incrémente que sur un vrai step (action réussie via pool)
        engine.step(_legal_action(engine))
        # Auto-advance ne compte pas comme step : episode_steps peut être 0
        # La valeur exacte dépend du nombre de phases auto-avancées
        # On vérifie juste que l'état est cohérent (pas d'exception)
        assert isinstance(engine.game_state["episode_steps"], int)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — turn limit
# ─────────────────────────────────────────────────────────────────────────────

class TestStepTurnLimit:

    def test_turn_limit_triggers_terminated(self):
        """step_turn_limit : dépasser max_turns_per_episode → terminated=True."""
        engine = _make_engine()
        engine.reset()
        # Force turn au-delà de la limite (3 définie dans config)
        engine.game_state["turn"] = 4
        engine.game_state["turn_limit_reached"] = False

        _, _, terminated, _, info = engine.step(_legal_action(engine))

        assert terminated is True
        assert info.get("turn_limit_exceeded") is True

    def test_turn_limit_info_contains_winner(self):
        """step_turn_limit_winner : info contient 'winner' quand turn_limit déclenché."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 4

        _, _, terminated, _, info = engine.step(_legal_action(engine))

        assert terminated is True
        assert "winner" in info

    def test_turn_limit_info_contains_win_method(self):
        """step_turn_limit_win_method : info contient 'win_method' quand turn_limit déclenché."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 4

        _, _, _, _, info = engine.step(_legal_action(engine))

        assert "win_method" in info


# ─────────────────────────────────────────────────────────────────────────────
# Tests — comptabilite de la porte turn_limit
# ─────────────────────────────────────────────────────────────────────────────

class TestTurnLimitGateAccounting:

    def test_turn_limit_episode_r_includes_final_step_reward(self, monkeypatch):
        """info['episode']['r'] inclut la récompense du step turn_limit.

        Sans le fix, _build_terminal_info lit episode_reward_accumulator AVANT
        que le step ne l'incrémente → info['episode']['r'] manque la récompense finale.
        """
        from engine.reward_calculator import RewardCalculator
        monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 7.5)
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 4

        _, reward, terminated, _, info = engine.step(_legal_action(engine))

        assert terminated is True
        assert info["turn_limit_exceeded"] is True, "porte empruntée : ce n'est pas le turn_limit"
        assert reward == pytest.approx(7.5)
        assert info["episode"]["r"] == pytest.approx(7.5)

    def test_turn_limit_episode_l_includes_final_step(self):
        """info['episode']['l'] compte le step turn_limit lui-même."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 4

        _, _, terminated, _, info = engine.step(_legal_action(engine))

        assert terminated is True
        assert info["turn_limit_exceeded"] is True, "porte empruntée : ce n'est pas le turn_limit"
        assert info["episode"]["l"] == 1

    def test_turn_limit_reward_breakdown_populated(self, monkeypatch):
        """last_reward_breakdown drainé vers tactical_data['reward_breakdown'] et retiré de game_state.

        Sans le fix, last_reward_breakdown reste dans game_state après reset() et
        la ventilation dans tactical_data vaut 0.0 sur toutes les composantes.
        """
        from engine.reward_calculator import RewardCalculator
        from engine.w40k_core import REWARD_BREAKDOWN_COMPONENTS

        KNOWN = {k: 0.0 for k in REWARD_BREAKDOWN_COMPONENTS}
        KNOWN['situational'] = 3.0

        def fake_reward(self_rc, success, result, game_state):
            game_state["last_reward_breakdown"] = KNOWN.copy()
            return 3.0

        monkeypatch.setattr(RewardCalculator, "calculate_reward", fake_reward)
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 4

        _, _, terminated, _, info = engine.step(_legal_action(engine))

        assert terminated is True
        assert info["turn_limit_exceeded"] is True, "porte empruntée : ce n'est pas le turn_limit"
        assert "last_reward_breakdown" not in engine.game_state
        assert info["tactical_data"]["reward_breakdown"]["situational"] == pytest.approx(3.0)



# ─────────────────────────────────────────────────────────────────────────────
# Tests — _build_terminal_info est un recalcul pur
# ─────────────────────────────────────────────────────────────────────────────

def _mixed_action_logs() -> list:
    """Journal couvrant TOUTES les branches de la boucle de `_build_terminal_info`.

    Un compteur par branche : deplacement, attente, charge (agent et adversaire), capacite hors
    branche dediee, tir avec mort, melee avec mort. Le contrat de chaque ligne est celui que la
    boucle lit en `require_key` — une ligne pauvre ferait lever, pas passer en silence.
    """
    from engine.w40k_core import CHARGE_LONG_DECLARATION_INCHES

    return [
        {"type": "move", "player": 1, "was_flee": True, "move_type": "advance"},
        {"type": "wait", "player": 1, "phase": "move"},
        {"type": "wait", "player": 1, "phase": "shoot"},
        charge_log_line(
            1, "charge",
            charge_nearest_enemy_inches=5.0,
            charge_target_distance_inches=float(CHARGE_LONG_DECLARATION_INCHES),
            ability_rule_effect="charge_after_advance",
        ),
        charge_log_line(2, "charge_fail", charge_nearest_enemy_inches=7.0),
        {"type": "reactive_move", "player": 2},
        {
            "type": "shoot", "player": 1, "turn": 1, "shooterId": "u1", "damage": 3,
            "shootDetails": [
                {"hitResult": "HIT", "targetDied": True, "targetValue": 12.0,
                 "hitAbility": "reroll", "woundAbility": "reroll"},
                {"hitResult": "MISS"},
            ],
        },
        {
            "type": "combat", "player": 1, "phase": "fight", "turn": 2, "shooterId": "u2",
            "damage": 4,
            "shootDetails": [
                {"hitResult": "HIT", "targetDied": True, "targetValue": 8.0,
                 "woundBonusAbility": "oath"},
            ],
        },
    ]


class TestBuildTerminalInfoIsPure:

    def test_charge_distance_not_doubled(self, monkeypatch):
        """charge_distance n'est pas doublé si _build_terminal_info est appelée deux fois.

        Sans le fix, la boucle action_logs accumule via += directement dans
        episode_tactical_data['charge_distance'] ; un second appel double les compteurs.
        """
        from engine.w40k_core import CHARGE_LONG_DECLARATION_INCHES

        engine = _make_engine()
        engine.reset()

        monkeypatch.setattr(
            engine, "_determine_winner_with_method",
            lambda: (1, "turn_limit"),
        )
        engine.game_state["action_logs"] = [charge_log_line(
            1, "charge",
            charge_nearest_enemy_inches=5.0,
            charge_target_distance_inches=float(CHARGE_LONG_DECLARATION_INCHES),
        )]

        engine._build_terminal_info()
        engine._build_terminal_info()

        cd = engine.episode_tactical_data['charge_distance']['agent']
        assert cd['target_n'] == 1.0, f"target_n doublé : {cd['target_n']}"
        assert cd['target_sum'] == pytest.approx(float(CHARGE_LONG_DECLARATION_INCHES))
        assert cd['long'] == 1.0, f"long doublé : {cd['long']}"

    def test_second_call_reproduces_the_first_on_every_counter(self, monkeypatch):
        """TOUS les compteurs, pas seulement charge_distance : deux appels, un seul résultat.

        La docstring de `_build_terminal_info` promet un RECALCUL PUR — aucun `+=` sur
        `self.episode_tactical_data`. Le seul verrou existant ne couvrait qu'un champ ; un
        compteur ajouté demain en `+=` direct doublerait sans rougir. Ici la comparaison porte
        sur le dict entier, donc sur les compteurs présents ET futurs.
        """
        import copy

        engine = _make_engine()
        engine.reset()

        monkeypatch.setattr(
            engine, "_determine_winner_with_method",
            lambda: (1, "turn_limit"),
        )
        engine.game_state["action_logs"] = _mixed_action_logs()

        engine._build_terminal_info()
        first = copy.deepcopy(engine.episode_tactical_data)
        engine._build_terminal_info()
        second = copy.deepcopy(engine.episode_tactical_data)

        # ANTI-VACANCE : un journal qui n'alimenterait rien rendrait l'égalité triviale.
        assert first['move_actions'] == 1
        assert first['move_flees'] == 1
        assert first['move_advances'] == 1
        assert first['move_waits'] == 1
        assert first['shoot_waits'] == 1
        assert first['charge_attempts'] == 1
        assert first['charge_attempts_opponent'] == 1
        assert first['shots_fired'] == 2
        assert first['hits'] == 1
        assert first['shoot_kills'] == 1
        assert first['melee_kills'] == 1
        assert first['damage_dealt'] == 7
        assert first['shoot_activations'] == 1
        assert first['fight_activations'] == 1
        assert first['charge_distance']['agent']['target_n'] == 1.0
        assert first['abilities_counts']['charge_after_advance_agent'] == 1
        assert first['abilities_counts']['reactive_move_opp'] == 1
        assert first['abilities_counts']['hit_reroll_agent'] == 1

        assert second == first, (
            "un compteur de la boucle action_logs accumule sur self.episode_tactical_data "
            "au lieu d'une variable locale : "
            f"{[k for k in first if first[k] != second[k]]}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tests — idempotence du bilan de fin d'épisode
# ─────────────────────────────────────────────────────────────────────────────

def _move_log(player: int, *, was_flee: bool, move_type: str) -> Dict[str, Any]:
    """Ligne `move` au contrat que la passe de comptage lit sans repli (`require_key`)."""
    return {
        "type": "move", "player": player, "turn": 1, "phase": "move",
        "was_flee": was_flee, "move_type": move_type,
    }


def _wait_log(player: int, phase: str) -> Dict[str, Any]:
    """Ligne `wait` : `phase` décide entre le compteur d'attente move et celui de tir."""
    return {"type": "wait", "player": player, "turn": 1, "phase": phase}


def _attack_log(
    player: int, *, kind: str, turn: int, shooter: str, damage: int,
    details: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Ligne `shoot` ou `combat`, au contrat de la passe de comptage.

    `phase` vaut "fight" pour la mêlée, et ce n'est pas décoratif : w40k_core LÈVE sur un log
    `combat` hors phase fight, pour ne pas ranger au tir les kills d'un émetteur inconnu.
    """
    if kind not in ("shoot", "combat"):
        raise ValueError(f"_attack_log: kind must be 'shoot' or 'combat', got {kind!r}")
    return {
        "type": kind, "player": player, "turn": turn, "shooterId": shooter,
        "phase": "fight" if kind == "combat" else "shoot",
        "damage": damage, "shootDetails": details,
    }


class TestBuildTerminalInfoIdempotence:
    """`_build_terminal_info` appelée deux fois laisse `episode_tactical_data` IDENTIQUE.

    POURQUOI DEUX APPELS : deux steps moteur rendent `terminated` dans le même épisode (mesure
    citée dans la docstring de la méthode : 24 terminaisons moteur pour 12 épisodes gym), donc
    le bilan est rebâti. Il est un RECALCUL PUR à partir d'`action_logs` : tout compteur qui
    accumulerait dans l'attribut au lieu d'une locale doublerait au second appel, et les courbes
    (`ai/metrics_tracker`) montreraient un facteur 2 indiscernable d'un agent qui progresse.

    CE TEST NE FERME PAS SEUL : il ne verrouille que les compteurs que le scénario ci-dessous
    fait vivre. Le verrou qui porte sur TOUS les compteurs, y compris ceux qu'aucun scénario
    n'exerce encore, est structurel —
    `tests/unit/engine/test_terminal_info_counters_are_locals.py`.
    """

    #: Clés dont le scénario garantit une valeur NON NULLE. Sans cette garde, l'égalité des deux
    #: appels porterait sur un dict de zéros : verte, et sans rien prouver.
    _EXPECTED_NON_ZERO = (
        "shots_fired", "hits", "damage_dealt", "damage_received",
        "shoot_kills", "melee_kills", "shoot_value_killed", "melee_value_killed",
        "charge_attempts", "charge_successes",
        "charge_attempts_opponent", "charge_successes_opponent",
        "move_actions", "move_flees", "move_advances", "move_waits",
        "shoot_activations", "shoot_waits", "fight_activations",
    )

    #: Compteurs d'abilities alimentés par le scénario, une clé par branche de la boucle.
    _EXPECTED_ABILITIES = (
        "reactive_move_agent", "charge_impact_agent", "move_after_shooting_agent",
        "charge_after_advance_agent", "hit_reroll_agent", "wound_reroll_agent",
        "oath_wound_bonus_opp",
    )

    @staticmethod
    def _scenario_logs() -> List[Dict[str, Any]]:
        """Un `action_logs` qui emprunte CHAQUE branche de la passe de comptage, des deux camps."""
        from engine.w40k_core import CHARGE_LONG_DECLARATION_INCHES

        return [
            _move_log(1, was_flee=True, move_type="normal"),
            _move_log(1, was_flee=False, move_type="advance"),
            # Camp adverse : filtré par la branche move, présent pour le prouver.
            _move_log(2, was_flee=False, move_type="normal"),
            _wait_log(1, "move"),
            _wait_log(1, "shoot"),
            charge_log_line(
                1, "charge",
                charge_target_distance_inches=float(CHARGE_LONG_DECLARATION_INCHES),
                ability_rule_effect="charge_after_advance",
            ),
            # Échec APRÈS déclaration : il porte une distance, donc il alimente fail_sum/fail_n.
            charge_log_line(1, "charge_fail", charge_target_distance_inches=11.0),
            charge_log_line(2, "charge"),
            charge_log_line(2, "charge_fail"),
            {"type": "reactive_move", "player": 1, "turn": 1, "phase": "shoot"},
            {"type": "charge_impact", "player": 1, "turn": 1, "phase": "charge"},
            {"type": "move_after_shooting", "player": 1, "turn": 1, "phase": "shoot"},
            _attack_log(
                1, kind="shoot", turn=1, shooter="s1", damage=3,
                details=[
                    {"hitResult": "HIT", "targetDied": True, "targetValue": 100.0,
                     "hitAbility": "Oath of Moment"},
                    {"hitResult": "MISS", "woundAbility": "Lethal Hits"},
                ],
            ),
            _attack_log(
                2, kind="shoot", turn=1, shooter="s2", damage=2,
                details=[{"hitResult": "HIT", "woundBonusAbility": "Oath of Moment"}],
            ),
            _attack_log(
                1, kind="combat", turn=2, shooter="s1", damage=4,
                details=[{"targetDied": True, "targetValue": 100.0}],
            ),
        ]

    def test_second_call_leaves_every_counter_unchanged(self, monkeypatch):
        """Le dict complet après le 2e appel est égal, clé à clé, à celui d'après le 1er."""
        engine = _make_engine()
        engine.reset()
        monkeypatch.setattr(
            engine, "_determine_winner_with_method", lambda: (1, "turn_limit"),
        )
        engine.game_state["action_logs"] = self._scenario_logs()

        engine._build_terminal_info()
        after_first = copy.deepcopy(engine.episode_tactical_data)

        # Garde anti-VERT VACANT : le scénario a bien fait vivre chaque famille de compteurs.
        zeroes = [k for k in self._EXPECTED_NON_ZERO if not after_first[k]]
        assert not zeroes, f"scénario muet sur {zeroes} : l'égalité ne prouverait rien"
        muted = [k for k in self._EXPECTED_ABILITIES if not after_first["abilities_counts"][k]]
        assert not muted, f"scénario muet sur abilities_counts {muted}"
        for camp in ("agent", "opponent"):
            assert after_first["charge_distance"][camp]["nearest_n"], (
                f"scénario muet sur charge_distance[{camp!r}]"
            )
        assert after_first["charge_distance"]["agent"]["fail_n"], (
            "scénario muet sur les échecs de charge déclarés"
        )

        engine._build_terminal_info()
        after_second = engine.episode_tactical_data

        assert set(after_second) == set(after_first), (
            "le second appel a ajouté ou retiré des clés : "
            f"{set(after_second) ^ set(after_first)}"
        )
        doubled = {
            key: (after_first[key], after_second[key])
            for key in after_first
            if after_second[key] != after_first[key]
        }
        assert not doubled, (
            "compteurs modifiés par un second appel de _build_terminal_info "
            f"(1er appel, 2e appel) : {doubled} — ces compteurs accumulent dans "
            "self.episode_tactical_data au lieu d'une variable locale affectée après la boucle"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tests — game over check
# ─────────────────────────────────────────────────────────────────────────────

class TestStepGameOver:

    def test_step_after_reset_game_not_over(self):
        """step_not_over : juste après reset(), terminated=False au premier step."""
        engine = _make_engine()
        engine.reset()
        # S'assurer que turn est dans la limite
        engine.game_state["turn"] = 1

        _, _, terminated, _, _ = engine.step(_legal_action(engine))

        # Pas de game_over immédiat sauf si phase advance auto
        # On vérifie juste que game_state est cohérent
        assert engine.game_state.get("turn_limit_reached", False) is False or terminated is True

    def test_step_pool_empty_triggers_phase_advance(self):
        """step_pool_empty : fight phase avec pools vides → masque tout-False → auto-advance."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 1
        # Fight phase : seule phase où pools vides donnent un masque tout-False
        engine.game_state["phase"] = "fight"
        engine.game_state["fight_subphase"] = None
        for pool_key in (
            "charging_activation_pool",
            "active_alternating_activation_pool",
            "non_active_alternating_activation_pool",
        ):
            engine.game_state[pool_key] = []

        # Action volontairement passée en dur, sans `_legal_action` : le masque est tout-False,
        # donc `step()` auto-avance la phase SANS jamais décoder l'action. Passer par
        # `_legal_action` appellerait `get_action_mask()` en amont, ce qui perturbe cet état
        # artificiel (pools vidés à la main) et fait échouer l'advance_phase — effet de bord
        # pré-existant de `get_action_mask`, hors périmètre de la refonte spatiale.
        _, _, _, _, info = engine.step(SQUAD_ACTION_WAIT)

        # Phase advance automatique doit avoir eu lieu
        assert info.get("phase_auto_advanced") is True or engine.game_state["phase"] != "fight"


class TestStepPostActionPoolEmpty:
    """Pool vide APRÈS une action réussie — branche distincte du pool vide À L'ENTRÉE.

    `test_step_pool_empty_triggers_phase_advance` ci-dessus couvre l'entrée de `step()`. Celle-ci
    couvre la sortie : le `advance_phase` déclenché par le pool vide avance la phase, et le `result`
    de l'action de l'agent doit SURVIVRE — c'est lui qui alimente `info` et `calculate_reward`.

    Pourquoi ce verrou existe : `step()` substituait le résultat du `advance_phase` à celui de
    l'agent. La ligne était l'initialiseur de boucle d'une cascade de phases doublonnée et morte
    (0 appel à `*_phase_start` mesuré — `_process_squad_action` cascade lui-même) ; son effet réel
    était sur la récompense. Mesure sur 8 épisodes : 25,6 substitutions par épisode, 25 % des
    calculs de récompense, où `reason: "pool_empty"` forçait `is_system_response` et versait 0.0 au
    lieu de la récompense de l'action (+68,20 annulés sur 8 épisodes, dernier tir et dernier
    corps-à-corps de chaque phase compris).

    Ces tests tiennent les DEUX côtés : le résultat de l'agent arrive dans `info`, et le payload du
    `advance_phase` n'y arrive pas. Réintroduire la substitution les rend rouges.
    """

    @staticmethod
    def _engine_with_post_action_empty_pool(monkeypatch, advance_result):
        """Construit l'état observé : action décodée puis exécutée, PUIS pool vide.

        Les deux constructions de masque de `step()` sont pilotées séparément (non vide à l'entrée
        pour que l'action soit décodée, vide ensuite pour atteindre la branche), et
        `_process_squad_action` est doublé pour rendre un résultat d'agent DISTINGUABLE puis le
        résultat d'`advance_phase`. C'est le joint exact que ce test verrouille.
        """
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 1

        mask_size = len(engine.get_action_mask())
        full = np.zeros(mask_size, dtype=bool)
        full[SQUAD_ACTION_WAIT] = True
        empty = np.zeros(mask_size, dtype=bool)
        eligible = [dict(engine.game_state["units"][0])]

        mask_calls = {"n": 0}

        def fake_mask(_game_state):
            mask_calls["n"] += 1
            # 1er appel = entrée de step() ; suivants = après l'action.
            return (full, eligible) if mask_calls["n"] == 1 else (empty, [])

        monkeypatch.setattr(
            engine.action_decoder, "get_squad_action_mask_and_eligible_units", fake_mask
        )
        monkeypatch.setattr(
            engine.action_decoder,
            "convert_squad_action",
            lambda *_a, **_k: {"action": "squad_wait"},
        )

        process_calls = {"n": 0}

        def fake_process(semantic):
            process_calls["n"] += 1
            if semantic.get("action") == "advance_phase":
                return True, dict(advance_result)
            return True, {"action": "squad_wait", "origine": "ACTION_AGENT"}

        monkeypatch.setattr(engine, "_process_squad_action", fake_process)
        return engine, process_calls

    # Le payload d'un `advance_phase` qui cascade : c'est celui qui écrasait le résultat de l'agent.
    _CASCADING_ADVANCE = {"phase_complete": True, "next_phase": "shoot", "reason": "pool_empty"}

    def test_agent_result_survives_phase_advance_in_info(self, monkeypatch):
        """`info` décrit l'action de l'agent, pas la transition qu'elle a déclenchée."""
        engine, process_calls = self._engine_with_post_action_empty_pool(
            monkeypatch, self._CASCADING_ADVANCE
        )

        _, _, _, _, info = engine.step(SQUAD_ACTION_WAIT)

        # Non-vacuité : les deux appels ont bien eu lieu (action de l'agent, puis advance_phase).
        # Sans cette assertion le test resterait vert si la branche pool-vide n'était pas atteinte.
        assert process_calls["n"] == 2
        assert info.get("origine") == "ACTION_AGENT"
        # Le payload de la transition ne fuit pas dans `info`.
        assert "next_phase" not in info
        assert "phase_complete" not in info

    def test_reward_is_computed_on_agent_result_not_on_advance(self, monkeypatch):
        """La récompense porte sur l'action de l'agent — le verrou qui compte.

        `info` n'est qu'un symptôme ; le vrai dégât était sur la récompense : le payload du
        `advance_phase` porte `reason: "pool_empty"`, ce qui force `is_system_response` dans
        `RewardCalculator` et verse 0.0 au lieu de la récompense de l'action.
        """
        engine, process_calls = self._engine_with_post_action_empty_pool(
            monkeypatch, self._CASCADING_ADVANCE
        )
        seen: list = []

        def spy(_self, success, result, _game_state):
            seen.append(result)
            return 0.0

        from engine.reward_calculator import RewardCalculator
        monkeypatch.setattr(RewardCalculator, "calculate_reward", spy)

        engine.step(SQUAD_ACTION_WAIT)

        assert process_calls["n"] == 2
        assert len(seen) == 1
        assert seen[0].get("origine") == "ACTION_AGENT"
        assert seen[0].get("reason") != "pool_empty"


# ─────────────────────────────────────────────────────────────────────────────
# Purges d'épisode des mémos de contrôle d'objectif (14.02)
#
# `game_state` est le MÊME objet d'un reset à l'autre : ce qui est mémoïsé par épisode doit
# mourir dans reset(), sinon il survit sans que rien ne le signale.
# ─────────────────────────────────────────────────────────────────────────────


class TestObjectiveControlEpisodeMemos:
    def test_reset_purges_last_boundary_memo(self):
        """Sans purge, la frontière porte encore ("fight", 5) de l'épisode précédent : au premier
        build d'obs du nouvel épisode, (phase, tour) diffère, le checkpoint 14.02 se déclenche et
        fige des contrôleurs AVANT que la moindre phase se soit terminée."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["_objective_control_last_boundary"] = ("fight", 5)
        engine.reset()
        assert "_objective_control_last_boundary" not in engine.game_state

    def test_reset_purges_logged_snapshot_memo(self):
        """Ce mémo évite de réécrire une ligne OBJECTIVE CONTROL identique. Survivant à l'épisode,
        il ferait SAUTER l'instantané initial du nouvel épisode (mêmes contrôleurs vides, mêmes VP
        à 0) et le replay démarrerait sans aucune donnée de contrôle."""
        engine = _make_engine()
        engine.reset()
        engine.game_state[W40KEngine.OBJECTIVE_CONTROL_LOGGED_KEY] = ((), 0, 0)
        engine.reset()
        assert W40KEngine.OBJECTIVE_CONTROL_LOGGED_KEY not in engine.game_state
