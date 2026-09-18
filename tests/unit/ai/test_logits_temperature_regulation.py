"""Tests — température autorégulée (option 2, plafonnement_p1.md) : T ← f(entropie de π_T).

Ce que le régime doit garantir, chacun verrouillé ici :
- la loi : ``T' = clip(T · exp(gain · (cible − H)), t_min, t_max)`` — T monte sous la cible,
  descend au-dessus, ne bouge pas à la cible ni sur une entropie NaN, reste dans ses bornes ;
- la spec est validée UNE fois pour `--new` et `--append` : quatre clés obligatoires, toutes
  des flottants > 0, t_min < t_max ; `null` = T fixe (le régime S9) ;
- le câblage : en fin de `train`, T est réglée sur l'entropie mesurée et ÉCRITE SUR LA POLITIQUE
  (donc transportée aux workers), `train/logits_temperature` publie la T qui a produit l'update ;
  sans spec, T est bit à bit la constante d'avant ;
- régime de RUN : la spec ne voyage pas dans le zip, le profil la réapplique en `--append`.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

import ai.train as train_module
from ai.patched_ppo import PatchedMaskablePPO
from ai.pointer_policy import (
    LOGITS_TEMPERATURE_REGULATION_KEYS,
    check_logits_temperature_regulation,
    regulate_logits_temperature,
)
from tests.unit.ai.test_critic_warmup import _run_one_update
from tests.unit.ai.test_pointer_head import _ToyEnv
from tests.unit.ai.test_q_head import _model, _policy

SPEC = {"entropy_target": 1.0, "gain": 0.1, "t_min": 1.0, "t_max": 4.0}


# --- la loi ------------------------------------------------------------------------------------


def test_t_monte_sous_la_cible_descend_au_dessus_et_tient_a_la_cible() -> None:
    assert regulate_logits_temperature(2.0, 0.7, SPEC) == pytest.approx(2.0 * math.exp(0.03))
    assert regulate_logits_temperature(2.0, 1.3, SPEC) == pytest.approx(2.0 * math.exp(-0.03))
    assert regulate_logits_temperature(2.0, 1.0, SPEC) == pytest.approx(2.0)


def test_t_reste_dans_ses_bornes_et_ignore_une_entropie_nan() -> None:
    assert regulate_logits_temperature(3.99, 0.0, SPEC) == 4.0
    assert regulate_logits_temperature(1.01, 5.0, SPEC) == 1.0
    # T de départ hors bornes : ramenée dans les bornes au premier réglage.
    assert regulate_logits_temperature(8.0, 1.0, SPEC) == 4.0
    assert regulate_logits_temperature(2.0, float("nan"), SPEC) == 2.0


def test_la_loi_est_multiplicative() -> None:
    """Une même correction RELATIVE à T = 1 et à T = 3 : la loi agit sur log T."""
    r1 = regulate_logits_temperature(1.0, 0.5, SPEC) / 1.0
    r3 = regulate_logits_temperature(3.0, 0.5, SPEC) / 3.0
    assert r1 == pytest.approx(r3)


# --- la spec ------------------------------------------------------------------------------------


def test_null_est_le_regime_t_fixe_et_la_spec_complete_passe() -> None:
    assert check_logits_temperature_regulation(None) is None
    assert check_logits_temperature_regulation({**SPEC, "gain": 1}) == {**SPEC, "gain": 1.0}


@pytest.mark.parametrize(
    "bad",
    [
        2.0,
        "x",
        {},
        {k: v for k, v in SPEC.items() if k != "gain"},
        {**SPEC, "extra": 1.0},
        {**SPEC, "entropy_target": 0.0},
        {**SPEC, "gain": -0.1},
        {**SPEC, "t_min": True},
        {**SPEC, "t_min": 4.0, "t_max": 4.0},
        {**SPEC, "t_min": "1"},
    ],
)
def test_les_specs_invalides_sont_refusees(bad) -> None:
    with pytest.raises(ValueError, match="logits_temperature_regulation"):
        check_logits_temperature_regulation(bad)
    with pytest.raises(ValueError, match="logits_temperature_regulation"):
        _model(logits_temperature_regulation=bad)


def test_les_cles_de_la_spec_sont_celles_du_profil() -> None:
    assert LOGITS_TEMPERATURE_REGULATION_KEYS == ("entropy_target", "gain", "t_min", "t_max")


# --- le câblage ---------------------------------------------------------------------------------


def test_sans_spec_t_est_la_constante_et_le_tag_la_publie() -> None:
    model = _model(logits_temperature=2.0)
    recorded = _run_one_update(model)
    assert recorded["train/logits_temperature"] == 2.0
    assert model.logits_temperature == 2.0 and _policy(model).logits_temperature == 2.0


def test_apres_une_update_t_suit_l_entropie_mesuree_et_atteint_la_politique() -> None:
    """Cible haute (20 nats, hors d'atteinte : ln du nombre d'actions ≈ 7,2) : T monte
    d'exactement `exp(gain · (cible − H))` depuis la T qui a produit l'update, et la politique
    porte la nouvelle T pour la prochaine collecte."""
    spec = {**SPEC, "entropy_target": 20.0, "gain": 0.01}
    model = _model(logits_temperature=2.0, logits_temperature_regulation=spec)
    recorded = _run_one_update(model)
    assert recorded["train/logits_temperature"] == 2.0, "le tag publie la T qui a produit l'update"
    measured_entropy = -float(recorded["train/entropy_loss"])
    assert np.isfinite(measured_entropy) and 0.0 < measured_entropy < 20.0
    expected = min(4.0, 2.0 * math.exp(0.01 * (20.0 - measured_entropy)))
    assert expected < 4.0, "VERT VACANT : la borne haute masquerait la loi"
    assert model.logits_temperature == pytest.approx(expected)
    assert model.logits_temperature > 2.0, "VERT VACANT : T n'a pas bougé"
    assert _policy(model).logits_temperature == pytest.approx(expected)


def test_une_cible_basse_fait_descendre_t_jusqu_a_sa_borne() -> None:
    spec = {**SPEC, "entropy_target": 0.001, "gain": 50.0}
    model = _model(logits_temperature=2.0, logits_temperature_regulation=spec)
    _run_one_update(model)
    assert model.logits_temperature == 1.0
    assert _policy(model).logits_temperature == 1.0


# --- le régime ----------------------------------------------------------------------------------


def test_la_spec_ne_voyage_pas_dans_le_zip(tmp_path) -> None:
    model = _model(logits_temperature=2.0, logits_temperature_regulation=SPEC)
    path = str(tmp_path / "t.zip")
    model.save(path)
    loaded = PatchedMaskablePPO.load(path, env=_ToyEnv(), device="cpu")
    assert loaded.logits_temperature_regulation is None
    assert loaded.logits_temperature == 1.0


def test_le_profil_pose_la_spec_en_append_et_null_la_retire() -> None:
    model = _model()
    train_module._apply_curriculum_model_params(
        model, {"logits_temperature_regulation": SPEC}, log=lambda *_: None
    )
    assert model.logits_temperature_regulation == SPEC
    train_module._apply_curriculum_model_params(
        model, {"logits_temperature_regulation": None}, log=lambda *_: None
    )
    assert model.logits_temperature_regulation is None
    assert "logits_temperature_regulation" in train_module._PLAIN_CURRICULUM_KEYS
