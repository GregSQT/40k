"""Échauffement critic (B6) — la branche politique ne retient pas ses activations.

Pendant l'échauffement, `loss = vf_coef × value_loss` : aucun backward ne traverse la branche
politique. Ses tenseurs (`policy_loss`, `entropy_loss`) empilés AVEC leur graphe dans les listes
de logging retenaient donc les activations de chaque mini-lot jusqu'à la fin de `train()`.
Mesuré le 2026-09-16 sur `x1_lineage` (340 × 24, lot 1020, 4 epochs) : 9,69 Gio alloués /
12,11 réservés par update d'échauffement contre 1,79 / 2,08 en régime normal, réservation
jamais rendue sous WSL2 (pas d'OOM, débordement en RAM hôte) — `train/time_update` 5 s →
20-345 s sur tout le reste du run `run_20260916-092441`.

L'instrument est `torch.autograd.graph.saved_tensors_hooks` : chaque tenseur intermédiaire
sauvé pour le backward est suivi par référence faible, étiqueté du mini-lot qui l'a produit.
`gc` ne verrait rien — les activations sauvées sont tenues par les nœuds C++ du graphe, pas
par des objets Python.
"""

from __future__ import annotations

import math
import weakref
from typing import Any, Dict, List

import pytest
import torch as th

from ai.patched_ppo import PatchedMaskablePPO
from ai.pointer_policy import PointerMaskablePolicy
from ai.spatial_extractor import SpatialCombinedExtractor
from tests.unit.ai.test_critic_warmup import _TABLE_ID, _run_one_update
from tests.unit.ai.test_pointer_head import _ToyEnv

#: 4 mini-lots par update : le verrou lit l'état au mini-lot 2 (et 3), pas avant — voir la
#: docstring de `_SavedActivationsTracker`.
_N_STEPS, _BATCH = 16, 4


def _production_model(n_warmup: int, device: str = "cpu") -> PatchedMaskablePPO:
    """Le VRAI chemin : `PointerMaskablePolicy` + `SpatialCombinedExtractor`, 4 mini-lots."""
    model = PatchedMaskablePPO(
        PointerMaskablePolicy, _ToyEnv(), n_steps=_N_STEPS, batch_size=_BATCH, n_epochs=1,
        seed=0, device=device, verbose=0,
        # `ent_coef` non nul : SB3 le met à 0 par défaut, et `diag/grad_norm_entropy_mb0`
        # vaudrait alors 0 quel que soit le code — le contrôle « > 0 » serait vacant.
        ent_coef=0.01,
        policy_kwargs={
            "net_arch": [16, 16],
            "features_extractor_class": SpatialCombinedExtractor,
            "features_extractor_kwargs": {"cnn_features": 8},
        },
        value_warmup_updates=n_warmup,
    )
    model.value_warmup_contract_id = _TABLE_ID
    return model


class _SavedActivationsTracker:
    """Suit les activations sauvées pour le backward, par mini-lot.

    `pack` reçoit chaque tenseur qu'un nœud du graphe garde pour son backward ; il rend une vue
    DÉTACHÉE de ce tenseur (même stockage, sans `grad_fn`) que le nœud tient alors, et en note
    une référence faible sous l'index du mini-lot courant. Rendre le tenseur lui-même serait
    faux : un nœud qui sauve sa propre sortie (`tanh`, `softmax`, `logsumexp`) tiendrait alors
    un objet dont `grad_fn` est ce même nœud — cycle C++ jamais libéré, et l'instrument
    fabriquerait la fuite qu'il mesure (11 tenseurs par mini-lot survivant à tout, mesuré hors
    `train()`). Les FEUILLES sont ignorées : paramètres et observations du rollout survivent
    légitimement, seuls les intermédiaires (activations) disent si un graphe est retenu.

    `alive(k)` compte, MAINTENANT, les activations du mini-lot `k` encore vivantes. Lu à
    l'entrée du mini-lot `k + 2` : au mini-lot `k + 1`, les locaux de `train()` (`policy_loss`,
    `ratio`…) tiennent encore le graphe de `k` jusqu'à leur réaffectation — c'est normal et
    borné à UN mini-lot. Ce qui est interdit, c'est la survie au-delà.
    """

    def __init__(self) -> None:
        self.minibatch = -1
        self._refs: Dict[int, List[weakref.ref]] = {}

    def pack(self, t: th.Tensor) -> th.Tensor:
        if t.is_leaf:
            return t
        kept = t.detach()
        self._refs.setdefault(self.minibatch, []).append(weakref.ref(kept))
        return kept

    @staticmethod
    def unpack(t: th.Tensor) -> th.Tensor:
        return t

    def alive(self, k: int) -> int:
        return sum(1 for r in self._refs.get(k, ()) if r() is not None)

    def seen(self, k: int) -> int:
        return len(self._refs.get(k, ()))


