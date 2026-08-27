"""Fermeture globale de l'API (F6, F12, F14) — `Documentation/Reference/infra/Security.md`.

Verrouille l'invariant : **tout est fermé par défaut**. Une route ajoutée sans réflexion
sur l'auth doit tomber en 401, jamais s'ouvrir. Ces tests échouent si le `before_request`
est retiré, si une route entre par erreur dans la liste blanche, ou si le filtre
path-traversal de `/api/replay/parse` régresse.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import services.api_server as api_server
from services.game_saves import SaveStore
from services.game_snapshots import capture_live_state
from services.api_server import app

# Routes fermées représentatives : jeu, lecture de logs, configuration de persistance.
CLOSED_ROUTES = [
    ("GET", "/api/game/state"),
    ("GET", "/api/armies"),
    ("GET", "/api/replay/list"),
    ("GET", "/api/game/snapshots"),
    ("GET", "/api/config/board"),
    ("GET", "/api/config/defaults"),
    ("GET", "/api/game/parties"),
    ("POST", "/api/game/action"),
    ("POST", "/api/game/snapshot/persist"),
    ("POST", "/api/replay/parse"),
]


@pytest.fixture
def anonymous_client(authenticated_api_client):
    """Client SANS token : la fixture autouse en injecte un, on le retire explicitement."""
    client = app.test_client()
    client.environ_base.pop("HTTP_AUTHORIZATION", None)
    return client


class TestApiClosedByDefault:

    @pytest.mark.parametrize("method,path", CLOSED_ROUTES)
    def test_route_exists(self, method, path):
        """Le chemin testé doit être une VRAIE route.

        Sans ce contrôle, `test_route_without_token_returns_401` resterait vert sur un
        chemin renommé, supprimé ou mal orthographié : une URL inconnue renvoie 401 elle
        aussi, donc l'assertion de fermeture ne prouverait plus rien.
        """
        matching = [
            rule for rule in app.url_map.iter_rules()
            if rule.rule == path and method in rule.methods
        ]
        assert matching, f"{method} {path} ne correspond à aucune route déclarée"

    @pytest.mark.parametrize("method,path", CLOSED_ROUTES)
    def test_route_without_token_returns_401(self, anonymous_client, method, path):
        """Toute route hors liste blanche, sans token → 401."""
        response = anonymous_client.open(path, method=method, json={})
        assert response.status_code == 401, f"{method} {path} n'est pas protégée"

    def test_invalid_token_returns_401(self, anonymous_client):
        """Un token inconnu de la table `sessions` ne passe pas."""
        response = anonymous_client.get(
            "/api/game/state", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 401

    def test_malformed_authorization_header_returns_401(self, anonymous_client):
        """Header présent mais mal formé (pas de schéma `Bearer`) → 401."""
        response = anonymous_client.get(
            "/api/game/state", headers={"Authorization": "not-a-real-token"}
        )
        assert response.status_code == 401


class TestWhitelist:

    @pytest.mark.parametrize("path", ["/api/health", "/"])
    def test_public_route_reachable_without_token(self, anonymous_client, path):
        """Liste blanche : joignable sans session."""
        assert anonymous_client.get(path).status_code == 200

    def test_login_reachable_without_token(self, anonymous_client):
        """`/api/auth/login` est joignable sans token (401 ici = identifiants faux,
        pas la porte d'entrée : la porte renverrait le même code, on vérifie donc le
        corps de la réponse pour distinguer les deux)."""
        response = anonymous_client.post(
            "/api/auth/login", json={"login": "unknown", "password": "wrong"}
        )
        assert response.status_code == 401
        assert response.get_json()["error"] == "Invalid credentials"

    def test_options_preflight_passes(self, anonymous_client):
        """Les préflights CORS partent sans `Authorization` : les bloquer casse le front."""
        assert anonymous_client.options("/api/game/state").status_code == 200

    def test_register_route_does_not_exist(self, anonymous_client):
        """F12 « fermeture pure » : la route n'existe plus du tout.

        La mettre simplement hors liste blanche ne suffirait pas — un testeur au profil
        `base` porteur d'une session valide pourrait créer des comptes en masse. Le test
        anonyme seul resterait vert dans ce cas : on vérifie donc les DEUX.
        """
        assert "/api/auth/register" not in {rule.rule for rule in app.url_map.iter_rules()}
        assert not hasattr(api_server, "register_user")

        payload = {"login": "intrus", "password": "hunter2"}
        # Anonyme : arrêté par la porte (401, sans révéler que la route n'existe pas).
        assert anonymous_client.post("/api/auth/register", json=payload).status_code == 401
        # Authentifié : franchit la porte et tombe sur 404 — aucun compte ne peut être créé.
        assert app.test_client().post("/api/auth/register", json=payload).status_code == 404

    def test_whitelist_contains_only_expected_endpoints(self):
        """Garde-fou : élargir la liste blanche doit être un acte conscient."""
        assert api_server._PUBLIC_ENDPOINTS == {"login_user", "health_check", "serve_frontend"}

    def test_unmatched_url_is_closed(self, anonymous_client):
        """URL ne correspondant à aucune route → 401 (endpoint `None`), pas 404 :
        la porte échoue du côté fermé et ne révèle pas quelles routes existent."""
        assert anonymous_client.post("/api/auth/login/", json={}).status_code == 401
        assert anonymous_client.get("/api/does/not/exist").status_code == 401

    def test_exemption_follows_the_view_not_the_url(self):
        """L'exemption est portée par le nom de la vue : changer l'URL d'une route publique
        ne peut pas laisser une entrée de liste blanche périmée derrière elle."""
        public_rules = {
            rule.rule
            for rule in app.url_map.iter_rules()
            if rule.endpoint in api_server._PUBLIC_ENDPOINTS
        }
        assert public_rules == {"/api/auth/login", "/api/health", "/"}


class TestAuthenticatedAccessStillWorks:
    """Contre-épreuve du « vert vacant » : si tout renvoyait 401, les tests ci-dessus
    passeraient sur une application cassée. On prouve donc que la porte s'ouvre."""

    @pytest.mark.parametrize(
        "path", ["/api/armies", "/api/replay/list", "/api/game/snapshots", "/api/auth/me"]
    )
    def test_valid_token_gets_a_real_response(self, path):
        """Client authentifié (fixture autouse) → 200, pas seulement « pas 401 ».

        Asserter `!= 401` laisserait passer un 500 : la porte serait franchie mais la route
        cassée, et le test resterait vert en signalant l'inverse.
        """
        assert app.test_client().get(path).status_code == 200


