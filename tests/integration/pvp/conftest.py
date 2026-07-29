"""Socle des tests d'intégration PvP : une vraie partie pilotée en in-process.

Pourquoi in-process et pas un script HTTP externe (``scripts/pvp_smoke_test.py``) :
tous les jets de dés du moteur passent par le ``random`` global du stdlib
(``combat_utils.resolve_dice_value``, ``charge_handlers`` 2D6, ``roll_d6`` injecté dans
``attack_sequence``). Le ``deterministic_seed`` autouse de ``tests/conftest.py`` pose donc
la seed du moteur lui-même : les résultats de tir/charge/mêlée sont reproductibles, ce
qu'un client HTTP dans un autre process ne peut pas obtenir.

Le script HTTP reste le smoke test de la vraie stack (réseau + auth + serveur réel) ;
ces tests-ci couvrent le contrat de données que le front consomme.

Isolation exigée (aucune écriture hors de la mémoire du test) :
  - ``config/users.db`` n'est JAMAIS ouverte (auth et permissions injectées) ;
  - la persistance des snapshots/saves est coupée : à l'import, ``api_server`` charge
    ``logs/save_config.json`` qui active la persistance disque en usage normal.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import pytest

import services.api_server as api_server
from services.api_server import app

# Profil de test : autorise tous les modes de jeu sans lire config/users.db.
_TEST_AUTH_USER = {
    "user_id": 1,
    "login": "integration-tests",
    "profile_id": 1,
    "profile_code": "test",
}
_TEST_PERMISSIONS = {
    "game_modes": ["pvp", "pvp_test", "pve", "pve_test"],
    "options": {},
}


class ActionRejected(RuntimeError):
    """Le backend a refusé l'action (``success: False`` ou HTTP != 200)."""

    def __init__(self, action: str, error: Any, status: int):
        super().__init__(f"action {action!r} refusée (HTTP {status}) : {error}")
        self.action = action
        self.error = error
        self.status = status


