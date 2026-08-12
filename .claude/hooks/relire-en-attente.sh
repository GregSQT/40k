#!/usr/bin/env python3
# PostToolUse (Edit/Write/MultiEdit/NotebookEdit) — tient la liste des fichiers de CODE modifiés
# depuis la dernière relecture, pour la session en cours.
#
# Motif (2026-08-12) : `/code-review` et `/simplify` sont lancés par l'agent en fin de sujet, pas
# par l'utilisateur (cf. puce RELIRE de CLAUDE.md), et un sujet s'étale sur plusieurs tours. Sans
# liste persistée, deux issues, toutes deux mesurées : relancer les deux passes à chaque tour —
# donc plusieurs fois sur le même code, ce que l'utilisateur a demandé d'éviter — ou se fier à la
# mémoire de contexte, qui disparaît à la compaction, c'est-à-dire précisément sur les sessions
# longues où le sujet dure. Le fichier survit à la compaction ET au redémarrage de session.
#
# POURQUOI PAS `git status` — mesuré le 2026-08-12 dans ce dépôt : le tree portait 38 fichiers
# modifiés (analyzer, handlers de phase, une trentaine de tests) alors que la tâche du moment en
# touchait 2. Une liste dérivée de git enverrait la review sur les chantiers des autres sessions.
# Cette liste-ci ne contient que ce que CETTE session a édité.
#
# CE QUE CE HOOK NE FAIT PAS, et ne peut pas faire : décider QUAND lancer les passes. « toutes les
# tâches terminées et plus d'arbitrage en attente » n'est pas observable depuis un hook — aucun
# outil ne sait si la demande de l'utilisateur est finie. Ce déclenchement reste une règle de
# CLAUDE.md ; ici on garantit seulement que la liste est exacte le moment venu.
#
# CE QUI COMPTE COMME CODE N'EST PAS ÉCRIT ICI : la liste est celle de `rapport-cloture.sh`, lue
# dans CLAUDE.md. Deux hooks qui définiraient « du code » chacun de leur côté divergeraient — c'est
# le doublon déjà payé une fois le 2026-08-12 sur la liste des sections du rapport.
#
# LIMITE ASSUMÉE — les éditions faites par un SOUS-AGENT : le payload PostToolUse n'expose aucun
# `isSidechain` (contrairement au transcript que lit `rapport-cloture.sh`), donc elles entrent dans
# la liste comme les autres. C'est le sens sûr de l'erreur : un fichier relu pour rien coûte une
# review, un fichier oublié coûte un bug. Ne pas « corriger » ça en devinant à partir du chemin.
#
# Usage hors hook, pour l'agent :
#   relire-en-attente.sh --liste <session_id>  -> un chemin par ligne, prêt pour le bloc RELIRE
#                                                 (cité s'il porte une espace : la seule forme que
#                                                  `rapport-cloture.sh` accepte pour ces chemins-là)
#   relire-en-attente.sh --vider <session_id>  -> à n'appeler QU'APRÈS avoir lancé les passes
# Le session_id est TOUJOURS requis : plusieurs sessions travaillent en parallèle dans ce dépôt, et
# le déduire des listes présentes revenait à effacer celle d'une autre session quand elle était la
# seule à avoir édité du code (mesuré le 2026-08-12).
import json
import os
import re
import shlex
import sys
from importlib import util
from importlib.machinery import SourceFileLoader

RACINE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DOSSIER = os.path.join(RACINE, ".claude", "relire-en-attente")
VOISIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rapport-cloture.sh")
FORME_UUID = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


_VOISIN_CHARGE = None


def voisin():
    """Le module voisin, chargé UNE fois par processus (il relit CLAUDE.md à chaque `config()`)."""
    global _VOISIN_CHARGE
    if _VOISIN_CHARGE is None:
        _VOISIN_CHARGE = _rapport_cloture()
    return _VOISIN_CHARGE


