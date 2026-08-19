"""T-E / T-G — correction des TÊTES D'ACTION sous MaskablePPO (cas jouet, avant tout run).

`V11_entity_encoder_pointer.md` §5.1 : « Tête pointeur : `log_prob`/entropie/masquage incorrects
sous MaskablePPO — **échoue silencieusement** (le training tourne, il apprend mal) ⇒ tests de
correction contre une tête dense de référence, sur cas jouet, AVANT tout run long. »

C'est exactement ce que fait ce fichier, pour les DEUX têtes. La référence n'est jamais « le même
code appelé deux fois » :

- **tir (T-E)** : les logits attendus sont recalculés à la main (`base` pour les actions non-tir,
  `q · e_i / sqrt(d)` pour les slots), et une **couche dense équivalente** est construite —
  `W_dense = E · W_q / sqrt(d)` — pour vérifier que le pointeur produit ce qu'une tête dense
  produirait sur les mêmes embeddings ;
- **move (T-G)** : la tête factorisée (`conv1x1(carte) + Linear(latent)` diffusé) est comparée à
  la forme NAÏVE qu'elle remplace — diffuser réellement le latent sur les 32x32, concaténer, puis
  appliquer une seule conv 1x1 sur la concaténation. Les deux DOIVENT coïncider au bit près :
  c'est la seule raison pour laquelle la factorisation est légitime.

Puis on compare `log_prob`, l'entropie et l'effet du masque des deux côtés.

Le test le plus critique du fichier est `test_move_logit_is_cell_local` : il vérifie
l'ALIGNEMENT `cellule (gx,gy) <-> action gy*32+gx`. Un `gx`/`gy` transposé dans la tête ne lève
rien, ne change aucune forme, et fait simplement viser à l'agent une cellule pour en jouer une
autre pendant 36 h de training.
"""

from __future__ import annotations

from typing import Dict

import gymnasium as gym
import numpy as np
import pytest
import torch
from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.distributions import MaskableCategorical

from ai.pointer_policy import DENSE_LOGIT_COUNT, PointerMaskablePolicy
from ai.spatial_extractor import SpatialCombinedExtractor
from engine.macro_intents import (
    ACTION_WAIT,
    ACTIVATE_SLOT_BASE,
    ACTIVATE_SLOT_COUNT,
    CHARGE_SLOT_BASE,
    CHARGE_SLOT_COUNT,
    CHOICE_BASE,
    CHOICE_COUNT,
    DEPLOY_SLOT_BASE,
    DEPLOY_SLOT_COUNT,
    MOVE_CELL_BASE,
    MOVE_CELL_COUNT,
    OATH_SLOT_BASE,
    FIGHT_SLOT_BASE,
    FIGHT_SLOT_COUNT,
    SHOOT_SLOT_BASE,
    SHOOT_SLOT_COUNT,
    TOTAL_ACTION_SIZE,
)
from engine.observation_entities import (
    decision_option_bin_index,
    deploy_cand_bin_index,
    deploy_cand_cont_index,
    global_bin_index,
    unit_bin_index,
)
from engine.spatial_grid import GRID_SIZE, cell_from_index, cell_index
from tests.unit.ai._fabriques import squad_obs_space

_UNIT_PRESENT = unit_bin_index("present")
_OPTION_PRESENT = decision_option_bin_index("present")
_CAND_PRESENT = deploy_cand_bin_index("present")


_space = squad_obs_space


class _ToyEnv(gym.Env):
    """Env jouet : l'espace d'observation réel, des transitions sans contenu.

    Les steps ALTERNENT phase de mouvement et phase de déploiement. Sans cette alternance, le
    rollout ne contiendrait que des observations d'une seule phase et la moitié du routage des
    ids 4-11 ne serait jamais parcourue : `deploy_query_net` recevrait un gradient NUL (il est
    dans le graphe par `torch.where`, donc `.grad` existerait quand même — un vert vacant).
    Alternance DÉTERMINISTE, jamais tirée au sort : un test doit construire l'état qu'il observe.
    """

    observation_space = _space()
    action_space = gym.spaces.Discrete(TOTAL_ACTION_SIZE)

    def __init__(self):
        super().__init__()
        self._steps = 0

    def _obs(self) -> Dict[str, np.ndarray]:
        self._steps += 1
        return _deploy_obs(1) if self._steps % 2 else _zero_obs(1)

    def reset(self, *, seed=None, options=None):
        return self._obs(), {}

    def step(self, action):
        return self._obs(), 0.0, False, False, {}

    def action_masks(self):
        return np.ones(TOTAL_ACTION_SIZE, dtype=bool)


def _zero_obs(batch: int = 2, phase: str = "move") -> Dict[str, np.ndarray]:
    obs: Dict[str, np.ndarray] = {}
    for key, sp in _space().spaces.items():
        shape = sp.shape
        assert shape is not None
        obs[key] = np.zeros((batch,) + tuple(int(d) for d in shape), dtype=np.float32)
    obs["allies_bin"][:, 0, _UNIT_PRESENT] = 1.0        # unité active présente
    obs["enemies_bin"][:, :3, _UNIT_PRESENT] = 1.0      # trois ennemis présents
    obs["enemies_cont"][:, :3, 0] = 5.0
    # Deux candidats de decision presents (§9.3 P2) : le jumeau exact des slots ennemis.
    obs["decision_options_bin"][:, :2, _OPTION_PRESENT] = 1.0
    obs["decision_options_bin"][:, 0, 0] = 1.0
    obs["decision_options_bin"][:, 1, 1] = 1.0
    # La phase est un ONE-HOT (§0.32 T-J) : une observation sans aucun bit posé n'existe pas dans
    # le moteur, et c'est ELLE qui décide si les ids 4-11 sont des cellules ou des slots de pose.
    obs["global_bin"][:, global_bin_index(f"phase_{phase}")] = 1.0
    return obs