class TestModeRbacOnEveryRequest:
    """Le RBAC ne doit pas se limiter au démarrage de partie : sans contrôle par requête,
    un profil qui n'a pas droit au mode courant peut quand même agir sur la partie."""

    @pytest.fixture
    def running_game(self, monkeypatch):
        """Partie `pvp` en cours, sans moteur réel."""
        engine_stub = SimpleNamespace(current_mode_code="pvp")
        monkeypatch.setattr(api_server, "engine", engine_stub)
        return engine_stub

    def _set_profile_modes(self, monkeypatch, modes):
        monkeypatch.setattr(
            api_server,
            "_resolve_permissions_for_profile",
            lambda _connection, _profile_id: {"game_modes": modes, "options": {}},
        )

    def test_forbidden_mode_is_refused(self, running_game, monkeypatch):
        """Profil limité à `pve`, partie `pvp` en cours → 403 sur les routes de jeu."""
        self._set_profile_modes(monkeypatch, ["pve"])
        response = app.test_client().post("/api/game/action", json={})
        assert response.status_code == 403
        assert "pvp" in response.get_json()["error"]

    def test_allowed_mode_passes(self, running_game, monkeypatch):
        """Même partie, profil qui autorise `pvp` → la porte laisse passer (pas de 403)."""
        self._set_profile_modes(monkeypatch, ["pvp", "pve"])
        assert app.test_client().post("/api/game/action", json={}).status_code != 403

    def test_start_game_is_exempt_from_current_mode_check(self, running_game, monkeypatch):
        """`start_game` REMPLACE le mode : le contrôler sur le mode courant bloquerait à
        tort une bascule légitime. Il valide lui-même le mode DEMANDÉ.

        Profil `pve` + partie `pvp` en cours + démarrage d'une partie `pve` : la porte doit
        laisser passer. Un 403 ici signifierait qu'elle a jugé sur le mode courant.
        """
        self._set_profile_modes(monkeypatch, ["pve"])
        assert "start_game" in api_server._MODE_CHANGING_ENDPOINTS
        response = app.test_client().post("/api/game/start", json={"mode_code": "pve"})
        assert response.status_code != 403, response.get_json()

    def test_start_game_still_validates_the_requested_mode(self, running_game, monkeypatch):
        """L'exemption ne désarme pas le contrôle : un mode demandé interdit reste refusé,
        par `start_game` lui-même (message distinct de celui de la porte)."""
        self._set_profile_modes(monkeypatch, ["pve"])
        response = app.test_client().post("/api/game/start", json={"mode_code": "pvp"})
        assert response.status_code == 403
        assert "not allowed for profile" in response.get_json()["error"]

    def test_meta_routes_are_not_mode_gated(self, running_game, monkeypatch):
        """Catalogues/config/identité restent joignables : `engine` est une globale de
        process, une partie `pvp` oubliée ne doit pas renvoyer 403 à un testeur `pve` sur
        toute la séquence de démarrage du front (403 que `apiFetch` ne redirige pas)."""
        self._set_profile_modes(monkeypatch, ["pve"])
        client = app.test_client()
        for path in ("/api/auth/me", "/api/armies", "/api/config/defaults", "/api/replay/list"):
            assert client.get(path).status_code != 403, path

    @pytest.mark.parametrize(
        "endpoint", ["start_game", "load_party", "load_save", "restore_snapshot"]
    )
    def test_mode_changing_routes_are_registered(self, endpoint):
        """Toute vue qui REMPLACE le mode doit être exemptée du contrôle sur le mode
        courant — sinon elle est jugée sur le mode qu'elle est en train de quitter."""
        assert endpoint in api_server._MODE_CHANGING_ENDPOINTS

    def test_every_route_is_classified(self):
        """Force la classification de toute route NOUVELLE.

        Le défaut (non listée) est le contrôle de mode, donc sûr ; ce test existe pour que
        l'ajout d'une route à une catégorie permissive reste un acte conscient et visible
        en revue, jamais un effet de bord.
        """
        assert api_server._PUBLIC_ENDPOINTS == {
            "health_check", "login_user", "serve_frontend"
        }
        assert api_server._MODE_CHANGING_ENDPOINTS == {
            "start_game", "load_party", "load_save", "restore_snapshot"
        }
        assert api_server._MODE_AGNOSTIC_ENDPOINTS == {
            # `logout_user` : révoquer sa propre session n'agit pas sur la partie en cours.
            # La soumettre au contrôle de mode empêcherait un testeur `pve` de se déconnecter
            # tant qu'une partie `pvp` traîne dans le process.
            "current_user", "logout_user", "list_armies", "get_board_config",
            "get_config_defaults", "get_default_replay_log", "get_replay_log_file",
            "list_replay_logs", "parse_replay_log",
        }

    def test_engine_without_mode_is_refused(self, monkeypatch):
        """Moteur PRÉSENT mais sans mode → refus, pas passage libre.

        C'est l'état exact produit par `initialize_engine()` au démarrage : un moteur PvP
        complet dont `current_mode_code` n'est posé que par `start_game`. Confondre ce cas
        avec « aucune partie » ouvrait la porte à tout profil, du boot au premier
        `start_game`. `test_no_game_running_skips_the_check` ne couvre PAS ce cas : il met
        `engine` à `None`.
        """
        monkeypatch.setattr(
            api_server, "engine", SimpleNamespace(current_mode_code=None, game_state={})
        )
        self._set_profile_modes(monkeypatch, ["pve"])
        response = app.test_client().post("/api/game/action", json={})
        assert response.status_code == 403
        assert "current_mode_code" in response.get_json()["error"]

    def test_no_game_running_skips_the_check(self, monkeypatch):
        """Aucune partie démarrée → aucun mode à contrôler, et aucune requête SQL de plus."""
        monkeypatch.setattr(api_server, "engine", None)

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("permissions résolues alors qu'aucune partie ne tourne")

        monkeypatch.setattr(api_server, "_resolve_permissions_for_profile", fail_if_called)
        assert app.test_client().get("/api/armies").status_code == 200


