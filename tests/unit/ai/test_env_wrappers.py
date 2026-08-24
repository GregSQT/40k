from typing import Any, Dict, List, Optional, Tuple, cast

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
    def __init__(self, mask=None, eligible=None, normalized_action: Optional[int] = 4, raise_validation=False):
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

    def activation_selection_slots(self, game_state, eligible_units=None):
        """Aucun choix d'activation en attente (V11 §0.48 `L2`).

        Ces doubles pilotent un masque SCRIPTÉ : le pool y est posé à la main, il n'y a donc pas
        d'ordre d'activation à choisir. `None` est la réponse exacte du décodeur réel dans ce
        cas — pas une neutralisation de commodité.
        """
        _ = (game_state, eligible_units)
        return None

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
        self.last_mask_and_eligible = None
        self.step_with_mask_calls = 0
        self.last_step_mask_and_eligible = None
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

    def step(self, action) -> tuple:
        # Miroir de `W40KEngine.step` : adaptateur gym 5-uplet au-dessus de `step_with_mask`.
        obs, reward, terminated, truncated, info, _mask = self.step_with_mask(action)
        return obs, reward, terminated, truncated, info

    def step_with_mask(self, action, mask_and_eligible=None) -> tuple:
        """Miroir de `W40KEngine.step_with_mask` — masque transmis dans les deux sens.

        Membre du contrat moteur (`ENGINE_CONTRACT_ATTRS`) : les wrappers l'appellent
        DIRECTEMENT, `step` n'etant plus que l'adaptateur gym. Le double enregistre le masque
        recu et rend celui de l'etat de sortie, comme le vrai moteur.
        """
        _ = action
        self.step_with_mask_calls += 1
        self.last_step_mask_and_eligible = mask_and_eligible
        obs, out_mask = self._step_observation()
        return obs, 0.0, False, False, {}, out_mask

    def get_action_mask(self):
        """Masque du moteur nu — ce que `BotControlledEnv.action_masks()` sert a defaut de depot."""
        mask, _eligible = self.action_decoder.get_squad_action_mask_and_eligible_units(
            self.game_state
        )
        return mask

    def auto_deployment_action(self, action_mask):
        """Pose que le MOTEUR jouerait a la place de la politique, ou None s'il n'en joue pas.

        Membre du contrat moteur (`ENGINE_CONTRACT_ATTRS`) : `BotControlledEnv` l'interroge a
        CHAQUE etat ou le joueur controle a une action jouable, pas seulement en deploiement.
        `None` n'est pas un repli : ce double n'a pas de phase de deploiement (sa `phase` est
        `move` ou `shoot`), donc le vrai moteur y rendrait `None` lui aussi.
        """
        _ = action_mask
        return None

    def _step_observation(self, mask_and_eligible=None):
        # Rend `(observation, masque_utilise)`, comme le vrai `_step_observation`.
        if self.defer_observation:
            return None, mask_and_eligible
        return self._build_observation(mask_and_eligible=mask_and_eligible), mask_and_eligible

    def _build_observation(self, mask_and_eligible=None):
        # `mask_and_eligible` fait partie du contrat moteur (cf. `W40KEngine._build_observation`) :
        # les wrappers le transmettent quand ils viennent de construire le masque.
        self.last_mask_and_eligible = mask_and_eligible
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


def test_compute_pool_ratio_for_episode_progression() -> None:
    wrapper = BotControlledEnv(
        _DummyEngine(),
        bot=_DummyBot(),
        self_play_opponent_enabled=True,
        self_play_ratio_start=0.1,
        self_play_ratio_end=0.5,
        self_play_total_episodes=10,
        self_play_warmup_episodes=2,
        self_play_n_envs=1,  # budgets deja exprimes par environnement dans ce test
        self_play_snapshot_path="snapshot.zip",
        self_play_snapshot_label="stub_v0",
        self_play_snapshot_refresh_episodes=1,
        self_play_snapshot_device="cpu",
    )
    wrapper._episode_index = 1
    assert wrapper._compute_pool_ratio_for_episode() == pytest.approx(0.1)
    wrapper._episode_index = 10
    assert wrapper._compute_pool_ratio_for_episode() == pytest.approx(0.5)


