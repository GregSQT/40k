#!/usr/bin/env python3
"""Mesure directe de l'étalement des bots (zones contrôlées par tour).

Joue des épisodes de bot eval sans passer par train.py ni step_logger.
Lit game_state["objective_controllers"] après chaque step pour compter les zones
contrôlées par le bot player (opponent_player).

⚠️ DEUX ENTRÉES DÉCIDENT DU CHIFFRE AUTANT QUE LES POIDS MESURÉS, et les deux étaient
silencieuses (corrigé le 2026-08-13) :

1. LE MODÈLE. Le script lisait le chemin CANONIQUE `model_ArmageddonAgent.zip`, que le moindre
   entraînement réécrit : le 2026-08-13 il valait md5 1072b0c6…, quand toutes les mesures du §12
   du chantier (référence T2=1.61 / T5=1.90 imprimée en bas) sont faites sur le checkpoint
   `robust_0.8721` (md5 6f6b98…). Deux campagnes se comparaient donc sans modèle commun, et rien
   ne le disait. Le checkpoint de référence est désormais NOMMÉ et VÉRIFIÉ AU MD5 — le jour où il
   change, le script lève au lieu de rendre un tableau incomparable. Son `_vec_normalize.pkl`
   apparié suit automatiquement (`get_vec_normalize_path` le dérive du zip chargé).
2. LE PLATEAU. Sans `W40K_BOARD_PATH`, c'est `config/config.json` qui décide (x5), où le classement
   des bots N'EST PAS le même — cf. l'avertissement de `config/bot_movement_weights.json`, qui a
   déjà coûté une campagne entière. La variable est donc EXIGÉE, pas défaultée.

Usage:
    W40K_BOARD_PATH=board/44x60x1 python3 scripts/bot_zone_direct.py [--episodes N]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Le modèle SUR LEQUEL TOUT LE §12 EST MESURÉ. Ce n'est pas « un modèle récent » : c'est l'étalon
#: qui rend les campagnes comparables entre elles. Le remplacer est une décision de protocole, qui
#: périme les chiffres du chantier — donc elle s'écrit ici, elle ne s'attrape pas par un
#: entraînement qui a réécrit le chemin canonique.
REFERENCE_MODEL = "ArmageddonAgent_12345_robust_0.8721.zip"
REFERENCE_MD5 = "6f6b98059a0a6c279b7d11dc427461fd"


def _require_reference_model() -> str:
    """Chemin du modèle étalon, vérifié au md5. Lève plutôt que de mesurer un autre modèle."""
    path = os.path.join(_PROJECT_ROOT, "ai", "models", "ArmageddonAgent", REFERENCE_MODEL)
    if not os.path.exists(path):
        raise RuntimeError(
            f"Modèle de référence absent : {path}. Toutes les mesures du §12 sont faites sur lui ; "
            "mesurer avec un autre rend le tableau incomparable."
        )
    with open(path, "rb") as handle:
        digest = hashlib.md5(handle.read()).hexdigest()
    if digest != REFERENCE_MD5:
        raise RuntimeError(
            f"{REFERENCE_MODEL} vaut md5 {digest}, attendu {REFERENCE_MD5} : le fichier a été "
            "réécrit. Restaurer le checkpoint, ou acter le nouvel étalon ICI et rejouer le §12."
        )
    return path


def _require_board_path() -> str:
    """Le plateau vient de l'environnement, jamais de config.json (cf. l'en-tête)."""
    board = os.environ.get("W40K_BOARD_PATH")
    if not board:
        raise RuntimeError(
            "W40K_BOARD_PATH non défini : sans elle le plateau est celui de config.json (x5), où "
            "le classement des bots diffère. Relancer avec W40K_BOARD_PATH=board/44x60x1."
        )
    return board


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=10)
    args = parser.parse_args()

    board_path = _require_board_path()

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

    model_path = _require_reference_model()
    vec_norm_enabled = bool(tc.get("vec_normalize", {}).get("enabled", False))
    vec_eval_enabled = bool(tc.get("vec_normalize_eval", {}).get("enabled", False))

    print(f"Modèle : {os.path.basename(model_path)} (md5 {REFERENCE_MD5})")
    print(f"Plateau : {board_path}")
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

    results: Dict[str, Dict[int, List[int]]] = {}

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

        ep_zones: Dict[int, List[int]] = defaultdict(list)

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

            for t, z in turn_snapshot.items():
                ep_zones[t].append(z)
            print(".", end="", flush=True)

        env.close()
        results[bot_name] = dict(ep_zones)
        last_t = max(ep_zones) if ep_zones else 0
        n = len(ep_zones.get(last_t, []))
        print(f" {n} ep")

    turns = [1, 2, 3, 4, 5]
    hdr = " | ".join(f"T{t}" for t in turns)
    print(f"\n{'Bot':<22} {'N':>4} | {hdr}")
    print("-" * (22 + 4 + 3 + len(turns) * 6 + 4))
    for bot, tdata in sorted(results.items()):
        last_t = max(tdata) if tdata else 0
        n = len(tdata.get(last_t, []))
        cells = []
        for t in turns:
            vals = tdata.get(t, [])
            cells.append(f"{sum(vals)/len(vals):.2f}" if vals else "  - ")
        print(f"{bot:<22} {n:>4} | " + " | ".join(f"{c:>4}" for c in cells))

    print()
    print("Référence §12.5 (post-§12.6, bot=P2, 100 ep): T2=1.61  T5=1.90  VP=31.0  combined=0.788")


if __name__ == "__main__":
    main()