def _deploy_obs(batch: int = 2) -> Dict[str, np.ndarray]:
    """Observation de PHASE DE DÉPLOIEMENT, avec trois slots de pose ouverts.

    Le bloc `deploy_cand_*` n'est rempli QUE dans cette phase (§0.40) et `present` y vaut
    exactement les slots que le masque ouvre : trois ici, les cinq autres restent des lignes de
    zéros, donc des embeddings nuls.
    """
    obs = _zero_obs(batch, phase="deployment")
    obs["deploy_cand_bin"][:, :3, _CAND_PRESENT] = 1.0
    obs["deploy_cand_bin"][:, 0, deploy_cand_bin_index("on_objective")] = 1.0
    obs["deploy_cand_bin"][:, 1, deploy_cand_bin_index("in_cover")] = 1.0
    for slot in range(3):
        obs["deploy_cand_cont"][:, slot, deploy_cand_cont_index("enemy_distance")] = 4.0 + slot
        obs["deploy_cand_cont"][:, slot, deploy_cand_cont_index("col_rel")] = 1.0 - slot
    return obs


def _tensors(obs: Dict[str, np.ndarray]) -> Dict[str, torch.Tensor]:
    return {k: torch.as_tensor(v) for k, v in obs.items()}


@pytest.fixture
def model() -> MaskablePPO:
    torch.manual_seed(7)
    return MaskablePPO(
        PointerMaskablePolicy, _ToyEnv(), n_steps=16, batch_size=8, device="cpu", verbose=0,
        policy_kwargs={
            "net_arch": [16, 16],
            "features_extractor_class": SpatialCombinedExtractor,
            "features_extractor_kwargs": {"cnn_features": 8},
        },
    )


def _manual_logits(policy, obs: Dict[str, torch.Tensor]):
    """Recalcul indépendant : (logits attendus, latent_pi).

    Volontairement écrit en `einsum` plutôt qu'en réutilisant `policy._point` : une référence qui
    appelle le code testé ne vérifie plus rien.
    """
    feats = policy._split_features(obs)
    embeddings, decision_emb = feats.enemies, feats.decision
    latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
    base = policy.action_net(latent_pi)
    scale = policy.entity_dim ** 0.5
    query = policy.query_net(latent_pi)
    pointer = torch.einsum("bd,bkd->bk", query, embeddings) / scale
    # V11 §9 P3-2 : seconde requete, memes embeddings -> logits de CIBLE DE CHARGE.
    charge_query = policy.charge_query_net(latent_pi)
    charge_pointer = torch.einsum("bd,bkd->bk", charge_query, embeddings) / scale
    # V11 §9 P3-1 : troisieme requete, memes embeddings -> logits de CIBLE DE MELEE.
    fight_query = policy.fight_query_net(latent_pi)
    fight_pointer = torch.einsum("bd,bkd->bk", fight_query, embeddings) / scale
    # V11 §9.3 P2 : quatrieme requete, embeddings de CANDIDATS -> logits CHOICE_i.
    choice = torch.einsum(
        "bd,bkd->bk", policy.choice_query_net(latent_pi), decision_emb
    ) / scale
    # Chantier 01 : cinquieme requete, memes embeddings d'ENNEMIS -> logits de cible d'Oath.
    oath_pointer = torch.einsum(
        "bd,bkd->bk", policy.oath_query_net(latent_pi), embeddings
    ) / scale
    move = policy._move_logits(latent_pi, feats.move_map)
    # §0.44 — en phase de déploiement, et LÀ SEULEMENT, les colonnes 4-11 des cellules sont
    # remplacées par le produit scalaire contre les candidats de pose.
    deploy = torch.einsum(
        "bd,bkd->bk", policy.deploy_query_net(latent_pi), feats.deploy
    ) / scale
    # V11 §0.48 `L2` : septieme requete, embeddings ALLIES -> logits d'ACTIVATION.
    activate_pointer = torch.einsum(
        "bd,bkd->bk", policy.activate_query_net(latent_pi), feats.allies
    ) / scale
    gate = (feats.is_deploy > 0.5).unsqueeze(1)
    low, high = DEPLOY_SLOT_BASE, DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT
    move = torch.cat(
        [move[:, :low], torch.where(gate, deploy, move[:, low:high]), move[:, high:]], dim=1
    )
    expected = torch.cat(
        [
            move,
            base[:, :1],        # wait
            pointer,
            charge_pointer,
            fight_pointer,
            base[:, 1:],        # fight-sans-cible, intents de zone
            choice,
            oath_pointer,
            activate_pointer,   # V11 §0.48 `L2`

        ],
        dim=1,
    )
    return expected, latent_pi


def test_shoot_logits_come_from_the_dot_product(model):
    """Les logits de tir SONT `q · e_i / sqrt(d)`, et le reste sort de `action_net` inchangé."""
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs())
    with torch.no_grad():
        expected, latent_pi = _manual_logits(policy, obs)
        feats = policy._split_features(obs)
        produced = policy._action_logits(
            policy.mlp_extractor.forward_actor(feats.trunk), feats
        )
    assert torch.allclose(produced, expected, atol=1e-6)
    # L'action `wait`, entre le move et le tir, vient bien de la PREMIERE colonne dense.
    with torch.no_grad():
        base = policy.action_net(latent_pi)
    assert torch.allclose(produced[:, ACTION_WAIT], base[:, 0], atol=1e-6)


