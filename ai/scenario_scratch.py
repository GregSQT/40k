"""Répertoire de travail des scénarios MATÉRIALISÉS (override de `wall_ref`). Module feuille.

Un scénario matérialisé est celui que l'épisode joue RÉELLEMENT, murs réécrits compris.
`W40KEngine.reset` journalise son chemin RELATIF à la racine du dépôt — c'est ce que le replay
repasse à `/api/config/board` pour dessiner le décor de cet épisode-là, information qu'aucune
autre ligne du journal ne porte. Journaliser le scénario d'ORIGINE à la place serait faux : ses
murs ne sont pas ceux joués.

DEUX contraintes, et elles ne sont satisfaites qu'ensemble :

1. **Sous `config/`.** `/api/config/board` refuse tout `scenario_file` hors de ce répertoire
   (`services/api_server.py`, « scenario_file must be under config/ »). Un scénario écrit dans
   `/tmp` faisait refuser l'épisode par le moteur ; l'écrire ailleurs sous le dépôt le faisait
   passer, mais le replay répondait alors 500 au chargement du décor. On écrit donc dans
   `config/local/`, déjà gitignoré et hors de l'énumération des agents.

2. **Survivre au processus.** Le replay est ouvert APRÈS le run. Un nettoyage `atexit` effaçait
   le fichier avant que quiconque puisse le lire. La purge se fait donc à la CRÉATION, sur les
   répertoires d'anciens runs, jamais sur celui du run en cours.

Deux appelants sans chemin d'import entre eux (`ai/bot_evaluation.py` pour l'éval,
`ai/train.py` pour l'entraînement) matérialisaient chacun dans `/tmp` : la contrainte vit ici
plutôt qu'en double.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time

# `config/local/` est gitignoré (.gitignore) et n'est enumeré par aucun chargeur de config.
_SCRATCH_SUBPATH = os.path.join("config", "local", "scenario_scratch")

# Les scénarios du run PRÉCÉDENT restent lisibles par le replay ; au-delà, ils ne servent plus
# personne. Purge à la création, pas à la sortie — un `atexit` détruirait le run qu'on vient de
# jouer. Un run parallèle plus jeune que ce seuil n'est jamais touché.
_STALE_AFTER_SECONDS = 24 * 3600


def repo_root() -> str:
    """Racine du dépôt — MÊME dérivation que `engine.w40k_core.repo_relative_scenario_path`."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _purge_stale(scratch_root: str) -> None:
    """Efface les répertoires de travail des runs révolus. Silencieux sur un répertoire déjà
    disparu ou en cours d'écriture par un autre processus : ce n'est pas une erreur métier."""
    now = time.time()
    for name in os.listdir(scratch_root):
        path = os.path.join(scratch_root, name)
        if not os.path.isdir(path):
            continue
        try:
            if now - os.path.getmtime(path) > _STALE_AFTER_SECONDS:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def make_scenario_scratch_dir(prefix: str) -> str:
    """Crée un répertoire de travail sous `config/local/` et purge ceux des runs révolus."""
    scratch_root = os.path.join(repo_root(), _SCRATCH_SUBPATH)
    os.makedirs(scratch_root, exist_ok=True)
    _purge_stale(scratch_root)
    return tempfile.mkdtemp(prefix=prefix, dir=scratch_root)
