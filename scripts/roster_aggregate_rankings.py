#!/usr/bin/env python3
"""
Agrège les matrices holdout_hard_matchups_{greedy,defensive_smart,adaptive}.json
et produit des classements par roster (P1 agent ou P2 opponent).

Pour chaque roster :
  - roster_value : somme des VALUE (unit_sampling_matrix.unit_values) du roster courant.
  - mean_greedy / mean_defensive_smart / mean_adaptive : moyenne marginale du win_rate
    pour ce bot seul (P1 : sur tous les P2 ; P2 : sur tous les P1).
  - mean_agg : moyenne pondérée (0.33, 0.33, 0.34) de ces trois moyennes.
  - worst / best : min / max du win_rate sur toutes les paires × bots.
  - worst_vs_roster / best_vs_roster : id du roster adverse (P2 si ligne P1, P1 si ligne P2)
    à la cellule où ce min/max est atteint (égalités : départage lexicographique stable).
  - worst_vs_value / best_vs_value : VALUE totale du roster worst_vs / best_vs.

Usage:
  python scripts/roster_aggregate_rankings.py
  python scripts/roster_aggregate_rankings.py --role p2 --sort worst
  python scripts/roster_aggregate_rankings.py --csv /tmp/p1_agg.csv
  python scripts/roster_aggregate_rankings.py --role p1 --sort mean --p1subset
  python scripts/roster_aggregate_rankings.py --role p1 --p1subset --p1-rosters id1,id2
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_UNITS_MATRIX = PROJECT_ROOT / "reports" / "unit_sampling_matrix.json"

BOT_FILES: Tuple[str, ...] = (
    "holdout_hard_matchups_greedy.json",
    "holdout_hard_matchups_defensive_smart.json",
    "holdout_hard_matchups_adaptive.json",
)
BOT_FILES_P1SUBSET: Tuple[str, ...] = (
    "holdout_hard_matchups_greedy_p1subset.json",
    "holdout_hard_matchups_defensive_smart_p1subset.json",
    "holdout_hard_matchups_adaptive_p1subset.json",
)
BOT_FILES_P1EXCLUDE: Tuple[str, ...] = (
    "holdout_hard_matchups_adaptive_p1exclude.json",
    "holdout_hard_matchups_aggressive_smart_p1exclude.json",
    "holdout_hard_matchups_defensive_p1exclude.json",
)
BOT_LABELS: Tuple[str, ...] = (
    "mean_greedy",
    "mean_defensive_smart",
    "mean_adaptive",
)
BOT_LABELS_P1EXCLUDE: Tuple[str, ...] = (
    "mean_adaptive",
    "mean_aggressive_smart",
    "mean_defensive",
)
BOT_WEIGHTS: Tuple[float, ...] = (0.33, 0.33, 0.34)
BOT_WEIGHTS_P1EXCLUDE: Tuple[float, ...] = (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)


def _require_weights_sum(weights: Sequence[float]) -> None:
    s = sum(weights)
    if abs(s - 1.0) > 1e-6:
        raise ValueError(f"BOT_WEIGHTS must sum to 1.0, got {s}")


def load_matchup_matrix(path: Path) -> Dict[str, Dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if "matchups" not in data:
        raise KeyError(f"Missing 'matchups' in {path}")
    return data["matchups"]


def _require_key(mapping: Dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing required key '{key}'")
    return mapping[key]


def load_unit_type_values(matrix_path: Path) -> Dict[str, int]:
    """
    Charge unit_type -> VALUE depuis matrix.unit_values (clés 'faction::unit_type').
    Lève si deux clés partagent le même unit_type avec des VALUE différentes.
    """
    with matrix_path.open(encoding="utf-8") as f:
        matrix = json.load(f)
    unit_values = _require_key(matrix, "unit_values")
    if not isinstance(unit_values, dict):
        raise TypeError(f"{matrix_path}: unit_values must be a dict")
    by_type: Dict[str, int] = {}
    for unit_key, raw_value in unit_values.items():
        if not isinstance(unit_key, str) or "::" not in unit_key:
            raise ValueError(
                f"{matrix_path}: clé unit_values invalide {unit_key!r} (attendu 'faction::unit_type')"
            )
        _faction, unit_type = unit_key.split("::", 1)
        value = int(raw_value)
        if unit_type in by_type and by_type[unit_type] != value:
            raise ValueError(
                f"{matrix_path}: unit_type {unit_type!r} a deux VALUE différentes "
                f"({by_type[unit_type]} vs {value})"
            )
        by_type[unit_type] = value
    return by_type


def roster_total_from_json(roster_path: Path, unit_type_values: Dict[str, int]) -> int:
    """Somme des VALUE (unit_type × count) pour un fichier roster JSON."""
    payload = json.loads(roster_path.read_text(encoding="utf-8"))
    roster_id = _require_key(payload, "roster_id")
    composition = _require_key(payload, "composition")
    if not isinstance(composition, list):
        raise TypeError(f"Invalid composition in {roster_path}")
    total = 0
    for entry in composition:
        unit_type = _require_key(entry, "unit_type")
        count = int(_require_key(entry, "count"))
        if unit_type not in unit_type_values:
            raise KeyError(
                f"unit_type {unit_type!r} absent de la matrice unit_values (roster {roster_path}, {roster_id!r})"
            )
        total += unit_type_values[unit_type] * count
    return total


def _roster_split_from_bot_json_name(filename: str) -> str:
    stem = Path(filename).stem
    marker = "_matchups_"
    if marker not in stem:
        raise ValueError(
            f"Nom de fichier matrice inattendu (attendu *{marker}*): {filename!r}"
        )
    return stem.split(marker, 1)[0]


def agent_key_and_scale_from_matchup_dir(matchup_dir: Path) -> Tuple[str, str]:
    """.../config/agents/<agent>/rosters/<scale>/matchups -> (agent, scale)."""
    resolved = matchup_dir.resolve()
    agents_root = (PROJECT_ROOT / "config" / "agents").resolve()
    try:
        rel = resolved.relative_to(agents_root)
    except ValueError as e:
        raise ValueError(
            f"--matchup-dir doit être sous {agents_root}, obtenu: {resolved}"
        ) from e
    parts = rel.parts
    if len(parts) < 4 or parts[1] != "rosters":
        raise ValueError(
            f"--matchup-dir attendu .../<agent>/rosters/<scale>/matchups, obtenu: {rel}"
        )
    return parts[0], parts[2]


def enrich_rows_with_roster_values(
    rows: List[Dict[str, Any]],
    role: Literal["p1", "p2"],
    agent_key: str,
    scale: str,
    roster_split: str,
    unit_type_values: Dict[str, int],
) -> None:
    """Ajoute roster_value, worst_vs_value, best_vs_value (mut rows)."""
    cache: Dict[str, int] = {}

    def p1_path(rid: str) -> Path:
        return (
            PROJECT_ROOT
            / "config"
            / "agents"
            / agent_key
            / "rosters"
            / scale
            / roster_split
            / f"{rid}.json"
        )

    def p2_path(rid: str) -> Path:
        return (
            PROJECT_ROOT
            / "config"
            / "agents"
            / "_p2_rosters"
            / scale
            / roster_split
            / f"{rid}.json"
        )

    def value_for(rid: str, side: Literal["p1", "p2"]) -> int:
        key = f"{side}:{rid}"
        if key in cache:
            return cache[key]
        path = p1_path(rid) if side == "p1" else p2_path(rid)
        if not path.is_file():
            raise FileNotFoundError(f"Roster JSON introuvable pour VALUE: {path}")
        v = roster_total_from_json(path, unit_type_values)
        cache[key] = v
        return v

    for r in rows:
        rid = str(r["roster_id"])
        wcp = str(r["worst_vs_roster"])
        bcp = str(r["best_vs_roster"])
        if role == "p1":
            r["roster_value"] = value_for(rid, "p1")
            r["worst_vs_value"] = value_for(wcp, "p2")
            r["best_vs_value"] = value_for(bcp, "p2")
        else:
            r["roster_value"] = value_for(rid, "p2")
            r["worst_vs_value"] = value_for(wcp, "p1")
            r["best_vs_value"] = value_for(bcp, "p1")


def marginal_means_p1(
    matrices: List[Dict[str, Dict[str, Any]]],
) -> Dict[str, List[float]]:
    """Pour chaque P1, liste [mean_bot0, mean_bot1, mean_bot2] sur les P2."""
    if not matrices:
        return {}
    p1_ids = set()
    for m in matrices:
        p1_ids |= set(m.keys())
    out: Dict[str, List[float]] = {}
    for p1 in sorted(p1_ids):
        per_bot: List[float] = []
        for m in matrices:
            row = m.get(p1)
            if row is None:
                raise KeyError(f"P1 roster {p1!r} missing in one matrix")
            rates = []
            for _p2, cell in row.items():
                rates.append(float(cell["win_rate"]))
            per_bot.append(sum(rates) / len(rates))
        out[p1] = per_bot
    return out


def marginal_means_p2(
    matrices: List[Dict[str, Dict[str, Any]]],
) -> Dict[str, List[float]]:
    """Pour chaque P2, liste [mean_bot0, mean_bot1, mean_bot2] sur les P1."""
    if not matrices:
        return {}
    p2_ids: set[str] = set()
    for m in matrices:
        for _p1, row in m.items():
            p2_ids |= set(row.keys())
    out: Dict[str, List[float]] = {}
    for p2 in sorted(p2_ids):
        per_bot: List[float] = []
        for m in matrices:
            rates = []
            for _p1, row in m.items():
                cell = row.get(p2)
                if cell is None:
                    raise KeyError(f"P2 roster {p2!r} missing under a P1 row")
                rates.append(float(cell["win_rate"]))
            per_bot.append(sum(rates) / len(rates))
        out[p2] = per_bot
    return out


def min_max_with_counterparty_p1(
    matrices: List[Dict[str, Dict[str, Any]]],
) -> Tuple[
    Dict[str, float],
    Dict[str, float],
    Dict[str, str],
    Dict[str, str],
]:
    """Min/max win_rate par P1 et id P2 à la cellule (départage déterministe si égalité)."""
    worst: Dict[str, float] = {}
    best: Dict[str, float] = {}
    worst_cp: Dict[str, str] = {}
    best_cp: Dict[str, str] = {}
    if not matrices:
        return worst, best, worst_cp, best_cp
    p1_ids = set()
    for m in matrices:
        p1_ids |= set(m.keys())
    for p1 in p1_ids:
        min_cand: Tuple[float, str, int] | None = None
        max_cand: Tuple[float, str, int] | None = None
        for bot_idx, m in enumerate(matrices):
            row = m[p1]
            for p2 in sorted(row.keys()):
                v = float(row[p2]["win_rate"])
                key_min = (v, p2, bot_idx)
                key_max = (v, p2, bot_idx)
                if min_cand is None or key_min < (min_cand[0], min_cand[1], min_cand[2]):
                    min_cand = (v, p2, bot_idx)
                if max_cand is None or key_max > (max_cand[0], max_cand[1], max_cand[2]):
                    max_cand = (v, p2, bot_idx)
        assert min_cand is not None and max_cand is not None
        worst[p1] = min_cand[0]
        worst_cp[p1] = min_cand[1]
        best[p1] = max_cand[0]
        best_cp[p1] = max_cand[1]
    return worst, best, worst_cp, best_cp


def min_max_with_counterparty_p2(
    matrices: List[Dict[str, Dict[str, Any]]],
) -> Tuple[
    Dict[str, float],
    Dict[str, float],
    Dict[str, str],
    Dict[str, str],
]:
    """Min/max win_rate par P2 et id P1 à la cellule."""
    worst: Dict[str, float] = {}
    best: Dict[str, float] = {}
    worst_cp: Dict[str, str] = {}
    best_cp: Dict[str, str] = {}
    if not matrices:
        return worst, best, worst_cp, best_cp
    p2_ids: set[str] = set()
    for m in matrices:
        for _p1, row in m.items():
            p2_ids |= set(row.keys())
    for p2 in p2_ids:
        min_cand: Tuple[float, str, int] | None = None
        max_cand: Tuple[float, str, int] | None = None
        for bot_idx, m in enumerate(matrices):
            for p1 in sorted(m.keys()):
                row = m[p1]
                v = float(row[p2]["win_rate"])
                key_min = (v, p1, bot_idx)
                key_max = (v, p1, bot_idx)
                if min_cand is None or key_min < (min_cand[0], min_cand[1], min_cand[2]):
                    min_cand = (v, p1, bot_idx)
                if max_cand is None or key_max > (max_cand[0], max_cand[1], max_cand[2]):
                    max_cand = (v, p1, bot_idx)
        assert min_cand is not None and max_cand is not None
        worst[p2] = min_cand[0]
        worst_cp[p2] = min_cand[1]
        best[p2] = max_cand[0]
        best_cp[p2] = max_cand[1]
    return worst, best, worst_cp, best_cp


def weighted_mean(per_bot: List[float], weights: Sequence[float]) -> float:
    return sum(w * x for w, x in zip(weights, per_bot, strict=True))


def build_rows_p1(
    matrices: List[Dict[str, Dict[str, Any]]],
    weights: Sequence[float],
    labels: Tuple[str, str, str] = BOT_LABELS,
) -> List[Dict[str, Any]]:
    mm = marginal_means_p1(matrices)
    wmap, bmap, wcp, bcp = min_max_with_counterparty_p1(matrices)
    rows: List[Dict[str, Any]] = []
    for p1, per_bot in mm.items():
        rows.append(
            {
                "roster_id": p1,
                labels[0]: per_bot[0],
                labels[1]: per_bot[1],
                labels[2]: per_bot[2],
                "mean_agg": weighted_mean(per_bot, weights),
                "worst": wmap[p1],
                "worst_vs_roster": wcp[p1],
                "best": bmap[p1],
                "best_vs_roster": bcp[p1],
            }
        )
    return rows


def build_rows_p2(
    matrices: List[Dict[str, Dict[str, Any]]],
    weights: Sequence[float],
    labels: Tuple[str, str, str] = BOT_LABELS,
) -> List[Dict[str, Any]]:
    mm = marginal_means_p2(matrices)
    wmap, bmap, wcp, bcp = min_max_with_counterparty_p2(matrices)
    rows: List[Dict[str, Any]] = []
    for p2, per_bot in mm.items():
        rows.append(
            {
                "roster_id": p2,
                labels[0]: per_bot[0],
                labels[1]: per_bot[1],
                labels[2]: per_bot[2],
                "mean_agg": weighted_mean(per_bot, weights),
                "worst": wmap[p2],
                "worst_vs_roster": wcp[p2],
                "best": bmap[p2],
                "best_vs_roster": bcp[p2],
            }
        )
    return rows


def sort_rows(
    rows: List[Dict[str, Any]], key: str, descending: bool
) -> List[Dict[str, Any]]:
    reverse = descending
    return sorted(rows, key=lambda r: r[key], reverse=reverse)


def csv_fieldnames(labels: Tuple[str, str, str]) -> Tuple[str, ...]:
    return (
        "roster_id",
        "roster_value",
        labels[0],
        labels[1],
        labels[2],
        "mean_agg",
        "worst",
        "worst_vs_roster",
        "worst_vs_value",
        "best",
        "best_vs_roster",
        "best_vs_value",
    )


CSV_FIELDNAMES: Tuple[str, ...] = csv_fieldnames(BOT_LABELS)

CSV_DELIMITER = ";"


def _csv_float_fr(value: float, decimals: int = 4) -> str:
    """Représentation décimale avec virgule (Excel FR / locale)."""
    return f"{value:.{decimals}f}".replace(".", ",")


def write_csv(
    path: Path,
    rows: List[Dict[str, Any]],
    labels: Tuple[str, str, str] = BOT_LABELS,
) -> None:
    """Écrit un CSV délimité par ';' et nombres décimaux avec ','."""
    fieldnames = list(csv_fieldnames(labels))
    float_keys = frozenset(("mean_agg", "worst", "best", labels[0], labels[1], labels[2]))
    int_keys = frozenset(("roster_value", "worst_vs_value", "best_vs_value"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            delimiter=CSV_DELIMITER,
            quoting=csv.QUOTE_MINIMAL,
        )
        w.writeheader()
        for r in rows:
            out_row: Dict[str, str] = {}
            for k in fieldnames:
                v = r[k]
                if v == "":
                    out_row[k] = ""
                elif k in float_keys:
                    out_row[k] = _csv_float_fr(float(v))
                elif k in int_keys:
                    out_row[k] = str(int(v))
                else:
                    out_row[k] = str(v)
            w.writerow(out_row)


def filter_p1_rows(
    rows: List[Dict[str, Any]], roster_filter: str | None
) -> List[Dict[str, Any]]:
    """Si roster_filter est une liste d'ids comma-separated, ne garde que ces lignes."""
    if not roster_filter or not str(roster_filter).strip():
        return rows
    allowed = {x.strip() for x in str(roster_filter).split(",") if x.strip()}
    if not allowed:
        return rows
    present = {r["roster_id"] for r in rows}
    missing = sorted(allowed - present)
    if missing:
        print(
            "⚠️  roster_id demandé(s) absent(s) des matrices : " + ", ".join(missing),
            file=sys.stderr,
        )
    return [r for r in rows if r["roster_id"] in allowed]


