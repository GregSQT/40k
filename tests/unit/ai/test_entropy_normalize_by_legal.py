"""Entropie normalisée par l'état : `model_params.entropy_normalize_by_legal` (ai/patched_ppo.py).

Le terme d'entropie de la loss PPO devient `-mean_i(H_i / ln n_i)` sur les échantillons à
n_i > 1 actions légales ; `train/entropy_loss` reste la moyenne BRUTE et un nouveau tag
`train/entropy_loss_normalized` est publié sur tous les runs, clé active ou non.

PREUVE PAR MUTATION (purger `__pycache__` si la mutation est de même longueur) :
  - dans `entropy_loss_normalized_by_legal`, remplacer `entropy / log_n` par `entropy`
    → ROUGE `test_normalized_term_is_mean_of_h_over_ln_n`, `test_train_*`.
  - remplacer `valid = n_legal > 1` par `n_legal > 0` → ROUGE `test_single_legal_action_is_excluded`.
  - dans `train()`, remplacer `entropy_term = (... if self.entropy_normalize_by_legal else entropy_loss)`
    par `entropy_term = entropy_loss_normalized` → ROUGE `test_train_without_key_optimizes_raw_entropy`.
  - retirer `"entropy_normalize_by_legal"` de `_PLAIN_CURRICULUM_KEYS` → ROUGE `test_curriculum_applies_the_key`.
  - retirer l'appel `check_entropy_normalize_by_legal` de `_apply_curriculum_model_params`
    → ROUGE `test_curriculum_refuses_a_non_bool_key_like_the_constructor`.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import gymnasium
import numpy as np
import pytest
import torch as th
from gymnasium import spaces

from ai import train
from ai.patched_ppo import PatchedMaskablePPO, entropy_loss_normalized_by_legal

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Terme pur
# ---------------------------------------------------------------------------

def _masks(counts: list[int], width: int, dtype: Any = th.float32) -> th.Tensor:
    masks = th.zeros((len(counts), width), dtype=dtype)
    for row, n in enumerate(counts):
        masks[row, :n] = 1
    return masks


def test_normalized_term_is_mean_of_h_over_ln_n() -> None:
    """Deux états, n=2 et n=200 : `mean(H/ln n)`, PAS la moyenne simple des entropies."""
    entropy = th.tensor([0.5, 4.0])
    masks = _masks([2, 200], 200)

    got = entropy_loss_normalized_by_legal(entropy, masks)

    expected = -(0.5 / math.log(2) + 4.0 / math.log(200)) / 2
    assert got.item() == pytest.approx(expected, rel=1e-6)
    assert got.item() != pytest.approx(-(0.5 + 4.0) / 2), "moyenne simple : pas normalisée"
    assert -1.0 <= got.item() <= 0.0


def test_bounded_in_minus_one_zero_at_maximal_entropy() -> None:
    """H_i = ln n_i sur chaque état → exactement -1 ; H_i = 0 → exactement 0."""
    counts = [2, 7, 194]
    masks = _masks(counts, 200)
    at_max = th.tensor([math.log(n) for n in counts])
    assert entropy_loss_normalized_by_legal(at_max, masks).item() == pytest.approx(-1.0)
    assert entropy_loss_normalized_by_legal(th.zeros(3), masks).item() == pytest.approx(0.0)


def test_single_legal_action_is_excluded() -> None:
    """n=1 : aucune décision (ln 1 = 0). Exclu de la moyenne, pas divisé par zéro."""
    entropy = th.tensor([0.0, 0.3])
    masks = _masks([1, 2], 5)

    got = entropy_loss_normalized_by_legal(entropy, masks)

    assert got.item() == pytest.approx(-0.3 / math.log(2)), "la moyenne porte sur le seul n=2"
    assert th.isfinite(got)


def test_no_state_with_choice_gives_zero_connected_to_the_graph() -> None:
    """Aucun n_i > 1 → 0, avec gradient (nul) : le backward de diagnostic par terme doit passer."""
    entropy = th.tensor([0.0, 0.0], requires_grad=True)
    masks = _masks([1, 1], 3)

    got = entropy_loss_normalized_by_legal(entropy, masks)

    assert got.item() == 0.0
    assert got.requires_grad, "terme détaché du graphe : `backward(retain_graph=True)` lèverait"
    got.backward()
    assert entropy.grad is not None and th.isfinite(entropy.grad).all()
    assert entropy.grad.abs().sum().item() == 0.0


def test_gradient_is_finite_next_to_an_excluded_state() -> None:
    """Le `where` ne doit pas laisser passer un `nan` de gradient depuis la ligne n=1."""
    entropy = th.tensor([0.0, 0.4], requires_grad=True)
    masks = _masks([1, 2], 3)

    entropy_loss_normalized_by_legal(entropy, masks).backward()

    assert entropy.grad is not None
    assert th.isfinite(entropy.grad).all(), entropy.grad
    assert entropy.grad[0].item() == 0.0
    assert entropy.grad[1].item() == pytest.approx(-1.0 / math.log(2))


def test_bool_masks_are_accepted() -> None:
    """Le buffer SB3 porte des masques float 0/1, le buffer GPU des bool : même résultat."""
    entropy = th.tensor([0.5, 4.0])
    as_float = entropy_loss_normalized_by_legal(entropy, _masks([2, 200], 200))
    as_bool = entropy_loss_normalized_by_legal(entropy, _masks([2, 200], 200, dtype=th.bool))
    assert as_float.item() == pytest.approx(as_bool.item())


# ---------------------------------------------------------------------------
# Chemin de production : PatchedMaskablePPO.train()
# ---------------------------------------------------------------------------

class _AlternatingMaskEnv(gymnasium.Env):
    """Discrete(4) ; pas pairs → 4 actions légales, pas impairs → 2. Récompense variable."""

    def __init__(self) -> None:
        super().__init__()
        self.observation_space = spaces.Box(-1.0, 1.0, shape=(3,), dtype=np.float32)
        self.action_space = spaces.Discrete(4)
        self._t = 0

    def reset(self, *, seed: Any = None, options: Any = None):
        self._t = 0
        return np.zeros(3, dtype=np.float32), {}

    def step(self, action):
        self._t += 1
        obs = np.full(3, self._t / 10.0, dtype=np.float32)
        return obs, float(action) * self._t, self._t >= 4, False, {}

    def action_masks(self) -> np.ndarray:
        mask = np.ones(4, dtype=bool)
        if self._t % 2:
            mask[2:] = False
        return mask


_ENT_COEF = 0.3


def _model(**extra: Any) -> PatchedMaskablePPO:
    model = PatchedMaskablePPO(
        "MlpPolicy",
        _AlternatingMaskEnv(),
        n_steps=8,
        batch_size=8,  # UN minibatch = tout le rollout : le diag mb0 porte sur ces 8 échantillons
        n_epochs=1,
        ent_coef=_ENT_COEF,
        seed=0,
        device="cpu",
        policy_kwargs={"net_arch": [8]},
        **extra,
    )
    # Logits étalés : à l'initialisation SB3 (gain 0.01) la politique est quasi uniforme et le
    # gradient de l'entropie y est ~0, ce qui rendrait les comparaisons de normes vides.
    action_net: Any = model.policy.action_net
    with th.no_grad():
        action_net.weight.mul_(100.0)
    return model


def _train_once(model: PatchedMaskablePPO) -> tuple[dict[str, float], dict[str, Any], Any]:
    """Un update ; retourne (tags du logger, minibatch vu par evaluate_actions, policy PRÉ-update)."""
    frozen_policy = copy.deepcopy(model.policy)
    seen: dict[str, Any] = {}
    policy: Any = model.policy
    original_evaluate = policy.evaluate_actions

    def _capture(obs, actions, action_masks=None):
        seen["obs"], seen["actions"], seen["masks"] = obs, actions, action_masks
        return original_evaluate(obs, actions, action_masks=action_masks)

    policy.evaluate_actions = _capture

    recorded: dict[str, float] = {}
    original_train = model.train

    def _train_and_capture() -> None:
        original_train()
        recorded.update(model.logger.name_to_value)

    model.train = _train_and_capture  # type: ignore[method-assign]
    model.learn(total_timesteps=8)
    assert seen, "evaluate_actions jamais appelé : aucun minibatch"
    assert recorded["train/n_minibatches_done"] == 1
    return recorded, seen, frozen_policy


def _entropy_term_grad_norm(policy: Any, seen: dict[str, Any], normalized: bool) -> float:
    """‖∇ ent_coef·terme‖ recalculée indépendamment sur la policy pré-update."""
    policy.optimizer.zero_grad()
    _values, _log_prob, entropy = policy.evaluate_actions(
        seen["obs"], seen["actions"], action_masks=seen["masks"]
    )
    if normalized:
        term = entropy_loss_normalized_by_legal(entropy, th.as_tensor(seen["masks"]))
    else:
        term = -th.mean(entropy)
    (_ENT_COEF * term).backward()
    return float(th.nn.utils.clip_grad_norm_(policy.parameters(), float("inf")))


def _expected_tags(policy: Any, seen: dict[str, Any]) -> tuple[float, float]:
    with th.no_grad():
        _v, _lp, entropy = policy.evaluate_actions(
            seen["obs"], seen["actions"], action_masks=seen["masks"]
        )
        raw = -th.mean(entropy).item()
        normalized = entropy_loss_normalized_by_legal(entropy, th.as_tensor(seen["masks"])).item()
    n_legal = th.as_tensor(seen["masks"]).sum(dim=1)
    assert set(n_legal.tolist()) == {2.0, 4.0}, "le minibatch doit mélanger deux largeurs"
    assert raw != pytest.approx(normalized), "cas dégénéré : les deux termes coïncident"
    return raw, normalized


def test_train_without_key_optimizes_raw_entropy_and_publishes_both_tags() -> None:
    """Clé absente : le terme de la loss est `-mean(H)` — comportement antérieur — et
    `train/entropy_loss_normalized` est tout de même publié."""
    recorded, seen, frozen = _train_once(_model())
    raw, normalized = _expected_tags(frozen, seen)

    assert recorded["train/entropy_loss"] == pytest.approx(raw, rel=1e-5)
    assert recorded["train/entropy_loss_normalized"] == pytest.approx(normalized, rel=1e-5)
    # Le gradient du terme d'entropie de la LOSS est celui de l'entropie brute.
    assert recorded["diag/grad_norm_entropy_mb0"] == pytest.approx(
        _entropy_term_grad_norm(copy.deepcopy(frozen), seen, normalized=False), rel=1e-4
    )
    assert recorded["diag/grad_norm_entropy_mb0"] != pytest.approx(
        _entropy_term_grad_norm(copy.deepcopy(frozen), seen, normalized=True), rel=1e-2
    ), "clé absente mais terme normalisé optimisé"


def test_train_with_key_optimizes_normalized_entropy_and_keeps_raw_tag() -> None:
    """Clé active : le terme optimisé est `-mean(H/ln n)` ; `train/entropy_loss` reste brut."""
    model = _model(entropy_normalize_by_legal=True)
    assert model.entropy_normalize_by_legal is True
    recorded, seen, frozen = _train_once(model)
    raw, normalized = _expected_tags(frozen, seen)

    assert recorded["train/entropy_loss"] == pytest.approx(raw, rel=1e-5), "tag brut altéré"
    assert recorded["train/entropy_loss_normalized"] == pytest.approx(normalized, rel=1e-5)
    assert recorded["diag/grad_norm_entropy_mb0"] == pytest.approx(
        _entropy_term_grad_norm(copy.deepcopy(frozen), seen, normalized=True), rel=1e-4
    )
    assert recorded["diag/grad_norm_entropy_mb0"] != pytest.approx(
        _entropy_term_grad_norm(copy.deepcopy(frozen), seen, normalized=False), rel=1e-2
    ), "clé active mais terme brut optimisé"


def test_key_active_and_entropy_none_raises() -> None:
    """Sans entropie analytique, ne jamais retomber sur `-log_prob` : lever."""
    model = _model(entropy_normalize_by_legal=True)
    policy: Any = model.policy
    original = policy.evaluate_actions

    def _without_entropy(obs, actions, action_masks=None):
        values, log_prob, _entropy = original(obs, actions, action_masks=action_masks)
        return values, log_prob, None

    policy.evaluate_actions = _without_entropy
    with pytest.raises(RuntimeError, match="entropie analytique"):
        model.learn(total_timesteps=8)


def test_key_defaults_to_false_and_rejects_non_bool() -> None:
    assert _model().entropy_normalize_by_legal is False
    with pytest.raises(TypeError, match="entropy_normalize_by_legal"):
        _model(entropy_normalize_by_legal="yes")  # type: ignore[arg-type]


def test_key_survives_save_and_load(tmp_path: Path) -> None:
    """Chemin `--append` : le flag est dans le zip ET `_apply_curriculum_model_params` le repose."""
    path = tmp_path / "m.zip"
    _model(entropy_normalize_by_legal=True).save(path)
    loaded = PatchedMaskablePPO.load(path, env=_AlternatingMaskEnv(), device="cpu")
    assert loaded.entropy_normalize_by_legal is True

    _model().save(path)
    assert PatchedMaskablePPO.load(path, env=_AlternatingMaskEnv(), device="cpu").entropy_normalize_by_legal is False


def test_curriculum_applies_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un profil `--append` portant la clé doit la poser sur le modèle chargé."""
    monkeypatch.setattr(train, "recreate_rollout_buffer", lambda model, **kw: None)
    model = SimpleNamespace()
    train._apply_curriculum_model_params(
        model,
        {"learning_rate": 0.002, "ent_coef": 0.03, "clip_range": 0.2,
         "entropy_normalize_by_legal": True},
        log=lambda _m: None,
    )
    assert model.entropy_normalize_by_legal is True
    assert "entropy_normalize_by_legal" in train._PLAIN_CURRICULUM_KEYS


