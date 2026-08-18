#!/usr/bin/env python3
# PreToolUse/Edit|Write|MultiEdit|NotebookEdit — bloque l'écriture de fichiers code dans main.
#
# Motif : les agents glissent de l'analyse vers l'écriture sans ouvrir de worktree, laissant des
# fichiers non commités dans main. Ce hook bloque ce glissement au moment précis du premier write.
#
# Fichiers code = extensions listées dans CLAUDE.md + CLAUDE.md lui-même + settings.json.
# En worktree → laisse passer. Dans main → refuse, avec les étapes à suivre.
#
# Pas de porte de sortie (marqueur, variable d'env, fichier jeton) : un agent peut les produire
# lui-même. Seule exception réelle : l'utilisateur travaille dans main explicitement — dans ce cas
# il accepte le prompt de permission qui apparaît.
import json
import os
import subprocess
import sys

CODE_EXTENSIONS = ('.py', '.pyi', '.sh', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')
CODE_BASENAMES = {'CLAUDE.md', 'settings.json'}


def is_code_file(path: str) -> bool:
    if os.path.basename(path) in CODE_BASENAMES:
        return True
    return any(path.endswith(ext) for ext in CODE_EXTENSIONS)


def is_in_main_worktree() -> bool:
    try:
        current = subprocess.check_output(
            ['git', 'rev-parse', '--show-toplevel'],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        result = subprocess.check_output(
            ['git', 'worktree', 'list', '--porcelain'],
            text=True, stderr=subprocess.DEVNULL
        )
        worktrees = [
            line[len('worktree '):] for line in result.splitlines()
            if line.startswith('worktree ')
        ]
        if not worktrees:
            return True
        return os.path.abspath(current) == os.path.abspath(worktrees[0])
    except Exception:
        return True  # fail safe : bloquer si indéterminé


def main():
    try:
        data = json.load(sys.stdin)
        file_path = data.get('tool_input', {}).get('file_path', '')
    except Exception:
        return

    if not file_path or not is_code_file(file_path):
        return

    if not is_in_main_worktree():
        return

    filename = os.path.basename(file_path)
    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': (
                f"REFUSÉ : '{filename}' est un fichier code et tu es dans main. "
                "Avant toute écriture : 1) git status --short, "
                "2) EnterWorktree <nom-du-sujet>, "
                "3) écrire depuis le worktree. "
                "Si tu as commencé en lecture/analyse et bascules vers l'écriture, "
                "ouvre le worktree maintenant, avant ce write."
            ),
        }
    }, ensure_ascii=False))


main()
