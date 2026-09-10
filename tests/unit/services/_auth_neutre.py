r"""Neutralisation de la fixture d'auth `autouse` pour les modules qui ne touchent pas l'API.

`tests/unit/services/conftest.py` déclare `authenticated_api_client` en `autouse` : sans elle,
tout test d'endpoint tomberait en 401 et testerait la porte d'entrée au lieu de l'endpoint visé.
Le prix est payé par CHAQUE test du dossier — le DDL complet de la base d'auth
(`initialize_auth_db`) plus un hash pbkdf2 — soit 0,19 à 0,32 s de setup par test, mesuré avec
`pytest --durations`, contre 0,01 s d'exécution sur les modules concernés ici.

Sept modules du dossier n'appellent jamais `app.test_client()` ni `services.api_server` (relevé :
`grep -L 'test_client\|api_server' tests/unit/services/test_*.py`). Ils importent la fixture
ci-dessous, qui porte le MÊME nom et masque donc celle du conftest, sans rien monter.

⚠️ Si un test de l'un de ces modules se met à appeler l'API, il tombera en 401 : la réponse est
de RETIRER l'import dans ce module, pas de contourner le refus — c'est exactement le signal que
le module a changé de nature.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def authenticated_api_client() -> None:
    """Masque la fixture d'auth du conftest : ce module ne parle pas à l'API Flask."""
    return None