def test_curriculum_refuses_a_non_bool_key_like_the_constructor(monkeypatch: pytest.MonkeyPatch) -> None:
    """`"false"` ou `1` : refusés en `--append` comme en `--new`, jamais posés par `setattr`."""
    monkeypatch.setattr(train, "recreate_rollout_buffer", lambda model, **kw: None)
    for bad in ("false", 1):
        with pytest.raises(TypeError, match="entropy_normalize_by_legal"):
            train._apply_curriculum_model_params(
                SimpleNamespace(),
                {"learning_rate": 0.002, "ent_coef": 0.03, "clip_range": 0.2,
                 "entropy_normalize_by_legal": bad},
                log=lambda _m: None,
            )


# ---------------------------------------------------------------------------
# Config de l'expérience : config/agents/ArmageddonAgent_x1_entnorm/
# ---------------------------------------------------------------------------

def test_entnorm_x1_long_is_x1_long_of_the_base_agent() -> None:
    """La copie n'a pas dérivé : son `x1_long` est identique au `x1_long` de ArmageddonAgent_x1."""
    from config_loader import get_config_loader

    loader = get_config_loader()
    base = loader.load_agent_training_config("ArmageddonAgent_x1", "x1_long")
    assert loader.load_agent_training_config("ArmageddonAgent_x1_entnorm", "x1_long") == base