def test_self_play_ramp_is_expressed_per_environment() -> None:
    """Budgets GLOBAUX en entrée, rampe parcourue par CHAQUE worker (V11 §0.57).

    `_episode_index` ne compte que les épisodes de ce wrapper. Sans conversion, un run à 4 envs
    voyait chaque worker s'arrêter au quart de la rampe — figée près de `ratio_start`.
    """
    wrapper = BotControlledEnv(
        _DummyEngine(),
        bot=_DummyBot(),
        self_play_opponent_enabled=True,
        self_play_ratio_start=0.0,
        self_play_ratio_end=1.0,
        self_play_total_episodes=40,  # GLOBAL
        self_play_warmup_episodes=0,
        self_play_n_envs=4,           # → 10 épisodes par env
        self_play_snapshot_path="snapshot.zip",
        self_play_snapshot_label="stub_v0",
        self_play_snapshot_refresh_episodes=1,
        self_play_snapshot_device="cpu",
    )
    wrapper._episode_index = 0
    assert wrapper._compute_pool_ratio_for_episode() == pytest.approx(0.0)
    wrapper._episode_index = 10  # dernier épisode de CE worker
    assert wrapper._compute_pool_ratio_for_episode() == pytest.approx(1.0), (
        "la rampe self-play doit être parcourue en entier par chaque environnement"
    )


def test_self_play_requires_n_envs() -> None:
    """Sans `n_envs`, la rampe n'a pas de dénominateur : erreur explicite, aucun défaut silencieux."""
    with pytest.raises(KeyError, match="self_play_n_envs is required"):
        BotControlledEnv(
            _DummyEngine(),
            bot=_DummyBot(),
            self_play_opponent_enabled=True,
            self_play_ratio_start=0.0,
            self_play_ratio_end=1.0,
            self_play_total_episodes=40,
            self_play_warmup_episodes=0,
            self_play_snapshot_path="snapshot.zip",
            self_play_snapshot_refresh_episodes=1,
            self_play_snapshot_device="cpu",
        )


def test_self_play_requires_snapshot_label() -> None:
    """Sans `snapshot_label`, les scalars 03_selfplay/* seraient silencieusement absents : erreur explicite."""
    with pytest.raises(KeyError, match="self_play_snapshot_label is required"):
        BotControlledEnv(
            _DummyEngine(),
            bot=_DummyBot(),
            self_play_opponent_enabled=True,
            self_play_ratio_start=0.0,
            self_play_ratio_end=1.0,
            self_play_total_episodes=40,
            self_play_warmup_episodes=0,
            self_play_n_envs=4,
            self_play_snapshot_path="snapshot.zip",
            self_play_snapshot_label="",
            self_play_snapshot_refresh_episodes=1,
            self_play_snapshot_device="cpu",
        )


def test_self_play_requires_snapshot_label_none() -> None:
    """None (valeur par défaut du paramètre) doit lever la même erreur que la chaîne vide."""
    with pytest.raises(KeyError, match="self_play_snapshot_label is required"):
        BotControlledEnv(
            _DummyEngine(),
            bot=_DummyBot(),
            self_play_opponent_enabled=True,
            self_play_ratio_start=0.0,
            self_play_ratio_end=1.0,
            self_play_total_episodes=40,
            self_play_warmup_episodes=0,
            self_play_n_envs=4,
            self_play_snapshot_path="snapshot.zip",
            self_play_snapshot_label=None,
            self_play_snapshot_refresh_episodes=1,
            self_play_snapshot_device="cpu",
        )


def test_self_play_snapshot_label_stripped() -> None:
    """Un label avec espaces superflus est stocké sans ces espaces."""
    env = BotControlledEnv(
        _DummyEngine(),
        bot=_DummyBot(),
        self_play_opponent_enabled=True,
        self_play_ratio_start=0.0,
        self_play_ratio_end=1.0,
        self_play_total_episodes=40,
        self_play_warmup_episodes=0,
        self_play_n_envs=4,
        self_play_snapshot_path="snapshot.zip",
        self_play_snapshot_label="  snap_v1  ",
        self_play_snapshot_refresh_episodes=1,
        self_play_snapshot_device="cpu",
    )
    assert env._self_play_snapshot_label == "snap_v1"


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
    # `_select_bot_move_action` tranche d'ABORD sur `unit_is_in_strategic_reserves` (chantier
    # 04c) : une escouade en réserves n'a pas de destination de move mais des candidats de mise
    # en place, et les ids des slots 4-8 sont NUMÉRIQUEMENT dans la plage des cellules de move,
    # donc « la liste des cellules est-elle vide » ne peut pas les distinguer. Ce prédicat lit
    # l'unité par `unit_by_id` : le gréement doit donc porter une unité POSÉE.
    engine.game_state["unit_by_id"] = {
        "u1": {"id": "u1", "player": 1, "col": 5, "row": 5, "in_strategic_reserves": False}
    }
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
    mask = [False] * 12
    mask[6] = True
    decoder = _DummyActionDecoder(mask=mask, eligible=[{"id": "u1", "player": 2}])
    model = _StubFrozenModel(action=6)
    wrapper = SelfPlayWrapper(_DummyEngine(decoder=decoder), frozen_model=cast(Any, model))
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


