"""Réduction de la surface d'information et session en cookie — F3, F10, F13.

Étape 4 de `Documentation/Reference/infra/securite.md`. Verrouille six invariants :

1. CORS : les origines sont une liste EXPLICITE, `*` est refusé au démarrage. Avant, `CORS(app)`
   sans `origins` valait `*` et n'importe quelle page du web pouvait lire l'API.
2. Traceback : il n'entre dans la réponse HTTP que si `EXPOSE_TRACEBACK` l'autorise, et
   « variable non définie » vaut FERMÉ. Avant, `handle_uncaught_exception` renvoyait chemins,
   structure du code et versions à tout appelant, en production comprise.
3. Cookie : le login pose un cookie `HttpOnly` + `SameSite=Strict`, seul porteur de session
   côté navigateur (le token ne va plus en `localStorage`, donc plus rien à voler par XSS).
4. CSRF : une authentification PAR COOKIE exige l'en-tête `CSRF_HEADER_NAME`. Sans lui, un
   `<form>` hébergé sur un autre site agirait au nom de l'utilisateur connecté.
5. Le cookie prime sur `Bearer` : un cookie périmé ne se fait pas repêcher par un autre canal.
6. Le cookie GLISSE avec la session (F2) et est EFFACÉ au logout.

Chaque test construit son état (cookie posé explicitement, proxy déclaré, échéance forcée en
SQL) : rien ne dépend d'un ordre d'exécution ni d'une variable d'environnement ambiante.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from werkzeug.exceptions import NotFound

import services.api_server as api_server
from services.api_server import app
from shared.data_validation import ConfigurationError


def _unauthenticated_client():
    """Client SANS le `Bearer` que la fixture autouse pose par défaut.

    Indispensable ici : les tests de cookie doivent observer le chemin cookie, et un `Bearer`
    résiduel authentifierait la requête par l'autre canal — le test passerait au vert sans rien
    prouver du mécanisme visé.
    """
    client = app.test_client()
    client.environ_base.pop("HTTP_AUTHORIZATION", None)
    return client


def _session_expiry(token: str) -> int:
    connection = sqlite3.connect(api_server.AUTH_DB_PATH)
    try:
        row = connection.execute(
            "SELECT expires_at FROM sessions WHERE token = ?", (token,)
        ).fetchone()
    finally:
        connection.close()
    assert row is not None, "session absente : le test observerait un état qu'il n'a pas construit"
    return row[0]


def _force_expiry(token: str, expires_at: int) -> None:
    connection = sqlite3.connect(api_server.AUTH_DB_PATH)
    try:
        updated = connection.execute(
            "UPDATE sessions SET expires_at = ? WHERE token = ?", (expires_at, token)
        ).rowcount
        connection.commit()
    finally:
        connection.close()
    assert updated == 1, "échéance non appliquée : le test ne mesurerait rien"


def _set_cookie_headers(response) -> list[str]:
    return [
        value for name, value in response.headers.items()
        if name.lower() == "set-cookie" and value.startswith(f"{api_server.SESSION_COOKIE_NAME}=")
    ]


class TestCorsOrigins:
    """F3. `CORS(app)` sans `origins` vaut `*` : toute page du web pouvait lire les réponses de
    l'API avec les identifiants de la victime."""

    def test_undefined_falls_back_to_dev_origins(self, monkeypatch):
        monkeypatch.delenv("W40K_CORS_ORIGINS", raising=False)
        assert api_server._resolve_cors_origins() == list(api_server._DEFAULT_CORS_ORIGINS)

    def test_explicit_list_is_parsed(self, monkeypatch):
        monkeypatch.setenv("W40K_CORS_ORIGINS", "https://a.tld, https://b.tld:8443")
        assert api_server._resolve_cors_origins() == ["https://a.tld", "https://b.tld:8443"]

    def test_empty_value_is_a_startup_error(self, monkeypatch):
        """Définie mais vide = faute de configuration, pas « aucune origine » — même convention
        que `W40K_TRUSTED_PROXIES` et `W40K_PERSIST_DIR`."""
        monkeypatch.setenv("W40K_CORS_ORIGINS", "   ")
        with pytest.raises(ConfigurationError, match="définie mais vide"):
            api_server._resolve_cors_origins()

    def test_wildcard_is_refused(self, monkeypatch):
        """Le joker est le défaut d'avant : l'accepter par configuration réintroduirait F3 tel
        quel, et il porterait désormais le cookie de session."""
        monkeypatch.setenv("W40K_CORS_ORIGINS", "https://a.tld,*")
        with pytest.raises(ConfigurationError, match=r"`\*` est refusé"):
            api_server._resolve_cors_origins()

    def test_bare_hostname_is_refused(self, monkeypatch):
        """`exemple.tld` sans schéma ne correspond à aucune origine : accepté, il ne
        matcherait jamais et le front serait bloqué sans que rien ne le dise."""
        monkeypatch.setenv("W40K_CORS_ORIGINS", "exemple.tld")
        with pytest.raises(ConfigurationError, match="n'est pas une origine"):
            api_server._resolve_cors_origins()

    def test_foreign_origin_gets_no_allow_header(self):
        """Contrôle sur la RÉPONSE réelle, pas sur le résolveur : c'est l'extension CORS montée
        au démarrage qui décide, et c'est elle qui était permissive."""
        client = app.test_client()
        response = client.get("/api/health", headers={"Origin": "https://evil.tld"})
        assert response.headers.get("Access-Control-Allow-Origin") is None, (
            "une origine non déclarée reçoit l'autorisation CORS : F3 est ouverte"
        )

    def test_declared_origin_is_allowed(self):
        """Contre-épreuve : sans elle, un CORS totalement cassé passerait le test ci-dessus."""
        declared = api_server.CORS_ORIGINS[0]
        client = app.test_client()
        response = client.get("/api/health", headers={"Origin": declared})
        assert response.headers.get("Access-Control-Allow-Origin") == declared