def test_entnorm_control_profile_is_x1_long_shortened_to_40k() -> None:
    """Bras de CONTRÔLE `x1_40k` = `x1_long` + 40 000 épisodes + évals intermédiaires à 30, rien d'autre.

    40 000 : la stagnation de P1 se lit en 30 à 40 000 épisodes (décision du 2026-09-12) ; les
    rampes sont en fraction du run, donc inchangées. Le chiffre publié (`bot_eval_final` 300)
    reste celui de `x1_long`.
    """
    from config_loader import get_config_loader

    loader = get_config_loader()
    long_ = loader.load_agent_training_config("ArmageddonAgent_x1_entnorm", "x1_long")
    control = loader.load_agent_training_config("ArmageddonAgent_x1_entnorm", "x1_40k")

    top_diff = {k for k in set(long_) | set(control) if long_.get(k) != control.get(k)}
    assert top_diff == {"type", "_doc", "total_episodes", "callback_params"}, top_diff
    assert control["total_episodes"] == 40_000
    cb_l, cb_c = long_["callback_params"], control["callback_params"]
    assert {k for k in set(cb_l) | set(cb_c) if cb_l.get(k) != cb_c.get(k)} == {"bot_eval_intermediate"}
    assert cb_c["bot_eval_intermediate"] == 30
    assert cb_c["bot_eval_final"] == 300 and cb_c["bot_eval_freq"] == 10_000
    assert control["model_params"] == long_["model_params"]


