#!/usr/bin/env python3
"""
scripts/roster_matchup_stats.py - Collect roster matchup statistics

Runs P1 (trained agent) vs P2 (GreedyBot) for each (p1_roster, p2_roster) pair,
collects win/loss/draw stats, and writes to config/agents/<agent>/rosters/<scale>/matchups/.

Output files:
  - P1 benchmark: <p1_roster_id>_matchups_<eval_bot>.json
  - P2 benchmark: <p2_roster_id>_matchups_<eval_bot>.json
  - P1 subset: <split>_matchups_<eval_bot>_p1subset.json  (--p1-rosters id1,id2,...)
  - Full matrix: <split>_matchups_<eval_bot>.json

Modes:
  - Full matrix (default): all P1 × P2 combinations
  - P1 benchmark: --p1-benchmark p1_roster-01  → one P1, evaluate all P2 rosters
  - P1 subset: --p1-rosters id1,id2  → only these P1 vs all P2 (same episodes each matchup)
  - P1 exclude: --p1-exclude id1,id2  → all P1 in split except these; output: <split>_matchups_<bot>_p1exclude.json
  - Quantile: --quantile best25|worst25 avec --owner agent et/ou --owner opponent → sous-ensembles selon mean_agg
    (RANKING_BOTS : control + adaptive + greedy + defensive). --merge-full-matrices (défaut si quantile) fusionne dans
    <split>_matchups_<eval_bot>.json.
  - P2 benchmark: --p2-benchmark p2_training_roster-01   → one P2, evaluate all P1 rosters
  - All splits: --all-splits  → run training, holdout_regular, holdout_hard

Usage:
  python scripts/roster_matchup_stats.py --agent Infantry_Troop_RangedSwarm [--scale 100pts] [--episodes 30]
  python scripts/roster_matchup_stats.py --agent Infantry_Troop_RangedSwarm --p1-benchmark p1_training_roster-01
  python scripts/roster_matchup_stats.py --agent Infantry_Troop_RangedSwarm --all-splits --episodes 100

--------------------------------------------------------------------------------------
Etat (V11 0.47) — cet outil etait MORT et a ete remis en service
--------------------------------------------------------------------------------------
Il ne pouvait plus tourner depuis la refonte de l'observation : sa boucle aplatissait l'obs,
devenue un `gym.spaces.Dict` (pipeline squad), et levait avant meme de servir le masque —
masque qui, lui, etait celui de l'ANCIEN layout d'actions et n'aurait produit que des
statistiques silencieusement fausses. Les scenarios qu'il ecrivait portaient en outre des
cles que le moteur rejette.

Trois regles a respecter en le modifiant :

1. La boucle d'evaluation N'EST PAS autonome : elle est calquee sur `ai/bot_evaluation.py`,
   la boucle d'evaluation de REFERENCE (cf. Documentation/Reference/training/entrainement.md, section
   "Evaluation"). Obs Dict servie telle quelle, masque via `W40KEngine.get_action_mask`,
   plafond de pas derive de `config_loader.get_max_turns`, siege lu dans
   `info["controlled_player"]`, episodes tronques comptes a part (`failed_episodes`), jamais
   melanges aux resultats de parties. Toute divergence avec la reference est un bug en
   sursis : ce fichier en a deja accumule quatre, plus une copie locale du normalizer
   d'observation qui avait elle aussi diverge (il delegue desormais a la reference).

2. Les scenarios ecrits suivent le contrat V11 : `board_ref` + `terrain_ref` (le terrain porte
   murs, aires d'objectifs et zones de deploiement). Aucune cle legacy — `objectives_ref`,
   `wall_ref`, `deployment_zone` — le moteur leve sur la premiere. Modele de reference :
   `scripts/build_holdout_benchmark.py`.

3. Aucun repli sur une donnee manquante : cet outil ne produit que des statistiques, un
   chiffre invente y est pire qu'un arret. Les lectures d'`info` passent par `require_key`,
   un matchup dont aucun episode n'aboutit leve au lieu de rendre un taux de victoire de 0.

Comportement verrouille par tests/unit/scripts/test_roster_matchup_eval_loop.py et
tests/unit/scripts/test_roster_matchup_scenario_contract.py.
"""

import argparse
import functools
import json
import math
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# SOURCE UNIQUE des noms de bots (cf. l'en-tete de `ai/bot_registry.py`). Import de module et non
# differe : les `choices` d'argparse sont evaluees au montage du parseur. Le registre ne declare que
# des chaines, il ne tire ni le moteur ni torch — c'est ce qui le rend importable ici.
from engine.constants import DRAW_WINNER
from ai.bot_registry import ALL_BOT_KEYS  # noqa: E402
from shared.json_atomic import write_json_atomic  # noqa: E402


def _model_md5(path: str) -> str:
    """Empreinte du .zip effectivement chargé, lue par blocs (les modèles font des dizaines de Mo).

    JUMEAU de `scripts/bot_zone_direct.py::_md5`, et la duplication est assumée : `scripts/` n'a
    pas de module commun que ces deux-là partagent, et six lignes de `hashlib` n'en justifient pas
    un. Ce qui doit rester en phase, c'est l'EXIGENCE — une mesure imprime le modèle sur lequel
    elle porte — pas le code qui la sert.
    """
    import hashlib

    digest = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@functools.lru_cache(maxsize=1)
def _import_roster_aggregate() -> Any:
    import importlib.util

    path = PROJECT_ROOT / "scripts" / "roster_aggregate_rankings.py"
    spec = importlib.util.spec_from_file_location("roster_aggregate_rankings", path)
    if spec is None:
        raise RuntimeError("importlib spec is None")
    mod = importlib.util.module_from_spec(spec)
    loader = spec.loader
    if loader is None:
        raise RuntimeError("importlib loader is None")
    loader.exec_module(mod)
    return mod


def _ranking_matrix_filenames(split: str) -> Tuple[str, ...]:
    """Mêmes bots que roster_aggregate_rankings (mean_agg de référence), même ordre.

    Dérivé de `RANKING_BOTS` : l'arité n'est plus figée à 3, et les deux scripts ne peuvent
    plus diverger sur la liste des bots agrégés.
    """
    agg = _import_roster_aggregate()
    return tuple(f"{split}_matchups_{bot}.json" for bot in agg.RANKING_BOTS)


def _quantile_ids_from_rows(
    rows: List[Dict[str, Any]], which: str, frac: float, key: str = "mean_agg"
) -> List[str]:
    """which: best25 = plus haut mean_agg en premier ; worst25 = quartile bas."""
    by_desc = sorted(rows, key=lambda r: float(r[key]), reverse=True)
    ids = [str(r["roster_id"]) for r in by_desc]
    n = len(ids)
    if n == 0:
        return []
    k = max(1, int(math.ceil(n * frac)))
    if which == "best25":
        return ids[:k]
    if which == "worst25":
        return ids[-k:]
    raise ValueError(f"Invalid quantile which: {which!r}")


