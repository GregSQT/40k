"""Tests — température des logits (S9, plafonnement_p1.md §9.9 étape 2) : π_T = softmax(logits / T).

Ce que le régime doit garantir, chacun verrouillé ici :
- T divise les logits AVANT le masquage, partout où la politique construit une distribution :
  `get_distribution` (collecte), `evaluate_actions` (ratio PPO, entropie) — et les deux
  rendent la MÊME log-probabilité pour la même action (ratio 1 sur la même π_T) ;
- l'argmax est invariant à T (les sondes déterministes mesurent la même politique) ;
- T = 1 est bit à bit le comportement antérieur ;
- régime de RUN : posé par le constructeur (`--new`) et par le profil (`_apply_curriculum_model_params`,
  `--append`) via une propriété qui ÉCRIT SUR LA POLITIQUE ; exclu du zip (un modèle rechargé
  repart à 1,0) ; transporté aux workers par la sérialisation de la politique ;
- refus explicite d'une valeur qui n'est pas un flottant > 0, et d'une politique qui ne
  tempère pas ses logits quand T ≠ 1.
"""
from __future__ import annotations

from typing import Any, cast

import cloudpickle
import numpy as np
import pytest
import torch as th

import ai.train as train_module
from ai.patched_ppo import PatchedMaskablePPO
from ai.pointer_policy import PointerMaskablePolicy, check_logits_temperature, masked_probs
from engine.macro_intents import TOTAL_ACTION_SIZE
from tests.unit.ai.test_critic_warmup import _model as _mlp_model
from tests.unit.ai.test_gradient_norm_is_pre_clip import _TinyMaskedEnv
from tests.unit.ai.test_pointer_head import _ToyEnv
from tests.unit.ai.test_q_head import _model, _obs_tensor, _policy


def _randomize_heads(pol: PointerMaskablePolicy) -> None:
    """Logits NON dégénérés : à l'initialisation, plusieurs têtes rendent des colonnes égales."""
    with th.no_grad():
        for p in pol.action_net.parameters():
            p.normal_()
        for p in pol.query_net.parameters():
            p.normal_()


def _masks(batch: int) -> np.ndarray:
    masks = np.ones((batch, TOTAL_ACTION_SIZE), dtype=bool)
    masks[1, 1030:] = False  # un état partiellement masqué
    return masks


# --- la distribution -----------------------------------------------------------------------------


def test_la_temperature_divise_les_logits_avant_le_masquage() -> None:
    """π_T(a|s) = softmax(logits(s) / T) sur les légales ; à T = 1 rien ne change."""
    pol = _policy(_model())
    pol.set_training_mode(False)
    _randomize_heads(pol)
    obs_t = _obs_tensor(pol)
    masks = _masks(3)
    with th.no_grad():
        feats = pol._split_features(obs_t)
        latent_pi = pol.mlp_extractor.forward_actor(feats.trunk)
        logits = pol._action_logits(latent_pi, feats)
        pol.logits_temperature = 1.0
        probs_1 = masked_probs(pol._distribution_from(latent_pi, feats, masks)).clone()
        pol.logits_temperature = 2.0
        probs_2 = masked_probs(pol._distribution_from(latent_pi, feats, masks)).clone()
    mask_t = th.as_tensor(masks)
    expected_1 = th.softmax(logits.masked_fill(~mask_t, -1e8), dim=1)
    expected_2 = th.softmax((logits / 2.0).masked_fill(~mask_t, -1e8), dim=1)
    assert th.allclose(probs_1, expected_1, atol=1e-6)
    assert th.allclose(probs_2, expected_2, atol=1e-6)
    assert th.equal(probs_2[1, 1030:], th.zeros_like(probs_2[1, 1030:])), "masque sans effet"
    # VERT VACANT : T = 2 aplatit réellement (entropie plus haute), et les argmax coïncident.
    h1 = -(probs_1.clamp_min(1e-12).log() * probs_1).sum(dim=1)
    h2 = -(probs_2.clamp_min(1e-12).log() * probs_2).sum(dim=1)
    assert bool((h2 > h1 + 1e-4).all()), (h1, h2)
    assert th.equal(probs_1.argmax(dim=1), probs_2.argmax(dim=1))


