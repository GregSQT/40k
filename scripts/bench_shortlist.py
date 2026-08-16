#!/usr/bin/env python3
"""Taux de divergence de _DoctrineBot.select_movement_destination
à DESTINATION_SHORTLIST ∈ {shortlist} vs référence=24.

OBJECTIF
--------
Mesure directe : pour N décisions synthétiques, quelle fraction choisit une
destination DIFFERENTE selon la shortlist testée vs la référence ?
On ne mesure PAS le win-rate — juste l'accord de décision.

SCENARIONS
----------
asymmetric  my_range >> enemy_range → "zone de tir sûre" hors shortlist réduite
balanced    my_range == enemy_range → pas de zone sûre, divergence ≈ 0
exposed     my_range << enemy_range → risque fort, destination optimale hors shortlist

CONSTRUCTION DES ÉTATS
-----------------------
États synthétiques sans objectifs (w_obj = 0, pas besoin de cartes de distance).
_damage_on est patché : valeur fixe (10.0 ou 8.0) selon qui attaque qui.
Les bots lisent leurs poids depuis la config réelle (load_doctrine_weights).

Usage :
    python3 scripts/bench_shortlist.py
    python3 scripts/bench_shortlist.py --shortlist 8 12 --episodes 500
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import ai.bot_doctrines as doc
from ai.bot_doctrines import (
    AlphaStrikeBot,
    AttritionBot,
    DecapitationBot,
    EndgameBot,
    RacerBot,
    ScorerBot,
)

# ── Paramètres de plateau ──────────────────────────────────────────────────────────────────────

BOARD_SIZE = 44          # colonnes et lignes (carré)
CANDIDATE_RADIUS = 7     # ½-côté de la grille de candidats → jusqu'à (2r+1)²-1 = 224 candidats
REFERENCE_SHORTLIST = 24

# ── Patch moteur de dégâts ─────────────────────────────────────────────────────────────────────

_MY_DAMAGE = 10.0
_THEIR_DAMAGE = 8.0


def _install_damage_patch() -> None:
    """Valeur fixe indépendante de la distance réelle.

    _firepower_from fait le test de portée (distance vs RNG) ; _damage_on ne fournit
    que la valeur. Renvoyé une constante ici isole le comportement du shortlist pur.
    """
    def _dmg(game_state: Any, attacker_id: Any, target_id: Any, is_ranged: bool) -> float:
        cache = game_state.get("units_cache", {})
        att = cache.get(str(attacker_id), {})
        return _MY_DAMAGE if int(att.get("player", 2)) == 1 else _THEIR_DAMAGE

    doc._damage_on = _dmg


# ── Fabrication d'état ─────────────────────────────────────────────────────────────────────────

def _make_unit(uid: str, player: int, rng: int) -> Dict[str, Any]:
    weapons = [{"RNG": rng}] if rng > 0 else []
    return {
        "id": uid,
        "player": player,
        "OC": 2,
        "battle_shocked": False,
        "VALUE": 100.0,
        "RNG_WEAPONS": weapons,
        "HP_MAX": 2,
    }


def _make_state(
    unit_col: int,
    unit_row: int,
    enemy_positions: List[Tuple[int, int]],
    my_rng: int,
    enemy_rng: int,
    turn: int = 3,
) -> Dict[str, Any]:
    """État moteur minimal : 1 escouade alliée + liste d'ennemis, pas d'objectifs.

    squad_cache requis par AttritionBot._withdrawing (_strength_measure).
    HP_CUR requis en units_cache par get_hp_from_cache (DecapitationBot._hp_left).
    """
    ally_id = "A"
    units: List[Dict[str, Any]] = [_make_unit(ally_id, 1, my_rng)]
    cache: Dict[str, Any] = {
        ally_id: {"player": 1, "col": unit_col, "row": unit_row, "orientation": 0, "HP_CUR": 2}
    }
    squad_models: Dict[str, Any] = {ally_id: [f"{ally_id}#0"]}
    models_cache: Dict[str, Any] = {
        f"{ally_id}#0": {
            "col": unit_col, "row": unit_row,
            "HP_CUR": 2, "BASE_SHAPE": "round", "BASE_SIZE": 1,
        }
    }
    # model_count_at_start=1 → _strength_measure lit HP_CUR/HP_MAX (unité mono-figurine)
    squad_cache: Dict[str, Any] = {
        ally_id: {"model_count_at_start": 1, "model_count": 1}
    }

    for i, (ec, er) in enumerate(enemy_positions):
        eid = f"E{i}"
        units.append(_make_unit(eid, 2, enemy_rng))
        cache[eid] = {"player": 2, "col": ec, "row": er, "orientation": 0, "HP_CUR": 2}
        squad_models[eid] = [f"{eid}#0"]
        models_cache[f"{eid}#0"] = {
            "col": ec, "row": er,
            "HP_CUR": 2, "BASE_SHAPE": "round", "BASE_SIZE": 1,
        }
        squad_cache[eid] = {"model_count_at_start": 1, "model_count": 1}

    return {
        "turn": turn,
        "episode_number": 1,
        "phase": "move",
        "config": {"game_rules": {"max_turns": 5}},
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_cache": cache,
        "models_cache": models_cache,
        "squad_models": squad_models,
        "squad_cache": squad_cache,
        # Pas d'objectifs : _objective_terms renvoie (None, []), w_obj = 0.
        # Le bench mesure le terme de tir pur.
    }


def _candidate_grid(
    unit_col: int,
    unit_row: int,
    radius: int = CANDIDATE_RADIUS,
) -> List[Tuple[int, int]]:
    """Grille de destinations candidates autour de l'unité, bornée au plateau."""
    cands = []
    for dc in range(-radius, radius + 1):
        for dr in range(-radius, radius + 1):
            col = unit_col + dc
            row = unit_row + dr
            if col < 0 or row < 0 or col >= BOARD_SIZE or row >= BOARD_SIZE:
                continue
            if col == unit_col and row == unit_row:
                continue
            cands.append((col, row))
    return cands


