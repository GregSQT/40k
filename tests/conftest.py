import atexit
import os
import random
import shutil
import sys
import tempfile

# AVANT tout import de `services.api_server` : ce module appelle `initialize_auth_db()` à
# l'import, qui ÉCRIT dans `AUTH_DB_PATH`. Sans cette redirection, lancer les tests
# modifierait `config/users.db` — fichier protégé (CLAUDE.md). `conftest.py` racine est
# chargé par pytest avant les modules de test, donc avant cet import.
#
# La clé est le WORKER, pas le process : sous `pytest -n 8`, le contrôleur pose la variable
# et les workers en HÉRITENT par l'environnement — un simple `if not in os.environ` les
# ferait donc tous retomber sur le même fichier SQLite, et exécuter `initialize_auth_db()`
# dessus en concurrence (le `database is locked` que l'on veut précisément éviter). On
# suffixe donc par `PYTEST_XDIST_WORKER`, seul discriminant fiable entre workers.
#
# Le répertoire est créé par `mkdtemp` (0700, nom imprévisible) : un chemin devinable dans
# `/tmp`, world-writable, permettrait d'y placer un lien symbolique vers `config/users.db`
# et d'annuler exactement la protection recherchée.
_xdist_worker = os.environ.get("PYTEST_XDIST_WORKER")
_auth_db_path = os.environ.get("W40K_AUTH_DB_PATH")
if _auth_db_path is None or _xdist_worker is not None:
    _auth_db_dir = tempfile.mkdtemp(prefix=f"w40k_pytest_auth_{_xdist_worker or 'main'}_")
    os.environ["W40K_AUTH_DB_PATH"] = os.path.join(_auth_db_dir, "users.db")
    atexit.register(shutil.rmtree, _auth_db_dir, True)

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def deterministic_seed() -> None:
    seed = 12345
    random.seed(seed)
    np.random.seed(seed)
    # `torch` est semé s'il est DÉJÀ chargé, jamais importé pour l'occasion : cet import coûte
    # 4,9 s (mesuré) que CHAQUE worker xdist payait au démarrage — sur `tests/integration/pvp/`,
    # où aucun test ne touche au RL, c'étaient 4,9 s x 6 workers intégralement perdus.
    # Aucun test n'y perd sa graine : pytest importe TOUS les modules de test à la collecte,
    # donc avant le premier setup de fixture — un fichier qui importe torch au niveau module
    # (`tests/unit/ai/test_pointer_head.py`, `test_entity_encoder_extractor.py`) l'a déjà mis
    # dans `sys.modules` quand cette ligne s'exécute. Seul un `import torch` dans le CORPS d'un
    # test arriverait trop tard : grep vérifié, aucun test de ce dépôt ne le fait.
    torch = sys.modules.get("torch")
    if torch is not None:
        torch.manual_seed(seed)
        # Même règle que ci-dessus : on n'importe pas torch pour l'occasion, on profite de
        # ce qu'il est déjà là. S'il l'est, un test peut charger un modèle — or torch >= 2.6
        # charge en `weights_only=True` et refuse les scalaires numpy des checkpoints sb3.
        # Les tests qui appellent `MaskablePPO.load`/`load_from_zip_file` DIRECTEMENT ne
        # passent par aucun module de `ai/`, donc par aucune autre inscription.
        from shared.torch_safe_globals import register_torch_safe_globals

        register_torch_safe_globals()
