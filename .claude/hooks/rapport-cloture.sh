#!/usr/bin/env python3
# UserPromptSubmit — vérifie la FORME du rapport de clôture du tour PRÉCÉDENT quand celui-ci a
# modifié des fichiers.
#
# Motif (2026-08-12) : CLAUDE.md prescrivait la présence de LU/JUMEAU/RELIRE et la disposition du
# bloc RELIRE par une vingtaine de lignes de texte. Une règle qui ne vit que dans le prompt échoue
# EN SILENCE, et elle échoue au pire moment : session longue, contexte dilué, c'est-à-dire quand la
# sortie n'est plus relue. Le cas le plus coûteux est déjà mesuré : le 2026-08-08, un RELIRE écrit
# en chemins RELATIFS pour un travail fait dans un worktree a envoyé une review entière — findings
# compris — sur le code du dépôt principal, sans que rien ne le signale.
#
# POURQUOI CE HOOK N'EST PAS UN HOOK Stop — mesuré le 2026-08-12, deux fois :
#   1. Le transcript est écrit de façon ASYNCHRONE : à l'instant où un hook Stop s'exécute, le
#      dernier message de l'assistant n'y figure pas encore.
#   2. Pire, ce qui y figure n'est pas RIEN : les textes intermédiaires du tour (« je commence
#      par… ») sont déjà écrits. Un hook Stop prend donc une phrase de narration de mi-parcours
#      pour le rapport final, et bloque un tour parfaitement conforme. Attendre n'y change rien —
#      l'attente se termine immédiatement, puisqu'un texte non vide est déjà présent.
#   Constaté en production : la première version de ce hook, branchée sur Stop, a bloqué le tour
#   même qui l'installait, en réclamant trois sections que le message contenait.
# Au prompt suivant, le transcript est complet et le dernier texte du tour précédent EST son
# message final. Le contrôle arrive un tour plus tard, mais il ne se trompe pas. Un contrôle qui
# regarde la mauvaise chose est pire qu'un contrôle en retard.
#
# PARTAGE DES RÔLES, à respecter si ce hook évolue :
#   - le hook garde la FORME (présence d'une section, disposition, nature des chemins) ;
#   - CLAUDE.md garde la SUBSTANCE (ce que LU doit contenir, pourquoi JUMEAU existe, quand PROMPTS
#     est dû). Rien de tout ça n'est mécaniquement vérifiable, donc rien de tout ça n'entre ici.
#
# LA CONFIGURATION N'EST PAS ÉCRITE ICI — les sections exigées et les fichiers qui comptent comme
# du code sont LUS dans les deux lignes déclaratives de CLAUDE.md (puce « FORME DU RAPPORT »).
# Motif mesuré le 2026-08-12 : la liste des sections existait en deux exemplaires indépendants,
# l'ajout de COUVERTURE au hook a laissé la puce énumérer LU/JUMEAU/RELIRE, et un agent qui s'y
# fiait se faisait réclamer une section absente de la liste qu'il venait de lire. Une source
# unique, et `--config` pour que le test la lise PAR le hook au lieu de reparser CLAUDE.md.
#
# Python et non bash : la charge utile est un transcript JSONL à parcourir. jq n'est PAS installé
# sur cette machine, et python3 l'est toujours (même constat que deny-verif-large.sh).
#
# Sortie : un `additionalContext` UserPromptSubmit qui énonce ce qui manque — l'agent rend son
# rapport avant de traiter le nouveau prompt. Le prompt de l'utilisateur n'est JAMAIS bloqué.
import json
import os
import re
import sys

EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# Ce que `/code-review` et `/simplify` acceptent en plus des chemins : niveaux d'effort et options.
# Un numéro de PR est reconnu à part (chiffres seuls). Tout le reste est un chemin, donc à vérifier.
ARGS_NON_CHEMIN = {
    "low", "medium", "high", "xhigh", "max", "ultra",
    "--fix", "--comment", "--post", "--no-post",
}

RACINE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CLAUDE_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "CLAUDE.md")
LIGNE_SECTIONS = re.compile(r"^\s*SECTIONS EXIGÉES\s*:\s*(.+)$", re.MULTILINE)
ITEM_SECTION = re.compile(r"`([A-ZÉÈÀÂÎÔÛÇ]+)`\s*=\s*(toujours|code)")
LIGNE_CODE = re.compile(r"^\s*FICHIERS COMPTÉS COMME CODE\s*:\s*(.+)$", re.MULTILINE)
ITEM_CODE = re.compile(r"`([^`\s]+)`")


