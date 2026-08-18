"""Exploitation du journal d'authentification — étapes 7 et 8 de `Security.md`.

L'étape 3 avait posé la table `auth_events` sans personne pour la lire : une table que
personne ne consulte ne détecte rien. `scripts/auth_journal.py` la lit. Ce fichier verrouille
ce dont dépend la confiance qu'on peut lui accorder :

1. il n'ÉCRIT pas — ni par son import, ni par sa connexion. Un auditeur qui crée la base qu'il
   audite rend « aucun compte » indiscernable de « fichier absent » ;
2. `--since` refuse ce qu'il ne comprend pas, au lieu de retomber sur une fenêtre par défaut :
   un rapport vide obtenu sur une mauvaise fenêtre est le pire résultat d'un outil d'audit ;
3. `accounts` détecte réellement un mot de passe trivial et SORT EN ERREUR (étape 8) ;
4. `suspects` sort en erreur sur un refus de rate limiting, seul événement du journal qui ne
   peut pas venir d'un utilisateur maladroit.

Chaque test construit sa propre base : rien n'est lu de `config/users.db`, fichier protégé.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

import scripts.auth_journal as auth_journal
from shared.auth_credentials import (
    AUTH_EVENT_LOGIN_FAILURE,
    AUTH_EVENT_LOGIN_SUCCESS,
    AUTH_EVENT_RATE_LIMITED,
    hash_password,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _build_db(path: Path, *, password: str = "un-mot-de-passe-non-trivial") -> None:
    """Base d'auth minimale mais RÉELLE : mêmes tables et mêmes colonnes que la production.

    Le hash est produit par `hash_password`, la fonction de production : un hash écrit à la
    main testerait un format que le code ne produit pas.
    """
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE profiles (id INTEGER PRIMARY KEY, code TEXT NOT NULL, label TEXT NOT NULL);
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, login TEXT NOT NULL,
                password_hash TEXT NOT NULL, profile_id INTEGER NOT NULL
            );
            CREATE TABLE sessions (
                token TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
            );
            CREATE TABLE auth_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at INTEGER NOT NULL,
                event TEXT NOT NULL, login TEXT NOT NULL, ip TEXT NOT NULL, details TEXT
            );
            INSERT INTO profiles (id, code, label) VALUES (1, 'base', 'Base');
            """
        )
        connection.execute(
            "INSERT INTO users (id, login, password_hash, profile_id) VALUES (1, ?, ?, 1)",
            ("testeur", hash_password(password)),
        )
        connection.commit()
    finally:
        connection.close()


def _add_event(path: Path, event: str, login: str, ip: str, occurred_at: int) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO auth_events (occurred_at, event, login, ip) VALUES (?, ?, ?, ?)",
            (occurred_at, event, login, ip),
        )
        connection.commit()
    finally:
        connection.close()


