"""T-D — l'extracteur applique le MÊME encodeur aux deux camps, et la policy tourne.

`V11_entity_encoder_pointer.md` §4 T-D, critères d'acceptation :
- la politique se construit et fait un forward ;
- « un test vérifie que le MÊME encodeur d'arme est appliqué à une arme amie et à la même arme
  côté ennemi (partage effectif des poids, PAS deux modules) ».

Le partage de poids est le cœur du chantier : au format plat, chaque slot ennemi portait ses
propres poids de première couche (~226 k paramètres par slot, §1.8) et le réseau réapprenait
« évaluer un ennemi » cinq fois. Un test qui se contenterait de vérifier une égalité de sorties
passerait aussi avec deux modules initialisés à l'identique — d'où la contre-épreuve par
PERTURBATION : on modifie les poids de l'encodeur partagé et on exige que les DEUX camps bougent.

Le second point dur est la NORMALISATION : `VecNormalize` normalise élément par élément, ce qui
donnerait à chaque slot ses propres statistiques et annulerait le partage. `EntityRunningNorm`
estime une statistique par feature, commune à tous les slots — c'est ce que verrouille
`test_running_norm_statistics_are_shared_across_slots`.
"""

from __future__ import annotations

from typing import Dict

import gymnasium as gym
import numpy as np
import pytest
import torch

from ai.spatial_extractor import EntityRunningNorm, SpatialCombinedExtractor
from engine.observation_builder import ObservationBuilder
from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE


def _space() -> gym.spaces.Dict:
    spaces = {}
    for key, shape in ObservationBuilder.squad_obs_shapes().items():
        low, high = (-1.0, 1.0) if key.endswith("_bin") else (-np.inf, np.inf)
        spaces[key] = gym.spaces.Box(low=low, high=high, shape=shape, dtype=np.float32)
    spaces["grid"] = gym.spaces.Box(
        low=0.0, high=1.0, shape=(GRID_CHANNELS, GRID_SIZE, GRID_SIZE), dtype=np.float32
    )
    return gym.spaces.Dict(spaces)


def _zero_batch(space: gym.spaces.Dict, batch: int = 2) -> Dict[str, torch.Tensor]:
    out: Dict[str, torch.Tensor] = {}
    for key, sp in space.spaces.items():
        shape = sp.shape
        assert shape is not None
        out[key] = torch.zeros((batch,) + tuple(int(d) for d in shape), dtype=torch.float32)
    return out


@pytest.fixture
def extractor() -> SpatialCombinedExtractor:
    torch.manual_seed(0)
    return SpatialCombinedExtractor(_space(), cnn_features=32)


def test_features_layout_exposes_the_enemy_embeddings(extractor):
    """Contrat de sortie : [tronc | embeddings ennemis par slot] — la tranche est publique."""
    sl = extractor.enemy_embeddings_slice()
    assert sl.start == extractor.trunk_dim
    assert sl.stop == extractor.features_dim
    assert (sl.stop - sl.start) == extractor.n_enemy_slots * extractor.entity_dim


def test_forward_shape_and_finiteness(extractor):
    space = _space()
    obs = _zero_batch(space)
    obs["allies_bin"][:, 0, 0] = 1.0     # l'unité active est présente
    out = extractor(obs)
    assert out.shape == (2, extractor.features_dim)
    assert torch.isfinite(out).all()


def test_the_same_weapon_encoder_serves_both_sides(extractor):
    """Une arme amie et la MÊME arme ennemie produisent le même embedding — un seul module.

    Contre-épreuve : on PERTURBE les poids de `weapon_encoder`. Deux modules distincts
    initialisés à l'identique passeraient l'égalité, mais pas la perturbation.
    """
    space = _space()
    obs = _zero_batch(space, batch=1)
    obs["allies_bin"][:, 0, 0] = 1.0
    obs["enemies_bin"][:, 0, 0] = 1.0
    # Même profil d'arme des deux côtés, même slot de registre.
    profile_cont = torch.arange(1.0, extractor.weapon_cont_dim + 1.0).unsqueeze(0)
    profile_bin = torch.zeros(1, extractor.weapon_bin_dim)
    profile_bin[0, -1] = 1.0  # slot de profil occupé
    for family in ("allies", "enemies"):
        obs[f"{family}_wpn_cont"][:, 0, 0] = profile_cont
        obs[f"{family}_wpn_bin"][:, 0, 0] = profile_bin

    extractor.eval()
    with torch.no_grad():
        ally = extractor._encode_units(obs, "allies")[:, 0]
        enemy = extractor._encode_units(obs, "enemies")[:, 0]
    assert torch.allclose(ally, enemy, atol=1e-6), (
        "schema unifie : la meme unite doit produire le meme embedding des deux cotes"
    )

    with torch.no_grad():
        first_layer = extractor.weapon_encoder[0]
        assert isinstance(first_layer, torch.nn.Linear)
        first_layer.weight.add_(1.0)
        ally_after = extractor._encode_units(obs, "allies")[:, 0]
        enemy_after = extractor._encode_units(obs, "enemies")[:, 0]
    assert not torch.allclose(ally, ally_after, atol=1e-6), "l'encodeur ami n'a pas bouge"
    assert not torch.allclose(enemy, enemy_after, atol=1e-6), (
        "l'encodeur ennemi n'a PAS bouge : les deux camps n'utilisent pas le meme module"
    )
    assert torch.allclose(ally_after, enemy_after, atol=1e-6)


