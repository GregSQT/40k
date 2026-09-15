"""Tests — tête Q (S14, plafonnement_p1.md §9.5) : avantage attendu à la place du GAE.

Ce que la tête doit garantir, chacun verrouillé ici :
- même structure que les têtes de politique (noms et formes), enregistrée EN DERNIER ;
- fraîche, elle rend un avantage nul pour toute action ; `evaluate_actions_q` rend l'avantage
  de l'action JOUÉE CENTRÉ sous π (`center_under_policy` : Σ_a π·A_c = 0 par état, l'offset
  par état que la tête absorbait — 98 % de Var(A) mesuré le 2026-09-15 — est retiré) et
  l'offset lui-même, et laisse (values, log_prob, entropy) identiques à `evaluate_actions` ;
- tags `adv_q_offset_abs_mean`, `q_loss_mb0`, `value_loss_mb0` (mini-lot 0 avant tout pas :
  la comparaison hors échantillon de la règle §5.13) ;
- un zip sauvé SANS la tête charge PAR TOUS LES CHEMINS (`MaskablePPO.load` nu compris : PvE,
  workers d'évaluation, pool) : anciens poids identiques, états Adam alignés sur les mêmes rangs,
  tête à zéro ; toute autre différence de `state_dict` reste refusée ;
- « tête fraîche » se lit sur le CONTENU (`is_untrained`, couches de sortie exactement nulles),
  pas sur la provenance : un zip entraîné en `gae` après S14 porte une tête jamais entraînée ;
- `q_head` : l'acteur reçoit `adv.detach()` — la tête ne reçoit de gradient que de sa perte —,
  pendant l'échauffement la tête apprend avec V, politique figée ; hors échauffement la
  politique bouge ; `gae` reste bit à bit le comportement antérieur (tête immobile) ;
- les clés sont validées ensemble, en `--new` comme en `--append`, et une tête fraîche exige
  l'échauffement.
"""
from __future__ import annotations

from typing import Any, cast

import numpy as np
import pytest
import torch as th
from sb3_contrib import MaskablePPO
from stable_baselines3.common.save_util import load_from_zip_file, save_to_zip_file

import ai.train as train_module
from ai.patched_ppo import PatchedMaskablePPO, check_advantage_source, check_q_coef
from ai.pointer_policy import (
    ADV_HEADS_PREFIX,
    HeadNets,
    PointerHeadNets,
    PointerMaskablePolicy,
    center_under_policy,
    extend_optimizer_state,
    masked_probs,
)
from ai.spatial_extractor import SpatialCombinedExtractor
from tests.unit.ai.test_critic_warmup import _run_one_update, _TABLE_ID
from tests.unit.ai.test_gradient_norm_is_pre_clip import _TinyMaskedEnv
from engine.macro_intents import TOTAL_ACTION_SIZE
from tests.unit.ai.test_pointer_head import _ToyEnv, _zero_obs

_HEAD_NAMES = tuple(HeadNets.__annotations__)


def _model(**kwargs: Any) -> PatchedMaskablePPO:
    """Le VRAI chemin : `PointerMaskablePolicy` + `SpatialCombinedExtractor`, petit."""
    th.manual_seed(7)
    model = PatchedMaskablePPO(
        PointerMaskablePolicy, _ToyEnv(), n_steps=8, batch_size=8, n_epochs=1, seed=0,
        device="cpu", verbose=0,
        policy_kwargs={
            "net_arch": [16, 16],
            "features_extractor_class": SpatialCombinedExtractor,
            "features_extractor_kwargs": {"cnn_features": 8},
        },
        **kwargs,
    )
    model.value_warmup_contract_id = _TABLE_ID
    return model


def _policy(model: PatchedMaskablePPO) -> PointerMaskablePolicy:
    """La politique de production, typée : le montage n'en construit pas d'autre."""
    assert isinstance(model.policy, PointerMaskablePolicy), type(model.policy).__name__
    return model.policy


def _params_of(path: str) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """(data, params, pytorch_variables) d'un zip, `params` lu comme des state_dicts imbriqués."""
    data, params, pytorch_variables = load_from_zip_file(path, device="cpu")
    assert params is not None and data is not None
    return dict(data), cast(dict[str, Any], dict(params)), pytorch_variables