def _frozen_pool_wrapper(**overrides):
    kwargs: Dict[str, Any] = dict(
        self_play_opponent_enabled=True,
        self_play_ratio_start=1.0,
        self_play_ratio_end=1.0,
        self_play_total_episodes=10,
        self_play_warmup_episodes=0,
        self_play_n_envs=1,
        self_play_snapshot_path="/introuvable/model_agent_P0.zip",
        self_play_snapshot_label="stub_v0",
        self_play_snapshot_device="cpu",
    )
    kwargs.update(overrides)
    return BotControlledEnv(_DummyEngine(), bot=_DummyBot(), **kwargs)


def test_a_frozen_pool_opponent_is_loaded_once_and_never_reread() -> None:
    """Un membre du pool est une archive : le relire, c'est payer 48 chargements pour rien.

    La preuve tient au chemin INTROUVABLE : toute relecture leverait `FileNotFoundError`.
    Le compteur d'episodes est pousse tres au-dela de n'importe quel `refresh` pour montrer
    que ce n'est pas lui qui retient le rechargement.
    """
    wrapper = _frozen_pool_wrapper(self_play_snapshot_frozen=True)
    wrapper._frozen_model = cast(Any, object())
    wrapper._episodes_since_snapshot_refresh = 10 ** 6
    wrapper._reload_self_play_snapshot_if_needed()


def test_a_non_frozen_snapshot_is_still_reread_when_the_counter_expires() -> None:
    """Jumeau du test precedent : sans `frozen`, la relecture a bien lieu."""
    wrapper = _frozen_pool_wrapper(self_play_snapshot_refresh_episodes=1)
    wrapper._frozen_model = cast(Any, object())
    wrapper._episodes_since_snapshot_refresh = 10 ** 6
    with pytest.raises(FileNotFoundError):
        wrapper._reload_self_play_snapshot_if_needed()


def test_a_frozen_snapshot_refuses_a_refresh_period() -> None:
    """Les deux ensemble n'ont pas de sens : le nombre serait ignore en silence."""
    with pytest.raises(ValueError, match="snapshot_frozen"):
        _frozen_pool_wrapper(
            self_play_snapshot_frozen=True, self_play_snapshot_refresh_episodes=10
        )


def test_compute_pool_ratio_returns_zero_when_disabled() -> None:
    wrapper = BotControlledEnv(_DummyEngine(), bot=_DummyBot(), self_play_opponent_enabled=False)
    assert wrapper._compute_pool_ratio_for_episode() == 0.0


def test_compute_pool_ratio_interpolates_between_start_and_end() -> None:
    wrapper = BotControlledEnv(
        _DummyEngine(),
        bot=_DummyBot(),
        self_play_opponent_enabled=True,
        self_play_ratio_start=0.2,
        self_play_ratio_end=0.6,
        self_play_total_episodes=10,
        self_play_warmup_episodes=2,
        self_play_n_envs=1,  # budgets deja exprimes par environnement dans ce test
        self_play_snapshot_path="snapshot.zip",
        self_play_snapshot_label="stub_v0",
        self_play_snapshot_refresh_episodes=1,
        self_play_snapshot_device="cpu",
    )
    wrapper._episode_index = 6  # midpoint-ish after warmup
    ratio = wrapper._compute_pool_ratio_for_episode()
    assert 0.2 < ratio < 0.6


def test_get_opponent_action_uses_self_play_branch_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = BotControlledEnv(_DummyEngine(), bot=_DummyBot(action=4))
    wrapper._episode_uses_self_play_opponent = True
    monkeypatch.setattr(wrapper, "_get_self_play_opponent_action", lambda decision=None: 9)
    # `_get_opponent_action` rend (action, decision encore valable). La branche self-play construit
    # une observation, donc MUTE l'etat : elle doit rendre None — c'est cette invalidation qui
    # empeche de transmettre au step suivant un masque devenu faux.
    action, surviving_decision = wrapper._get_opponent_action()
    assert action == 9
    assert surviving_decision is None


# ─────────────────────────────────────────────────────────────────────────────
# Masque porté d'un appelant à l'autre (cf. `MaskDecision`) — réutilisation ET péremption
# ─────────────────────────────────────────────────────────────────────────────


class _SequenceDecoder(_DummyActionDecoder):
    """Rend une réponse DIFFÉRENTE à chaque construction, et les compte.

    C'est le seul moyen de distinguer « le wrapper a relu le masque » de « il a rejoué le
    précédent » : avec un décodeur qui répond toujours pareil, les deux se lisent identiquement
    et le test afficherait vert dans les deux cas.
    """

    def __init__(self, responses) -> None:
        super().__init__(normalized_action=None)
        self._responses = list(responses)
        self.calls = 0

    def get_squad_action_mask_and_eligible_units(self, game_state):
        _ = game_state
        self.calls += 1
        return self._responses[min(self.calls - 1, len(self._responses) - 1)]


