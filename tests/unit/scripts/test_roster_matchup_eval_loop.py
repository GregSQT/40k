"""Verrouille le COMPORTEMENT de la boucle d'evaluation de scripts/roster_matchup_stats.py.

La boucle avait diverge de la reference vivante ai/bot_evaluation.py sur quatre points, dont
un la rendait totalement inutilisable : l'observation du pipeline squad est un
`gym.spaces.Dict` (engine/w40k_core.py:639) et la boucle l'aplatissait, ce qui levait avant
meme d'atteindre le masque d'actions.

`_run_single_episode` est exercee ici avec des DOUBLURES (env et modele factices) : aucun
moteur, aucun modele, aucune partie. Le faux modele enregistre ce qu'il recoit, ce qui permet
de verifier ce qui compte reellement — la forme de l'observation servie, la provenance du
masque, l'arret au plafond de pas et la lecture du vainqueur — et non la tournure du source.
"""
import importlib.util
import random
import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "roster_matchup_stats.py"

MASK_SIZE = 8


def _load_script_module():
    spec = importlib.util.spec_from_file_location("roster_matchup_stats_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script_module()


def _squad_obs() -> dict:
    """Forme d'observation du pipeline squad : un dict de tenseurs, pas un vecteur a plat."""
    return {
        "global_cont": np.zeros((4,), dtype=np.float32),
        "grid": np.zeros((2, 3, 3), dtype=np.float32),
    }


def _squad_mask() -> np.ndarray:
    mask = np.zeros(MASK_SIZE, dtype=bool)
    mask[3] = True  # une seule action ouverte : signature reconnaissable du bon masque
    return mask


def _legacy_mask() -> np.ndarray:
    mask = np.zeros(MASK_SIZE, dtype=bool)
    mask[6] = True  # signature de l'ANCIEN layout, celui qui ne doit plus jamais etre servi
    return mask


class FakeActionDecoder:
    """Voie LEGACY. Toute lecture est enregistree : elle ne doit jamais servir."""

    def __init__(self):
        self.calls = 0

    def get_action_mask_and_eligible_units(self, game_state):
        self.calls += 1
        return _legacy_mask(), []


class FakeEngine:
    def __init__(self):
        self.action_decoder = FakeActionDecoder()
        self.game_state = {}
        self.get_action_mask_calls = 0

    def get_action_mask(self):
        self.get_action_mask_calls += 1
        return _squad_mask()


class FakeEnv:
    """Env minimal : rend une obs Dict, termine apres `steps_before_done` pas (jamais si None)."""

    def __init__(self, steps_before_done, final_info, obs=None):
        self.engine = FakeEngine()
        self._steps_before_done = steps_before_done
        self._final_info = final_info
        self._obs = _squad_obs() if obs is None else obs
        self.step_calls = 0
        self.reset_seeds = []

    def reset(self, seed=None):
        self.reset_seeds.append(seed)
        self.step_calls = 0
        return self._obs, {}

    def step(self, action):
        self.step_calls += 1
        done = (
            self._steps_before_done is not None
            and self.step_calls >= self._steps_before_done
        )
        # Le moteur ecrit "controlled_player" dans l'info de CHAQUE step
        # (engine/w40k_core.py:1870) : la doublure fait pareil, sinon l'arret au plafond
        # (episode non termine) lirait une info que le moteur ne rend jamais.
        return self._obs, 0.0, done, False, self._final_info


class FakeModel:
    """Enregistre TOUT ce que `predict` recoit : c'est la sonde du test."""

    def __init__(self):
        self.received_obs = []
        self.received_masks = []

    def predict(self, obs, action_masks=None, deterministic=True):
        self.received_obs.append(obs)
        self.received_masks.append(np.asarray(action_masks))
        return np.array([3]), None


def _run(script, env, model, max_steps=10, ep_seed=123, obs_normalizer=None):
    return script._run_single_episode(
        env=env,
        model=model,
        obs_normalizer=obs_normalizer,
        max_steps_per_episode=max_steps,
        ep_seed=ep_seed,
    )


def test_dict_observation_reaches_predict_unflattened(script):
    """Defaut d'origine : `np.asarray(obs, float32)` sur une obs Dict. Le modele doit
    recevoir le dict LUI-MEME, cles et tenseurs intacts."""
    env = FakeEnv(steps_before_done=1, final_info={"winner": 1, "controlled_player": 1})
    model = FakeModel()
    _run(script, env, model)

    assert len(model.received_obs) == 1
    served = model.received_obs[0]
    assert isinstance(served, dict), f"obs servie au modele: {type(served)!r} au lieu d'un dict"
    assert set(served) == {"global_cont", "grid"}
    assert served["grid"].shape == (2, 3, 3), "le tenseur de grille a ete aplati"


def test_flat_observation_still_normalized_to_batch(script):
    """Chemin legacy Box a plat : conserve, avec conversion float32 + dimension de batch."""
    env = FakeEnv(
        steps_before_done=1,
        final_info={"winner": 1, "controlled_player": 1},
        obs=np.zeros((4,), dtype=np.float64),
    )
    model = FakeModel()
    _run(script, env, model)

    served = model.received_obs[0]
    assert isinstance(served, np.ndarray)
    assert served.dtype == np.float32
    assert served.shape == (1, 4)


def test_normalizer_output_is_what_reaches_predict(script):
    """Le modele voit la sortie du normalizer, pas l'obs brute (et un dict reste un dict)."""
    env = FakeEnv(steps_before_done=1, final_info={"winner": 1, "controlled_player": 1})
    model = FakeModel()
    marker = {
        "global_cont": np.ones((4,), dtype=np.float32),
        "grid": np.ones((2, 3, 3), dtype=np.float32),
    }
    _run(script, env, model, obs_normalizer=lambda obs: marker)

    served = model.received_obs[0]
    assert isinstance(served, dict)
    assert served["global_cont"].tolist() == [1.0, 1.0, 1.0, 1.0]


def test_mask_comes_from_engine_not_from_legacy_decoder(script):
    """Le masque servi est celui de `engine.get_action_mask()` (semantique SQUAD).
    La voie legacy `action_decoder.get_action_mask_and_eligible_units` ne doit pas etre lue."""
    env = FakeEnv(steps_before_done=1, final_info={"winner": 1, "controlled_player": 1})
    model = FakeModel()
    _run(script, env, model)

    served_mask = model.received_masks[0].reshape(-1)
    assert served_mask.tolist() == _squad_mask().tolist(), (
        "le masque servi n'est pas celui de engine.get_action_mask()"
    )
    assert env.engine.get_action_mask_calls == 1
    assert env.engine.action_decoder.calls == 0, "la voie legacy du decodeur d'actions a ete lue"


def test_episode_stops_at_step_cap(script):
    """Env qui ne termine jamais : la boucle doit s'arreter exactement au plafond."""
    env = FakeEnv(steps_before_done=None, final_info={"winner": 1, "controlled_player": 2})
    model = FakeModel()
    outcome = _run(script, env, model, max_steps=5)
    assert env.step_calls == 5, f"la boucle a fait {env.step_calls} pas au lieu de 5"
    assert len(model.received_obs) == 5
    assert outcome == "loss"


def test_winner_is_read_from_engine_info(script):
    """Le siege controle vient de `info["controlled_player"]`. Ici il vaut 2 : un identifiant
    recalcule depuis un `agent_seat_mode="p1"` aurait compte une defaite."""
    env = FakeEnv(steps_before_done=1, final_info={"winner": 2, "controlled_player": 2})
    assert _run(script, env, FakeModel()) == "win"

    env = FakeEnv(steps_before_done=1, final_info={"winner": 1, "controlled_player": 2})
    assert _run(script, env, FakeModel()) == "loss"

    env = FakeEnv(steps_before_done=1, final_info={"winner": -1, "controlled_player": 2})
    assert _run(script, env, FakeModel()) == "draw"


def test_missing_controlled_player_is_an_explicit_error(script):
    """Pas de repli : sans la cle, l'erreur est explicite plutot qu'un comptage faux."""
    env = FakeEnv(steps_before_done=1, final_info={"winner": 1})
    with pytest.raises(Exception):
        _run(script, env, FakeModel())


def test_both_random_generators_are_seeded(script):
    """random ET numpy sont graines par la graine d'episode (les doublures n'en consomment pas)."""
    env = FakeEnv(steps_before_done=1, final_info={"winner": 1, "controlled_player": 1})
    _run(script, env, FakeModel(), ep_seed=777)
    after_loop = (random.random(), float(np.random.random()))

    random.seed(777)
    np.random.seed(777)
    expected = (random.random(), float(np.random.random()))

    assert after_loop == expected, "au moins un des deux generateurs n'est pas graine"


def test_reset_receives_the_episode_seed(script):
    env = FakeEnv(steps_before_done=1, final_info={"winner": 1, "controlled_player": 1})
    _run(script, env, FakeModel(), ep_seed=4242)
    assert env.reset_seeds == [4242]


def test_obs_normalizer_delegates_to_reference(script, monkeypatch):
    """`_build_obs_normalizer` ne reimplemente pas le normalizer : il rend celui de la
    reference (ai/bot_evaluation._build_eval_obs_normalizer_for_worker), seul a traiter l'obs
    Dict. Une copie locale avait deja re-diverge en aplatissant les dicts."""
    import ai.bot_evaluation as bot_evaluation
    import config_loader

    sentinel = object()
    seen = {}

    def fake_builder(model, model_path, vec_enabled, vec_eval_enabled):
        seen["args"] = (model, model_path, vec_enabled, vec_eval_enabled)
        return sentinel

    monkeypatch.setattr(bot_evaluation, "_build_eval_obs_normalizer_for_worker", fake_builder)

    class FakeLoader:
        def load_agent_training_config(self, agent_key, training_config_name):
            return {"vec_normalize": {"enabled": True}, "vec_normalize_eval": {"enabled": True}}

    monkeypatch.setattr(config_loader, "get_config_loader", lambda: FakeLoader())

    result = script._build_obs_normalizer("AnyAgent", "default", "/tmp/model.zip")
    assert result is sentinel, "le normalizer n'est plus celui de la reference"
    assert seen["args"] == (None, "/tmp/model.zip", True, True)
