"""Tests — échauffement du critic (décision B6 : value_warmup_updates).

Pendant les N premières updates (train() calls), seul value_loss contribue à la loss :
policy_loss et entropy sont annulés. L'early-stop KL est désactivé pendant ce régime.
Après N updates, le comportement normal reprend.

`train/value_warmup_active` est publié à 1 pendant le régime warmup, 0 ensuite.
`_vwu_done` compte le nombre d'updates warmup effectuées. Ni la clé ni le compteur ne sont
sérialisés : le régime appartient au run, jamais au checkpoint.

Pendant le warmup, la politique est immobile au bit près : paramètres hors critic gelés
(`grad = None`) ET statistiques d'`EntityRunningNorm` figées (tout ce qui n'est pas critic passe
en mode évaluation, sinon `set_training_mode(True)` les fait avancer à chaque minibatch).
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pytest
import torch as th
from gymnasium import spaces
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

from ai.patched_ppo import PatchedMaskablePPO
from ai.pointer_policy import PointerMaskablePolicy
from ai.spatial_extractor import EntityRunningNorm, SpatialCombinedExtractor
from tests.unit.ai.test_gradient_norm_is_pre_clip import _TinyMaskedEnv
from tests.unit.ai.test_pointer_head import _ToyEnv


def _model(n_warmup: int, **policy_kwargs: Any) -> PatchedMaskablePPO:
    """`MlpPolicy` sur `_TinyMaskedEnv` ; la clé passe par le constructeur, comme en `--new`."""
    return PatchedMaskablePPO(
        "MlpPolicy",
        _TinyMaskedEnv(),
        n_steps=8,
        batch_size=4,
        n_epochs=1,
        seed=0,
        device="cpu",
        policy_kwargs={"net_arch": [8], **policy_kwargs},
        value_warmup_updates=n_warmup,
    )


def _production_model(n_warmup: int) -> PatchedMaskablePPO:
    """Le VRAI chemin : `PointerMaskablePolicy` + `SpatialCombinedExtractor` (extracteur partagé imposé)."""
    return PatchedMaskablePPO(
        PointerMaskablePolicy, _ToyEnv(), n_steps=8, batch_size=4, n_epochs=1, seed=0,
        device="cpu", verbose=0,
        policy_kwargs={
            "net_arch": [16, 16],
            "features_extractor_class": SpatialCombinedExtractor,
            "features_extractor_kwargs": {"cnn_features": 8},
        },
        value_warmup_updates=n_warmup,
    )


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
        # `del`, pas une réassignation : `model.train = original_train` laisserait une méthode
        # LIÉE dans `__dict__`, que `save()` sérialise (cloudpickle) et que `load()` restaure —
        # le modèle rechargé entraînerait alors une copie du modèle d'origine, pas lui-même.
        del model.train
    return recorded


def _snapshot(*param_sources: Iterable[th.nn.Parameter]) -> list[th.Tensor]:
    """Copie détachée des tenseurs, pour comparer au bit près avant/après une update."""
    return [t.detach().clone() for source in param_sources for t in source]


def _policy_head_params(model: PatchedMaskablePPO) -> list[th.Tensor]:
    """Poids de la politique seule : tête d'action + tronc pi (le tronc vf est séparé)."""
    pol = model.policy
    return _snapshot(pol.action_net.parameters(), pol.mlp_extractor.policy_net.parameters())


def _value_head_params(model: PatchedMaskablePPO) -> list[th.Tensor]:
    pol = model.policy
    return _snapshot(pol.value_net.parameters(), pol.mlp_extractor.value_net.parameters())


def _all_equal(before: list[th.Tensor], after: list[th.Tensor]) -> bool:
    return all(th.equal(a, b) for a, b in zip(before, after))


def test_value_warmup_active_est_1_pendant_le_warmup() -> None:
    """train/value_warmup_active = 1 pendant la première update warmup.

    VERROU. Retirer value_warmup_updates de _PLAIN_CURRICULUM_KEYS ou oublier l'incrémentation
    de _vwu_done ferait tomber ce test au ROUGE : soit le compteur ne monterait jamais, soit
    l'indicateur resterait 0 même avec value_warmup_updates > 0.
    """
    model = _model(n_warmup=3)
    recorded = _run_one_update(model)

    assert "train/value_warmup_active" in recorded, "train() ne publie pas train/value_warmup_active"
    assert recorded["train/value_warmup_active"] == pytest.approx(1.0), (
        "première update avec value_warmup_updates=3 doit avoir warmup_active=1"
    )
    assert model._vwu_done == 1, "_vwu_done doit être 1 après la première update"


