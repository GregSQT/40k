#!/usr/bin/env python3
"""Banc de MÊLÉE bot contre bot — mesure de référence rejouable du lot `melee-100`.

POURQUOI CET OUTIL EXISTE
    Le lot melee-100 (D+ toutes les figurines engagées frappent, A1 pile-in « engagée si
    possible », A2 charge « contact si possible », A3/A4 consolidation, B2/B3 décisions de
    l'agent, A5 passe de l'étape Fight) change le jeu joué. Sans une mesure prise sur le moteur
    d'AVANT, rejouée à l'identique sur le moteur d'APRÈS, l'effet du lot ne se mesure pas — et
    un `--new` de la lignée serait lancé sur une foi.

CE QUI EST MESURÉ (par joueur 1 / 2, et par siège agent / adversaire)
    - figurines tuées et VALUE tuée, au tir et en mêlée (`action_logs` type `shoot` / `combat`) ;
    - charges déclarées / réussies, distance médiane à la cible déclarée (11.04) ;
    - activations de mêlée, figurines ENGAGÉES (04.02, `get_fighting_models` sans cible) contre
      figurines qui FRAPPENT (porteuses d'un intent à l'appel de
      `build_manual_fight_allocation`), attaques déclarées contre attaques possibles (une arme
      ordinaire + toutes les [EXTRA ATTACKS] par figurine engagée, 04.01 / 24.11) ;
    - géométrie de fin de charge et de fin de pile-in, par figurine : contact
      (`model_in_base_contact`), engagée (≤ zone d'engagement, hors contact), hors engagement ;
    - consolidations par mode 12.08 (`ongoing` / `engaging` / `objective`), plan vide compris ;
    - New Foes to Face déclenchés (12.08 AFTER, `fight_v11_consolidation_freeze_new_foes`) ;
    - victoires.

COMMENT C'EST MESURÉ — au moment de l'ÉVÉNEMENT, jamais après le step
    `BotControlledEnv.step` joue TOUT le tour de l'adversaire d'un seul appel (et `reset()` le
    premier tour entier de P1 quand l'agent siège en P2) : relire les positions après le step
    mesurerait une charge de P2 avec des figurines déjà pilées, ou une cible déjà morte. Les
    sondes sont donc posées SUR le moteur : l'écriture d'`action_logs`
    (`action_log_utils._append_entry`, corps unique des deux chemins d'émission) notifie chaque
    ligne à son émission (positions vivantes, avant tout mouvement suivant), et trois fonctions
    du chemin gym sont enveloppées
    (`build_manual_fight_allocation`, `squad_consolidate_plan`,
    `fight_v11_consolidation_freeze_new_foes`). Aucune sonde n'altère le jeu : chaque enveloppe
    rend exactement ce que la fonction d'origine rend.

    Le chemin de décision des deux bots est celui de la PRODUCTION
    (`BotControlledEnv._get_bot_action`, siège agent via `scripted_action_for_agent_side`),
    comme `scripts/bot_ranking.py`.

⚠️ FIXER LA RÉSOLUTION — `W40K_BOARD_PATH=board/44x60x1`, comme les évaluations de référence.
    Le script LÈVE si la variable est absente : deux résolutions sont deux géométries de mêlée
    (contact = case adjacente à x1, écart bord à bord à x5), et un JSON sans résolution écrite
    ne se compare à rien.

USAGE
    W40K_BOARD_PATH=board/44x60x1 python3 scripts/melee_bench.py --episodes 40 \
        --out logs/melee_bench_avant_2026-09-18.json
    Les épisodes sont partagés à parts égales entre `agent_seat_mode` p1 et p2.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from shared.data_validation import require_key  # noqa: E402

DEFAULT_SCENARIO = (
    "config/agents/ArmageddonAgent_x1/scenarios/training/scenario_training_armageddon1.json"
)
#: Randomness du TacticalBot. `tactical` est le holdout SCELLÉ (`ai/bot_registry.py`) et n'a pas
#: d'entrée dans `callback_params.bot_eval_randomness` ; la valeur est celle des six bots du panel
#: (0.05, `ArmageddonAgent_x1_training_config.json`), écrite dans le JSON produit.
DEFAULT_RANDOMNESS = 0.05
SEAT_MODES = ("p1", "p2")

#: Compteurs entiers tenus PAR JOUEUR (1 / 2). Les listes (distances) sont à part.
_PLAYER_COUNTERS = (
    "shoot_kills", "shoot_value_killed", "melee_kills", "melee_value_killed",
    "charges_declared", "charges_succeeded",
    "fight_activations", "fight_activations_with_target",
    "models_engaged", "models_striking", "attacks_declared", "attacks_possible",
    "after_charge_contact", "after_charge_engaged", "after_charge_out",
    "after_pile_in_contact", "after_pile_in_engaged", "after_pile_in_out",
    "consolidation_ongoing", "consolidation_engaging", "consolidation_objective",
    "consolidation_none",
    "new_foes_triggered", "new_foes_units",
    "wins",
)


class MeleeProbe:
    """Accumulateurs d'une tranche d'épisodes + sondes posées sur le moteur."""

    def __init__(self) -> None:
        self.by_player: Dict[str, "Counter[str]"] = {"1": Counter(), "2": Counter()}
        self.charge_target_distances: Dict[str, List[float]] = {"1": [], "2": []}
        self.episodes: List[Dict[str, Any]] = []

    # ── sondes ────────────────────────────────────────────────────────────────
    def install(self) -> None:
        import engine.action_log_utils as alu
        import engine.phase_handlers.fight_handlers as fh
        import engine.phase_handlers.shared_utils as su

        self._orig_append = alu._append_entry
        self._orig_alloc = fh.build_manual_fight_allocation
        self._orig_consolidate = su.squad_consolidate_plan
        self._orig_freeze = fh.fight_v11_consolidation_freeze_new_foes

        def _alloc(game_state: Dict[str, Any], attacker_squad_id: str) -> Dict[str, Any]:
            self._record_fight_activation(game_state, str(attacker_squad_id))
            return self._orig_alloc(game_state, attacker_squad_id)

        def _consolidate(game_state: Dict[str, Any], squad_id: str, *, mode: Optional[str] = None):
            plan = self._orig_consolidate(game_state, squad_id, mode=mode)
            if plan is None:
                player = self._player_of(game_state, str(squad_id))
                self.by_player[player]["consolidation_none"] += 1
            return plan

        def _freeze(game_state: Dict[str, Any], unit: Dict[str, Any]) -> List[str]:
            new_foes = self._orig_freeze(game_state, unit)
            if new_foes:
                player = str(int(require_key(unit, "player")))
                self.by_player[player]["new_foes_triggered"] += 1
                self.by_player[player]["new_foes_units"] += len(new_foes)
            return new_foes

        def _append(game_state: Dict[str, Any], entry: Dict[str, Any]) -> None:
            self._orig_append(game_state, entry)
            self._on_log(game_state, entry)

        alu._append_entry = _append
        fh.build_manual_fight_allocation = _alloc
        su.squad_consolidate_plan = _consolidate
        fh.fight_v11_consolidation_freeze_new_foes = _freeze

    def uninstall(self) -> None:
        import engine.action_log_utils as alu
        import engine.phase_handlers.fight_handlers as fh
        import engine.phase_handlers.shared_utils as su

        alu._append_entry = self._orig_append
        fh.build_manual_fight_allocation = self._orig_alloc
        su.squad_consolidate_plan = self._orig_consolidate
        fh.fight_v11_consolidation_freeze_new_foes = self._orig_freeze

    # ── lecture des lignes ────────────────────────────────────────────────────
    @staticmethod
    def _player_of(game_state: Dict[str, Any], squad_id: str) -> str:
        return str(int(require_key(require_key(game_state, "units_cache")[squad_id], "player")))

    def _on_log(self, gs: Dict[str, Any], log: Dict[str, Any]) -> None:
        """Une ligne d'`action_logs` vient d'être émise : les positions de `gs` sont celles de
        l'instant (cf. docstring de module)."""
        log_type = log.get("type")  # get allowed : la plupart des lignes n'en portent pas
        if log_type in ("shoot", "combat"):
            player = str(int(require_key(log, "player")))
            prefix = "melee" if log_type == "combat" else "shoot"
            for shot in require_key(log, "shootDetails"):
                if not shot.get("targetDied", False):  # get allowed : absent = pas de mort
                    continue
                self.by_player[player][f"{prefix}_kills"] += 1
                # VALUE entière dans tous les rosters ; `int` garde le compteur entier.
                self.by_player[player][f"{prefix}_value_killed"] += int(
                    require_key(shot, "targetValue")
                )
        elif log_type in ("charge", "charge_fail"):
            player = str(int(require_key(log, "player")))
            self.by_player[player]["charges_declared"] += 1
            target_distance = require_key(log, "charge_target_distance_inches")
            if target_distance is not None:
                self.charge_target_distances[player].append(float(target_distance))
            if log_type == "charge":
                self.by_player[player]["charges_succeeded"] += 1
                self._record_geometry(gs, str(require_key(log, "unitId")), player, "after_charge")
        elif log_type in ("pile_in", "overrun_pile_in"):
            player = str(int(require_key(log, "player")))
            self._record_geometry(gs, str(require_key(log, "unitId")), player, "after_pile_in")
        elif log_type == "consolidation":
            player = str(int(require_key(log, "player")))
            mode = require_key(log, "consolidationMode")
            if mode not in ("ongoing", "engaging", "objective"):
                raise ValueError(f"consolidationMode inattendu {mode!r}")
            self.by_player[player][f"consolidation_{mode}"] += 1

    def _record_geometry(
        self, game_state: Dict[str, Any], squad_id: str, player: str, prefix: str
    ) -> None:
        """Classe chaque figurine vivante de l'escouade : contact / engagée / hors engagement,
        contre n'importe quelle figurine ennemie (une unité qui vient de charger ne peut être
        engagée qu'avec ses cibles, 11.04 AFTER MOVING)."""
        from engine.phase_handlers.shared_utils import get_fighting_models, model_in_base_contact

        models_cache = require_key(game_state, "models_cache")
        squad_models = require_key(game_state, "squad_models")
        alive = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
        engaged = set(get_fighting_models(game_state, squad_id, None))
        counters = self.by_player[player]
        for mid in alive:
            if model_in_base_contact(game_state, mid, models_cache[mid]):
                counters[f"{prefix}_contact"] += 1
            elif mid in engaged:
                counters[f"{prefix}_engaged"] += 1
            else:
                counters[f"{prefix}_out"] += 1

    def _record_fight_activation(self, game_state: Dict[str, Any], squad_id: str) -> None:
        from engine.combat_utils import expected_dice_value
        from engine.phase_handlers.shared_utils import get_fighting_models
        from engine.utils.weapon_helpers import melee_weapons, weapon_has_rule

        models_cache = require_key(game_state, "models_cache")
        intents = require_key(game_state, "pending_squad_fight_intents").get(squad_id, [])  # get allowed
        player = self._player_of(game_state, squad_id)
        counters = self.by_player[player]
        counters["fight_activations"] += 1
        if intents:
            counters["fight_activations_with_target"] += 1
        engaged = get_fighting_models(game_state, squad_id, None)
        strikers = {str(i["model_id"]) for i in intents}
        counters["models_engaged"] += len(engaged)
        counters["models_striking"] += len(strikers)
        counters["attacks_declared"] += sum(int(i["n_attacks_resolved"]) for i in intents)
        for mid in engaged:
            ordinary: List[float] = []
            extra = 0.0
            for idx, weapon in enumerate(melee_weapons(models_cache[mid])):
                nb = expected_dice_value(require_key(weapon, "NB"), f"melee_bench_{mid}_{idx}")
                if weapon_has_rule(weapon, "EXTRA_ATTACKS"):
                    extra += nb
                else:
                    ordinary.append(nb)
            counters["attacks_possible"] += int(round((max(ordinary) if ordinary else 0.0) + extra))

    # ── fusion ────────────────────────────────────────────────────────────────
    def export(self) -> Dict[str, Any]:
        return {
            "by_player": {p: dict(c) for p, c in self.by_player.items()},
            "charge_target_distances": self.charge_target_distances,
            "episodes": self.episodes,
        }


