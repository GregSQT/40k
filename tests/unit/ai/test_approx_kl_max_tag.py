"""`train/approx_kl_max` — tag KL maximum par update.

Quand `target_kl` est actif, `approx_kl_divs` accumule le KL de chaque mini-lot.
La valeur déclenchante du break est ajoutée à la liste AVANT le test (ligne 270 de
`ai/patched_ppo.py`), donc `max(approx_kl_divs) ≥ valeur déclenchante > 1.5 × target_kl`.
Sans break, tous les mini-lots sont sous le seuil par construction, donc le max aussi.

Deux sens nécessaires : un tag constamment élevé passerait le seul test de break.

PREUVE PAR MUTATION :
  Remplacer `np.max` par `np.min` → ROUGE `test_approx_kl_max_exceeds_threshold`.
  Supprimer le `logger.record` → ROUGE les deux tests de présence.
  Restaurer → VERT.
  Purger `__pycache__` si la mutation est de même longueur que l'original.
"""

from __future__ import annotations

from typing import Any

import gymnasium
import numpy as np
from gymnasium import spaces

from ai.patched_ppo import PatchedMaskablePPO


class _TinyMaskedEnv(gymnasium.Env):
    """Env minimal supportant le masquage — récompenses variables pour gradient non nul."""

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


def _train_once(target_kl: float | None) -> dict[str, float]:
    """Un update PPO complet ; retourne les scalaires posés sur le logger."""
    model = PatchedMaskablePPO(
        "MlpPolicy",
        _TinyMaskedEnv(),
        n_steps=8,
        batch_size=4,
        n_epochs=4,
        target_kl=target_kl,
        seed=0,
        device="cpu",
        policy_kwargs={"net_arch": [8]},
    )
    recorded: dict[str, float] = {}
    original_train = model.train

    def _train_and_capture() -> None:
        original_train()
        recorded.update(model.logger.name_to_value)

    model.train = _train_and_capture  # type: ignore[method-assign]
    model.learn(total_timesteps=8)
    return recorded


def test_approx_kl_max_absent_when_target_kl_is_none() -> None:
    """Sans `target_kl`, `approx_kl_divs` reste vide — le tag ne doit pas apparaître."""
    recorded = _train_once(target_kl=None)

    assert "train/approx_kl_max" not in recorded, (
        "train/approx_kl_max publié sans target_kl — le tag n'a de sens que "
        "quand l'early-stopping KL est actif"
    )


def test_approx_kl_max_exceeds_threshold_when_early_stopped() -> None:
    """`target_kl` infime : le max publié doit dépasser `1.5 × target_kl`.

    La valeur déclenchante est appendée à `approx_kl_divs` AVANT le break, donc
    `max(approx_kl_divs) ≥ valeur déclenchante > 1.5 × target_kl`.
    """
    target_kl = 1e-20  # tout KL float32 > 0 dépasse ce seuil — seed-indépendant
    recorded = _train_once(target_kl=target_kl)

    assert "train/approx_kl_max" in recorded, "train/approx_kl_max absent malgré target_kl actif"
    threshold = 1.5 * target_kl
    assert recorded["train/approx_kl_max"] > threshold, (
        f"approx_kl_max={recorded['train/approx_kl_max']:.2e} ≤ seuil {threshold:.2e} — "
        "le break n'a pas eu lieu ou le tag renvoie le min au lieu du max"
    )


def test_approx_kl_max_below_threshold_when_no_early_stop() -> None:
    """`target_kl` inatteignable : le max publié doit rester sous `1.5 × target_kl`.

    Sans break, tous les mini-lots sont sous le seuil par construction.
    Un tag constamment élevé passerait le test précédent mais échouerait ici.
    """
    target_kl = 100.0  # inatteignable — aucun mini-lot ne dépasse 150.0
    recorded = _train_once(target_kl=target_kl)

    assert "train/approx_kl_max" in recorded, "train/approx_kl_max absent malgré target_kl actif"
    threshold = 1.5 * target_kl
    assert recorded["train/approx_kl_max"] < threshold, (
        f"approx_kl_max={recorded['train/approx_kl_max']:.2e} ≥ seuil {threshold:.2e} — "
        "break déclenché avec target_kl=100.0 ? (tag renvoie une valeur incorrecte)"
    )
