#!/usr/bin/env python3
"""Combien de chantiers ont été livrés dans `main` sans passer par la feuille de route ?

POURQUOI CETTE PORTE EXISTE. `Documentation/Roadmap/ROADMAP_INDEX.md` se déclare source unique de
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

CE QU'ELLE VAUT VRAIMENT — SEULE SOURCE DU CALIBRAGE, ne pas en recopier les chiffres ailleurs.
MÉTHODE, re-jouable en quelques secondes : pour chaque fusion du tronc depuis le 2026-08-10,
rejouer la porte telle qu'elle se serait prononcée à ce moment — `undeclared_merges(M^1)` pour la
dette, `branch_touches_roadmap(M^1, M^2)` pour la déclaration — et compter les refus par plafond.
MESURE du 2026-08-12, sur **50** fusions : plafond 1 → **15** refus, 2 → **11**, 3 → **9**,
4 → **9**. Les 9 refus du plafond 3 tombent TOUS le 2026-08-10, sur une dette de 92 à 100 : c'est
l'arriéré antérieur au moment où la feuille a pris son rôle, soldé par la première déclaration.
Sur les **41** fusions qui suivent ce solde : le plafond 3 ne se déclenche **pas une seule fois**
— y compris sur les chantiers dont on sait qu'ils n'ont pas été déclarés —, le plafond 2 refuse
**2** fusions, `c38ee8f5` (ez-mask-minkowski) et `2ede29f5` (socle-ligne-charge, tous deux
réellement non déclarés), et le plafond 1 en refuse **6**.

D'OÙ LE RÉGLAGE, tranché par l'utilisateur le 2026-08-12 : **plafond 2**. À 3 (et 4, qui rend le
même résultat) la porte était devenue une borne d'arriéré sans effet sur le flux courant. À 2 elle
refuse exactement les deux oublis avérés sur 41 fusions, sans toucher aux 39 autres. À 1 elle
refuserait 6 fois : assez souvent pour qu'on prenne l'habitude de la contourner, ce qui est le
risque qui avait fait abandonner le refus sec.

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
Contournement assumé — DEUX FORMES, selon le moment, et c'est le moment qui décide :
  - avant de lancer la fusion   : `ROADMAP_GATE=off git merge …`
  - après un refus (fusion en cours, MERGE_HEAD présent) : `ROADMAP_GATE=off git commit`
⚠️ PAS `--no-verify` : mesuré le 2026-08-12 sur git 2.43, `git merge --no-verify` saute
`pre-merge-commit` et `commit-msg`, JAMAIS `prepare-commit-msg` — là où cette porte vit depuis
qu'elle a besoin de MERGE_HEAD. La sortie de secours annoncée pendant un jour n'existait donc pas :
le refus enfermait l'utilisateur au milieu d'une fusion, en lui indiquant une porte murée.
⚠️ ET PAS `git merge` DANS LE MESSAGE DE REFUS : quand ce refus s'affiche, la fusion est déjà
commencée, et git répond alors `fatal: You have not concluded your merge (MERGE_HEAD exists)`.
Une consigne juste au mauvais moment est aussi murée qu'une consigne fausse (mesuré le 2026-08-12,
deuxième fois sur la même arête).

JAMAIS DE TRACE PYTHON EN SORTIE. Mesuré le 2026-08-11 : `--merge` mourait sur une
`CalledProcessError` de dix lignes dans deux états atteignables — sans fusion en cours, et pendant
une vraie fusion en HEAD détaché. git affichait « Not committing merge » sans qu'une seule ligne
dise ce qu'on attendait de l'utilisateur ; relancer `git commit` faisait passer la fusion, ce qui
donne l'impression d'une porte cassée plutôt que d'un refus motivé. Toute sortie est désormais un
feu vert ou un refus LISIBLE — filet de sécurité compris (voir `__main__`).
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

ROADMAP = "Documentation/Roadmap/ROADMAP_INDEX.md"

#: Dette qui DÉCLENCHE le refus — on en tolère donc `MAX_UNDECLARED - 1`. La docstring disait
#: « nombre toléré », soit un cran de trop : la prochaine recalibration se serait décalée.
#: Porté de 3 à 2 le 2026-08-12 (décision utilisateur). Le pourquoi et les chiffres sont dans le
#: calibrage en tête de module, et NULLE PART AILLEURS — les recopier est ce qui a produit deux
#: jeux contradictoires.
MAX_UNDECLARED = 2

#: Les deux façons dont une livraison déclare. Nommées ici parce que les tests les vérifient et
#: qu'un message recopié dans un test cesse un jour de correspondre à celui du code.
DECLARED_BY_BRANCH = "la branche fusionnée met la feuille de route à jour"
DECLARED_BY_INDEX = "la ligne de la feuille de route est écrite dans ce commit de fusion"

#: Désarmement explicite, et VISIBLE : la porte annonce elle-même qu'elle s'est tue. Elle a
#: annoncé `--no-verify` pendant un jour, qui ne saute pas `prepare-commit-msg` — un refus dont
#: la sortie de secours n'existe pas enferme l'utilisateur au milieu d'une fusion.
GATE_OFF_ENV = "ROADMAP_GATE"

#: Seule branche où « livrer » a un sens. Fusionner `main` DANS un worktree est l'opération
#: inverse : elle n'apporte rien de neuf au projet.
PROTECTED_BRANCH = "main"


def verdict(undeclared: list[str], declaration: str) -> tuple[bool, str]:
    """(la fusion peut passer, message). Cœur PUR : aucun appel à git, testable tel quel.

    `declaration` porte D'OÙ vient la ligne — vide si personne ne l'a écrite. Un booléen forçait
    le feu vert à toujours dire « la branche fusionnée », y compris quand c'était l'index : le
    module s'interdit ailleurs de faire dire à la porte plus qu'elle ne sait.
    """
    if declaration:
        return True, declaration
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
        f"   {ROADMAP} se déclare source unique de l'ordre du travail.\n"
        "   Qui l'ouvre pour décider de la suite décide sur un état du projet qui n'existe plus.\n\n"
        "   POUR SORTIR, sans annuler la fusion en cours :\n"
        f"     écris leurs lignes — celle de la fusion comprise — dans {ROADMAP},\n"
        "     puis  git add -A  et  git commit.  L'index compte : la ligne écrite ici et\n"
        "     maintenant vaut déclaration.\n\n"
        f"   Si aucun de ces merges n'est un chantier : {GATE_OFF_ENV}=off git commit\n"
        "   (la fusion est DÉJÀ en cours quand tu lis ceci : `git merge` répondrait\n"
        "    « You have not concluded your merge ». Et `--no-verify` ne saute pas\n"
        "    `prepare-commit-msg`, donc il ne désarme pas cette porte.)"
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


def current_branch() -> str:
    """La branche courante, ou la chaîne VIDE si HEAD est détaché.

    UN SEUL appel pour les trois états qui comptent, et c'est ce qui rend la suite sûre :
    `main` attaché → `main` ; HEAD détaché → chaîne vide, rc 0 ; git qui ne répond pas (hors
    dépôt, dépôt illisible) → rc 128, donc `git` lève et le filet refuse en clair.

    C'est la troisième forme de ce contrôle, les deux premières ayant coûté un défaut chacune :
    `symbolic-ref` sortait 128 EN PLEINE FUSION sur un HEAD détaché (trace Python), puis sa
    version tolérante confondait « pas de branche » et « pas de réponse » et rendait un feu vert
    silencieux hors dépôt. Ici la distinction est portée par git, pas par une sonde préalable dont
    seule de la prose garantissait l'ordre.
    """
    return git("branch", "--show-current")


def index_declares() -> bool:
    """La ligne écrite ET indexée MAINTENANT vaut déclaration.

    Sans ça, le refus dictait une remédiation qui ne débloquait rien : la dette regarde
    l'historique, `branch_touches_roadmap` regarde la branche, aucune des deux ne voit ce que
    l'utilisateur vient d'écrire. Il pouvait donc écrire sa ligne, `git add`, `git commit`, et se
    faire refuser à l'identique — au milieu d'une fusion, sans issue (mesuré le 2026-08-12).
    C'est aussi la définition la plus juste de « cette livraison déclare » : ce que le commit en
    train de se faire contient.
    """
    return bool(git("diff", "--cached", "--name-only", "HEAD", "--", ROADMAP))


def merge_heads() -> list[str]:
    """TOUTES les têtes de la fusion en cours ; liste vide si aucune fusion n'est en cours.

    `git rev-parse MERGE_HEAD` n'en rend qu'UNE — la première ligne du fichier. Sur une pieuvre
    (`git merge A B`), la porte jugeait donc `A` seul et refusait une livraison que `B` avait
    déclarée. Le fichier porte une tête par ligne ; `--git-path` donne son emplacement sans
    supposer que le dossier git s'appelle `.git` (worktrees).
    """
    path = ROOT / git("rev-parse", "--git-path", "MERGE_HEAD")
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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

    Ce que la BRANCHE a écrit, pas ce qui diffère entre les deux têtes — sinon tout ce qui a
    avancé sur `main` pendant la vie du chantier lui serait mis au crédit.

    Un `log` d'intervalle, et NON un diff trois points, qui posait la même question mais exigeait
    une base commune : `git diff HEAD...MERGE_HEAD` sort 128 « fatal: no merge base » sur un
    `git merge --allow-unrelated-histories`, et la fusion — déclaration comprise — devenait un
    « contrôle impossible » opaque en pleine opération. L'intervalle ne calcule aucune base.

    Le chemin est passé à git en PATHSPEC plutôt qu'énuméré ici : git s'arrête au premier commit
    qui touche la feuille au lieu d'imprimer tous les fichiers de toute la branche (mesuré sur un
    intervalle de 40 commits : 8,5 ms et une sortie constante, contre 15,1 ms et 8 ko).
    """
    return bool(git("log", "-1", "--format=%H", f"{head}..{other}", "--", ROADMAP))


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    if mode not in ("--merge", "--status"):
        print(__doc__)
        return 2
    if mode == "--merge":
        desarme = os.environ.get(GATE_OFF_ENV, "")
        if desarme:
            # Désarmement VOULU, et dit à voix haute : un contournement silencieux ne se distingue
            # pas d'une porte cassée. TOUTE valeur non vide désarme — exiger `off` à la lettre
            # aurait refusé `=OFF`, `=1`, `=true` sans dire pourquoi, au milieu d'une fusion :
            # c'est la même arête « issue annoncée mais murée » que cette porte a déjà payée deux
            # fois. La valeur reçue est reprise dans le message, pour qu'un désarmement
            # involontaire (variable exportée et oubliée) se voie.
            print(f"↷ feuille de route : porte désarmée par {GATE_OFF_ENV}={desarme}")
            return 0
        # HEAD détaché → chaîne vide, donc « hors `main` » : fusionner là ne livre rien dans
        # `main`. Hors dépôt, `current_branch()` lève et part au filet — la distinction est
        # portée par git lui-même.
        if current_branch() != PROTECTED_BRANCH:
            print("↷ feuille de route : fusion hors `main`, sans objet")
            return 0
        heads = merge_heads()
        if not heads:
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
        # UNE tête qui déclare suffit : la livraison a sa ligne, peu importe laquelle l'apporte.
        # L'index compte au même titre : c'est là qu'atterrit la ligne écrite pour se débloquer.
        # La RAISON est transportée, pas un booléen : le feu vert affirmait « la branche fusionnée
        # met la feuille de route à jour » y compris quand c'était l'index — donc précisément dans
        # le cas où l'utilisateur venait de se débloquer à la main.
        if any(branch_touches_roadmap("HEAD", h) for h in heads):
            declaration = DECLARED_BY_BRANCH
        elif index_declares():
            declaration = DECLARED_BY_INDEX
        else:
            declaration = ""
    else:
        declaration = ""
    # La dette ne se calcule QUE si elle peut servir : deux `git log` de plus sur chaque fusion
    # déjà déclarée, dont `verdict` ne regarde même pas le résultat.
    ok, message = verdict([] if declaration else undeclared_merges("HEAD"), declaration)
    print(f"{'✅' if ok else '❌'} feuille de route : {message}")
    return 0 if ok or mode == "--status" else 1