def _single_action_mask(slot: int) -> list:
    """Masque n'autorisant QUE `slot` — de quoi rendre identifiable le masque qu'un test observe."""
    mask = [False] * mi.TOTAL_ACTION_SIZE
    mask[slot] = True
    return mask


def test_reset_path_observation_cannot_advance_a_phase() -> None:
    """L'observation construite APRES l'unique contrôle ne doit pas pouvoir changer l'état.

    Le `reset` construit son observation sans report, donc après le contrat de sortie de la boucle
    et sans contrôle derrière. `_build_observation` avance la phase quand le pool est vide : la
    seule chose qui l'en empêche ici est qu'on lui transmette le masque du contrat, dont le pool
    est non vide. Ce test vérifie que ce masque est bien transmis — sinon la construction
    recalculerait, et un pool devenu vide entre-temps ferait avancer une phase juste avant de
    rendre l'état à la politique, sans que rien ne le voie.
    """
    slot = mi.SHOOT_SLOT_BASE
    engine = _DummyEngine(
        decoder=_DummyActionDecoder(
            mask=_single_action_mask(slot), eligible=[{"id": "c1", "player": 1}]
        )
    )
    engine.game_state["phase"] = "shoot"
    wrapper = BotControlledEnv(engine, bot=_DummyBot(action=slot), agent_seat_mode="p1")
    wrapper._apply_episode_seat()

    _obs, _reward, terminated, _truncated, _info, _ready = (
        wrapper._play_bot_until_control_returns(debug_mode=False)
    )

    assert not terminated
    assert engine.build_observation_calls == 1
    carried = engine.last_mask_and_eligible
    assert carried is not None, (
        "observation du reset construite sans masque : elle peut avancer une phase, et plus "
        "aucun controle ne verifie l'etat rendu a la politique"
    )
    assert carried[1], "le pool transmis est vide : la branche d'avancement redevient atteignable"


class _TerminatingDummyEngine(_DummyEngine):
    """Moteur qui termine l'episode SUR l'action de la politique.

    C'est le seul cas ou le jeu du bot d'apres est saute — donc le seul ou une decision etablie
    AVANT l'action pourrait survivre jusqu'a l'observation terminale.
    """

    #: Masque de l'etat d'APRES l'action — distinguable de tout masque d'avant.
    POST_ACTION_MASK = (np.zeros(1, dtype=bool), [{"id": "post", "player": 1}])

    def step_with_mask(self, action, mask_and_eligible=None) -> tuple:
        _ = (action, mask_and_eligible)
        self.step_with_mask_calls += 1
        obs, _out = self._step_observation()
        return obs, 0.0, True, False, {}, self.POST_ACTION_MASK


def test_terminal_observation_never_uses_a_pre_action_mask() -> None:
    """Verrou du mode grave : l'observation terminale ne doit PAS etre batie sur le masque d'avant
    l'action. Elle n'echoue pas bruyamment si c'est le cas — elle decrit juste un etat qui n'existe
    plus, et PPO l'apprend comme observation finale."""
    slot = mi.SHOOT_SLOT_BASE
    engine = _TerminatingDummyEngine(
        decoder=_DummyActionDecoder(
            mask=_single_action_mask(slot),
            eligible=[{"id": "c1", "player": 1}],
            normalized_action=slot,
        )
    )
    engine.game_state["phase"] = "shoot"
    wrapper = BotControlledEnv(engine, bot=_DummyBot(action=slot), agent_seat_mode="p1")
    wrapper._apply_episode_seat()

    _obs, _reward, terminated, _truncated, _info = wrapper.step(slot)

    assert terminated
    # Le verrou porte sur la PROVENANCE du masque, pas sur son absence : l'observation terminale
    # decrit l'etat d'apres l'action, donc elle a le droit d'utiliser le masque que le moteur a
    # construit sur CET etat (il remonte par le 6e element de `step_with_mask`). Ce qu'elle ne
    # doit jamais recevoir, c'est celui d'avant — un etat qui n'existe plus, appris par PPO comme
    # observation finale.
    # Identite des ELEMENTS et non du couple : il transite par une `MaskDecision` puis
    # `mask_pair_of`, qui reforme un tuple. Ce sont bien les memes objets qui arrivent.
    received = engine.last_mask_and_eligible
    assert received is not None, "l'observation terminale n'a recu aucun masque"
    assert received[0] is engine.POST_ACTION_MASK[0], (
        "l'observation terminale n'a pas recu le masque construit APRES l'action de la politique"
    )
    assert received[1] is engine.POST_ACTION_MASK[1]


