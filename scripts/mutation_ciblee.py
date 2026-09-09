#!/usr/bin/env python3
"""Mutation testing CIBLE SUR LE DIFF : est-ce que les tests mordent encore ?

POURQUOI CE SCRIPT EXISTE
-------------------------
CLAUDE.md (T4 — TESTS) impose deja cette preuve : « remettre le defaut → constater ROUGE →
retablir le fix → constater VERT ». Elle se fait A LA MAIN, UNE FOIS, au moment du correctif.
Rien ne la rejoue ensuite. Un test qui a cesse de mordre — fixture qui a derive, assertion
devenue tautologique, code deplace hors du chemin exerce — reste vert indefiniment, et sa
verdure se lit comme une garantie.

Ce script automatise exactement ce geste, sur le PERIMETRE DU DIFF et rien d'autre : il abime
les lignes que l'on vient d'ecrire, et regarde si la suite s'en apercoit. Un mutant SURVIVANT
est un defaut que les tests laisseraient passer.

POURQUOI CIBLE, ET PAS UNE CAMPAGNE COMPLETE
--------------------------------------------
`engine/`, `ai/`, `services/` et `shared/` totalisent ~135 000 lignes, et la suite unitaire se
compte en minutes : une campagne exhaustive se compterait en jours, donc ne serait jamais lancee.
Le diff, lui, fait quelques dizaines de lignes, et c'est la que le risque est — le code qu'on
vient de changer est celui dont personne ne sait encore s'il est teste.

CE QU'UN MUTANT SURVIVANT VEUT DIRE, ET CE QU'IL NE VEUT PAS DIRE
-----------------------------------------------------------------
Il veut dire : « aucun des tests joues ne distingue ce code de ce code-la ». Trois causes, et
elles ne se corrigent pas de la meme facon :

1. la ligne n'est couverte par aucun test → ecrire le test ;
2. elle est couverte, mais l'assertion ne regarde pas ce qu'elle change → renforcer l'assertion ;
3. la mutation est SEMANTIQUEMENT NEUTRE (une borne inatteignable, un cas equivalent). C'est un
   faux positif legitime : il se constate, il ne se corrige pas.

Le script ne tranche pas entre les trois — il rend le mutant, sa ligne et les tests joues.

SURETE
------
Le fichier mute est restaure dans un `finally`, et sa restauration est VERIFIEE par comparaison
du contenu avant de passer au mutant suivant. Le script s'arrete net si un fichier n'a pas pu
etre remis en etat : laisser un mutant dans l'arbre serait pire que tout ce qu'il mesure.

Chaque mutation purge `__pycache__` : un `.pyc` compile depuis le mutant survivrait a la
restauration si le fichier restaure a la MEME TAILLE et la meme mtime a la seconde pres — et
Python rejouerait alors le mutant en croyant lire l'original.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import time
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

RACINE = Path(__file__).resolve().parents[1]

#: Repertoires dont le code est mute. `tests/` en est exclu par construction : muter un test ne
#: dit rien de la qualite des tests, seulement qu'il se teste lui-meme.
PERIMETRE = ("engine/", "ai/", "services/", "shared/")

#: Substitutions d'operateurs. Chacune change le COMPORTEMENT sans changer la syntaxe — c'est le
#: critere d'entree dans cette table. `+`/`-` n'y sont pas : ils sont aussi unaires, et muter
#: `-1` en `+1` produit du bruit plutot qu'un defaut.
MUTATIONS_OP: Dict[str, Tuple[str, ...]] = {
    "<": ("<=", ">"),
    ">": (">=", "<"),
    "<=": ("<",),
    ">=": (">",),
    "==": ("!=",),
    "!=": ("==",),
}

#: Substitutions de mots-cles.
MUTATIONS_MOT: Dict[str, Tuple[str, ...]] = {
    "and": ("or",),
    "or": ("and",),
    "True": ("False",),
    "False": ("True",),
}


@dataclass(frozen=True)
class Mutant:
    """Une mutation unique : un fichier, une ligne, un remplacement de token."""

    fichier: str
    ligne: int
    colonne: int
    avant: str
    apres: str

    def __str__(self) -> str:
        return f"{self.fichier}:{self.ligne} `{self.avant}` -> `{self.apres}`"


# --------------------------------------------------------------------------- lecture du diff


def lignes_modifiees(diff: str) -> Dict[str, Set[int]]:
    """Les lignes AJOUTEES ou MODIFIEES par ce diff unifie, par fichier.

    Seules les lignes `+` comptent : une ligne supprimee n'existe plus, il n'y a rien a muter.
    Les numeros sont ceux du fichier APRES le diff, donc ceux du fichier sur le disque.
    """
    par_fichier: Dict[str, Set[int]] = {}
    fichier: Optional[str] = None
    ligne_courante = 0
    for brute in diff.splitlines():
        if brute.startswith("+++ "):
            chemin = brute[4:].strip()
            fichier = chemin[2:] if chemin.startswith("b/") else chemin
            if fichier == "/dev/null":
                fichier = None
            continue
        if brute.startswith("@@"):
            entete = re.search(r"\+(\d+)", brute)
            ligne_courante = int(entete.group(1)) if entete else 0
            continue
        if fichier is None:
            continue
        if brute.startswith("+"):
            par_fichier.setdefault(fichier, set()).add(ligne_courante)
            ligne_courante += 1
        elif brute.startswith("-"):
            continue
        elif brute.startswith(" "):
            ligne_courante += 1
    return par_fichier


def dans_le_perimetre(fichier: str) -> bool:
    """Un `.py` de production, hors tests."""
    return fichier.endswith(".py") and fichier.startswith(PERIMETRE)


# --------------------------------------------------------------------------- generation


def mutants_du_fichier(chemin: Path, lignes: Iterable[int]) -> List[Mutant]:
    """Les mutants applicables aux lignes donnees de ce fichier.

    La source est TOKENISEE plutot que parcourue par expression reguliere : un `==` dans une
    chaine de caracteres ou un `and` dans un commentaire ne sont pas du code, et les muter
    produirait des mutants qu'aucun test ne peut tuer — donc des faux survivants, qui ruinent la
    lecture du rapport.
    """
    voulues = set(lignes)
    source = chemin.read_text(encoding="utf-8")
    trouves: List[Mutant] = []
    flux = io.StringIO(source).readline
    for jeton in tokenize.generate_tokens(flux):
        if jeton.start[0] not in voulues:
            continue
        if jeton.type == tokenize.OP:
            remplacements = MUTATIONS_OP.get(jeton.string, ())
        elif jeton.type == tokenize.NAME:
            # `and`, `or`, `True`, `False` sont des NAME pour `tokenize` — il n'y a pas de type
            # KEYWORD dans ce module, contrairement a ce que son nom laisse attendre.
            remplacements = MUTATIONS_MOT.get(jeton.string, ())
        else:
            remplacements = ()
        for apres in remplacements:
            trouves.append(
                Mutant(str(chemin.relative_to(RACINE)), jeton.start[0], jeton.start[1],
                       jeton.string, apres)
            )
    return trouves


def applique(source: str, mutant: Mutant) -> str:
    """La source avec CE mutant applique — une seule occurrence, reperee par ligne ET colonne.

    Un `str.replace` sur la ligne muterait toutes les occurrences du meme operateur : deux
    defauts a la fois ne se diagnostiquent pas, et un test qui en tue un seul ferait passer le
    couple pour mort.
    """
    lignes = source.splitlines(keepends=True)
    index = mutant.ligne - 1
    ligne = lignes[index]
    debut, fin = mutant.colonne, mutant.colonne + len(mutant.avant)
    if ligne[debut:fin] != mutant.avant:
        raise ValueError(
            f"{mutant.fichier}:{mutant.ligne} ne porte plus `{mutant.avant}` en colonne "
            f"{mutant.colonne} : le fichier a change depuis la generation des mutants."
        )
    lignes[index] = ligne[:debut] + mutant.apres + ligne[fin:]
    return "".join(lignes)


# --------------------------------------------------------------------------- choix des tests


def tests_candidats(fichier: str, tests_du_diff: Sequence[str]) -> List[str]:
    """Les fichiers de test a jouer contre ce fichier de production.

    Deux sources, cumulees : les tests TOUCHES par le meme diff (ceux qu'on vient d'ecrire pour
    ce changement, donc les premiers concernes) et ceux que la CONVENTION de nommage designe —
    `engine/foo.py` -> `tests/unit/engine/test_foo*.py`.

    Aucun candidat n'est un RESULTAT, pas une erreur : cela signifie que rien, dans le nommage ni
    dans le diff, ne relie ce fichier a un test. Le rapport le dit.
    """
    candidats = [t for t in tests_du_diff if Path(RACINE / t).exists()]
    module = Path(fichier)
    dossier = RACINE / "tests" / "unit" / module.parts[0]
    if dossier.is_dir():
        candidats.extend(
            str(p.relative_to(RACINE)) for p in sorted(dossier.glob(f"test_{module.stem}*.py"))
        )
    # `dict.fromkeys` plutot qu'un `set` : l'ordre de passage doit etre reproductible d'un run a
    # l'autre, sinon deux rapports du meme diff ne se comparent pas.
    return list(dict.fromkeys(candidats))


# --------------------------------------------------------------------------- execution


#: Repertoires dont les `__pycache__` ne sont JAMAIS purges : ils ne contiennent aucun mutant, et
#: les balayer coute plus cher que tout le reste du run.
HORS_PURGE = (".venv", "node_modules", ".git", "__pypackages__")


def purge_pycache(racine: Path) -> None:
    """Supprime les `__pycache__` DU DEPOT : cf. l'entete, un `.pyc` du mutant se rejouerait.

    Le balayage s'arrete aux dependances. Mesure du 2026-09-09 : `.venv` porte 539 `__pycache__`
    contre 35 pour le depot ; les purger faisait recompiler torch, SB3 et numpy DEUX FOIS par
    mutant — devant chacun des quarante pytest — et laissait le venv nu a la fin du run. Aucun de
    ces caches ne peut contenir un mutant : le script ne mute que `engine/`, `ai/`, `services/`
    et `shared/`.
    """
    for cache in racine.rglob("__pycache__"):
        if any(partie in HORS_PURGE for partie in cache.relative_to(racine).parts):
            continue
        shutil.rmtree(cache, ignore_errors=True)


def joue_les_tests(tests: Sequence[str], timeout: int) -> bool:
    """Vrai si la suite passe (donc si le mutant SURVIT).

    Un DEPASSEMENT de delai compte comme un mutant TUE, et non comme une erreur qui interrompt la
    campagne : muter une comparaison peut rendre une boucle infinie, c'est meme un des defauts que
    l'on cherche. Le harnais s'arreterait alors sur le premier d'entre eux, sans recapitulatif ni
    verdict pour les mutants suivants — le rapport entier serait perdu pour un mutant qui, lui,
    est bien detecte.
    """
    if not tests:
        return True
    try:
        resultat = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-x", "-q", "--no-header",
             "-p", "no:cacheprovider"],
            cwd=RACINE, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"      ⏱️  depassement de {timeout} s : mutant compte comme TUE")
        return False
    return resultat.returncode == 0


def evalue(mutant: Mutant, tests: Sequence[str], timeout: int) -> bool:
    """Applique le mutant, joue les tests, restaure. Rend True si le mutant est TUE.

    La restauration est verifiee : le script leve si le fichier n'est pas revenu a l'identique,
    plutot que de continuer sur un arbre abime.
    """
    chemin = RACINE / mutant.fichier
    original = chemin.read_text(encoding="utf-8")
    try:
        chemin.write_text(applique(original, mutant), encoding="utf-8")
        purge_pycache(RACINE)
        return not joue_les_tests(tests, timeout)
    finally:
        chemin.write_text(original, encoding="utf-8")
        purge_pycache(RACINE)
        if chemin.read_text(encoding="utf-8") != original:
            raise RuntimeError(
                f"ARRET : {mutant.fichier} n'a pas pu etre restaure. Verifier `git diff` AVANT "
                "toute autre commande."
            )


def diff_courant(base: Optional[str]) -> str:
    """Le diff a examiner : contre `base` si donnee, sinon les modifications non commitees."""
    commande = ["git", "diff"] + ([base] if base else []) + ["--unified=0"]
    return subprocess.run(commande, cwd=RACINE, capture_output=True, text=True, check=True).stdout


def main(argv: Optional[List[str]] = None) -> int:
    # `__doc__` est `None` sous `python -OO` : la description se lit du module, elle ne s'en
    # deduit pas.
    parseur = argparse.ArgumentParser(
        description="Mutation testing cible sur le diff : est-ce que les tests mordent encore ?"
    )
    parseur.add_argument("--base", help="ref git de comparaison (defaut : modifications non commitees)")
    parseur.add_argument("--tests", nargs="*", default=None,
                         help="fichiers de test a jouer (defaut : deduits du diff et du nommage)")
    parseur.add_argument("--max-mutants", type=int, default=40,
                         help="borne le run ; au-dela, le diff est trop gros pour un controle de livraison")
    parseur.add_argument("--timeout", type=int, default=900, help="secondes par mutant")
    args = parseur.parse_args(argv)

    diff = diff_courant(args.base)
    touches = lignes_modifiees(diff)
    tests_du_diff = [f for f in touches if f.startswith("tests/") and f.endswith(".py")]
    cibles = {f: l for f, l in touches.items() if dans_le_perimetre(f)}
    if not cibles:
        print("Aucun fichier de production dans le diff : rien a muter.")
        return 0

    plan: List[Tuple[Mutant, List[str]]] = []
    for fichier, lignes in sorted(cibles.items()):
        tests = args.tests if args.tests is not None else tests_candidats(fichier, tests_du_diff)
        for mutant in mutants_du_fichier(RACINE / fichier, lignes):
            plan.append((mutant, tests))

    if not plan:
        print("Aucune mutation applicable aux lignes modifiees (ni comparaison, ni booleen).")
        return 0
    if len(plan) > args.max_mutants:
        print(f"⚠️  {len(plan)} mutants pour un plafond de {args.max_mutants} : "
              f"les {args.max_mutants} premiers sont joues. Decouper la livraison, ou relever "
              f"--max-mutants en connaissance du temps que cela coute.")
        plan = plan[: args.max_mutants]

    survivants: List[Tuple[Mutant, List[str]]] = []
    sans_test: List[Mutant] = []
    debut = time.time()
    for index, (mutant, tests) in enumerate(plan, start=1):
        if not tests:
            sans_test.append(mutant)
            print(f"[{index}/{len(plan)}] ⚠️  {mutant} — AUCUN test candidat")
            continue
        tue = evalue(mutant, tests, args.timeout)
        print(f"[{index}/{len(plan)}] {'✅ tue' if tue else '🔴 SURVIVANT'}  {mutant}")
        if not tue:
            survivants.append((mutant, tests))

    print(f"\n{'=' * 70}\n{len(plan)} mutants en {time.time() - debut:.0f} s")
    for mutant in sans_test:
        print(f"  ⚠️  sans test candidat : {mutant}")
    for mutant, tests in survivants:
        print(f"  🔴 SURVIVANT : {mutant}\n       tests joues : {' '.join(tests)}")
    if not survivants and not sans_test:
        print("  ✅ tous les mutants ont ete tues.")
    return 1 if (survivants or sans_test) else 0


if __name__ == "__main__":
    raise SystemExit(main())
