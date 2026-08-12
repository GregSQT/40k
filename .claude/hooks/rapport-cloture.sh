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
# Python et non bash : la charge utile est un transcript JSONL à parcourir. jq n'est PAS installé
# sur cette machine, et python3 l'est toujours (même constat que deny-verif-large.sh).
#
# Sortie : un `additionalContext` UserPromptSubmit qui énonce ce qui manque — l'agent rend son
# rapport avant de traiter le nouveau prompt. Le prompt de l'utilisateur n'est JAMAIS bloqué.
import json
import os
import re
import sys

CODE_SUFFIXES = (".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}


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
                path_arg = (b.get("input") or {}).get("file_path") or ""
                if path_arg:
                    edited.append(path_arg)
            elif b.get("type") == "text" and entry.get("type") == "assistant":
                text = b.get("text") or ""
                if text.strip():
                    last_text = text
    turns.append((edited, last_text))
    return turns[1:]  # le premier segment précède tout prompt : ce n'est pas un tour


def relire_faults(report, in_worktree):
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

    if in_worktree:
        # Un chemin relatif désigne le fichier du dépôt PRINCIPAL, homonyme mais SANS la
        # modification : la review relirait un chantier étranger (défaut mesuré le 2026-08-08).
        for ln in cmd_lines:
            args = ln.split()[1:]
            if any(not a.startswith("/") for a in args):
                faults.append(
                    "travail fait dans un worktree : tous les chemins du RELIRE doivent être ABSOLUS"
                )
                break
    return faults


def faults_of(turn):
    """Défauts de forme du rapport d'un tour. Liste vide = rien à redire."""
    edited, report = turn
    if not edited:
        return []  # tour de lecture, d'analyse ou de discussion : aucun rapport n'est dû
    faults = []
    for section in ("LU", "JUMEAU"):
        if not re.search(r"^\s*" + section + r"\s*:", report, re.MULTILINE):
            faults.append(f"la ligne {section} est absente (elle est TOUJOURS due)")
    if any(f.endswith(CODE_SUFFIXES) for f in edited):
        faults += relire_faults(report, any("/.claude/worktrees/" in f for f in edited))
    return faults


def main():
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

    faults = faults_of(turns[-1])
    if faults:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": (
                            "Ton tour PRÉCÉDENT a modifié des fichiers sans rapport de clôture "
                            "conforme — " + " ; ".join(faults) + ". Rends ce rapport maintenant, "
                            "en tête de ta réponse, AVANT de traiter la nouvelle demande. Ne "
                            "relance aucun travail : il s'agit seulement de rendre compte de ce "
                            "qui a déjà été fait."
                        ),
                    }
                },
                ensure_ascii=False,
            )
        )
    sys.exit(0)


main()
