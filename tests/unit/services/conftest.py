"""Fixtures partagées des tests d'API Flask.

Depuis la fermeture globale de l'API (`before_request`, faille F6 de
`Documentation/Reference/infra/Security.md`), toute route hors liste blanche exige
un `Authorization: Bearer <token>` valide. Les tests d'endpoints doivent donc disposer
d'une session réelle : la fixture ci-dessous monte une base d'auth temporaire et fait
porter le token par défaut à tout client de test.

`config/users.db` (fichier protégé) est mis hors d'atteinte en amont, par la variable
`W40K_AUTH_DB_PATH` posée dans le `conftest.py` racine : `services.api_server` écrit dans
sa base d'auth dès l'import, donc la redirection doit précéder l'import, pas la fixture.
"""

from __future__ import annotations

import secrets
import sqlite3
import time
from pathlib import Path

import pytest

import services.api_server as api_server


@pytest.fixture(autouse=True)
def authenticated_api_client(monkeypatch, tmp_path: Path):
    """Base d'auth temporaire + token de session porté par défaut par `app.test_client()`.

    Autouse : sans elle, tout appel de test tomberait en 401 et testerait la porte
    d'entrée au lieu de l'endpoint visé.
    """
    db_path = tmp_path / "users_test.db"
    monkeypatch.setattr(api_server, "AUTH_DB_PATH", str(db_path))

    # Schéma + profil + utilisateur créés par le code de production lui-même : le test ne
    # duplique pas le DDL, il casserait silencieusement à la prochaine migration.
    api_server.initialize_auth_db()

    connection = sqlite3.connect(db_path)
    try:
        profile_id = connection.execute(
            "SELECT id FROM profiles WHERE code = ?", ("base",)
        ).fetchone()[0]
        cursor = connection.execute(
            "INSERT INTO users (login, password_hash, profile_id) VALUES (?, ?, ?)",
            ("pytest_user", api_server._hash_password("pytest_password"), profile_id),
        )
        token = secrets.token_urlsafe(48)
        now = int(time.time())
        connection.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, cursor.lastrowid, now, now + api_server.SESSION_TTL_SECONDS),
        )
        connection.commit()
    finally:
        connection.close()

    original_test_client = api_server.app.test_client

    def test_client_with_session(*args, **kwargs):
        client = original_test_client(*args, **kwargs)
        client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return client

    monkeypatch.setattr(api_server.app, "test_client", test_client_with_session)
    return token