def test_unit_encoder_is_a_single_module(extractor):
    """Aucun module d'encodage n'est dupliqué par camp (verrou structurel du partage)."""
    named = dict(extractor.named_modules())
    encoders = [n for n in named if n.endswith("_encoder")]
    assert sorted(encoders) == [
        "self_model_encoder", "type_encoder", "unit_encoder", "weapon_encoder",
    ]
    assert not any("ally" in n or "enemy" in n for n in named)


def test_absent_entities_do_not_leak_into_the_aggregation(extractor):
    """Un slot vide ne contribue ni à l'agrégation ni à son propre embedding.

    Sans masquage, le recentrage de la normalisation donnerait une valeur NON nulle à une
    entité absente, indistinguable d'une entité réelle.
    """
    space = _space()
    obs = _zero_batch(space, batch=1)
    obs["allies_bin"][:, 0, 0] = 1.0
    extractor.eval()
    with torch.no_grad():
        emb = extractor._encode_units(obs, "enemies")
    assert torch.count_nonzero(emb) == 0


def test_self_model_mask_is_the_present_bit_not_the_row(extractor):
    """V11 §0.32 T-H : le masque des figurines se lit sur le bit `present`, PAS sur la ligne.

    L'extracteur déduisait la présence de `(|cont| + |bin|) > 0`, faute de bit dédié. Deux
    conséquences, toutes deux silencieuses : une figurine à ligne nulle (sur le centroïde arrondi
    et sans drapeau) était comptée absente, et une ligne de padding non nulle serait comptée
    présente. On verrouille la SECONDE, qui discrimine les deux lectures : ici la ligne 5 porte des
    continues non nulles avec `present = 0` — l'ancienne déduction en faisait une figurine, la
    lecture du bit l'ignore. La première est verrouillée côté moteur
    (`tests/unit/engine/test_squad_obs_geometry_phase_presence.py`).
    """
    from engine.observation_entities import self_model_bin_index

    present_idx = self_model_bin_index("present")
    space = _space()
    extractor.eval()

    obs = _zero_batch(space, batch=1)
    obs["allies_bin"][:, 0, 0] = 1.0
    obs["self_models_bin"][:, 0, present_idx] = 1.0  # une seule figurine réelle
    with torch.no_grad():
        reference = extractor(obs)

    polluted = {k: v.clone() for k, v in obs.items()}
    polluted["self_models_cont"][:, 5, :] = 3.0  # slot de padding, `present` reste à 0
    with torch.no_grad():
        got = extractor(polluted)

    assert torch.allclose(reference, got, atol=1e-6), (
        "une ligne de figurine a `present = 0` a change la sortie : le masque est deduit de la "
        "ligne au lieu d'etre lu sur le bit de presence"
    )

    # Contre-épreuve : le MÊME bruit avec `present = 1` doit, lui, changer la sortie.
    real = {k: v.clone() for k, v in polluted.items()}
    real["self_models_bin"][:, 5, present_idx] = 1.0
    with torch.no_grad():
        changed = extractor(real)
    assert not torch.allclose(reference, changed, atol=1e-6), (
        "une figurine reellement presente n'a eu aucun effet : le masque ne lit rien"
    )


def test_running_norm_statistics_are_shared_across_slots():
    """Une seule statistique par feature, estimée sur TOUS les slots — pas une par slot."""
    norm = EntityRunningNorm(2)
    norm.train()
    x = torch.tensor([[[0.0, 10.0], [4.0, 30.0]]])  # 1 batch, 2 slots, 2 features
    mask = torch.ones(1, 2)
    norm(x, mask)
    assert norm.running_mean[0].item() == pytest.approx(2.0, abs=1e-3)
    assert norm.running_mean[1].item() == pytest.approx(20.0, abs=1e-2)


