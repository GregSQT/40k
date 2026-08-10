#!/usr/bin/env python3
"""Les renvois des documents d'entrée pointent-ils encore quelque chose de réel ?

POURQUOI CE SCRIPT EXISTE. `Documentation/Implémentation/analyzer_couverture.md` est le document
d'ENTRÉE des lots : il dit ce qui est vérifié, ce qui ne l'est pas, et pourquoi. Il est tenu à la
main, et rien ne le confrontait au dépôt. Le 2026-08-10, un contrôle ponctuel a mesuré l'état de
ses renvois **après une seule journée de livraisons** :

    147 citations `fichier.py:ligne` — 31 saines, 76 PROUVÉES FAUSSES, 40 invérifiables.

Les numéros de ligne ont donc été supprimés au profit du couple `fichier.py` + nom de symbole, qui
ne rouille pas. Ce script est la seconde moitié de cette décision : sans lui, le document
redevient invérifiable dès la prochaine session, et c'est très exactement la situation qu'on
voulait quitter. Trois lignes de ce document se sont déjà révélées fausses le même jour, toutes
dans le sens qui coûte le plus cher — annoncer une donnée disponible qui ne l'est pas.

CE QU'IL ÉTABLIT : tout fichier cité existe, et tout symbole cité vit dans le fichier cité **de la
même cellule**. CE QU'IL N'ÉTABLIT PAS : qu'un renvoi sans symbole soit juste — il n'y a alors
rien à confronter, et ces cas sont COMPTÉS et affichés plutôt que passés sous silence.

Usage : python3 scripts/check_doc_references.py [doc.md ...]
Sortie : 0 si aucun renvoi cassé, 1 sinon.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

DEFAULT_DOCS = ["Documentation/Implémentation/analyzer_couverture.md"]

#: Répertoires où un nom de fichier nu est cherché. `scripts/` en fait partie : son absence a
#: produit une fausse alerte sur `check_ai_rules.py` au premier passage.
SEARCH_DIRS = [
    "", "ai", "ai/analyzer_phases", "engine", "engine/phase_handlers", "engine/utils",
    "shared", "scripts", "services", "config", "tests/unit/ai", "tests/unit/engine",
]

FILE_REF = re.compile(r"([A-Za-z0-9_/]+\.(?:py|json|md))")
BACKTICKED = re.compile(r"`([^`]+)`")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")

#: Un renvoi générique (`*_handler.py`, `analyzer_phases/*`) ne désigne aucun fichier précis : il
#: n'y a rien à résoudre, et le compter en échec ferait du bruit là où le document est correct.
WILDCARD = re.compile(r"[*]")


def resolve(name: str) -> pathlib.Path | None:
    if "/" in name:
        candidate = ROOT / name
        return candidate if candidate.exists() else None
    for directory in SEARCH_DIRS:
        candidate = ROOT / directory / name if directory else ROOT / name
        if candidate.exists():
            return candidate
    return None


def symbol_is_present(symbol: str, body: str) -> bool:
    """Le symbole vit-il dans ce fichier, littéralement ou COMPOSÉ ?

    Plusieurs compteurs ne sont jamais écrits en toutes lettres : `analyzer_hit` écrit
    ``stats[f"{key}_mismatch"]`` et `analyzer_wound` fait de même. Chercher le nom complet
    (`shoot_hit_result_mismatch`) rend alors 0 hit sur un document pourtant juste — première
    cause de fausse alerte du contrôle d'origine. On accepte donc aussi le suffixe composé, à
    partir d'une frontière `_` et d'une longueur qui exclut les fragments passe-partout.
    """
    if symbol in body:
        return True
    parts = symbol.split("_")
    for start in range(1, len(parts)):
        suffix = "_" + "_".join(parts[start:])
        if len(suffix) >= 8 and f'"{{key}}{suffix}"' in body:
            return True
        if len(suffix) >= 8 and f"'{{key}}{suffix}'" in body:
            return True
    return False


def cells(line: str) -> list[str]:
    """Fragments d'une ligne de doc à traiter INDÉPENDAMMENT.

    Une ligne de tableau cite souvent plusieurs fichiers et plusieurs symboles qui ne vont pas
    ensemble. Les apparier tous avec tous fabrique des affirmations que le document n'a jamais
    faites — seconde cause de fausse alerte du contrôle d'origine. On découpe donc par cellule.
    """
    if not line.lstrip().startswith("|"):
        # PROSE : hors contrôle, et c'est un choix. Une phrase narrative cite couramment plusieurs
        # fichiers et plusieurs symboles qui ne vont pas ensemble (« `analyzer_wound.py` (module
        # neuf) ; `_handle_fled` … ») ; les apparier produit des alertes que le document ne mérite
        # pas. Un contrôle qui crie toujours est un contrôle que personne ne lance — c'est le mode
        # d'échec des verts vacants, par l'autre bout. Les renvois PORTEURS sont dans les cellules
        # des matrices ; ce sont eux qu'on vérifie, et les autres sont COMPTÉS comme non vérifiés.
        return []
    return line.split("|")


def check(doc_path: pathlib.Path) -> tuple[int, int, int, list[str]]:
    resolved = unverifiable = 0
    broken: list[str] = []
    for lineno, line in enumerate(doc_path.read_text(encoding="utf-8").split("\n"), 1):
        fragments = cells(line)
        if not fragments:
            unverifiable += len([n for n in FILE_REF.findall(line) if not WILDCARD.search(n)])
            continue
        for cell in fragments:
            names = [
                m.group(1) for m in FILE_REF.finditer(cell)
                if not (m.start() and cell[m.start() - 1] == "*")
            ]
            names = [n for n in dict.fromkeys(names) if not WILDCARD.search(n)]
            if not names:
                continue
            symbols: list[str] = []
            for raw in BACKTICKED.findall(cell):
                # Un fragment qui porte un chemin ou un joker (`analyzer_phases/*`) désigne un
                # ENSEMBLE de fichiers, pas un symbole : en tirer des identifiants fabriquait des
                # paires que le document n'a jamais affirmées.
                if "/" in raw or "*" in raw or FILE_REF.fullmatch(raw.strip()):
                    continue
                symbols += IDENTIFIER.findall(raw)
            symbols = [s for s in dict.fromkeys(symbols) if not s.endswith("py")]

            missing = [n for n in names if resolve(n) is None]
            for name in missing:
                broken.append(f"{doc_path.name}:{lineno}  FICHIER INTROUVABLE  {name}")
            present = [n for n in names if n not in missing]
            if not present:
                continue
            if not symbols:
                unverifiable += len(present)
                continue
            # UN renvoi est confirmé dès qu'UN des fichiers de la cellule porte UN des symboles
            # de la cellule. Exiger que CHAQUE fichier les porte tous serait une affirmation que
            # le document ne fait pas : une cellule cite couramment le producteur ET le lecteur
            # d'une donnée, dont les symboles ne vivent que d'un côté.
            bodies = [resolve(n).read_text(encoding="utf-8", errors="replace") for n in present]  # type: ignore[union-attr]
            if any(symbol_is_present(s, b) for s in symbols for b in bodies):
                resolved += len(present)
            else:
                broken.append(
                    f"{doc_path.name}:{lineno}  AUCUN SYMBOLE dans {', '.join(present)} — "
                    f"cherchés : {', '.join(symbols[:4])}"
                )
    return resolved, unverifiable, len(broken), broken


def main(argv: list[str]) -> int:
    docs = argv[1:] or DEFAULT_DOCS
    failed = False
    for doc in docs:
        path = ROOT / doc if not pathlib.Path(doc).is_absolute() else pathlib.Path(doc)
        if not path.exists():
            print(f"❌ document introuvable : {doc}")
            failed = True
            continue
        resolved, unverifiable, n_broken, broken = check(path)
        icon = "❌" if n_broken else "✅"
        print(
            f"{icon} {doc} — {resolved} renvois confirmés, {n_broken} cassés, "
            f"{unverifiable} sans symbole à confronter (non vérifiés)"
        )
        for entry in broken:
            print(f"   {entry}")
        failed = failed or bool(n_broken)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
