"""Tests — échauffement du critic (décision B6 : value_warmup_updates).

Pendant les N premières updates (train() calls), seul value_loss contribue à la loss :
policy_loss et entropy sont annulés. L'early-stop KL est désactivé pendant ce régime.
Après N updates, le comportement normal reprend.

`train/value_warmup_active` est publié à 1 pendant le régime warmup, 0 ensuite.
`_vwu_done` compte le nombre d'updates warmup effectuées.
"""

from __future__ import annotations

from typing import Any

import gymnasium
import numpy as np
import pytest
from gymnasium import spaces

from ai.patched_ppo import PatchedMaskablePPO


class _TinyMaskedEnv(gymnasium.Env):
    """Env minimal : 3 obs, 2 actions, 4 steps par épisode. Identique à test_gradient_norm."""

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


def _model_with_warmup(n_warmup: int) -> PatchedMaskablePPO:
    model = PatchedMaskablePPO(
        "MlpPolicy",
        _TinyMaskedEnv(),
        n_steps=8,
        batch_size=4,
        n_epochs=1,
        seed=0,
        device="cpu",
        policy_kwargs={"net_arch": [8]},
    )
    model.value_warmup_updates = n_warmup
    return model


def _run_one_update(model: PatchedMaskablePPO) -> dict[str, float]:
    """Lance une update et retourne les scalaires logués."""
    recorded: dict[str, float] = {}
    original_train = model.train

    def _capture() -> None:
        original_train()
        recorded.update(model.logger.name_to_value)

    model.train = _capture  # type: ignore[method-assign]
    try:
        model.learn(total_timesteps=8)
    finally:
        model.train = original_train  # type: ignore[method-assign]
    return recorded


def test_value_warmup_active_est_1_pendant_le_warmup() -> None:
    """train/value_warmup_active = 1 pendant la première update warmup.

    VERROU. Retirer value_warmup_updates de _PLAIN_CURRICULUM_KEYS ou oublier l'incrémentation
    de _vwu_done ferait tomber ce test au ROUGE : soit le compteur ne monterait jamais, soit
    l'indicateur resterait 0 même avec value_warmup_updates > 0.
    """
    model = _model_with_warmup(n_warmup=3)
    recorded = _run_one_update(model)

    assert "train/value_warmup_active" in recorded, "train() ne publie pas train/value_warmup_active"
    assert recorded["train/value_warmup_active"] == pytest.approx(1.0), (
        "première update avec value_warmup_updates=3 doit avoir warmup_active=1"
    )
    assert getattr(model, "_vwu_done", 0) == 1, "_vwu_done doit être 1 après la première update"


def test_value_warmup_active_est_0_sans_warmup() -> None:
    """Sans value_warmup_updates, train/value_warmup_active = 0 dès la première update."""
    model = _model_with_warmup(n_warmup=0)
    recorded = _run_one_update(model)

    assert recorded.get("train/value_warmup_active") == pytest.approx(0.0), (
        "sans warmup, value_warmup_active doit valoir 0"
    )
    assert getattr(model, "_vwu_done", 0) == 0, "_vwu_done ne doit pas incrementer hors warmup"


def test_vwu_done_incremente_puis_sature() -> None:
    """_vwu_done monte jusqu'à value_warmup_updates puis s'arrête.

    VERROU. Sans la condition `if _was_warmup`, _vwu_done continuerait d'incrémenter au-delà
    de value_warmup_updates et pousserait _in_warmup à True pour toujours.
    """
    n = 2
    model = _model_with_warmup(n_warmup=n)

    # Update 1 : warmup actif
    _run_one_update(model)
    assert getattr(model, "_vwu_done", 0) == 1

    # Reset le logger pour capturer la seconde update
    _run_one_update(model)
    assert getattr(model, "_vwu_done", 0) == 2

    # Update 3 : warmup terminé, _vwu_done ne monte plus
    recorded = _run_one_update(model)
    assert getattr(model, "_vwu_done", 0) == 2, "_vwu_done ne doit pas dépasser value_warmup_updates"
    assert recorded.get("train/value_warmup_active") == pytest.approx(0.0), (
        "après N updates, warmup_active doit valoir 0"
    )


def _policy_head_params(model: PatchedMaskablePPO) -> list:
    """Poids de la politique seule : tête d'action + tronc pi (le tronc vf est séparé)."""
    pol = model.policy
    tensors = list(pol.action_net.parameters()) + list(pol.mlp_extractor.policy_net.parameters())
    return [t.detach().clone() for t in tensors]


