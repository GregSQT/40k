#!/usr/bin/env python3
"""Un chantier qu'on livre dans `main` a-t-il sa ligne dans la feuille de route ?

POURQUOI CETTE PORTE EXISTE. `Documentation/Implémentation/ROADMAP.md` se déclare source unique de
l'ordre du travail, et sa règle de discipline dit qu'un chantier livré met sa ligne à jour DANS la
même livraison. Mesuré le 2026-08-11 : sur les sept dernières livraisons, **trois** n'avaient
laissé aucune trace dans ce fichier — `ez-mask-minkowski`, `deep-strike-observe` et
`terrains-mc1-mc2-tests`. Deux d'entre elles changeaient ce que le jeu autorise (l'ensemble des
coups légaux, la façon dont les figurines se déploient), donc les scores d'avant et d'après
n'étaient plus comparables sans que rien ne le dise. La règle était écrite depuis le début : elle
a échoué trois fois de suite parce que rien ne la vérifiait.

CE QU'ELLE ÉTABLIT : une fusion **dans `main`** qui apporte du code ou de la configuration touche
aussi la feuille de route.

CE QU'ELLE N'ÉTABLIT PAS, et il faut le savoir pour ne pas s'y fier plus qu'elle ne vaut :
  - que la ligne ajoutée soit JUSTE, ni même qu'elle parle du bon chantier. Aucune machine ne sait
    le dire ; c'est le contrôle de `check_doc_references.py` qui attrape ensuite les valeurs
    fausses, et personne n'attrape une ligne creuse.
  - qu'un chantier livré autrement qu'en fusionnant dans `main` soit déclaré. Un commit direct sur
    `main` passe : la porte viserait alors chaque correction de détail, et un contrôle qui refuse
    tout finit désactivé.
  - qu'une livraison de TESTS seuls soit déclarée : elle est traitée comme une vérification, pas
    comme un chantier. `tests/` ne compte donc pas comme apport.

Usage : python3 scripts/check_roadmap_declared.py --merge     (depuis le hook `pre-merge-commit`)
        python3 scripts/check_roadmap_declared.py <base> <tête>
Sortie : 0 si la livraison est déclarée ou n'apporte rien, 1 sinon.
Contournement assumé, quand la fusion n'est vraiment pas un chantier : `git merge --no-verify`.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

ROADMAP = "Documentation/Implémentation/ROADMAP.md"

#: Ce qui fait d'une fusion une LIVRAISON. `tests/` en est absent volontairement (cf. docstring),
#: `Documentation/` aussi : un chantier de documentation se déclare par la feuille de route
#: elle-même, qui est dans ce dossier.
DELIVERY_PREFIXES = (
    "engine/", "ai/", "services/", "shared/", "scripts/", "config/",
    "frontend/src/", "frontend/wasm-los/",
)

#: Seule branche où la discipline s'applique : c'est « livrer ». Une fusion de `main` DANS un
#: worktree est l'opération inverse, elle n'apporte rien de neuf au projet.
PROTECTED_BRANCH = "main"


def delivered(files: list[str]) -> list[str]:
    """Les fichiers de la fusion qui en font une livraison."""
    return [f for f in files if f.startswith(DELIVERY_PREFIXES)]


def verdict(files: list[str]) -> tuple[bool, str]:
    """(la fusion peut passer, message). Cœur PUR : aucun appel à git, donc testable tel quel."""
    apports = delivered(files)
    if not apports:
        return True, "aucun apport de code ou de configuration — rien à déclarer"
    if ROADMAP in files:
        return True, f"{len(apports)} fichier(s) livré(s), feuille de route mise à jour"
    montre = "\n".join(f"     {f}" for f in apports[:12])
    reste = f"\n     … et {len(apports) - 12} autre(s)" if len(apports) > 12 else ""
    return False, (
        f"Cette fusion livre {len(apports)} fichier(s) de code ou de configuration sans toucher\n"
        f"   la feuille de route :\n{montre}{reste}\n\n"
        f"   {ROADMAP} se déclare source unique de l'ordre du travail. Un chantier\n"
        "   livré y met sa ligne à jour DANS la même livraison — sinon le prochain qui lit ce\n"
        "   fichier pour décider de la suite décide sur un état du projet qui n'existe plus.\n\n"
        "   Ajoute la ligne, puis relance la fusion.\n"
        "   Si cette fusion n'est vraiment pas un chantier : git merge --no-verify"
    )


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def current_branch() -> str:
    return git("symbolic-ref", "--short", "HEAD")


def merge_files() -> list[str]:
    """Fichiers qu'apporte la branche fusionnée, depuis la base commune.

    Trois points (`HEAD...MERGE_HEAD`) et non deux : on veut ce que la BRANCHE a fait, pas ce qui
    diffère entre les deux têtes. Avec deux points, tout ce qui a avancé sur `main` pendant la vie
    du chantier compterait comme apporté par lui.
    """
    merge_head = (ROOT / ".git" / "MERGE_HEAD").read_text(encoding="utf-8").split()[0]
    return [f for f in git("diff", "--name-only", f"HEAD...{merge_head}").split("\n") if f]


def main(argv: list[str]) -> int:
    if argv[1:2] == ["--merge"]:
        branch = current_branch()
        if branch != PROTECTED_BRANCH:
            print(f"↷ feuille de route : fusion hors `{PROTECTED_BRANCH}` ({branch}), sans objet")
            return 0
        files = merge_files()
    elif len(argv) == 3:
        files = [f for f in git("diff", "--name-only", f"{argv[1]}...{argv[2]}").split("\n") if f]
    else:
        print(__doc__)
        return 2
    ok, message = verdict(files)
    print(f"{'✅' if ok else '❌'} feuille de route : {message}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