class TestLoadedModeIsValidated:
    """Charger une sauvegarde REMPLACE `current_mode_code` (`_sync_derived_engine_attrs`).
    La porte juge le mode courant : sans contrôle du mode CIBLE, un profil `pve` en partie
    `pve` charge une partie `pvp` sans que personne ne valide quoi que ce soit."""

    @pytest.fixture
    def pve_profile_in_pve_game(self, monkeypatch):
        monkeypatch.setattr(
            api_server, "engine", SimpleNamespace(current_mode_code="pve", game_state={})
        )
        monkeypatch.setattr(
            api_server,
            "_resolve_permissions_for_profile",
            lambda _connection, _profile_id: {"game_modes": ["pve"], "options": {}},
        )

    def test_loading_a_forbidden_mode_party_is_refused(
        self, pve_profile_in_pve_game, monkeypatch
    ):
        """`/api/game/party/load` d'une partie `pvp` → 403, avant toute mutation."""
        monkeypatch.setattr(
            api_server._SAVE_STORE,
            "party_start_point",
            lambda _name: {"state": {"game_state": {"current_mode_code": "pvp"}, "engine_attrs": {}}, "meta": {}},
        )

        def must_not_run(*_args, **_kwargs):
            raise AssertionError("l'engine a été muté malgré un mode interdit")

        monkeypatch.setattr(api_server._SAVE_STORE, "load_party_start", must_not_run)
        response = app.test_client().post(
            "/api/game/party/load", json={"name": "partie_pvp"}
        )
        assert response.status_code == 403
        assert "pvp" in response.get_json()["error"]

    def test_loading_an_allowed_mode_party_passes_the_mode_check(
        self, pve_profile_in_pve_game, monkeypatch
    ):
        """Contre-épreuve : une partie `pve` n'est pas bloquée par ce contrôle."""
        monkeypatch.setattr(
            api_server._SAVE_STORE,
            "party_start_point",
            lambda _name: {"state": {"game_state": {"current_mode_code": "pve"}, "engine_attrs": {}}, "meta": {}},
        )
        response = app.test_client().post(
            "/api/game/party/load", json={"name": "partie_pve"}
        )
        assert response.status_code != 403

    @pytest.mark.parametrize("view_mode", ["view", "resume"])
    def test_view_mode_is_gated_too(self, pve_profile_in_pve_game, monkeypatch, view_mode):
        """`mode=view` renvoie l'état complet ET fixe la partie courante : le contrôle ne
        peut pas être réservé à `resume`, sinon la lecture d'un mode interdit reste ouverte.
        """
        monkeypatch.setattr(
            api_server._SAVE_STORE,
            "party_start_point",
            lambda _name: {"state": {"game_state": {"current_mode_code": "pvp"}, "engine_attrs": {}}, "meta": {}},
        )

        def must_not_run(*_args, **_kwargs):
            raise AssertionError("partie courante fixée malgré un mode interdit")

        monkeypatch.setattr(api_server._SAVE_STORE, "set_current", must_not_run)
        response = app.test_client().post(
            "/api/game/party/load", json={"name": "partie_pvp", "mode": view_mode}
        )
        assert response.status_code == 403

    def test_state_without_mode_is_refused(self, pve_profile_in_pve_game, monkeypatch):
        """Un état sans `current_mode_code` est REFUSÉ, jamais autorisé par défaut : le
        laisser passer serait précisément le contournement que ce contrôle vise (T1)."""
        monkeypatch.setattr(
            api_server._SAVE_STORE,
            "party_start_point",
            lambda _name: {"state": {"game_state": {}, "engine_attrs": {}}, "meta": {}},
        )
        response = app.test_client().post(
            "/api/game/party/load", json={"name": "sans_mode", "mode": "view"}
        )
        assert response.status_code == 403
        assert "current_mode_code" in response.get_json()["error"]

    def test_loading_a_forbidden_mode_save_point_is_refused(
        self, pve_profile_in_pve_game, monkeypatch
    ):
        """Même faille sur `/api/game/save/load` (save-point d'une autre partie)."""
        monkeypatch.setattr(
            api_server._SAVE_STORE,
            "point",
            lambda _pid: {"state": {"game_state": {"current_mode_code": "pvp"}, "engine_attrs": {}}, "meta": {}},
        )

        def must_not_run(*_args, **_kwargs):
            raise AssertionError("l'engine a été muté malgré un mode interdit")

        monkeypatch.setattr(api_server._SAVE_STORE, "restore_point", must_not_run)
        response = app.test_client().post("/api/game/save/load", json={"id": "p1"})
        assert response.status_code == 403


