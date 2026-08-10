"""Durcissement des sessions et rate limiting du login (F2, F8) — `Documentation/Implémentation/Security.md`.

Verrouille sept invariants :
1. une session échue n'authentifie plus (avant : `WHERE s.token = ?` seul, token valide à vie) ;
2. une session vivante voit son échéance repoussée, mais SANS écrire à chaque requête ;
3. le login se ferme après `LOGIN_ATTEMPT_MAX_FAILURES` tentatives dans la fenêtre ;
4. le logout révoque immédiatement, sans attendre l'expiration ;
5. l'IP retenue est celle du CLIENT, pas celle du proxy — sinon la clé du rate limiting perd
   sa composante IP et cinq essais ratés verrouillent le compte de n'importe qui ;
6. la tentative est inscrite AVANT la vérification du mot de passe, ce qui la place dans la
   même transaction que le comptage et rend le plafond atomique ;
7. le journal `auth_events` est append-only : un succès rend les tentatives non comptables
   sans les détruire, et aucun échec fictif n'est inventé sur une connexion réussie.

Chaque test CONSTRUIT l'état qu'il observe (échéance forcée en SQL, échecs répétés
réellement émis, en-têtes de proxy posés explicitement) : rien n'est espéré d'un ordre
d'exécution, d'une horloge ou d'une configuration ambiante.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

import services.api_server as api_server
from services.api_server import app
from shared.data_validation import ConfigurationError


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


class TestReferenceScriptMatchesProduction:
    """Le script de référence `Documentation/Memoire/Annexe_script_BDD_auth.sql` doit décrire
    LE MÊME schéma que `initialize_auth_db()`.

    Il avait silencieusement divergé (`created_at TEXT`, pas d'`expires_at`, pas de journal) :
    une base recréée à partir de lui produisait exactement le schéma que la migration détruit
    au démarrage, et le rate limiting tombait sur une table absente. Rien ne le signalait —
    d'où ce test, qui compare les deux au lieu de faire confiance à la relecture.
    """

    @staticmethod
    def _schema_of(db_path) -> set:
        connection = sqlite3.connect(db_path)
        try:
            return {
                " ".join(row[0].split())
                for row in connection.execute(
                    "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
                )
            }
        finally:
            connection.close()

    def test_reference_script_produces_the_production_schema(self, tmp_path, monkeypatch):
        script = (
            Path(__file__).resolve().parents[3]
            / "Documentation" / "Memoire" / "Annexe_script_BDD_auth.sql"
        )
        assert script.exists(), f"script de référence introuvable : {script}"

        from_script = tmp_path / "from_script.db"
        connection = sqlite3.connect(from_script)
        try:
            connection.executescript(script.read_text(encoding="utf-8"))
            connection.commit()
        finally:
            connection.close()

        from_code = tmp_path / "from_code.db"
        monkeypatch.setattr(api_server, "AUTH_DB_PATH", str(from_code))
        api_server.initialize_auth_db()

        missing = self._schema_of(from_code) - self._schema_of(from_script)
        assert not missing, (
            "le script de référence ne crée pas ces objets produits par initialize_auth_db : "
            f"{sorted(missing)}"
        )


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
        """Compte les ouvertures de transaction d'ÉCRITURE pendant la requête.

        Observer `expires_at` ne suffirait pas : sur une session fraîche, un renouvellement
        inutile réécrit la MÊME valeur (`now + TTL`), donc la colonne ne bouge pas et le test
        resterait vert alors que l'écriture — le coût que le seuil existe pour éviter — a bien
        eu lieu. Mesuré : sans ce compteur, retirer le seuil ne fait échouer aucun test.

        L'instrument suit `auth_db_write_cursor`, le point de passage UNIQUE des écritures.
        Il visait auparavant `_get_auth_db_connection` : quand le code est passé au context
        manager partagé, il a cessé de voir quoi que ce soit — un compteur qui ne compte plus
        rien rend un test vert. C'est ce test qui l'a signalé en devenant rouge.
        """
        opened: list[int] = []
        original = api_server.auth_db_write_cursor

        @contextmanager
        def counting_writer(*args, **kwargs):
            opened.append(1)
            with original(*args, **kwargs) as cursor:
                yield cursor

        monkeypatch.setattr(api_server, "auth_db_write_cursor", counting_writer)
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


class TestClientIp:
    """`_client_ip` décide de la clé du rate limiting. S'il rend la même valeur pour tout le
    monde, cinq essais ratés verrouillent le compte de n'importe qui : la protection F8 se
    retourne en déni de service. Le front passe TOUJOURS par un proxy (Vite en dev, nginx en
    conteneur), donc ce n'est pas un cas de bord."""

    @staticmethod
    def _ip_for(monkeypatch, *, trusted, remote_addr, forwarded=None):
        # Le jeu est construit comme en production (adresses NORMALISÉES, pas des chaînes) :
        # un test qui poserait des chaînes testerait un mécanisme que le code n'utilise pas.
        monkeypatch.setattr(
            api_server,
            "TRUSTED_PROXIES",
            frozenset(api_server._normalize_ip(item) for item in trusted),
        )
        headers = {"X-Forwarded-For": forwarded} if forwarded is not None else {}
        with app.test_request_context("/api/auth/login", environ_base={"REMOTE_ADDR": remote_addr},
                                      headers=headers):
            return api_server._client_ip()

    def test_direct_connection_uses_remote_addr(self, monkeypatch):
        assert self._ip_for(monkeypatch, trusted=[], remote_addr="203.0.113.7") == "203.0.113.7"

    def test_forwarded_header_ignored_from_untrusted_source(self, monkeypatch):
        """Sans proxy déclaré, `X-Forwarded-For` est de la donnée client : la suivre offrirait
        un compteur neuf à chaque tentative."""
        got = self._ip_for(
            monkeypatch, trusted=[], remote_addr="203.0.113.7", forwarded="1.2.3.4"
        )
        assert got == "203.0.113.7"

    def test_forwarded_header_used_from_trusted_proxy(self, monkeypatch):
        """Derrière un proxy déclaré, c'est l'IP du client qui compte, pas celle du proxy —
        sinon tous les utilisateurs partagent un seul seau."""
        got = self._ip_for(
            monkeypatch, trusted=["10.0.0.1"], remote_addr="10.0.0.1", forwarded="203.0.113.7"
        )
        assert got == "203.0.113.7"

    def test_chain_is_walked_right_to_left(self, monkeypatch):
        """La partie gauche de la chaîne est écrite par le client : seul le premier élément
        non fiable en partant de la DROITE est croyable."""
        got = self._ip_for(
            monkeypatch,
            trusted=["10.0.0.1", "10.0.0.2"],
            remote_addr="10.0.0.1",
            forwarded="9.9.9.9, 203.0.113.7, 10.0.0.2",
        )
        assert got == "203.0.113.7"

    def test_ipv4_mapped_proxy_is_recognised(self, monkeypatch):
        """`::ffff:10.0.0.1` et `10.0.0.1` sont la MÊME adresse, et Werkzeug rend l'une ou
        l'autre selon la pile réseau. Une comparaison de chaînes les distinguerait, ferait
        ignorer `X-Forwarded-For` en silence, et restaurerait le seau partagé."""
        got = self._ip_for(
            monkeypatch,
            trusted=["10.0.0.1"],
            remote_addr="::ffff:10.0.0.1",
            forwarded="203.0.113.7",
        )
        assert got == "203.0.113.7"

    def test_hostname_in_config_is_rejected_at_startup(self, monkeypatch):
        """Un nom d'hôte ne peut jamais correspondre à `remote_addr` : l'accepter donnerait une
        configuration d'apparence correcte qui ne s'applique à rien."""
        monkeypatch.setenv("W40K_TRUSTED_PROXIES", "nginx")
        with pytest.raises(ConfigurationError, match="adresse IP"):
            api_server._resolve_trusted_proxies()

    def test_trusted_proxy_without_usable_header_raises(self, monkeypatch):
        """Proxy de confiance qui n'a pas posé l'en-tête : erreur explicite. Se rabattre sur
        `remote_addr` rangerait tout le monde dans le même seau — le repli silencieux
        exactement là où il fait le plus de dégâts."""
        with pytest.raises(RuntimeError, match="X-Forwarded-For"):
            self._ip_for(monkeypatch, trusted=["10.0.0.1"], remote_addr="10.0.0.1")

    def test_empty_env_var_is_a_startup_error(self, monkeypatch):
        """Variable définie mais vide = faute de configuration, pas « aucun proxy »."""
        monkeypatch.setenv("W40K_TRUSTED_PROXIES", "  ,  ")
        with pytest.raises(ConfigurationError):
            api_server._resolve_trusted_proxies()

    def test_unset_env_var_trusts_nobody(self, monkeypatch):
        monkeypatch.delenv("W40K_TRUSTED_PROXIES", raising=False)
        assert api_server._resolve_trusted_proxies() == frozenset()


class TestAuthEventsJournal:
    """Le journal est append-only : c'est ce qui permet au rate limiting et à la traçabilité
    (étape 7) de vivre sur une seule table, avec une seule écriture par événement."""

    @staticmethod
    def _events(login="pytest_user"):
        connection = _connect()
        try:
            return [
                (row["event"], row["ip"])
                for row in connection.execute(
                    "SELECT event, ip FROM auth_events WHERE login = ? ORDER BY id", (login,)
                )
            ]
        finally:
            connection.close()

    def test_failure_then_success_are_both_kept(self, authenticated_api_client):
        """Le succès ne DÉTRUIT pas l'échec qui le précède — il le rend non comptable.
        Un compteur qui s'efface ne peut pas servir de journal."""
        client = app.test_client()
        client.post("/api/auth/login", json={"login": "pytest_user", "password": "wrong"})
        client.post("/api/auth/login", json={"login": "pytest_user", "password": "pytest_password"})

        events = [event for event, _ in self._events()]
        assert events == [
            "login_attempt", "login_failure",   # essai raté : tentative puis issue
            "login_attempt", "login_success",   # essai réussi : AUCUN échec inventé
        ]

    def test_rate_limited_is_recorded_as_its_own_event(self, authenticated_api_client):
        """Un refus n'est pas un essai : le compter comme `login_failure` ferait s'auto-
        prolonger le blocage indéfiniment."""
        client = app.test_client()
        for _ in range(api_server.LOGIN_ATTEMPT_MAX_FAILURES + 1):
            client.post("/api/auth/login", json={"login": "pytest_user", "password": "wrong"})

        events = [event for event, _ in self._events()]
        assert events.count("login_attempt") == api_server.LOGIN_ATTEMPT_MAX_FAILURES
        assert events.count("login_failure") == api_server.LOGIN_ATTEMPT_MAX_FAILURES
        assert events.count("rate_limited") == 1

    def test_refusals_do_not_grow_the_journal(self, authenticated_api_client):
        """Un attaquant qui martèle un compte bloqué ne doit pas faire grossir la table.

        Chaque requête refusée écrivait une ligne, sur un chemin qu'il contrôle entièrement et
        sous le verrou d'écriture — donc en concurrence directe avec les logins légitimes. Une
        seule trace par fenêtre suffit à l'audit.
        """
        client = app.test_client()
        for _ in range(api_server.LOGIN_ATTEMPT_MAX_FAILURES):
            client.post("/api/auth/login", json={"login": "pytest_user", "password": "wrong"})

        for _ in range(20):
            assert client.post(
                "/api/auth/login", json={"login": "pytest_user", "password": "wrong"}
            ).status_code == 429

        events = [event for event, _ in self._events()]
        assert events.count("rate_limited") == 1, (
            f"{events.count('rate_limited')} lignes pour 21 refus : le journal grossit avec "
            "le martèlement"
        )

    def test_retention_applies_even_without_any_successful_login(self, authenticated_api_client):
        """La purge doit tourner sur toute tentative. Cantonnée au login réussi, le seul chemin
        qui bornait la table était celui qu'un attaquant ne prend jamais."""
        connection = _connect()
        try:
            connection.execute(
                "INSERT INTO auth_events (occurred_at, event, login, ip) VALUES (?, ?, ?, ?)",
                (int(time.time()) - api_server.AUTH_EVENT_RETENTION_SECONDS - 10,
                 "login_failure", "ancien", "1.1.1.1"),
            )
            connection.commit()
        finally:
            connection.close()

        # UNIQUEMENT des échecs : aucun login réussi dans ce test.
        app.test_client().post(
            "/api/auth/login", json={"login": "pytest_user", "password": "wrong"}
        )

        assert self._events("ancien") == []

    def test_logout_revokes_even_if_journaling_fails(self, authenticated_api_client):
        """La révocation ne dépend pas de la journalisation.

        Les deux partageaient une transaction : `_client_ip()` peut lever (proxy de confiance
        sans en-tête exploitable), et le rollback annulait alors la révocation — l'utilisateur
        voyait un 500 en croyant s'être déconnecté, avec un token toujours valide.
        """
        token = authenticated_api_client
        client = app.test_client()

        def exploding_ip():
            raise RuntimeError("proxy mal configuré")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(api_server, "_client_ip", exploding_ip)
            client.post("/api/auth/logout")

        connection = _connect()
        try:
            remaining = connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE token = ?", (token,)
            ).fetchone()[0]
        finally:
            connection.close()
        assert remaining == 0, "session non révoquée alors que l'utilisateur a demandé à partir"

    def test_logout_is_journaled(self, authenticated_api_client):
        app.test_client().post("/api/auth/logout")
        assert "logout" in [event for event, _ in self._events()]

    def test_attempt_is_recorded_before_password_verification(self, authenticated_api_client, monkeypatch):
        """L'inscription précède PBKDF2 — c'est ce qui la place dans la MÊME transaction que
        le comptage, donc ce qui rend le plafond atomique.

        Vérifier l'ordre plutôt que la concurrence : un test à threads dépendrait d'un
        entrelacement, et prouverait donc quelque chose de différent à chaque exécution.
        """
        seen: list[int] = []
        original = api_server._verify_password

        def spying_verify(password, password_hash):
            connection = _connect()
            try:
                seen.append(
                    connection.execute(
                        "SELECT COUNT(*) FROM auth_events WHERE event = 'login_attempt'"
                    ).fetchone()[0]
                )
            finally:
                connection.close()
            return original(password, password_hash)

        monkeypatch.setattr(api_server, "_verify_password", spying_verify)
        app.test_client().post(
            "/api/auth/login", json={"login": "pytest_user", "password": "pytest_password"}
        )

        assert seen == [1], (
            "la tentative doit être committée AVANT la vérification du mot de passe ; "
            f"vu depuis PBKDF2 : {seen}"
        )

    def test_counting_holds_the_write_lock(self, authenticated_api_client, monkeypatch):
        """Le comptage se fait DANS une transaction d'écriture déjà verrouillée.

        C'est le cœur de l'atomicité du plafond : sans `BEGIN IMMEDIATE`, SQLite ne pose le
        verrou qu'à la première écriture, et N requêtes concurrentes lisent alors le même
        total, passent toutes, et lancent toutes PBKDF2 — le déni de service que le contrôle
        est censé empêcher. Werkzeug crée un thread par requête, ce parallélisme est réel.

        Observé sans concurrence, donc sans dépendre d'un entrelacement : depuis l'intérieur
        du comptage, une SECONDE connexion qui tente d'écrire immédiatement doit se heurter au
        verrou. En transaction différée, elle l'obtiendrait.
        """
        blocked: list[bool] = []
        original = api_server._count_login_attempts_since_success

        def probing_count(cursor, login, ip, now):
            rival = sqlite3.connect(api_server.AUTH_DB_PATH, timeout=0)
            try:
                rival.execute("BEGIN IMMEDIATE")
                blocked.append(False)
            except sqlite3.OperationalError:
                blocked.append(True)
            finally:
                rival.close()
            return original(cursor, login, ip, now)

        monkeypatch.setattr(api_server, "_count_login_attempts_since_success", probing_count)
        app.test_client().post(
            "/api/auth/login", json={"login": "pytest_user", "password": "wrong"}
        )

        assert blocked == [True], (
            "le comptage ne tient pas le verrou d'écriture : deux logins concurrents "
            "peuvent lire le même total et passer tous les deux le plafond"
        )

    def test_retention_purges_old_events(self, authenticated_api_client):
        """La purge suit la rétention (30 j), pas la fenêtre du rate limiting (60 s)."""
        connection = _connect()
        try:
            connection.execute(
                "INSERT INTO auth_events (occurred_at, event, login, ip) VALUES (?, ?, ?, ?)",
                (int(time.time()) - api_server.AUTH_EVENT_RETENTION_SECONDS - 10,
                 "login_failure", "ancien", "1.1.1.1"),
            )
            connection.commit()
        finally:
            connection.close()

        app.test_client().post(
            "/api/auth/login", json={"login": "pytest_user", "password": "pytest_password"}
        )

        assert self._events("ancien") == []

    def test_recent_events_survive_the_purge(self, authenticated_api_client):
        """Contre-épreuve : sans elle, une purge qui efface TOUT passerait le test ci-dessus."""
        connection = _connect()
        try:
            connection.execute(
                "INSERT INTO auth_events (occurred_at, event, login, ip) VALUES (?, ?, ?, ?)",
                (int(time.time()) - 60, "login_failure", "recent", "1.1.1.1"),
            )
            connection.commit()
        finally:
            connection.close()

        app.test_client().post(
            "/api/auth/login", json={"login": "pytest_user", "password": "pytest_password"}
        )

        assert self._events("recent") != []


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