def test_pointer_matches_a_dense_reference_head(model):
    """Contre-épreuve « tête dense de référence » : W_dense = E · W_q / sqrt(d).

    Sur des embeddings donnés, le pointeur doit produire EXACTEMENT ce que produirait une
    couche dense de ces poids — et donner les mêmes `log_prob` et la même entropie.
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        embeddings = feats.enemies
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        pointer = policy._action_logits(latent_pi, feats)[
            :, SHOOT_SLOT_BASE:SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT
        ]

        dense = torch.nn.Linear(latent_pi.shape[1], SHOOT_SLOT_COUNT, bias=True)
        w_q = policy.query_net.weight            # (d, latent)
        b_q = policy.query_net.bias              # (d,)
        e = embeddings[0]                        # (K, d)
        scale = policy.entity_dim ** 0.5
        dense.weight.copy_(e @ w_q / scale)
        dense.bias.copy_(e @ b_q / scale)
        dense_out = dense(latent_pi)
    assert torch.allclose(pointer, dense_out, atol=1e-5)

    # … et les grandeurs que PPO consomme sont identiques des deux côtés.
    masks = np.ones((1, TOTAL_ACTION_SIZE), dtype=bool)
    with torch.no_grad():
        full = policy._action_logits(latent_pi, feats)
        reference = torch.cat(
            [
                full[:, :SHOOT_SLOT_BASE],
                dense_out,
                full[:, SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT:],
            ],
            dim=1,
        )
        dist_pointer = policy._distribution_from(latent_pi, feats, masks)
        ref_dist = MaskableCategorical(logits=reference, masks=masks)
        actions = torch.arange(TOTAL_ACTION_SIZE)
        for a in (0, SHOOT_SLOT_BASE, SHOOT_SLOT_BASE + 2, TOTAL_ACTION_SIZE - 1):
            assert dist_pointer.log_prob(actions[a:a + 1]).item() == pytest.approx(
                ref_dist.log_prob(actions[a:a + 1]).item(), abs=1e-5
            )
        assert dist_pointer.entropy().item() == pytest.approx(ref_dist.entropy().item(), abs=1e-5)


def test_masking_removes_a_shoot_slot_from_the_distribution(model):
    """Un slot masqué a une probabilité NULLE et ne contribue plus à l'entropie."""
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    masks = np.zeros((1, TOTAL_ACTION_SIZE), dtype=bool)
    masks[0, SHOOT_SLOT_BASE:SHOOT_SLOT_BASE + 3] = True
    with torch.no_grad():
        dist = policy.get_distribution(obs, action_masks=masks)
        probs = dist.distribution.probs
    assert probs is not None
    assert float(probs[0, SHOOT_SLOT_BASE:SHOOT_SLOT_BASE + 3].sum()) == pytest.approx(1.0, abs=1e-5)
    assert float(probs[0, :SHOOT_SLOT_BASE].sum()) == pytest.approx(0.0, abs=1e-6)
    assert float(probs[0, SHOOT_SLOT_BASE + 3:].sum()) == pytest.approx(0.0, abs=1e-6)
    # Trois actions équiprobables au plus : l'entropie est bornée par ln 3.
    entropy = dist.entropy()
    assert entropy is not None
    assert float(entropy) <= float(np.log(3.0)) + 1e-5


def test_pointer_logit_is_slot_local(model):
    """À tronc FIXÉ, l'embedding du slot 1 ne déplace QUE le logit du slot 1.

    C'est la propriété qui rend le nombre de slots gratuit : chaque logit de tir ne dépend que
    de son propre ennemi. (Le tronc, lui, voit l'agrégation des ennemis en CONTEXTE — c'est
    voulu : changer un ennemi change aussi le contexte, donc les autres logits. On isole donc
    ici la tête pointeur, à latent constant.)
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        embeddings = feats.enemies
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        before = policy._action_logits(latent_pi, feats)
        perturbed = embeddings.clone()
        perturbed[:, 1] += 1.0
        after = policy._action_logits(latent_pi, feats._replace(enemies=perturbed))
    diff = (after - before).abs()[0]
    changed = torch.nonzero(diff > 1e-6).flatten().tolist()
    # Le slot 1 pilote QUATRE logits depuis le chantier 01 : « tirer sur lui », « le charger »,
    # « le frapper » et « lui jurer Oath ». Les quatre sortent du MEME embedding, par quatre
    # requetes distinctes — c'est le partage recherche.
    assert changed == [
        SHOOT_SLOT_BASE + 1, CHARGE_SLOT_BASE + 1, FIGHT_SLOT_BASE + 1, OATH_SLOT_BASE + 1
    ], f"logits deplaces : {changed[:5]}"


def test_evaluate_actions_returns_values_log_prob_entropy(model):
    """Ordre de retour SB3 : (values, log_prob, entropy). L'inverser sabote PPO en silence."""
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs())
    masks = np.ones((2, TOTAL_ACTION_SIZE), dtype=bool)
    actions = torch.tensor([SHOOT_SLOT_BASE, SHOOT_SLOT_BASE + 1])
    with torch.no_grad():
        values, log_prob, entropy = policy.evaluate_actions(obs, actions, action_masks=masks)
        dist = policy.get_distribution(obs, action_masks=masks)
        predicted_values = policy.predict_values(obs)
    assert values.shape == (2, 1)
    assert log_prob.shape == (2,)
    assert entropy is not None and entropy.shape == (2,)
    assert torch.allclose(values, predicted_values, atol=1e-6)
    assert torch.allclose(log_prob, dist.log_prob(actions), atol=1e-6)


def test_forward_log_prob_matches_the_distribution(model):
    """`forward` renvoie le `log_prob` de l'action qu'il a effectivement tirée."""
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs())
    masks = np.ones((2, TOTAL_ACTION_SIZE), dtype=bool)
    with torch.no_grad():
        actions, values, log_prob = policy(obs, deterministic=True, action_masks=masks)
        dist = policy.get_distribution(obs, action_masks=masks)
    assert torch.allclose(log_prob, dist.log_prob(actions), atol=1e-6)
    assert torch.isfinite(values).all()


def test_learning_step_runs_end_to_end(model):
    """Un cycle rollout + optimisation complet passe (gradients finis, aucune NaN)."""
    model.learn(total_timesteps=32)
    grads = [p.grad for p in model.policy.parameters() if p.grad is not None]
    assert grads, "aucun gradient : la tete pointeur n'est pas dans le graphe"
    assert all(torch.isfinite(g).all() for g in grads)
    assert model.policy.query_net.weight.grad is not None, (
        "la matrice de requete du pointeur ne recoit PAS de gradient"
    )
    assert model.policy.choice_query_net.weight.grad is not None, (
        "la requete du pointeur de DECISION ne recoit PAS de gradient (§9.3 P2)"
    )
    # T-G : les trois modules de la tête de move sont dans le graphe eux aussi. Une tête
    # branchée « à côté » (logits recalculés puis écrasés par `action_net`) passerait tous les
    # tests de forme et n'apprendrait jamais.
    for name in ("move_cell_net", "move_ctx_net", "move_out_net"):
        grad = getattr(model.policy, name).weight.grad
        assert grad is not None and torch.isfinite(grad).all(), (
            f"{name} ne recoit PAS de gradient : la tete de move n'est pas dans le graphe"
        )
    # §0.44 — la tête de déploiement, elle, exige un gradient NON NUL : elle est branchée par un
    # `torch.where`, donc `.grad` existe (à zéro) même si aucune observation de déploiement n'est
    # passée. C'est le rollout alterné de `_ToyEnv` qui rend ce contrôle non vacant.
    deploy_grad = model.policy.deploy_query_net.weight.grad
    assert deploy_grad is not None and torch.isfinite(deploy_grad).all()
    assert float(deploy_grad.abs().sum()) > 0.0, (
        "la requete de DEPLOIEMENT recoit un gradient NUL : ses logits ne sont selectionnes "
        "dans aucun etat du rollout (§0.44)"
    )