class TestAuthReadConnectionIsReused:
    """La porte lit cette base à chaque requête (mesuré : 189 µs sur connexion neuve contre
    19 µs sur connexion ouverte). Le partage doit valoir ENTRE THREADS : le serveur de dev
    est en HTTP/1.0 sans keep-alive, donc un thread par requête — un `threading.local`
    n'économiserait rien en production, seulement dans des tests mono-thread."""

    def test_connection_is_shared_across_threads(self):
        """LE test qui compte : deux threads distincts doivent obtenir la MÊME connexion.

        Un cache par thread rendrait ce test rouge tout en gardant vert un test
        mono-thread — c'est exactement le piège que ce cas verrouille.
        """
        seen = []
        barrier = threading.Barrier(2)

        def grab():
            barrier.wait()  # force un vrai recouvrement des deux threads
            with api_server.auth_db_read_cursor() as connection:
                seen.append(connection)

        threads = [threading.Thread(target=grab) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(seen) == 2
        assert seen[0] is seen[1]

    def test_connection_is_reopened_when_the_db_path_changes(self, monkeypatch, tmp_path):
        with api_server.auth_db_read_cursor() as connection:
            first = connection
        other_db = tmp_path / "autre_users.db"
        monkeypatch.setattr(api_server, "AUTH_DB_PATH", str(other_db))
        api_server.initialize_auth_db()
        with api_server.auth_db_read_cursor() as connection:
            assert connection is not first
            # La nouvelle connexion lit bien la NOUVELLE base, pas l'ancienne.
            assert connection.execute("PRAGMA database_list").fetchone()["file"].endswith(
                "autre_users.db"
            )

    def test_writes_still_use_a_dedicated_connection(self):
        """Les écritures gardent une connexion propre : une transaction en échec ne doit
        pas rester pendante sur la connexion partagée par les autres requêtes."""
        with api_server.auth_db_write_cursor() as write_cursor:
            with api_server.auth_db_read_cursor() as read_connection:
                assert write_cursor.connection is not read_connection

    def test_write_cursor_rolls_back_on_exception(self):
        """Une exception dans le `with` ne doit rien laisser committé : c'est ce qui permet
        aux appelants de ne plus gérer eux-mêmes commit et rollback sur chaque sortie."""
        marker = "rollback_probe"
        with pytest.raises(RuntimeError):
            with api_server.auth_db_write_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO auth_events (occurred_at, event, login, ip) VALUES (0, ?, ?, ?)",
                    ("login_failure", marker, "1.1.1.1"),
                )
                raise RuntimeError("échec simulé au milieu de la transaction")

        with api_server.auth_db_read_cursor() as connection:
            remaining = connection.execute(
                "SELECT COUNT(*) FROM auth_events WHERE login = ?", (marker,)
            ).fetchone()[0]
        assert remaining == 0


