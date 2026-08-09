"""Une save produite par une VRAIE partie se relit à travers le dépickle restreint (F7).

Le test unitaire du garde (`tests/unit/services/test_game_saves_restricted_unpickle.py`) travaille
sur des formes reconstituées : il prouve que le gadget est refusé, pas que la liste blanche couvre
ce que le moteur écrit réellement. Une classe capturée dans l'état et absente de `_ALLOWED_CLASSES`
casserait tout chargement de partie — c'est CE cas que ce fichier verrouille, avec un état produit
par le moteur, pas par un stub.
"""

from __future__ import annotations

import services.api_server as api_server
from services.game_saves import SaveStore


def test_enabling_persist_mid_game_starts_recording(game, tmp_path, monkeypatch):
    """Activer l'enregistrement EN COURS de partie doit ouvrir une partie de saves.

    `start_party` n'est atteint qu'au démarrage, quand la persistance est déjà active. Sans amorce
    à la transition off→on, `_timeline_capture` sort sur `if not party` : l'UI annonce
    l'enregistrement actif et pas une seule row n'est écrite de toute la partie.
    """
    store = SaveStore(str(tmp_path / "parties"))
    monkeypatch.setattr(api_server, "_SAVE_STORE", store)
    monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", False)
    monkeypatch.setattr(api_server, "_persist_save_config", lambda: None)
    assert store.current_party() is None, "une partie est déjà ouverte : le test ne prouve rien"

    response = game._client.post("/api/game/snapshot/persist", json={"enabled": True})

    assert response.status_code == 200
    assert store.current_party() is not None, "aucune partie de saves ouverte : rien ne s'enregistre"
    assert store.list_all_rows(), "partie ouverte mais vide : pas d'ancre de départ"


def test_real_game_state_survives_the_restricted_unpickle(game, tmp_path, monkeypatch):
    """Save d'une partie réelle → relecture par `SaveStore.point` (chemin Select/view/Resume)."""
    store = SaveStore(str(tmp_path / "parties"))
    monkeypatch.setattr(api_server, "_SAVE_STORE", store)

    store.start_party(api_server.engine, "partie_reelle", "20260810-120000")
    meta = store.add_point(api_server.engine, "20260810-120100", "verrou", "manual")

    row = store.point(meta["id"])

    # L'état relu doit être RICHE : un state vide traverserait n'importe quelle liste blanche et
    # rendrait ce test vert sans rien prouver (vert vacant).
    game_state = row["state"]["game_state"]
    assert game_state["units"], "état capturé sans unités : le test ne prouve rien"
    assert _contains_non_builtin(row["state"]), (
        "état capturé fait de types de base seulement : il traverserait n'importe quelle liste "
        "blanche, ce test ne verrouillerait rien"
    )


def _contains_non_builtin(value, depth: int = 0) -> bool:
    """Vrai si l'état porte au moins un objet qui DOIT passer par `find_class` (numpy,
    `ParsedWeaponRule`, …). Les types de base ont leurs propres opcodes et ne prouvent rien."""
    if depth > 6:
        return False
    if isinstance(value, dict):
        return any(
            _contains_non_builtin(v, depth + 1) for v in list(value.values())[:200]
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_non_builtin(v, depth + 1) for v in list(value)[:200])
    return not isinstance(value, (bool, int, float, str, bytes, type(None)))