# ======================================================================================
# T-G — tête de move : conv 1x1 par cellule (V11 §0.32)
# ======================================================================================


def _grid_spike_move_logits(policy, gx: int, gy: int):
    """Logits de cellule avant / après un pic dans la cellule (gx,gy) de la GRILLE.

    Le latent du tronc est FIXÉ à celui de l'observation de référence : la branche aplatie du
    tronc voit elle aussi le pic, et le latent conditionne les 1024 cellules — sans ce gel, TOUT
    bouge et la géométrie n'est plus observable. C'est le même isolement que pour le pointeur de
    tir, où le tronc voit l'agrégation des ennemis.
    """
    obs = _tensors(_zero_obs(1))
    spiked = {k: v.clone() for k, v in obs.items()}
    spiked["grid"][:, 0, gy, gx] = 1.0     # indexation [canal, gy, gx] du builder
    with torch.no_grad():
        feats = policy._split_features(obs)
        spiked_map = policy._split_features(spiked).move_map
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        return (
            policy._move_logits(latent_pi, feats.move_map),
            policy._move_logits(latent_pi, spiked_map),
        )


def test_move_logit_is_cell_local(model):
    """⚠️ TEST D'ALIGNEMENT. Un pic dans la colonne (gx,gy) ne déplace QUE l'action `gy*32+gx`.

    C'est le test qui protège de la faute silencieuse la plus coûteuse du chantier : une
    transposition `gx`/`gy` dans la tête ne lève rien, ne change aucune forme, et fait viser à
    l'agent une cellule pour en jouer une autre pendant tout le run. On prend une cellule
    ASYMÉTRIQUE (`gx != gy`) : à `gx == gy`, une transposition passerait le test.

    On isole la tête (carte fixée, latent constant), comme `test_pointer_logit_is_slot_local`
    isole le pointeur : la pile conv de l'extracteur a un champ réceptif de 5x5, donc un pic
    dans l'OBSERVATION touche légitimement le voisinage — c'est l'objet du test suivant.
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    gx, gy = 5, 20
    with torch.no_grad():
        feats = policy._split_features(obs)
        move_map = feats.move_map
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        before = policy._action_logits(latent_pi, feats)
        perturbed = move_map.clone()
        perturbed[:, :, gy, gx] += 5.0
        after = policy._action_logits(latent_pi, feats._replace(move_map=perturbed))
    diff = (after - before).abs()[0]
    changed = torch.nonzero(diff > 1e-6).flatten().tolist()
    assert changed == [MOVE_CELL_BASE + cell_index(gx, gy)], (
        f"logits deplaces : {changed[:5]} — attendu la seule action de la cellule "
        f"({gx},{gy}) = {MOVE_CELL_BASE + cell_index(gx, gy)}"
    )


def test_grid_spike_stays_inside_the_receptive_field_of_its_cell(model):
    """De bout en bout : un pic dans la GRILLE ne bouge que le voisinage 5x5 de SA cellule.

    Contrôle de la chaîne complète obs -> extracteur -> tête, sans isoler quoi que ce soit. Deux
    couches 3x3 donnent un champ réceptif de 5x5 : les cellules déplacées doivent toutes tomber
    dans cette fenêtre, centrée sur (gx,gy). Une transposition, à `gx != gy`, envoie la fenêtre
    ailleurs et fait rougir le test.
    """
    policy = model.policy
    policy.set_training_mode(False)
    gx, gy = 5, 20
    before, after = _grid_spike_move_logits(policy, gx, gy)
    diff = (after - before).abs()[0]
    moved = torch.nonzero(diff > 1e-6).flatten().tolist()
    assert moved, "le pic dans la grille n'a bouge AUCUN logit de cellule : la carte est morte"
    assert cell_index(gx, gy) in moved, "la cellule du pic elle-meme n'a pas bouge"
    for idx in moved:
        # Décomposition inverse par `cell_from_index`, le JUMEAU de `cell_index` utilisé ci-dessus :
        # la réécrire à la main ici testerait l'arithmétique du test, pas celle du moteur.
        cx, cy = cell_from_index(idx)
        assert abs(cx - gx) <= 2 and abs(cy - gy) <= 2, (
            f"la cellule {idx} = ({cx},{cy}) a bouge alors qu'elle est "
            f"hors du champ receptif 5x5 de ({gx},{gy}) : geometrie desalignee"
        )


def test_move_head_matches_the_naive_broadcast_reference(model):
    """Référence : diffuser VRAIMENT le latent sur les 32x32, concaténer, UNE conv 1x1.

    La tête factorise ce calcul (`conv1x1(carte) + Linear(latent)`) pour ne pas matérialiser un
    tenseur `(B, latent_dim, 32, 32)` — 1,3 Go à batch 1024. La factorisation n'est légitime que
    si elle donne le MÊME résultat : c'est ce que vérifie ce test, en construisant la forme naïve
    à partir des poids de la tête (`W = [W_carte | W_latent]`).
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=2))
    with torch.no_grad():
        feats = policy._split_features(obs)
        move_map = feats.move_map
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        produced = policy._move_logits(latent_pi, move_map)

        # Forme naïve : broadcast explicite du latent, concaténation, UNE seule conv 1x1.
        batch = latent_pi.shape[0]
        broadcast = latent_pi[:, :, None, None].expand(-1, -1, GRID_SIZE, GRID_SIZE)
        stacked = torch.cat([move_map, broadcast], dim=1)
        naive = torch.nn.Conv2d(stacked.shape[1], policy.move_cell_net.out_channels, 1)
        naive.weight.copy_(
            torch.cat(
                [
                    policy.move_cell_net.weight,
                    policy.move_ctx_net.weight[:, :, None, None],
                ],
                dim=1,
            )
        )
        assert naive.bias is not None, "Conv2d construit avec bias=True (défaut)"
        naive.bias.copy_(policy.move_cell_net.bias + policy.move_ctx_net.bias)
        reference = policy.move_out_net(torch.relu(naive(stacked))).reshape(
            batch, MOVE_CELL_COUNT
        )
    assert torch.allclose(produced, reference, atol=1e-5), (
        "la tete factorisee ne calcule PAS la conv 1x1 sur [carte ; latent diffuse]"
    )


