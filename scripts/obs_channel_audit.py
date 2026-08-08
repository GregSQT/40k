#!/usr/bin/env python3
"""Audit des canaux d'observation : le MOTEUR les remplit-il, le RÉSEAU les lit-il ?

Deux volets, sur les scénarios d'entraînement réels et le VRAI moteur (aucun mock) :

  (A) MOTEUR — N épisodes en actions masquées aléatoires. Pour chaque clé d'observation et
      chaque CHAMP de son registre (nom lu dans `engine/observation_entities.py`, jamais un
      index recopié) : min, max, nb de valeurs distinctes, fraction non nulle. Un champ à une
      seule valeur distincte sur tout le corpus est un canal que le moteur ne remplit pas.

  (B) RÉSEAU — la vraie policy (`PointerMaskablePolicy` + `SpatialCombinedExtractor`), forward
      sur les observations collectées, puis backward de `Σ logits + Σ valeur`. Un champ dont le
      gradient est EXACTEMENT nul sur tout le lot est reçu mais jamais lu.
      Les clés d'ids (`*_ability_ids`, `*_status_ids`, `*_wpn_rule_ids`) ne sont pas
      différentiables : elles sont vérifiées sur le gradient des LIGNES d'`EmbeddingBag`
      correspondant aux ids réellement observés.

Précaution (sans quoi le volet B ment) : `EntityRunningNorm` clippe à ±10 σ. Avec des
statistiques à l'initialisation (mean=0, var=1), toute feature d'échelle > 10 (PV cumulés,
distances en subhex) saturerait et sortirait un gradient nul — faux positif. On fait donc
tourner quelques passes en mode `train()` pour que les statistiques épousent les données
avant de mesurer, et on rapporte le taux de saturation restant.

Aucune écriture : ni config, ni modèle, ni state. Lecture seule sur le dépôt.

Usage : `python3 scripts/obs_channel_audit.py`  (venv projet activé).
À relancer après tout ajout de champ d'observation : un champ constant sur tout le corpus est un
canal que le moteur ne remplit pas, un champ à gradient nul est un canal que le réseau ne lit pas.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

AGENT = "ArmageddonAgent"
TRAINING_CONFIG = "x1_debug"
BANK = PROJECT_ROOT / "config" / "agents" / AGENT / "scenarios" / "training"
#: Scénarios « pleins » de la banque (roster tiré au sort), un par terrain — DÉCOUVERTS, jamais
#: listés à la main : un scénario ajouté à la banque entre dans le corpus sans toucher ce fichier.
SCENARIOS = sorted(p.name for p in BANK.glob("scenario_training_armageddon*.json"))
SEEDS = tuple(range(1, 13))
MAX_STEPS_PER_EPISODE = 1200
GRAD_BATCH = 192          # observations conservées pour le volet B
DISTINCT_CAP = 12         # au-delà, on cesse de collectionner les valeurs distinctes


# --------------------------------------------------------------------------- registres
def field_names() -> Dict[str, List[str]]:
    """Nom de chaque colonne, par clé d'observation. Source unique = les registres."""
    from engine.observation_entities import (
        DECISION_CTX_BIN_FIELDS,
        DECISION_OPTION_BIN_FIELDS,
        DEPLOY_CAND_BIN_FIELDS,
        DEPLOY_CAND_CONT_FIELDS,
        GLOBAL_BIN_FIELDS,
        GLOBAL_CONT_FIELDS,
        MODEL_TYPE_BIN_FIELDS,
        MODEL_TYPE_CONT_FIELDS,
        SELF_MODEL_BIN_FIELDS,
        SELF_MODEL_CONT_FIELDS,
        UNIT_ABILITY_SLOTS,
        UNIT_BIN_FIELDS,
        UNIT_CONT_FIELDS,
        UNIT_STATUS_SLOTS,
    )
    from engine.observation_weapon_profiles import (
        PROFILE_BIN_SIZE,
        PROFILE_CONT_SIZE,
        WEAPON_RULE_ID_SLOTS,
        WEAPON_RULE_PARAMS,
    )
    from engine.spatial_grid import GRID_CHANNEL_NAMES

    # Le registre d'armes n'exporte pas de tuple de NOMS (son layout est décrit en commentaire
    # de `PROFILE_STAT_CONT`) : on le reconstruit ici depuis les constantes réelles, et on
    # vérifie la longueur — un layout qui bougerait ferait lever, pas dériver les libellés.
    profile_cont = (
        ["nb", "atk", "str", "ap", "dmg", "range", "carriers"]
        + [f"param_{name.lower()}" for name, _default in WEAPON_RULE_PARAMS]
        + ["anti_threshold"]
    )
    if len(profile_cont) != PROFILE_CONT_SIZE or PROFILE_BIN_SIZE != 1:
        raise ValueError(
            f"Layout de profil d'arme inattendu : {len(profile_cont)} libelles pour "
            f"PROFILE_CONT_SIZE={PROFILE_CONT_SIZE}, PROFILE_BIN_SIZE={PROFILE_BIN_SIZE}"
        )
    profile_bin = ["present"]

    names: Dict[str, List[str]] = {
        "global_cont": list(GLOBAL_CONT_FIELDS),
        "global_bin": list(GLOBAL_BIN_FIELDS),
        "self_models_cont": list(SELF_MODEL_CONT_FIELDS),
        "self_models_bin": list(SELF_MODEL_BIN_FIELDS),
        "decision_ctx_bin": list(DECISION_CTX_BIN_FIELDS),
        "decision_options_bin": list(DECISION_OPTION_BIN_FIELDS),
        "deploy_cand_cont": list(DEPLOY_CAND_CONT_FIELDS),
        "deploy_cand_bin": list(DEPLOY_CAND_BIN_FIELDS),
        # LUS depuis `spatial_grid`, jamais recopiés : le seul livrable de cet audit est de NOMMER
        # le canal mort, donc un libellé décalé enverrait corriger un canal sain.
        "grid": list(GRID_CHANNEL_NAMES),
    }
    for family in ("allies", "enemies"):
        names[f"{family}_cont"] = list(UNIT_CONT_FIELDS)
        names[f"{family}_bin"] = list(UNIT_BIN_FIELDS)
        names[f"{family}_ability_ids"] = [f"slot{i}" for i in range(UNIT_ABILITY_SLOTS)]
        names[f"{family}_status_ids"] = [f"slot{i}" for i in range(UNIT_STATUS_SLOTS)]
        names[f"{family}_wpn_cont"] = list(profile_cont)
        names[f"{family}_wpn_bin"] = list(profile_bin)
        names[f"{family}_wpn_rule_ids"] = [f"slot{i}" for i in range(WEAPON_RULE_ID_SLOTS)]
        names[f"{family}_types_cont"] = list(MODEL_TYPE_CONT_FIELDS)
        names[f"{family}_types_bin"] = list(MODEL_TYPE_BIN_FIELDS)
    return names


