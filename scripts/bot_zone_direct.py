#!/usr/bin/env python3
"""Mesure directe de l'étalement des bots (zones contrôlées par tour).

Joue des épisodes de bot eval sans passer par train.py ni step_logger.
Lit game_state["objective_controllers"] après chaque step pour compter les zones
contrôlées par le bot player (opponent_player).

Usage:
    source .venv/bin/activate && python3 scripts/bot_zone_direct.py [--episodes N]
                                                                   [--json-out FICHIER]

`--json-out` écrit le relevé PAR ÉPISODE (graine, joueur du bot, zones par tour) : la sortie
texte agrégée reste identique, seul s'y ajoute le chemin du fichier écrit.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, TextIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 2 : `run` regroupe les métadonnées du run, `model` (basename) devient `model_path`/`model_bytes`
# /`model_mtime`. Un lecteur de la v1 lèverait un KeyError sur un fichier v2 — d'où le numéro.
_JSON_SCHEMA_VERSION = 2


def _episode_record(
    bot_name: str,
    episode: int,
    seed: int,
    bot_player: int,
    turn_snapshot: Dict[int, int],
) -> Dict[str, Any]:
    """Relevé d'UN épisode, suffisant pour le rejouer (graine) et l'inspecter (zones/tour)."""
    return {
        "bot": bot_name,
        "episode": episode,
        "seed": seed,
        "bot_player": bot_player,
        "zones_by_turn": {str(t): turn_snapshot[t] for t in sorted(turn_snapshot)},
    }


def _turns_of(records: List[Dict[str, Any]]) -> Dict[int, List[int]]:
    """{tour: [zones, un par épisode]} pour les relevés d'UN seul bot, dans l'ordre des épisodes."""
    per_turn: Dict[int, List[int]] = {}
    for rec in records:
        for turn_key, zones in rec["zones_by_turn"].items():
            per_turn.setdefault(int(turn_key), []).append(zones)
    return per_turn


def _aggregate_zones(records: List[Dict[str, Any]]) -> Dict[str, Dict[int, List[int]]]:
    """Agrège les relevés par épisode en {bot: {tour: [zones, ...]}} — source du tableau texte."""
    by_bot: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        by_bot.setdefault(rec["bot"], []).append(rec)
    return {bot: _turns_of(bot_records) for bot, bot_records in by_bot.items()}


def _n_at_last_turn(per_turn: Dict[int, List[int]]) -> int:
    """Nombre d'épisodes parvenus au dernier tour observé — le `N` de la ligne et du tableau."""
    if not per_turn:
        return 0
    return len(per_turn[max(per_turn)])


def _part_path(path: str) -> str:
    return path + ".part"


@contextlib.contextmanager
def _json_out_draft(path: Optional[str]) -> Iterator[Optional[TextIO]]:
    """Brouillon ouvert AVANT de jouer, publié seulement si le run va jusqu'au bout.

    Tout ce qui peut rater sur la destination doit rater ici, en une seconde, pas après la
    partie quand les graines sont déjà perdues. Deux contrôles, parce qu'aucun ne suffit :
    `path` ne doit pas être un DOSSIER (le `os.replace` final échouerait seul, tout à la fin),
    et le brouillon `<path>.part` doit s'ouvrir (ce qui prouve, syscall à l'appui, que le
    dossier existe et qu'il est inscriptible — un `isdir` laisserait passer une lecture seule).
    Écrire dans le brouillon plutôt que dans `path` protège le relevé PRÉCÉDENT : il reste
    intact tant que le nouveau n'est pas complet, et la publication est atomique.
    Aucune création de dossier : un chemin faux se voit, il ne se répare pas en silence.
    Sortie par exception : le brouillon est refermé ET effacé — pas de résidu vide à trier.
    """
    if path is None:
        yield None
        return
    if os.path.isdir(path):
        raise IsADirectoryError(f"--json-out {path} est un dossier : la destination doit être un fichier")
    handle = open(_part_path(path), "w", encoding="utf-8")
    try:
        yield handle
    except BaseException:
        handle.close()
        os.remove(_part_path(path))
        raise
    handle.close()
    os.replace(_part_path(path), path)