def test_value_warmup_active_est_0_sans_warmup() -> None:
    """Sans value_warmup_updates, train/value_warmup_active = 0 dès la première update."""
    model = _model(n_warmup=0)
    recorded = _run_one_update(model)

    assert recorded.get("train/value_warmup_active") == pytest.approx(0.0), (
        "sans warmup, value_warmup_active doit valoir 0"
    )
    assert model._vwu_done == 0, "_vwu_done ne doit pas incrementer hors warmup"


def test_vwu_done_incremente_puis_sature() -> None:
    """_vwu_done monte jusqu'à value_warmup_updates puis s'arrête.

    VERROU. Sans la condition `if _in_warmup`, _vwu_done continuerait d'incrémenter au-delà
    de value_warmup_updates et pousserait _in_warmup à True pour toujours.
    """
    n = 2
    model = _model(n_warmup=n)

    # Update 1 : warmup actif
    _run_one_update(model)
    assert model._vwu_done == 1

    # Update 2 : warmup actif
    _run_one_update(model)
    assert model._vwu_done == 2

    # Update 3 : warmup terminé, _vwu_done ne monte plus
    recorded = _run_one_update(model)
    assert model._vwu_done == 2, "_vwu_done ne doit pas dépasser value_warmup_updates"
    assert recorded.get("train/value_warmup_active") == pytest.approx(0.0), (
        "après N updates, warmup_active doit valoir 0"
    )


def test_la_politique_ne_bouge_pas_pendant_le_warmup_mais_le_critic_oui() -> None:
    """Pendant le warmup, seul le critic apprend : les poids de la politique restent identiques.

    VERROU. Retirer le gel `grad = None` des paramètres hors critic dans la branche
    `_in_warmup` de `PatchedMaskablePPO.train` ET remettre la loss complète fait passer ce test
    au ROUGE : la tête d'action reçoit un gradient et ses poids changent.
    CONTRÔLE NON VACANT : les poids du critic DOIVENT changer sur la même update, sinon
    l'égalité de la politique pourrait venir d'un learning rate nul.
    """
    model = _model(n_warmup=1)
    pi_before = _policy_head_params(model)
    vf_before = _value_head_params(model)

    _run_one_update(model)

    assert _all_equal(pi_before, _policy_head_params(model)), (
        "la politique a bougé pendant le warmup critic"
    )
    assert not _all_equal(vf_before, _value_head_params(model)), (
        "le critic n'a pas bougé : l'update n'a rien appris, le test ne prouve rien"
    )


def test_la_politique_bouge_hors_warmup() -> None:
    """Miroir : sans warmup, la même update déplace la politique."""
    model = _model(n_warmup=0)
    pi_before = _policy_head_params(model)

    _run_one_update(model)

    assert not _all_equal(pi_before, _policy_head_params(model))


def test_la_cle_est_acceptee_par_le_constructeur_comme_en_new() -> None:
    """`--new` passe TOUT `model_params` au constructeur : la clé doit y être un kwarg explicite.

    VERROU. Retirer `value_warmup_updates` de la signature de `PatchedMaskablePPO.__init__`
    fait lever `TypeError: unexpected keyword argument` — exactement ce qu'un run `--new` ferait
    le jour où le profil porte la clé.
    """
    model = _model(n_warmup=2)
    assert model.value_warmup_updates == 2
    assert model._vwu_done == 0


def test_le_warmup_est_un_regime_de_run_pas_un_heritage_de_checkpoint(tmp_path) -> None:
    """Sauver après un run échauffé puis recharger : ni la clé ni le compteur ne voyagent.

    Deux défauts distincts, un seul verrou. Sans `_vwu_done` dans `_excluded_save_params`,
    `_vwu_done = N` voyagerait dans le zip et le run `--append` suivant sauterait en silence
    l'échauffement que son profil demande. Sans `value_warmup_updates` dans la même liste, la
    clé restaurée au `load` + le compteur remis à 0 rejouaient N updates critic-only sur tout
    `--append` dont le profil ne porte pas la clé (`_apply_curriculum_model_params` ne pose que
    ce que le profil porte). Un checkpoint ne porte donc AUCUN régime d'échauffement : c'est le
    profil du run, et lui seul, qui l'active.
    """
    model = _model(n_warmup=1)
    _run_one_update(model)
    assert model._vwu_done == 1
    path = tmp_path / "m.zip"
    model.save(str(path))

    loaded = PatchedMaskablePPO.load(str(path), env=_TinyMaskedEnv(), device="cpu")
    assert loaded.value_warmup_updates == 0, (
        "la clé a voyagé dans le zip : un --append sans la clé rejouerait le warmup en silence"
    )
    assert loaded._vwu_done == 0, "le compteur ne doit pas être hérité du checkpoint"
    recorded = _run_one_update(loaded)
    assert recorded.get("train/value_warmup_active") == pytest.approx(0.0), (
        "le modèle rechargé a rejoué un warmup que son run n'a pas demandé"
    )


