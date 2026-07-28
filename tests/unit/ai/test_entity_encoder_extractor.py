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

from ai.spatial_extractor import (
    POSITIONAL_CHANNELS,
    EntityRunningNorm,
    SpatialCombinedExtractor,
    positional_channels,
)
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index
from engine.spatial_grid import (
    GRID_CELL_COUNT,
    GRID_CHANNELS,
    GRID_SIZE,
    cell_center_px,
)

_UNIT_PRESENT = unit_bin_index("present")


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
    """Contrat de sortie : [tronc | embeddings ennemis | carte de move] — tranches publiques.

    V11 §0.32 T-G : la carte NON aplatie s'ajoute derrière les embeddings ennemis. Les deux
    tranches sont lues par `ai/pointer_policy.py` au build, jamais recalculées de son côté.
    """
    sl = extractor.enemy_embeddings_slice()
    assert sl.start == extractor.trunk_dim
    assert (sl.stop - sl.start) == extractor.n_enemy_slots * extractor.entity_dim

    move = extractor.move_map_slice()
    assert move.start == sl.stop
    assert move.stop == extractor.features_dim
    assert (move.stop - move.start) == extractor.move_map_channels * GRID_CELL_COUNT


def test_forward_shape_and_finiteness(extractor):
    space = _space()
    obs = _zero_batch(space)
    obs["allies_bin"][:, 0, _UNIT_PRESENT] = 1.0     # l'unité active est présente
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
    obs["allies_bin"][:, 0, _UNIT_PRESENT] = 1.0
    obs["enemies_bin"][:, 0, _UNIT_PRESENT] = 1.0
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
    obs["allies_bin"][:, 0, _UNIT_PRESENT] = 1.0
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
    obs["allies_bin"][:, 0, _UNIT_PRESENT] = 1.0
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

    C'est le STEM qui lit la grille brute depuis T-G : les branches tronc et carte partent de lui.
    """
    extractor = SpatialCombinedExtractor(_space(), cnn_features=32)
    assert extractor.cnn_stem[0].in_channels == GRID_CHANNELS
    assert extractor.cnn[0].in_channels == extractor.cnn_stem[0].out_channels


def test_move_map_keeps_the_full_resolution(extractor):
    """V11 §0.32 T-G : la carte de move sort en 32x32, sans le moindre stride.

    C'est le stride qui détruit la correspondance cellule <-> action : après deux stride 2, une
    colonne de features couvre 16 cellules et ne peut plus en scorer une seule. La branche
    APLATIE du tronc, elle, garde ses strides — les deux coexistent.
    """
    space = _space()
    obs = _zero_batch(space, batch=2)
    obs["allies_bin"][:, 0, _UNIT_PRESENT] = 1.0
    extractor.eval()
    with torch.no_grad():
        out = extractor(obs)
    carte = out[:, extractor.move_map_slice()].reshape(
        2, extractor.move_map_channels, GRID_SIZE, GRID_SIZE
    )
    assert carte.shape == (2, extractor.move_map_channels, GRID_SIZE, GRID_SIZE)
    assert torch.isfinite(carte).all()
    for conv in extractor.map_net:
        if isinstance(conv, torch.nn.Conv2d):
            assert conv.stride == (1, 1), "un stride dans la branche carte casse l'alignement"


def test_move_map_carries_the_positional_channels(extractor):
    """Les canaux positionnels sont DANS la carte, et valent ceux de `cell_center_px`.

    Amendement §0.32 T-G : sans eux, la conv 1x1 serait invariante par translation, donc
    strictement plus faible que la tête dense qu'elle remplace — incapable d'exprimer « le
    centre n'est pas le bord » sur une grille égocentrique normalisée par le budget d'Advance.

    On les vérifie contre `spatial_grid.cell_center_px`, la source unique de la géométrie : x et
    y sont l'offset de la cellule par rapport à l'ancre, en unités de demi-étendue. Un `rayon`
    de 1,0 est donc EXACTEMENT la limite d'atteignabilité, pour toute unité et toute échelle.
    """
    pos = positional_channels()
    assert pos.shape == (1, POSITIONAL_CHANNELS, GRID_SIZE, GRID_SIZE)

    anchor_col, anchor_row, half_extent = 30, 20, 24
    # Ancre et demi-étendue RECONSTRUITES depuis `cell_center_px` (deux cellules opposées, deux
    # inconnues) : aucune constante de géométrie n'est recopiée ici.
    x0, y0 = cell_center_px(0, 0, anchor_col, anchor_row, half_extent)
    x1, y1 = cell_center_px(GRID_SIZE - 1, GRID_SIZE - 1, anchor_col, anchor_row, half_extent)
    span = GRID_SIZE / (2.0 * (GRID_SIZE - 1.0))
    width_x, width_y = (x1 - x0) * span, (y1 - y0) * span
    ax = x0 + (1.0 - 1.0 / GRID_SIZE) * width_x
    ay = y0 + (1.0 - 1.0 / GRID_SIZE) * width_y

    for gx, gy in ((0, 0), (5, 20), (GRID_SIZE - 1, GRID_SIZE - 1), (16, 16)):
        cx, cy = cell_center_px(gx, gy, anchor_col, anchor_row, half_extent)
        expected_x = (cx - ax) / width_x
        expected_y = (cy - ay) / width_y
        assert pos[0, 0, gy, gx].item() == pytest.approx(expected_x, abs=1e-5)
        assert pos[0, 1, gy, gx].item() == pytest.approx(expected_y, abs=1e-5)
        assert pos[0, 2, gy, gx].item() == pytest.approx(
            float(np.hypot(expected_x, expected_y)), abs=1e-5
        )
    # Sémantique du rayon : ~0 au centre (mon bloc), ~1 au bord de la fenêtre (limite
    # d'atteignabilité). La grille étant paire, aucune cellule ne tombe exactement sur 0 ni sur 1.
    half = GRID_SIZE // 2
    assert pos[0, 2, half, half].item() < 0.05
    assert pos[0, 2, half, GRID_SIZE - 1].item() == pytest.approx(1.0, abs=0.05)
    assert pos[0, 2, half, half].item() < pos[0, 2, half, GRID_SIZE - 1].item()

    # … et ils arrivent bien jusqu'au bout de la carte (derniers canaux, non appris).
    space = _space()
    obs = _zero_batch(space, batch=1)
    obs["allies_bin"][:, 0, _UNIT_PRESENT] = 1.0
    extractor.eval()
    with torch.no_grad():
        carte = extractor(obs)[:, extractor.move_map_slice()].reshape(
            1, extractor.move_map_channels, GRID_SIZE, GRID_SIZE
        )
    assert torch.allclose(carte[:, -POSITIONAL_CHANNELS:], pos, atol=1e-6), (
        "les canaux positionnels n'atteignent pas la tete : la conv 1x1 serait invariante par "
        "translation, donc plus faible que la tete dense qu'elle remplace"
    )


def test_move_map_is_not_translation_invariant(extractor):
    """Contre-épreuve du point précédent : la MÊME configuration locale, deux rayons.

    Un pic identique au centre et au bord doit produire des colonnes DIFFÉRENTES. Sans canaux
    positionnels, une convolution donnerait strictement la même réponse aux deux endroits — et
    l'agent ne pourrait plus distinguer « je bouge à peine » de « je pousse mon Advance au
    maximum », alors que c'est cette distinction qui lui coûte son tir.
    """
    space = _space()
    extractor.eval()

    def _column(gx: int, gy: int) -> torch.Tensor:
        obs = _zero_batch(space, batch=1)
        obs["allies_bin"][:, 0, _UNIT_PRESENT] = 1.0
        obs["grid"][:, 0, gy, gx] = 1.0
        with torch.no_grad():
            carte = extractor(obs)[:, extractor.move_map_slice()].reshape(
                1, extractor.move_map_channels, GRID_SIZE, GRID_SIZE
            )
        # On exclut les canaux positionnels eux-mêmes : c'est la RÉPONSE APPRISE qui doit
        # différer, pas seulement les trois canaux ajoutés à la fin.
        return carte[0, : -POSITIONAL_CHANNELS, gy, gx]

    centre = _column(GRID_SIZE // 2, GRID_SIZE // 2)
    bord = _column(1, 1)
    assert not torch.allclose(centre, bord, atol=1e-5), (
        "la carte repond identiquement au centre et au bord : les canaux positionnels ne sont "
        "pas lus par la pile conv"
    )


def test_map_channels_must_be_positive():
    """Aucune valeur par défaut masquant une erreur : une largeur de carte absurde doit LEVER."""
    with pytest.raises(ValueError, match="map_channels"):
        SpatialCombinedExtractor(_space(), cnn_features=32, map_channels=0)


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
    obs["allies_bin"][:, 0, _UNIT_PRESENT] = 1.0
    obs["enemies_bin"][:, 0, _UNIT_PRESENT] = 1.0
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