def _rapport_cloture():
    """Le module voisin, chargé par chemin : son extension `.sh` interdit un import normal.

    Son `main()` s'exécute à l'import. On lui donne un argv nu et un stdin vide : il n'y voit aucun
    payload, sort en silence, et n'écrit RIEN sur notre stdout — que le harnais lit comme du JSON.
    """
    # Loader EXPLICITE : `.sh` n'est pas un suffixe de source reconnu, donc `spec_from_file_location`
    # seul rend un spec sans loader, et l'import échoue sur un `NoneType` sans rapport avec la cause.
    spec = util.spec_from_file_location(
        "rapport_cloture", VOISIN, loader=SourceFileLoader("rapport_cloture", VOISIN)
    )
    module = util.module_from_spec(spec)
    argv, stdin, dwb = sys.argv, sys.stdin, sys.dont_write_bytecode
    # Pas de .pyc : il atterrirait dans `.claude/hooks/__pycache__` à chaque édition, et un cache
    # d'un fichier qu'on relit à chaque appel n'a aucun intérêt ici.
    sys.dont_write_bytecode = True
    sys.argv = [VOISIN]
    with open(os.devnull, encoding="utf-8") as vide:
        sys.stdin = vide
        try:
            spec.loader.exec_module(module)
        except SystemExit:
            pass
        finally:
            sys.argv, sys.stdin, sys.dont_write_bytecode = argv, stdin, dwb
    return module


def est_du_code(chemin):
    """Vrai si ce fichier engage une relecture, selon la SEULE liste du dépôt (CLAUDE.md)."""
    cfg = voisin().config()
    return chemin.endswith(tuple(cfg["code_suffixes"])) or os.path.basename(chemin) in cfg[
        "code_basenames"
    ]


def dans_le_depot(chemin):
    """Appartenance au dépôt, telle que le VOISIN la définit — jamais une seconde définition ici.

    Un script jetable écrit dans le scratchpad est du `.py`, mais le relire n'a aucun sens : il ne
    sera pas livré. Constaté le 2026-08-12 : trois `migrate_*.py` du scratchpad figuraient dans une
    liste de production et seraient partis en review.
    """
    return voisin().dans_le_depot(chemin)


def chemin_note(chemin):
    """Chemin tel qu'il figurera au bloc RELIRE : TOUJOURS absolu.

    Un chemin relatif s'interprète depuis le cwd de la review, qui n'est pas forcément le dépôt où
    l'édition a eu lieu : en session worktree, `CLAUDE.md` relatif désigne la copie du worktree, pas
    celle du dépôt principal qu'on vient de modifier — c'est le défaut mesuré le 2026-08-08, avec un
    verdict entier rendu sur le mauvais code. L'absolu est le seul forme juste dans les deux dépôts,
    et `rapport-cloture.sh` l'exige déjà dès qu'un worktree est en jeu.
    """
    return os.path.abspath(chemin)


def fichier_de_session(session_id):
    return os.path.join(DOSSIER, f"{session_id}.txt")


def fichier_relu(session_id):
    """Instantané de ce que le dernier `--liste` a rendu : ce que `--vider` a le droit d'effacer."""
    return os.path.join(DOSSIER, f"{session_id}.relu")


def lire(fichier):
    """Entrées du fichier, NORMALISÉES à la lecture : absolues, dans le dépôt, dédoublonnées.

    Normaliser aussi ici et pas seulement à l'écriture, pour deux raisons mesurées le 2026-08-12 :
    - les listes déjà écrites par une version antérieure portent des chemins relatifs et des scripts
      jetables du scratchpad ; elles se réparent ainsi sans qu'on touche l'état d'autres sessions ;
    - deux éditions du même fichier dans un même message passent par deux processus concurrents, qui
      lisent tous deux une liste sans l'entrée : le dédoublonnage à l'écriture ne peut pas les voir.
    Une entrée relative est jointe à la RACINE, jamais au cwd du moment : c'est ce qu'elle voulait
    dire quand elle a été écrite.
    """
    try:
        with open(fichier, encoding="utf-8") as fh:
            brutes = [ln.strip() for ln in fh if ln.strip()]
    except FileNotFoundError:
        return []
    absolues = [c if os.path.isabs(c) else os.path.join(RACINE, c) for c in brutes]
    return list(dict.fromkeys(c for c in absolues if dans_le_depot(c)))


