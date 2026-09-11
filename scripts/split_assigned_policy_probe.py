#!/usr/bin/env python3
"""La politique EXPLOITE-t-elle les bits `split_assigned_w<i>`, ou les reçoit-elle sans s'en servir ?

`scripts/obs_channel_audit.py` répond déjà à deux questions voisines et NE répond pas à celle-ci :
le moteur remplit-il le canal (volet A), le réseau le lit-il au sens du gradient (volet B). Un
gradient non nul ne prouve QUE le câblage : la dérivée d'une couche linéaire par rapport à une
entrée vaut son poids, elle est non nulle même pour une entrée toujours à zéro. La question qui
reste — la DÉCISION change-t-elle quand l'arme déjà engagée change de cible — se mesure sur la
distribution d'actions, et seulement sur un modèle ENTRAÎNÉ. Elle se pose aux DEUX sous-états du
tir fractionné, et la sonde les mesure SÉPARÉMENT : au sous-état ARME (« laquelle j'engage
ensuite »), au sous-état CIBLE (« sur qui je la pointe »). Ne mesurer que le second rendrait un
verdict portant sur la moitié du mécanisme — c'est ce que faisait cette sonde avant le
2026-09-11, et le verdict « pas exploités » qu'elle a servi ce jour-là ne valait que pour CIBLE.

MÉTHODE. Sur de vrais états de jeu (scénarios d'entraînement, actions masquées aléatoires), on
s'arrête à chaque point d'arrêt du tir fractionné — ARME comme CIBLE — portant déjà au moins un
couple arme→cible. Là, on construit un CONTREFACTUEL : le même état, à ceci près que le couple déjà
commité vise une AUTRE escouade ennemie éligible. Les deux observations ne diffèrent alors que par
les bits `split_assigned_w<i>` — c'est mesuré ici, pas supposé (`--strict` lève si une autre clé
bouge). On compare les distributions d'actions de la politique sur ces deux observations, en
distance de variation totale (TVD), restreinte aux actions LÉGALES.

POURQUOI DEUX TÉMOINS, sans quoi le nombre ne veut rien dire :

  PLANCHER  — la même observation contre elle-même. Doit valoir EXACTEMENT 0. Un plancher non nul
              dénoncerait du non-déterminisme dans la sonde, et tout le reste serait du bruit.
  RÉFÉRENCE — la même mesure quand les deux escouades ennemies ÉCHANGENT leurs caractéristiques
              (ligne continue et drapeaux, les dix bits exceptés). Le choix de cible en dépend par
              construction du jeu, et l'échange garde deux unités RÉELLES du même état : aucune
              valeur contradictoire, donc aucun étalon gonflé par une observation impossible. Elle
              donne l'ordre de grandeur d'« un champ que la politique utilise » sur ces mêmes
              états. Sans elle, un TVD de 0,004 est illisible : proche du plancher, ou déjà
              l'ampleur d'un champ décisif ?

LECTURE DU VERDICT :
  TVD_split ≈ plancher                      -> câblés mais INEXPLOITÉS.
  TVD_split de l'ordre de TVD_référence     -> exploités.
  entre les deux                            -> à rapporter tel quel, avec les trois nombres.

Le nombre d'ACTIONS LÉGALES des points mesurés est rapporté avec eux : une TVD faible sur un
masque large peut venir de la dilution sur des actions sans rapport, et non de l'indifférence de
la politique.

La sonde n'écrit rien : ni config, ni modèle, ni state. Elle ne juge pas non plus « bon » ou
« mauvais » — elle rend des nombres, par sous-état puis réunis.

Usage :
    python3 scripts/split_assigned_policy_probe.py --model ai/models/<agent>/model_<agent>.zip
    python3 scripts/split_assigned_policy_probe.py           # politique NON entraînée : valide
                                                             # l'instrument, ne conclut sur rien
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# UN SEUL site de construction du moteur d'audit, partagé avec `obs_channel_audit` : deux
# constructions libres de diverger feraient porter aux deux sondes des verdicts non comparables,
# alors qu'on les lit côte à côte.
from scripts.obs_channel_audit import MAX_STEPS_PER_EPISODE, SCENARIOS, make_engine
from engine.action_decoder import PENDING_SHOOT_WEAPON_SEL_KEY
from engine.observation_entities import (
    K_WEAPONS_RANGED,
    split_assigned_field,
    unit_bin_index,
)
from shared.data_validation import require_key

#: Colonnes des dix bits, lues du registre — jamais un index recopié.
SPLIT_BIT_IDX: Tuple[int, ...] = tuple(
    unit_bin_index(split_assigned_field(i)) for i in range(K_WEAPONS_RANGED)
)


def _tvd(p: np.ndarray, q: np.ndarray) -> float:
    """Distance de variation totale entre deux distributions d'actions."""
    return float(0.5 * np.abs(p - q).sum())