def _items(texte, ligne_motif, item_motif, etiquette, claude_md):
    """Items d'une ligne déclarative de CLAUDE.md — la seule façon dont ce hook se configure.

    Toute anomalie lève, y compris PARTIELLE et surtout partielle : une entrée qui perd ses
    backticks ou une liste repliée sur deux lignes ferait disparaître RELIRE en silence, donc le
    contrôle des chemins absolus en worktree (défaut du 2026-08-08). Un garde-fou muet est
    indistinguable d'un tour conforme (T1), donc on préfère l'erreur bruyante.

    Chaque morceau séparé par une virgule doit correspondre ENTIÈREMENT à un item : ni résidu, ni
    virgule finale, ni entrée collée à sa voisine. Reste le repli non ponctué, que rien sur la
    ligne ne trahit : on regarde si la ligne IMMÉDIATEMENT suivante commence par un item. Borné
    là EXPRÈS — balayer tout le fichier ferait mourir le hook sur une mention illustrative écrite
    ailleurs dans CLAUDE.md, avec en prime un diagnostic faux.
    """
    lignes = list(ligne_motif.finditer(texte))
    if not lignes:
        raise ValueError(f"aucune ligne `{etiquette} :` dans {claude_md}")
    if len(lignes) > 1:
        raise ValueError(
            f"{len(lignes)} lignes `{etiquette} :` dans {claude_md} : la source doit rester "
            "unique, sinon les suivantes ne commandent plus rien"
        )
    ligne = lignes[0]
    items = []
    for morceau in ligne.group(1).strip().split(","):
        morceau = morceau.strip()
        if not morceau:
            raise ValueError(
                f"entrée vide dans `{etiquette} :` — virgule en trop, ou liste repliée ?"
            )
        reconnu = item_motif.fullmatch(morceau)
        if not reconnu:
            raise ValueError(f"entrée non reconnue dans `{etiquette} :` : {morceau!r}")
        items.append(reconnu.groups())
    # Un repli COMMENCE par un item, donc par un backtick : c'est ce qui le distingue d'une ligne
    # voisine qui en cite un (l'autre ligne déclarative, une glose entre parenthèses, une puce).
    # Chercher un item n'importe où sur la ligne suivante suffisait à faire mourir les deux
    # garde-fous sur un CLAUDE.md conforme, selon l'ordre où ses lignes sont écrites.
    # Deux amorces possibles pour une continuation : l'item lui-même (backtick) ou la virgule qui le
    # relie au précédent. Une prose qui CITE un item sans commencer par l'un des deux n'en est pas
    # une, et rien ne permet de l'en distinguer — c'est la limite assumée de ce contrôle.
    suivante = [
        ln for ln in texte[ligne.end():].split("\n")[1:2] if ln.lstrip()[:1] in ("`", ",")
    ]
    if suivante and item_motif.search(suivante[0]):
        raise ValueError(
            f"la liste `{etiquette} :` doit tenir sur UNE ligne, elle se poursuit sur la "
            "suivante : " + suivante[0].strip()
        )
    return items


def config(claude_md=CLAUDE_MD):
    """Config du hook, LUE dans CLAUDE.md — jamais écrite ici : une seule source, celle qu'on lit.

    `sections` : (nom, portée) des sections du rapport. Portée `toujours` = due sur tout tour qui
    a modifié un fichier ; `code` = due seulement si un fichier de code a bougé. Les fichiers qui
    comptent comme du code sont déclarés de la même façon — un suffixe, ou un nom entier pour les
    fichiers qui pilotent les hooks et dont la modification peut les éteindre.
    """
    with open(claude_md, encoding="utf-8") as fh:
        texte = fh.read()
    fichiers = [
        item for (item,) in _items(texte, LIGNE_CODE, ITEM_CODE, "FICHIERS COMPTÉS COMME CODE",
                                   claude_md)
    ]
    return {
        "sections": [list(s) for s in _items(texte, LIGNE_SECTIONS, ITEM_SECTION,
                                             "SECTIONS EXIGÉES", claude_md)],
        "code_suffixes": [f for f in fichiers if f.startswith(".")],
        "code_basenames": [f for f in fichiers if not f.startswith(".")],
    }


