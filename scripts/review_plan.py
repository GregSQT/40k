#!/usr/bin/env python3
"""Pilote de campagne de code review.

Trois responsabilites, aucune autre :
  1. classer les fichiers par risque pour choisir les cibles ;
  2. tenir un backlog persistant de l'avancement (a faire / en cours / fait + commit) ;
  3. accumuler les arbitrages dans un fichier append-only qui survit a un plantage.

Le script ne lance NI /code-review NI /simplify NI la suite de tests : ces trois-la
appartiennent a l'utilisateur (cf. CLAUDE.md). Il ne modifie aucun fichier de code.

--------------------------------------------------------------------------------
POURQUOI LE CLASSEMENT EST UN SIMPLE TRI PAR TAILLE
--------------------------------------------------------------------------------
Mesure faite sur ce depot le 2026-08-06 : 186 commits de correction, 12 519 lignes
supprimees datees par git blame, holdout temporel coupe au 2026-07-29 (93 fix avant
pour deriver, 93 apres pour predire), 45 fichiers candidats.

Correlation de Spearman entre la metrique et les lignes reellement corrigees apres T :

    taille seule                 +0.627   <- gagnant
    churn x taille               +0.600
    age pondere par bande        +0.583
    lignes corrigees passees     +0.480
    churn seul                   +0.485
    densite corrections/kloc     +0.333

Aucune ponderation ne bat `wc -l`. Le churn, l'age du code et l'historique de bugs
ont tous ete testes et rejetes. NE PAS les reintroduire dans le score sans refaire
la mesure : c'est exactement l'erreur qui a produit la premiere version de ce script.

Sur l'age du code, la mesure a aussi montre (hors boucle write-debug < 6 h, qui pese
17 % des lignes corrigees et n'est pas reviewable) : le code recent est SOUS-represente
dans les bugs (0.66-0.68x), le code > 6 mois aussi (0.84x), le pic est a 3-6 mois
(1.94x). Mais ces poids sont instables d'une fenetre a l'autre (3-6 mois vaut 1.21x
si on ne derive que sur la premiere moitie de l'historique), et le holdout montre
qu'ils n'ameliorent pas la prediction. D'ou : signal reel, trop instable pour scorer.

Limites assumees : 45 fichiers, donc un ecart de +-0.05 entre metriques est dans le
bruit ; la fenetre "apres T" ne fait que 8 jours. Ce qui est solide, ce n'est pas que
la taille gagne de peu, c'est qu'aucune metrique plus riche ne fait mieux.

Le churn reste AFFICHE parce qu'il informe la priorite entre deux fichiers de taille
comparable, mais il n'entre dans aucun calcul.

Usage :
    python3 scripts/review_plan.py rank [--top N] [--since "6 months ago"]
    python3 scripts/review_plan.py sync [--top N] [--since "6 months ago"]
    python3 scripts/review_plan.py status
    python3 scripts/review_plan.py start <chemin>
    python3 scripts/review_plan.py done  <chemin> [--commit SHA]
    python3 scripts/review_plan.py note  <chemin> "<arbitrage>"
    python3 scripts/review_plan.py arbitrages
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.json_atomic import write_json_atomic  # noqa: E402  (dépend du sys.path ci-dessus)

# Repertoires balayes. tests/ est exclu : un test n'a pas de scenario d'echec en
# production, T4 ecarterait quasi tout ce qui en sortirait.
SCAN_DIRS = ("engine", "ai", "services", "shared", "scripts", "frontend/src")

CODE_SUFFIXES = (".py", ".ts", ".tsx")

# Fichiers de donnees : une review y rendrait du bruit, pas des findings.
EXCLUDE_PREFIXES = ("frontend/src/roster/",)

# Sous ce seuil, un fichier ne merite pas une passe dediee : il se review avec son
# appelant s'il en a besoin.
MIN_REVIEW_LINES = 200

# Au-dela de ce seuil, un fichier ne se passe pas en une seule review : la passe
# degenere en survol. Comme la taille EST le predicteur, ce drapeau est le coeur
# du classement, pas une decoration.
SPLIT_THRESHOLD = 2000

BACKLOG_JSON = Path("Documentation/Review/review_backlog.json")
BACKLOG_MD = Path("Documentation/Review/review_backlog.md")
ARBITRAGES_MD = Path("Documentation/Review/review_arbitrages.md")

STATES = ("todo", "doing", "done")


def repo_root() -> Path:
    """Racine du depot git. Leve si on n'est pas dans un depot."""
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def git(root: Path, *args: str) -> str:
    """Execute git dans le depot. Leve sur echec, jamais de sortie muette."""
    out = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return out.stdout


def churn_counts(root: Path, since: str) -> dict[str, int]:
    """Nombre de commits touchant chaque fichier depuis `since`. Informatif seul."""
    raw = git(
        root, "log", f"--since={since}", "--name-only", "--pretty=format:",
        "--", *SCAN_DIRS,
    )
    counts: dict[str, int] = {}
    for line in raw.splitlines():
        path = line.strip()
        if path:
            counts[path] = counts.get(path, 0) + 1
    return counts