def test_un_checkpoint_anterieur_a_b6_charge_sans_warmup(tmp_path) -> None:
    """Zip sauvé sans la clé (S11 P0) : chargé avec value_warmup_updates = 0, pas d'erreur.

    Simule l'antériorité en retirant la clé du `__dict__` avant la sauvegarde.
    """
    model = _model(n_warmup=0)
    delattr(model, "value_warmup_updates")
    path = tmp_path / "old.zip"
    model.save(str(path))

    loaded = PatchedMaskablePPO.load(str(path), env=_TinyMaskedEnv(), device="cpu")
    assert loaded.value_warmup_updates == 0
    recorded = _run_one_update(loaded)
    assert recorded.get("train/value_warmup_active") == pytest.approx(0.0)


# --- Extracteur PARTAGÉ à paramètres (le cas de production) --------------------------------
#
# `MlpPolicy` a un extracteur `Flatten` SANS paramètre : les cinq tests ci-dessus ne prouvent
# l'immobilité de la politique que pour lui. En production, `PointerMaskablePolicy` exige
# `share_features_extractor=True` (ai/pointer_policy.py) et ses logits `q · e_i` lisent les
# embeddings de l'extracteur : un gradient de value loss qui traverse l'extracteur déplace la
# politique — sans clip (policy_loss hors de la loss) et sans early-stop KL. Le montage
# ci-dessous reproduit la structure : un extracteur `Linear` partagé par l'acteur et le critic.


class _LinearExtractor(BaseFeaturesExtractor):
    """Extracteur partagé À PARAMÈTRES : une couche linéaire 3 -> 6."""

    def __init__(self, observation_space: spaces.Box) -> None:
        super().__init__(observation_space, features_dim=6)
        self.proj = th.nn.Linear(3, 6)

    def forward(self, observations: th.Tensor) -> th.Tensor:
        return th.tanh(self.proj(observations))


def _model_with_shared_extractor(n_warmup: int) -> PatchedMaskablePPO:
    return _model(
        n_warmup, features_extractor_class=_LinearExtractor, share_features_extractor=True
    )


def _extractor_params(model: PatchedMaskablePPO) -> list[th.Tensor]:
    return _snapshot(model.policy.features_extractor.parameters())


def _policy_logits(model: PatchedMaskablePPO) -> np.ndarray:
    """Logits de la politique sur une grille d'observations fixes : ce que voit l'agent."""
    obs = th.tensor([[0.1, 0.2, 0.3], [-0.4, 0.0, 0.4], [0.3, -0.3, 0.3]], dtype=th.float32)
    with th.no_grad():
        dist = model.policy.get_distribution(obs)
    inner = dist.distribution
    assert isinstance(inner, th.distributions.Categorical), type(inner).__name__
    return inner.logits.numpy().copy()


def test_l_extracteur_partage_a_des_parametres() -> None:
    """VERT VACANT : sans paramètre dans l'extracteur, le test suivant ne prouverait rien de
    plus que ceux à `Flatten`."""
    model = _model_with_shared_extractor(n_warmup=1)
    assert model.policy.share_features_extractor is True
    assert len(_extractor_params(model)) == 2, "Linear 3->6 : un poids et un biais attendus"


def test_avec_extracteur_partage_les_logits_de_la_politique_sont_immobiles_pendant_le_warmup() -> None:
    """Le cas de production : extracteur partagé, la politique ne doit pas bouger d'un bit.

    VERROU. Sans le gel des paramètres hors critic (`_critic_only_param_ids` dans
    `PatchedMaskablePPO.train`), la value loss rétropropage à travers l'extracteur partagé, ses
    poids changent et les logits de la politique avec eux — ROUGE constaté avant le gel.
    CONTRÔLE NON VACANT : le critic doit bouger sur la même update.
    """
    model = _model_with_shared_extractor(n_warmup=1)
    ext_before = _extractor_params(model)
    pi_before = _policy_head_params(model)
    logits_before = _policy_logits(model)
    vf_before = _value_head_params(model)

    _run_one_update(model)

    assert _all_equal(ext_before, _extractor_params(model)), (
        "l'extracteur partagé a bougé pendant le warmup critic : la politique qui le lit a bougé"
    )
    assert _all_equal(pi_before, _policy_head_params(model))
    assert np.array_equal(logits_before, _policy_logits(model)), (
        "les logits de la politique ont changé pendant le warmup critic"
    )
    assert not _all_equal(vf_before, _value_head_params(model)), (
        "le critic n'a pas bougé : l'update n'a rien appris, le test ne prouve rien"
    )