def test_trunk_context_reorders_the_cells_it_is_not_a_uniform_shift(model):
    """Le conditionnement par le tronc doit RÉORDONNER les cellules, pas les décaler en bloc.

    C'est le piège de l'amendement §0.32 T-G : avec une conv 1x1 UNIQUE sur
    `[carte ; latent diffuse]`, la contribution du latent est la même pour les 1024 cellules —
    donc strictement invisible du softmax. Le conditionnement serait un no-op silencieux : la
    tête tournerait, apprendrait, et ne saurait toujours rien du tour, des VP ni des objectifs
    hors fenêtre. La non-linéarité intercalée est ce qui l'évite.

    Mutation de contrôle : retirer le `torch.relu` de `_move_logits` rend l'écart CONSTANT et
    fait rougir ce test.
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        move_map = feats.move_map
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        # Une carte NON dégénérée : sinon toutes les cellules sont identiques et aucune tête,
        # même correcte, ne pourrait les réordonner.
        varied = move_map + torch.randn_like(move_map)
        before = policy._move_logits(latent_pi, varied)
        after = policy._move_logits(latent_pi + 3.0, varied)
    delta = (after - before)[0]
    assert float(delta.max() - delta.min()) > 1e-3, (
        "changer le latent decale les 1024 logits de la MEME quantite : le conditionnement est "
        "invisible du softmax, donc inexistant"
    )


def test_move_head_costs_nothing_per_cell(model):
    """Le nombre de cellules est GRATUIT en paramètres — c'est tout l'objet de T-G.

    Une tête dense coûterait `latent_dim x 1024` paramètres pour ces logits. Ici, les trois
    modules réunis sont bornés par quelques milliers de paramètres, indépendamment de
    `GRID_CELL_COUNT`.
    """
    policy = model.policy
    head = sum(
        p.numel()
        for module in (policy.move_cell_net, policy.move_ctx_net, policy.move_out_net)
        for p in module.parameters()
    )
    dense_equivalent = policy.mlp_extractor.latent_dim_pi * MOVE_CELL_COUNT
    assert head < dense_equivalent, (
        f"la tete de move ({head} parametres) n'est pas moins chere que la tete dense "
        f"qu'elle remplace ({dense_equivalent})"
    )
    # Aucun paramètre de la tête n'est indexé par la cellule.
    for module in (policy.move_cell_net, policy.move_ctx_net, policy.move_out_net):
        for p in module.parameters():
            assert MOVE_CELL_COUNT not in tuple(p.shape), (
                "un parametre de la tete de move est dimensionne par le nombre de cellules : "
                "le partage de poids entre cellules n'est pas effectif"
            )


def test_action_net_has_no_dead_column(model):
    """`action_net` est réduit à ses colonnes VIVES (V11 §9 P3-2 : `Linear(latent, 17)`).

    Avant P2, la couche était dimensionnée sur l'action space entier et 1050 de ses colonnes ne
    recevaient aucun gradient — ~336 k paramètres inertes. Ce test verrouille les deux moitiés de
    la propriété : la taille EST celle des actions denses, et CHACUNE de ces colonnes déplace
    réellement le logit qu'elle est censée produire (une colonne morte signalerait un assemblage
    qui l'ignore).

    ⚠️ Historique utile : `L2` a d'abord porté ses 12 slots d'ACTIVATION ICI, en colonnes denses,
    faute de tête pointeur. `activate_query_net` les a remplacées et la couche est redescendue à
    17 — ce cas est ce qui rend ce retrait VÉRIFIABLE plutôt que déclaré.
    """
    policy = model.policy
    policy.set_training_mode(False)
    assert policy.action_net.out_features == DENSE_LOGIT_COUNT
    # Les ids denses, dans l'ordre : wait, puis tout ce qui suit les slots de mêlée
    # (fight-sans-cible + intents de zone) jusqu'aux CHOICE.
    dense_action_ids = (
        [ACTION_WAIT]
        + list(range(FIGHT_SLOT_BASE + FIGHT_SLOT_COUNT, CHOICE_BASE))
    )
    assert len(dense_action_ids) == DENSE_LOGIT_COUNT
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
    # Logits BRUTS : ceux de la distribution sont renormalisés, donc TOUS bougent des qu'un seul
    # change — la localité y serait invisible.
    for column, action_id in enumerate(dense_action_ids):
        with torch.no_grad():
            before = policy._action_logits(latent_pi, feats)
            policy.action_net.bias[column].add_(10.0)
            after = policy._action_logits(latent_pi, feats)
            policy.action_net.bias[column].sub_(10.0)
        moved = torch.nonzero((after - before).abs()[0] > 1e-6).flatten().tolist()
        assert moved == [action_id], (
            f"la colonne dense {column} devait deplacer la seule action {action_id}, "
            f"elle a deplace {moved[:5]}"
        )


# ======================================================================================
# P3-2 — tête pointeur de CHARGE : la cible de charge est un slot ennemi (V11 §9 P3-2)
# ======================================================================================


def test_charge_logits_come_from_the_charge_pointer(model):
    """Les logits `CHARGE_SLOT_i` SONT `q_charge · e_i / sqrt(d)`, pas des colonnes denses.

    Même raison que le tir et la mêlée : le candidat est une ENTITÉ déjà encodée, donc le slot
    doit être scoré sur son embedding — un slot de plus coûte alors zéro paramètre.
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        embeddings = feats.enemies
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        produced = policy._action_logits(latent_pi, feats)
        expected = torch.einsum(
            "bd,bkd->bk", policy.charge_query_net(latent_pi), embeddings
        ) / (policy.entity_dim ** 0.5)
    assert torch.allclose(
        produced[:, CHARGE_SLOT_BASE:CHARGE_SLOT_BASE + CHARGE_SLOT_COUNT], expected, atol=1e-6
    )