def _warmup_update_tracking_saved_activations(
    model: PatchedMaskablePPO,
) -> tuple[Dict[int, int], Dict[int, int], Dict[str, float]]:
    """Une update ; rend (vivantes du mini-lot k-2 à l'entrée de k, sauvées par mini-lot, logs)."""
    tracker = _SavedActivationsTracker()
    alive_two_back: Dict[int, int] = {}
    policy = model.policy
    original_evaluate = policy.evaluate_actions

    def _evaluate(obs: Any, actions: th.Tensor, action_masks: Any = None):
        tracker.minibatch += 1
        k = tracker.minibatch
        if k >= 2:
            alive_two_back[k] = tracker.alive(k - 2)
        return original_evaluate(obs, actions, action_masks=action_masks)

    policy.evaluate_actions = _evaluate  # type: ignore[method-assign]
    original_train = model.train

    def _train_with_hooks() -> None:
        with th.autograd.graph.saved_tensors_hooks(tracker.pack, tracker.unpack):
            original_train()

    model.train = _train_with_hooks  # type: ignore[method-assign]
    try:
        recorded = _run_one_update(model)
    finally:
        del policy.evaluate_actions
    n_minibatches = tracker.minibatch + 1
    assert n_minibatches == _N_STEPS // _BATCH, f"{n_minibatches} mini-lots, 4 attendus"
    seen = {k: tracker.seen(k) for k in range(n_minibatches)}
    return alive_two_back, seen, recorded


def test_en_echauffement_les_activations_d_un_mini_lot_ne_survivent_pas_au_suivant() -> None:
    """VERROU. Réintroduire `pg_losses_t.append(policy_loss)` (sans `detach`) avec le graphe de
    la politique attaché — c'est-à-dire retirer le détachement de `log_prob`/`entropy` en tête
    de boucle dans `PatchedMaskablePPO.train` — fait passer ce test au ROUGE : les activations
    du mini-lot 0 sont encore vivantes à l'entrée du mini-lot 2, celles du 1 à l'entrée du 3.
    CONTRÔLE NON VACANT : chaque mini-lot a bien sauvé des activations (`seen > 0`), sinon un
    hook non branché rendrait `alive == 0` sans rien prouver.
    """
    model = _production_model(n_warmup=1)
    alive_two_back, seen, recorded = _warmup_update_tracking_saved_activations(model)

    assert recorded["train/value_warmup_active"] == pytest.approx(1.0), "pas en échauffement"
    assert all(n > 0 for n in seen.values()), f"aucune activation suivie : {seen}"
    assert alive_two_back == {2: 0, 3: 0}, (
        f"activations retenues au-delà d'un mini-lot pendant l'échauffement : {alive_two_back} "
        f"(sauvées par mini-lot : {seen})"
    )


def test_hors_echauffement_le_backward_complet_libere_deja_les_activations() -> None:
    """Témoin : sans échauffement, la loss complète traverse toute la branche politique et le
    backward libère tout — le même instrument rend 0, ce qui prouve qu'il ne compte pas des
    feuilles ou des tenseurs légitimement persistants."""
    model = _production_model(n_warmup=0)
    alive_two_back, seen, recorded = _warmup_update_tracking_saved_activations(model)

    assert recorded["train/value_warmup_active"] == pytest.approx(0.0)
    assert all(n > 0 for n in seen.values()), f"aucune activation suivie : {seen}"
    assert alive_two_back == {2: 0, 3: 0}, alive_two_back


def test_le_diagnostic_de_gradient_du_mini_lot_0_survit_au_detachement() -> None:
    """Le détachement épargne le mini-lot du diagnostic : `diag/grad_norm_policy_mb0` reste
    calculé en échauffement (fini, non nul). Détacher aussi ce mini-lot casserait le backward
    du diagnostic (« does not require grad ») ou rendrait NaN — et la lecture d'acceptation
    du premier rollout (`plafonnement_p1.md`) lit précisément cette courbe."""
    model = _production_model(n_warmup=1)
    recorded = _run_one_update(model)

    assert recorded["train/value_warmup_active"] == pytest.approx(1.0)
    for tag in ("diag/grad_norm_policy_mb0", "diag/grad_norm_entropy_mb0", "diag/grad_norm_value_mb0"):
        assert math.isfinite(recorded[tag]) and recorded[tag] > 0.0, f"{tag} = {recorded[tag]!r}"
    # Les scalaires de la branche détachée sont publiés, finis : un forward identique, sans graphe.
    for tag in ("train/entropy_loss", "train/policy_gradient_loss", "train/clip_fraction", "train/approx_kl"):
        assert math.isfinite(recorded[tag]), f"{tag} = {recorded[tag]!r}"


@pytest.mark.skipif(not th.cuda.is_available(), reason="métrique CUDA : carte requise")
def test_les_metriques_memoire_cuda_sont_publiees_par_update() -> None:
    """`train/cuda_peak_allocated_gib` (pic de CETTE update) et `train/cuda_reserved_gib`
    (réservation de l'allocateur en fin d'update) : la courbe qui manquait le 2026-09-16."""
    model = _production_model(n_warmup=0, device="cuda")
    recorded = _run_one_update(model)

    peak, reserved = recorded["train/cuda_peak_allocated_gib"], recorded["train/cuda_reserved_gib"]
    assert 0.0 < peak <= reserved, (peak, reserved)


def test_sur_cpu_aucune_metrique_cuda_n_est_publiee() -> None:
    model = _production_model(n_warmup=0)
    recorded = _run_one_update(model)
    assert "train/cuda_peak_allocated_gib" not in recorded
    assert "train/cuda_reserved_gib" not in recorded