class TestExposeTracebackResolution:
    """F10. Le tri-état est le mécanisme : sans lui, le bloc `__main__` ne pourrait pas rouvrir
    le traceback en développement sans écraser un `W40K_EXPOSE_TRACEBACK=false` posé exprès."""

    def test_undefined_is_none(self, monkeypatch):
        monkeypatch.delenv("W40K_EXPOSE_TRACEBACK", raising=False)
        assert api_server._resolve_expose_traceback() is None

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values(self, monkeypatch, raw):
        monkeypatch.setenv("W40K_EXPOSE_TRACEBACK", raw)
        assert api_server._resolve_expose_traceback() is True

    @pytest.mark.parametrize("raw", ["0", "false", "FALSE", "no", "off"])
    def test_falsy_values(self, monkeypatch, raw):
        monkeypatch.setenv("W40K_EXPOSE_TRACEBACK", raw)
        assert api_server._resolve_expose_traceback() is False

    def test_garbage_is_a_startup_error(self, monkeypatch):
        """Une valeur illisible interprétée comme fausse serait sûre, mais une valeur illisible
        interprétée comme vraie serait la fuite : refuser les deux est la seule règle stable."""
        monkeypatch.setenv("W40K_EXPOSE_TRACEBACK", "peut-être")
        with pytest.raises(ConfigurationError, match="n'est ni vrai ni faux"):
            api_server._resolve_expose_traceback()


class TestUncaughtExceptionResponse:
    """F10. Avant, `handle_uncaught_exception` renvoyait `traceback` inconditionnellement :
    chemins du serveur, structure du code et versions installées, offerts à tout appelant."""

    @staticmethod
    def _handle(monkeypatch, expose):
        monkeypatch.setattr(api_server, "EXPOSE_TRACEBACK", expose)
        with app.test_request_context("/api/health"):
            try:
                raise RuntimeError("secret dans /home/greg/40k/services/api_server.py")
            except RuntimeError as error:
                result = api_server.handle_uncaught_exception(error)
                assert isinstance(result, tuple)
                response, status = result
            return response.get_json(), status

    def test_closed_by_default(self, monkeypatch):
        """`None` (variable non définie) doit se comporter comme fermé : c'est l'état d'une
        production où personne n'a rien déclaré."""
        payload, status = self._handle(monkeypatch, None)
        assert status == 500
        assert "traceback" not in payload
        assert "error_type" not in payload
        assert payload["error"] == "Internal server error", (
            "le message d'exception d'origine fuit : il porte un chemin de fichier serveur"
        )
        assert payload["error_id"]

    def test_explicitly_closed(self, monkeypatch):
        payload, _ = self._handle(monkeypatch, False)
        assert "traceback" not in payload
        assert "/home/greg" not in str(payload), "un chemin serveur est présent dans la réponse"

    def test_open_in_development(self, monkeypatch):
        """Contre-épreuve : sans elle, un handler qui ne renverrait JAMAIS de traceback
        passerait les deux tests ci-dessus, et le développement perdrait son diagnostic."""
        payload, status = self._handle(monkeypatch, True)
        assert status == 500
        assert "Traceback (most recent call last)" in payload["traceback"]
        assert payload["error_type"] == "RuntimeError"
        assert payload["error_id"]

    def test_http_exceptions_pass_through(self, monkeypatch):
        """`abort(404)` est un refus VOULU, pas un incident : le transformer en 500 générique
        casserait les réponses d'erreur légitimes de l'API."""
        monkeypatch.setattr(api_server, "EXPOSE_TRACEBACK", False)
        with app.test_request_context("/api/health"):
            error = NotFound()
            assert api_server.handle_uncaught_exception(error) is error


