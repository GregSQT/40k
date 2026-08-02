import atexit
import os
import random
import shutil
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

try:
    import torch
except ImportError:  # pragma: no cover
    torch = None


@pytest.fixture(autouse=True)
def deterministic_seed() -> None:
    seed = 12345
    random.seed(seed)
    np.random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)