def test_entnorm_treated_profile_is_control_plus_two_overrides() -> None:
    """`x1_40k_entnorm` = `x1_40k` + entropy_normalize_by_legal + ent_coef ×5, rien d'autre."""
    from config_loader import get_config_loader

    loader = get_config_loader()
    control = loader.load_agent_training_config("ArmageddonAgent_x1_entnorm", "x1_40k")
    treated = loader.load_agent_training_config("ArmageddonAgent_x1_entnorm", "x1_40k_entnorm")

    top_diff = {k for k in set(control) | set(treated) if control.get(k) != treated.get(k)}
    assert top_diff == {"type", "_doc", "model_params"}, top_diff

    mp_c, mp_t = control["model_params"], treated["model_params"]
    mp_diff = {k for k in set(mp_c) | set(mp_t) if mp_c.get(k) != mp_t.get(k)}
    assert mp_diff == {"entropy_normalize_by_legal", "ent_coef"}, mp_diff
    assert mp_t["entropy_normalize_by_legal"] is True
    assert mp_t["ent_coef"] == {"start": 0.5, "end": 0.05, "decay_fraction": 0.4}
    assert mp_c["ent_coef"] == {"start": 0.1, "end": 0.01, "decay_fraction": 0.4}
    assert "2026-09-13" in treated["_doc"]


