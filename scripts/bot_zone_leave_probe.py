#!/usr/bin/env python3
"""Quand un bot quitte une zone d'objectif, OÙ VA-T-IL, et quel terme l'y pousse ?

`bot_zone_direct.py` mesure un RÉSULTAT (zones tenues par tour) ; cette sonde mesure la
DÉCISION qui le produit. Elle a été écrite pour départager les deux mécanismes candidats du
§12.15 de `Documentation/Reference/training/panel_bots.md`, et c'est son chiffre qui a tranché :

  - côté ENNEMI : le bot abandonne la zone pour du VIDE, et neutraliser `w_enemy` le fait rester.
    Le terme ennemi, linéaire par hexe et sans plafond, bat le forfait de tenue de zone ;
  - côté OBJECTIF : le bot part sans que `w_enemy` y soit pour quelque chose. Le forfait
    `hold_bonus` ne distingue pas une 1re zone d'une 4e, et il s'annule entre deux zones.

TÉMOIN NATUREL, et c'est lui qui rend la sonde vérifiable : `scorer` a `w_enemy = 0.0` depuis le
§12.9. Le contrefactuel « w_enemy = 0 » ne change donc RIEN chez lui et DOIT rendre 0,0 %. Toute
autre valeur dénonce l'instrument, pas le bot — c'est ce qui est arrivé à la première version
(20,5 %, cf. `_counterfactual_choice`). Ne jamais lire cette sortie sans regarder cette case.

MÉTHODE. On enveloppe `select_movement_destination` et, pour chaque décision prise DEPUIS une
zone, on rejoue la même décision avec un terme neutralisé — en appelant la vraie fonction, jamais
en réimplémentant son score.

⚠️ « hors zone » NE VEUT PAS DIRE « perdu ». Le pool de destinations est borné par le mouvement :
partir vers une zone lointaine passe par des hexes qui n'appartiennent à aucune zone, et
l'étalement volontaire de `w_crowd` produit exactement ça. C'est le TERME retenu qui distingue la
poursuite d'ennemi du transit, pas la classe de destination.

Usage :
    W40K_BOARD_PATH=board/44x60x1 python3 scripts/bot_zone_leave_probe.py \\
        --episodes 30 --bots alpha,decapitation,scorer
"""
from __future__ import annotations

import argparse
import copy
import os
import gymnasium
import random
import sys
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, cast

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Chaque contrefactuel neutralise UN terme du sextuplet rendu par `movement_weights`
#: (w_objective, w_enemy, w_fire, w_risk, w_contest, w_crowd). Un seul à la fois : deux termes
#: neutralisés ensemble ne disent plus lequel portait la décision.
COUNTERFACTUALS: Dict[str, int] = {"w_enemy=0": 1, "w_crowd=0": 5}

_TRAINING_CONFIG = "x1_long"


def zone_index(pos: Tuple[int, int], zones: Sequence[set]) -> Optional[int]:
    """Index de la zone contenant l'ANCRE, ou None.

    L'ancre et non l'empreinte de socle : c'est ainsi que `_geometric` classe ses candidates
    (`any(d in zone for zone in zones)`), et une sonde doit classer comme le score classe. La
    lecture par figurine, exacte, ne vaut que pour la position COURANTE et n'a pas d'équivalent
    pour une destination candidate.
    """
    for i, zone in enumerate(zones):
        if pos in zone:
            return i
    return None


def _counterfactual_choice(
    bot: Any,
    original: Callable,
    real_weights: Callable,
    unit: Any,
    valid_destinations: List[Tuple[int, int]],
    game_state: Any,
    index: int,
    pre_states: Tuple[Any, Any],
) -> Tuple[int, int]:
    """Rejoue UNE décision avec le terme `index` mis à zéro, sans rien laisser derrière.

    ⚠️ LES TIRAGES SONT REMIS À L'ÉTAT D'AVANT L'APPEL RÉEL, et c'est le point : les bots tirent
    (`bot_eval_randomness` = 0.05) à chaque décision. Une première version repartait de l'état
    d'APRÈS l'appel réel — le contrefactuel voyait donc d'autres tirages et prenait la branche
    aléatoire quand l'appel réel ne l'avait pas prise. Mesure du défaut : `scorer`, dont
    `w_enemy` vaut DÉJÀ 0.0, voyait 20,5 % de ses départs « retenus » par un contrefactuel qui ne
    changeait rien. Le témoin naturel a dénoncé l'instrument avant que ses chiffres ne servent.

    ⚠️ L'ÉTAT DU BOT EST RESTAURÉ : `DecapitationBot._enemy_anchors` ÉCRIT `_focus_target` quand
    la cible est morte, donc un appel contrefactuel peut élire une cible que le bot n'aurait pas
    eue, et la vraie partie continuerait dessus.
    """
    import numpy as np

    poids = list(real_weights(unit, game_state))
    poids[index] = 0.0
    snapshot = copy.copy(bot.__dict__)
    pre_rng, pre_np = pre_states
    bot.movement_weights = lambda u, g, _p=tuple(poids): _p
    try:
        random.setstate(pre_rng)
        np.random.set_state(pre_np)
        return original(unit, valid_destinations, game_state)
    finally:
        bot.movement_weights = real_weights
        bot.__dict__.clear()
        bot.__dict__.update(snapshot)