def _obs_tensor(policy: PointerMaskablePolicy, batch: int = 3) -> dict[str, th.Tensor]:
    obs_t, _ = policy.obs_to_tensor(_zero_obs(batch))
    assert isinstance(obs_t, dict)
    return cast(dict[str, th.Tensor], obs_t)


# --- structure ----------------------------------------------------------------------------------


def test_la_tete_q_a_les_memes_tetes_que_la_politique_noms_et_formes() -> None:
    """VERROU du miroir `_build_head_nets` ↔ `_build_mlp_extractor` : une tête ajoutée d'un côté
    seulement rend ce test rouge, avant qu'un assemblage lève sur un attribut absent."""
    pol = _policy(_model())
    assert isinstance(pol.adv_heads, PointerHeadNets)
    for name in _HEAD_NAMES:
        mine = getattr(pol, name)
        theirs = getattr(pol.adv_heads, name)
        assert type(mine) is type(theirs), name
        assert mine.weight.shape == theirs.weight.shape, name
        assert mine.bias.shape == theirs.bias.shape, name
    adv_param_names = {n.split(".")[0] for n, _ in pol.adv_heads.named_parameters()}
    assert adv_param_names == set(_HEAD_NAMES)


def test_les_parametres_de_la_tete_q_sont_les_derniers_et_l_optimiseur_suit_cet_ordre() -> None:
    """Sans quoi un zip antérieur alignerait ses états Adam sur les mauvais paramètres."""
    pol = _policy(_model())
    names = [n for n, _ in pol.named_parameters()]
    first_adv = next(i for i, n in enumerate(names) if n.startswith(ADV_HEADS_PREFIX))
    assert all(n.startswith(ADV_HEADS_PREFIX) for n in names[first_adv:])
    assert not any(n.startswith(ADV_HEADS_PREFIX) for n in names[:first_adv])
    assert names[first_adv - 1].startswith("value_net."), names[first_adv - 1]
    optimizer_params = pol.optimizer.param_groups[0]["params"]
    assert [id(p) for p in optimizer_params] == [id(p) for _, p in pol.named_parameters()]


def test_une_tete_fraiche_rend_un_avantage_nul_pour_toute_action() -> None:
    pol = _policy(_model())
    pol.set_training_mode(False)
    obs_t = _obs_tensor(pol)
    with th.no_grad():
        feats = pol._split_features(obs_t)
        _, latent_vf = pol.mlp_extractor(feats.trunk)
        adv_all = pol.expected_advantages(latent_vf, feats)
    assert adv_all.shape == (3, TOTAL_ACTION_SIZE)
    assert th.equal(adv_all, th.zeros_like(adv_all))


# --- centrage sous π ----------------------------------------------------------------------------


def test_center_under_policy_annule_la_moyenne_sous_pi_par_etat() -> None:
    """Σ_a π·A_c = 0 ligne par ligne, pour des poids quelconques ; l'offset rendu est Σ_a π·A."""
    g = th.Generator().manual_seed(3)
    adv_all = th.randn(4, 9, generator=g, dtype=th.float64)
    probs = th.softmax(th.randn(4, 9, generator=g, dtype=th.float64), dim=1)
    adv_c, offset = center_under_policy(adv_all, probs)
    assert adv_c.shape == adv_all.shape and offset.shape == (4,)
    assert th.allclose((probs * adv_c).sum(dim=1), th.zeros(4, dtype=th.float64), atol=1e-12)
    assert th.allclose(offset, (probs * adv_all).sum(dim=1))
    assert not th.allclose(offset, th.zeros(4, dtype=th.float64)), "VERT VACANT : offset nul"