class _StubFrozenModel:
    """Adversaire gele minimal : `predict(obs, deterministic, action_masks) -> (action, state)`."""

    def __init__(self, action: int) -> None:
        self._action = action
        self.received_masks: List[Any] = []

    def predict(self, obs, deterministic, action_masks):
        _ = (obs, deterministic)
        self.received_masks.append(action_masks)
        return np.int64(self._action), None


def test_self_play_opponent_hands_its_mask_to_the_observation() -> None:
    """Le chemin self-play passe REELLEMENT par le site optimise, et lui donne son masque.

    Ce test existe parce que le banc de mesure (scenario bot) ne traverse jamais ce chemin :
    corrige mais jamais appele, il ne corrigerait rien, et aucun compteur ne le dirait.
    """
    slot = mi.SHOOT_SLOT_BASE
    mask = _single_action_mask(slot)
    eligible = [{"id": "b1", "player": 2}]
    engine = _DummyEngine(decoder=_DummyActionDecoder(mask=mask, eligible=eligible))
    wrapper = BotControlledEnv(engine, bot=_DummyBot(), agent_seat_mode="p1")
    wrapper._frozen_model = cast(Any, _StubFrozenModel(action=slot))
    wrapper._self_play_deterministic = True

    assert wrapper._get_self_play_opponent_action() == slot
    assert engine.build_observation_calls == 1
    carried = engine.last_mask_and_eligible
    assert carried is not None, "l'observation a reconstruit le masque au lieu de le recevoir"
    # Le decodeur stub recopie ses arguments : on compare le contenu, pas l'identite.
    assert list(carried[0]) == mask and carried[1] == eligible


def test_carried_mask_is_reused_within_a_state_and_dropped_after_each_engine_step() -> None:
    """Le masque porté sert l'action du bot, et ne survit JAMAIS à un `env.step`.

    Les deux défauts que ce test verrouille, en sens inverse l'un de l'autre :
      - retirer le passage de valeur -> 5 constructions au lieu de 3, le gain disparaît ;
      - retirer la remise à None avant `env.step` -> le bot rejoue le masque de l'activation
        précédente sur un état qui a bougé. C'est le mode grave : il ne lève pas, le moteur
        exécute quelque chose de cohérent mais faux.
    """
    first_slot, second_slot = mi.SHOOT_SLOT_BASE, mi.SHOOT_SLOT_BASE + 1
    bot_unit = [{"id": "b1", "player": 2}]
    decoder = _SequenceDecoder(
        [
            (_single_action_mask(first_slot), bot_unit),
            (_single_action_mask(second_slot), bot_unit),
            (_single_action_mask(first_slot), [{"id": "c1", "player": 1}]),
        ]
    )
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["phase"] = "shoot"  # hors phase move : le bot reçoit les actions du masque
    bot = _DummyBot(action=first_slot)
    wrapper = BotControlledEnv(engine, bot=bot, agent_seat_mode="p1")
    wrapper._apply_episode_seat()

    _obs, terminated, _truncated, _info, _reward, decision = wrapper._run_bot_until_not_bot_turn(
        terminated=False,
        truncated=False,
        obs=None,
        info={},
        debug_mode=False,
        accumulate_reward=False,
        cumulative_reward=0.0,
    )

    assert not terminated
    # Le bot a vu le masque FRAIS à chaque activation, jamais deux fois le même.
    assert [actions for actions, _gs, _unit in bot.received] == [[first_slot], [second_slot]]
    # Une construction par activation (réutilisée pour choisir l'action) + celle qui fait sortir.
    assert decoder.calls == 3
    # Cette dernière est rendue à l'appelant, qui enchaîne sans la refaire (site « boucle bot
    # -> boucle appelante » : rien ne s'exécute entre les deux).
    assert decision is not None and decision.decision_owner == 1


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
            {"label": "A", "effect_ids": ("reroll_1_tohit_fight",), "declines": False, "payload": {}},
            {"label": "B", "effect_ids": ("reroll_1_save_fight",), "declines": False, "payload": {}},
        ],
    }


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
    decision = wrapper._get_decision_owner_from_mask()
    assert decision.decision_owner == 2
    assert decision.has_valid_actions is True
    assert decision.eligible_count == 0
    # Le masque qui a servi a repondre est rendu avec la reponse : c'est ce qui permet a
    # l'appelant adjacent de ne pas le reconstruire (cf. `MaskDecision`).
    assert list(np.asarray(decision.action_mask, dtype=bool)) == _decision_mask()
    assert decision.eligible_units == []


