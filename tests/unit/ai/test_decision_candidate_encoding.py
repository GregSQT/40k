"""Les candidats de décision doivent être DISCERNABLES par le réseau (V11 §9.3 P2).

Le moteur remplissait `decision_options_cont` depuis P3-4, mais `SpatialCombinedExtractor` ne
lisait que `decision_options_bin` : la clé continue n'apparaissait dans aucun de ses accès
d'observation, et son `decision_encoder` était dimensionné sur le seul bloc binaire. Mesuré avant
correction, deux candidats aux traits continus opposés sortaient à un écart d'embedding de
**exactement 0.0** — et comme `pointer_policy._point` score chaque candidat par un produit
scalaire nu, sans biais par slot, des embeddings égaux donnent des logits égaux : `CHOICE_0` et
`CHOICE_1` étaient un pile-ou-face que PPO ne pouvait pas apprendre.

Cinq types de décision sur neuf en dépendaient — `allocation_model` (à chaque blessure non
sauvegardée), `charge_placement` (à chaque charge réussie), `mortal_wounds_target` et les deux
décisions de Grot Orderly. Les quatre autres restaient apprenables par un autre canal :
`rule_choice` par le one-hot de l'effet accordé, `waaagh_call` / `fly_declaration` /
`ascent_declaration` par le bit `declines`.

Ce fichier verrouille le CANAL, au niveau du réseau. Que chaque type émette bien des traits
distincts est verrouillé côté moteur, dans les tests de chaque décision.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pytest
import torch

from ai.spatial_extractor import SpatialCombinedExtractor
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import (
    DECISION_OPTION_CONT_SIZE,
    MAX_DECISION_OPTIONS,
    decision_ctx_bin_index,
    decision_option_bin_index,
    decision_option_cont_index,
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


def _two_candidates(cont_0: Dict[str, float], cont_1: Dict[str, float]) -> Dict[str, torch.Tensor]:
    """Deux candidats PRÉSENTS, lignes binaires identiques, traits continus au choix.

    Lignes binaires identiques n'est pas un cas de laboratoire : c'est ce que posent les cinq
    types dont les candidats n'accordent aucun effet et ne renoncent à rien.
    """
    obs = _zero_obs()
    obs["decision_ctx_bin"][0, decision_ctx_bin_index("decision_pending")] = 1.0
    obs["decision_ctx_bin"][0, decision_ctx_bin_index("decision_type_allocation_model")] = 1.0
    present = decision_option_bin_index("present")
    for slot in (0, 1):
        obs["decision_options_bin"][0, slot, present] = 1.0
    for slot, values in ((0, cont_0), (1, cont_1)):
        for field, value in values.items():
            obs["decision_options_cont"][0, slot, decision_option_cont_index(field)] = value
    return obs


def _decision_embeddings(extractor: SpatialCombinedExtractor, obs) -> torch.Tensor:
    with torch.no_grad():
        out = extractor(obs)
    emb = out[0, extractor.decision_embeddings_slice()]
    return emb.reshape(extractor.n_decision_options, -1)


def test_extractor_reads_the_continuous_candidate_block():
    """La clé est EXIGÉE à la construction et entre dans la largeur de `decision_encoder`."""
    extractor = _extractor()
    assert extractor.decision_option_cont_dim == DECISION_OPTION_CONT_SIZE
    first_layer = next(m for m in extractor.decision_encoder.modules() if isinstance(m, torch.nn.Linear))
    assert first_layer.in_features == extractor.decision_option_dim + DECISION_OPTION_CONT_SIZE, (
        "le candidat entre par ses DEUX blocs ; sur le seul binaire, les traits continus "
        "n'atteignent aucun poids"
    )


def test_candidates_differing_only_by_continuous_traits_are_discernable():
    """Le VERROU : lignes binaires identiques + traits continus opposés -> embeddings distincts.

    ROUGE avant le câblage : écart mesuré à exactement 0.0.
    """
    extractor = _extractor()
    emb = _decision_embeddings(
        extractor,
        _two_candidates(
            {"role_tier_norm": 0.0, "dist_enemy_norm": 0.0},
            {"role_tier_norm": 1.0, "dist_enemy_norm": 1.0},
        ),
    )
    ecart = (emb[0] - emb[1]).abs().max().item()
    assert ecart > 1e-6, (
        f"deux candidats aux traits opposés restent indiscernables (écart {ecart}) : la tête "
        f"pointeur leur donnerait des logits égaux"
    )


def test_a_single_column_is_enough_to_separate_two_candidates():
    """Une SEULE colonne qui diffère suffit — chaque colonne du registre porte du gradient.

    Sans cela, un type dont une seule grandeur distingue les candidats (le quota d'un profil
    rendu, par exemple) resterait un tirage au sort malgré un bloc continu branché.
    """
    extractor = _extractor()
    for field in ("profile_value_norm", "target_wounded_hp_norm", "obj_dist_norm"):
        emb = _decision_embeddings(extractor, _two_candidates({field: 0.0}, {field: 1.0}))
        ecart = (emb[0] - emb[1]).abs().max().item()
        assert ecart > 1e-6, f"la colonne {field!r} ne sépare aucun candidat (écart {ecart})"


def test_absent_candidates_stay_null_whatever_their_continuous_row():
    """Un slot VIDE sort à zéro même si son rang continu est rempli.

    `_encode_masked` annule les entités absentes, et c'est la moitié qu'on oublie : sans elle un
    slot vide sortirait le BIAIS de l'encodeur, un vecteur constant non nul que les têtes
    pointeur scorent comme un candidat réel.
    """
    extractor = _extractor()
    obs = _two_candidates({"role_tier_norm": 0.5}, {"role_tier_norm": 0.9})
    # Le slot 2 n'est PAS présent, mais son rang continu porte des valeurs.
    obs["decision_options_cont"][0, 2, decision_option_cont_index("role_tier_norm")] = 1.0
    emb = _decision_embeddings(extractor, obs)
    assert torch.count_nonzero(emb[2]).item() == 0, (
        "un slot sans bit `present` doit rester nul, quel que soit son rang continu"
    )


def test_extractor_rejects_a_cardinality_mismatch_between_the_two_blocks():
    """Les deux blocs décrivent les MÊMES candidats : un désaccord de slots doit LEVER.

    Sans ce contrôle, rien ne lèverait — les deux tenseurs resteraient des rangs valides — et
    l'encodeur mélangerait les traits d'un candidat avec les drapeaux d'un autre.
    """
    import gymnasium as gym

    spaces = dict(squad_obs_space().spaces)
    spaces["decision_options_cont"] = gym.spaces.Box(
        low=-np.inf, high=np.inf,
        shape=(MAX_DECISION_OPTIONS + 1, DECISION_OPTION_CONT_SIZE), dtype=np.float32,
    )
    with pytest.raises(ValueError, match="decision_options_cont"):
        SpatialCombinedExtractor(gym.spaces.Dict(spaces), cnn_features=_CNN_FEATURES)


def test_extractor_requires_the_continuous_block():
    """La clé absente LÈVE à la construction, elle n'est pas silencieusement ignorée."""
    import gymnasium as gym

    spaces = dict(squad_obs_space().spaces)
    del spaces["decision_options_cont"]
    with pytest.raises(KeyError, match="decision_options_cont"):
        SpatialCombinedExtractor(gym.spaces.Dict(spaces), cnn_features=_CNN_FEATURES)