def _args(**overrides) -> argparse.Namespace:
    defaults = {"since": 7 * 86400, "since_label": "7d", "min_failures": 5,
                "event": None, "login": None, "ip": None, "limit": 100}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestNoWriteSideEffect:
    """Le verrou qui a motivé `shared/auth_credentials.py`.

    `services/api_server.py` appelle `initialize_auth_db()` au niveau module : l'importer suffit
    à écrire dans la base et à la CRÉER si elle manque. Un outil de lecture qui passerait par lui
    fabriquerait la base qu'il vient auditer.
    """

    @staticmethod
    def _import_in_subprocess(module: str, db_path: Path) -> None:
        """Import dans un processus NEUF. Dans le processus de test, `services.api_server` est
        déjà importé (conftest) : son effet de bord a déjà eu lieu et serait invisible ici."""
        environment = dict(os.environ, W40K_AUTH_DB_PATH=str(db_path))
        subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=_REPO_ROOT, env=environment, check=True,
            capture_output=True, text=True, timeout=300,
        )

    def test_shared_module_import_creates_nothing(self, tmp_path):
        db_path = tmp_path / "jamais_creee.db"
        self._import_in_subprocess("shared.auth_credentials", db_path)
        assert not db_path.exists(), (
            "importer le socle d'auth crée la base : `scripts/auth_journal.py` fabriquerait "
            "la base qu'il est censé auditer"
        )

    def test_api_server_import_does_create_it(self, tmp_path):
        """CONTRE-ÉPREUVE. Sans elle, un test d'environnement cassé (import muet, chemin ignoré)
        rendrait le test ci-dessus vert sans rien prouver."""
        db_path = tmp_path / "creee_par_le_serveur.db"
        self._import_in_subprocess("services.api_server", db_path)
        assert db_path.exists(), (
            "l'import de api_server n'écrit plus : la prémisse de la séparation a changé, "
            "le test ci-dessus ne prouve donc plus rien"
        )

    def test_connection_is_read_only(self, tmp_path):
        db_path = tmp_path / "users.db"
        _build_db(db_path)
        connection = auth_journal.open_readonly(str(db_path))
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                connection.execute("DELETE FROM auth_events")
        finally:
            connection.close()

    def test_missing_database_is_reported_not_created(self, tmp_path):
        db_path = tmp_path / "absente.db"
        with pytest.raises(SystemExit, match="introuvable"):
            auth_journal.open_readonly(str(db_path))
        assert not db_path.exists()


class TestParseDuration:
    @pytest.mark.parametrize(
        "raw,expected", [("30s", 30), ("15m", 900), ("24h", 86400), ("7d", 604800), ("2w", 1209600)]
    )
    def test_valid(self, raw, expected):
        assert auth_journal.parse_duration(raw) == expected

    @pytest.mark.parametrize("raw", ["7", "7j", "-1d", "d7", "", "1.5h"])
    def test_invalid_is_refused(self, raw):
        """Un `--since 7` accepté comme sept secondes rendrait un rapport vide et laisserait
        croire qu'il ne s'est rien passé."""
        with pytest.raises(argparse.ArgumentTypeError):
            auth_journal.parse_duration(raw)


class TestAccountsAudit:
    """Étape 8 : « vérifier les mots de passe des comptes existants (pas de comptes de test type
    admin/admin) »."""

    def test_trivial_password_fails_the_audit(self, tmp_path, capsys):
        db_path = tmp_path / "users.db"
        _build_db(db_path, password="admin")
        connection = auth_journal.open_readonly(str(db_path))
        try:
            code = auth_journal.command_accounts(connection, _args())
        finally:
            connection.close()
        assert code == 1, "un compte à mot de passe trivial ne fait pas échouer l'audit"
        assert "TRIVIAL" in capsys.readouterr().out

    def test_login_used_as_password_is_caught(self, tmp_path, capsys):
        """`admin/admin` est le cas NOMMÉ par l'étape 8 ; le login n'est pas dans la liste
        statique, il faut donc le tester en plus."""
        db_path = tmp_path / "users.db"
        _build_db(db_path, password="testeur")
        connection = auth_journal.open_readonly(str(db_path))
        try:
            code = auth_journal.command_accounts(connection, _args())
        finally:
            connection.close()
        assert code == 1
        assert "'testeur'" in capsys.readouterr().out

    def test_strong_password_passes(self, tmp_path, capsys):
        """Contre-épreuve : sans elle, une fonction qui déclarerait TOUT trivial passerait les
        deux tests ci-dessus."""
        db_path = tmp_path / "users.db"
        _build_db(db_path, password="7Kx!pQ2z-vNm4Lr")
        connection = auth_journal.open_readonly(str(db_path))
        try:
            code = auth_journal.command_accounts(connection, _args())
        finally:
            connection.close()
        assert code == 0
        assert "Aucun mot de passe trivial" in capsys.readouterr().out