def test_charge_query_is_distinct_from_shoot_and_fight(model):
    """Trois requêtes DISTINCTES sur les mêmes embeddings — pas une seule partagée.

    Partager la requête forcerait un ordre de préférence unique pour « qui tirer », « qui
    charger » et « qui frapper », alors que ce sont trois questions différentes. La contre-épreuve
    est structurelle : perturber la requête de charge ne doit toucher QUE les logits de charge.
    """
    policy = model.policy
    policy.set_training_mode(False)
    assert policy.charge_query_net is not policy.query_net
    assert policy.charge_query_net is not policy.fight_query_net
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        before = policy._action_logits(latent_pi, feats)
        policy.charge_query_net.bias.add_(1.0)
        after = policy._action_logits(latent_pi, feats)
        policy.charge_query_net.bias.sub_(1.0)
    changed = torch.nonzero((after - before).abs()[0] > 1e-6).flatten().tolist()
    # Seuls les slots dont l'embedding est non nul bougent (un slot vide est masqué à zéro par
    # l'encodeur, donc son produit scalaire l'est aussi) : on exige donc « aucun logit hors de la
    # famille charge », et au moins un déplacé — sans quoi le test passerait sur une tête morte.
    assert changed, "la requete de charge ne deplace AUCUN logit : tete inerte"
    assert all(
        CHARGE_SLOT_BASE <= action < CHARGE_SLOT_BASE + CHARGE_SLOT_COUNT for action in changed
    ), f"la requete de charge deplace des logits hors de sa famille : {changed[:5]}"


def test_charge_head_costs_nothing_per_slot(model):
    """Le nombre de slots de charge est GRATUIT en paramètres."""
    policy = model.policy
    for parameter in policy.charge_query_net.parameters():
        assert CHARGE_SLOT_COUNT not in tuple(parameter.shape), (
            "un parametre de la tete de charge est dimensionne par le nombre de slots"
        )


# ======================================================================================
# P2 — tête pointeur de DÉCISION : les candidats de `pending_agent_decision` (V11 §9.3)
# ======================================================================================


def test_choice_logits_come_from_the_decision_pointer(model):
    """Les logits `CHOICE_i` SONT `q_choice · c_i / sqrt(d)`, pas des colonnes denses.

    Même raison que pour le tir : l'option `i` d'un prompt n'a rien à voir avec l'option `i` d'un
    autre, donc une ligne de poids par slot n'aurait RIEN à généraliser.
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        decision_emb = feats.decision
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        produced = policy._action_logits(latent_pi, feats)
        expected = torch.einsum(
            "bd,bkd->bk", policy.choice_query_net(latent_pi), decision_emb
        ) / (policy.entity_dim ** 0.5)
    assert torch.allclose(
        produced[:, CHOICE_BASE:CHOICE_BASE + CHOICE_COUNT], expected, atol=1e-6
    )


def test_choice_logit_is_candidate_local(model):
    """⚠️ TEST D'ALIGNEMENT `CHOICE_i` <-> candidat `i`.

    L'ordre des candidats est CONTRACTUEL (§9.6) : `decision_options_bin[i]` décrit le candidat
    que joue `CHOICE_i`. Une permutation ici ferait appliquer au moteur une option autre que celle
    que l'agent a évaluée, sans que rien ne lève.
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        decision_emb = feats.decision
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        before = policy._action_logits(latent_pi, feats)
        perturbed = decision_emb.clone()
        perturbed[:, 1] += 1.0
        after = policy._action_logits(latent_pi, feats._replace(decision=perturbed))
    changed = torch.nonzero((after - before).abs()[0] > 1e-6).flatten().tolist()
    assert changed == [CHOICE_BASE + 1], f"logits deplaces : {changed[:5]}"


def test_choice_head_costs_nothing_per_candidate(model):
    """Le nombre de candidats est GRATUIT en paramètres : aucun poids n'est indexé par le slot."""
    policy = model.policy
    for module in (policy.choice_query_net, policy.features_extractor.decision_encoder):
        for parameter in module.parameters():
            assert CHOICE_COUNT not in tuple(parameter.shape), (
                "un parametre de la tete de decision est dimensionne par le nombre de candidats"
            )


# ======================================================================================
# L1 / §0.44 — tête pointeur de DÉPLOIEMENT : les ids 4-11 selon la phase
# ======================================================================================
#
# Le point dur du chantier n'est pas le produit scalaire (c'est le jumeau de `choice_query_net`),
# c'est le ROUTAGE : les mêmes ids sont des cellules de move et des slots de pose, et seule la
# phase les sépare. Les deux tests qui suivent sont les deux moitiés d'un même verrou — inverser
# le sens du `torch.where` de `_deploy_logits` les fait rougir TOUS LES DEUX.

_DEPLOY_IDS = slice(DEPLOY_SLOT_BASE, DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT)


def _deploy_pointer_reference(policy, feats, latent_pi) -> torch.Tensor:
    """`q_deploy · c_i / sqrt(d)`, recalculé hors de la policy."""
    return torch.einsum(
        "bd,bkd->bk", policy.deploy_query_net(latent_pi), feats.deploy
    ) / (policy.entity_dim ** 0.5)


