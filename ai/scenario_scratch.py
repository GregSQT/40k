"""Répertoire de travail des scénarios MATÉRIALISÉS (override de `wall_ref`). Module feuille.

Un scénario matérialisé est celui que l'épisode joue RÉELLEMENT, murs réécrits compris.
`W40KEngine.reset` journalise son chemin RELATIF à la racine du dépôt — c'est ce que le replay
repasse à `/api/config/board` pour dessiner le décor de cet épisode-là, information qu'aucune
autre ligne du journal ne porte. Un scénario écrit dans `/tmp` n'a pas de chemin relatif
exprimable : le moteur refuse l'épisode (« Scenario file hors du dépôt, non journalisable pour
le replay ») et l'évaluation meurt au premier reset dès que le step logging est actif.

Journaliser le scénario d'ORIGINE à la place serait faux : ses murs ne sont pas ceux joués, et
c'est précisément le défaut que ce chemin de log corrige. Le contrôle miroir, côté consommateur,
est `engine.w40k_core.repo_relative_scenario_path`.

Deux appelants sans chemin d'import entre eux (`ai/bot_evaluation.py` pour l'éval,
`ai/train.py` pour l'entraînement) matérialisaient chacun dans `/tmp` : la contrainte vit ici
plutôt qu'en double.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

# `tmp/` est gitignoré à la racine du dépôt (.gitignore). Nettoyé à la sortie du processus.
_SCRATCH_DIRNAME = "tmp"


def repo_root() -> str:
    """Racine du dépôt — MÊME dérivation que `W40KEngine.reset` pour son chemin relatif."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_scenario_scratch_dir(prefix: str) -> str:
    """Crée un répertoire de travail SOUS la racine du dépôt et l'enregistre au nettoyage.

    L'appelant garde la responsabilité de ne le créer qu'une fois (globale + `atexit` de son
    côté s'il veut un répertoire unique par processus)."""
    scratch_root = os.path.join(repo_root(), _SCRATCH_DIRNAME)
    os.makedirs(scratch_root, exist_ok=True)
    path = tempfile.mkdtemp(prefix=prefix, dir=scratch_root)
    atexit.register(lambda: shutil.rmtree(path, ignore_errors=True))
    return path
