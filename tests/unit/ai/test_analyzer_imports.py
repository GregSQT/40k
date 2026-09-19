"""Chaque module de l'analyzer s'importe SEUL, dans un interpréteur neuf.

Mesuré le 2026-09-19 : `python3 -m pytest tests/unit/ai/test_analyzer_hit_result.py` échouait à
la COLLECTE — `ImportError: cannot import name 'WOUND_SEGMENT_PRESENT_RE' from partially
initialized module 'ai.analyzer_hit'`. Le cycle
`analyzer_hit → analyzer_core → analyzer_suppression → analyzer_hit` ne se refermait que lorsque
`ai.analyzer_hit` était le PREMIER module de la chaîne importé ; lancé après n'importe quel autre
fichier de tests analyzer, le même fichier passait. Un défaut qui ne se voit qu'au lancement
isolé est précisément celui qu'une suite complète ne peut pas attraper.

SOUS-PROCESSUS et non `importlib` : dans la session pytest courante, les modules sont déjà dans
`sys.modules` au moment où ce test tourne, si bien qu'un import y réussit quel que soit l'ordre.
Seul un interpréteur neuf rejoue l'ordre qui casse.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

#: Tous les modules de l'analyzer, HANDLERS de `ai/analyzer_phases/` compris : ils participent
#: à la même chaîne d'imports, et un glob resté à la racine les aurait laissés hors du verrou —
#: précisément là où passe le cycle corrigé ici. Découverts et non listés à la main : un module
#: ajouté demain y entre sans que personne ait à y penser.
_RACINE = pathlib.Path(__file__).resolve().parents[3]
_MODULES = sorted(
    {f"ai.{p.stem}" for p in (_RACINE / "ai").glob("analyzer*.py")}
    | {f"ai.analyzer_phases.{p.stem}"
       for p in (_RACINE / "ai" / "analyzer_phases").glob("*.py")
       if p.stem != "__init__"}
)


def test_la_decouverte_trouve_bien_les_modules():
    """VERT VACANT : un glob qui ne trouve rien ferait passer la paramétrisation à vide."""
    assert len(_MODULES) >= 15, _MODULES
    assert "ai.analyzer_hit" in _MODULES
    assert "ai.analyzer_phases.shoot_handler" in _MODULES, (
        "les handlers de phase sont dans la même chaîne d'imports et doivent être couverts"
    )


@pytest.mark.parametrize("module", _MODULES)
def test_le_module_s_importe_seul(module: str):
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=str(pathlib.Path(__file__).resolve().parents[3]),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"`import {module}` échoue dans un interpréteur neuf — import circulaire :\n"
        f"{proc.stderr}"
    )