def _value_head_params(model: PatchedMaskablePPO) -> list:
    pol = model.policy
    tensors = list(pol.value_net.parameters()) + list(pol.mlp_extractor.value_net.parameters())
    return [t.detach().clone() for t in tensors]


def test_la_politique_ne_bouge_pas_pendant_le_warmup_mais_le_critic_oui() -> None:
    """Pendant le warmup, seul le critic apprend : les poids de la politique restent identiques.

    VERROU. Remettre `loss = policy_loss + self.ent_coef * entropy_term + self.vf_coef *
    value_loss` dans la branche `_in_warmup` fait passer ce test au ROUGE : la tête d'action
    reçoit un gradient et ses poids changent.
    CONTRÔLE NON VACANT : les poids du critic DOIVENT changer sur la même update, sinon
    l'égalité de la politique pourrait venir d'un learning rate nul.
    """
    model = _model_with_warmup(n_warmup=1)
    pi_before = _policy_head_params(model)
    vf_before = _value_head_params(model)

    _run_one_update(model)

    pi_after = _policy_head_params(model)
    vf_after = _value_head_params(model)
    assert all(np.array_equal(a.numpy(), b.numpy()) for a, b in zip(pi_before, pi_after)), (
        "la politique a bougé pendant le warmup critic"
    )
    assert any(not np.array_equal(a.numpy(), b.numpy()) for a, b in zip(vf_before, vf_after)), (
        "le critic n'a pas bougé : l'update n'a rien appris, le test ne prouve rien"
    )


def test_la_politique_bouge_hors_warmup() -> None:
    """Miroir : sans warmup, la même update déplace la politique."""
    model = _model_with_warmup(n_warmup=0)
    pi_before = _policy_head_params(model)

    _run_one_update(model)

    pi_after = _policy_head_params(model)
    assert any(not np.array_equal(a.numpy(), b.numpy()) for a, b in zip(pi_before, pi_after))


def test_la_cle_est_acceptee_par_le_constructeur_comme_en_new() -> None:
    """`--new` passe TOUT `model_params` au constructeur : la clé doit y être un kwarg explicite.

    VERROU. Retirer `value_warmup_updates` de la signature de `PatchedMaskablePPO.__init__`
    fait lever `TypeError: unexpected keyword argument` — exactement ce qu'un run `--new` ferait
    le jour où le profil porte la clé.
    """
    model = PatchedMaskablePPO(
        "MlpPolicy", _TinyMaskedEnv(), n_steps=8, batch_size=4, n_epochs=1, seed=0,
        device="cpu", policy_kwargs={"net_arch": [8]}, value_warmup_updates=2,
    )
    assert model.value_warmup_updates == 2
    assert model._vwu_done == 0


def test_le_warmup_est_un_regime_de_run_pas_un_heritage_de_checkpoint(tmp_path) -> None:
    """Sauver après le warmup puis recharger : `_vwu_done` repart de 0, la clé est conservée.

    Sans `_excluded_save_params`, `_vwu_done = N` voyagerait dans le zip et le run `--append`
    suivant sauterait en silence l'échauffement que son profil demande.
    """
    model = _model_with_warmup(n_warmup=1)
    _run_one_update(model)
    assert model._vwu_done == 1
    path = tmp_path / "m.zip"
    model.save(str(path))

    loaded = PatchedMaskablePPO.load(str(path), env=_TinyMaskedEnv(), device="cpu")
    assert loaded.value_warmup_updates == 1, "la clé fait partie du checkpoint, comme entropy_normalize_by_legal"
    assert loaded._vwu_done == 0, "le compteur ne doit pas être hérité du checkpoint"


def test_un_checkpoint_anterieur_a_b6_charge_sans_warmup(tmp_path) -> None:
    """Zip sauvé sans la clé (S11 P0) : chargé avec value_warmup_updates = 0, pas d'erreur.

    Simule l'antériorité en retirant la clé du `__dict__` avant la sauvegarde.
    """
    model = _model_with_warmup(n_warmup=0)
    delattr(model, "value_warmup_updates")
    path = tmp_path / "old.zip"
    model.save(str(path))

    loaded = PatchedMaskablePPO.load(str(path), env=_TinyMaskedEnv(), device="cpu")
    assert loaded.value_warmup_updates == 0
    recorded = _run_one_update(loaded)
    assert recorded.get("train/value_warmup_active") == pytest.approx(0.0)