class TestSuspects:
    def test_rate_limited_event_fails(self, tmp_path, capsys):
        db_path = tmp_path / "users.db"
        _build_db(db_path)
        _add_event(db_path, AUTH_EVENT_RATE_LIMITED, "testeur", "203.0.113.9", int(time.time()))
        connection = auth_journal.open_readonly(str(db_path))
        try:
            code = auth_journal.command_suspects(connection, _args())
        finally:
            connection.close()
        assert code == 1, "un refus de rate limiting passe inaperçu"
        assert "203.0.113.9" in capsys.readouterr().out

    def test_account_sweep_is_flagged(self, tmp_path, capsys):
        """Plusieurs LOGINS distincts en échec depuis une même IP : un utilisateur qui se trompe
        se trompe sur son propre login, pas sur ceux des autres."""
        db_path = tmp_path / "users.db"
        _build_db(db_path)
        now = int(time.time())
        for index in range(6):
            _add_event(db_path, AUTH_EVENT_LOGIN_FAILURE, f"cible{index}", "198.51.100.4", now)
        connection = auth_journal.open_readonly(str(db_path))
        try:
            code = auth_journal.command_suspects(connection, _args())
        finally:
            connection.close()
        assert code == 1
        assert "balayage de comptes" in capsys.readouterr().out

    def test_quiet_journal_passes(self, tmp_path, capsys):
        """Contre-épreuve : une activité normale ne doit pas déclencher d'alerte, sinon la
        commande devient du bruit et personne ne la regarde."""
        db_path = tmp_path / "users.db"
        _build_db(db_path)
        _add_event(db_path, AUTH_EVENT_LOGIN_SUCCESS, "testeur", "192.0.2.10", int(time.time()))
        connection = auth_journal.open_readonly(str(db_path))
        try:
            code = auth_journal.command_suspects(connection, _args())
        finally:
            connection.close()
        assert code == 0
        assert "aucun — personne n'a atteint le plafond" in capsys.readouterr().out

    def test_event_filter_selects(self, tmp_path, capsys):
        """`events --event/--login/--ip` passe par une requête à filtres optionnels
        (`? IS NULL OR colonne = ?`). Un filtre qui ne filtrerait pas — ou qui viderait tout —
        rendrait la commande inutilisable sans rien signaler."""
        db_path = tmp_path / "users.db"
        _build_db(db_path)
        now = int(time.time())
        _add_event(db_path, AUTH_EVENT_LOGIN_SUCCESS, "alice", "192.0.2.1", now)
        _add_event(db_path, AUTH_EVENT_LOGIN_FAILURE, "bob", "192.0.2.2", now)

        connection = auth_journal.open_readonly(str(db_path))
        try:
            auth_journal.command_events(connection, _args(event=AUTH_EVENT_LOGIN_FAILURE))
            filtered = capsys.readouterr().out
            auth_journal.command_events(connection, _args())
            unfiltered = capsys.readouterr().out
        finally:
            connection.close()

        assert "bob" in filtered and "alice" not in filtered, "le filtre --event ne filtre pas"
        # Contre-épreuve : sans filtre, les DEUX lignes sortent — un filtre qui viderait
        # systématiquement le résultat passerait l'assertion ci-dessus.
        assert "alice" in unfiltered and "bob" in unfiltered

    def test_events_outside_the_window_are_not_reported(self, tmp_path, capsys):
        """La fenêtre doit réellement filtrer : sinon `--since` serait décoratif et un incident
        vieux d'un mois se lirait comme actuel."""
        db_path = tmp_path / "users.db"
        _build_db(db_path)
        _add_event(
            db_path, AUTH_EVENT_RATE_LIMITED, "testeur", "203.0.113.9",
            int(time.time()) - 30 * 86400,
        )
        connection = auth_journal.open_readonly(str(db_path))
        try:
            code = auth_journal.command_suspects(connection, _args(since=3600, since_label="1h"))
        finally:
            connection.close()
        assert code == 0
        assert "203.0.113.9" not in capsys.readouterr().out
