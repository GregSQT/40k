#!/usr/bin/env python3
"""PostToolUse — lance check_doc_references.py après toute édition d'un fichier Documentation/Roadmap/.

Déclenché sur Edit|Write|MultiEdit|NotebookEdit ; la sélection par chemin se fait ici.
Émet les erreurs en additionalContext si le script sort en code 1 ; silence sinon.
"""
import json
import os
import subprocess
import sys

RACINE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ROADMAP = os.path.join(RACINE, "Documentation", "Roadmap")


def emit(context: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        }
    }, ensure_ascii=False))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)

    entree = payload.get("tool_input") or {}
    chemin = entree.get("file_path") or entree.get("notebook_path") or ""
    if not chemin:
        sys.exit(0)

    chemin_abs = chemin if os.path.isabs(chemin) else os.path.abspath(chemin)
    roadmap_abs = os.path.abspath(ROADMAP)
    if not chemin_abs.startswith(roadmap_abs + os.sep):
        sys.exit(0)

    venv_python = os.path.join(RACINE, ".venv", "bin", "python3")
    python = venv_python if os.path.exists(venv_python) else sys.executable
    script = os.path.join(RACINE, "scripts", "check_doc_references.py")

    result = subprocess.run(
        [python, script],
        cwd=RACINE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    if result.returncode != 0:
        # Seules les lignes d'erreur, pas le rapport complet : les ✅ et les compteurs ne sont
        # pas de l'information actionnelle pour l'agent.
        _ERROR_MARKERS = (
            "❌", "INTROUVABLE", "MORT", "PÉRIMÉE", "ORPHELIN", "ABSENT", "FAUSSE",
            "NON DÉFINI", "NON LISTÉ", "ORPHELINE", "ANCRE DE LIGNE",
        )
        lines = (result.stdout + result.stderr).splitlines()
        errors = [ln for ln in lines if any(m in ln for m in _ERROR_MARKERS)]
        summary = "\n".join(errors) if errors else (result.stdout + result.stderr).strip()
        emit(
            f"check_doc_references.py après l'édition de "
            f"{os.path.relpath(chemin_abs, RACINE)} :\n{summary}"
        )

    sys.exit(0)


main()