def _action_probs(dist: Any) -> np.ndarray:
    """Le vecteur de probabilités INDEXÉ PAR ID D'ACTION que porte `dist`.

    C'est la forme d'une distribution catégorielle masquée, celle qu'exige déjà
    `PointerMaskablePolicy` (ai/pointer_policy.py). Une distribution multi-catégorielle porte à la
    place une LISTE de facteurs : les probabilités par action n'en sortent pas telles quelles, et
    un TVD calculé dessus mesurerait autre chose que le choix d'action. La sonde le dit plutôt que
    de rendre un nombre qui ne répond pas à sa question.
    """
    from sb3_contrib.common.maskable.distributions import MaskableCategoricalDistribution

    if not isinstance(dist, MaskableCategoricalDistribution):
        raise TypeError(
            "La sonde compare des probabilités par action et exige donc une "
            f"distribution catégorielle masquée (reçue : {type(dist).__name__})."
        )
    return dist.distribution.probs.cpu().numpy()[0].astype(np.float64)


class _Policy:
    """La politique interrogée : un modèle entraîné, ou une politique NON entraînée.

    La seconde ne sert qu'à valider l'instrument (le plancher tombe-t-il à 0, la référence
    sort-elle un nombre) : ses poids sont aléatoires, donc AUCUN de ses TVD ne dit quoi que ce
    soit sur l'exploitation. La sonde le rappelle dans son rapport plutôt que de laisser un
    lecteur pressé prendre un bruit d'initialisation pour un verdict.
    """

    def __init__(self, model_path: Optional[str], eng: Any) -> None:
        import torch
        from shared.torch_safe_globals import register_torch_safe_globals

        register_torch_safe_globals()
        self.torch = torch
        self.trained = model_path is not None
        from sb3_contrib import MaskablePPO

        self.normalize = None
        if model_path is not None:
            self.model = MaskablePPO.load(model_path, device="cpu")
            # NORMALISATION : le modèle a été entraîné derrière `VecNormalize`. L'interroger sur
            # une observation BRUTE lui donne des grandeurs hors de sa distribution, et le TVD
            # mesuré serait celui d'un réseau en terrain inconnu — pas celui de la politique.
            # Même chargement que le self-play gelé (`ai/env_wrappers.py:1060`).
            from ai.vec_normalize_utils import build_snapshot_normalizer

            self.normalize = build_snapshot_normalizer(model_path, True, True)
        else:
            import gymnasium as gym
            from ai.pointer_policy import PointerMaskablePolicy
            from ai.spatial_extractor import SpatialCombinedExtractor

            class _Env(gym.Env):
                observation_space = eng.observation_space
                action_space = eng.action_space

                def reset(self, *, seed=None, options=None):
                    return self.observation_space.sample(), {}

                def step(self, action):
                    return self.observation_space.sample(), 0.0, False, False, {}

                def action_masks(self):
                    return np.ones(int(eng.action_space.n), dtype=bool)

            # La VRAIE architecture, et non `MultiInputPolicy` : valider l'instrument sur un
            # extracteur qui n'est pas celui du projet ne prouverait rien de l'instrument.
            self.model = MaskablePPO(
                PointerMaskablePolicy, _Env(), device="cpu", n_steps=8, batch_size=8, verbose=0,
                policy_kwargs={
                    "features_extractor_class": SpatialCombinedExtractor,
                    "features_extractor_kwargs": {"cnn_features": 32},
                },
            )
        self.model.policy.set_training_mode(False)

    def distribution(self, obs: Dict[str, np.ndarray], mask: np.ndarray) -> np.ndarray:
        """Probabilités d'action, masque appliqué. Déterministe : aucun tirage."""
        torch = self.torch
        if self.normalize is not None:
            normed = self.normalize({k: v[None, ...] for k, v in obs.items()})
            batch = {k: torch.as_tensor(np.asarray(v)) for k, v in normed.items()}
        else:
            batch = {k: torch.as_tensor(v[None, ...]) for k, v in obs.items()}
        with torch.no_grad():
            dist = self.model.policy.get_distribution(
                batch, action_masks=mask[None, :].copy()
            )
            return _action_probs(dist)


