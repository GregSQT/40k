"""Durcissement des sessions et rate limiting du login (F2, F8) — `Documentation/Implémentation/Security.md`.

Verrouille quatre invariants :
1. une session échue n'authentifie plus (avant : `WHERE s.token = ?` seul, token valide à vie) ;
2. une session vivante voit son échéance repoussée, mais SANS écrire à chaque requête ;
3. le login se ferme après `LOGIN_ATTEMPT_MAX_FAILURES` échecs dans la fenêtre ;
4. le logout révoque immédiatement, sans attendre l'expiration.

Chaque test CONSTRUIT l'état qu'il observe (échéance forcée en SQL, échecs répétés
réellement émis) : rien n'est espéré d'un ordre d'exécution ou d'une horloge.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

import services.api_server as api_server
from services.api_server import app


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(api_server.AUTH_DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _session_row(token: str) -> sqlite3.Row:
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT * FROM sessions WHERE token = ?", (token,)
        ).fetchone()
    finally:
        connection.close()
    assert row is not None, "session absente : le test observerait un état qu'il n'a pas construit"
    return row


def _force_expiry(token: str, expires_at: int) -> None:
    connection = _connect()
    try:
        updated = connection.execute(
            "UPDATE sessions SET expires_at = ? WHERE token = ?", (expires_at, token)
        ).rowcount
        connection.commit()
    finally:
        connection.close()
    assert updated == 1, "aucune session mise à jour : le test ne prouverait rien"


class TestSchema:

    def test_sessions_table_carries_expiry(self):
        """`expires_at` existe et est NOT NULL — sans quoi une session sans échéance
        pourrait être insérée et vivrait éternellement."""
        connection = _connect()
        try:
            columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(sessions)")}
        finally:
            connection.close()
        assert "expires_at" in columns
        assert columns["expires_at"]["notnull"] == 1

    def test_migration_recreates_legacy_table(self, tmp_path, monkeypatch):
        """Une base au SCHÉMA ANCIEN (sans `expires_at`) est migrée au démarrage.

        C'est le cas réel de `config/users.db`, créée avant le durcissement : sans migration,
        `initialize_auth_db` la laisserait telle quelle et tout INSERT de session échouerait.
        """
        legacy_db = tmp_path / "legacy_users.db"
        connection = sqlite3.connect(legacy_db)
        try:
            connection.executescript(
                """
                CREATE TABLE sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO sessions (token, user_id, created_at) VALUES ('legacy', 1, '0');
                """
            )
            connection.commit()
        finally:
            connection.close()

        monkeypatch.setattr(api_server, "AUTH_DB_PATH", str(legacy_db))
        api_server.initialize_auth_db()

        connection = sqlite3.connect(legacy_db)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
            survivors = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        finally:
            connection.close()

        assert "expires_at" in columns
        # Les tokens sans échéance sont RÉVOQUÉS par la migration : ce sont exactement ceux
        # que F2 vise. Les conserver leur inventerait une échéance qu'aucune donnée ne porte.
        assert survivors == 0


class TestExpiredSessionRejected:

    def test_expired_session_returns_401(self, authenticated_api_client):
        """Session échue → 401. C'est l'invariant central de F2."""
        token = authenticated_api_client
        _force_expiry(token, int(time.time()) - 1)

        client = app.test_client()
        response = client.get("/api/game/state")
        assert response.status_code == 401

    def test_live_session_still_authenticates(self, authenticated_api_client):
        """Contre-épreuve du test précédent : sans l'expiration forcée, la MÊME requête
        passe. Sans elle, un 401 dû à toute autre cause validerait le test à tort."""
        client = app.test_client()
        response = client.get("/api/game/state")
        assert response.status_code != 401


class TestSlidingRenewal:

    @staticmethod
    def _count_write_connections(monkeypatch) -> list[int]:
        """Compte les connexions d'ÉCRITURE ouvertes pendant la requête.

        Observer `expires_at` ne suffirait pas : sur une session fraîche, un renouvellement
        inutile réécrit la MÊME valeur (`now + TTL`), donc la colonne ne bouge pas et le test
        resterait vert alors que l'écriture — le coût que le seuil existe pour éviter — a bien
        eu lieu. Mesuré : sans ce compteur, retirer le seuil ne fait échouer aucun test.
        """
        opened: list[int] = []
        original = api_server._get_auth_db_connection

        def counting_connection():
            opened.append(1)
            return original()

        monkeypatch.setattr(api_server, "_get_auth_db_connection", counting_connection)
        return opened

    def test_stale_session_is_renewed(self, authenticated_api_client, monkeypatch):
        """Une échéance en retard de plus du seuil est repoussée par une requête authentifiée."""
        token = authenticated_api_client
        now = int(time.time())
        stale = now + api_server.SESSION_TTL_SECONDS - api_server.SESSION_RENEW_AFTER_SECONDS - 60
        _force_expiry(token, stale)

        writes = self._count_write_connections(monkeypatch)
        app.test_client().get("/api/game/state")

        assert writes, "aucune écriture : la session périmée n'a pas été renouvelée"
        assert _session_row(token)["expires_at"] > stale

    def test_fresh_session_is_not_rewritten(self, authenticated_api_client, monkeypatch):
        """Une échéance récente n'entraîne AUCUNE écriture : c'est ce qui évite une écriture
        SQLite par requête (jusqu'à ~40/s sur les prévisualisations au survol)."""
        token = authenticated_api_client
        before = _session_row(token)["expires_at"]

        writes = self._count_write_connections(monkeypatch)
        app.test_client().get("/api/game/state")

        assert not writes, f"{len(writes)} écriture(s) sur une session fraîche : le seuil ne joue pas"
        assert _session_row(token)["expires_at"] == before


class TestLoginRateLimit:

    def _fail_login(self, client):
        return client.post(
            "/api/auth/login", json={"login": "pytest_user", "password": "wrong_password"}
        )

    def test_repeated_failures_return_429(self, authenticated_api_client):
        """Au-delà du plafond, le login répond 429 au lieu de rejouer PBKDF2."""
        client = app.test_client()
        for attempt in range(api_server.LOGIN_ATTEMPT_MAX_FAILURES):
            assert self._fail_login(client).status_code == 401, (
                f"tentative {attempt + 1} : attendu 401 avant d'atteindre le plafond"
            )

        assert self._fail_login(client).status_code == 429

    def test_correct_password_also_blocked_once_limited(self, authenticated_api_client):
        """Le plafond bloque le COUPLE (login, IP), pas seulement les mauvais mots de passe :
        sinon un attaquant qui trouve le bon mot de passe passerait malgré la limitation."""
        client = app.test_client()
        for _ in range(api_server.LOGIN_ATTEMPT_MAX_FAILURES):
            self._fail_login(client)

        response = client.post(
            "/api/auth/login", json={"login": "pytest_user", "password": "pytest_password"}
        )
        assert response.status_code == 429

    def test_success_clears_the_counter(self, authenticated_api_client):
        """Un login réussi sous le plafond remet le compteur à zéro : un utilisateur qui se
        trompe puis se rappelle de son mot de passe ne doit pas rester pénalisé.

        Le budget d'échecs est reconsommé ENTIÈREMENT après le succès. Vérifier un seul échec
        ne prouverait rien : sans remise à zéro, ce premier échec répond 401 lui aussi (4
        échecs mémorisés, plafond à 5) et le test resterait vert. Mesuré.
        """
        client = app.test_client()
        for _ in range(api_server.LOGIN_ATTEMPT_MAX_FAILURES - 1):
            self._fail_login(client)

        ok = client.post(
            "/api/auth/login", json={"login": "pytest_user", "password": "pytest_password"}
        )
        assert ok.status_code == 200

        for attempt in range(api_server.LOGIN_ATTEMPT_MAX_FAILURES - 1):
            assert self._fail_login(client).status_code == 401, (
                f"échec {attempt + 1} après un succès : le compteur n'est pas reparti de zéro"
            )

    def test_login_issues_expiry(self, authenticated_api_client):
        """Le token émis au login porte une échéance cohérente avec le TTL configuré."""
        client = app.test_client()
        response = client.post(
            "/api/auth/login", json={"login": "pytest_user", "password": "pytest_password"}
        )
        assert response.status_code == 200
        issued = response.get_json()["access_token"]

        expires_at = _session_row(issued)["expires_at"]
        assert expires_at == pytest.approx(int(time.time()) + api_server.SESSION_TTL_SECONDS, abs=5)


class TestLogout:

    def test_logout_revokes_immediately(self, authenticated_api_client):
        """Après logout, le MÊME token est refusé — sans attendre les sept jours."""
        token = authenticated_api_client
        client = app.test_client()

        assert client.post("/api/auth/logout").status_code == 200

        connection = _connect()
        try:
            remaining = connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE token = ?", (token,)
            ).fetchone()[0]
        finally:
            connection.close()
        assert remaining == 0
        assert client.get("/api/game/state").status_code == 401

    def test_logout_requires_authentication(self):
        """La route n'est pas publique : sans token, elle tombe dans la porte d'auth."""
        client = app.test_client()
        client.environ_base.pop("HTTP_AUTHORIZATION", None)
        assert client.post("/api/auth/logout").status_code == 401
