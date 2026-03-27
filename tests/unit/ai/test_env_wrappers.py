import gymnasium as gym
import numpy as np
import pytest

from ai.env_wrappers import BotControlledEnv, SelfPlayWrapper
from engine.action_decoder import ActionValidationError


class _DummyActionDecoder:
    def __init__(self, mask=None, eligible=None, normalized_action=4, raise_validation=False):
        self._mask = list(mask) if mask is not None else [False] * 12
        self._eligible = list(eligible) if eligible is not None else []
        self._normalized_action = normalized_action
        self._raise_validation = raise_validation

    def get_action_mask_and_eligible_units(self, game_state):
        _ = game_state
        return self._mask, self._eligible

    def normalize_action_input(self, raw_action, phase, source, action_space_size):
        _ = (phase, source, action_space_size)
        return int(raw_action) if self._normalized_action is None else self._normalized_action

    def validate_action_against_mask(self, action_int, action_mask, phase, source, unit_id):
        _ = (action_int, action_mask, phase, source, unit_id)
        if self._raise_validation:
            raise ActionValidationError(
                code="DUMMY_INVALID_ACTION",
                message="invalid action from dummy decoder",
                context={"phase": phase, "source": source, "unit_id": unit_id},
            )


class _DummyEngine(gym.Env):
    metadata = {}

    def __init__(self, decoder=None):
        super().__init__()
        self.action_space = gym.spaces.Discrete(12)
        self.observation_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(4,), dtype=np.float32)
        self.action_decoder = decoder or _DummyActionDecoder()
        self.game_state = {
            "phase": "move",
            "debug_mode": False,
            "current_player": 1,
            "episode_number": 1,
            "episode_steps": 0,
        }
        self.config = {}

    def reset(self, *, seed=None, options=None):
        _ = (seed, options)
        return np.zeros((4,), dtype=np.float32), {}

    def step(self, action):
        _ = action
        return np.zeros((4,), dtype=np.float32), 0.0, False, False, {}

    def _build_observation(self):
        return np.zeros((4,), dtype=np.float32)

    def _check_game_over(self):
        return False

    def _determine_winner_with_method(self):
        return None, None

    def close(self):
        return None


class _DummyBot:
    def __init__(self, action=4):
        self._action = action

    def select_action(self, valid_actions):
        _ = valid_actions
        return self._action


def test_bot_controlled_env_requires_bot_or_bots() -> None:
    with pytest.raises(ValueError, match=r"requires either 'bot' or 'bots'"):
        BotControlledEnv(_DummyEngine(), bot=None, bots=None)


def test_bot_controlled_env_random_seat_requires_global_seed() -> None:
    with pytest.raises(ValueError, match=r"global_seed is required"):
        BotControlledEnv(_DummyEngine(), bot=_DummyBot(), agent_seat_mode="random")


def test_bot_controlled_env_self_play_enabled_requires_parameters() -> None:
    with pytest.raises(KeyError, match=r"self_play_ratio_start is required"):
        BotControlledEnv(_DummyEngine(), bot=_DummyBot(), self_play_opponent_enabled=True)


def test_resolve_controlled_player_respects_fixed_modes() -> None:
    wrapper_p1 = BotControlledEnv(_DummyEngine(), bot=_DummyBot(), agent_seat_mode="p1")
    wrapper_p2 = BotControlledEnv(_DummyEngine(), bot=_DummyBot(), agent_seat_mode="p2")
    assert wrapper_p1._resolve_controlled_player_for_episode() == 1
    assert wrapper_p2._resolve_controlled_player_for_episode() == 2


def test_compute_self_play_ratio_for_episode_progression() -> None:
    wrapper = BotControlledEnv(
        _DummyEngine(),
        bot=_DummyBot(),
        self_play_opponent_enabled=True,
        self_play_ratio_start=0.1,
        self_play_ratio_end=0.5,
        self_play_total_episodes=10,
        self_play_warmup_episodes=2,
        self_play_snapshot_path="snapshot.zip",
        self_play_snapshot_refresh_episodes=1,
        self_play_snapshot_device="cpu",
    )
    wrapper._episode_index = 1
    assert wrapper._compute_self_play_ratio_for_episode() == pytest.approx(0.1)
    wrapper._episode_index = 10
    assert wrapper._compute_self_play_ratio_for_episode() == pytest.approx(0.5)


def test_get_bot_action_returns_wait_when_no_eligible_units() -> None:
    decoder = _DummyActionDecoder(mask=[False] * 12, eligible=[])
    engine = _DummyEngine(decoder=decoder)
    wrapper = BotControlledEnv(engine, bot=_DummyBot(action=4))
    assert wrapper._get_bot_action() == 11


def test_get_bot_action_raises_on_empty_mask_with_eligible_units() -> None:
    decoder = _DummyActionDecoder(mask=[False] * 12, eligible=[{"id": "u1", "player": 2}])
    engine = _DummyEngine(decoder=decoder)
    wrapper = BotControlledEnv(engine, bot=_DummyBot())
    with pytest.raises(RuntimeError, match=r"empty action mask"):
        wrapper._get_bot_action()


