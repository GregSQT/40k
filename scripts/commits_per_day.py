#!/usr/bin/env python3
"""Compte les commits git par jour ou par semaine et trace un histogramme."""
import argparse
import collections
import subprocess
import sys

import matplotlib.pyplot as plt


def get_commit_dates() -> list[str]:
    output = subprocess.run(
        ["git", "log", "--pretty=%ad", "--date=short"],
        capture_output=True, text=True, check=True,
    ).stdout
    return output.splitlines()


def to_week(date: str) -> str:
    year, week, _ = __import__("datetime").date.fromisoformat(date).isocalendar()
    return f"{year}-W{week:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weekly", action="store_true", help="agréger par semaine au lieu du jour")
    parser.add_argument("--output", default="commits_per_day.png", help="fichier image de sortie")
    args = parser.parse_args()

    dates = get_commit_dates()
    if not dates:
        print("Aucun commit trouvé.", file=sys.stderr)
        sys.exit(1)

    keys = [to_week(d) for d in dates] if args.weekly else dates
    counts = collections.Counter(keys)
    ordered = sorted(counts.items())
    labels, values = zip(*ordered)

    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.3), 5))
    ax.bar(labels, values)
    ax.set_ylabel("Commits")
    ax.set_title("Commits par semaine" if args.weekly else "Commits par jour")
    ax.tick_params(axis="x", rotation=90)
    fig.tight_layout()
    fig.savefig(args.output)
    print(f"Graphique enregistré dans {args.output}")


if __name__ == "__main__":
    main()