def _sans_notes(bloc: Any) -> Any:
    """Le bloc privé de ses clés-commentaires, à toute profondeur.

    Une clé-commentaire d'un JSON de config, c'est un suffixe `_normal` ET une valeur TEXTE
    (même critère que `_comparable` de `test_schedule_decay_fraction.py`) : la note qui documente
    le réglage voisin — et l'HISTORIQUE de ses runs (« DESACTIVE après le run S11 »), propre à
    chaque agent. Le miroir porte sur les VALEURS de récompense : deux agents peuvent annoter
    différemment le même réglage sans que la comparaison rougisse.
    """
    if not isinstance(bloc, dict):
        return bloc
    return {
        k: _sans_notes(v) for k, v in bloc.items()
        if not (k.endswith("_normal") and isinstance(v, str))
    }


def test_entnorm_rewards_config_is_keyed_on_the_new_agent() -> None:
    """`load_agent_rewards_config` indexe la table par la clé d'agent : elle doit être renommée,
    et ses VALEURS sont le miroir de `ArmageddonAgent_x1` (le traitement est dans la config
    d'entraînement, jamais dans les récompenses)."""
    from config_loader import get_config_loader

    loader = get_config_loader()
    rewards = loader.load_agent_rewards_config("ArmageddonAgent_x1_entnorm")
    base = loader.load_agent_rewards_config("ArmageddonAgent_x1")
    treated = _sans_notes(rewards["ArmageddonAgent_x1_entnorm"])
    control = _sans_notes(base["ArmageddonAgent_x1"])
    assert treated == control
    assert "objective_rewards" in treated and "squad_shaping" in treated, (
        "VERT VACANT : le retrait des notes a vidé les sections comparées"
    )
    assert "ArmageddonAgent_x1" not in rewards