def _other_eligible_target(game_state: Dict[str, Any], squad_id: str, weapon_slot: int,
                           assigned_target: str,
                           enemy_slot_ids: List[Optional[str]]) -> Optional[str]:
    """Une autre cible que le moteur aurait RÉELLEMENT pu donner à CETTE arme.

    L'éligibilité est recalculée par la fonction du moteur pour le slot d'arme du couple déjà
    commité — et non empruntée à `pending["eligible_target_slots"]`, qui décrit l'arme ENCORE en
    attente, une autre arme donc une autre portée. Prendre le premier ennemi venu fabriquerait un
    état que le moteur ne peut pas produire (cible hors de portée de cette arme-là), et le TVD
    serait alors mesuré hors distribution : le réseau réagirait à une situation impossible.
    """
    from engine.phase_handlers.shared_utils import shoot_weapon_eligible_target_slots

    _code, eligible = shoot_weapon_eligible_target_slots(
        game_state, squad_id, int(weapon_slot), enemy_slot_ids
    )
    for slot_i in eligible:
        tsid = enemy_slot_ids[slot_i]
        if tsid is not None and str(tsid) != str(assigned_target):
            return str(tsid)
    return None


def _observation(eng: Any, squad_id: str) -> Dict[str, np.ndarray]:
    """L'observation COMPLÈTE d'une escouade, grille comprise, et DÉTACHÉE du moteur.

    Même assemblage que `_build_for_squad` dans `W40KEngine._build_observation_and_mask` : le bloc
    d'entités remplit le scratch, la grille s'écrit dans `full["grid"]`. La reconstruire ici de
    façon plus courte (bloc d'entités seul) donnerait une observation SANS grille, que la policy
    refuse — et l'oubli passerait pour un défaut du modèle.

    La copie profonde n'est pas une précaution de style : le moteur rend son SCRATCH, réécrit à
    l'appel suivant. Sans copie, `obs_a` et `obs_b` seraient le même tableau et tous les TVD
    vaudraient 0 — un « inexploité » entièrement fabriqué par la sonde.
    """
    eng.obs_builder.build_squad_observation(eng.game_state, squad_id)
    full = eng.obs_builder._ensure_full_obs_scratch()
    eng.obs_builder.build_squad_grid(eng.game_state, squad_id, out=full["grid"])
    return {k: np.array(v, copy=True) for k, v in full.items()}


def _keys_differing(a: Dict[str, np.ndarray], b: Dict[str, np.ndarray]) -> List[str]:
    return [k for k in a if not np.array_equal(a[k], b[k])]


def _bits_only(a: Dict[str, np.ndarray], b: Dict[str, np.ndarray]) -> bool:
    """Les deux observations ne diffèrent-elles QUE par les dix bits ?

    Vérifié et non supposé : si une autre colonne bougeait, le TVD mesurerait cette colonne-là
    en plus, et le verdict serait faux dans le sens FAVORABLE — le pire des deux.
    """
    diff = _keys_differing(a, b)
    if diff not in (["enemies_bin"], []):
        return False
    x, y = a["enemies_bin"].copy(), b["enemies_bin"].copy()
    x[:, list(SPLIT_BIT_IDX)] = 0.0
    y[:, list(SPLIT_BIT_IDX)] = 0.0
    return bool(np.array_equal(x, y))