def _resolve_p1_quantile_ids(
    matchup_out_dir: Path,
    current_split: str,
    which: str,
    frac: float,
) -> List[str]:
    agg = _import_roster_aggregate()
    names = _ranking_matrix_filenames(current_split)
    matrices: List[Dict[str, Dict[str, Any]]] = []
    for name in names:
        p = matchup_out_dir / name
        if not p.is_file():
            raise FileNotFoundError(
                f"Classement quantile: fichier manquant {p} "
                f"(nécessite les {len(names)} matrices {names} pour calculer mean_agg)."
            )
        matrices.append(agg.load_matchup_matrix(p))
    rows = agg.build_rows_p1(matrices, agg.BOT_WEIGHTS)
    return _quantile_ids_from_rows(rows, which, frac)


def _resolve_p2_quantile_ids(
    matchup_out_dir: Path,
    current_split: str,
    which: str,
    frac: float,
) -> List[str]:
    agg = _import_roster_aggregate()
    names = _ranking_matrix_filenames(current_split)
    matrices = []
    for name in names:
        p = matchup_out_dir / name
        if not p.is_file():
            raise FileNotFoundError(
                f"Classement quantile P2: fichier manquant {p} "
                f"(nécessite les {len(names)} matrices {names})."
            )
        matrices.append(agg.load_matchup_matrix(p))
    rows = agg.build_rows_p2(matrices, agg.BOT_WEIGHTS)
    return _quantile_ids_from_rows(rows, which, frac)