def dans_le_depot(chemin):
    """Vrai si le fichier appartient au dépôt — worktrees inclus, ils vivent sous `.claude/`.

    Défini ICI et utilisé aussi par `relire-en-attente.sh`, qui charge ce module : les deux hooks
    doivent s'accorder sur ce qui est du travail livrable, sinon l'un réclame une relecture que
    l'autre refuse d'inscrire dans sa liste.
    """
    return os.path.abspath(chemin).startswith(RACINE + os.sep)


def blocks(entry):
    """Blocs de contenu d'une entrée de transcript, [] si l'entrée n'en porte pas."""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def is_real_user_prompt(entry):
    """Vrai message de l'utilisateur, par opposition aux entrées `type: user` du harnais.

    Un retour d'outil est écrit dans le transcript comme une entrée `type: user` portant un bloc
    `tool_result` : le confondre avec un prompt découperait un tour en morceaux, et le morceau
    final — celui qui porte le rapport — masquerait tout ce qui a été modifié avant lui.
    """
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    bs = blocks(entry)
    if not bs:
        return False
    return not any(b.get("type") == "tool_result" for b in bs)


def read_turns(path):
    """Découpe le transcript en tours : [(fichiers modifiés, dernier texte assistant), ...].

    Le DERNIER texte et non le premier : les textes intermédiaires d'un tour ne sont pas son
    rapport, et c'est en les confondant avec lui qu'un contrôle branché sur Stop se trompe.
    """
    entries = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            # Les sous-agents écrivent dans le même transcript : leurs éditions et leurs messages
            # ne sont pas le rapport du tour principal.
            if isinstance(entry, dict) and not entry.get("isSidechain"):
                entries.append(entry)

    turns, edited, last_text = [], [], ""
    for entry in entries:
        if is_real_user_prompt(entry):
            turns.append((edited, last_text))
            edited, last_text = [], ""
            continue
        for b in blocks(entry):
            if b.get("type") == "tool_use" and b.get("name") in EDIT_TOOLS:
                # `NotebookEdit` nomme son argument `notebook_path` : ne lire que `file_path`
                # laissait un tour qui n'édite qu'un notebook passer pour un tour sans modification.
                entree = b.get("input") or {}
                path_arg = entree.get("file_path") or entree.get("notebook_path") or ""
                if path_arg:
                    edited.append(path_arg)
            elif b.get("type") == "text" and entry.get("type") == "assistant":
                text = b.get("text") or ""
                if text.strip():
                    last_text = text
    turns.append((edited, last_text))
    return turns[1:]  # le premier segment précède tout prompt : ce n'est pas un tour


def relire_faults(report):
    """Défauts de forme du bloc RELIRE. Liste vide = conforme."""
    lines = report.splitlines()
    labels = [ln for ln in lines if re.match(r"^\s*RELIRE\s*:", ln)]
    if not labels:
        return ["la section RELIRE est absente"]

    faults = []
    if not any(re.match(r"^\s*RELIRE\s*:\s*$", ln) for ln in labels):
        faults.append(
            "l'étiquette `RELIRE :` doit être SEULE sur sa ligne, la première commande sur la suivante"
        )

    cmd_lines = [ln for ln in lines if re.match(r"^\s*/(code-review|simplify)\b", ln)]
    for name in ("code-review", "simplify"):
        if not any(re.match(r"^\s*/" + name + r"\b", ln) for ln in cmd_lines):
            faults.append(f"`/{name}` doit être seul en début de sa propre ligne")

    # Chemins ABSOLUS, sans condition. La version d'avant n'exigeait l'absolu que si un fichier
    # ÉDITÉ vivait sous `.claude/worktrees/` : une session worktree qui ne touche que le dépôt
    # principal — CLAUDE.md, les hooks, cas fréquent — y échappait, et son `/code-review CLAUDE.md`
    # relatif se résolvait sur la copie du worktree, c'est-à-dire le défaut du 2026-08-08 intact.
    # Où l'on est n'est pas observable ici ; l'absolu est juste partout, donc on l'exige partout.
    for ln in cmd_lines:
        # Tout argument est un chemin SAUF ce que ces commandes acceptent d'autre — liste fermée,
        # donc décidable. Trier « ça ressemble à un chemin » ne l'est pas : `engine` (un répertoire
        # relatif, sans point ni slash) passait, et le défaut du 2026-08-08 restait ouvert.
        chemins = [a for a in ln.split()[1:] if a not in ARGS_NON_CHEMIN and not a.isdigit()]
        relatifs = [a for a in chemins if not a.startswith("/")]
        if relatifs:
            faults.append(
                "tous les chemins du bloc RELIRE doivent être ABSOLUS — vu : "
                + ", ".join(relatifs[:3])
                + " (le verdict d'une passe se met sur la ligne `→`, pas sur la commande)"
            )
            break
    return faults