def collect(eng: Any, policy: _Policy, seed: int, strict: bool) -> List[Dict[str, Any]]:
    """Un épisode : un enregistrement par point d'arrêt de CIBLE portant déjà un couple."""
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    obs, _info = eng.reset(seed=seed)
    rng = np.random.default_rng(seed * 7919 + 13)
    out: List[Dict[str, Any]] = []
    steps = 0
    while steps < MAX_STEPS_PER_EPISODE:
        gs = eng.game_state
        if gs.get("game_over"):  # get allowed : clé absente = partie en cours
            break
        mask = eng.get_action_mask()
        if not mask.any():
            break

        # LES DEUX SOUS-ÉTATS. Les bits sont posés dans l'un comme dans l'autre, et l'usage le
        # plus direct de l'information est celui que le filtre d'origine excluait : au sous-état
        # ARME, « quelle arme j'engage ensuite sachant ce qui est déjà parti et sur qui ». Ne
        # mesurer que la CIBLE rendait un verdict portant sur la moitié du mécanisme.
        pending = gs.get(PENDING_SHOOT_WEAPON_SEL_KEY)  # get allowed : None = aucun split-fire
        if pending is not None and pending.get("assignments"):  # get allowed : couple commité
            # get allowed : `pending_weapon` armé = sous-état CIBLE, absent = sous-état ARME.
            sous_etat = "CIBLE" if pending.get("pending_weapon") is not None else "ARME"
            rec = _measure(eng, policy, pending, mask, strict)
            if rec is not None:
                rec["sous_etat"] = sous_etat
                out.append(rec)

        obs, _r, term, trunc, _i = eng.step(int(rng.choice(np.flatnonzero(mask))))
        steps += 1
        if term or trunc:
            break
    return out