class TestCapturedModeMatchesRealShape:
    """`_captured_mode` lit dans l'enveloppe produite par `capture_live_state`. Les stubs
    des tests ci-dessus décrivent cette forme de mémoire ; si elle change, ils resteraient
    verts sur une forme que le code de production ne produit plus. Ce test la construit
    donc avec la VRAIE fonction, sans rien inventer."""

    def test_mode_is_read_from_a_genuinely_captured_state(self):
        # `config` : `capture_live_state` l'exige en `require_key` depuis qu'elle capture à part
        # `uses_codex_detachment` et `army_faction` (données de ROSTER, pas d'état de jeu). Vide
        # ici — c'est le cas « scénario muet » que ces deux lectures gèrent nommément, et ce test
        # ne porte que sur l'emplacement du mode dans l'enveloppe.
        engine = SimpleNamespace(game_state={"current_mode_code": "pvp", "turn": 1, "config": {}})
        captured = capture_live_state(engine)
        # Garde-fou sur la forme elle-même : le mode n'est PAS à la racine.
        assert "current_mode_code" not in captured
        assert api_server._captured_mode(captured) == "pvp"

    def test_captured_state_without_mode_reads_as_none(self):
        engine = SimpleNamespace(game_state={"turn": 1, "config": {}})  # cf. commentaire ci-dessus
        assert api_server._captured_mode(capture_live_state(engine)) is None