def _fmt_table_int_cell(value: Any, width: int) -> str:
    if value == "":
        return " " * width
    return f"{int(value):>{width}}"


def print_table(
    title: str,
    rows: List[Dict[str, Any]],
    sort_key: str,
    labels: Tuple[str, str, str] = BOT_LABELS,
) -> None:
    print(title)
    print(f"(tri par {sort_key})")
    wv_w = 36
    bv_w = 36
    vw = 6
    hdr = (
        f"{'roster_id':<42} {'VALUE':>{vw}} {labels[0]:>14} {labels[1]:>14} {labels[2]:>14} "
        f"{'mean_agg':>10} {'worst':>8} {'worst_vs':>{wv_w}} {'w_v':>{vw}} "
        f"{'best':>8} {'best_vs':>{bv_w}} {'b_v':>{vw}}"
    )
    print(hdr)
    for r in rows:
        wv_raw = r["worst_vs_roster"]
        bv_raw = r["best_vs_roster"]
        wv = (wv_raw[: wv_w - 2] + "..") if len(wv_raw) > wv_w else wv_raw
        bv = (bv_raw[: bv_w - 2] + "..") if len(bv_raw) > bv_w else bv_raw
        print(
            f"{r['roster_id']:<42} {_fmt_table_int_cell(r['roster_value'], vw)} "
            f"{r[labels[0]]:14.4f} {r[labels[1]]:14.4f} {r[labels[2]]:14.4f} "
            f"{r['mean_agg']:10.4f} {r['worst']:8.4f} {wv:>{wv_w}} {_fmt_table_int_cell(r['worst_vs_value'], vw)} "
            f"{r['best']:8.4f} {bv:>{bv_w}} {_fmt_table_int_cell(r['best_vs_value'], vw)}"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Agrégats multi-bots des matchups holdout_hard.")
    parser.add_argument(
        "--matchup-dir",
        type=Path,
        default=PROJECT_ROOT
        / "config/agents/CoreAgent/rosters/150pts/matchups",
        help="Répertoire contenant les 3 JSON holdout_hard_matchups_*.json",
    )
    parser.add_argument(
        "--role",
        choices=("p1", "p2", "both"),
        default="both",
        help="P1 = rosters agent ; P2 = rosters opponent",
    )
    parser.add_argument(
        "--sort",
        choices=("mean", "worst", "best"),
        default="mean",
        help="Clé de tri (mean_agg, worst, best). worst/best : ordre décroissant par défaut pour best, croissant pour worst",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Si défini, écrit un CSV (suffixe _p1 / _p2 si both) : séparateur ';', décimales ','.",
    )
    parser.add_argument(
        "--p1subset",
        action="store_true",
        help=(
            "Charge holdout_hard_matchups_<bot>_p1subset.json (générés par "
            "roster_matchup_stats.py --p1-rosters ...) au lieu des matrices complètes."
        ),
    )
    parser.add_argument(
        "--p1exclude",
        action="store_true",
        help=(
            "Charge holdout_hard_matchups_<bot>_p1exclude.json (adaptive, aggressive_smart, "
            "defensive — sortie de roster_matchup_stats.py --p1-exclude). Moyenne pondérée 1/3 chacun."
        ),
    )
    parser.add_argument(
        "--p1-rosters",
        metavar="ID_LIST",
        default=None,
        help=(
            "Liste comma-separated de roster_id P1 à afficher (filtre après agrégation). "
            "Utile avec une matrice complète ou pour réordonner un sous-ensemble."
        ),
    )
    parser.add_argument(
        "--units-matrix",
        type=Path,
        default=DEFAULT_UNITS_MATRIX,
        help=(
            "Matrice unit_sampling (unit_values) pour calculer roster VALUE ; "
            f"défaut: {DEFAULT_UNITS_MATRIX.relative_to(PROJECT_ROOT)}"
        ),
    )
    parser.add_argument(
        "--skip-roster-values",
        action="store_true",
        help="Ne pas charger les VALUE des rosters (pas de colonnes roster_value / *_vs_value).",
    )
    args = parser.parse_args()

    if args.p1subset and args.p1exclude:
        print("❌ Utiliser soit --p1subset soit --p1exclude, pas les deux.", file=sys.stderr)
        sys.exit(1)

    sort_key_map = {"mean": "mean_agg", "worst": "worst", "best": "best"}
    sort_field = sort_key_map[args.sort]

    if args.p1exclude:
        bot_files = BOT_FILES_P1EXCLUDE
        weights = BOT_WEIGHTS_P1EXCLUDE
        labels: Tuple[str, str, str] = BOT_LABELS_P1EXCLUDE
    elif args.p1subset:
        bot_files = BOT_FILES_P1SUBSET
        weights = BOT_WEIGHTS
        labels = BOT_LABELS
    else:
        bot_files = BOT_FILES
        weights = BOT_WEIGHTS
        labels = BOT_LABELS

    _require_weights_sum(weights)

    matrices: List[Dict[str, Dict[str, Any]]] = []
    for name in bot_files:
        p = args.matchup_dir / name
        if not p.is_file():
            print(f"Fichier manquant: {p}", file=sys.stderr)
            sys.exit(1)
        matrices.append(load_matchup_matrix(p))

    roster_split = _roster_split_from_bot_json_name(bot_files[0])
    agent_key, scale = agent_key_and_scale_from_matchup_dir(args.matchup_dir)
    unit_type_values: Dict[str, int] | None = None
    if not args.skip_roster_values:
        if not args.units_matrix.is_file():
            print(f"Fichier manquant (unit_values): {args.units_matrix}", file=sys.stderr)
            sys.exit(1)
        unit_type_values = load_unit_type_values(args.units_matrix)

    # Tri : pour "worst" on veut souvent voir les plus faibles min en premier (croissant)
    descending = args.sort == "best" or args.sort == "mean"

    if args.role in ("p1", "both"):
        rows_p1 = build_rows_p1(matrices, weights, labels)
        rows_p1 = filter_p1_rows(rows_p1, args.p1_rosters)
        sorted_p1 = sort_rows(rows_p1, sort_field, descending)
        if unit_type_values is not None:
            enrich_rows_with_roster_values(
                sorted_p1, "p1", agent_key, scale, roster_split, unit_type_values
            )
        else:
            for r in sorted_p1:
                r["roster_value"] = ""
                r["worst_vs_value"] = ""
                r["best_vs_value"] = ""
        if args.p1exclude:
            p1_title = "=== P1 (agent) rosters — matrices p1exclude (adaptive, aggressive_smart, defensive) ==="
        elif args.p1subset:
            p1_title = "=== P1 (agent) rosters — matrices p1subset ==="
        else:
            p1_title = "=== P1 (agent) rosters ==="
        print_table(p1_title, sorted_p1, args.sort, labels)
        if args.csv:
            out = args.csv.parent / (args.csv.stem + "_p1" + args.csv.suffix)
            write_csv(out, sorted_p1, labels)
            print(f"CSV P1: {out}")

    if args.role in ("p2", "both"):
        rows_p2 = build_rows_p2(matrices, weights, labels)
        sorted_p2 = sort_rows(rows_p2, sort_field, descending)
        if unit_type_values is not None:
            enrich_rows_with_roster_values(
                sorted_p2, "p2", agent_key, scale, roster_split, unit_type_values
            )
        else:
            for r in sorted_p2:
                r["roster_value"] = ""
                r["worst_vs_value"] = ""
                r["best_vs_value"] = ""
        print_table("=== P2 (opponent) rosters ===", sorted_p2, args.sort, labels)
        if args.csv:
            out = args.csv.parent / (args.csv.stem + "_p2" + args.csv.suffix)
            write_csv(out, sorted_p2, labels)
            print(f"CSV P2: {out}")


if __name__ == "__main__":
    main()