def _make_env(scenario_file: str, seat_mode: str, bot_type: str, randomness: float):
    from sb3_contrib.common.wrappers import ActionMasker

    from ai.bot_registry import build_bot
    from ai.env_wrappers import BotControlledEnv
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    engine = W40KEngine(
        rewards_config="ArmageddonAgent_x1",
        training_config_name="x1",
        controlled_agent="ArmageddonAgent_x1",
        scenario_file=scenario_file,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    masked = ActionMasker(engine, lambda _env: engine.get_action_mask())
    opponent = build_bot(bot_type, {bot_type: randomness})
    return BotControlledEnv(masked, opponent, UnitRegistry(), agent_seat_mode=seat_mode, env_rank=0)


def play_slice(
    *,
    scenario_file: str,
    seat_mode: str,
    seeds: List[int],
    bot_type: str,
    randomness: float,
    max_steps_per_episode: int,
) -> Dict[str, Any]:
    """Joue `seeds` en `seat_mode` (les deux sièges tenus par `bot_type`) et rend les
    accumulateurs. Exécutable dans un worker."""
    import random

    import numpy as np

    from ai.bot_registry import build_bot
    from engine.constants import DRAW_WINNER

    probe = MeleeProbe()
    probe.install()
    env = _make_env(scenario_file, seat_mode, bot_type, randomness)
    agent_seat_bot = build_bot(bot_type, {bot_type: randomness})
    try:
        for seed in seeds:
            random.seed(seed)
            np.random.seed(seed)
            _obs, _info = env.reset(seed=seed)
            gs = env.engine.game_state
            done = False
            steps = 0
            info: Dict[str, Any] = {}
            while not done and steps < max_steps_per_episode:
                action = env.scripted_action_for_agent_side(agent_seat_bot)
                _obs, _reward, terminated, truncated, info = env.step(int(action))
                done = bool(terminated) or bool(truncated)
                steps += 1
            if not done:
                raise RuntimeError(
                    f"Épisode non terminé en {max_steps_per_episode} pas (seed {seed}, "
                    f"{seat_mode}) — le compter fausserait la mesure."
                )
            winner = require_key(info, "winner")
            if winner != DRAW_WINNER:
                probe.by_player[str(int(winner))]["wins"] += 1
            probe.episodes.append({
                "seed": int(seed),
                "seat_mode": seat_mode,
                "controlled_player": int(require_key(info, "controlled_player")),
                "winner": winner,
                "turns": int(require_key(gs, "turn")),
                "steps": steps,
            })
    finally:
        env.close()
        probe.uninstall()
    return probe.export()


def _merge(parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_player: Dict[str, "Counter[str]"] = {"1": Counter(), "2": Counter()}
    distances: Dict[str, List[float]] = {"1": [], "2": []}
    episodes: List[Dict[str, Any]] = []
    for part in parts:
        for p in ("1", "2"):
            by_player[p].update(part["by_player"][p])
            distances[p].extend(part["charge_target_distances"][p])
        episodes.extend(part["episodes"])
    return {"by_player": by_player, "charge_target_distances": distances, "episodes": episodes}


def _by_seat(episodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:  # noqa: D401
    """Victoires par SIÈGE (agent = `scripted_action_for_agent_side`, adversaire = bot du
    wrapper) : les deux chemins de décision sont distincts, la parité se lit ici."""
    seat = {
        "agent_seat": Counter(episodes=0, wins=0),
        "opponent_seat": Counter(episodes=0, wins=0),
    }
    for ep in episodes:
        seat["agent_seat"]["episodes"] += 1
        seat["opponent_seat"]["episodes"] += 1
        winner = ep["winner"]
        if winner == ep["controlled_player"]:
            seat["agent_seat"]["wins"] += 1
        elif winner in (1, 2):
            seat["opponent_seat"]["wins"] += 1
    return {k: dict(v) for k, v in seat.items()}


def _ratio(num: float, den: float) -> Optional[float]:
    return (num / den) if den else None


def _derived(counters: "Counter[str]") -> Dict[str, Optional[float]]:
    return {
        "striking_over_engaged": _ratio(counters["models_striking"], counters["models_engaged"]),
        "attacks_declared_over_possible": _ratio(
            counters["attacks_declared"], counters["attacks_possible"]
        ),
        "charge_success_rate": _ratio(counters["charges_succeeded"], counters["charges_declared"]),
        "after_charge_contact_rate": _ratio(
            counters["after_charge_contact"],
            counters["after_charge_contact"] + counters["after_charge_engaged"]
            + counters["after_charge_out"],
        ),
        "after_pile_in_out_rate": _ratio(
            counters["after_pile_in_out"],
            counters["after_pile_in_contact"] + counters["after_pile_in_engaged"]
            + counters["after_pile_in_out"],
        ),
    }


def build_report(merged: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    by_player: Dict[str, Any] = {}
    for p in ("1", "2"):
        counters: "Counter[str]" = merged["by_player"][p]
        row: Dict[str, Any] = {name: counters[name] for name in _PLAYER_COUNTERS}
        dists = merged["charge_target_distances"][p]
        row["charge_target_distance_inches_median"] = (
            statistics.median(dists) if dists else None
        )
        row["derived"] = _derived(counters)
        by_player[p] = row
    total: "Counter[str]" = Counter()
    for p in ("1", "2"):
        total.update(merged["by_player"][p])
    return {
        "meta": meta,
        "by_player": by_player,
        "totals": {**{name: total[name] for name in _PLAYER_COUNTERS}, "derived": _derived(total)},
        "by_seat": _by_seat(merged["episodes"]),
        "episodes": merged["episodes"],
    }


def _engine_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT, capture_output=True,
        text=True, check=True,
    ).stdout.strip()


def run_bench(
    *,
    n_episodes: int,
    scenario_file: str,
    out_path: Optional[str],
    seed: int = 4242,
    bot_type: str = "tactical",
    randomness: float = DEFAULT_RANDOMNESS,
    workers: int = 1,
    seat_modes: tuple = SEAT_MODES,
) -> Dict[str, Any]:
    """Joue `n_episodes` répartis sur `seat_modes` et rend (et écrit) le rapport."""
    board_path = os.environ.get("W40K_BOARD_PATH")  # get allowed : contrôlé juste après
    if not board_path:
        raise RuntimeError(
            "W40K_BOARD_PATH absent — fixer la résolution (board/44x60x1 pour la référence) : "
            "deux résolutions sont deux géométries de mêlée, un JSON sans résolution ne se "
            "compare à rien."
        )
    if n_episodes <= 0:
        raise ValueError("n_episodes doit être > 0")
    from config_loader import get_config_loader

    game_rules = require_key(get_config_loader().get_game_config(), "game_rules")
    max_steps_per_episode = int(require_key(game_rules, "max_turns")) * 400

    seeds = [seed + i for i in range(n_episodes)]
    tasks: List[Dict[str, Any]] = []
    for i, ep_seed in enumerate(seeds):
        tasks.append({"seat_mode": seat_modes[i % len(seat_modes)], "seed": ep_seed})
    workers = max(1, min(int(workers), len(tasks)))
    # Tranches par (worker, siège) : un env par tranche, les graines distribuées en tourniquet.
    slices: Dict[tuple, List[int]] = {}
    for i, task in enumerate(tasks):
        slices.setdefault((i % workers, task["seat_mode"]), []).append(task["seed"])
    parts: List[Dict[str, Any]] = []
    if workers == 1:
        for (_w, seat_mode), slice_seeds in sorted(slices.items()):
            parts.append(play_slice(
                scenario_file=scenario_file, seat_mode=seat_mode, seeds=slice_seeds,
                bot_type=bot_type, randomness=randomness,
                max_steps_per_episode=max_steps_per_episode,
            ))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(
                    play_slice, scenario_file=scenario_file, seat_mode=seat_mode,
                    seeds=slice_seeds, bot_type=bot_type, randomness=randomness,
                    max_steps_per_episode=max_steps_per_episode,
                )
                for (_w, seat_mode), slice_seeds in sorted(slices.items())
            ]
            for future in as_completed(futures):
                parts.append(future.result())  # propage les exceptions sans les avaler
    merged = _merge(parts)
    meta = {
        "date": date.today().isoformat(),
        "engine_commit": _engine_commit(),
        "scenario": scenario_file,
        "board_path": board_path,
        "n_episodes": n_episodes,
        "seat_modes": list(seat_modes),
        "bot": bot_type,
        "randomness": randomness,
        "seed": seed,
    }
    report = build_report(merged, meta)
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
    return report


def _print_summary(report: Dict[str, Any]) -> None:
    print(f"🥊 melee_bench — {report['meta']['n_episodes']} parties, moteur "
          f"{report['meta']['engine_commit']}, {report['meta']['board_path']}")
    for p in ("1", "2"):
        row = report["by_player"][p]
        d = row["derived"]
        print(f"  joueur {p}: victoires={row['wins']} · tir kills/VALUE={row['shoot_kills']}/"
              f"{row['shoot_value_killed']:.0f} · mêlée kills/VALUE={row['melee_kills']}/"
              f"{row['melee_value_killed']:.0f}")
        print(f"     charges {row['charges_succeeded']}/{row['charges_declared']} "
              f"(médiane cible {row['charge_target_distance_inches_median']}) · "
              f"contact après charge {row['after_charge_contact']}/"
              f"{row['after_charge_contact'] + row['after_charge_engaged'] + row['after_charge_out']}")
        print(f"     mêlée : activations={row['fight_activations']} · frappent/engagées="
              f"{row['models_striking']}/{row['models_engaged']} ({d['striking_over_engaged']}) · "
              f"attaques {row['attacks_declared']}/{row['attacks_possible']} "
              f"({d['attacks_declared_over_possible']})")
        print(f"     pile-in contact/engagée/hors={row['after_pile_in_contact']}/"
              f"{row['after_pile_in_engaged']}/{row['after_pile_in_out']} · conso "
              f"ongoing/engaging/objective/none={row['consolidation_ongoing']}/"
              f"{row['consolidation_engaging']}/{row['consolidation_objective']}/"
              f"{row['consolidation_none']} · New Foes={row['new_foes_triggered']}")
    print(f"  sièges : {report['by_seat']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Banc de mêlée bot contre bot.")
    parser.add_argument("--episodes", type=int, default=40)
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--out", required=True, help="JSON de sortie (ex. logs/melee_bench_avant_<date>.json)")
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--bot", default="tactical")
    parser.add_argument("--randomness", type=float, default=DEFAULT_RANDOMNESS)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()
    report = run_bench(
        n_episodes=args.episodes, scenario_file=args.scenario, out_path=args.out,
        seed=args.seed, bot_type=args.bot, randomness=args.randomness, workers=args.workers,
    )
    _print_summary(report)
    print(f"💾 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