def test_bot_plays_its_own_decision_instead_of_waiting() -> None:
    """La décision du camp BOT est jouée par le bot — plus par l'action de l'agent (§9.4 point 0).

    Sans ce branchement, `_get_bot_action` retomberait sur `ACTION_WAIT`, action que le masque
    d'une décision n'autorise pas.
    """
    decoder = _DummyActionDecoder(mask=_decision_mask(), eligible=[], normalized_action=None)
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
    validation. Le cas AVEC `frozen_model` est couvert par le test suivant — il ne l'était pas, et
    cette docstring affirmait qu'il fonctionnait « déjà ».
    """
    decoder = _DummyActionDecoder(mask=_decision_mask(), eligible=[], normalized_action=None)
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["pending_agent_decision"] = _decision_state(player=2)
    wrapper = SelfPlayWrapper(engine, allow_random_opponent=True)
    for _ in range(20):
        assert wrapper._get_frozen_model_action() in (mi.CHOICE_BASE, mi.CHOICE_BASE + 1)


def test_frozen_model_is_asked_to_answer_a_pending_decision() -> None:
    """L'autre moitié du cas ci-dessus : AVEC `frozen_model`, le modèle doit être interrogé.

    Le pool éligible est vide par construction pendant une décision, et cette branche sortait sur
    `ACTION_WAIT` avant même d'atteindre `predict` — action hors masque. Le moteur ne revalide pas
    contre le masque : `convert_squad_action` lève en move/shoot/charge/fight, et rend
    silencieusement `command_wait` en phase command, décision perdue sans trace.
    """
    decoder = _DummyActionDecoder(mask=_decision_mask(), eligible=[], normalized_action=None)
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["pending_agent_decision"] = _decision_state(player=2)
    model = _StubFrozenModel(action=mi.CHOICE_BASE)
    wrapper = SelfPlayWrapper(engine, frozen_model=cast(Any, model))

    action = wrapper._get_frozen_model_action()

    assert model.received_masks, "le modèle n'a pas été interrogé : un WAIT hors masque a été rendu"
    assert action == mi.CHOICE_BASE


def test_bot_env_self_play_opponent_answers_a_pending_decision() -> None:
    """Jumeau du précédent dans `BotControlledEnv` — même défaut, même correction."""
    decoder = _DummyActionDecoder(mask=_decision_mask(), eligible=[], normalized_action=None)
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["pending_agent_decision"] = _decision_state(player=2)
    model = _StubFrozenModel(action=mi.CHOICE_BASE + 1)
    wrapper = BotControlledEnv(engine, bot=_DummyBot(), agent_seat_mode="p1")
    wrapper._frozen_model = cast(Any, model)
    wrapper._self_play_deterministic = True

    action = wrapper._get_self_play_opponent_action()

    assert model.received_masks, "le modèle n'a pas été interrogé : un WAIT hors masque a été rendu"
    assert action == mi.CHOICE_BASE + 1


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
    """`ENGINE_CONTRACT_ATTRS` doit couvrir EXACTEMENT les `self.engine.<x>` du module.

    Sinon la vérification cesse de prouver ce qu'elle affirme : un membre utilisé mais non
    listé retomberait sur un AttributeError tardif, exactement ce que le cast faisait.

    Égalité et non inclusion : le commentaire du tuple promet « rien de plus, rien de moins »,
    et seule l'égalité prouve la première moitié. Un membre retiré du code mais laissé dans le
    tuple resterait exigé de tout moteur ET de tout double, sans que rien ne le signale.
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
    declared = set(ENGINE_CONTRACT_ATTRS)
    assert used == declared, (
        f"membres utilisés mais non vérifiés par unwrap_engine : {sorted(used - declared)} ; "
        f"membres exigés mais plus utilisés : {sorted(declared - used)}"
    )


