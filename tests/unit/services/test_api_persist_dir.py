"""Répertoire de persistance et snapshots (F7, F11) — `Documentation/Reference/infra/Security.md`.

Verrouille l'invariant : **le client ne choisit plus où le serveur écrit**. Le répertoire de
persistance vient de l'environnement du process ; un `directory` reçu en requête est refusé, pas
ignoré. Verrouille aussi la disparition du sélecteur natif (`pick-directory`, `subprocess`) et de
la persistance pickle des snapshots.
"""

from __future__ import annotations

import os

import pytest

import services.api_server as api_server
from services.api_server import app
from shared.data_validation import ConfigurationError


class TestPersistDirIsServerSide:

    def test_directory_in_request_is_refused(self, monkeypatch, tmp_path):
        """Un `directory` envoyé par le client → 400, et le répertoire du serveur ne bouge pas.

        Rejet explicite plutôt qu'ignorance silencieuse (T1) : un client qui croit choisir sa
        destination doit l'apprendre, pas écrire ailleurs qu'il ne pense.
        """
        monkeypatch.setattr(api_server, "_PERSIST_DIR", str(tmp_path))
        cible = tmp_path / "ailleurs"
        response = app.test_client().post(
            "/api/game/snapshot/persist", json={"enabled": True, "directory": str(cible)}
        )
        assert response.status_code == 400
        assert "directory" in response.get_json()["error"]
        assert not cible.exists(), "le répertoire du client a été créé sur disque"
        assert api_server._PERSIST_DIR == str(tmp_path)

    def test_toggle_without_directory_still_works(self, monkeypatch, tmp_path):
        """Contre-épreuve du « tout est refusé » : le toggle seul passe toujours."""
        monkeypatch.setattr(api_server, "_PERSIST_DIR", str(tmp_path))
        monkeypatch.setattr(api_server, "_persist_save_config", lambda: None)
        # Le flag est une globale de MODULE : sans restauration, il resterait à True pour tout le
        # worker et un test PvP suivant écrirait dans le vrai `logs/pvp_saves`.
        monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", False)
        response = app.test_client().post("/api/game/snapshot/persist", json={"enabled": True})
        assert response.status_code == 200
        assert response.get_json()["persist_enabled"] is True

    def test_enabling_persist_writes_no_pickle(self, monkeypatch, tmp_path):
        """Aucun `.pkl` n'est plus écrit : le fichier de snapshots était produit à chaque
        capture et relu par personne (la reprise passe par les saves)."""
        monkeypatch.setattr(api_server, "_PERSIST_DIR", str(tmp_path))
        monkeypatch.setattr(api_server, "_persist_save_config", lambda: None)
        monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", False)  # cf. test ci-dessus
        app.test_client().post("/api/game/snapshot/persist", json={"enabled": True})
        assert list(tmp_path.glob("**/*.pkl")) == []

    def test_env_var_overrides_the_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv("W40K_PERSIST_DIR", str(tmp_path))
        assert api_server._resolve_persist_dir() == str(tmp_path)

    def test_absent_env_var_falls_back_to_logs(self, monkeypatch):
        monkeypatch.delenv("W40K_PERSIST_DIR", raising=False)
        assert api_server._resolve_persist_dir().endswith(os.sep + "logs")

    def test_empty_env_var_raises(self, monkeypatch):
        """Variable définie mais vide = erreur au démarrage, jamais un défaut silencieux :
        un chemin vide écrirait dans le répertoire courant du process sans que rien ne le dise."""
        monkeypatch.setenv("W40K_PERSIST_DIR", "   ")
        with pytest.raises(ConfigurationError, match="W40K_PERSIST_DIR"):
            api_server._resolve_persist_dir()


class TestPickDirectoryIsGone:
    """F11 : `subprocess`/`powershell.exe` n'est plus atteignable depuis le réseau — la route
    est supprimée, pas seulement authentifiée."""

    def test_route_does_not_exist(self):
        assert "/api/game/pick-directory" not in {
            rule.rule for rule in app.url_map.iter_rules()
        }
        assert not hasattr(api_server, "pick_directory")

    def test_authenticated_client_gets_404(self):
        """Authentifié, donc au-delà de la porte : 404 prouve l'absence de la route (un client
        anonyme recevrait 401 même pour une URL inexistante)."""
        assert app.test_client().post("/api/game/pick-directory").status_code == 404
