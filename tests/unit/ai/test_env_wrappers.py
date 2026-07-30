from typing import Any, Dict, List, Tuple

import gymnasium as gym
import numpy as np
import pytest

from ai.env_wrappers import (
    ENGINE_CONTRACT_ATTRS,
    BotControlledEnv,
    SelfPlayWrapper,
    unwrap_engine,
)
from engine.action_decoder import ActionValidationError
from engine import macro_intents as mi


class _DummyActionDecoder:
    def __init__(self, mask=None, eligible=None, normalized_action=4, raise_validation=False):
        self._mask = list(mask) if mask is not None else [False] * 12
        self._eligible = list(eligible) if eligible is not None else []
        self._normalized_action = normalized_action
        self._raise_validation = raise_validation

    # `get_action_mask_and_eligible_units` a été retiré de cette stub avec la méthode qu'elle
    # imitait (masque de l'ancien espace 0-15, supprimé le 2026-07-29 — cf. la pierre tombale
    # d'`engine/action_decoder.py`). Le pipeline squad est le seul chemin.
    def get_squad_action_mask_and_eligible_units(self, game_state):
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
        # Report d'observation (cf. W40KEngine._step_observation) : membre du contrat moteur.
        self.defer_observation = False
        self.build_observation_calls = 0
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
        # Miroir de `W40KEngine.step` : l'observation retournee passe par le report.
        return self._step_observation(), 0.0, False, False, {}

    def _step_observation(self):
        if self.defer_observation:
            return None
        return self._build_observation()

    def _build_observation(self):
        self.build_observation_calls += 1
        return np.zeros((4,), dtype=np.float32)

    def _check_game_over(self):
        return False

    def _determine_winner_with_method(self):
        return None, None

    def get_turn_step_limit(self) -> int:
        """Plafond anti-runaway d'un tour, comme `W40KEngine.get_turn_step_limit`.

        Fait partie du contrat moteur verifie par `unwrap_engine` : un double qui ne l'expose
        pas n'est pas un moteur pour ces wrappers, et le deballage doit le refuser.
        """
        return 200

    def close(self):
        return None


class _DummyBot:
    """Doublure FIDELE au contrat exige par `BotControlledEnv._get_bot_action`.

    Meme surface que les bots reels (`ai/evaluation_bots.py` : RandomBot, GreedyBot,
    DefensiveBot, ControlBot, ...) : `select_action_with_state(valid_actions, game_state,
    active_unit) -> int`. La doublure precedente n'exposait qu'un `select_action(valid_actions)`
    qui n'existe sur AUCUN bot de production — le wrapper ne l'a jamais appele, et le test
    couvrait un chemin imaginaire.

    Les arguments recus sont enregistres : c'est la seule facon de verifier que le wrapper
    transmet bien l'escouade ACTIVEE (`eligible_units[0]`) et les seules actions du masque.
    """

    def __init__(self, action: int = 4) -> None:
        self._action = action
        self.received: List[Tuple[List[int], Dict[str, Any], Dict[str, Any]]] = []

    def select_action_with_state(
        self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]
    ) -> int:
        self.received.append((list(valid_actions), game_state, active_unit))
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
    assert wrapper._get_bot_action() == mi.ACTION_WAIT


def test_get_bot_action_raises_on_empty_mask_with_eligible_units() -> None:
    decoder = _DummyActionDecoder(mask=[False] * 12, eligible=[{"id": "u1", "player": 2}])
    engine = _DummyEngine(decoder=decoder)
    wrapper = BotControlledEnv(engine, bot=_DummyBot())
    with pytest.raises(RuntimeError, match=r"empty action mask"):
        wrapper._get_bot_action()


def test_get_bot_action_tracks_shoot_stats_and_returns_normalized_action() -> None:
    slot = mi.SHOOT_SLOT_BASE  # 19
    mask = [False] * mi.TOTAL_ACTION_SIZE
    mask[slot] = True
    eligible = [{"id": "u1", "player": 2}]
    decoder = _DummyActionDecoder(mask=mask, eligible=eligible, normalized_action=slot)
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["phase"] = "shoot"
    bot = _DummyBot(action=slot)
    wrapper = BotControlledEnv(engine, bot=bot)
    action = wrapper._get_bot_action()
    assert action == slot
    assert wrapper.shoot_opportunities == 1
    assert wrapper.shoot_actions == 1
    # Le wrapper a bien consulte le bot par le contrat reel, avec les SEULES actions du masque
    # et l'escouade ACTIVEE (`eligible_units[0]`) — pas `current_player`, pas un slot devine.
    assert len(bot.received) == 1
    seen_actions, seen_state, seen_unit = bot.received[0]
    assert seen_actions == [slot]
    assert seen_state is engine.game_state
    assert seen_unit is eligible[0]