def _field_axis(key: str, *, batched: bool = False) -> int:
    """Axe des CHAMPS : 0 pour la grille (canal), dernier axe pour tout le reste.

    `batched=True` : le tenseur porte le lot en tête, ce qui décale l'axe de la grille d'un cran
    (le dernier axe, lui, reste le dernier). Écrit ICI plutôt que re-dérivé par arithmétique au
    site d'appel, où la table à deux cas devait être reconstituée de tête.
    """
    if key == "grid":
        return 1 if batched else 0
    return -1


def _labels(names: Dict[str, List[str]], key: str) -> List[str]:
    """Libellés d'une clé d'observation — LÈVE si la clé n'est pas au registre.

    Aucun repli en libellés numériques : cet outil existe pour NOMMER les canaux morts, donc une
    clé ajoutée à l'observation et oubliée ici doit faire échouer l'audit, pas sortir en `[7]`
    dans un rapport qu'on lira comme complet.
    """
    if key not in names:
        raise KeyError(
            f"Cle d'observation '{key}' absente de `field_names()` : ajouter son registre de "
            f"libelles. Cles connues : {sorted(names)}"
        )
    return names[key]


# --------------------------------------------------------------------------- volet A
class FieldStats:
    """Statistiques par champ, accumulées en ligne (aucune observation n'est conservée).

    La CONSTANCE d'un champ se lit sur `lo == hi` — pas sur un ensemble de valeurs distinctes,
    qui répondait à la même question pour 88 % du coût de `update` (mesuré : 11,7 ms l'appel
    complet, 1,35 ms sans, × 254 champs × ~4 000 steps). L'ensemble n'est donc conservé que pour
    la clé qui en RAPPORTE le cardinal — la grille —, et borné par `DISTINCT_CAP`.
    """

    def __init__(self, n_fields: int, *, track_distinct: bool = False):
        self.lo = np.full(n_fields, np.inf, dtype=np.float64)
        self.hi = np.full(n_fields, -np.inf, dtype=np.float64)
        self.nonzero = np.zeros(n_fields, dtype=np.int64)
        self.total = np.zeros(n_fields, dtype=np.int64)
        self.distinct: Optional[List[set]] = (
            [set() for _ in range(n_fields)] if track_distinct else None
        )

    def update(self, flat: np.ndarray) -> None:
        """`flat` : (n_fields, n_samples)."""
        self.lo = np.minimum(self.lo, flat.min(axis=1))
        self.hi = np.maximum(self.hi, flat.max(axis=1))
        self.nonzero += (flat != 0.0).sum(axis=1)
        self.total += flat.shape[1]
        if self.distinct is None:
            return
        for i, values in enumerate(self.distinct):
            if len(values) <= DISTINCT_CAP:
                values.update(np.unique(np.round(flat[i], 6)).tolist())

    def is_constant(self, i: int) -> bool:
        """Le champ `i` n'a pris qu'une seule valeur sur tout le corpus."""
        return bool(self.lo[i] == self.hi[i])