def test_avec_extracteur_partage_l_extracteur_bouge_hors_warmup() -> None:
    """Miroir : hors warmup, la même update déplace l'extracteur partagé (le gel est bien
    limité au régime warmup, pas permanent)."""
    model = _model_with_shared_extractor(n_warmup=0)
    ext_before = _extractor_params(model)
    logits_before = _policy_logits(model)

    _run_one_update(model)

    assert not _all_equal(ext_before, _extractor_params(model))
    assert not np.array_equal(logits_before, _policy_logits(model))


# --- Le VRAI chemin : PointerMaskablePolicy + SpatialCombinedExtractor --------------------------

_CRITIC_PREFIXES = ("mlp_extractor.value_net.", "value_net.")


def test_sur_la_policy_de_production_seul_le_critic_bouge_pendant_le_warmup() -> None:
    """`PointerMaskablePolicy` (extracteur partagé imposé) : pendant le warmup, l'extracteur,
    le tronc pi et TOUTES les têtes restent identiques au bit près ; seuls
    `mlp_extractor.value_net` et `value_net` changent.

    C'est le montage qui manquait : `MlpPolicy` a un extracteur sans paramètre, et son vert ne
    disait rien de la policy réellement entraînée. L'assertion finale est NOMMÉE (préfixes),
    indépendante de la partition que le modèle déclare (`_critic_only_param_ids`).
    """
    model = _production_model(n_warmup=1)
    pol = model.policy
    critic_ids = model._critic_only_param_ids()
    named_before = {n: p.detach().clone() for n, p in pol.named_parameters()}
    assert len(named_before) > 20, "VERT VACANT : la policy de production porte des dizaines de tenseurs"
    non_critic = [n for n, p in pol.named_parameters() if id(p) not in critic_ids]
    assert any(n.startswith("features_extractor.") for n in non_critic)
    assert any("query_net" in n for n in non_critic)

    _run_one_update(model)

    moved = sorted(
        n for n, p in pol.named_parameters()
        if not th.equal(named_before[n], p.detach())
    )
    assert moved, "le critic n'a pas bougé : l'update n'a rien appris, le test ne prouve rien"
    leaked = [n for n in moved if not n.startswith(_CRITIC_PREFIXES)]
    assert not leaked, f"des paramètres hors critic ont bougé pendant le warmup : {leaked}"


def test_sur_la_policy_de_production_les_statistiques_de_normalisation_sont_figees_pendant_le_warmup() -> None:
    """Le gel des paramètres ne fige pas les BUFFERS : `EntityRunningNorm` avance ses
    `running_mean/var/count` à chaque forward en mode entraînement, et les logits de la
    politique bougent avec eux (mesuré sans le gel : 9 buffers sur 16 déplacés, Δprobs 4,5e-4
    après une update warmup). Pendant le warmup, ni les buffers ni la distribution de la
    politique sur une observation fixe ne doivent changer, au bit près.

    Rouge sans le passage en mode évaluation de tout ce qui n'est pas critic en tête de `train`.
    """
    model = _production_model(n_warmup=1)
    pol = model.policy
    norms = [m for m in pol.modules() if isinstance(m, EntityRunningNorm)]
    assert norms, "VERT VACANT : l'extracteur de production porte des EntityRunningNorm"
    buffers_before = {n: b.detach().clone() for n, b in pol.named_buffers()}
    assert any("running_mean" in n for n in buffers_before)

    env = _ToyEnv()
    obs, _ = env.reset(seed=1)
    obs_t, _ = pol.obs_to_tensor(obs)
    mask = env.action_masks()

    def _probs() -> th.Tensor:
        pol.set_training_mode(False)
        with th.no_grad():
            inner = pol.get_distribution(obs_t, action_masks=mask).distribution
        assert isinstance(inner, th.distributions.Categorical), type(inner).__name__
        return inner.probs.clone()

    probs_before = _probs()

    _run_one_update(model)

    moved = sorted(n for n, b in pol.named_buffers() if not th.equal(buffers_before[n], b.detach()))
    assert moved == [], f"statistiques de normalisation déplacées pendant le warmup : {moved}"
    probs_after = _probs()
    assert th.equal(probs_before, probs_after), (
        f"la politique a bougé pendant le warmup : max |Δprobs| = "
        f"{float((probs_after - probs_before).abs().max())}"
    )
    # Hors warmup (update suivante), les statistiques reprennent leur mise à jour : le gel est
    # bien un régime, pas une désactivation.
    _run_one_update(model)
    assert model._vwu_done == 1
    moved_after = [n for n, b in pol.named_buffers() if not th.equal(buffers_before[n], b.detach())]
    assert moved_after, "les statistiques ne bougent plus du tout : le gel a survécu au warmup"