def test_running_norm_ignores_padding():
    """Les entités absentes sont exclues de l'estimation (sinon tout converge vers zéro)."""
    norm = EntityRunningNorm(1)
    norm.train()
    x = torch.tensor([[[8.0], [0.0]]])
    mask = torch.tensor([[1.0, 0.0]])
    norm(x, mask)
    assert norm.running_mean[0].item() == pytest.approx(8.0, abs=1e-3)


def test_missing_key_raises():
    """Aucun repli : une clé absente de l'espace d'observation doit LEVER."""
    space = _space()
    incomplete = gym.spaces.Dict(
        {k: v for k, v in space.spaces.items() if k != "enemies_wpn_cont"}
    )
    with pytest.raises(KeyError):
        SpatialCombinedExtractor(incomplete, cnn_features=32)


def test_grid_channel_count_is_read_from_the_single_source():
    """`GRID_CHANNELS` est la SOURCE UNIQUE : l'extracteur ne code aucun nombre de canaux en dur.

    V11 §0.32 (T-K/T-L) a fait passer la grille de 7 a 9 canaux. Si l'extracteur recopiait la
    valeur, le CNN prendrait une entree d'une autre profondeur que celle produite par
    `build_squad_grid` — un decalage silencieux de la semantique apprise.
    """
    assert SpatialCombinedExtractor(_space(), cnn_features=32).cnn[0].in_channels == GRID_CHANNELS


def test_wrong_grid_shape_raises():
    """Aucun repli : une grille d'une autre profondeur doit LEVER, pas etre rabotee."""
    spaces = dict(_space().spaces)
    spaces["grid"] = gym.spaces.Box(
        low=0.0, high=1.0, shape=(GRID_CHANNELS - 1, GRID_SIZE, GRID_SIZE), dtype=np.float32
    )
    with pytest.raises(ValueError, match="forme de grille inattendue"):
        SpatialCombinedExtractor(gym.spaces.Dict(spaces), cnn_features=32)


def test_divergent_unit_schema_raises():
    """Un camp qui gagnerait une feature que l'autre n'a pas casse le partage : ça doit LEVER."""
    space = _space()
    spaces = dict(space.spaces)
    shape = spaces["enemies_cont"].shape
    assert shape is not None
    spaces["enemies_cont"] = gym.spaces.Box(
        low=-np.inf, high=np.inf, shape=(int(shape[0]), int(shape[1]) + 1), dtype=np.float32
    )
    with pytest.raises(ValueError, match="schema d'unite divergent"):
        SpatialCombinedExtractor(gym.spaces.Dict(spaces), cnn_features=32)


def test_maskable_policy_builds_and_forwards():
    """La policy MaskablePPO se construit sur l'espace d'entites et produit un forward complet.

    Critere d'acceptation T-D (« la politique se construit et fait un forward »). On verifie
    aussi que `log_prob` et l'entropie sont finis : une tete qui recevrait des embeddings non
    masques (NaN issus d'un max sur un ensemble vide) le ferait sauter ici, avant tout run.
    """
    from sb3_contrib import MaskablePPO
    from sb3_contrib.common.maskable.distributions import MaskableCategorical

    class _Env(gym.Env):
        observation_space = _space()
        action_space = gym.spaces.Discrete(17)

        def reset(self, *, seed=None, options=None):
            return self.observation_space.sample(), {}

        def step(self, action):
            return self.observation_space.sample(), 0.0, False, False, {}

        def action_masks(self):
            return np.ones(17, dtype=bool)

    model = MaskablePPO(
        "MultiInputPolicy", _Env(), n_steps=8, batch_size=8, device="cpu", verbose=0,
        policy_kwargs={
            "net_arch": [16, 16],
            "features_extractor_class": SpatialCombinedExtractor,
            "features_extractor_kwargs": {"cnn_features": 8},
        },
    )
    obs = _zero_batch(_space())
    obs["allies_bin"][:, 0, 0] = 1.0
    obs["enemies_bin"][:, 0, 0] = 1.0
    model.policy.set_training_mode(False)
    with torch.no_grad():
        actions, values, log_prob = model.policy(obs)
        dist = model.policy.get_distribution(obs)
    assert actions.shape == (2,)
    assert values.shape == (2, 1)
    assert log_prob is not None and torch.isfinite(log_prob).all()
    assert isinstance(dist.distribution, MaskableCategorical)
    entropy = dist.entropy()
    assert entropy is not None and torch.isfinite(entropy).all()