class TestPreReadRowIsVerified:
    """`restore_point(row=)` évite un second scan du fichier de partie. Le raccourci ne
    doit pas devenir un canal d'écrasement silencieux : `point_id` resterait décoratif et
    une row dépareillée restaurerait un état étranger sans rien signaler."""

    def test_mismatched_row_is_rejected(self, tmp_path):
        store = SaveStore(str(tmp_path / "parties"))
        store._current = "partie_test"
        foreign_row = {"meta": {"id": "20260101-000000"}, "state": {}}
        with pytest.raises(ValueError, match="incohérente"):
            store.restore_point(SimpleNamespace(), "20260202-111111", row=foreign_row)

    def test_matching_row_is_accepted(self, tmp_path, monkeypatch):
        """Contre-épreuve : une row cohérente passe (sinon le test ci-dessus serait vert
        pour la simple raison que tout est refusé)."""
        store = SaveStore(str(tmp_path / "parties"))
        store._current = "partie_test"
        monkeypatch.setattr(store, "_assert_scenario_match", lambda *_a, **_k: None)
        monkeypatch.setattr("services.game_saves.apply_live_state", lambda *_a, **_k: None)
        row = {"meta": {"id": "20260202-111111"}, "state": {}}
        assert store.restore_point(SimpleNamespace(), "20260202-111111", row=row) is row["meta"]


class TestReplayParsePathTraversal:
    """F14 : filtre aligné sur `/api/replay/file/<filename>`."""

    @pytest.mark.parametrize(
        "log_path",
        ["../../etc/passwd", "/etc/passwd", "subdir/train_step.log", "..\\windows.log"],
    )
    def test_traversal_is_rejected(self, log_path):
        response = app.test_client().post("/api/replay/parse", json={"log_path": log_path})
        assert response.status_code == 400

    def test_non_log_extension_is_rejected(self):
        response = app.test_client().post(
            "/api/replay/parse", json={"log_path": "config.json"}
        )
        assert response.status_code == 400
        assert response.get_json()["error"] == "Only .log files are allowed"

    def test_plain_filename_is_accepted_by_the_filter(self):
        """Un nom simple passe le filtre : 404 (fichier absent) ≠ 400 (rejet)."""
        response = app.test_client().post(
            "/api/replay/parse", json={"log_path": "definitely_absent.log"}
        )
        assert response.status_code == 404