def line_count(path: Path) -> int:
    """Nombre de lignes d'un fichier texte."""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def is_reviewable(rel_path: str) -> bool:
    """Vrai si le fichier a une valeur de review (code, pas donnee)."""
    if any(rel_path.startswith(prefix) for prefix in EXCLUDE_PREFIXES):
        return False
    return rel_path.endswith(CODE_SUFFIXES)


def build_ranking(root: Path, since: str) -> list[dict[str, Any]]:
    """Classement par taille de TOUS les fichiers de code suivis par git.

    L'enumeration part de `git ls-files`, pas de `git log` : un fichier gros et
    jamais touche depuis six mois doit apparaitre, puisque c'est la taille qui
    porte le signal, pas le churn.
    """
    churn = churn_counts(root, since)
    ranking: list[dict[str, Any]] = []
    for line in git(root, "ls-files", "--", *SCAN_DIRS).splitlines():
        rel_path = line.strip()
        if not rel_path or not is_reviewable(rel_path):
            continue
        absolute = root / rel_path
        if not absolute.is_file():
            continue
        lines = line_count(absolute)
        if lines < MIN_REVIEW_LINES:
            continue
        ranking.append(
            {
                "path": rel_path,
                "lines": lines,
                # 0 = reellement zero commit sur la fenetre, pas une valeur de repli.
                "churn": churn.get(rel_path, 0),
                "passes": max(1, round(lines / SPLIT_THRESHOLD + 0.4)),
            }
        )
    ranking.sort(key=lambda item: item["lines"], reverse=True)
    return ranking


def print_ranking(ranking: list[dict[str, Any]], top: int) -> None:
    """Affiche le classement en colonnes."""
    print(f"{'#':>3}  {'lignes':>6}  {'passes':>6}  {'churn':>5}  fichier")
    for index, item in enumerate(ranking[:top], start=1):
        print(
            f"{index:>3}  {item['lines']:>6}  {item['passes']:>6}  "
            f"{item['churn']:>5}  {item['path']}"
        )
    shown = ranking[:top]
    print(
        f"\n{len(ranking)} fichiers de >= {MIN_REVIEW_LINES} lignes classes par TAILLE "
        f"(seul predicteur qui tienne, cf. docstring), {len(shown)} affiches."
    )
    print(
        f"'passes' = nombre de passes de review estimees a "
        f"~{SPLIT_THRESHOLD} lignes chacune : total {sum(i['passes'] for i in shown)} "
        f"passes pour ces {len(shown)} fichiers."
    )
    print("'churn' est informatif : il departage deux fichiers de taille voisine.")


def load_backlog(root: Path) -> dict[str, Any]:
    """Charge le backlog. Leve si absent : c'est `sync` qui le cree."""
    path = root / BACKLOG_JSON
    if not path.is_file():
        raise SystemExit(
            f"Backlog absent ({BACKLOG_JSON}). Lance d'abord :\n"
            f"    python3 scripts/review_plan.py sync"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def save_backlog(root: Path, backlog: dict[str, Any]) -> None:
    """Ecrit le backlog JSON (source de verite) et regenere le rendu Markdown."""
    path = root / BACKLOG_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, backlog)
    render_backlog_md(root, backlog)


def render_backlog_md(root: Path, backlog: dict[str, Any]) -> None:
    """Rendu lisible du backlog. Regenere integralement a chaque ecriture."""
    targets = backlog["targets"]
    by_state = {state: [t for t in targets if t["state"] == state] for state in STATES}
    lines = [
        "# Backlog de code review",
        "",
        f"Genere par `scripts/review_plan.py` — derniere sync : {backlog['synced_at']}",
        "",
        "Cibles classees par TAILLE. Le churn, l'age du code et l'historique de bugs",
        "ont ete mesures et rejetes comme predicteurs — voir la docstring du script.",
        "",
        f"Ce fichier est un RENDU. La source de verite est `{BACKLOG_JSON}`.",
        "Ne pas l'editer a la main.",
        "",
        "| etat | cibles | passes restantes |",
        "|---|---:|---:|",
    ]
    for state, label in (("todo", "a faire"), ("doing", "en cours"), ("done", "fait")):
        items = by_state[state]
        passes = sum(t["passes"] for t in items) if state != "done" else 0
        lines.append(f"| {label} | {len(items)} | {passes if passes else ''} |")
    lines.append("")

    labels = {"doing": "En cours", "todo": "A faire", "done": "Fait"}
    for state in ("doing", "todo", "done"):
        items = by_state[state]
        if not items:
            continue
        lines.append(f"## {labels[state]}")
        lines.append("")
        lines.append("| lignes | passes | churn | fichier | commit | arbitrages |")
        lines.append("|---:|---:|---:|---|---|---:|")
        for item in items:
            commit = item["commit"] if item["commit"] else ""
            lines.append(
                f"| {item['lines']} | {item['passes']} | {item['churn']} | "
                f"`{item['path']}` | {commit} | {item['arbitrages']} |"
            )
        lines.append("")
    (root / BACKLOG_MD).write_text("\n".join(lines), encoding="utf-8")