def faults_of(turn, cfg):
    """Défauts de forme du rapport d'un tour. Liste vide = rien à redire."""
    edited, report = turn
    if not edited:
        return []  # tour de lecture, d'analyse ou de discussion : aucun rapport n'est dû
    # `dans_le_depot` compte autant que le suffixe : un script de sonde jetable écrit dans le
    # scratchpad est du `.py` mais ne sera pas livré. Sans ce filtre, RELIRE était réclamée pour lui
    # alors que `relire-en-attente.sh` l'exclut de sa liste — les deux hooks se contredisaient sur
    # tout tour qui instrumente quelque chose.
    du_code = any(
        dans_le_depot(f)
        and (f.endswith(tuple(cfg["code_suffixes"])) or os.path.basename(f) in cfg["code_basenames"])
        for f in edited
    )
    faults = []
    for name, portee in cfg["sections"]:
        if portee == "code" and not du_code:
            continue
        if name == "RELIRE":
            # Seule section dont la forme INTERNE est vérifiable : son absence y est déjà dite.
            faults += relire_faults(report)
            continue
        if not re.search(r"^\s*" + name + r"\s*:", report, re.MULTILINE):
            due = (
                "elle est TOUJOURS due"
                if portee == "toujours"
                else "due dès qu'un fichier de code a bougé"
            )
            faults.append(f"la ligne {name} est absente ({due})")
    return faults


def emit(context):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            },
            ensure_ascii=False,
        )
    )


def main():
    if sys.argv[1:2] and sys.argv[1] != "--config":
        # Sans ça, un flag mal tapé tombe dans le chemin transcript et sort 0 sans rien dire :
        # exactement le garde-fou muet que ce fichier existe pour éviter (même règle chez le voisin).
        sys.exit(f"{sys.argv[1]} : flag inconnu, attendu --config")

    if sys.argv[1:2] == ["--config"]:
        # Le test lit la config PAR le hook, pas en reparsant CLAUDE.md de son côté : reparser
        # recréerait le deuxième exemplaire que cette source unique supprime.
        print(json.dumps(config(), ensure_ascii=False))
        sys.exit(0)

    try:
        payload = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)

    transcript = payload.get("transcript_path")
    if not transcript or not os.path.exists(transcript):
        sys.exit(0)

    try:
        turns = read_turns(transcript)
    except OSError:
        sys.exit(0)

    # Le prompt qui vient d'être soumis peut déjà figurer au transcript et ouvrir un tour vide :
    # le tour à juger est le dernier qui porte réellement quelque chose.
    while turns and not turns[-1][0] and not turns[-1][1]:
        turns.pop()
    if not turns:
        sys.exit(0)

    try:
        cfg = config()
    except (OSError, ValueError) as err:
        # Se taire ici rendrait le garde-fou muet sans que rien ne le signale (T1) : on le DIT.
        emit(
            "Le contrôle de forme du rapport de clôture ne peut pas lire sa configuration dans "
            f"CLAUDE.md ({err}). Signale-le : tant que ce n'est pas réparé, plus rien ne vérifie "
            "la forme du rapport."
        )
        sys.exit(0)

    faults = faults_of(turns[-1], cfg)
    if faults:
        emit(
            "Ton tour PRÉCÉDENT a modifié des fichiers sans rapport de clôture conforme — "
            + " ; ".join(faults)
            + ". Rends ce rapport maintenant, en tête de ta réponse, AVANT de traiter la "
            "nouvelle demande. Ne relance aucun travail : il s'agit seulement de rendre compte "
            "de ce qui a déjà été fait."
        )
    sys.exit(0)


main()