@pytest.mark.parametrize("attr", ENGINE_CONTRACT_ATTRS)
def test_dummy_engine_honours_every_contract_member(attr: str) -> None:
    """Verrou SYMÉTRIQUE du précédent : le double expose tout ce que le contrat exige.

    Il existait déjà, mais comme effet de bord de `test_unwrap_engine_peels_every_wrapper_layer`,
    dont le nom promet autre chose. Un membre ajouté au contrat et oublié sur `_DummyEngine`
    faisait donc virer au rouge les ~10 tests qui construisent un wrapper, en enfouissant la
    cause dans leur message. Paramétré, l'échec nomme le membre manquant, et une réécriture du
    test de déballage ne peut plus emporter la garantie sans que rien ne le dise.
    """
    assert hasattr(_DummyEngine(), attr), (
        f"`_DummyEngine` n'expose pas '{attr}' : tout ajout à ENGINE_CONTRACT_ATTRS doit être "
        f"reflété sur le double, sinon `unwrap_engine` refuse de construire les wrappers en test"
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
    assert isinstance(obs, np.ndarray) and cast(np.ndarray, obs).shape == (4,)


def test_step_defers_intermediate_observations_and_builds_exactly_one() -> None:
    """Le report est REELLEMENT arme pendant le step, et une seule observation est construite.

    Sans cette assertion le report pourrait etre inactif (drapeau jamais pose) sans qu'aucun
    test ne bronche : le comportement resterait correct et le gain nul.
    """
    wrapper, engine = _deferral_wrapper()
    engine.build_observation_calls = 0
    seen_flag: List[bool] = []
    # On sonde `step_with_mask` et non `step` : le wrapper appelle l'implementation directement
    # pour transmettre le masque (`_engine_step`), `step` n'etant plus que l'adaptateur gym.
    # Sonder `step` laissait ce test vert sans rien observer.
    inner_step = engine.step_with_mask

    def _spy(action, mask_and_eligible=None):
        seen_flag.append(engine.defer_observation)
        return inner_step(action, mask_and_eligible)

    engine.step_with_mask = _spy  # type: ignore[method-assign]
    wrapper.step(mi.ACTION_WAIT)
    assert seen_flag and all(seen_flag), "defer_observation n'etait pas arme pendant les steps moteur"
    assert engine.build_observation_calls == 1


def test_step_clears_deferral_even_when_the_engine_raises() -> None:
    """Le drapeau ne doit pas survivre a une exception : sinon tout step ulterieur rendrait None."""
    wrapper, engine = _deferral_wrapper()

    def _boom(action, mask_and_eligible=None):
        _ = (action, mask_and_eligible)
        raise RuntimeError("boom moteur")

    engine.step_with_mask = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="boom moteur"):
        wrapper.step(mi.ACTION_WAIT)
    assert engine.defer_observation is False


# ─────────────────────────────────────────────────────────────────────────────
# Désignation d'Oath of Moment (chantier 03) — JUMEAU des décisions ci-dessus
#
# Le moteur s'arrête dessus comme sur un `pending_agent_decision`, mais par un AUTRE mécanisme
# (dimension d'action + pointeur, `OATH_SLOTS`). Les quatre replis « pool vide -> ACTION_WAIT »
# de `env_wrappers` ne testaient que le premier mécanisme : le second les faisait tous rendre
# une action HORS MASQUE, et le décodeur levait. Mesuré le 2026-08-05 sur un vrai run :
# « convert_squad_action: aucune unité eligible en phase 'move' pour action 1024 ».
#
# La désignation n'est PAS optionnelle (« select one unit from your opponent's army ») : le
# masque n'ouvre donc aucun WAIT, ce qui rend le repli fatal au lieu de simplement inutile.
# ─────────────────────────────────────────────────────────────────────────────


def _oath_mask() -> list:
    """Masque d'une désignation d'Oath : DEUX slots ouverts, et RIEN d'autre.

    `ACTION_WAIT` reste fermé — c'est l'invariant qui rend les replis fatals, et l'écrire ici
    fait échouer le test si le masque de production s'assouplissait un jour.
    """
    mask = [False] * mi.TOTAL_ACTION_SIZE
    mask[mi.OATH_SLOT_BASE] = True
    mask[mi.OATH_SLOT_BASE + 3] = True
    return mask


def test_le_predicat_de_pause_couvre_les_quatre_mecanismes_de_choix() -> None:
    """`engine_is_paused_on_player_choice` : les quatre mécanismes de `_PLAYER_CHOICE_MECHANISMS`.

    Un seul point de lecture pour les quatre replis. Le vérifier ici évite qu'un nouveau
    mécanisme n'ait à être ajouté quatre fois — c'est exactement ainsi que l'Oath a été oublié.
    Ce test est le garde-fou contre un typo dans la clé d'un `_read_pending_*`.
    """
    from ai.env_wrappers import engine_is_paused_on_player_choice

    base: dict = {
        "pending_agent_decision": None,
        "pending_oath_selection": None,
        "pending_coherency_removal": None,
        "pending_fight_weapon_select": None,
    }
    assert engine_is_paused_on_player_choice(base) is False

    assert engine_is_paused_on_player_choice(
        {**base, "pending_agent_decision": _decision_state(player=1)}
    ) is True
    assert engine_is_paused_on_player_choice(
        {**base, "pending_oath_selection": 2}
    ) is True
    assert engine_is_paused_on_player_choice(
        {**base, "pending_coherency_removal": {"unit_id": "u1", "candidates": []}}
    ) is True
    assert engine_is_paused_on_player_choice(
        {**base, "pending_fight_weapon_select": {"unit_id": "u2", "weapons": []}}
    ) is True