def test_get_bot_action_converts_validation_error_to_runtime_error() -> None:
    mask = [False] * 12
    mask[4] = True
    decoder = _DummyActionDecoder(
        mask=mask,
        eligible=[{"id": "u1", "player": 2}],
        normalized_action=4,
        raise_validation=True,
    )
    engine = _DummyEngine(decoder=decoder)
    # Phase non-move : la phase move est routee vers select_movement_destination (testee a part),
    # les autres phases passent par normalize/validate — c'est ce chemin qu'on couvre ici.
    engine.game_state["phase"] = "charge"
    wrapper = BotControlledEnv(engine, bot=_DummyBot(action=4))
    with pytest.raises(RuntimeError, match=r"Bot action validation failed"):
        wrapper._get_bot_action()


class _MoveDestBot:
    """Bot minimal pour la phase move : renvoie une destination fixe."""

    def __init__(self, dest):
        self._dest = dest

    def select_movement_destination(self, unit, valid_destinations, game_state):
        _ = (unit, valid_destinations, game_state)
        return self._dest


def _move_wrapper(cell_map, dest):
    """Wrapper + game_state gréé avec une carte de cellules mémoisée (anchor (5,5), phase move)."""
    engine = _DummyEngine()
    engine.game_state["phase"] = "move"
    engine.game_state["units_cache"] = {"u1": {"col": 5, "row": 5}}
    engine.game_state["_squad_move_cell_maps"] = {
        "u1": {"anchor": (5, 5), "phase": "move", "map": cell_map}
    }
    return BotControlledEnv(engine, bot=_MoveDestBot(dest)), engine.game_state


def test_select_bot_move_action_translates_destination_to_cell() -> None:
    # Cellules 10 -> (6,6), 20 -> (7,7). Le bot vise (7,7) -> cellule 20.
    cell_map = {10: ((6, 6), 3.0), 20: ((7, 7), 8.0)}
    wrapper, gs = _move_wrapper(cell_map, dest=(7, 7))
    action = wrapper._select_bot_move_action(gs, {"id": "u1"}, [10, 20, mi.ACTION_WAIT])
    assert action == 20


def test_select_bot_move_action_anchor_means_wait() -> None:
    # Le bot renvoie l'ancre (5,5) -> signal « je tiens ma position » -> WAIT.
    cell_map = {10: ((6, 6), 3.0)}
    wrapper, gs = _move_wrapper(cell_map, dest=(5, 5))
    action = wrapper._select_bot_move_action(gs, {"id": "u1"}, [10, mi.ACTION_WAIT])
    assert action == mi.ACTION_WAIT


def test_select_bot_move_action_no_move_cell_returns_wait() -> None:
    # Aucune cellule de move dans le masque (seul WAIT) -> WAIT, sans lire la carte.
    wrapper, gs = _move_wrapper({10: ((6, 6), 3.0)}, dest=(6, 6))
    action = wrapper._select_bot_move_action(gs, {"id": "u1"}, [mi.ACTION_WAIT])
    assert action == mi.ACTION_WAIT


def test_select_bot_move_action_illegal_destination_raises() -> None:
    # Le bot renvoie un hex hors des destinations legales et != ancre -> erreur explicite.
    cell_map = {10: ((6, 6), 3.0)}
    wrapper, gs = _move_wrapper(cell_map, dest=(9, 9))
    with pytest.raises(RuntimeError, match=r"hors des .* destinations legales"):
        wrapper._select_bot_move_action(gs, {"id": "u1"}, [10, mi.ACTION_WAIT])


def test_self_play_wrapper_get_frozen_model_action_fallback_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    # No eligible units -> WAIT
    decoder_no_units = _DummyActionDecoder(mask=[False] * 12, eligible=[])
    wrapper_no_units = SelfPlayWrapper(_DummyEngine(decoder=decoder_no_units))
    assert wrapper_no_units._get_frozen_model_action() == mi.ACTION_WAIT

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
    wrapper_valid = SelfPlayWrapper(_DummyEngine(decoder=decoder_valid), allow_random_opponent=True)
    monkeypatch.setattr("random.choice", lambda seq: seq[-1])
    assert wrapper_valid._get_frozen_model_action() == 7

    # V11 §10.4 : sans opt-in explicite, pas de repli silencieux sur du hasard.
    wrapper_refuses = SelfPlayWrapper(_DummyEngine(decoder=decoder_valid))
    with pytest.raises(RuntimeError, match=r"adversaire d'entrainement valide"):
        wrapper_refuses._get_frozen_model_action()


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


