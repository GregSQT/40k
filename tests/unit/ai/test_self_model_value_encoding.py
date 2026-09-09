"""P3-0 — la VALEUR d'une figurine doit atteindre la tête pointeur COHERENCY.

`COHERENCY_SLOT_i` désigne la ligne `i` de `self_models_*`. `SpatialCombinedExtractor` encode ce
bloc LIGNE PAR LIGNE (`self_model_encoder`, aucune interaction entre slots) et
`pointer_policy._point` score chaque ligne par un produit scalaire nu, sans biais de slot : tout
ce que la ligne ne porte pas est INATTEIGNABLE pour cette tête, même s'il vit ailleurs dans
l'observation. Le rôle d'allocation y vivait — mais AGRÉGÉ PAR TYPE — et les PV courants n'y
étaient plus depuis §9.4.

Ce fichier verrouille le CANAL, au niveau du réseau ; que le moteur remplisse ces colonnes est
verrouillé côté moteur (`tests/unit/engine/test_squad_obs_model_value_p3_0.py`).
"""

from __future__ import annotations

from typing import Dict

import torch

from ai.spatial_extractor import SpatialCombinedExtractor
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import (
    SELF_MODEL_BIN_SIZE,
    SELF_MODEL_CONT_SIZE,
    self_model_bin_index,
    self_model_cont_index,
)
from tests.unit.ai._fabriques import squad_obs_space

_CNN_FEATURES = 64


def _extractor() -> SpatialCombinedExtractor:
    torch.manual_seed(0)
    extractor = SpatialCombinedExtractor(squad_obs_space(), cnn_features=_CNN_FEATURES)
    extractor.eval()
    return extractor


def _zero_obs() -> Dict[str, torch.Tensor]:
    obs = {
        key: torch.zeros((1,) + tuple(shape), dtype=torch.float32)
        for key, shape in ObservationBuilder.squad_obs_shapes().items()
    }
    grid_space = squad_obs_space().spaces["grid"]
    assert grid_space.shape is not None
    obs["grid"] = torch.zeros((1,) + tuple(grid_space.shape), dtype=torch.float32)
    return obs


def _two_models(
    bin_0: Dict[str, float],
    bin_1: Dict[str, float],
    cont_0: Dict[str, float] | None = None,
    cont_1: Dict[str, float] | None = None,
) -> Dict[str, torch.Tensor]:
    """Deux figurines PRÉSENTES, à la MÊME position — seule leur valeur les sépare.

    Même position n'est pas un cas de laboratoire : `col_rel`/`row_rel` disent où retirer sans
    casser la cohérence, jamais ce que la figurine vaut, et deux figurines voisines d'un même
    rang de formation ont des positions quasi identiques.
    """
    obs = _zero_obs()
    present = self_model_bin_index("present")
    for slot, (bins, conts) in enumerate(((bin_0, cont_0), (bin_1, cont_1))):
        obs["self_models_bin"][0, slot, present] = 1.0
        for field, value in bins.items():
            obs["self_models_bin"][0, slot, self_model_bin_index(field)] = value
        for field, value in (conts or {}).items():
            obs["self_models_cont"][0, slot, self_model_cont_index(field)] = value
    return obs


def _self_model_embeddings(extractor: SpatialCombinedExtractor, obs) -> torch.Tensor:
    with torch.no_grad():
        out = extractor(obs)
    emb = out[0, extractor.self_model_embeddings_slice()]
    return emb.reshape(extractor.n_self_models, -1)


def test_encoder_width_covers_the_whole_row():
    """Les DEUX blocs entrent dans `self_model_encoder` : une colonne hors largeur n'existe pas."""
    extractor = _extractor()
    assert extractor.self_model_cont_dim == SELF_MODEL_CONT_SIZE
    assert extractor.self_model_bin_dim == SELF_MODEL_BIN_SIZE
    first_layer = next(
        m for m in extractor.self_model_encoder.modules() if isinstance(m, torch.nn.Linear)
    )
    assert first_layer.in_features == SELF_MODEL_CONT_SIZE + SELF_MODEL_BIN_SIZE


def test_role_separates_two_models_at_the_same_position():
    """Le VERROU : à position égale, le personnage attaché et une figurine de base diffèrent.

    ROUGE avant P3-0 : sans le one-hot de rôle dans la ligne, l'écart valait exactement 0.0 —
    mesuré en jeu sur 67 paires de figurines de valeur différente sur 67.
    """
    extractor = _extractor()
    emb = _self_model_embeddings(extractor, _two_models({"role_leader": 1.0}, {}))
    ecart = (emb[0] - emb[1]).abs().max().item()
    assert ecart > 1e-6, (
        f"le personnage attaché reste indiscernable d'une figurine de base (écart {ecart}) : "
        "la tête pointeur COHERENCY leur donne le même score"
    )


def test_each_role_and_the_wounded_bit_carry_gradient():
    """Chaque colonne ajoutée sépare À ELLE SEULE deux figurines — aucune n'est morte."""
    extractor = _extractor()
    for field in (
        "role_special_weapon", "role_sergeant", "role_support", "role_leader", "wounded",
    ):
        emb = _self_model_embeddings(extractor, _two_models({field: 1.0}, {}))
        ecart = (emb[0] - emb[1]).abs().max().item()
        assert ecart > 1e-6, f"la colonne {field!r} ne sépare aucune figurine (écart {ecart})"


def test_hp_ratio_separates_two_models():
    """Le DEGRÉ de dégâts atteint le réseau, pas seulement le fait d'être entamée."""
    extractor = _extractor()
    emb = _self_model_embeddings(
        extractor,
        _two_models(
            {"wounded": 1.0}, {"wounded": 1.0},
            cont_0={"hp_ratio": 0.2}, cont_1={"hp_ratio": 0.9},
        ),
    )
    ecart = (emb[0] - emb[1]).abs().max().item()
    assert ecart > 1e-6, f"deux figurines entamées à des degrés opposés restent égales ({ecart})"


def test_absent_models_stay_null_whatever_their_value():
    """Un slot VIDE sort à zéro même si ses colonnes de valeur sont remplies.

    Sans `_encode_masked`, il sortirait le BIAIS de l'encodeur — un vecteur constant non nul que
    la tête pointeur score comme une figurine réelle, donc un slot d'action jouable sur personne.
    """
    extractor = _extractor()
    obs = _two_models({"role_leader": 1.0}, {})
    obs["self_models_bin"][0, 2, self_model_bin_index("role_leader")] = 1.0
    obs["self_models_cont"][0, 2, self_model_cont_index("hp_ratio")] = 1.0
    emb = _self_model_embeddings(extractor, obs)
    assert torch.count_nonzero(emb[2]).item() == 0, (
        "un slot sans bit `present` doit rester nul, quelles que soient ses colonnes"
    )