# ── Définition des scénarios ───────────────────────────────────────────────────────────────────

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "asymmetric": {
        "my_rng": 24, "enemy_rng": 8,
        "desc": "my_range >> enemy_range : zone de tir sûre accessible",
    },
    "balanced": {
        "my_rng": 16, "enemy_rng": 16,
        "desc": "my_range == enemy_range : pas de zone à risque asymétrique",
    },
    "exposed": {
        "my_rng": 10, "enemy_rng": 20,
        "desc": "my_range << enemy_range : risque fort, fuite hors shortlist",
    },
}

# ── Bots testés ────────────────────────────────────────────────────────────────────────────────

def _make_bots() -> Dict[str, doc._DoctrineBot]:
    return {
        "RacerBot":       RacerBot(),
        "EndgameBot":     EndgameBot(),
        "AlphaStrikeBot": AlphaStrikeBot(),
        "AttritionBot":   AttritionBot(),
        "DecapitationBot": DecapitationBot(),
        "ScorerBot":      ScorerBot(),
    }


# ── Cœur de la mesure ─────────────────────────────────────────────────────────────────────────

def _decision(
    bot: doc._DoctrineBot,
    state: Dict[str, Any],
    unit: Dict[str, Any],
    candidates: List[Tuple[int, int]],
    shortlist: int,
) -> Tuple[int, int]:
    """Décision du bot avec DESTINATION_SHORTLIST = shortlist."""
    prev = doc.DESTINATION_SHORTLIST
    doc.DESTINATION_SHORTLIST = shortlist
    try:
        return bot.select_movement_destination(unit, candidates, state)
    finally:
        doc.DESTINATION_SHORTLIST = prev


