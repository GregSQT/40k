"""`train/approx_kl_max` et `train/n_minibatches_done` — tags de coupure KL par update.

Quand `target_kl` est actif, `approx_kl_divs` accumule le KL de chaque mini-lot.
La valeur déclenchante du break est ajoutée à la liste AVANT le test (ligne 270 de
`ai/patched_ppo.py`), donc `max(approx_kl_divs) ≥ valeur déclenchante > 1.5 × target_kl`.
Sans break, tous les mini-lots sont sous le seuil par construction, donc le max aussi.

Deux sens nécessaires : un tag constamment élevé passerait le seul test de break.

`n_minibatches_done` compte les `optimizer.step()` réellement exécutés : `approx_kl_max` dit
SI l'update a été coupée, ce compteur dit OÙ. Sans coupure il vaut exactement
`n_epochs × ceil(n_steps / batch_size)` ; avec coupure il est strictement inférieur, parce que
le mini-lot déclencheur fait `break` AVANT son backward et n'est donc jamais compté.

PREUVE PAR MUTATION :
  Remplacer `np.max` par `np.min` → ROUGE `test_approx_kl_max_exceeds_threshold`.
  Supprimer le `logger.record` → ROUGE les deux tests de présence.
  Supprimer `n_minibatches_done += 1` → ROUGE `test_n_minibatches_done_counts_every_step`.
  Déplacer l'incrément avant le test d'early-stop → ROUGE
  `test_n_minibatches_done_stops_at_first_step_when_early_stopped` (target_kl infime :
  coupure au mini-lot 0 ou 1, compteur attendu ≤ 1, obtenu 2).
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


_N_STEPS = 8
_BATCH_SIZE = 4
_N_EPOCHS = 4
#: Pas de gradient d'un update dont aucune epoch n'est coupée.
_N_MINIBATCHES_PLANNED = _N_EPOCHS * (_N_STEPS // _BATCH_SIZE)


def _train_once(target_kl: float | None) -> dict[str, float]:
    """Un update PPO complet ; retourne les scalaires posés sur le logger."""
    model = PatchedMaskablePPO(
        "MlpPolicy",
        _TinyMaskedEnv(),
        n_steps=_N_STEPS,
        batch_size=_BATCH_SIZE,
        n_epochs=_N_EPOCHS,
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


def test_n_minibatches_done_counts_every_step_when_no_early_stop() -> None:
    """Sans coupure, le compteur vaut EXACTEMENT le plan `n_epochs × minibatches`.

    Égalité stricte, pas `>= 1` : un compteur qui s'arrêterait à la première epoch, ou qui
    compterait les epochs au lieu des mini-lots, passerait un test de simple présence.
    """
    recorded = _train_once(target_kl=None)

    assert "train/n_minibatches_done" in recorded, "train/n_minibatches_done absent du dump"
    assert recorded["train/n_minibatches_done"] == _N_MINIBATCHES_PLANNED, (
        f"n_minibatches_done={recorded['train/n_minibatches_done']} ≠ plan "
        f"{_N_MINIBATCHES_PLANNED} ({_N_EPOCHS} epochs × {_N_STEPS // _BATCH_SIZE} mini-lots) "
        "alors qu'aucune coupure n'est possible sans target_kl"
    )


def test_n_minibatches_done_stops_at_first_step_when_early_stopped() -> None:
    """`target_kl` infime : au plus UN pas de gradient est exécuté.

    Le mini-lot 0 évalue la politique qui a collecté le rollout : son KL vaut 0 exactement (ou
    le bruit float32), donc la coupure tombe au mini-lot 0 ou, après le premier pas, au mini-lot
    1 — jamais plus tard, tout KL d'une politique qui a bougé dépassant 1,5e-20. Le mini-lot
    déclencheur fait `break` avant `loss.backward()` et ne doit pas être compté : un incrément
    placé avant le test d'early-stop rendrait 2 ici (mesuré : 1 avec l'incrément après `step()`).
    """
    recorded = _train_once(target_kl=1e-20)

    assert recorded["train/approx_kl_max"] > 1.5e-20, "pré-condition : la coupure doit avoir eu lieu"
    done = recorded["train/n_minibatches_done"]
    assert 0 <= done <= 1, (
        f"n_minibatches_done={done} après une coupure au mini-lot 0 ou 1 — le mini-lot "
        "déclencheur a été compté, ou la coupure est arrivée plus tard que prévu"
    )