class Reservoir:
    """Échantillon UNIFORME d'observations pour le volet B, sur tout le corpus.

    Le lot doit couvrir toutes les phases, pas seulement le début du premier épisode
    (déploiement + move) : sans cela les champs de combat sortiraient « non lus » faute d'avoir
    été échantillonnés. Objet et non état de module : l'audit peut être rejoué dans le même
    processus sans traîner le compteur du run précédent.
    """

    def __init__(self, capacity: int, seed: int = 20260808):
        self.capacity = int(capacity)
        self.rng = np.random.default_rng(seed)
        self.seen = 0
        self.kept: List[Dict[str, np.ndarray]] = []

    def offer(self, observation: Dict[str, np.ndarray]) -> None:
        self.seen += 1
        if len(self.kept) < self.capacity:
            self.kept.append(self._copy(observation))
            return
        j = int(self.rng.integers(0, self.seen))
        if j < self.capacity:
            self.kept[j] = self._copy(observation)

    @staticmethod
    def _copy(observation: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        return {k: np.array(v, copy=True) for k, v in observation.items()}


def _to_fields(key: str, arr: np.ndarray) -> np.ndarray:
    """(…) -> (n_fields, n_samples), l'axe des champs ramené en tête."""
    moved = np.moveaxis(arr, _field_axis(key), 0)
    return moved.reshape(moved.shape[0], -1).astype(np.float64)


def make_engine(scenario: str):
    """Moteur d'audit sur `scenario`. UN site de construction, partagé par les deux volets.

    Le volet B lit `observation_space` / `action_space` sur un moteur : le construire à part
    laisserait deux configurations libres de diverger alors que le rapport CROISE leurs résultats
    (« déjà constant en A »).
    """
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    return W40KEngine(
        rewards_config=AGENT,
        training_config_name=TRAINING_CONFIG,
        controlled_agent=AGENT,
        scenario_file=str(BANK / scenario),
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )


def collect(eng, stats: Dict[str, FieldStats], reservoir: Reservoir, seed: int) -> dict:
    """Un épisode. Le moteur est RÉUTILISÉ d'une graine à l'autre : `reset(seed=)` retire le
    roster et refait la géométrie, alors qu'une construction coûte ~1,1 s (mesuré) — 24 pour un
    corpus qui n'en demande qu'une par scénario."""
    obs, _info = eng.reset(seed=seed)
    rng = np.random.default_rng(seed * 7919 + 13)
    phases = defaultdict(int)
    steps = 0

    def absorb(observation: Dict[str, np.ndarray]) -> None:
        for key, arr in observation.items():
            if key not in stats:
                stats[key] = FieldStats(
                    arr.shape[_field_axis(key)], track_distinct=(key == "grid")
                )
            stats[key].update(_to_fields(key, arr))
        reservoir.offer(observation)

    absorb(obs)
    while steps < MAX_STEPS_PER_EPISODE:
        gs = eng.game_state
        if gs.get("game_over"):
            break
        mask = eng.get_action_mask()
        if not mask.any():
            break
        phases[str(gs.get("phase"))] += 1
        action = int(rng.choice(np.flatnonzero(mask)))
        obs, _r, term, trunc, _i = eng.step(action)
        steps += 1
        # `step` ne rend `None` que sous `defer_observation`, que cet audit ne demande jamais :
        # un `None` ici signifierait que l'observation mesurée n'est pas celle du moteur.
        if obs is None:
            raise RuntimeError(
                f"observation reportée (defer_observation) au step {steps} — "
                f"l'audit ne peut pas mesurer un canal qu'il n'a pas reçu"
            )
        absorb(obs)
        if term or trunc:
            break
    return {"steps": steps, "phases": dict(phases)}


# --------------------------------------------------------------------------- volet B
ID_KEYS = {
    "allies_ability_ids": "ability_embedding",
    "enemies_ability_ids": "ability_embedding",
    "allies_status_ids": "status_embedding",
    "enemies_status_ids": "status_embedding",
    "allies_wpn_rule_ids": "weapon_rule_embedding",
    "enemies_wpn_rule_ids": "weapon_rule_embedding",
}


def gradient_pass(eng, keep: List[Dict[str, np.ndarray]]):
    """Gradient de `Σ logits + Σ valeur` par rapport à chaque champ d'observation."""
    import torch

    from ai.pointer_policy import PointerMaskablePolicy
    from ai.spatial_extractor import SpatialCombinedExtractor
    from shared.data_validation import require_key

    # Architecture LUE dans la config de l'agent, jamais recopiée : c'est la règle que
    # `ai/train._inject_spatial_extractor` fait respecter au training (`cnn_features` y est
    # `require_key`, sans valeur par défaut). Recopiée ici, une config qui changerait de largeur
    # ferait mesurer un réseau que personne n'entraîne — et rendre « canal non lu » sur une
    # architecture fantôme.
    model_params = require_key(require_key(eng.training_config, "model_params"), "policy_kwargs")
    fx_kwargs = require_key(model_params, "features_extractor_kwargs")
    torch.manual_seed(0)
    policy = PointerMaskablePolicy(
        eng.observation_space,
        eng.action_space,
        lambda _progress: 3e-4,
        net_arch=require_key(model_params, "net_arch"),
        features_extractor_class=SpatialCombinedExtractor,
        features_extractor_kwargs={"cnn_features": require_key(fx_kwargs, "cnn_features")},
    )

    batch = {
        key: torch.as_tensor(np.stack([o[key] for o in keep]), dtype=torch.float32)
        for key in keep[0]
    }

    # Épouser les statistiques des données AVANT de mesurer : à l'initialisation
    # (mean=0, var=1) le clip ±10σ de `EntityRunningNorm` saturerait toute feature d'échelle
    # > 10 et lui donnerait un gradient nul — faux positif.
    #
    # UNE passe suffit, et ce n'est pas une approximation : `EntityRunningNorm` est un
    # accumulateur de Chan initialisé à `count=1e-4`, pas une moyenne mobile à momentum — la
    # première passe pose déjà la moyenne et la variance EXACTES du lot. Vérifié par mesure :
    # `unit_norm.running_mean`/`running_var` identiques à 1e-6 près après 1, 2 et 8 passes (seul
    # `count` monte). Les 7 passes suivantes coûtaient 1,5 s pour ne rien changer.
    policy.train()
    with torch.no_grad():
        policy.extract_features(batch)
    policy.eval()

    inputs = {k: v.clone().requires_grad_(k not in ID_KEYS) for k, v in batch.items()}
    feats = policy._split_features(inputs)
    latent_pi, latent_vf = policy.mlp_extractor(feats.trunk)
    logits = policy._action_logits(latent_pi, feats)
    value = policy.value_net(latent_vf)
    (logits.sum() + value.sum()).backward()

    grads: Dict[str, np.ndarray] = {}
    for key, tensor in inputs.items():
        if key in ID_KEYS:
            continue
        if tensor.grad is None:
            grads[key] = np.zeros(tensor.shape[_field_axis(key)])
            continue
        g = np.abs(tensor.grad.detach().numpy())
        moved = np.moveaxis(g, _field_axis(key, batched=True), 0)
        grads[key] = moved.reshape(moved.shape[0], -1).sum(axis=1)

    # Clés d'ids : gradient des LIGNES d'embedding correspondant aux ids observés.
    extractor = policy.features_extractor
    id_report = {}
    for key, table_name in ID_KEYS.items():
        table = getattr(extractor, table_name)
        weight_grad = table.weight.grad
        ids = np.unique(batch[key].numpy().astype(np.int64))
        ids = ids[ids != 0]
        if weight_grad is None:
            id_report[key] = (ids.tolist(), 0)
            continue
        rows = np.abs(weight_grad.detach().numpy()).sum(axis=1)
        touched = int(sum(1 for i in ids if rows[int(i)] > 0.0))
        id_report[key] = (ids.tolist(), touched)

    # Taux de saturation du clip, pour ne pas confondre « non lu » et « écrasé par le clip ».
    # `None` = NON MESURÉ (aucune entité présente dans le lot), à ne surtout pas confondre avec
    # « rien ne sature » : une moyenne sur un tenseur vide rend NaN, que le filtre `v > 0.0` du
    # rapport laisse passer pour « aucune ».
    sat: Dict[str, Optional[np.ndarray]] = {}
    for name, norm_key, mask_key in (
        ("unit_norm", "allies_cont", "allies_bin"),
        ("weapon_norm", "allies_wpn_cont", "allies_wpn_bin"),
        ("type_norm", "allies_types_cont", "allies_types_bin"),
        ("self_model_norm", "self_models_cont", "self_models_bin"),
        ("deploy_cand_norm", "deploy_cand_cont", "deploy_cand_bin"),
    ):
        norm = getattr(extractor, name)
        # ENTITÉS PRÉSENTES SEULEMENT (`present` = dernier champ, convention §0.37). Compter les
        # lignes de padding ferait passer pour « saturée » toute feature dont la valeur des
        # entités réelles est proche d'une constante : leur 0 de padding tombe alors à des
        # dizaines de σ de la moyenne, alors que `EntityRunningNorm` les annule de toute façon.
        present = batch[mask_key][..., -1] > 0
        if not present.any():
            sat[norm_key] = None
            continue
        x = batch[norm_key][present]
        normed = (x - norm.running_mean) / torch.sqrt(norm.running_var + norm.epsilon)
        over = (normed.abs() > norm.clip).float()
        # PAR CHAMP : un taux global ne dit pas QUELLE feature sature, or c'est elle seule qui
        # perd de l'information au clip.
        sat[norm_key] = over.reshape(-1, over.shape[-1]).mean(dim=0).numpy()
    return grads, id_report, sat


# --------------------------------------------------------------------------- rapport
def main() -> int:
    names = field_names()
    stats: Dict[str, FieldStats] = {}
    reservoir = Reservoir(GRAD_BATCH)
    engines = {}
    print("=== (A) MOTEUR — collecte ===", flush=True)
    for scenario in SCENARIOS:
        engines[scenario] = make_engine(scenario)
        for seed in SEEDS:
            r = collect(engines[scenario], stats, reservoir, seed)
            print(f"  {scenario} seed={seed}: {r['steps']} steps, phases={r['phases']}",
                  flush=True)

    print("\n=== (A) champs CONSTANTS sur tout le corpus ===")
    dead_any = False
    for key in sorted(stats):
        st = stats[key]
        labels = _labels(names, key)
        for i in range(len(st.lo)):
            if st.is_constant(i):
                dead_any = True
                print(f"  {key}.{labels[i]:<32} constant = {st.lo[i]:g}")
    if not dead_any:
        print("  (aucun)")

    print("\n=== (A) grille : couverture par canal ===")
    g = stats["grid"]
    assert g.distinct is not None  # `track_distinct=True` pour cette clé, et elle seule
    for i, label in enumerate(_labels(names, "grid")):
        frac = g.nonzero[i] / max(1, g.total[i])
        print(f"  canal {i} {label:<10} min={g.lo[i]:<8.3g} max={g.hi[i]:<8.3g} "
              f"non nul={frac:.4%} distinct={min(len(g.distinct[i]), DISTINCT_CAP + 1)}")

    keep = reservoir.kept
    print(f"\n=== (B) RÉSEAU — gradient sur {len(keep)} observations ===", flush=True)
    grads, id_report, sat = gradient_pass(engines[SCENARIOS[0]], keep)
    print("  saturation du clip par champ (>0 = information ecrasee) :")
    for key, per_field in sat.items():
        if per_field is None:
            print(f"    {key:<24} NON MESURE (0 entite presente sur le lot)")
            continue
        labels = _labels(names, key)
        hits = [(labels[i], v) for i, v in enumerate(per_field) if v > 0.0]
        if not hits:
            print(f"    {key:<24} aucune")
            continue
        for label, value in sorted(hits, key=lambda t: -t[1]):
            print(f"    {key}.{label:<28} {value:.2%}")

    print("\n=== (B) champs à gradient EXACTEMENT nul ===")
    silent_any = False
    for key in sorted(grads):
        labels = _labels(names, key)
        st = stats[key]
        for i, value in enumerate(grads[key]):
            if value != 0.0:
                continue
            silent_any = True
            note = (
                " (déjà constant en A)" if st.is_constant(i)
                else "  <-- VARIABLE mais NON LU"
            )
            print(f"  {key}.{labels[i]:<32} grad=0{note}")
    if not silent_any:
        print("  (aucun)")

    print("\n=== (B) clés d'ids : lignes d'embedding touchées ===")
    for key, (ids, touched) in sorted(id_report.items()):
        state = "OK" if touched == len(ids) and ids else ("AUCUN ID OBSERVÉ" if not ids else "PARTIEL")
        print(f"  {key:<26} ids observés={len(ids)} lignes avec gradient={touched}  {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