if __name__ == "__main__":
    try:
        code = main(sys.argv)
    except Exception as exc:  # noqa: BLE001 - filet: une trace de dix lignes ne dit rien à git
        # Ce filet n'AVALE rien : il refuse, dit l'erreur exacte, et laisse la sortie de secours.
        # Le rendre vert masquerait une panne de la porte derrière une fusion réussie (T1).
        # Le stderr de git est LA cause lisible (« fatal: not a git repository ») : sans lui le
        # refus se réduit à « exit status 128 », qui ne dit à personne quoi réparer.
        cause = getattr(exc, "stderr", "")
        dit_par_git = f"   git a dit : {cause.strip()}\n" if cause else ""
        print(
            f"❌ feuille de route : contrôle impossible — {type(exc).__name__}: {exc}\n"
            f"{dit_par_git}"
            "   La porte n'a pas pu se prononcer : le commit est refusé, pas la fusion approuvée.\n"
            "   Si l'état du dépôt est sain, c'est un défaut de la porte elle-même — à corriger\n"
            "   dans scripts/check_roadmap_declared.py.\n"
            f"   Pour passer outre en attendant : {GATE_OFF_ENV}=off git commit  (fusion en cours)\n"
            f"   ou {GATE_OFF_ENV}=off git merge …  si elle n'a pas encore commencé.",
            file=sys.stderr,
        )
        code = 2
    sys.exit(code)