def test_center_under_policy_est_invariant_a_une_constante_par_etat() -> None:
    """`(V − c) + (A + c)` : la constante par état que la tête absorbait est retirée exactement."""
    g = th.Generator().manual_seed(5)
    adv_all = th.randn(3, 7, generator=g, dtype=th.float64)
    probs = th.softmax(th.randn(3, 7, generator=g, dtype=th.float64), dim=1)
    c = th.tensor([[10.0], [-3.5], [0.25]], dtype=th.float64)
    adv_c, offset = center_under_policy(adv_all, probs)
    adv_c_shifted, offset_shifted = center_under_policy(adv_all + c, probs)
    assert th.allclose(adv_c, adv_c_shifted, atol=1e-12)
    assert th.allclose(offset_shifted, offset + c.squeeze(1))


def test_center_under_policy_ignore_les_colonnes_illegales() -> None:
    """Probs nulles hors légales : la valeur de A sur une action illégale ne change rien."""
    probs = th.tensor([[0.5, 0.0, 0.5], [0.0, 1.0, 0.0]], dtype=th.float64)
    adv_all = th.tensor([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=th.float64)
    adv_all_garbage = adv_all.clone()
    adv_all_garbage[0, 1] = 1e6
    adv_all_garbage[1, 0] = -1e6
    adv_all_garbage[1, 2] = 1e6
    _, offset = center_under_policy(adv_all, probs)
    _, offset_garbage = center_under_policy(adv_all_garbage, probs)
    assert th.equal(offset, th.tensor([2.0, 5.0], dtype=th.float64))
    assert th.equal(offset_garbage, offset)


def test_center_under_policy_refuse_des_formes_differentes() -> None:
    with pytest.raises(ValueError, match="formes"):
        center_under_policy(th.zeros(2, 5), th.zeros(2, 4))


def test_evaluate_actions_q_rend_l_avantage_centre_de_l_action_jouee_sans_changer_le_reste() -> None:
    """`adv` = A_c(s, a_t) avec A_c centré sous la π MASQUÉE de la politique ; `offset` = Σ π·A
    brut ; (values, log_prob, entropy) identiques à `evaluate_actions`."""
    pol = _policy(_model())
    pol.set_training_mode(False)
    # Poids NON nuls sur la tête, sinon l'avantage vaut zéro partout et rien ne se prouve.
    with th.no_grad():
        for p in pol.adv_heads.parameters():
            p.normal_()
    obs_t = _obs_tensor(pol)
    actions = th.tensor([0, 1024, 1025 + 2])
    masks = np.ones((3, TOTAL_ACTION_SIZE), dtype=bool)
    masks[1, 1030:] = False  # un état partiellement masqué : π nulle sur ces colonnes
    with th.no_grad():
        values, log_prob, entropy, adv, offset = pol.evaluate_actions_q(obs_t, actions, masks)
        values_ref, log_prob_ref, entropy_ref = pol.evaluate_actions(
            cast(Any, obs_t), actions, cast(Any, masks)
        )
        feats = pol._split_features(obs_t)
        latent_pi, latent_vf = pol.mlp_extractor(feats.trunk)
        adv_all = pol.expected_advantages(latent_vf, feats)
        probs = masked_probs(pol._distribution_from(latent_pi, feats, masks))
    assert th.equal(values, values_ref)
    assert th.equal(log_prob, log_prob_ref)
    assert entropy is not None and entropy_ref is not None and th.equal(entropy, entropy_ref)
    assert adv.shape == (3,) and offset.shape == (3,)
    assert th.equal(probs[1, 1030:], th.zeros_like(probs[1, 1030:])), "VERT VACANT : masque sans effet"
    expected_offset = (probs * adv_all).sum(dim=1)
    assert th.allclose(offset, expected_offset)
    raw = th.stack([adv_all[i, int(a)] for i, a in enumerate(actions)])
    assert th.allclose(adv, raw - expected_offset)
    assert not th.allclose(adv, raw), "VERT VACANT : centrage sans effet (offset nul)"
    assert not th.equal(adv, th.zeros_like(adv)), "VERT VACANT : avantages tous nuls"


# --- chargement d'un zip antérieur ------------------------------------------------------------


def _save_without_adv_heads(model: PatchedMaskablePPO, path: str) -> None:
    """Fabrique un zip « d'avant la tête Q » : même modèle, clés `adv_heads.*` et rangs Adam en moins."""
    tmp = path + ".full.zip"
    model.save(tmp)
    data, params, pytorch_variables = _params_of(tmp)
    policy_state = {k: v for k, v in params["policy"].items() if not k.startswith(ADV_HEADS_PREFIX)}
    # Rangs Adam = PARAMÈTRES (pas les entrées du state_dict, qui compte aussi les buffers
    # d'`EntityRunningNorm`) : ceux de la politique hors tête Q.
    n_old = sum(1 for n, _ in _policy(model).named_parameters() if not n.startswith(ADV_HEADS_PREFIX))
    optimizer_state = params["policy.optimizer"]
    old_ranks = list(range(n_old))
    optimizer_state = {
        "state": {r: v for r, v in optimizer_state["state"].items() if r < n_old},
        "param_groups": [dict(optimizer_state["param_groups"][0], params=old_ranks)],
    }
    assert len(optimizer_state["param_groups"][0]["params"]) == n_old
    save_to_zip_file(
        path, data=data, params={"policy": policy_state, "policy.optimizer": optimizer_state},
        pytorch_variables=pytorch_variables,
    )


def test_un_zip_sans_tete_q_charge_avec_poids_et_etats_adam_alignes(tmp_path) -> None:
    model = _model()
    _run_one_update(model)  # un pas d'Adam : des états `exp_avg` existent pour chaque rang
    path = str(tmp_path / "old.zip")
    _save_without_adv_heads(model, path)
    before = {n: p.detach().clone() for n, p in _policy(model).named_parameters()}
    old_state = _policy(model).optimizer.state_dict()["state"]
    n_old = len([n for n in before if not n.startswith(ADV_HEADS_PREFIX)])
    assert n_old < len(before), "VERT VACANT : la tête Q n'ajoute aucun paramètre"
    assert set(old_state) >= set(range(n_old)), "VERT VACANT : aucun état Adam à aligner"

    loaded = PatchedMaskablePPO.load(path, env=_ToyEnv(), device="cpu")

    assert _policy(loaded).adv_heads.is_untrained(), "tête absente du zip : elle doit rester à zéro"
    for n, p in _policy(loaded).named_parameters():
        if n.startswith(ADV_HEADS_PREFIX):
            continue
        assert th.equal(before[n], p.detach()), n
    new_state = _policy(loaded).optimizer.state_dict()["state"]
    assert set(new_state) == set(range(n_old)), "rangs Adam : les anciens seulement, aucun pour la tête"
    for rank in range(n_old):
        assert th.equal(old_state[rank]["exp_avg"], new_state[rank]["exp_avg"]), rank
    ranks = _policy(loaded).optimizer.param_groups[0]["params"]
    assert len(ranks) == len(list(_policy(loaded).parameters()))
    # Le modèle rechargé s'entraîne : Adam a bien reçu un groupe complet.
    _run_one_update(loaded)


def test_un_zip_complet_charge_par_le_chemin_sb3_et_n_est_pas_fraiche(tmp_path) -> None:
    """Tête entraînée (un pas d'Adam en `q_head`) : le zip la porte, le modèle rechargé la lit
    telle quelle et `is_untrained()` est faux — aucun échauffement n'est exigé."""
    model = _model(advantage_source="q_head", q_coef=0.5, value_warmup_updates=1)
    _run_one_update(model)
    assert not _policy(model).adv_heads.is_untrained(), "VERT VACANT : la tête n'a pas appris"
    path = str(tmp_path / "full.zip")
    model.save(path)
    loaded = PatchedMaskablePPO.load(path, env=_ToyEnv(), device="cpu")
    assert loaded.uses_q_head and loaded.adv_heads_untrained is False
    for (n, p), (m, q) in zip(_policy(model).named_parameters(), _policy(loaded).named_parameters()):
        assert n == m and th.equal(p.detach(), q.detach()), n


def test_un_zip_sans_tete_q_charge_par_maskable_ppo_nu(tmp_path) -> None:
    """Finding de review du 2026-09-15 : `MaskablePPO.load` NU (engine/pve_controller.py:115,
    ai/bot_evaluation.py:982 et :1011, snapshots du pool) ne passe pas par `PatchedMaskablePPO`.
    La tolérance vit donc dans la politique (`load_state_dict`) et dans son optimiseur
    (`lenient_optimizer_class`), pas dans le modèle. Mesuré avant correction sur
    `model_ArmageddonAgent_x1.zip` : `RuntimeError: Missing key(s) in state_dict: "adv_heads…"`."""
    model = _model()
    _run_one_update(model)
    path = str(tmp_path / "old.zip")
    _save_without_adv_heads(model, path)
    before = {n: p.detach().clone() for n, p in _policy(model).named_parameters()}

    loaded = MaskablePPO.load(path, env=_ToyEnv(), device="cpu")

    assert type(loaded) is MaskablePPO, "VERT VACANT : le chemin testé doit être le chemin nu"
    policy = loaded.policy
    assert isinstance(policy, PointerMaskablePolicy)
    assert policy.adv_heads.is_untrained()
    for n, p in policy.named_parameters():
        if not n.startswith(ADV_HEADS_PREFIX):
            assert th.equal(before[n], p.detach()), n
    assert len(policy.optimizer.param_groups[0]["params"]) == len(list(policy.parameters()))
    # Le chemin nu joue : une prédiction déterministe sur l'observation nulle.
    action, _ = loaded.predict(_zero_obs(1), deterministic=True)
    assert action.shape == (1,)


def test_une_autre_difference_de_state_dict_reste_refusee(tmp_path) -> None:
    """Le chemin lenient ne couvre QUE la tête absente : un `value_net` manquant lève encore."""
    model = _model()
    path = str(tmp_path / "broken.zip")
    _save_without_adv_heads(model, path)
    data, params, pytorch_variables = _params_of(path)
    params["policy"].pop("value_net.bias")
    save_to_zip_file(path, data=data, params=params, pytorch_variables=pytorch_variables)
    with pytest.raises(RuntimeError, match="value_net.bias"):
        PatchedMaskablePPO.load(path, env=_ToyEnv(), device="cpu")
    with pytest.raises(RuntimeError, match="value_net.bias"):
        MaskablePPO.load(path, env=_ToyEnv(), device="cpu")


def test_extend_optimizer_state_refuse_un_etat_inaligne() -> None:
    with pytest.raises(ValueError, match="inaligne"):
        extend_optimizer_state({"state": {}, "param_groups": [{"params": [0, 2]}]}, 5)
    with pytest.raises(ValueError, match="inaligne"):
        extend_optimizer_state({"state": {}, "param_groups": [{"params": [0, 1, 2]}]}, 2)
    with pytest.raises(ValueError, match="groupe"):
        extend_optimizer_state({"state": {}, "param_groups": []}, 2)
    ext = extend_optimizer_state({"state": {0: {"x": 1}}, "param_groups": [{"params": [0, 1], "lr": 1.0}]}, 4)
    assert ext["param_groups"][0]["params"] == [0, 1, 2, 3]
    assert ext["param_groups"][0]["lr"] == 1.0
    assert ext["state"] == {0: {"x": 1}}


# --- entraînement -------------------------------------------------------------------------------

_CRITIC_AND_Q_PREFIXES = ("mlp_extractor.value_net.", "value_net.", ADV_HEADS_PREFIX)


def test_pendant_l_echauffement_la_tete_q_apprend_avec_v_et_la_politique_est_figee() -> None:
    model = _model(advantage_source="q_head", q_coef=0.5, value_warmup_updates=1)
    pol = _policy(model)
    before = {n: p.detach().clone() for n, p in pol.named_parameters()}

    recorded = _run_one_update(model)

    moved = sorted(n for n, p in pol.named_parameters() if not th.equal(before[n], p.detach()))
    assert any(n.startswith(ADV_HEADS_PREFIX) for n in moved), "la tête Q n'a pas appris pendant l'échauffement"
    assert any(n.startswith("value_net.") for n in moved), "V n'a pas appris : l'update ne prouve rien"
    leaked = [n for n in moved if not n.startswith(_CRITIC_AND_Q_PREFIXES)]
    assert not leaked, f"hors critic et tête Q, des paramètres ont bougé pendant l'échauffement : {leaked}"
    assert recorded["train/value_warmup_active"] == pytest.approx(1.0)
    assert recorded["train/advantage_source_q"] == pytest.approx(1.0)
    assert np.isfinite(recorded["train/q_loss"])


def test_hors_echauffement_la_politique_bouge_sous_l_avantage_q() -> None:
    model = _model(advantage_source="q_head", q_coef=0.5, value_warmup_updates=0)
    pol = _policy(model)
    # Tête non nulle : à zéro, l'avantage normalisé est 0/eps = 0 et la politique n'aurait aucun
    # gradient de performance — seul l'entropie la ferait bouger, ce qui ne prouverait rien.
    with th.no_grad():
        for p in pol.adv_heads.parameters():
            p.normal_(std=0.1)
    pi_before = [p.detach().clone() for p in pol.query_net.parameters()]
    recorded = _run_one_update(model)
    assert not all(th.equal(a, b) for a, b in zip(pi_before, pol.query_net.parameters()))
    assert np.isfinite(recorded["train/q_loss"]) and np.isfinite(recorded["train/adv_q_abs_mean"])
    assert recorded["train/adv_q_abs_mean"] > 0.0
    assert np.isfinite(recorded["diag/grad_norm_q_mb0"])


def test_les_tags_du_centrage_et_du_mini_lot_0_sont_publies_en_q_head() -> None:
    """`adv_q_offset_abs_mean` (offset retiré, > 0 sur une tête non nulle), `q_loss_mb0` et
    `value_loss_mb0` (premier mini-lot AVANT tout pas d'Adam, V brute). Sur ce mini-lot,
    `q_loss_mb0 − value_loss_mb0 = E[A_c² − 2·A_c·R]` : recalculé ici à la main sur le buffer
    avec les poids d'AVANT l'update, pour prouver que le tag est bien la mesure pré-update."""
    model = _model(advantage_source="q_head", q_coef=0.5, value_warmup_updates=0)
    pol = _policy(model)
    with th.no_grad():
        for p in pol.adv_heads.parameters():
            p.normal_(std=0.1)
    recorded = _run_one_update(model)
    assert np.isfinite(recorded["train/adv_q_offset_abs_mean"])
    assert recorded["train/adv_q_offset_abs_mean"] > 0.0, "VERT VACANT : offset nul sur une tête non nulle"
    assert np.isfinite(recorded["train/q_loss_mb0"]) and np.isfinite(recorded["train/value_loss_mb0"])
    # n_steps = batch_size = 8, n_epochs = 1 : UN seul mini-lot, donc `train/q_loss` (moyenne
    # sur les mini-lots, calculée AVANT le pas) doit coïncider avec `q_loss_mb0` — et diverger
    # d'une mesure faite APRÈS l'update sur le même lot.
    assert recorded["train/q_loss"] == pytest.approx(recorded["train/q_loss_mb0"])
    pol.set_training_mode(False)
    buf = next(model.rollout_buffer.get(8))
    with th.no_grad():
        values, _, _, adv_c, _ = pol.evaluate_actions_q(
            cast(Any, buf.observations), buf.actions.long().flatten(), buf.action_masks
        )
        after = float(th.nn.functional.mse_loss(buf.returns, values.flatten() + adv_c))
    assert after != pytest.approx(recorded["train/q_loss_mb0"]), "VERT VACANT : l'update n'a rien changé"


def test_les_tags_du_centrage_et_du_mini_lot_0_sont_nan_en_gae_sauf_value_loss_mb0() -> None:
    recorded = _run_one_update(_model())
    assert np.isnan(recorded["train/adv_q_offset_abs_mean"])
    assert np.isnan(recorded["train/q_loss_mb0"])
    # V brute du mini-lot 0 existe sous toute source : une mesure valide n'est pas jetée.
    assert np.isfinite(recorded["train/value_loss_mb0"])


def test_la_tete_q_ne_recoit_de_gradient_que_de_sa_propre_perte() -> None:
    """VERROU du `detach` : l'acteur lit `adv.detach()`. Le diagnostic par terme fait un backward
    séparé pour chaque terme (policy, value, entropy, q) sur le mini-lot 0, puis un backward de
    la loss complète. Un hook sur un poids de la tête compte les backward qui l'atteignent :
    2 attendus (terme q + loss complète). Sans le `detach`, le terme policy l'atteint aussi → 3.
    """
    model = _model(advantage_source="q_head", q_coef=0.5, value_warmup_updates=0)
    pol = _policy(model)
    with th.no_grad():
        for p in pol.adv_heads.parameters():
            p.normal_(std=0.1)
    calls: list[int] = []
    pol.adv_heads.query_net.weight.register_hook(lambda g: calls.append(1))
    _run_one_update(model)
    assert len(calls) == 2, f"{len(calls)} backward ont atteint la tête Q (2 attendus : terme q + loss)"


def test_en_gae_la_tete_q_est_inerte_et_le_comportement_est_inchange() -> None:
    model = _model()  # advantage_source par défaut : gae
    pol = _policy(model)
    adv_before = [p.detach().clone() for p in pol.adv_heads.parameters()]
    recorded = _run_one_update(model)
    assert all(th.equal(a, b) for a, b in zip(adv_before, pol.adv_heads.parameters()))
    assert recorded["train/advantage_source_q"] == pytest.approx(0.0)
    assert np.isnan(recorded["train/q_loss"])
    assert np.isnan(recorded["diag/grad_norm_q_mb0"])


# --- clés et garde-fous -------------------------------------------------------------------------


def test_les_cles_sont_validees_ensemble() -> None:
    assert check_advantage_source("gae") == "gae"
    assert check_advantage_source("q_head") == "q_head"
    with pytest.raises(ValueError, match="advantage_source"):
        check_advantage_source("Q_head")
    assert check_q_coef(None, "gae") is None
    assert check_q_coef(0.25, "q_head") == 0.25
    with pytest.raises(ValueError, match="q_coef"):
        check_q_coef(None, "q_head")
    with pytest.raises(ValueError, match="q_coef"):
        check_q_coef(0.0, "q_head")
    with pytest.raises(ValueError, match="q_coef"):
        check_q_coef(True, "q_head")
    with pytest.raises(ValueError, match="q_coef"):
        check_q_coef(0.5, "gae")


def test_q_head_exige_une_politique_pointeur() -> None:
    with pytest.raises(TypeError, match="PointerMaskablePolicy"):
        PatchedMaskablePPO(
            "MlpPolicy", _TinyMaskedEnv(), n_steps=8, batch_size=4, n_epochs=1, seed=0,
            device="cpu", policy_kwargs={"net_arch": [8]},
            advantage_source="q_head", q_coef=0.5,
        )


def test_une_tete_fraiche_sans_echauffement_est_refusee_par_train_et_par_arm(tmp_path) -> None:
    model = _model()
    path = str(tmp_path / "old.zip")
    _save_without_adv_heads(model, path)
    loaded = PatchedMaskablePPO.load(path, env=_ToyEnv(), device="cpu")
    loaded.value_warmup_contract_id = _TABLE_ID
    train_module._apply_curriculum_model_params(
        loaded, {"advantage_source": "q_head", "q_coef": 0.5}, log=lambda *_: None
    )
    assert loaded.uses_q_head and loaded.adv_heads_untrained
    with pytest.raises(RuntimeError, match="value_warmup_updates"):
        _run_one_update(loaded)


def test_une_tete_presente_mais_jamais_entrainee_en_gae_est_fraiche(tmp_path) -> None:
    """Finding de review du 2026-09-15 : un zip entraîné en `gae` APRÈS S14 porte la tête (clés
    présentes) mais elle n'a reçu aucun gradient — ses avantages valent zéro partout. Lue par la
    provenance (clés absentes), elle passait pour entraînée : marqueur d'échauffement déjà posé
    → saut → `policy_loss ≡ 0`, seule l'entropie déplaçait la politique. Lue par le CONTENU, elle
    exige l'échauffement, et `arm_value_warmup` ne le saute jamais."""
    rewards = {"agent": {"base_actions": {"a": 1.0}}}
    fingerprint = train_module.reward_table_fingerprint(rewards, "agent")
    model = _model(value_warmup_updates=1)  # gae : la tête est présente, inerte
    _run_one_update(model)
    assert model.value_warmup_done_under == _TABLE_ID, "VERT VACANT : marqueur non posé"
    path = str(tmp_path / "gae.zip")
    model.save(path)
    saved_keys = set(_params_of(path)[1]["policy"])
    assert any(k.startswith(ADV_HEADS_PREFIX) for k in saved_keys), "VERT VACANT : le zip doit PORTER la tête"
    loaded = PatchedMaskablePPO.load(path, env=_ToyEnv(), device="cpu")
    train_module._apply_curriculum_model_params(
        loaded, {"advantage_source": "q_head", "q_coef": 0.5}, log=lambda *_: None
    )
    assert loaded.adv_heads_untrained, "tête présente mais à zéro : elle est fraîche"
    loaded.value_warmup_contract_id = _TABLE_ID
    with pytest.raises(RuntimeError, match="value_warmup_updates"):
        _run_one_update(loaded)
    # Marqueur de la table courante déjà posé : sans la lecture par le contenu, saut ; ici, jamais.
    loaded.value_warmup_done_under = fingerprint
    loaded.value_warmup_updates = 2
    messages: list[str] = []
    train_module.arm_value_warmup(
        loaded, {"value_warmup_updates": 2}, rewards, "agent", log=messages.append
    )
    assert loaded.value_warmup_updates == 2
    assert any("jamais entrainee" in m for m in messages)


def test_arm_value_warmup_exige_et_ne_saute_jamais_l_echauffement_d_une_tete_fraiche(tmp_path) -> None:
    rewards = {"agent": {"base_actions": {"a": 1.0}}}
    fingerprint = train_module.reward_table_fingerprint(rewards, "agent")
    model = _model()
    path = str(tmp_path / "old.zip")
    _save_without_adv_heads(model, path)
    loaded = PatchedMaskablePPO.load(path, env=_ToyEnv(), device="cpu")
    train_module._apply_curriculum_model_params(
        loaded, {"advantage_source": "q_head", "q_coef": 0.5}, log=lambda *_: None
    )
    with pytest.raises(ValueError, match="value_warmup_updates"):
        train_module.arm_value_warmup(loaded, {}, rewards, "agent", log=lambda *_: None)
    # Marqueur de CETTE table déjà posé : sans tête fraîche il y aurait saut ; avec, jamais.
    loaded.value_warmup_done_under = fingerprint
    loaded.value_warmup_updates = 3
    messages: list[str] = []
    train_module.arm_value_warmup(
        loaded, {"value_warmup_updates": 3}, rewards, "agent", log=messages.append
    )
    assert loaded.value_warmup_updates == 3
    assert any("jamais entrainee" in m for m in messages)


def test_apply_curriculum_valide_le_couple_de_cles_en_append() -> None:
    model = _model()
    with pytest.raises(ValueError, match="q_coef"):
        train_module._apply_curriculum_model_params(
            model, {"advantage_source": "q_head"}, log=lambda *_: None
        )
    with pytest.raises(ValueError, match="q_coef"):
        train_module._apply_curriculum_model_params(
            model, {"advantage_source": "gae", "q_coef": 0.5}, log=lambda *_: None
        )
    train_module._apply_curriculum_model_params(
        model, {"advantage_source": "q_head", "q_coef": 0.5}, log=lambda *_: None
    )
    assert model.advantage_source == "q_head" and model.q_coef == 0.5
    train_module._apply_curriculum_model_params(
        model, {"advantage_source": "gae"}, log=lambda *_: None
    )
    assert model.advantage_source == "gae" and model.q_coef is None


def test_les_cles_de_la_tete_q_voyagent_dans_le_zip(tmp_path) -> None:
    model = _model(advantage_source="q_head", q_coef=0.5)
    path = str(tmp_path / "q.zip")
    model.save(path)
    loaded = PatchedMaskablePPO.load(path, env=_ToyEnv(), device="cpu")
    assert loaded.advantage_source == "q_head" and loaded.q_coef == 0.5
    # La fraîcheur ne voyage pas comme un drapeau : elle se relit sur les poids.
    assert loaded.adv_heads_untrained is True
