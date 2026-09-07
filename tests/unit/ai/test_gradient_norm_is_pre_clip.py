"""`train/gradient_norm` publie la norme BRUTE, mesurée AVANT écrêtage.

Défaut d'origine : `ai/patched_ppo.py` jetait la valeur de retour de `clip_grad_norm_` et
`ai/training_callbacks.py` recalculait la norme sur des `p.grad` DÉJÀ écrêtés. La courbe
publiée valait donc `min(norme brute, max_grad_norm)` et ne pouvait pas dépasser le plafond :
56 updates sur 60 à exactement 0.5000 sur run_20260906-183917 (`max_grad_norm` 0.5).

PREUVE PAR MUTATION :
  Dans `ai/patched_ppo.py`, republier la norme post-écrêtage — remplacer l'accumulation
  ``grad_norms_t.append(th.nn.utils.clip_grad_norm_(...))`` par un appel dont le retour est
  jeté, suivi d'un recalcul sur ``p.grad`` — rend ROUGE
  ``test_train_publishes_norm_above_max_grad_norm``.
  Restaurer → VERT.
  Purger ``__pycache__`` si la mutation est de même longueur que l'original.
"""

from __future__ import annotations

from typing import Any

import gymnasium
import numpy as np
import pytest
import torch as th
from gymnasium import spaces
from torch import nn

from ai.patched_ppo import PatchedMaskablePPO, _grad_norm_stats

# Deux minibatches, un seul au-dessus du plafond : moyenne des normes brutes = 3.0,
# part écrêtée = 0.5. La moyenne des normes POST-écrêtage vaudrait (0.5 + 0.2) / 2 = 0.35.
_RAW_NORMS = (5.8, 0.2)
_MAX_GRAD_NORM = 0.5
_EXPECTED_MEAN = 3.0
_EXPECTED_CLIP_FRACTION = 0.5
_POST_CLIP_MEAN = 0.35


def _force_grad_norm(module: nn.Module, norm: float) -> None:
    """Pose sur `module` un gradient dont la norme L2 globale vaut exactement `norm`."""
    params = list(module.parameters())
    for p in params:
        p.grad = th.zeros_like(p)
    flat = params[0].grad
    assert flat is not None
    flat.view(-1)[0] = norm


def _global_grad_norm(module: nn.Module) -> float:
    grads = [p.grad.reshape(-1) for p in module.parameters() if p.grad is not None]
    return float(th.cat(grads).norm(2))


def test_clip_grad_norm_returns_the_norm_before_clipping() -> None:
    """Contrat torch : le retour de `clip_grad_norm_` est la norme AVANT écrêtage."""
    module = nn.Linear(4, 3)
    _force_grad_norm(module, _RAW_NORMS[0])

    returned = float(th.nn.utils.clip_grad_norm_(module.parameters(), _MAX_GRAD_NORM))

    assert returned == pytest.approx(_RAW_NORMS[0]), (
        "clip_grad_norm_ doit retourner la norme brute, pas la norme écrêtée"
    )
    assert _global_grad_norm(module) == pytest.approx(_MAX_GRAD_NORM, rel=1e-5), (
        "l'écrêtage doit avoir mordu — sans quoi le test ne distingue rien"
    )


def test_grad_norm_stats_averages_raw_norms_and_counts_clipped_minibatches() -> None:
    """Moyenne = normes brutes ; fraction = part des minibatches réellement écrêtés."""
    norms = [th.tensor(v) for v in _RAW_NORMS]

    mean, fraction = _grad_norm_stats(norms, _MAX_GRAD_NORM)

    assert mean == pytest.approx(_EXPECTED_MEAN), (
        f"moyenne des normes brutes attendue {_EXPECTED_MEAN}, "
        f"la moyenne post-écrêtage vaudrait {_POST_CLIP_MEAN}"
    )
    assert fraction == pytest.approx(_EXPECTED_CLIP_FRACTION)
    assert mean != pytest.approx(_POST_CLIP_MEAN), "valeur post-écrêtage republiée"


def test_grad_norm_stats_without_minibatch_is_nan() -> None:
    """Aucun minibatch écoulé (early-stopping target_kl au premier) → NaN, pas 0.0."""
    mean, fraction = _grad_norm_stats([], _MAX_GRAD_NORM)

    assert np.isnan(mean) and np.isnan(fraction), (
        "0.0 se lirait comme un gradient nul mesuré, pas comme une absence de mesure"
    )


class _TinyMaskedEnv(gymnasium.Env):
    """Env minimal supportant le masquage — récompenses variables (gradient non nul)."""

    def __init__(self) -> None:
        super().__init__()
        self.observation_space = spaces.Box(-1.0, 1.0, shape=(3,), dtype=np.float32)
        self.action_space = spaces.Discrete(2)
        self._t = 0

    def reset(self, *, seed: Any = None, options: Any = None):
        self._t = 0
        return np.zeros(3, dtype=np.float32), {}

    def step(self, action):
        self._t += 1
        obs = np.full(3, self._t / 10.0, dtype=np.float32)
        reward = float(action) * self._t
        return obs, reward, self._t >= 4, False, {}

    def action_masks(self) -> np.ndarray:
        return np.ones(2, dtype=bool)


def _train_once(max_grad_norm: float) -> dict[str, float]:
    """Un update PPO complet ; retourne les scalaires posés sur le logger."""
    model = PatchedMaskablePPO(
        "MlpPolicy",
        _TinyMaskedEnv(),
        n_steps=8,
        batch_size=4,
        n_epochs=1,
        max_grad_norm=max_grad_norm,
        seed=0,
        device="cpu",
        policy_kwargs={"net_arch": [8]},
    )
    # Capture juste après train(), avant que learn() ne vide le logger par son dump.
    # Le logger n'existe pas avant _setup_learn, d'où l'enveloppe sur train et non sur record.
    recorded: dict[str, float] = {}
    original_train = model.train

    def _train_and_capture() -> None:
        original_train()
        recorded.update(model.logger.name_to_value)

    model.train = _train_and_capture  # type: ignore[method-assign]
    model.learn(total_timesteps=8)
    return recorded


def test_train_publishes_norm_above_max_grad_norm() -> None:
    """Plafond écrasé : la norme publiée doit le dépasser de plusieurs ordres de grandeur.

    C'est le verrou du CHEMIN DE PRODUCTION — `PatchedMaskablePPO.train()` doit publier le
    retour de `clip_grad_norm_`. Republier la norme post-écrêtage bornerait la valeur au
    plafond, ici 1e-8.
    """
    plafond = 1e-8
    recorded = _train_once(plafond)

    assert "train/gradient_norm" in recorded, "train() ne publie plus train/gradient_norm"
    assert recorded["train/gradient_norm"] > 1e-4, (
        f"norme publiée {recorded['train/gradient_norm']} bornée par max_grad_norm={plafond} :"
        " c'est la norme APRÈS écrêtage qui est publiée"
    )
    assert recorded["train/grad_clip_fraction"] == pytest.approx(1.0), (
        "tous les minibatches dépassent un plafond de 1e-8"
    )


def test_train_reports_zero_clip_fraction_under_a_loose_ceiling() -> None:
    """Plafond hors d'atteinte : aucun minibatch écrêté, et la norme reste finie."""
    recorded = _train_once(1e9)

    assert recorded["train/grad_clip_fraction"] == pytest.approx(0.0)
    assert 0.0 < recorded["train/gradient_norm"] < 1e9
