"""Symboles partagés entre conftest.py et les fichiers de test PvP.

Séparés de conftest.py pour éviter l'import direct d'un conftest — pratique interdite
par test_fabriques_partagees.py (deux copies module, état dupliqué).
Les fixtures pytest (``api_isolated``, ``game``, …) restent dans conftest.py : pytest les
y découvre automatiquement ; les importer d'un fichier quelconque n'aurait aucun effet.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

import services.api_server as api_server
from services.api_server import app

_TEST_AUTH_USER = {
    "user_id": 1,
    "login": "integration-tests",
    "profile_id": 1,
    "profile_code": "test",
    "token": "integration-tests-token",
    "expires_at": 1 << 62,
}
_TEST_PERMISSIONS = {
    "game_modes": ["pvp", "pvp_test", "pve", "pve_test"],
    "options": {},
}

INTEGRATION_SCENARIO = "config/board/44x60x5/scenario/scenario_pvp_integration.json"


class ActionRejected(RuntimeError):
    """Le backend a refusé l'action (``success: False`` ou HTTP != 200)."""

    def __init__(self, action: str, error: Any, status: int):
        super().__init__(f"action {action!r} refusée (HTTP {status}) : {error}")
        self.action = action
        self.error = error
        self.status = status


class ActionsExhausted(AssertionError):
    """Budget d'actions épuisé dans play_nominal sans atteindre la condition d'arrêt."""


class GameClient:
    """Pilote une partie via les vraies routes Flask, comme le front.

    ``check`` est appelé après chaque action réussie : c'est le crochet des invariants
    transversaux (T2), pour qu'aucune tranche n'ait à penser à les revalider.
    """

    def __init__(self, client, check=None):
        self._client = client
        self._check = check
        self.state: Dict[str, Any] = {}
        self.start_state: Dict[str, Any] = {}

    # -- transport --------------------------------------------------------- #

    def start(
        self,
        mode_code: str = "pvp",
        board_path: Optional[str] = None,
        scenario_file: Optional[str] = INTEGRATION_SCENARIO,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"mode_code": mode_code}
        if board_path is not None:
            payload["board_path"] = board_path
        if scenario_file is not None:
            payload["scenario_file"] = scenario_file
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

    FIGHT_SUBPHASE_EXIT = {
        "pile_in": "end_pile_in",
        "fight": "skip_fight",
        "consolidate": "end_consolidation",
    }

    def pending_faction_decision(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        """La réponse à une décision de 08.04 en attente, ou None."""
        pending_oath = self.state.get("pending_oath_selection")
        if pending_oath is not None and int(pending_oath) == self.current_player:
            targets = self.alive_ids(self.enemy_player())
            if not targets:
                raise AssertionError(
                    "designation d'Oath en attente sans aucune cible vivante : le moteur ne la "
                    "pose que s'il en existe une"
                )
            return "select_oath_target", {"unitId": targets[0]}
        decision = self.state.get("pending_agent_decision")
        if decision is not None and decision["player"] == self.current_player:
            return "agent_decision", {"option_index": 0}
        return None

    def nominal_action(self) -> Tuple[str, Dict[str, Any]]:
        """L'action qui fait avancer la partie depuis l'état courant, sans rien tenter d'autre."""
        faction_decision = self.pending_faction_decision()
        if faction_decision is not None:
            return faction_decision
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
        return "advance_phase", {}

    def play_nominal(self, max_actions: int = 1000, until=None) -> int:
        """Déroule la partie par actions nominales. Renvoie le nombre d'actions jouées."""
        for played in range(max_actions):
            if until is not None and until(self):
                return played
            if until is None and self.state.get("game_over"):
                return played
            action, payload = self.nominal_action()
            self.act(action, **payload)
        raise ActionsExhausted(f"{max_actions} actions sans atteindre la condition d'arrêt")

    def drain_to(self, target_phase: str) -> Dict[str, Any]:
        """Skippe toutes les activations jusqu'à atteindre ``target_phase``."""
        self.play_nominal(max_actions=500, until=lambda c: c.phase == target_phase)
        return self.state

    @property
    def phase(self) -> str:
        return self.state["phase"]

    @property
    def current_player(self) -> int:
        return int(self.state["current_player"])

    def enemy_player(self) -> int:
        return 2 if self.current_player == 1 else 1


_MISSING = object()


def assert_game_states_equal(a: dict, b: dict, label: str = "") -> None:
    differences = sorted(k for k in set(a) | set(b) if a.get(k, _MISSING) != b.get(k, _MISSING))
    assert not differences, f"{label} : {differences}" if label else f"états différents : {differences}"


@contextmanager
def _in_memory_write_cursor(immediate: bool = False):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        yield connection.cursor()
    finally:
        connection.close()