def test_bot_joue_un_slot_d_oath_au_lieu_d_un_wait_hors_masque() -> None:
    """`BotControlledEnv._get_bot_action` doit DÉSIGNER, pas retomber sur `ACTION_WAIT`.

    Le pool éligible est vide pendant la désignation : sans la branche Oath, le repli
    « pool vide -> WAIT » rend 1024, que le masque n'ouvre pas.
    """
    decoder = _DummyActionDecoder(mask=_oath_mask(), eligible=[], normalized_action=None)
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["pending_agent_decision"] = None
    engine.game_state["pending_oath_selection"] = 2
    wrapper = BotControlledEnv(engine, bot=_DummyBot(), agent_seat_mode="p1")

    action = wrapper._get_bot_action()

    assert action != mi.ACTION_WAIT, "un WAIT hors masque a été rendu : le décodeur lèverait"
    assert action in (mi.OATH_SLOT_BASE, mi.OATH_SLOT_BASE + 3)


def test_self_play_sans_modele_joue_un_slot_d_oath() -> None:
    """Jumeau dans `SelfPlayWrapper` sans `frozen_model` — même défaut, même correction."""
    decoder = _DummyActionDecoder(mask=_oath_mask(), eligible=[], normalized_action=None)
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["pending_agent_decision"] = None
    engine.game_state["pending_oath_selection"] = 2
    wrapper = SelfPlayWrapper(engine, frozen_model=None, allow_random_opponent=True)

    action = wrapper._get_frozen_model_action()

    assert action != mi.ACTION_WAIT
    assert action in (mi.OATH_SLOT_BASE, mi.OATH_SLOT_BASE + 3)


def test_self_play_avec_modele_est_interroge_pendant_une_designation_d_oath() -> None:
    """Avec `frozen_model`, le modèle doit être INTERROGÉ : le repli sortait avant `predict`."""
    decoder = _DummyActionDecoder(mask=_oath_mask(), eligible=[], normalized_action=None)
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["pending_agent_decision"] = None
    engine.game_state["pending_oath_selection"] = 2
    model = _StubFrozenModel(action=mi.OATH_SLOT_BASE + 3)
    wrapper = SelfPlayWrapper(engine, frozen_model=cast(Any, model))

    action = wrapper._get_frozen_model_action()

    assert model.received_masks, "le modèle n'a pas été interrogé : un WAIT hors masque a été rendu"
    assert action == mi.OATH_SLOT_BASE + 3


def test_bot_env_self_play_opponent_est_interroge_pendant_une_designation_d_oath() -> None:
    """Quatrieme site : `BotControlledEnv._get_self_play_opponent_action`."""
    decoder = _DummyActionDecoder(mask=_oath_mask(), eligible=[], normalized_action=None)
    engine = _DummyEngine(decoder=decoder)
    engine.game_state["pending_agent_decision"] = None
    engine.game_state["pending_oath_selection"] = 2
    model = _StubFrozenModel(action=mi.OATH_SLOT_BASE)
    wrapper = BotControlledEnv(engine, bot=_DummyBot(), agent_seat_mode="p1")
    wrapper._frozen_model = cast(Any, model)
    wrapper._self_play_deterministic = True

    action = wrapper._get_self_play_opponent_action()

    assert model.received_masks, "le modèle n'a pas été interrogé : un WAIT hors masque a été rendu"
    assert action == mi.OATH_SLOT_BASE


def test_reload_snapshot_wraps_model_in_normalized_frozen_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """_reload_self_play_snapshot_if_needed doit produire un _NormalizedFrozenModel, pas un MaskablePPO nu.

    Sans ce wrapper, P1 self-play recoit des observations brutes alors que le modele
    a ete entraine avec VecNormalize — le signal self-play est fausse.
    """
    from ai.vec_normalize_utils import _NormalizedFrozenModel

    snapshot = tmp_path / "model_stub.zip"
    snapshot.write_bytes(b"stub")

    class _FakeRawModel:
        pass

    dummy_normalizer = lambda obs: obs  # noqa: E731

    monkeypatch.setattr("sb3_contrib.MaskablePPO.load", lambda path, device: _FakeRawModel())
    monkeypatch.setattr(
        "ai.vec_normalize_utils.build_snapshot_normalizer",
        lambda path, vn_enabled, eval_enabled: dummy_normalizer,
    )

    wrapper = _frozen_pool_wrapper(
        self_play_snapshot_path=str(snapshot),
        self_play_snapshot_frozen=True,
        self_play_vec_normalize_enabled=True,
        self_play_vec_normalize_eval_enabled=True,
    )
    wrapper._reload_self_play_snapshot_if_needed(force=True)

    assert isinstance(wrapper._frozen_model, _NormalizedFrozenModel), (
        "Le modele charge doit etre un _NormalizedFrozenModel, pas un MaskablePPO nu"
    )
    assert wrapper._frozen_model._normalizer is dummy_normalizer