def _measure(eng: Any, policy: _Policy, pending: Dict[str, Any], mask: np.ndarray,
             strict: bool) -> Optional[Dict[str, Any]]:
    """Les trois TVD sur UN point d'arrêt. `None` si l'état ne s'y prête pas."""
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    squad_id = str(require_key(pending, "squad_id"))
    units_cache = require_key(eng.game_state, "units_cache")
    entry = require_key(units_cache, squad_id)
    enemy_slots = get_enemy_slot_mapping(eng.game_state, int(require_key(entry, "player")))

    # Un point d'arrêt à UNE seule action légale ne porte aucune information : la distribution y
    # vaut 1 sur cette action quoi qu'on perturbe, et le TVD y est nul par construction. Les
    # compter diluerait la moyenne et ferait passer un effet réel pour une absence d'effet —
    # c'est la version « mesure » du test vert vacant. Comptés à part, jamais silencieusement.
    if int(np.count_nonzero(mask)) < 2:
        return {"degenere": 1.0}

    wcode = sorted(require_key(pending, "assignments"))[0]
    assign = require_key(require_key(pending, "assignments"), wcode)
    assigned = str(require_key(assign, "target_id"))
    other = _other_eligible_target(
        eng.game_state, squad_id, int(require_key(assign, "weapon_slot")), assigned, enemy_slots
    )
    if other is None:
        return {"sans_autre_cible": 1.0}

    obs_a = _observation(eng, squad_id)
    assign["target_id"] = other
    obs_b = _observation(eng, squad_id)
    assign["target_id"] = assigned  # état RENDU tel quel : la sonde ne joue pas la partie

    # Deux observations IDENTIQUES ne sont pas une contrefactuelle pure : c'est une régression de
    # câblage (les bits ne suivent plus la cible). Sans ce refus, `tvd_split` vaudrait 0 partout
    # et le rapport se lirait « câblés mais INEXPLOITÉS » — le verdict le plus grave, rendu par
    # une panne de la sonde plutôt que par la politique.
    if not _keys_differing(obs_a, obs_b):
        raise RuntimeError(
            f"les bits ne suivent plus la cible sur {squad_id!r} : déplacer le couple de "
            f"{assigned!r} vers {other!r} laisse l'observation INCHANGÉE"
        )
    if not _bits_only(obs_a, obs_b):
        if strict:
            raise RuntimeError(
                f"contrefactuelle impure sur {squad_id!r} : clés différentes "
                f"{_keys_differing(obs_a, obs_b)} — le TVD mesurerait autre chose que les bits"
            )
        return {"impure": 1.0}

    # RÉFÉRENCE : les deux escouades ennemies ÉCHANGENT leurs caractéristiques — toute la ligne
    # continue ET la ligne de drapeaux, les dix bits exceptés. Un échange, et non une valeur
    # forcée : mettre `hp_total` à 0 en laissant `alive_models`, `hp_max` et `present` intacts
    # fabriquerait une escouade contradictoire, que le réseau n'a jamais vue à l'entraînement —
    # l'étalon sortirait gonflé et ferait passer les bits pour inertes par comparaison. Ici les
    # deux lignes restent des unités RÉELLES du même état, seule leur place change.
    obs_ref = {k: np.array(v, copy=True) for k, v in obs_a.items()}
    row = next(
        (i for i, tsid in enumerate(enemy_slots) if tsid is not None and str(tsid) == assigned),
        None,
    )
    row_other = next(
        (i for i, tsid in enumerate(enemy_slots) if tsid is not None and str(tsid) == other),
        None,
    )
    if row is None or row_other is None:
        raise RuntimeError(
            f"cible {assigned!r} ou {other!r} absente du mapping de slots ennemis de "
            f"{squad_id!r} — l'observation ne pourrait pas porter son bit"
        )
    keep = [c for c in range(obs_ref["enemies_bin"].shape[1]) if c not in set(SPLIT_BIT_IDX)]
    for key, cols in (("enemies_cont", None), ("enemies_bin", keep)):
        block = obs_ref[key]
        sel = slice(None) if cols is None else cols
        a_row = block[row, sel].copy()
        block[row, sel] = block[row_other, sel]
        block[row_other, sel] = a_row

    # SATURATION : tout le bloc continu ennemi mis à zéro. Aucune signification tactique — c'est
    # un contrôle d'INSTRUMENT. Si même cette perturbation-là ne bouge pas la distribution, la
    # sonde ne peut RIEN détecter, et un « TVD split nul » ne voudrait pas dire « inexploité »
    # mais « sonde muette ». `main` refuse de conclure dans ce cas.
    obs_sat = {k: np.array(v, copy=True) for k, v in obs_a.items()}
    obs_sat["enemies_cont"][:, :] = 0.0

    p_a = policy.distribution(obs_a, mask)
    p_b = policy.distribution(obs_b, mask)
    p_a2 = policy.distribution(obs_a, mask)
    p_ref = policy.distribution(obs_ref, mask)
    p_sat = policy.distribution(obs_sat, mask)
    return {
        # Nombre d'actions LÉGALES : sans lui, une TVD faible se lit mal — elle peut venir d'un
        # masque large qui dilue la mesure sur des actions sans rapport avec le choix, et non de
        # l'indifférence de la politique.
        "n_actions_legales": float(np.count_nonzero(mask)),
        "tvd_split": _tvd(p_a, p_b),
        "tvd_plancher": _tvd(p_a, p_a2),
        "tvd_reference": _tvd(p_a, p_ref),
        "tvd_saturation": _tvd(p_a, p_sat),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=None,
                    help="modèle entraîné ; absent = politique non entraînée (valide l'instrument)")
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--strict", action="store_true",
                    help="lève si une contrefactuelle fait bouger autre chose que les dix bits")
    args = ap.parse_args()

    records: List[Dict[str, Any]] = []
    policy: Optional[_Policy] = None
    for scenario in SCENARIOS:
        eng = make_engine(scenario)
        if policy is None:
            policy = _Policy(args.model, eng)
        for seed in range(1, args.seeds + 1):
            records.extend(collect(eng, policy, seed, args.strict))

    # Chaque motif d'écart est COMPTÉ et affiché. Un point d'arrêt silencieusement absent du
    # rapport, c'est un dénominateur faux : « SPLIT moyen sur 10 points » ne se lit pas pareil
    # selon qu'il y en avait 12 ou 300.
    motifs = (
        ("degenere", "une seule action légale — aucune perturbation ne peut rien y changer"),
        ("sans_autre_cible", "aucune AUTRE cible éligible pour l'arme déjà assignée"),
        ("impure", "contrefactuelle impure (une autre clé bouge) — relancer avec --strict"),
    )
    ecartes = {k: [r for r in records if k in r] for k, _ in motifs}
    mesures = [r for r in records if not any(k in r for k, _ in motifs)]
    print(f"points d'arrêt rencontrés : {len(records)}")
    for key, why in motifs:
        detail = "  ".join(
            f"{se}={sum(1 for r in ecartes[key] if r.get('sous_etat') == se)}"  # get allowed
            for se in ("ARME", "CIBLE")
        )
        print(f"   écartés — {why:62s} : {len(ecartes[key]):3d}  ({detail})")
    print(f"points d'arrêt mesurés    : {len(mesures)}")
    records = mesures
    if not records:
        print("AUCUN point d'arrêt informatif — rien à conclure.")
        return 1

    labels = (("tvd_plancher", "PLANCHER   (obs contre elle-même)"),
              ("tvd_split", "SPLIT      (cible déjà assignée changée)"),
              ("tvd_reference", "RÉFÉRENCE  (les deux cibles échangent leurs caractéristiques)"),
              ("tvd_saturation", "SATURATION (bloc ennemi continu à zéro)"))

    # PAR SOUS-ÉTAT, et pas seulement en bloc : les bits servent à deux décisions différentes —
    # quelle arme engager ensuite (ARME), sur qui la pointer (CIBLE). Une moyenne commune peut
    # noyer un effet présent dans l'un sous l'indifférence de l'autre.
    for sous_etat in ("ARME", "CIBLE"):
        lot = [r for r in records if r.get("sous_etat") == sous_etat]  # get allowed
        if not lot:
            print(f"\n── sous-état {sous_etat} : AUCUN point mesuré ──")
            continue
        na = np.array([r["n_actions_legales"] for r in lot])
        print(f"\n── sous-état {sous_etat} — {len(lot)} points, "
              f"actions légales : méd={np.median(na):.0f} max={na.max():.0f} ──")
        for key, label in labels:
            vals = np.array([r[key] for r in lot])
            print(f"  {label:60s} moy={vals.mean():.6f}  med={np.median(vals):.6f}  "
                  f"max={vals.max():.6f}")

    print("\n── les deux sous-états réunis ──")
    stat: Dict[str, np.ndarray] = {}
    for key, label in labels:
        vals = np.array([r[key] for r in records])
        stat[key] = vals
        print(f"  {label:60s} moy={vals.mean():.6f}  med={np.median(vals):.6f}  "
              f"max={vals.max():.6f}  écart-type={vals.std():.6f}")

    if float(stat["tvd_plancher"].max()) != 0.0:
        print("\n❌ PLANCHER non nul : la sonde n'est pas déterministe, aucun autre nombre "
              "n'est lisible.")
        return 2
    if float(stat["tvd_saturation"].max()) <= 0.0:
        print("\n❌ SONDE MUETTE : même le bloc ennemi entier mis à zéro ne bouge pas la "
              "distribution. Un « SPLIT nul » ne signifierait pas « inexploité » — ne rien "
              "conclure de ce rapport.")
        return 2

    if policy is not None and not policy.trained:
        print("\n⚠️  politique NON entraînée : ces nombres valident l'INSTRUMENT (plancher nul, "
              "sonde non muette) et ne disent RIEN de l'exploitation. Relancer avec --model "
              "après le run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