def ecrire(fichier, chemins):
    os.makedirs(DOSSIER, exist_ok=True)
    with open(fichier, "w", encoding="utf-8") as fh:
        fh.writelines(c + "\n" for c in chemins)


def ajouter(session_id, chemin):
    """Ajoute le chemin s'il manque. L'ordre d'édition est conservé : il aide à relire le sujet."""
    en_attente = lire(fichier_de_session(session_id))
    if chemin in en_attente:
        return
    os.makedirs(DOSSIER, exist_ok=True)
    with open(fichier_de_session(session_id), "a", encoding="utf-8") as fh:
        fh.write(chemin + "\n")


def emit(context):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": context,
                }
            },
            ensure_ascii=False,
        )
    )


def session_valide(session_id):
    """Le session_id sert de nom de fichier : il ne doit pas pouvoir désigner autre chose.

    Aucune déduction de l'id à partir des listes présentes : « s'il n'y en a qu'une, c'est la
    mienne » est faux dès qu'une session parallèle est la seule à avoir édité du code — mesuré, elle
    se faisait relire puis EFFACER sa liste par une session qui n'avait rien touché.
    """
    if not FORME_UUID.fullmatch(session_id or ""):
        raise ValueError(
            f"session_id invalide : {session_id!r}. Attendu l'UUID seul — dans le chemin de ton "
            "scratchpad, c'est le dossier qui CONTIENT `scratchpad`, pas le dernier composant"
        )
    return session_id


def horodatage(chemin):
    """mtime du fichier, ou None s'il n'existe plus : la version relue, pas seulement son nom."""
    try:
        return os.stat(chemin).st_mtime
    except OSError:
        return None


def commande_liste(session_id):
    """Rend la liste et DATE ce qui a été rendu : `--vider` n'effacera que cette version-là.

    Retenir les seuls NOMS ne suffit pas : la review corrige les fichiers qu'elle relit (`--fix`,
    `/simplify`), donc chaque correction se faisait effacer d'une liste où elle venait de rentrer,
    sans jamais avoir été relue — c'est-à-dire le cas le plus fréquent, pas un cas limite.
    """
    en_attente = lire(fichier_de_session(session_id))
    if not en_attente:
        # Sans ÉNUMÉRER les autres listes : ce serait inviter la devinette que cette conception
        # interdit, et que `--vider` rend destructrice.
        # Ne compte que ce qui appartient VRAIMENT à d'autres sessions : compter les fichiers de
        # la session courante — une liste périmée entièrement filtrée par `lire()`, son `.relu` —
        # envoyait chercher un mauvais id pour un état qui n'a rien d'anormal.
        autres = (
            len({f.split(".")[0] for f in os.listdir(DOSSIER)} - {session_id})
            if os.path.isdir(DOSSIER)
            else 0
        )
        raise ValueError(
            f"aucune liste pour la session {session_id} : id faux, ou liste déjà vidée "
            f"({autres} autre(s) session(s) ont une liste dans {DOSSIER} — ne pas relire la leur)"
        )
    with open(fichier_relu(session_id), "w", encoding="utf-8") as fh:
        json.dump({c: horodatage(c) for c in en_attente}, fh)
    # `shlex.quote` : un chemin à espace existe dans ce dépôt, et le sortir nu donnait une liste que
    # `rapport-cloture.sh` refuse ensuite — le producteur ne produisait alors AUCUNE forme que son
    # contrôleur accepte, donc une réclamation sans issue.
    print("\n".join(shlex.quote(c) for c in en_attente))