class GameClient:
    """Pilote une partie via les vraies routes Flask, comme le front.

    ``check`` est appelé après chaque action réussie : c'est le crochet des invariants
    transversaux (T2), pour qu'aucune tranche n'ait à penser à les revalider.
    """

    def __init__(self, client, check=None):
        self._client = client
        self._check = check
        self.state: Dict[str, Any] = {}
        # La route /start enrichit sa réponse de champs que /state et /action ne renvoient
        # pas (``max_turns``, ``pve_mode``) : on garde l'état initial pour pouvoir s'y
        # référer sans confondre « absent du contrat » et « disparu ».
        self.start_state: Dict[str, Any] = {}

    # -- transport --------------------------------------------------------- #

    def start(self, mode_code: str = "pvp_test", board_path: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"mode_code": mode_code}
        if board_path is not None:
            payload["board_path"] = board_path
        response = self._client.post("/api/game/start", json=payload)
        body = response.get_json()
        if response.status_code != 200 or not body.get("success"):
            raise ActionRejected("start", body.get("error"), response.status_code)
        self.state = body["game_state"]
        self.start_state = self.state
        if self._check is not None:
            self._check(self.state, "start")
        return self.state

    def refresh(self) -> Dict[str, Any]:
        response = self._client.get("/api/game/state")
        body = response.get_json()
        if response.status_code != 200 or not body.get("success"):
            raise ActionRejected("state", body.get("error"), response.status_code)
        self.state = body["game_state"]
        return self.state

    def act(self, action: str, **payload: Any) -> Dict[str, Any]:
        """Exécute une action attendue comme LÉGALE ; lève si le moteur la refuse."""
        ok, body = self.try_act(action, **payload)
        if not ok:
            raise ActionRejected(action, body.get("error"), body.get("_status", 200))
        return body

    def try_act(self, action: str, **payload: Any) -> Tuple[bool, Dict[str, Any]]:
        """Exécute une action pouvant être refusée ; renvoie (accepté, réponse).

        L'état local est resynchronisé dans les deux cas : un rejet ne doit rien changer,
        et c'est précisément ce que les tests de rejet vérifient.
        """
        response = self._client.post("/api/game/action", json={"action": action, **payload})
        body = response.get_json()
        if body is None:
            raise AssertionError(f"action {action!r} : réponse non-JSON (HTTP {response.status_code})")
        body["_status"] = response.status_code
        accepted = response.status_code == 200 and bool(body.get("success"))
        if "game_state" in body:
            self.state = body["game_state"]
        else:
            self.refresh()
        if self._check is not None:
            self._check(self.state, action)
        return accepted, body

    # -- lectures d'état ---------------------------------------------------- #

    def unit(self, unit_id: Any) -> Dict[str, Any]:
        for candidate in self.state["units"]:
            if str(candidate["id"]) == str(unit_id):
                return candidate
        raise KeyError(f"unité {unit_id} absente de game_state.units")

    def pool(self, name: str) -> List[str]:
        if name not in self.state:
            raise KeyError(f"pool {name!r} absent du game_state")
        return [str(uid) for uid in self.state[name]]

    def alive_ids(self, player: Optional[int] = None) -> List[str]:
        return [
            str(u["id"])
            for u in self.state["units"]
            if u["HP_CUR"] > 0 and (player is None or u["player"] == player)
        ]

    def models_of(self, unit_id: Any) -> List[str]:
        squad_models = self.state["squad_models"]
        key = str(unit_id)
        if key not in squad_models:
            raise KeyError(f"unité {key} absente de squad_models")
        return [str(m) for m in squad_models[key]]

    # -- pilotage ----------------------------------------------------------- #

    POOL_BY_PHASE = {
        "command": "command_activation_pool",
        "move": "move_activation_pool",
        "shoot": "shoot_activation_pool",
        "charge": "charge_activation_pool",
    }

    # Chaque sous-phase de fight a son propre verbe de sortie : le dispatch fight
    # (fight_handlers.py, ``sub == "pile_in"`` / ``"fight"``) ignore SILENCIEUSEMENT les
    # verbes des autres sous-phases en renvoyant success=True — d'où le verbe explicite.
    FIGHT_SUBPHASE_EXIT = {
        "pile_in": "end_pile_in",
        "fight": "skip_fight",
        "consolidate": "end_consolidation",
    }

    def nominal_action(self) -> Tuple[str, Dict[str, Any]]:
        """L'action qui fait avancer la partie depuis l'état courant, sans rien tenter d'autre."""
        if self.phase == "fight":
            subphase = self.state["fight_subphase"]
            if subphase not in self.FIGHT_SUBPHASE_EXIT:
                raise AssertionError(f"sous-phase de fight inconnue : {subphase!r}")
            return self.FIGHT_SUBPHASE_EXIT[subphase], {}
        pool_key = self.POOL_BY_PHASE.get(self.phase)
        if pool_key is None:
            raise AssertionError(f"phase sans pool drainable : {self.phase!r}")
        pool = self.pool(pool_key)
        if pool:
            return "skip", {"unitId": pool[0]}
        # Seule la transition move→shoot demande un advance_phase explicite (le moteur
        # diffère l'init du tir hors gym, w40k_core.py:6192-6210) ; les autres basculent
        # d'elles-mêmes, mais le verbe reste accepté et sans effet de bord.
        return "advance_phase", {}

    def play_nominal(self, max_actions: int = 1000, until=None) -> int:
        """Déroule la partie par actions nominales. Renvoie le nombre d'actions jouées.

        ``until`` : prédicat sur le client ; l'exécution s'arrête dès qu'il est vrai.
        Sans prédicat, va jusqu'à ``game_over``.
        """
        for played in range(max_actions):
            if until is not None and until(self):
                return played
            if until is None and self.state.get("game_over"):
                return played
            action, payload = self.nominal_action()
            self.act(action, **payload)
        raise AssertionError(f"{max_actions} actions sans atteindre la condition d'arrêt")

    def drain_to(self, target_phase: str) -> Dict[str, Any]:
        """Skippe toutes les activations jusqu'à atteindre ``target_phase``."""
        self.play_nominal(max_actions=500, until=lambda c: c.phase == target_phase)
        if self.phase != target_phase:
            raise AssertionError(f"phase {self.phase!r} au lieu de {target_phase!r}")
        return self.state

    @property
    def phase(self) -> str:
        return self.state["phase"]

    @property
    def current_player(self) -> int:
        return int(self.state["current_player"])

    def enemy_player(self) -> int:
        return 2 if self.current_player == 1 else 1


@pytest.fixture
def api_isolated(monkeypatch):
    """Neutralise les effets de bord hors mémoire : users.db et persistance disque."""
    monkeypatch.setattr(api_server, "_get_authenticated_user_or_response", lambda: (_TEST_AUTH_USER, None))
    monkeypatch.setattr(api_server, "_resolve_permissions_for_profile", lambda _conn, _pid: _TEST_PERMISSIONS)
    monkeypatch.setattr(api_server, "_get_auth_db_connection", lambda: sqlite3.connect(":memory:"))
    # api_server charge logs/save_config.json à l'import : en usage normal la persistance
    # des snapshots et l'autosave sont actifs et écriraient sur le disque de l'utilisateur.
    monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", False)
    monkeypatch.setattr(api_server, "_PERSIST_DIR_SET", False)
    monkeypatch.setattr(api_server, "_AUTOSAVE_ENABLED", False)
    yield
    # Le moteur est une globale de module : ne pas laisser la partie d'un test au suivant.
    api_server.engine = None


@pytest.fixture
def game(api_isolated):
    """Partie ``pvp_test`` démarrée, invariants transversaux armés."""
    from tests.integration.pvp.invariants import assert_state_invariants

    with app.test_client() as flask_client:
        client = GameClient(flask_client, check=assert_state_invariants)
        client.start("pvp_test")
        yield client


@pytest.fixture
def game_unchecked(api_isolated):
    """Même partie, SANS revalidation automatique.

    Réservé aux tests qui vérifient les invariants eux-mêmes (sinon un échec d'invariant
    ferait échouer le test avant son assertion propre, en masquant ce qu'il mesurait).
    """
    with app.test_client() as flask_client:
        client = GameClient(flask_client)
        client.start("pvp_test")
        yield client