def test_collecte_et_ratio_lisent_la_meme_pi_t() -> None:
    """`get_distribution` (collecte) et `evaluate_actions` (ratio PPO) rendent la même
    log-probabilité sous T : le ratio d'une action jouée vaut 1 sur les mêmes poids."""
    pol = _policy(_model())
    pol.set_training_mode(False)
    _randomize_heads(pol)
    obs_t = _obs_tensor(pol)
    masks = _masks(3)
    actions = th.tensor([0, 1024, 1025 + 2])
    pol.logits_temperature = 2.0
    with th.no_grad():
        lp_collect = pol.get_distribution(obs_t, action_masks=masks).log_prob(actions)
        _, lp_train, entropy = pol.evaluate_actions(cast(Any, obs_t), actions, cast(Any, masks))
        pol.logits_temperature = 1.0
        lp_ref = pol.get_distribution(obs_t, action_masks=masks).log_prob(actions)
    assert th.allclose(lp_collect, lp_train)
    assert not th.allclose(lp_collect, lp_ref), "VERT VACANT : T sans effet sur log_prob"
    assert entropy is not None and bool(th.isfinite(entropy).all())


# --- le régime : constructeur, profil, zip, workers ----------------------------------------------


def test_le_constructeur_pose_t_sur_la_politique() -> None:
    model = _model(logits_temperature=2.0)
    assert model.logits_temperature == 2.0
    assert _policy(model).logits_temperature == 2.0
    assert _policy(_model()).logits_temperature == 1.0


def test_le_profil_pose_t_sur_la_politique_en_append() -> None:
    """`_apply_curriculum_model_params` passe par `setattr` : la propriété écrit sur la politique."""
    model = _model()
    train_module._apply_curriculum_model_params(
        model, {"logits_temperature": 2.0}, log=lambda *_: None
    )
    assert model.logits_temperature == 2.0 and _policy(model).logits_temperature == 2.0
    train_module._apply_curriculum_model_params(
        model, {"logits_temperature": 1.0}, log=lambda *_: None
    )
    assert _policy(model).logits_temperature == 1.0


def test_t_ne_voyage_pas_dans_le_zip(tmp_path) -> None:
    """Un modèle rechargé repart à 1,0 : évaluation, adversaires figés et PvE jouent T = 1."""
    model = _model(logits_temperature=2.0)
    path = str(tmp_path / "t.zip")
    model.save(path)
    loaded = PatchedMaskablePPO.load(path, env=_ToyEnv(), device="cpu")
    assert loaded.logits_temperature == 1.0
    assert _policy(loaded).logits_temperature == 1.0
    assert "logits_temperature" not in _policy(loaded).state_dict()


def test_t_voyage_vers_les_workers() -> None:
    """La politique sérialisée pour la collecte distribuée porte T."""
    model = _model(logits_temperature=2.0)
    blob = model._serialize_policy_for_workers()
    worker_policy = cloudpickle.loads(blob)
    assert isinstance(worker_policy, PointerMaskablePolicy)
    assert worker_policy.logits_temperature == 2.0


# --- refus -----------------------------------------------------------------------------------------


def test_les_valeurs_invalides_sont_refusees() -> None:
    for bad in (0, -1.0, True, "2", None):
        with pytest.raises(ValueError, match="logits_temperature"):
            check_logits_temperature(bad)
    assert check_logits_temperature(2) == 2.0
    with pytest.raises(ValueError, match="logits_temperature"):
        _model(logits_temperature=0.0)


def test_une_politique_sans_temperature_refuse_t_different_de_1() -> None:
    """`MlpPolicy` ne tempère pas : T = 1 passe, T ≠ 1 lève au lieu d'être ignoré en silence."""
    model = _mlp_model(n_warmup=0)
    model.logits_temperature = 1.0
    with pytest.raises(TypeError, match="logits_temperature"):
        model.logits_temperature = 2.0
    with pytest.raises(TypeError, match="logits_temperature"):
        PatchedMaskablePPO(
            "MlpPolicy", _TinyMaskedEnv(), n_steps=8, batch_size=4, n_epochs=1, seed=0,
            device="cpu", policy_kwargs={"net_arch": [8]}, logits_temperature=2.0,
        )