class TestSessionCookie:
    """F13. Le token vivait en `localStorage` : une seule XSS l'exfiltrait, pour sept jours
    d'accès complet."""

    @staticmethod
    def _login(client, **kwargs):
        return client.post(
            "/api/auth/login",
            json={"login": "pytest_user", "password": "pytest_password"},
            **kwargs,
        )

    def test_login_sets_httponly_strict_cookie(self, authenticated_api_client):
        client = _unauthenticated_client()
        response = self._login(client)
        assert response.status_code == 200

        cookies = _set_cookie_headers(response)
        assert len(cookies) == 1, f"cookie de session non posé : {response.headers}"
        header = cookies[0]
        assert "HttpOnly" in header, "sans HttpOnly, JavaScript relit le token : F13 est ouverte"
        assert "SameSite=Strict" in header, "sans SameSite, le cookie part sur une requête CSRF"
        assert "Path=/" in header

    def test_cookie_is_not_secure_over_plain_http(self, authenticated_api_client):
        """`Secure` posé en HTTP ferait IGNORER le cookie par le navigateur : le login du poste
        de développement (http://localhost:5175) n'authentifierait plus rien."""
        client = _unauthenticated_client()
        assert "Secure" not in _set_cookie_headers(self._login(client))[0]

    def test_cookie_is_secure_behind_https_proxy(self, authenticated_api_client, monkeypatch):
        """En production, TLS se termine sur nginx : `request.is_secure` voit du clair et
        priverait le cookie de `Secure`. C'est `X-Forwarded-Proto` qui porte la vérité, lu
        depuis un proxy de confiance uniquement."""
        monkeypatch.setattr(
            api_server, "TRUSTED_PROXIES",
            frozenset({api_server._normalize_ip("172.28.0.10")}),
        )
        client = _unauthenticated_client()
        response = self._login(
            client,
            environ_base={"REMOTE_ADDR": "172.28.0.10"},
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.7"},
        )
        assert response.status_code == 200
        assert "Secure" in _set_cookie_headers(response)[0]

    def test_untrusted_proxy_cannot_claim_https(self, authenticated_api_client, monkeypatch):
        """`X-Forwarded-Proto` est falsifiable : le lire d'une source non déclarée laisserait un
        client décider des attributs de son propre cookie."""
        monkeypatch.setattr(api_server, "TRUSTED_PROXIES", frozenset())
        client = _unauthenticated_client()
        response = self._login(client, headers={"X-Forwarded-Proto": "https"})
        assert "Secure" not in _set_cookie_headers(response)[0]

    def test_cookie_authenticates_with_csrf_header(self, authenticated_api_client):
        client = _unauthenticated_client()
        assert self._login(client).status_code == 200
        response = client.get(
            "/api/auth/me", headers={api_server.CSRF_HEADER_NAME: "web"}
        )
        assert response.status_code == 200, "le cookie posé au login n'authentifie pas"
        assert response.get_json()["user"]["login"] == "pytest_user"

    def test_cookie_without_csrf_header_is_refused(self, authenticated_api_client):
        """LE verrou anti-CSRF. Un cookie part avec toute requête vers l'origine, y compris
        déclenchée par un autre site ; un `<form>` cross-site ne peut poser aucun en-tête
        personnalisé, donc exiger celui-ci ferme le vecteur."""
        client = _unauthenticated_client()
        assert self._login(client).status_code == 200
        response = client.get("/api/auth/me")
        assert response.status_code == 401, (
            "une requête par cookie sans en-tête anti-CSRF est acceptée : un formulaire hébergé "
            "sur un autre site agirait au nom de l'utilisateur connecté"
        )

    def test_bearer_path_is_unchanged(self, authenticated_api_client):
        """Les clients hors navigateur (`scripts/pvp_smoke_test.py`, tests d'intégration) n'ont
        pas de bocal à cookies et ne posent pas l'en-tête anti-CSRF : leur chemin ne doit pas
        avoir bougé."""
        client = _unauthenticated_client()
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {authenticated_api_client}"},
        )
        assert response.status_code == 200

    def test_cookie_takes_priority_over_bearer(self, authenticated_api_client):
        """Un cookie périmé signifie que l'utilisateur est réellement déconnecté ; le repêcher
        par l'autre canal serait le repli que T1 interdit."""
        client = _unauthenticated_client()
        client.set_cookie(api_server.SESSION_COOKIE_NAME, "token-revoque")
        response = client.get(
            "/api/auth/me",
            headers={
                api_server.CSRF_HEADER_NAME: "web",
                "Authorization": f"Bearer {authenticated_api_client}",
            },
        )
        assert response.status_code == 401, (
            "un cookie invalide se fait rattraper par l'en-tête Bearer"
        )

    def test_logout_clears_the_cookie(self, authenticated_api_client):
        """Révoquer côté serveur suffit à rendre le token inopérant, mais laisserait un cookie
        d'apparence valide sur le poste — et le front boucherait en 401 au lieu d'aller au login."""
        client = _unauthenticated_client()
        assert self._login(client).status_code == 200

        response = client.post(
            "/api/auth/logout", headers={api_server.CSRF_HEADER_NAME: "web"}
        )
        assert response.status_code == 200
        cleared = _set_cookie_headers(response)
        assert len(cleared) == 1, "aucun Set-Cookie d'effacement sur le logout"
        assert f"{api_server.SESSION_COOKIE_NAME}=;" in cleared[0], cleared[0]
        # Les attributs sont répétés : un navigateur identifie un cookie par (nom, domaine,
        # chemin), et un effacement au `Path` divergent créerait un second cookie vide.
        assert "Path=/" in cleared[0]

        # Le cookie a effectivement disparu du client de test : la session est morte.
        assert client.get(
            "/api/auth/me", headers={api_server.CSRF_HEADER_NAME: "web"}
        ).status_code == 401

    def test_cookie_slides_with_the_session(self, authenticated_api_client):
        """L'échéance serveur est GLISSANTE (F2) ; sans ce rafraîchissement le cookie garderait
        celle du login et le navigateur déconnecterait l'utilisateur au septième jour alors que
        sa session est vivante."""
        client = _unauthenticated_client()
        token = self._login(client).get_json()["access_token"]

        # Échéance vieillie au-delà du seuil de renouvellement : la prochaine requête DOIT
        # prolonger la session, donc reposer le cookie.
        stale = int(time.time()) + api_server.SESSION_TTL_SECONDS - (
            api_server.SESSION_RENEW_AFTER_SECONDS + 60
        )
        _force_expiry(token, stale)

        response = client.get(
            "/api/auth/me", headers={api_server.CSRF_HEADER_NAME: "web"}
        )
        assert response.status_code == 200
        assert _session_expiry(token) > stale, "la session n'a pas été prolongée : rien à observer"
        assert _set_cookie_headers(response), (
            "session prolongée sans que le cookie suive : il expirera avant elle"
        )

    def test_frontend_declares_the_same_csrf_header(self):
        """Le front et le back portent CHACUN le nom de l'en-tête anti-CSRF — deux langages, donc
        pas de constante partageable. S'ils divergent, le backend refuse tout appel du front en
        401 : la panne est totale, immédiate, et illisible depuis l'un ou l'autre fichier.

        Le test lit la SOURCE du front plutôt que d'espérer qu'on pense aux deux endroits.
        """
        api_fetch = (
            Path(__file__).resolve().parents[3]
            / "frontend" / "src" / "services" / "apiFetch.ts"
        )
        assert api_fetch.exists(), f"client API du front introuvable : {api_fetch}"
        declaration = f'const CSRF_HEADER = "{api_server.CSRF_HEADER_NAME}";'
        assert declaration in api_fetch.read_text(encoding="utf-8"), (
            f"le front ne déclare pas {api_server.CSRF_HEADER_NAME!r} : tout appel authentifié "
            f"par cookie sera refusé en 401"
        )

    def test_no_cookie_slide_for_bearer_clients(self, authenticated_api_client):
        """Poser un cookie à un client `Bearer` lui remettrait un identifiant qu'il n'a pas
        demandé et ne relira jamais."""
        token = authenticated_api_client
        stale = int(time.time()) + api_server.SESSION_TTL_SECONDS - (
            api_server.SESSION_RENEW_AFTER_SECONDS + 60
        )
        _force_expiry(token, stale)

        client = _unauthenticated_client()
        response = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert _session_expiry(token) > stale, "la session n'a pas été prolongée : rien à observer"
        assert not _set_cookie_headers(response), (
            "un client Bearer reçoit un cookie de session non sollicité"
        )