def _install_probe(bot: Any, tally: Dict[str, int]) -> None:
    """Enveloppe `select_movement_destination` du bot pour compter les départs de zone."""
    import numpy as np

    from ai.bot_doctrines import objective_hex_sets
    from engine.phase_handlers.shared_utils import require_unit_from_cache
    from shared.data_validation import require_key

    original = bot.select_movement_destination
    real_weights = bot.movement_weights

    def wrapped(unit, valid_destinations, game_state=None):
        pre_states = (random.getstate(), np.random.get_state())
        chosen = original(unit, valid_destinations, game_state)
        if game_state is None:
            return chosen
        zones = objective_hex_sets(game_state)
        if not zones:
            return chosen
        entry = require_unit_from_cache(str(require_key(unit, "id")), game_state, "_probe")
        depuis = zone_index((int(entry["col"]), int(entry["row"])), zones)
        if depuis is None:
            return chosen  # décision prise hors zone : hors sujet de la sonde

        tally["depuis_zone"] += 1
        vers = zone_index((int(chosen[0]), int(chosen[1])), zones)
        if vers == depuis:
            tally["reste"] += 1
            return chosen
        classe = "autre_zone" if vers is not None else "hors_zone"
        tally[classe] += 1

        post_states = (random.getstate(), np.random.get_state())
        for libelle, index in COUNTERFACTUALS.items():
            autre = _counterfactual_choice(
                bot, original, real_weights, unit, valid_destinations, game_state,
                index, pre_states,
            )
            if zone_index((int(autre[0]), int(autre[1])), zones) is not None:
                # Le terme neutralisé était CE QUI faisait quitter la zone.
                tally[f"{classe}|retenu_par_{libelle}"] += 1
        random.setstate(post_states[0])
        np.random.set_state(post_states[1])
        return chosen

    bot.select_movement_destination = wrapped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=30)
    parser.add_argument(
        "--bots",
        default="alpha,decapitation,scorer",
        help="Styles à sonder. Garder `scorer` : c'est le témoin qui valide l'instrument.",
    )
    args = parser.parse_args()

    import numpy as np
    from sb3_contrib import MaskablePPO
    from sb3_contrib.common.wrappers import ActionMasker
    from sb3_contrib.common.maskable.utils import get_action_masks
    from config_loader import get_config_loader
    from ai.unit_registry import UnitRegistry
    from ai.bot_registry import build_bot
    from ai.env_wrappers import BotControlledEnv
    from ai.training_utils import get_scenario_list_for_phase
    from ai.bot_evaluation import (
        _build_eval_obs_normalizer_for_worker, _episode_seed, _load_bot_eval_params,
    )
    from engine.w40k_core import W40KEngine
    from shared.data_validation import require_key

    from bot_zone_direct import _require_board_path, _require_reference_model, _prepare_model_input

    board_path = _require_board_path()
    model_path = _require_reference_model()
    config = get_config_loader()
    tc = config.load_agent_training_config("ArmageddonAgent_x1", _TRAINING_CONFIG)
    model = MaskablePPO.load(model_path, device="cpu")
    normalize = _build_eval_obs_normalizer_for_worker(
        model, model_path,
        bool(tc.get("vec_normalize", {}).get("enabled", False)),
        bool(tc.get("vec_normalize_eval", {}).get("enabled", False)),
    )
    params = _load_bot_eval_params(config, "ArmageddonAgent_x1", _TRAINING_CONFIG)
    randomness = params["randomness"]
    agent_seat_mode = require_key(tc, "agent_seat_mode")
    base_seed = int(require_key(tc, "seed"))
    seat_seed = tc.get("agent_seat_seed", base_seed)
    scenarios = get_scenario_list_for_phase(config, "ArmageddonAgent_x1", _TRAINING_CONFIG, scenario_type="holdout")
    if not scenarios:
        raise RuntimeError(f"Aucun scénario holdout trouvé pour ArmageddonAgent/{_TRAINING_CONFIG} — vérifier config/agents/ArmageddonAgent_x1/scenarios/")
    scenario_file = scenarios[0]

    print(f"Modèle : {os.path.basename(model_path)}   Plateau : {board_path}")

    obs_space = model.observation_space
    if not isinstance(obs_space, gymnasium.spaces.Dict):
        raise TypeError(f"Espace d'observation Dict attendu, reçu {type(obs_space)}")
    model_known = set(obs_space.spaces.keys())
    tallies: Dict[str, Dict[str, int]] = {}
    for bot_name in [b.strip() for b in args.bots.split(",") if b.strip()]:
        bot = build_bot(bot_name, dict(randomness))
        registry = UnitRegistry()
        base_env = W40KEngine(
            rewards_config="ArmageddonAgent_x1", training_config_name=_TRAINING_CONFIG,
            controlled_agent="ArmageddonAgent_x1", active_agents=None,
            scenario_file=scenario_file, unit_registry=registry,
            quiet=True, gym_training_mode=True, training_n_envs=1,
        )
        env = BotControlledEnv(
            ActionMasker(base_env, lambda e: cast(W40KEngine, e).get_action_mask()), bot, registry,
            agent_seat_mode=agent_seat_mode, global_seed=seat_seed, env_rank=0,
        )
        tally: Dict[str, int] = defaultdict(int)
        _install_probe(bot, tally)

        print(f"  {bot_name:<14}", end=" ", flush=True)
        for ep_idx in range(args.episodes):
            ep_seed = _episode_seed(base_seed, bot_name, 0, ep_idx)
            random.seed(ep_seed)
            np.random.seed(ep_seed)
            obs, _info = env.reset(seed=ep_seed)
            env.engine.game_state["no_gym_allocation_model"] = True
            done = False
            while not done:
                model_obs = normalize(obs) if normalize else obs
                masks = np.asarray(get_action_masks(env), dtype=bool)
                if masks.ndim == 1:
                    masks = masks.reshape(1, -1)
                model_input = _prepare_model_input(model_obs, model_known)
                action, _ = model.predict(model_input, action_masks=masks, deterministic=True)
                obs, _r, term, trunc, _i = env.step(int(np.asarray(action).flat[0]))
                done = bool(term or trunc)
            print(".", end="", flush=True)
        env.close()
        print(f" {tally['depuis_zone']} décisions depuis une zone")
        tallies[bot_name] = dict(tally)

    print(f"\n{'bot':<14} {'N':>6} | {'reste':>12} | {'autre zone':>12} | {'hors zone':>12}")
    print("-" * 66)
    for bot_name, t in tallies.items():
        n = t.get("depuis_zone", 0) or 1
        cells = " | ".join(
            f"{t.get(k, 0):>5} {100 * t.get(k, 0) / n:>5.1f}%"
            for k in ("reste", "autre_zone", "hors_zone")
        )
        print(f"{bot_name:<14} {t.get('depuis_zone', 0):>6} | {cells}")

    print("\nDéparts HORS ZONE retenus par la neutralisation d'un terme :")
    entetes = " | ".join(f"{lib:>22}" for lib in COUNTERFACTUALS)
    print(f"{'bot':<14} | {entetes}")
    print("-" * (16 + 25 * len(COUNTERFACTUALS)))
    for bot_name, t in tallies.items():
        hz = t.get("hors_zone", 0) or 1
        cells = " | ".join(
            f"{t.get(f'hors_zone|retenu_par_{lib}', 0):>6} "
            f"{100 * t.get(f'hors_zone|retenu_par_{lib}', 0) / hz:>6.1f}%{'':>7}"
            for lib in COUNTERFACTUALS
        )
        print(f"{bot_name:<14} | {cells}")
    print(
        "\n⚠️ CONTRÔLE DE VALIDITÉ : `scorer` a w_enemy = 0.0, donc sa case « w_enemy=0 » DOIT\n"
        "   valoir 0.0 %. Toute autre valeur dénonce l'instrument — ne pas lire le reste."
    )


if __name__ == "__main__":
    main()