def test_deploy_logits_come_from_the_deploy_pointer_in_deployment_phase(model):
    """En phase de déploiement, les ids 4-11 SONT `q_deploy · c_i / sqrt(d)`.

    Avant §0.44 ils sortaient de la conv 1x1 de la carte, aux cellules (0, 4..11) de la fenêtre
    égocentrique — des cellules sans aucun rapport avec les hexes candidats.
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_deploy_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        produced = policy._action_logits(latent_pi, feats)
        expected = _deploy_pointer_reference(policy, feats, latent_pi)
        move = policy._move_logits(latent_pi, feats.move_map)
    assert torch.allclose(produced[:, _DEPLOY_IDS], expected, atol=1e-6)
    # … et ce n'est PAS ce que la conv aurait produit : sans cet écart, le test passerait aussi
    # avec un routage inerte (les deux têtes rendraient la même chose par hasard numérique).
    assert not torch.allclose(produced[:, _DEPLOY_IDS], move[:, _DEPLOY_IDS], atol=1e-4)
    # Les 1016 AUTRES cellules restent celles de la conv : le remplacement est borné aux 8 ids.
    assert torch.allclose(produced[:, :DEPLOY_SLOT_BASE], move[:, :DEPLOY_SLOT_BASE], atol=1e-6)
    assert torch.allclose(
        produced[:, DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT:MOVE_CELL_COUNT],
        move[:, DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT:],
        atol=1e-6,
    )


@pytest.mark.parametrize("phase", ["move", "command", "shoot", "charge", "fight"])
def test_outside_deployment_the_same_ids_stay_move_cells(model, phase):
    """⚠️ MOITIÉ INVERSE DU VERROU. Hors déploiement, les ids 4-11 restent des CELLULES.

    Router hors phase de déploiement serait pire que ne pas router du tout : le bloc
    `deploy_cand_*` est nul par contrat hors de cette phase, donc le produit scalaire rendrait
    8 logits rigoureusement égaux — un choix uniforme sur 8 cellules parfaitement jouables.

    `command` est là pour l'alignement de l'INDEX du drapeau : c'est le bit VOISIN de
    `phase_deployment` dans `global_bin`. Un index décalé d'un cran routerait ici (le décalage
    dans l'autre sens, lui, est attrapé par le test de phase de déploiement ci-dessus).
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1, phase=phase))
    with torch.no_grad():
        feats = policy._split_features(obs)
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        produced = policy._action_logits(latent_pi, feats)
        move = policy._move_logits(latent_pi, feats.move_map)
    assert torch.allclose(produced[:, :MOVE_CELL_COUNT], move, atol=1e-6), (
        f"en phase {phase}, les logits de cellule ne sont plus ceux de la conv 1x1"
    )


def test_the_phase_flag_routes_per_sample_not_per_batch(model):
    """Un lot MÉLANGE les phases (n_envs) : le routage doit être par ÉCHANTILLON.

    Une branche `if` scalaire — la forme naturelle si on lisait la phase comme un booléen —
    trancherait pour tout le lot d'après le premier échantillon. En rollout vectorisé, la moitié
    des environnements jouerait alors la mauvaise tête, sans que rien ne lève.
    """
    policy = model.policy
    policy.set_training_mode(False)
    mixed = {
        key: torch.cat([value, _tensors(_zero_obs(1, phase="move"))[key]], dim=0)
        for key, value in _tensors(_deploy_obs(1)).items()
    }
    with torch.no_grad():
        feats = policy._split_features(mixed)
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        produced = policy._action_logits(latent_pi, feats)
        pointer = _deploy_pointer_reference(policy, feats, latent_pi)
        move = policy._move_logits(latent_pi, feats.move_map)
    assert torch.allclose(produced[0, _DEPLOY_IDS], pointer[0], atol=1e-6)
    assert torch.allclose(produced[1, _DEPLOY_IDS], move[1, _DEPLOY_IDS], atol=1e-6)