def test_get_bot_action_tracks_shoot_stats_and_returns_normalized_action() -> None:
    mask = [False] * 12
    mask[4] = True
    decoder = _DummyActionDecoder(mask=mask, eligible=[{"id": "u1", "player": 2}], normalized_action=4)
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["phase"] = "shoot"
    wrapper = BotControlledEnv(engine, bot=_DummyBot(action=4))
    action = wrapper._get_bot_action()
    assert action == 4
    assert wrapper.shoot_opportunities == 1
    assert wrapper.shoot_actions == 1


def test_get_bot_action_converts_validation_error_to_runtime_error() -> None:
    mask = [False] * 12
    mask[4] = True
    decoder = _DummyActionDecoder(
        mask=mask,
        eligible=[{"id": "u1", "player": 2}],
        normalized_action=4,
        raise_validation=True,
    )
    wrapper = BotControlledEnv(_DummyEngine(decoder=decoder), bot=_DummyBot(action=4))
    with pytest.raises(RuntimeError, match=r"Bot action validation failed"):
        wrapper._get_bot_action()


def test_self_play_wrapper_get_frozen_model_action_fallback_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    # No eligible units -> WAIT
    decoder_no_units = _DummyActionDecoder(mask=[False] * 12, eligible=[])
    wrapper_no_units = SelfPlayWrapper(_DummyEngine(decoder=decoder_no_units))
    assert wrapper_no_units._get_frozen_model_action() == 11

    # Eligible units but no valid action -> explicit error
    decoder_empty = _DummyActionDecoder(mask=[False] * 12, eligible=[{"id": "u1", "player": 2}])
    wrapper_empty = SelfPlayWrapper(_DummyEngine(decoder=decoder_empty))
    with pytest.raises(RuntimeError, match=r"empty action mask"):
        wrapper_empty._get_frozen_model_action()

    # Eligible + valid with no frozen model -> random valid action
    mask = [False] * 12
    mask[3] = True
    mask[7] = True
    decoder_valid = _DummyActionDecoder(mask=mask, eligible=[{"id": "u1", "player": 2}])
    wrapper_valid = SelfPlayWrapper(_DummyEngine(decoder=decoder_valid))
    monkeypatch.setattr("random.choice", lambda seq: seq[-1])
    assert wrapper_valid._get_frozen_model_action() == 7


def test_self_play_wrapper_get_frozen_model_action_uses_frozen_model_predict() -> None:
    class FrozenModel:
        def predict(self, obs, deterministic, action_masks):
            _ = (obs, deterministic, action_masks)
            return 6, None

    mask = [False] * 12
    mask[6] = True
    decoder = _DummyActionDecoder(mask=mask, eligible=[{"id": "u1", "player": 2}])
    wrapper = SelfPlayWrapper(_DummyEngine(decoder=decoder), frozen_model=FrozenModel())
    assert wrapper._get_frozen_model_action() == 6


def test_self_play_wrapper_stats_helpers() -> None:
    wrapper = SelfPlayWrapper(_DummyEngine(), frozen_model=None, update_frequency=3)
    assert wrapper.should_update_frozen_model() is False
    wrapper.episodes_since_update = 3
    assert wrapper.should_update_frozen_model() is True

    zero_stats = wrapper.get_win_rate_stats()
    assert zero_stats["total_games"] == 0

    wrapper.player1_wins = 2
    wrapper.player2_wins = 1
    wrapper.draws = 1
    stats = wrapper.get_win_rate_stats()
    assert stats["total_games"] == 4
    assert stats["player1_win_rate"] == pytest.approx(50.0)


def test_get_decision_owner_from_mask_detects_mixed_owners() -> None:
    decoder = _DummyActionDecoder(
        mask=[True] + [False] * 11,
        eligible=[{"id": "u1", "player": 1}, {"id": "u2", "player": 2}],
    )
    wrapper = BotControlledEnv(_DummyEngine(decoder=decoder), bot=_DummyBot())
    with pytest.raises(RuntimeError, match=r"mixed owners"):
        wrapper._get_decision_owner_from_mask()


def test_compute_self_play_ratio_returns_zero_when_disabled() -> None:
    wrapper = BotControlledEnv(_DummyEngine(), bot=_DummyBot(), self_play_opponent_enabled=False)
    assert wrapper._compute_self_play_ratio_for_episode() == 0.0


def test_compute_self_play_ratio_interpolates_between_start_and_end() -> None:
    wrapper = BotControlledEnv(
        _DummyEngine(),
        bot=_DummyBot(),
        self_play_opponent_enabled=True,
        self_play_ratio_start=0.2,
        self_play_ratio_end=0.6,
        self_play_total_episodes=10,
        self_play_warmup_episodes=2,
        self_play_snapshot_path="snapshot.zip",
        self_play_snapshot_refresh_episodes=1,
        self_play_snapshot_device="cpu",
    )
    wrapper._episode_index = 6  # midpoint-ish after warmup
    ratio = wrapper._compute_self_play_ratio_for_episode()
    assert 0.2 < ratio < 0.6


def test_get_opponent_action_uses_self_play_branch_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = BotControlledEnv(_DummyEngine(), bot=_DummyBot(action=4))
    wrapper._episode_uses_self_play_opponent = True
    monkeypatch.setattr(wrapper, "_get_self_play_opponent_action", lambda: 9)
    assert wrapper._get_opponent_action() == 9