def _write_json_out(handle: TextIO, run_meta: Dict[str, Any], records: List[Dict[str, Any]]) -> None:
    payload = {"schema_version": _JSON_SCHEMA_VERSION, "run": run_meta, "episodes": records}
    json.dump(payload, handle, ensure_ascii=False, indent=2)
    handle.write("\n")


def _model_fingerprint(model_path: str) -> Dict[str, Any]:
    """Identité du checkpoint, à relever AVANT de le charger : un entraînement qui réécrit le
    `.zip` pendant le run ferait sinon consigner les métadonnées d'un modèle qui n'a pas joué.
    Le chemin seul est constant d'un run à l'autre, donc muet — c'est la taille et la date
    qui distinguent deux checkpoints.
    """
    return {
        "model_path": model_path,
        "model_bytes": os.path.getsize(model_path),
        "model_mtime": datetime.fromtimestamp(os.path.getmtime(model_path)).isoformat(timespec="seconds"),
    }


def _run_meta(
    model_fingerprint: Dict[str, Any],
    scenario_file: str,
    episodes_requested: int,
    base_seed: int,
    agent_seat_mode: str,
    agent_seat_seed: Optional[int],
    bot_randomness: Dict[str, Any],
) -> Dict[str, Any]:
    """Ce qui distingue DEUX relevés l'un de l'autre — sans ça, un avant et un après §12.7
    sont indiscernables, et une graine d'épisode ne suffit pas à reconstruire la doctrine du bot.
    """
    return {
        "agent": "ArmageddonAgent",
        "training_config": "x1_panel",
        **model_fingerprint,
        "scenario_file": scenario_file,
        "episodes_requested": episodes_requested,
        "base_seed": base_seed,
        "agent_seat_mode": agent_seat_mode,
        "agent_seat_seed": agent_seat_seed,
        "bot_randomness": dict(bot_randomness),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument(
        "--json-out",
        dest="json_out",
        default=None,
        help="Fichier JSON où écrire le relevé par épisode (graine, joueur du bot, zones par tour)",
    )
    args = parser.parse_args()

    # le brouillon s'ouvre AVANT les imports lourds : un chemin faux coûte une seconde, et il
    # n'est publié que si le run va au bout (sinon refermé et effacé, cf. `_json_out_draft`).
    with _json_out_draft(args.json_out) as json_handle:
        import numpy as np
        from sb3_contrib import MaskablePPO
        from sb3_contrib.common.wrappers import ActionMasker
        from sb3_contrib.common.maskable.utils import get_action_masks
        from config_loader import get_config_loader
        from ai.unit_registry import UnitRegistry
        from ai.bot_registry import build_bot
        from ai.env_wrappers import BotControlledEnv
        from ai.training_utils import get_scenario_list_for_phase
        from ai.bot_evaluation import _build_eval_obs_normalizer_for_worker, _episode_seed
        from engine.w40k_core import W40KEngine

        config = get_config_loader()
        tc = config.load_agent_training_config("ArmageddonAgent", "x1_panel")
        cb = tc["callback_params"]

        model_path = os.path.join(_PROJECT_ROOT, "ai", "models", "ArmageddonAgent", "model_ArmageddonAgent.zip")
        vec_norm_enabled = bool(tc.get("vec_normalize", {}).get("enabled", False))
        vec_eval_enabled = bool(tc.get("vec_normalize_eval", {}).get("enabled", False))

        print(f"Modèle : {os.path.basename(model_path)}")
        model_fingerprint = _model_fingerprint(model_path)  # avant le chargement : cf. docstring
        model = MaskablePPO.load(model_path, device="cpu")
        normalize = _build_eval_obs_normalizer_for_worker(model, model_path, vec_norm_enabled, vec_eval_enabled)

        bot_weights: dict = cb.get("bot_eval_weights", {})
        bot_randomness: dict = cb.get("bot_eval_randomness", {})
        agent_seat_mode: str = tc.get("agent_seat_mode", "p1")
        if "seed" not in tc:
            raise RuntimeError("Clé 'seed' absente de la config d'entraînement ArmageddonAgent/x1_panel — run non reproductible")
        base_seed: int = int(tc["seed"])
        agent_seat_seed: Optional[int] = tc.get("agent_seat_seed", base_seed)

        scenarios = get_scenario_list_for_phase(config, "ArmageddonAgent", "x1_panel", scenario_type="holdout")
        if not scenarios:
            raise RuntimeError("Aucun scénario holdout trouvé pour ArmageddonAgent/x1_panel — vérifier config/agents/ArmageddonAgent/scenarios/")
        scenario_file = scenarios[0]

        episode_records: List[Dict[str, Any]] = []

        for bot_name in bot_weights:
            print(f"  {bot_name:<16}", end=" ", flush=True)
            bot = build_bot(bot_name, dict(bot_randomness))
            unit_registry = UnitRegistry()

            base_env = W40KEngine(
                rewards_config="ArmageddonAgent",
                training_config_name="x1_panel",
                controlled_agent="ArmageddonAgent",
                active_agents=None,
                scenario_file=scenario_file,
                unit_registry=unit_registry,
                quiet=True,
                gym_training_mode=True,
                training_n_envs=1,
            )

            masked = ActionMasker(base_env, lambda e: e.get_action_mask())
            env = BotControlledEnv(
                masked, bot, unit_registry,
                agent_seat_mode=agent_seat_mode,
                global_seed=agent_seat_seed,
                env_rank=0,
            )

            bot_records: List[Dict[str, Any]] = []

            for ep_idx in range(args.episodes):
                ep_seed = _episode_seed(base_seed, bot_name, 0, ep_idx)
                obs, info = env.reset(seed=ep_seed)
                bot_player: int = int(info.get("opponent_player", 2))
                done = False
                turn_snapshot: Dict[int, int] = {}

                while not done:
                    model_obs = normalize(obs) if normalize else obs
                    action_masks = np.asarray(get_action_masks(env), dtype=bool)
                    if action_masks.ndim == 1:
                        action_masks = action_masks.reshape(1, -1)
                    if isinstance(model_obs, dict):
                        model_input = model_obs
                    else:
                        model_input = np.asarray(model_obs, dtype=np.float32)
                        if model_input.ndim == 1:
                            model_input = model_input.reshape(1, -1)
                    action, _ = model.predict(model_input, action_masks=action_masks, deterministic=True)
                    action_scalar = int(np.asarray(action).flat[0])
                    obs, _, terminated, truncated, _ = env.step(action_scalar)
                    done = bool(terminated or truncated)

                    gs = env.engine.game_state
                    cur_turn: int = int(gs.get("turn", 0))
                    if cur_turn >= 1:
                        controllers: dict = gs.get("objective_controllers", {})
                        zones = sum(1 for v in controllers.values() if v == bot_player)
                        turn_snapshot[cur_turn] = zones

                bot_records.append(_episode_record(bot_name, ep_idx, ep_seed, bot_player, turn_snapshot))
                print(".", end="", flush=True)

            env.close()
            episode_records.extend(bot_records)
            print(f" {_n_at_last_turn(_turns_of(bot_records))} ep")

        turns = [1, 2, 3, 4, 5]
        hdr = " | ".join(f"T{t}" for t in turns)
        print(f"\n{'Bot':<22} {'N':>4} | {hdr}")
        print("-" * (22 + 4 + 3 + len(turns) * 6 + 4))
        # le tableau est DÉRIVÉ des mêmes relevés que le JSON : les deux ne peuvent pas diverger.
        aggregated = _aggregate_zones(episode_records)
        for bot in sorted(bot_weights):
            tdata = aggregated.get(bot, {})
            cells = []
            for t in turns:
                vals = tdata.get(t, [])
                cells.append(f"{sum(vals)/len(vals):.2f}" if vals else "  - ")
            print(f"{bot:<22} {_n_at_last_turn(tdata):>4} | " + " | ".join(f"{c:>4}" for c in cells))

        if json_handle is not None:
            run_meta = _run_meta(
                model_fingerprint, scenario_file, args.episodes, base_seed,
                agent_seat_mode, agent_seat_seed, bot_randomness,
            )
            _write_json_out(json_handle, run_meta, episode_records)
            print(f"\nRelevé par épisode : {args.json_out} ({len(episode_records)} épisodes)")

        print()
        print("Référence §12.5 (post-§12.6, bot=P2, 100 ep): T2=1.61  T5=1.90  VP=31.0  combined=0.788")


if __name__ == "__main__":
    main()