# ─────────────────────────────────────────────────────────────────────────────
# V11 §9.3 (P2) — décision agent : qui la possède, et qui la joue côté bot
# ─────────────────────────────────────────────────────────────────────────────


def _decision_state(player: int) -> dict:
    """`game_state` portant une décision en attente, appartenant à `player`."""
    return {
        "type": "rule_choice",
        "player": player,
        "unit_id": "u9",
        "options": [
            {"label": "A", "effect_ids": ("reroll_1_tohit_fight",), "payload": {}},
            {"label": "B", "effect_ids": ("reroll_1_save_fight",), "payload": {}},
        ],
    }


class _PassthroughDecoder(_DummyActionDecoder):
    """Decodeur stub qui rend l'action telle quelle : sans lui, le tirage du bot serait masque
    par la normalisation figee du stub de base."""

    def normalize_action_input(self, raw_action, phase, source, action_space_size):
        _ = (phase, source, action_space_size)
        return int(raw_action)


def _decision_mask() -> list:
    mask = [False] * mi.TOTAL_ACTION_SIZE
    mask[mi.CHOICE_BASE] = True
    mask[mi.CHOICE_BASE + 1] = True
    return mask


def test_decision_owner_is_the_player_of_the_pending_decision() -> None:
    """Le pool d'unités éligibles est vide pendant une décision : sans ce cas, le wrapper
    conclurait « personne ne décide » et tenterait d'avancer une phase que la décision bloque."""
    decoder = _DummyActionDecoder(mask=_decision_mask(), eligible=[])
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["pending_agent_decision"] = _decision_state(player=2)
    wrapper = BotControlledEnv(engine, bot=_DummyBot())
    owner, has_valid_actions, eligible_count = wrapper._get_decision_owner_from_mask()
    assert owner == 2
    assert has_valid_actions is True
    assert eligible_count == 0


def test_bot_plays_its_own_decision_instead_of_waiting() -> None:
    """La décision du camp BOT est jouée par le bot — plus par l'action de l'agent (§9.4 point 0).

    Sans ce branchement, `_get_bot_action` retomberait sur `ACTION_WAIT`, action que le masque
    d'une décision n'autorise pas.
    """
    decoder = _PassthroughDecoder(mask=_decision_mask(), eligible=[])
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["pending_agent_decision"] = _decision_state(player=2)
    wrapper = BotControlledEnv(engine, bot=_DummyBot())
    for _ in range(20):
        action = wrapper._get_bot_action()
        assert action in (mi.CHOICE_BASE, mi.CHOICE_BASE + 1), (
            "le bot doit jouer un CANDIDAT, pas une action de phase"
        )


def test_self_play_opponent_plays_its_own_decision() -> None:
    """Symétrique du bot : sans `frozen_model`, l'adversaire self-play joue un CHOICE.

    `ACTION_WAIT` est hors masque quand une décision est en attente : le renvoyer lèverait à la
    validation. Avec un `frozen_model`, la prédiction masquée choisit déjà un `CHOICE_i`.
    """
    decoder = _PassthroughDecoder(mask=_decision_mask(), eligible=[])
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["pending_agent_decision"] = _decision_state(player=2)
    wrapper = SelfPlayWrapper(engine, allow_random_opponent=True)
    for _ in range(20):
        assert wrapper._get_frozen_model_action() in (mi.CHOICE_BASE, mi.CHOICE_BASE + 1)


class _NotAnEngine(gym.Env):
    """Noyau qui n'honore PAS le contrat moteur : ni `game_state`, ni le reste."""

    metadata = {}

    def reset(self, *, seed=None, options=None):
        _ = (seed, options)
        return np.zeros((4,), dtype=np.float32), {}

    def step(self, action):
        _ = action
        return np.zeros((4,), dtype=np.float32), 0.0, False, False, {}


class _PassthroughWrapper(gym.Wrapper):
    """Wrapper quelconque, pour simuler un changement d'ordre d'emballage."""


def test_unwrap_engine_peels_every_wrapper_layer() -> None:
    """Le déballage descend jusqu'au moteur quelle que soit la PROFONDEUR de la pile.

    Les deux déballages précédents divergeaient : l'un pelait un seul niveau, l'autre tous.
    Ajouter un wrapper entre le moteur et `BotControlledEnv` faisait donc silencieusement
    pointer `self.engine` sur un wrapper — l'erreur ne serait apparue qu'au premier attribut
    manquant, très loin de la cause.
    """
    engine = _DummyEngine()
    stack = _PassthroughWrapper(_PassthroughWrapper(engine))
    assert unwrap_engine(stack, "test") is engine
    assert unwrap_engine(engine, "test") is engine, "un env non emballé est un cas légitime"