def _rebuild_summaries_from_matchups(
    matchups: Dict[str, Dict[str, Dict[str, Any]]],
    p1_order: Sequence[Tuple[str, str]],
    p2_order: Sequence[Tuple[str, str]],
) -> Tuple[float, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Recalcule overall_wr et résumés P1/P2 à partir d'une matrice complète (grille P1×P2)."""
    p1_ids = [rid for _r, rid in p1_order]
    p2_ids = [rid for _r, rid in p2_order]
    all_rates: List[float] = []
    for p1_id in p1_ids:
        for p2_id in p2_ids:
            if p1_id not in matchups:
                raise KeyError(f"Résumé: P1 {p1_id!r} absent de matchups")
            row = matchups[p1_id]
            if p2_id not in row:
                raise KeyError(f"Résumé: cellule manquante P1={p1_id!r} P2={p2_id!r}")
            all_rates.append(float(row[p2_id]["win_rate"]))
    overall_wr = sum(all_rates) / len(all_rates) if all_rates else 0.0

    p1_summaries: List[Dict[str, Any]] = []
    for p1_id in p1_ids:
        p2_data = matchups[p1_id]
        rates = [float(p2_data[p2_id]["win_rate"]) for p2_id in p2_ids]
        avg_wr = sum(rates) / len(rates)
        best = max(((p2_id, p2_data[p2_id]["win_rate"]) for p2_id in p2_ids), key=lambda x: x[1])
        worst = min(((p2_id, p2_data[p2_id]["win_rate"]) for p2_id in p2_ids), key=lambda x: x[1])
        p1_summaries.append(
            {
                "p1_roster_id": p1_id,
                "overall_win_rate": round(avg_wr, 4),
                "vs_best": best[0],
                "vs_worst": worst[0],
                "sur_performant": avg_wr > overall_wr + 0.05,
                "sous_performant": avg_wr < overall_wr - 0.05,
            }
        )

    p2_summaries: List[Dict[str, Any]] = []
    for p2_id in p2_ids:
        rates = [float(matchups[p1_id][p2_id]["win_rate"]) for p1_id in p1_ids]
        avg_wr = sum(rates) / len(rates)
        p2_summaries.append(
            {
                "p2_roster_id": p2_id,
                "p1_win_rate_vs_this_p2": round(avg_wr, 4),
                "sur_performant_p2": avg_wr < overall_wr - 0.05,
                "sous_performant_p2": avg_wr > overall_wr + 0.05,
            }
        )
    return overall_wr, p1_summaries, p2_summaries


def _merge_partial_into_full_json(
    full_path: Path,
    partial_matchups: Dict[str, Dict[str, Dict[str, Any]]],
    p1_order: Sequence[Tuple[str, str]],
    p2_order: Sequence[Tuple[str, str]],
    args: argparse.Namespace,
    model_path: str,
    eval_bot_name: str,
    current_split: str,
) -> None:
    """Fusionne les cellules rejouées dans la matrice complète et réécrit le JSON."""
    with full_path.open(encoding="utf-8") as f:
        doc = json.load(f)
    mm = doc.get("matchups")
    if not isinstance(mm, dict):
        raise KeyError(f"{full_path} : clé 'matchups' absente ou invalide")
    for p1, row in partial_matchups.items():
        if p1 not in mm:
            mm[p1] = {}
        for p2, cell in row.items():
            mm[p1][p2] = cell
    doc["matchups"] = mm
    overall_wr, p1_s, p2_s = _rebuild_summaries_from_matchups(mm, p1_order, p2_order)
    doc["overall_win_rate"] = round(overall_wr, 4)
    doc["episodes_per_matchup"] = args.episodes
    doc["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc["model_path"] = model_path
    doc["eval_bot"] = eval_bot_name
    doc["eval_bot_randomness"] = float(args.eval_bot_randomness)
    doc["split"] = current_split
    doc["p1_summaries"] = sorted(p1_s, key=lambda x: -x["overall_win_rate"])
    doc["p2_summaries"] = sorted(p2_s, key=lambda x: x["p1_win_rate_vs_this_p2"])
    doc["quantile"] = getattr(args, "quantile", None)
    doc["quantile_owners"] = list(getattr(args, "quantile_owners", []) or [])
    doc["quantile_frac"] = float(args.quantile_frac)
    doc["matchup_merge_note"] = (
        "Fusion partielle depuis roster_matchup_stats.py (quantile) ; "
        "résumés recalculés sur la grille matchups complète."
    )
    write_json_atomic(full_path, doc)
    print(f"\n✅ Fusion dans matrice complète: {full_path}")


def _collect_p1_rosters(agent_key: str, scale: str, split: str) -> List[Tuple[str, str]]:
    """Return [(ref, roster_id), ...] for P1 rosters in split."""
    base = PROJECT_ROOT / "config" / "agents" / agent_key / "rosters" / scale / split
    if not base.exists():
        return []
    refs: List[Tuple[str, str]] = []
    patterns: List[str] = [
        # Current naming convention
        f"agent_{split}_roster_*.json",
        # Legacy naming conventions
        f"p1_{split}_roster-*.json",
    ]
    if split == "training":
        patterns.append("p1_training_roster-*.json")
    seen_paths = set()
    for pattern in patterns:
        for p in sorted(base.glob(pattern)):
            if p in seen_paths:
                continue
            if "_kpis" in p.name or "_matchups" in p.name:
                continue
            seen_paths.add(p)
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "roster_id" not in data:
                continue
            roster_id = data.get("roster_id", p.stem)
            ref = f"{split}/{p.name}"
            refs.append((ref, roster_id))
    return refs


def _collect_p2_rosters(scale: str, split: str) -> List[Tuple[str, str]]:
    """Return [(ref, roster_id), ...] for P2 rosters in split."""
    base = PROJECT_ROOT / "config" / "agents" / "_p2_rosters" / scale / split
    if not base.exists():
        return []
    refs: List[Tuple[str, str]] = []
    patterns = [
        # Current naming convention
        f"opponent_{split}_roster_*.json",
        # Legacy naming convention
        "p2_*_roster-*.json",
    ]
    seen_paths = set()
    for pattern in patterns:
        for p in sorted(base.glob(pattern)):
            if p in seen_paths:
                continue
            if "_kpis" in p.name or "_matchups" in p.name:
                continue
            seen_paths.add(p)
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "roster_id" not in data:
                continue
            roster_id = data.get("roster_id", p.stem)
            ref = f"{split}/{p.name}"
            refs.append((ref, roster_id))
    return refs


def _build_scenario_template(scale: str, board_ref: str, terrain_ref: str) -> Dict[str, Any]:
    """Base scenario template for matchup scenarios.

    Pas de parametre `split` : il n'apparait dans aucune cle du scenario. Le moteur le deduit
    du CHEMIN du fichier ("/scenarios/training/", "/scenarios/holdout_*/",
    `GameStateManager._load_units_from_roster_refs`), chemin que l'appelant construit deja.

    Contrat moteur V11 (meme forme que `_build_scenarios` dans
    scripts/build_holdout_benchmark.py) : murs, aires d'objectifs et zones de deploiement
    viennent TOUS du `terrain_ref`, resolu sous `config/board/<board_ref>/terrain/`
    (`GameStateManager.load_units_from_scenario`, qui delegue a `_resolve_board_dir`).
    Aucune cle legacy : `objectives_ref` est explicitement rejetee par le moteur (meme
    fonction, garde sur les cles d'objectifs supprimees) et `deployment_zone` est inutile des
    lors que le terrain porte une section `deployment_zones`.
    """
    return {
        "deployment_type": "active",
        # Clause de detachement d'Oath of Moment : champ OBLIGATOIRE des qu'une armee ADEPTUS
        # ASTARTES est en jeu (`game_state.uses_codex_detachment` leve sinon), et ces matchups
        # croisent tous les rosters, marines compris.
        "uses_codex_detachment": {"1": True, "2": True},
        "scale": scale,
        "p1_roster_seed": 42,
        "primary_objectives": ["objectives_control"],
        "board_ref": board_ref,
        "terrain_ref": terrain_ref,
    }


def _generate_rule_checker_artifacts(
    agent_key: str, scale: str, board_ref: str, terrain_ref: str
) -> None:
    """Genere les artefacts rule-checker et rend compte a l'ecran.

    La FABRICATION vit dans `shared/rule_checker_scenarios.py`, partagee avec
    `ai/train.py --rule-checker` qui les regenere au lancement : deux fabricants du meme
    artefact divergeraient, et c'est deja arrive (les fichiers commites portaient encore
    `objectives_ref`, refuse par le moteur, longtemps apres la correction du generateur).
    """
    from shared import rule_checker_scenarios

    scenario_paths = rule_checker_scenarios.generate(
        PROJECT_ROOT,
        agent_key=agent_key,
        params=rule_checker_scenarios.GenerationParams(
            scale=scale, board_ref=board_ref, terrain_ref=terrain_ref
        ),
    )
    run_dir = Path(scenario_paths[0]).parent
    print(f"✅ Rule-checker scenarios generated: {len(scenario_paths)}")
    print(f"📁 Output dir: {run_dir}")
    print(f"🧾 Manifest: {run_dir / 'manifest.json'}")
    print(f"🧾 Rejected audit: {run_dir / 'audit_rejected.json'}")


def _run_single_episode(
    env,
    model,
    obs_normalizer,
    max_steps_per_episode: int,
    ep_seed: int,
) -> str:
    """Joue UN episode et rend "win", "loss", "draw" ou "failed".

    Extrait de `_run_matchup_episodes` pour etre exercable avec des doublures (env et modele
    factices), sans faire tourner de partie. C'est la seule partie qui DECIDE : quelle
    observation et quel masque sont servis au modele, quand l'episode s'arrete, et comment le
    resultat est lu. Calquee sur la boucle de reference `ai/bot_evaluation._eval_worker_task`.

    "failed" = episode TRONQUE par le plafond de pas : la partie n'a jamais atteint sa fin,
    le moteur n'a donc pas de vainqueur a designer (`info["winner"]` vaut None hors
    terminaison, `W40KEngine.step`). Le classer gagne/perdu/nul fabriquerait une statistique.
    La reference tient le meme compte separe sous le nom `failed_episodes`
    (`_eval_worker_task`, agrege par `evaluate_against_bots` en `total_failed_episodes`).
    """
    import numpy as np
    from shared.data_validation import require_key

    # `ai/bot_evaluation._eval_worker_task` : les DEUX generateurs sont poses.
    random.seed(ep_seed)
    np.random.seed(ep_seed)
    obs, info = env.reset(seed=ep_seed)
    done = False
    step_count = 0
    while not done and step_count < max_steps_per_episode:
        model_obs = obs_normalizer(obs) if obs_normalizer is not None else obs
        # Obs Dict (MultiInputPolicy + CNN) : predict la gere nativement, ne pas aplatir.
        # Copie conforme de `ai/bot_evaluation._eval_worker_task`. L'obs du pipeline squad est un
        # gym.spaces.Dict : l'aplatir levait avant meme d'atteindre le masque.
        if isinstance(model_obs, dict):
            model_input = model_obs
        else:
            model_input = np.asarray(model_obs, dtype=np.float32)
            if model_input.ndim == 1:
                model_input = model_input.reshape(1, -1)
        # MEME chemin que la production (`ai/bot_evaluation._eval_worker_task`) : le masque servi au
        # modele doit etre celui de la semantique SQUAD que `env.step` decode. La voie
        # legacy `action_decoder.get_action_mask_and_eligible_units` construit l'ancien
        # layout (mask[9]=charge, mask[10]=fight, mask[11]=wait, mask[4+i]=tir) et a la
        # meme longueur (total_action_size) : l'erreur etait donc silencieuse.
        # `engine.get_action_mask()` fait de plus avancer la phase de combat quand le
        # masque sort vide — sans quoi la boucle d'evaluation se bloquerait sur un masque
        # tout a False.
        # `get_action_masks` de sb3_contrib = le chemin de PPO : il resout `action_masks` sur
        # le wrapper le PLUS EXTERNE, donc `BotControlledEnv.action_masks`, qui sert la decision
        # deja etablie. L'appel direct `env.engine.get_action_mask()` qui vivait ici POIGNARDAIT
        # ce depot : il fait avancer la phase de combat sur masque vide (cf. sa docstring), donc
        # il pouvait deplacer l'etat ENTRE deux `step()` — le step suivant consommait alors le
        # masque d'un etat revolu, sans que rien ne leve. Il ne gagnait rien au passage : cette
        # boucle n'utilisait pas le depot, elle ne faisait que le perimer.
        # L'avancement de phase reste assure : sans depot, `action_masks()` retombe sur
        # `engine.get_action_mask()` ; avec depot, le masque est non vide par precondition, donc
        # la boucle d'avancement n'aurait de toute facon rien fait.
        from sb3_contrib.common.maskable.utils import get_action_masks

        action_masks = np.asarray(get_action_masks(env), dtype=bool)
        if action_masks.ndim == 1:
            action_masks = action_masks.reshape(1, -1)
        action, _ = model.predict(model_input, action_masks=action_masks, deterministic=True)
        action_scalar = int(np.asarray(action).flat[0])
        obs, _, terminated, truncated, info = env.step(action_scalar)
        done = bool(terminated or truncated)
        step_count += 1
    if not done:
        # Sortie par le plafond de pas : la partie est INACHEVEE. Aucun resultat n'en est
        # deductible — la compter en defaite (ce que faisait le code) ou en nul biaiserait le
        # taux de victoire sans laisser de trace.
        return "failed"
    # Pas de `info.get("winner")` : un `None` de repli n'est ni `controlled_player` ni -1,
    # l'episode serait compte en DEFAITE alors que la donnee manque. Le moteur ecrit toujours
    # la cle dans `W40KEngine.step`, partie terminee comme partie en cours : son absence est
    # une anomalie d'environnement, pas un cas de jeu.
    winner = require_key(info, "winner")
    if winner is None:
        # Episode termine SANS vainqueur : le moteur n'en produit jamais (`W40KEngine.step`
        # pose un vainqueur reel a la terminaison, et -1 sur sa propre troncature). Un None
        # ici veut dire que l'env ment sur sa terminaison ; le compter en defaite masquerait
        # le probleme dans la statistique.
        raise ValueError(
            "Episode termine avec info['winner'] = None : l'environnement signale une fin de "
            "partie sans vainqueur, ce que le moteur ne produit jamais."
        )
    # `ai/bot_evaluation._eval_worker_task` : le siege controle est LU dans l'info rendue par l'env, pas
    # recalcule ici. Un identifiant recalcule localement peut diverger silencieusement du
    # siege reellement joue (BotControlledEnv gere l'alternance des sieges).
    controlled_player = require_key(info, "controlled_player")
    if winner == controlled_player:
        return "win"
    if winner == DRAW_WINNER:
        return "draw"
    return "loss"


def _build_eval_env(
    scenario_file: str,
    agent_key: str,
    model_path: str,
    training_config_name: str,
    rewards_config_name: str,
    n_episodes: int,
    opponent_mode: str,
    eval_bot_name: str,
    eval_bot_randomness: float,
    agent_seat_mode: str,
):
    """Construit l'environnement d'evaluation (moteur -> ActionMasker -> BotControlledEnv).

    Extrait de `_run_matchup_episodes` pour que le cablage du siege soit verifiable avec des
    doublures, sans construire de moteur. `agent_seat_mode` est transmis dans LES DEUX modes
    d'adversaire : il etait valide puis oublie en mode bot, ou le wrapper retombait sur son
    defaut "p1" (`BotControlledEnv.__init__`, param `agent_seat_mode`) — l'option existait,
    etait documentee, et n'avait aucun effet.
    """
    from ai.training_utils import setup_imports
    from ai.bot_registry import build_bot
    from ai.env_wrappers import BotControlledEnv
    from ai.evaluation_bots import GreedyBot
    from sb3_contrib.common.wrappers import ActionMasker
    from ai.unit_registry import UnitRegistry

    unit_registry = UnitRegistry()
    W40KEngine, _ = setup_imports()
    if opponent_mode not in {"bot", "agent"}:
        raise ValueError(f"opponent_mode must be 'bot' or 'agent' (got {opponent_mode!r})")
    if agent_seat_mode not in {"p1", "p2"}:
        raise ValueError(f"agent_seat_mode must be 'p1' or 'p2' (got {agent_seat_mode!r})")

    # SOURCE UNIQUE des noms de bots : `ai/bot_registry.py`. Ce fichier portait sa propre table
    # cle -> classe, restee sur le panel d'origine : `--eval-bot racer` levait « Unknown eval bot »
    # alors que le bot existe. C'est le defaut exact qui a fait naitre le registre (constate sur
    # `bot_ranking.py` le 2026-08-11), reste ici parce que ce troisieme appelant a ete manque.
    if opponent_mode == "bot" and eval_bot_name not in ALL_BOT_KEYS:
        raise ValueError(
            f"Unknown eval bot: {eval_bot_name!r}. Valid: {', '.join(sorted(ALL_BOT_KEYS))}"
        )

    def mask_fn(env):
        return env.get_action_mask()

    base_env = W40KEngine(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=agent_key,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True,
        debug_mode=False,
        # UN environnement joue en serie : denominateur des rampes par-episode.
        training_n_envs=1,
    )
    masked_env = ActionMasker(base_env, mask_fn)
    if opponent_mode == "bot":
        bot = build_bot(eval_bot_name, {eval_bot_name: float(eval_bot_randomness)})
        env = BotControlledEnv(
            masked_env,
            bot,
            unit_registry,
            agent_seat_mode=agent_seat_mode,
        )
    else:
        # Force self-play opponent every episode (agent vs agent), snapshot taken from model_path.
        # A fallback bot list is required by BotControlledEnv signature, but ratio=1.0 ensures
        # self-play path is always selected.
        fallback_bot = GreedyBot(randomness=0.0)
        env = BotControlledEnv(
            masked_env,
            bots=[fallback_bot],
            unit_registry=unit_registry,
            agent_seat_mode=agent_seat_mode,
            self_play_opponent_enabled=True,
            self_play_ratio_start=1.0,
            self_play_ratio_end=1.0,
            self_play_total_episodes=max(1, int(n_episodes)),
            self_play_warmup_episodes=0,
            # Ce script joue ses episodes dans UN seul environnement, en serie : le budget
            # ci-dessus est deja per-env (cf. V11 §0.57).
            self_play_n_envs=1,
            self_play_snapshot_path=model_path,
            # Le modele ne bouge pas pendant le script : le charger une fois suffisait, et le
            # refresh_episodes=1 d'avant le rechargeait a CHAQUE episode.
            self_play_snapshot_frozen=True,
            self_play_snapshot_device="cpu",
            self_play_deterministic=True,
        )
    return env


def _run_matchup_episodes(
    scenario_file: str,
    agent_key: str,
    model_path: str,
    training_config_name: str,
    rewards_config_name: str,
    n_episodes: int,
    opponent_mode: str,
    eval_bot_name: str,
    eval_bot_randomness: float,
    agent_seat_mode: str,
    obs_normalizer=None,
    seed: int = 42,
) -> Tuple[int, int, int, int]:
    """Run n_episodes with model vs bot, return (wins, losses, draws, failed_episodes).

    `failed_episodes` compte les episodes TRONQUES par le plafond de pas, jamais melanges aux
    resultats de parties : meme separation que `failed_episodes` dans la reference
    (`ai/bot_evaluation._eval_worker_task`), qui les agrege en `total_failed_episodes`.
    """
    from sb3_contrib import MaskablePPO
    from config_loader import get_max_turns

    env = _build_eval_env(
        scenario_file=scenario_file,
        agent_key=agent_key,
        model_path=model_path,
        training_config_name=training_config_name,
        rewards_config_name=rewards_config_name,
        n_episodes=n_episodes,
        opponent_mode=opponent_mode,
        eval_bot_name=eval_bot_name,
        eval_bot_randomness=eval_bot_randomness,
        agent_seat_mode=agent_seat_mode,
    )
    model = MaskablePPO.load(model_path, env=env)
    # Meme source que la reference (`ai/bot_evaluation.evaluate_against_bots`, qui pose la cle
    # "max_steps_per_episode" des taches d'evaluation) : la duree de bataille vient de
    # game_rules.max_turns via config_loader.get_max_turns(). Aucun plafond en dur, aucune
    # valeur par defaut : si la config ne porte pas max_turns, get_max_turns leve.
    max_steps_per_episode = int(get_max_turns()) * 400
    wins, losses, draws, failed = 0, 0, 0, 0
    for ep in range(n_episodes):
        outcome = _run_single_episode(
            env=env,
            model=model,
            obs_normalizer=obs_normalizer,
            max_steps_per_episode=max_steps_per_episode,
            ep_seed=(seed + ep * 1000) % (2**31),
        )
        if outcome == "win":
            wins += 1
        elif outcome == "draw":
            draws += 1
        elif outcome == "failed":
            failed += 1
        else:
            losses += 1
    env.close()
    return wins, losses, draws, failed


def _build_obs_normalizer(agent_key: str, training_config_name: str, model_path: str):
    """Build observation normalizer if VecNormalize is enabled.

    Le normalizer lui-meme n'est PAS reecrit ici : c'est celui de la reference,
    `ai/bot_evaluation._build_eval_obs_normalizer_for_worker`, seul a traiter l'obs Dict du
    pipeline squad (`normalize_obs` sur "global_cont") autant que le chemin legacy Box a plat.
    Une copie locale re-divergerait silencieusement —
    c'est exactement ce qui s'etait produit : elle aplatissait l'obs Dict.
    Ce script ne garde que la LECTURE des drapeaux dans la config d'agent.
    """
    from shared.data_validation import require_key
    from ai.bot_evaluation import _build_eval_obs_normalizer_for_worker

    config = __import__("config_loader", fromlist=["get_config_loader"]).get_config_loader()
    training_cfg = config.load_agent_training_config(agent_key, training_config_name)
    vec_cfg = require_key(training_cfg, "vec_normalize")
    vec_eval_cfg = require_key(training_cfg, "vec_normalize_eval")
    return _build_eval_obs_normalizer_for_worker(
        None,
        model_path,
        bool(vec_cfg.get("enabled")),
        bool(vec_eval_cfg.get("enabled")),
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construit le parseur de la ligne de commande.

    Extrait de `main()` pour que les valeurs par defaut soient interrogeables sur le parseur
    REELLEMENT construit (`parser.get_default(...)`), au lieu d'etre relues dans le texte du
    source — une lecture qui casse a la premiere reformulation et ne prouve rien.
    """
    parser = argparse.ArgumentParser(description="Collect roster matchup statistics")
    parser.add_argument("--agent", required=True, help="Agent key (e.g. Infantry_Troop_RangedSwarm)")
    parser.add_argument("--scale", default="100pts", help="Roster scale")
    parser.add_argument("--episodes", type=int, default=30, help="Episodes per matchup")
    parser.add_argument("--split", nargs="?", default="training", const="training",
                    help="Roster split: training (default), holdout_regular, holdout_hard")
    parser.add_argument("--training-config", default="default", help="Training config name")
    parser.add_argument("--rewards-config", default=None, help="Rewards config (default: same as agent)")
    parser.add_argument("--p1-benchmark", metavar="ROSTER_ID", default=None,
                    help="Use single P1 roster as benchmark; evaluate all P2 rosters vs it (e.g. p1_roster-01)")
    parser.add_argument(
        "--p1-rosters",
        metavar="ID_LIST",
        default=None,
        help=(
            "Comma-separated P1 roster ids to evaluate (vs all P2 in split). "
            "Mutually exclusive with --p1-benchmark. Output: <split>_matchups_<bot>_p1subset.json"
        ),
    )
    parser.add_argument(
        "--p1-exclude",
        metavar="ID_LIST",
        default=None,
        help=(
            "Comma-separated P1 roster ids to skip. Applied to the full split roster list, "
            "or to the set selected by --p1-rosters. Use to omit rosters already benchmarked."
        ),
    )
    parser.add_argument("--p1-benchmark-split", metavar="SPLIT", default=None,
                    help="Split to load P1 benchmark from (e.g. holdout_regular). Default: same as --split")
    parser.add_argument("--p2-benchmark", metavar="ROSTER_ID", default=None,
                    help="Use single P2 roster as benchmark; evaluate all P1 rosters vs it (e.g. p2_roster-01)")
    parser.add_argument("--p2-benchmark-split", metavar="SPLIT", default=None,
                    help="Split to load P2 benchmark from (e.g. holdout). Default: same as --split")
    parser.add_argument("--all-splits", action="store_true",
                    help="Run for training, holdout_regular, and holdout_hard (output: <split>_matchups.json each)")
    parser.add_argument("--board-ref", default="44x60x5",
                    help="Board de reference des scenarios generes (config/board/<board_ref>/). "
                         "Defaut 44x60x5 : le board de la banque de scenarios par-agent, celui "
                         "qu'emploie aussi scripts/build_holdout_benchmark.py")
    parser.add_argument("--terrain-ref", default="terrain-mc1.json",
                    help="Terrain des scenarios generes (config/board/<board_ref>/terrain/<terrain_ref>) "
                         "— il porte les murs, les aires d'objectifs et les zones de deploiement. "
                         "Defaut terrain-mc1.json : le terrain des scenarios vivants de la banque, "
                         "verifie porteur d'aires \"objective\": true et d'une section "
                         "deployment_zones, les deux prerequis du contrat V11")
    parser.add_argument(
        "--opponent-mode",
        choices=["bot", "agent"],
        default="bot",
        help="bot: evaluate model vs configured bot(s); agent: evaluate model vs agent self-play opponent",
    )
    parser.add_argument(
        "--eval-bot",
        default="greedy",
        choices=sorted(ALL_BOT_KEYS),
        help="Single evaluation bot used for matchup generation",
    )
    parser.add_argument(
        "--eval-bots",
        default=None,
        help=(
            "Optional comma-separated list of eval bots to generate multiple matchup matrices in one run, "
            "e.g. control,adaptive,greedy,defensive"
        ),
    )
    parser.add_argument(
        "--eval-bot-randomness",
        type=float,
        default=0.15,
        help="Randomness passed to non-random eval bots",
    )
    parser.add_argument(
        "--agent-seat-mode",
        choices=["p1", "p2"],
        default="p1",
        help="Seat used when --opponent-mode agent and bidirectional mode is disabled",
    )
    parser.add_argument(
        "--agent-seat-bidirectional",
        action="store_true",
        help="When --opponent-mode agent, evaluate both seats (p1 and p2) and aggregate results",
    )
    parser.add_argument(
        "--rule-checker",
        action="store_true",
        help="Generate dedicated rule-checker scenarios in config/rule_checker/ using units with at least one RULES_STATUS value == 2",
    )
    parser.add_argument(
        "--quantile",
        choices=["best25", "worst25"],
        default=None,
        help=(
            "Quartile par mean_agg agrégé (RANKING_BOTS : control + adaptive + greedy + defensive). "
            "À combiner avec --owner agent et/ou --owner opponent."
        ),
    )
    parser.add_argument(
        "--owner",
        dest="quantile_owners",
        action="append",
        choices=["agent", "opponent"],
        metavar="WHO",
        help=(
            "Applique --quantile aux rosters de l'agent (P1) et/ou de l'adversaire (P2). "
            "Répéter pour les deux: --owner agent --owner opponent."
        ),
    )
    parser.add_argument(
        "--quantile-frac",
        type=float,
        default=0.25,
        help="Taille du quartile (défaut 0.25). k = ceil(n * frac), min 1.",
    )
    parser.add_argument(
        "--merge-full-matrices",
        dest="merge_full_matrices",
        action="store_const",
        const=True,
        default=None,
        help="Fusionner les cellules rejouées dans <split>_matchups_<eval_bot>.json (défaut: oui si quantile)",
    )
    parser.add_argument(
        "--no-merge-full-matrices",
        dest="merge_full_matrices",
        action="store_const",
        const=False,
        default=None,
        help="Écrire un JSON partiel au lieu de fusionner dans la matrice complète",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()

    if args.rule_checker:
        _generate_rule_checker_artifacts(
            agent_key=args.agent,
            scale=args.scale,
            board_ref=args.board_ref,
            terrain_ref=args.terrain_ref,
        )
        return

    owners_norm = list(dict.fromkeys(getattr(args, "quantile_owners", None) or []))
    args.quantile_owners = owners_norm
    args.quantile_p1 = "agent" in owners_norm
    args.quantile_p2 = "opponent" in owners_norm

    if args.p1_benchmark and args.p2_benchmark:
        print("❌ Cannot use both --p1-benchmark and --p2-benchmark")
        sys.exit(1)
    if args.p1_benchmark and args.p1_rosters:
        print("❌ Cannot use both --p1-benchmark and --p1-rosters")
        sys.exit(1)
    if args.p1_benchmark and args.p1_exclude:
        print("❌ Cannot use both --p1-benchmark and --p1-exclude")
        sys.exit(1)
    if args.all_splits and (args.p1_benchmark or args.p2_benchmark):
        print("❌ --all-splits cannot be used with --p1-benchmark or --p2-benchmark")
        sys.exit(1)
    if args.eval_bot_randomness < 0.0 or args.eval_bot_randomness > 1.0:
        print(f"❌ --eval-bot-randomness must be in [0,1], got {args.eval_bot_randomness}")
        sys.exit(1)
    if args.opponent_mode == "agent" and args.eval_bots is not None:
        print("❌ --eval-bots is not compatible with --opponent-mode agent")
        sys.exit(1)
    if args.opponent_mode == "bot" and args.agent_seat_bidirectional:
        print("❌ --agent-seat-bidirectional is only valid with --opponent-mode agent")
        sys.exit(1)
    if args.merge_full_matrices is None:
        args.merge_full_matrices = bool(args.quantile_p1 or args.quantile_p2)
    if (args.quantile_p1 or args.quantile_p2) and args.quantile is None:
        print("❌ Avec --owner, --quantile (best25|worst25) est requis")
        sys.exit(1)
    if args.quantile is not None and not (args.quantile_p1 or args.quantile_p2):
        print("❌ --quantile requiert au moins un --owner agent et/ou --owner opponent")
        sys.exit(1)
    if args.quantile_p1:
        if args.p1_benchmark or args.p1_rosters or args.p1_exclude:
            print(
                "❌ quantile côté agent (--owner agent) incompatible avec "
                "--p1-benchmark, --p1-rosters et --p1-exclude"
            )
            sys.exit(1)
    if args.quantile_p2 and args.p2_benchmark:
        print("❌ quantile côté adversaire (--owner opponent) incompatible avec --p2-benchmark")
        sys.exit(1)
    if (args.quantile_p1 or args.quantile_p2) and not (0.0 < args.quantile_frac <= 1.0):
        print(f"❌ --quantile-frac doit être dans ]0,1], obtenu: {args.quantile_frac}")
        sys.exit(1)
    rewards_config = args.rewards_config or args.agent

    config = __import__("config_loader", fromlist=["get_config_loader"]).get_config_loader()
    models_root = config.get_models_root()
    model_path = os.path.join(models_root, args.agent, f"model_{args.agent}.zip")
    if not os.path.exists(model_path):
        print(f"❌ Model not found: {model_path}")
        sys.exit(1)
    # LE CHEMIN CANONIQUE EST PARTAGE ET VOLATIL : tout `train.py --new`, depuis n'importe quelle
    # session, l'ecrase. Une campagne de matchups ne dit donc rien de son modele si elle ne
    # l'IDENTIFIE pas. Le 2026-08-13, ce chemin portait un modele different de celui dont le
    # chantier des bots tirait tous ses chiffres, et deux tableaux ont ete publies dessus sans que
    # rien ne le signale (cf. Documentation/Reference/training/panel_bots.md §12.7, invalidee, et §12.8).
    # Le md5 est le seul identifiant qui survive a un renommage ou a une recopie.
    print(f"📦 Modèle : {model_path}\n   md5 : {_model_md5(model_path)}")

    splits_to_run: List[str] = (
        ["training", "holdout_regular", "holdout_hard"] if args.all_splits else [args.split]
    )
    if args.opponent_mode == "agent":
        eval_bot_names = ["agent"]
    elif args.eval_bots is None:
        eval_bot_names = [str(args.eval_bot)]
    else:
        eval_bot_names = [token.strip() for token in str(args.eval_bots).split(",") if token.strip()]
        if not eval_bot_names:
            print("❌ --eval-bots provided but empty after parsing")
            sys.exit(1)
        invalid = [name for name in eval_bot_names if name not in ALL_BOT_KEYS]
        if invalid:
            print(f"❌ Invalid bot(s) in --eval-bots: {invalid}. Valid: {sorted(ALL_BOT_KEYS)}")
            sys.exit(1)

    for current_split in splits_to_run:
        for eval_bot_name in eval_bot_names:
            if args.all_splits or len(eval_bot_names) > 1:
                print(f"\n{'='*60}\n📌 Split: {current_split} | Eval bot: {eval_bot_name}\n{'='*60}")
            _run_one_split(args, current_split, model_path, rewards_config, eval_bot_name)


def _run_one_split(
    args: argparse.Namespace,
    current_split: str,
    model_path: str,
    rewards_config: str,
    eval_bot_name: str,
) -> None:
    """Run matchup stats for one split (training, holdout_regular, or holdout_hard)."""
    p1_split = args.p1_benchmark_split if args.p1_benchmark and args.p1_benchmark_split else current_split
    p2_split_base = args.p2_benchmark_split if args.p2_benchmark and args.p2_benchmark_split else current_split
    p2_split = "holdout" if p2_split_base.startswith("holdout") else p2_split_base

    p1_rosters = _collect_p1_rosters(args.agent, args.scale, p1_split)
    p2_rosters = _collect_p2_rosters(args.scale, p2_split)
    if not p2_rosters and p2_split != p2_split_base:
        p2_rosters = _collect_p2_rosters(args.scale, p2_split_base)
    if not p1_rosters:
        print(f"❌ No P1 rosters in {args.agent}/rosters/{args.scale}/{p1_split}/")
        return
    if not p2_rosters:
        print(f"❌ No P2 rosters in _p2_rosters/{args.scale}/{p2_split}/")
        return

    matchups_out_dir = PROJECT_ROOT / "config" / "agents" / args.agent / "rosters" / args.scale / "matchups"
    matchups_out_dir.mkdir(parents=True, exist_ok=True)

    p1_rosters_full: List[Tuple[str, str]] = []
    p2_rosters_full: List[Tuple[str, str]] = []
    if args.quantile_p1 or args.quantile_p2:
        if args.quantile is None:
            raise ValueError("--quantile est requis avec --owner agent et/ou --owner opponent")
        p1_rosters_full = list(p1_rosters)
        p2_rosters_full = list(p2_rosters)

    if args.quantile_p1:
        qids = set(
            _resolve_p1_quantile_ids(
                matchups_out_dir, current_split, str(args.quantile), float(args.quantile_frac)
            )
        )
        p1_rosters = [(r, rid) for r, rid in p1_rosters if rid in qids]
        print(
            f"📌 Quantile agent (P1) {args.quantile} (frac={args.quantile_frac}): "
            f"{len(p1_rosters)} roster(s) / {len(qids)} id(s) cible(s)"
        )
        if not p1_rosters:
            print("❌ Aucun P1 après filtre quantile")
            return
    if args.quantile_p2:
        qids = set(
            _resolve_p2_quantile_ids(
                matchups_out_dir, current_split, str(args.quantile), float(args.quantile_frac)
            )
        )
        p2_rosters = [(r, rid) for r, rid in p2_rosters if rid in qids]
        print(
            f"📌 Quantile adversaire (P2) {args.quantile} (frac={args.quantile_frac}): "
            f"{len(p2_rosters)} roster(s) / {len(qids)} id(s) cible(s)"
        )
        if not p2_rosters:
            print("❌ Aucun P2 après filtre quantile")
            return

    if args.p1_benchmark:
        p1_rosters = [(ref, rid) for ref, rid in p1_rosters if rid == args.p1_benchmark]
        if not p1_rosters:
            print(f"❌ P1 benchmark '{args.p1_benchmark}' not found in {p1_split}")
            return
        print(f"📌 P1 benchmark: {args.p1_benchmark} (from {p1_split}, evaluating {len(p2_rosters)} P2 rosters from {p2_split})")
    elif args.p1_rosters:
        allowed = {x.strip() for x in str(args.p1_rosters).split(",") if x.strip()}
        if not allowed:
            print("❌ --p1-rosters is empty")
            return
        found_ids = {rid for _, rid in p1_rosters}
        missing = sorted(allowed - found_ids)
        if missing:
            print(f"❌ P1 roster id(s) not found in {p1_split}: {missing}")
            return
        p1_rosters = [(ref, rid) for ref, rid in p1_rosters if rid in allowed]
        print(
            f"📌 P1 subset: {len(p1_rosters)} roster(s) vs {len(p2_rosters)} P2 "
            f"({current_split}, {args.episodes} ep/matchup)"
        )
    if args.p2_benchmark:
        p2_rosters = [(ref, rid) for ref, rid in p2_rosters if rid == args.p2_benchmark]
        if not p2_rosters:
            print(f"❌ P2 benchmark '{args.p2_benchmark}' not found in {p2_split}")
            return
        print(f"📌 P2 benchmark: {args.p2_benchmark} (from {p2_split}, evaluating {len(p1_rosters)} P1 rosters from {p1_split})")

    if args.p1_exclude:
        excl = {x.strip() for x in str(args.p1_exclude).split(",") if x.strip()}
        if not excl:
            print("❌ --p1-exclude is empty")
            return
        before_ids = {rid for _, rid in p1_rosters}
        unknown_excl = sorted(excl - before_ids)
        if unknown_excl:
            print(f"⚠️  --p1-exclude id(s) not in current P1 set (ignored): {unknown_excl}")
        before_n = len(p1_rosters)
        p1_rosters = [(ref, rid) for ref, rid in p1_rosters if rid not in excl]
        print(
            f"📌 P1 exclude: removed {before_n - len(p1_rosters)} roster(s), "
            f"{len(p1_rosters)} remaining ({current_split})"
        )
        if not p1_rosters:
            print("❌ No P1 rosters left after --p1-exclude")
            return

    scenario_subdir = current_split
    scenario_dir = PROJECT_ROOT / "config" / "agents" / args.agent / "scenarios" / scenario_subdir
    matchup_dir = scenario_dir / "matchups"
    matchup_dir.mkdir(parents=True, exist_ok=True)
    run_label_raw = str(eval_bot_name) if eval_bot_name else str(args.opponent_mode)
    run_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", run_label_raw)
    run_matchup_dir = matchup_dir / f"run_{current_split}_{run_label}_{os.getpid()}_{int(time.time() * 1000)}"
    run_matchup_dir.mkdir(parents=True, exist_ok=True)
    template = _build_scenario_template(
        args.scale,
        args.board_ref,
        args.terrain_ref,
    )
    obs_normalizer = _build_obs_normalizer(args.agent, args.training_config, model_path)

    matchups: Dict[str, Dict[str, Dict[str, Any]]] = {}
    total_matchups = len(p1_rosters) * len(p2_rosters)
    current = 0
    total_matchup_seconds = 0.0
    for p1_ref, p1_id in p1_rosters:
        matchups[p1_id] = {}
        for p2_ref, p2_id in p2_rosters:
            current += 1
            matchup_start = time.perf_counter()
            scenario_data = {
                **template,
                "agent_roster_ref": p1_ref,
                "opponent_roster_ref": p2_ref,
            }
            scenario_file = run_matchup_dir / f"matchup_{p1_id}_{p2_id}.json"
            write_json_atomic(scenario_file, scenario_data)
            scenario_path = str(scenario_file)
            print(f"[{current}/{total_matchups}] {p1_id} vs {p2_id}...", end=" ", flush=True)
            if args.opponent_mode == "agent" and bool(args.agent_seat_bidirectional):
                wins_p1, losses_p1, draws_p1, failed_p1 = _run_matchup_episodes(
                    scenario_path,
                    args.agent,
                    model_path,
                    args.training_config,
                    rewards_config,
                    args.episodes,
                    opponent_mode="agent",
                    eval_bot_name=eval_bot_name,
                    eval_bot_randomness=float(args.eval_bot_randomness),
                    agent_seat_mode="p1",
                    obs_normalizer=obs_normalizer,
                )
                wins_p2, losses_p2, draws_p2, failed_p2 = _run_matchup_episodes(
                    scenario_path,
                    args.agent,
                    model_path,
                    args.training_config,
                    rewards_config,
                    args.episodes,
                    opponent_mode="agent",
                    eval_bot_name=eval_bot_name,
                    eval_bot_randomness=float(args.eval_bot_randomness),
                    agent_seat_mode="p2",
                    obs_normalizer=obs_normalizer,
                )
                wins = wins_p1 + wins_p2
                losses = losses_p1 + losses_p2
                draws = draws_p1 + draws_p2
                failed = failed_p1 + failed_p2
            else:
                wins, losses, draws, failed = _run_matchup_episodes(
                    scenario_path,
                    args.agent,
                    model_path,
                    args.training_config,
                    rewards_config,
                    args.episodes,
                    opponent_mode=str(args.opponent_mode),
                    eval_bot_name=eval_bot_name,
                    eval_bot_randomness=float(args.eval_bot_randomness),
                    agent_seat_mode=str(args.agent_seat_mode),
                    obs_normalizer=obs_normalizer,
                )
            # Les episodes tronques sont EXCLUS du denominateur : ce ne sont pas des parties.
            total = wins + losses + draws
            if total == 0:
                raise RuntimeError(
                    f"Matchup {p1_id} vs {p2_id} : aucun episode n'est alle au bout "
                    f"({failed} tronque(s) sur {args.episodes}). Aucun taux de victoire n'en "
                    f"est deductible — un 0.0 de repli serait une statistique inventee."
                )
            win_rate = wins / total
            matchups[p1_id][p2_id] = {
                "wins": wins,
                "losses": losses,
                "draws": draws,
                # Meme nom que la reference (`ai/bot_evaluation._eval_worker_task`) : episodes tronques par
                # le plafond de pas, hors du calcul du taux de victoire.
                "failed_episodes": failed,
                "win_rate": round(win_rate, 4),
            }
            matchup_elapsed = time.perf_counter() - matchup_start
            total_matchup_seconds += matchup_elapsed
            avg_matchup_seconds = total_matchup_seconds / float(current)
            avg_matchup_text = f"{avg_matchup_seconds:.3f}".replace(".", ",")
            failed_text = f" | ⚠️ {failed} tronque(s)" if failed else ""
            print(
                f"WR={win_rate:.2%} ({wins}W-{losses}L-{draws}D){failed_text} "
                f"| avg: {avg_matchup_text}s"
            )
            try:
                scenario_file.unlink()
            except OSError:
                pass
    try:
        run_matchup_dir.rmdir()
    except OSError:
        pass

    overall_wr = sum(
        m["win_rate"] for p1_data in matchups.values() for m in p1_data.values()
    ) / max(1, total_matchups)
    p1_summaries: List[Dict[str, Any]] = []
    for p1_id, p2_data in matchups.items():
        rates = [m["win_rate"] for m in p2_data.values()]
        avg_wr = sum(rates) / len(rates) if rates else 0
        best = max(p2_data.items(), key=lambda x: x[1]["win_rate"])
        worst = min(p2_data.items(), key=lambda x: x[1]["win_rate"])
        p1_summaries.append({
            "p1_roster_id": p1_id,
            "overall_win_rate": round(avg_wr, 4),
            "vs_best": best[0],
            "vs_worst": worst[0],
            "sur_performant": avg_wr > overall_wr + 0.05,
            "sous_performant": avg_wr < overall_wr - 0.05,
        })
    p2_summaries: List[Dict[str, Any]] = []
    for _p2_ref, p2_id in p2_rosters:
        rates = [matchups[p1_id][p2_id]["win_rate"] for p1_id in matchups if p2_id in matchups[p1_id]]
        if not rates:
            continue
        avg_wr = sum(rates) / len(rates)
        p2_summaries.append({
            "p2_roster_id": p2_id,
            "p1_win_rate_vs_this_p2": round(avg_wr, 4),
            "sur_performant_p2": avg_wr < overall_wr - 0.05,
            "sous_performant_p2": avg_wr > overall_wr + 0.05,
        })

    use_quantile_merge = bool(
        args.merge_full_matrices and (args.quantile_p1 or args.quantile_p2)
    )
    if use_quantile_merge:
        full_path = matchups_out_dir / f"{current_split}_matchups_{eval_bot_name}.json"
        _merge_partial_into_full_json(
            full_path,
            matchups,
            p1_rosters_full,
            p2_rosters_full,
            args,
            model_path,
            eval_bot_name,
            current_split,
        )
        return

    if args.p1_benchmark:
        out_filename = f"{p1_rosters[0][1]}_matchups_{eval_bot_name}.json"
    elif args.p2_benchmark:
        out_filename = f"{p2_rosters[0][1]}_matchups_{eval_bot_name}.json"
    elif args.p1_rosters:
        out_filename = f"{current_split}_matchups_{eval_bot_name}_p1subset.json"
    elif args.p1_exclude:
        # Ne pas écraser la matrice complète quand seul --p1-exclude réduit la liste P1
        out_filename = f"{current_split}_matchups_{eval_bot_name}_p1exclude.json"
    elif args.quantile_p1 or args.quantile_p2:
        parts = []
        if args.quantile_p1:
            parts.append(f"agent_{args.quantile}")
        if args.quantile_p2:
            parts.append(f"opponent_{args.quantile}")
        qrole = "_".join(parts)
        out_filename = f"{current_split}_matchups_{eval_bot_name}_quantile_{qrole}.json"
    else:
        out_filename = f"{current_split}_matchups_{eval_bot_name}.json"
    out_path = matchups_out_dir / out_filename
    output: Dict[str, Any] = {
        "agent_key": args.agent,
        "scale": args.scale,
        "split": current_split,
        "model_path": model_path,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "episodes_per_matchup": args.episodes,
        "p1_benchmark": args.p1_benchmark,
        "p1_benchmark_split": args.p1_benchmark_split,
        "p2_benchmark": args.p2_benchmark,
        "p2_benchmark_split": args.p2_benchmark_split,
        "quantile": args.quantile,
        "quantile_owners": list(args.quantile_owners),
        "quantile_frac": float(args.quantile_frac),
        "opponent_mode": str(args.opponent_mode),
        "agent_seat_mode": str(args.agent_seat_mode),
        "agent_seat_bidirectional": bool(args.agent_seat_bidirectional),
        "eval_bot": eval_bot_name,
        "eval_bot_randomness": float(args.eval_bot_randomness),
        "overall_win_rate": round(overall_wr, 4),
        "matchups": matchups,
        "p1_summaries": sorted(p1_summaries, key=lambda x: -x["overall_win_rate"]),
        "p2_summaries": sorted(p2_summaries, key=lambda x: x["p1_win_rate_vs_this_p2"]),
    }
    write_json_atomic(out_path, output)
    print(f"\n✅ Wrote {out_path}")


if __name__ == "__main__":
    main()
