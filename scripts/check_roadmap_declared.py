#!/usr/bin/env python3
"""Combien de chantiers ont été livrés dans `main` sans passer par la feuille de route ?

POURQUOI CETTE PORTE EXISTE. `Documentation/Implémentation/ROADMAP.md` se déclare source unique de
l'ordre du travail, et sa règle de discipline veut qu'un chantier livré mette sa ligne à jour dans
la même livraison. Mesuré le 2026-08-11 : sur les sept dernières livraisons, **trois** n'avaient
laissé aucune trace — `ez-mask-minkowski`, `deep-strike-observe`, `terrains-mc1-mc2-tests`. Deux
changeaient ce que le jeu autorise (coups légaux, déploiement), donc les scores d'avant et d'après
n'étaient plus comparables sans que rien ne le dise. La règle était écrite : elle a échoué trois
fois de suite parce que rien ne la vérifiait.

POURQUOI UN PLAFOND, ET PAS UN REFUS SEC. Le refus sec a été essayé et MESURÉ avant d'être
abandonné : « la branche fusionnée doit toucher la feuille de route » refuse **22 des 25** derniers
merges, et « la feuille doit avoir bougé depuis le merge précédent » en refuse **20 sur 25**. Le
flux réel écrit la ligne dans un commit de suivi, après la fusion — acceptable tant que le suivi
arrive. Une porte rouge en permanence serait contournée dès le premier usage : on aurait troqué un
manque visible contre un contrôle mort.

CE QU'ELLE VAUT VRAIMENT, mesuré une fois ses deux défauts corrigés (échappement des accents,
simplification d'historique) : sur les 17 fusions postérieures au 2026-08-10, le plafond 3 en
refuse 4 — et ce sont les QUATRE plus anciennes, antérieures au moment où la feuille a pris son
rôle. Sur les treize suivantes, **elle ne se déclencherait pas une seule fois**, y compris sur les
trois chantiers dont on sait qu'ils n'ont pas été déclarés.

LA RAISON, et c'est sa limite de fond : la dette retombe à zéro dès que la feuille de route est
TOUCHÉE, pour n'importe quel motif — une correction de valeur, une reformulation, une typo. Or ce
fichier est retouché souvent. La porte mesure donc une SÉCHERESSE d'écriture, pas la déclaration
d'un chantier précis, et une écriture sans rapport la désarme sans intention de tricher. Elle
attrape l'oubli prolongé ; elle ne remplace pas la discipline, et il ne faut pas lui faire dire
qu'un chantier a sa ligne.

CE QU'ELLE N'ÉTABLIT PAS :
  - que la ligne écrite soit JUSTE, ni qu'elle parle du bon chantier — aucune machine ne le sait.
    Les valeurs fausses sont attrapées ensuite par `check_doc_references.py` ; une ligne creuse
    n'est attrapée par personne.
  - qu'un chantier livré par un commit direct sur `main` soit déclaré : la porte ne regarde que
    les fusions, sinon elle viserait chaque correction de détail.

Usage : python3 scripts/check_roadmap_declared.py --merge   (depuis le hook `prepare-commit-msg`)
        python3 scripts/check_roadmap_declared.py --status   (état courant, sans rien bloquer)
Sortie : 0 si la dette est sous le plafond, 1 si la porte refuse, 2 si elle n'a PAS PU se
        prononcer (usage faux, `--merge` hors fusion, état du dépôt inattendu). Une porte qui ne
        sait pas ne dit jamais oui : 2 bloque le commit comme 1, mais l'annonce autrement.
Contournement assumé : `git merge --no-verify`.

JAMAIS DE TRACE PYTHON EN SORTIE. Mesuré le 2026-08-11 : `--merge` mourait sur une
`CalledProcessError` de dix lignes dans deux états atteignables — sans fusion en cours, et pendant
une vraie fusion en HEAD détaché. git affichait « Not committing merge » sans qu'une seule ligne
dise ce qu'on attendait de l'utilisateur ; relancer `git commit` faisait passer la fusion, ce qui
donne l'impression d'une porte cassée plutôt que d'un refus motivé. Toute sortie est désormais un
feu vert ou un refus LISIBLE — filet de sécurité compris (voir `__main__`).
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

ROADMAP = "Documentation/Implémentation/ROADMAP.md"

#: Nombre de chantiers qu'on tolère non déclarés. Voir le calibrage en tête de module — ce n'est
#: pas un chiffre choisi au jugé, c'est le seul qui ne refuse que le cas réellement fautif.
MAX_UNDECLARED = 3

#: Seule branche où « livrer » a un sens. Fusionner `main` DANS un worktree est l'opération
#: inverse : elle n'apporte rien de neuf au projet.
PROTECTED_BRANCH = "main"


def verdict(undeclared: list[str], branch_declares: bool) -> tuple[bool, str]:
    """(la fusion peut passer, message). Cœur PUR : aucun appel à git, testable tel quel."""
    if branch_declares:
        return True, "la branche fusionnée met la feuille de route à jour"
    count = len(undeclared)
    if count < MAX_UNDECLARED:
        reste = MAX_UNDECLARED - count - 1
        return True, (
            f"{count} chantier(s) livré(s) sans déclaration, plafond {MAX_UNDECLARED} — "
            f"encore {reste} avant blocage"
        )
    listing = "\n".join(f"     {line}" for line in undeclared)
    return False, (
        f"{count} chantiers ont été livrés dans `{PROTECTED_BRANCH}` sans que la feuille de route\n"
        f"   ne bouge :\n{listing}\n\n"
        f"   {ROADMAP} se déclare source unique de l'ordre du travail. Qui l'ouvre pour décider de\n"
        "   la suite décide sur un état du projet qui n'existe plus. Écris leurs lignes — celle de\n"
        "   la fusion en cours comprise — puis relance.\n\n"
        "   Si aucun de ces merges n'est un chantier : git merge --no-verify"
    )


def git(*args: str) -> str:
    """`core.quotePath=false` n'est PAS un confort d'affichage.

    Par défaut git échappe les octets non-ASCII des chemins qu'il IMPRIME :
    `Documentation/Implémentation/…` ressort en `"Documentation/Impl\\303\\251mentation/…"`. Le
    comparer au chemin littéral rend donc toujours faux — mesuré le 2026-08-11, la porte s'était
    livrée avec sa sortie de secours morte, et les deux mesures de calibrage qui s'appuyaient sur
    la même comparaison étaient à refaire. Le dossier de ce dépôt porte un accent : ce réglage est
    une condition de correction, pas une préférence.
    """
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.strip()


def git_maybe(*args: str) -> str | None:
    """Comme `git`, mais rend `None` quand la commande sort non-zéro AU LIEU de lever.

    Réservé aux DEUX questions dont l'échec est un ÉTAT, pas une panne : « sur quelle branche
    suis-je ? » (HEAD détaché → pas de branche) et « une fusion est-elle en cours ? » (pas de
    MERGE_HEAD). Partout ailleurs `git` reste `check=True` : un échec y est une vraie panne et
    doit remonter au filet, pas se muer en silence.
    """
    completed = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def undeclared_merges(head: str) -> list[str]:
    """Les fusions entrées dans `main` depuis la dernière écriture de la feuille de route.

    `--first-parent` des DEUX côtés : sans lui, `git log -- <chemin>` suit la simplification
    d'historique et peut désigner un commit vivant DANS la branche fusionnée. L'intervalle repart
    alors d'avant la fusion et recompte toutes les fusions arrivées sur le tronc pendant la vie du
    chantier — la dette explose juste après une déclaration correcte. On ne compte que le tronc,
    qui est précisément ce que « livré dans `main` » veut dire.
    """
    last = git("log", "-1", "--first-parent", "--format=%H", head, "--", ROADMAP)
    span = f"{last}..{head}" if last else head
    listing = git("log", "--merges", "--first-parent", "--format=%h %s", span)
    return [line for line in listing.split("\n") if line]


def branch_touches_roadmap(head: str, other: str) -> bool:
    """La branche fusionnée écrit-elle dans la feuille de route ?

    Trois points : ce que la BRANCHE a fait depuis la base commune, pas ce qui diffère entre les
    deux têtes — sinon tout ce qui a avancé sur `main` pendant la vie du chantier lui serait mis
    au crédit.
    """
    return ROADMAP in git("diff", "--name-only", f"{head}...{other}").split("\n")


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    if mode not in ("--merge", "--status"):
        print(__doc__)
        return 2
    if mode == "--merge":
        # HEAD détaché : `symbolic-ref` sort 128, ce qui tuait la porte EN PLEINE FUSION. Ce
        # n'est pourtant pas une anomalie — fusionner sur un HEAD détaché ne livre rien dans
        # `main`, c'est exactement le cas « hors `main`, sans objet ».
        if git_maybe("symbolic-ref", "--short", "HEAD") != PROTECTED_BRANCH:
            print("↷ feuille de route : fusion hors `main`, sans objet")
            return 0
        merge_head = git_maybe("rev-parse", "MERGE_HEAD")
        if merge_head is None:
            # Le hook `prepare-commit-msg` garde déjà l'appel derrière la présence de MERGE_HEAD :
            # arriver ici veut dire que `--merge` a été lancé HORS d'une fusion — à la main, ou
            # par un hook mal branché. Feu vert INTERDIT : `pre-merge-commit` tourne précisément
            # avant l'écriture de MERGE_HEAD, et un « sans objet » complaisant y rendrait la porte
            # muette pour toujours sans que rien ne le signale (CLAUDE.md T1).
            print(
                "❌ feuille de route : `--merge` sans fusion en cours (MERGE_HEAD absent).\n"
                "   Sans MERGE_HEAD, la porte ne sait pas quelle branche est fusionnée : elle ne\n"
                "   se prononce pas, et ne dit pas oui par défaut.\n"
                "   Ce mode s'appelle depuis le hook `prepare-commit-msg`, pendant une fusion.\n"
                "   Pour l'état courant du dépôt : "
                "python3 scripts/check_roadmap_declared.py --status"
            )
            return 2
        declares = branch_touches_roadmap("HEAD", merge_head)
    else:
        declares = False
    ok, message = verdict(undeclared_merges("HEAD"), declares)
    print(f"{'✅' if ok else '❌'} feuille de route : {message}")
    return 0 if ok or mode == "--status" else 1


if __name__ == "__main__":
    try:
        code = main(sys.argv)
    except Exception as exc:  # noqa: BLE001 - filet: une trace de dix lignes ne dit rien à git
        # Ce filet n'AVALE rien : il refuse, dit l'erreur exacte, et laisse la sortie de secours.
        # Le rendre vert masquerait une panne de la porte derrière une fusion réussie (T1).
        print(
            f"❌ feuille de route : contrôle impossible — {type(exc).__name__}: {exc}\n"
            "   La porte n'a pas pu se prononcer : le commit est refusé, pas la fusion approuvée.\n"
            "   Si l'état du dépôt est sain, c'est un défaut de la porte elle-même — à corriger\n"
            "   dans scripts/check_roadmap_declared.py.\n"
            "   Pour passer outre en attendant : git merge --no-verify",
            file=sys.stderr,
        )
        code = 2
    sys.exit(code)