def test_unwrap_engine_names_what_it_found() -> None:
    """Quand l'affirmation est fausse, l'erreur nomme la pile, le type atteint et le manquant."""
    stack = _PassthroughWrapper(_NotAnEngine())
    with pytest.raises(TypeError) as excinfo:
        unwrap_engine(stack, "BotControlledEnv")
    message = str(excinfo.value)
    assert "BotControlledEnv" in message
    assert "_PassthroughWrapper -> _NotAnEngine" in message
    assert "game_state" in message


def test_engine_contract_covers_every_engine_access() -> None:
    """`ENGINE_CONTRACT_ATTRS` doit couvrir TOUS les `self.engine.<x>` du module.

    Sinon la vérification cesse de prouver ce qu'elle affirme : un membre utilisé mais non
    listé retomberait sur un AttributeError tardif, exactement ce que le cast faisait.
    """
    import ast
    import inspect

    import ai.env_wrappers as env_wrappers

    source = inspect.getsource(env_wrappers)
    used = {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "engine"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "self"
    }
    assert used, "aucun accès self.engine.<x> détecté : le balayage AST est cassé"
    assert used <= set(ENGINE_CONTRACT_ATTRS), (
        f"membres du moteur utilisés mais non vérifiés par unwrap_engine : "
        f"{sorted(used - set(ENGINE_CONTRACT_ATTRS))}"
    )


def test_wrappers_refuse_a_core_that_is_not_an_engine() -> None:
    """Les deux wrappers refusent à la CONSTRUCTION un noyau hors contrat."""
    with pytest.raises(TypeError, match="n'honore pas le contrat moteur"):
        BotControlledEnv(_PassthroughWrapper(_NotAnEngine()), bot=_DummyBot())
    with pytest.raises(TypeError, match="n'honore pas le contrat moteur"):
        SelfPlayWrapper(_PassthroughWrapper(_NotAnEngine()), allow_random_opponent=True)


# ─── Report d'observation (perf) — cf. W40KEngine._step_observation ──────────────────────


def _deferral_wrapper() -> Tuple[BotControlledEnv, "_DummyEngine"]:
    """Wrapper dont le tour appartient a l'AGENT : `step` applique l'action puis rend la main."""
    mask = [False] * mi.TOTAL_ACTION_SIZE
    mask[mi.ACTION_WAIT] = True
    decoder = _DummyActionDecoder(
        mask=mask, eligible=[{"id": "u1", "player": 1}], normalized_action=mi.ACTION_WAIT
    )
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["phase"] = "charge"
    wrapper = BotControlledEnv(engine, bot=_DummyBot(), agent_seat_mode="p1")
    wrapper.controlled_player = 1
    wrapper.bot_player = 2
    return wrapper, engine


def test_step_returns_a_real_observation_despite_deferral() -> None:
    """Le report ne doit JAMAIS laisser filtrer un `None` vers PPO.

    Un step gym enchaine plusieurs steps moteur ; seule la derniere observation est lue, mais
    elle doit etre reelle — c'est aussi le `terminal_observation` en fin d'episode.
    """
    wrapper, engine = _deferral_wrapper()
    obs, _reward, _term, _trunc, _info = wrapper.step(mi.ACTION_WAIT)
    assert obs is not None
    assert isinstance(obs, np.ndarray) and obs.shape == (4,)


def test_step_defers_intermediate_observations_and_builds_exactly_one() -> None:
    """Le report est REELLEMENT arme pendant le step, et une seule observation est construite.

    Sans cette assertion le report pourrait etre inactif (drapeau jamais pose) sans qu'aucun
    test ne bronche : le comportement resterait correct et le gain nul.
    """
    wrapper, engine = _deferral_wrapper()
    engine.build_observation_calls = 0
    seen_flag: List[bool] = []
    inner_step = engine.step

    def _spy(action):
        seen_flag.append(engine.defer_observation)
        return inner_step(action)

    engine.step = _spy  # type: ignore[method-assign]
    wrapper.step(mi.ACTION_WAIT)
    assert seen_flag and all(seen_flag), "defer_observation n'etait pas arme pendant les steps moteur"
    assert engine.build_observation_calls == 1


def test_step_clears_deferral_even_when_the_engine_raises() -> None:
    """Le drapeau ne doit pas survivre a une exception : sinon tout step ulterieur rendrait None."""
    wrapper, engine = _deferral_wrapper()

    def _boom(action):
        _ = action
        raise RuntimeError("boom moteur")

    engine.step = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="boom moteur"):
        wrapper.step(mi.ACTION_WAIT)
    assert engine.defer_observation is False