def _w_fire_nonzero(bot: doc._DoctrineBot, state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Vrai si le bot a w_fire > 0 ou w_risk > 0 pour cet état (shortlist active)."""
    try:
        weights = bot.movement_weights(unit, state)
    except Exception:
        return False
    _, _, w_fire, w_risk, *_ = weights
    return w_fire != 0.0 or w_risk != 0.0


def run_bench(
    shortlists: List[int],
    n_episodes: int,
    rng_seed: int = 42,
) -> Dict[str, Any]:
    """
    Renvoie un dict {scenario → {bot → {shortlist → divergence_rate}}}.

    divergence_rate = fraction de décisions différentes de la référence (shortlist=24).
    """
    rng = random.Random(rng_seed)
    results: Dict[str, Dict[str, Dict[int, float]]] = {}

    _install_damage_patch()

    for scen_name, scen in SCENARIOS.items():
        my_rng: int = scen["my_rng"]
        enemy_rng: int = scen["enemy_rng"]

        # Compteurs : {bot_name: {shortlist: [n_diverge, n_total]}}
        counters: Dict[str, Dict[int, List[int]]] = defaultdict(
            lambda: {k: [0, 0] for k in shortlists}
        )

        bots = _make_bots()

        for _ in range(n_episodes):
            # Position de l'unité alliée (intérieur du plateau, marge = radius)
            margin = CANDIDATE_RADIUS + 1
            uc = rng.randint(margin, BOARD_SIZE - margin - 1)
            ur = rng.randint(margin, BOARD_SIZE - margin - 1)

            # 1 à 3 ennemis placés aléatoirement
            n_enemies = rng.randint(1, 3)
            enemies = [
                (rng.randint(0, BOARD_SIZE - 1), rng.randint(0, BOARD_SIZE - 1))
                for _ in range(n_enemies)
            ]

            state = _make_state(uc, ur, enemies, my_rng, enemy_rng)
            unit = state["unit_by_id"]["A"]
            candidates = _candidate_grid(uc, ur)

            if not candidates:
                continue

            # Référence à shortlist=24
            ref_decisions: Dict[str, Tuple[int, int]] = {}
            for bot_name, bot in bots.items():
                if not _w_fire_nonzero(bot, state, unit):
                    # Shortlist inactive pour ce bot/état : pas de divergence possible
                    continue
                try:
                    ref_decisions[bot_name] = _decision(
                        bot, state, unit, candidates, REFERENCE_SHORTLIST
                    )
                except Exception:
                    pass

            # Décisions aux shortlists testées
            for k in shortlists:
                if k == REFERENCE_SHORTLIST:
                    # divergence = 0 par définition
                    for bot_name in ref_decisions:
                        counters[bot_name][k][1] += 1
                    continue

                for bot_name, bot in bots.items():
                    if bot_name not in ref_decisions:
                        continue
                    try:
                        decision = _decision(bot, state, unit, candidates, k)
                    except Exception:
                        continue
                    counters[bot_name][k][0] += int(decision != ref_decisions[bot_name])
                    counters[bot_name][k][1] += 1

        # Taux de divergence
        scen_result: Dict[str, Dict[int, float]] = {}
        for bot_name, kd in counters.items():
            scen_result[bot_name] = {}
            for k, (n_div, n_tot) in kd.items():
                scen_result[bot_name][k] = n_div / n_tot if n_tot > 0 else float("nan")
        results[scen_name] = scen_result

    return results


# ── Affichage ──────────────────────────────────────────────────────────────────────────────────

def _print_table(results: Dict[str, Any], shortlists: List[int]) -> None:
    tested = [k for k in shortlists if k != REFERENCE_SHORTLIST]
    header_ks = [f"K={k}" for k in tested] + [f"K={REFERENCE_SHORTLIST}(ref)"]

    for scen_name, scen in SCENARIOS.items():
        print(f"\n{'═' * 70}")
        print(f"SCÉNARIO : {scen_name} — {scen['desc']}")
        print(f"{'─' * 70}")
        col_w = 18
        header = f"{'Bot':<20}" + "".join(f"{h:>{col_w}}" for h in header_ks)
        print(header)
        print("─" * len(header))

        bot_data = results.get(scen_name, {})
        for bot_name in sorted(bot_data):
            row = f"{bot_name:<20}"
            for k in tested:
                rate = bot_data[bot_name].get(k, float("nan"))
                val = f"{rate:.1%}" if not (rate != rate) else "n/a"
                row += f"{val:>{col_w}}"
            row += f"{'0.0%':>{col_w}}"
            print(row)


def _print_summary(results: Dict[str, Any], shortlists: List[int]) -> None:
    tested = [k for k in shortlists if k != REFERENCE_SHORTLIST]
    if not tested:
        return
    print(f"\n{'═' * 70}")
    print("RÉSUMÉ — divergence moyenne par shortlist (toutes scènes, tous bots)")
    print(f"{'─' * 70}")
    totals: Dict[int, List[float]] = defaultdict(list)
    for scen_data in results.values():
        for bot_data in scen_data.values():
            for k in tested:
                rate = bot_data.get(k, float("nan"))
                if rate == rate:  # not nan
                    totals[k].append(rate)
    for k in tested:
        vals = totals[k]
        mean = sum(vals) / len(vals) if vals else float("nan")
        print(f"  K={k:<4}  moyenne={mean:.1%}  min={min(vals):.1%}  max={max(vals):.1%}")


# ── Point d'entrée ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shortlist", type=int, nargs="+", default=[8, 12, REFERENCE_SHORTLIST],
        metavar="K",
        help=f"Valeurs de DESTINATION_SHORTLIST à tester (défaut : 8 12 {REFERENCE_SHORTLIST})",
    )
    parser.add_argument(
        "--episodes", type=int, default=200,
        help="Nombre d'états synthétiques par scénario (défaut : 200)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Graine aléatoire (défaut : 42)",
    )
    args = parser.parse_args()

    shortlists = sorted(set(args.shortlist))
    if REFERENCE_SHORTLIST not in shortlists:
        shortlists.append(REFERENCE_SHORTLIST)

    print(f"bench_shortlist.py — {args.episodes} épisodes/scénario, "
          f"shortlists={shortlists}, ref={REFERENCE_SHORTLIST}")

    results = run_bench(shortlists, n_episodes=args.episodes, rng_seed=args.seed)
    _print_table(results, shortlists)
    _print_summary(results, shortlists)


if __name__ == "__main__":
    main()