def cmd_sync(root: Path, since: str, top: int) -> None:
    """Fusionne le classement courant dans le backlog sans perdre l'avancement."""
    ranking = build_ranking(root, since)[:top]
    path = root / BACKLOG_JSON
    existing: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for target in json.loads(path.read_text(encoding="utf-8"))["targets"]:
            existing[target["path"]] = target

    targets: list[dict[str, Any]] = []
    for item in ranking:
        previous = existing.pop(item["path"], None)
        targets.append(
            {
                "path": item["path"],
                "lines": item["lines"],
                "churn": item["churn"],
                "passes": item["passes"],
                "state": previous["state"] if previous else "todo",
                "commit": previous["commit"] if previous else None,
                "arbitrages": previous["arbitrages"] if previous else 0,
            }
        )
    # Une cible sortie du top mais deja engagee reste dans le backlog : la perdre
    # ferait disparaitre un travail en cours.
    kept = [t for t in existing.values() if t["state"] != "todo"]
    targets.extend(kept)

    backlog = {
        "since": since,
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "targets": targets,
    }
    save_backlog(root, backlog)
    print(
        f"{len(ranking)} cibles synchronisees, {len(kept)} conservees hors top. "
        f"-> {BACKLOG_MD}"
    )


def find_target(backlog: dict[str, Any], rel_path: str) -> dict[str, Any]:
    """Retrouve une cible du backlog. Leve si absente : pas d'ajout implicite."""
    for target in backlog["targets"]:
        if target["path"] == rel_path:
            return target
    raise SystemExit(
        f"'{rel_path}' n'est pas dans le backlog. Cibles disponibles :\n"
        + "\n".join(f"    {t['path']}" for t in backlog["targets"])
    )


def cmd_status(root: Path) -> None:
    """Affiche l'etat du backlog."""
    backlog = load_backlog(root)
    print(f"Sync : {backlog['synced_at']}")
    for state in ("doing", "todo", "done"):
        items = [t for t in backlog["targets"] if t["state"] == state]
        passes = sum(t["passes"] for t in items)
        print(f"\n[{state}] {len(items)} cibles, {passes} passes")
        for item in items:
            commit = f"  {item['commit']}" if item["commit"] else ""
            arb = f"  ({item['arbitrages']} arbitrage(s))" if item["arbitrages"] else ""
            print(
                f"  {item['lines']:>6} lig.  {item['passes']:>2} passe(s)  "
                f"{item['path']}{commit}{arb}"
            )


def cmd_set_state(root: Path, rel_path: str, state: str, commit: str | None) -> None:
    """Passe une cible dans un etat donne."""
    backlog = load_backlog(root)
    target = find_target(backlog, rel_path)
    target["state"] = state
    if commit is not None:
        target["commit"] = commit
    save_backlog(root, backlog)
    suffix = f" (commit {commit})" if commit else ""
    print(f"{rel_path} -> {state}{suffix}")


def cmd_note(root: Path, rel_path: str, text: str) -> None:
    """Ajoute un arbitrage. Ecriture append-only : rien n'est jamais reecrit."""
    backlog = load_backlog(root)
    target = find_target(backlog, rel_path)

    path = root / ARBITRAGES_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "# Arbitrages de code review\n\n"
            "Append-only. Chaque entree attend une decision utilisateur.\n",
            encoding="utf-8",
        )
    stamp = datetime.now().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n- [{stamp}] `{rel_path}` — {text}\n")

    target["arbitrages"] += 1
    save_backlog(root, backlog)
    print(
        f"Arbitrage enregistre ({target['arbitrages']} sur {rel_path}) "
        f"-> {ARBITRAGES_MD}"
    )


def cmd_arbitrages(root: Path) -> None:
    """Affiche tous les arbitrages accumules."""
    path = root / ARBITRAGES_MD
    if not path.is_file():
        print(f"Aucun arbitrage enregistre ({ARBITRAGES_MD} absent).")
        return
    sys.stdout.write(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("rank", "sync"):
        p = sub.add_parser(name)
        p.add_argument("--top", type=int, default=30)
        p.add_argument("--since", default="6 months ago",
                       help="fenetre de la colonne churn (informative uniquement)")

    sub.add_parser("status")

    p_start = sub.add_parser("start")
    p_start.add_argument("path")

    p_done = sub.add_parser("done")
    p_done.add_argument("path")
    p_done.add_argument("--commit", default=None)

    p_note = sub.add_parser("note")
    p_note.add_argument("path")
    p_note.add_argument("text")

    sub.add_parser("arbitrages")

    args = parser.parse_args()
    root = repo_root()

    if args.command == "rank":
        print_ranking(build_ranking(root, args.since), args.top)
    elif args.command == "sync":
        cmd_sync(root, args.since, args.top)
    elif args.command == "status":
        cmd_status(root)
    elif args.command == "start":
        cmd_set_state(root, args.path, "doing", None)
    elif args.command == "done":
        cmd_set_state(root, args.path, "done", args.commit)
    elif args.command == "note":
        cmd_note(root, args.path, args.text)
    elif args.command == "arbitrages":
        cmd_arbitrages(root)


if __name__ == "__main__":
    main()