def test_deploy_logit_is_candidate_local(model):
    """⚠️ TEST D'ALIGNEMENT `DEPLOY_SLOT_BASE + i` <-> candidat `i` (invariant D1).

    `deploy_cand_*[i]` décrit l'hexe que pose l'action `4 + i` : une permutation ici ferait poser
    l'escouade à un endroit autre que celui que l'agent a évalué, sans que rien ne lève.
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_deploy_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        before = policy._action_logits(latent_pi, feats)
        perturbed = feats.deploy.clone()
        perturbed[:, 1] += 1.0
        after = policy._action_logits(latent_pi, feats._replace(deploy=perturbed))
    changed = torch.nonzero((after - before).abs()[0] > 1e-6).flatten().tolist()
    assert changed == [DEPLOY_SLOT_BASE + 1], f"logits deplaces : {changed[:5]}"


def test_deploy_query_is_distinct_from_the_other_pointers(model):
    """Requête PROPRE au déploiement : « où poser » n'est pas « quelle option choisir ».

    Contre-épreuve structurelle : perturber `deploy_query_net` ne doit toucher QUE les ids 4-11,
    et seulement les slots dont le candidat est OUVERT (un slot fermé a un embedding nul, donc un
    produit scalaire nul quoi qu'il arrive à la requête).
    """
    policy = model.policy
    policy.set_training_mode(False)
    assert policy.deploy_query_net is not policy.choice_query_net
    assert policy.deploy_query_net is not policy.query_net
    obs = _tensors(_deploy_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        before = policy._action_logits(latent_pi, feats)
        policy.deploy_query_net.bias.add_(1.0)
        after = policy._action_logits(latent_pi, feats)
        policy.deploy_query_net.bias.sub_(1.0)
    changed = torch.nonzero((after - before).abs()[0] > 1e-6).flatten().tolist()
    assert changed == [DEPLOY_SLOT_BASE, DEPLOY_SLOT_BASE + 1, DEPLOY_SLOT_BASE + 2], (
        f"la requete de deploiement deplace {changed[:5]} — attendu les 3 slots OUVERTS"
    )


def test_deploy_head_costs_nothing_per_slot(model):
    """Le nombre de slots de pose est GRATUIT en paramètres.

    C'est ce qui rend le pré-dimensionnement `DEPLOY_SLOT_COUNT = 8` pour
    `DEPLOY_STRATEGY_COUNT = 7` stratégies réellement sans coût : ouvrir une 8ᵉ stratégie
    n'ajoutera ni paramètre, ni retrain.
    """
    policy = model.policy
    for module in (policy.deploy_query_net, policy.features_extractor.deploy_cand_encoder):
        for parameter in module.parameters():
            assert DEPLOY_SLOT_COUNT not in tuple(parameter.shape), (
                "un parametre de la tete de deploiement est dimensionne par le nombre de slots"
            )


# ======================================================================================
# V11 §0.48 `L2` — tête pointeur d'ACTIVATION : quelle escouade ALLIÉE activer
# ======================================================================================


def test_activate_logits_come_from_the_ally_pointer(model):
    """Les logits `ACTIVATE_SLOT_i` SONT `q_act · a_i / sqrt(d)`, pas des colonnes denses.

    Même raison que le tir, la charge et la mêlée, côté ALLIÉ : le candidat est une entité déjà
    encodée, donc le slot se score sur son embedding — un slot de plus coûte alors zéro paramètre.
    `L2` a d'abord livré ces logits en colonnes DENSES d'`action_net` (moitié réseau différée) ;
    ce cas est ce qui rend le remplacement vérifiable.
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        produced = policy._action_logits(latent_pi, feats)
        expected = torch.einsum(
            "bd,bkd->bk", policy.activate_query_net(latent_pi), feats.allies
        ) / (policy.entity_dim ** 0.5)
    low = ACTIVATE_SLOT_BASE
    assert torch.allclose(
        produced[:, low:low + ACTIVATE_SLOT_COUNT], expected, atol=1e-6
    )


def test_activate_pointer_reads_the_ally_row_zero_too(model):
    """La ligne 0 (unité ACTIVE) est un CANDIDAT, pas seulement du contexte de tronc.

    Le slot d'activation 0 désigne l'ancre du pool — le seul toujours ouvert. Si l'extracteur
    n'exposait que les lignes 1..K-1, l'action `ACTIVATE_SLOT_i` pointerait la ligne `i+1` : un
    décalage d'un cran, invisible, qui ferait activer B en croyant activer A (invariant D1).
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
    assert feats.allies.shape[1] == ACTIVATE_SLOT_COUNT
    # `_zero_obs` ne pose `present` QUE sur la ligne 0 : son embedding est donc le seul non nul.
    # Si la tranche démarrait à la ligne 1, ce bloc serait entièrement nul.
    assert feats.allies[0, 0].abs().sum() > 0, (
        "la ligne alliee 0 est absente de la tranche lue par la tete d'activation"
    )


def test_activate_query_is_distinct_from_the_other_pointers(model):
    """Requête PROPRE à l'activation : perturber `activate_query_net` ne bouge QUE ces slots."""
    policy = model.policy
    policy.set_training_mode(False)
    assert policy.activate_query_net is not policy.query_net
    assert policy.activate_query_net is not policy.deploy_query_net
    assert policy.activate_query_net is not policy.choice_query_net
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        feats = policy._split_features(obs)
        latent_pi = policy.mlp_extractor.forward_actor(feats.trunk)
        before = policy._action_logits(latent_pi, feats)
        policy.activate_query_net.bias.add_(1.0)
        after = policy._action_logits(latent_pi, feats)
        policy.activate_query_net.bias.sub_(1.0)
    changed = torch.nonzero((after - before).abs()[0] > 1e-6).flatten().tolist()
    # Seule la ligne 0 est `present` dans `_zero_obs` : les autres ont un embedding nul, donc un
    # produit scalaire nul quoi qu'il arrive à la requête.
    assert changed == [ACTIVATE_SLOT_BASE], (
        f"la requete d'activation deplace {changed[:5]} — attendu le seul slot OUVERT"
    )


def test_activate_head_costs_nothing_per_slot(model):
    """Le nombre de slots d'activation est GRATUIT en paramètres.

    C'est ce qui rend `K_ALLY_SLOTS = 12` sans coût de capacité : la valeur a été portée de 8 à 12
    pour couvrir des formats plus grands que les rosters courants, et cette gratuité est
    exactement la justification donnée (V11 §0.48 `L2`). Si elle tombait, l'arbitrage tomberait.
    """
    policy = model.policy
    for module in (policy.activate_query_net, policy.features_extractor.unit_encoder):
        for parameter in module.parameters():
            assert ACTIVATE_SLOT_COUNT not in tuple(parameter.shape), (
                "un parametre de la tete d'activation est dimensionne par le nombre de slots"
            )


def test_a_non_binary_phase_flag_raises(model):
    """Le drapeau de phase doit rester 0/1 : normalisé, il ferait router au hasard.

    `global_bin` est hors `norm_obs_keys` (ai/train._vec_norm_obs_keys) précisément pour ça. Si
    cette exclusion tombait, le routage des ids 4-11 ne reposerait plus sur rien — et le seul
    symptôme serait un agent qui déploie mal.
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_deploy_obs(batch=1))
    obs["global_bin"][:, global_bin_index("phase_deployment")] = 0.7
    with pytest.raises(RuntimeError, match="phase_deployment"):
        policy._split_features(obs)


def test_pointer_requires_the_entity_extractor():
    """Sans les embeddings d'entités, la tête pointeur n'a pas de sens : ça doit LEVER."""
    from stable_baselines3.common.torch_layers import CombinedExtractor

    with pytest.raises(TypeError, match="SpatialCombinedExtractor"):
        MaskablePPO(
            PointerMaskablePolicy, _ToyEnv(), device="cpu", verbose=0,
            policy_kwargs={"net_arch": [8], "features_extractor_class": CombinedExtractor},
        )


def test_non_finite_logits_raise_instead_of_poisoning_ppo(model, monkeypatch):
    """Un `-inf` doit LEVER : torch l'accepte, et il rend l'entropie NaN.

    C'est le cas que les contraintes de torch ne couvrent PAS : `-inf` est un logit licite
    (probabilité 0), mais `MaskableCategorical.entropy` calcule `logits * probs`, donc
    `-inf * 0.0 = nan` sur un slot non masqué — le terme d'entropie de PPO devient NaN et
    empoisonne les poids en silence. (`+inf` et `NaN`, eux, sont déjà rejetés par torch, mais
    sa validation entière disparaît sous `python -O` : le contrôle ne s'y délègue pas.)
    """
    logits = torch.zeros((1, TOTAL_ACTION_SIZE), dtype=torch.float32)
    logits[0, 3] = float("-inf")
    unmasked = np.ones((1, TOTAL_ACTION_SIZE), dtype=bool)
    assert torch.isnan(MaskableCategorical(logits=logits, masks=unmasked).entropy()).all(), (
        "sans le controle, ce -inf passe et rend l'entropie NaN"
    )

    monkeypatch.setattr(model.policy, "_action_logits", lambda *_args, **_kwargs: logits)
    with pytest.raises(RuntimeError, match="Non-finite action logits"):
        model.policy._distribution_from(None, None, unmasked)