def commande_vider(session_id):
    """Retire les entrées relues INCHANGÉES depuis, garde celles que la review a rouvertes."""
    try:
        with open(fichier_relu(session_id), encoding="utf-8") as fh:
            relus = json.load(fh)
    except (FileNotFoundError, ValueError):
        relus = {}
    if not relus:
        raise ValueError(
            f"rien de relu à effacer pour la session {session_id} : `--vider` s'appelle APRÈS un "
            "`--liste` et les passes de relecture"
        )
    reste = [
        c
        for c in lire(fichier_de_session(session_id))
        if c not in relus or horodatage(c) != relus[c]
    ]
    if reste:
        ecrire(fichier_de_session(session_id), reste)
    elif os.path.exists(fichier_de_session(session_id)):
        os.remove(fichier_de_session(session_id))
    os.remove(fichier_relu(session_id))
    if reste:
        # Échappé comme dans `commande_liste` : ce reste s'écrit tel quel dans le prochain RELIRE,
        # et le sortir nu redonnait un chemin à espace que `rapport-cloture.sh` refuse.
        print("\n".join(shlex.quote(c) for c in reste))


def main():
    argument = sys.argv[1:2]
    if argument:
        # TOUT argument engage la ligne de commande, pas seulement ceux qui commencent par `-` :
        # `relire-en-attente.sh <uuid>`, flag oublié, tombait dans le chemin PostToolUse et sortait
        # 0 avec stdout vide — soit « rien à relire » alors que la liste était pleine.
        commandes = {"--liste": commande_liste, "--vider": commande_vider}
        if argument[0] not in commandes:
            sys.exit(f"{argument[0]} : flag inconnu, attendu --liste ou --vider <session_id>")
        try:
            commandes[argument[0]](session_valide(sys.argv[2] if sys.argv[2:3] else ""))
        except (OSError, ValueError) as err:
            sys.exit(str(err))
        sys.exit(0)

    try:
        payload = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)

    # `NotebookEdit` nomme son argument `notebook_path` : ne lire que `file_path` laissait une
    # édition de notebook hors de la liste, donc hors relecture.
    entree = payload.get("tool_input") or {}
    chemin = entree.get("file_path") or entree.get("notebook_path") or ""
    if not chemin:
        sys.exit(0)

    session_id = payload.get("session_id")
    if not session_id:
        # Se taire ici perdrait la liste sans que rien ne le signale, et l'agent croirait la
        # relecture à jour. On le DIT plutôt que d'écrire dans un fichier fourre-tout (T1).
        emit(
            "La liste des fichiers à relire ne peut pas être tenue : le payload du hook "
            "`relire-en-attente.sh` ne porte pas de `session_id`. Signale-le, et tiens la liste "
            "à la main pour ce sujet."
        )
        sys.exit(0)

    try:
        # Même contrôle qu'en ligne de commande : l'id NOMME le fichier de liste. Non validé ici, un
        # id fantaisiste écrivait une liste que `--liste` refuse ensuite de lire (donc une relecture
        # perdue), et `../../..` écrivait hors du dossier des listes.
        session_valide(session_id)
        if dans_le_depot(chemin) and est_du_code(chemin):
            ajouter(session_id, chemin_note(chemin))
    # `except Exception` et non une liste de types : le voisin est CHARGÉ ici, donc une coquille
    # dedans lève ce qu'elle veut (SyntaxError, ImportError…) — et ça arrive précisément sur les
    # tours qui l'éditent. Un traceback nu sortirait rc=1 sans rien dire à l'agent, et l'édition
    # disparaîtrait de la liste en silence. On ne masque rien : on le DIT (T1).
    except Exception as err:  # noqa: BLE001
        emit(
            f"La liste des fichiers à relire n'a pas pu être mise à jour ({type(err).__name__}: "
            f"{err}). Tant que ce n'est pas réparé, le bloc RELIRE doit être écrit à la main."
        )
    sys.exit(0)


main()
