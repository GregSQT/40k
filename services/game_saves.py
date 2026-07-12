"""Saves d'une partie PvP : 1 fichier pickle par PARTIE, contenant plusieurs save-points.

- Une partie = un fichier ``{AAAAMMJJ_hh-mm}.pkl`` (nom fixé au save de début de partie).
- Chaque save-point = {meta, state} : état vivant capturé + métadonnées (turn/phase/#event, note, kind).
- ``Select`` navigue les save-points de la partie COURANTE ; ``Load`` charge une autre partie (à son
  game start) et la rend courante.

Aucun fallback masquant une erreur : un nom/id invalide lève.
"""

from __future__ import annotations

import os
import pickle
import re
from typing import Any, Dict, List, Optional

from services.game_snapshots import apply_live_state, capture_live_state

# Nom de fichier de partie : AAAAMMJJ_hh-mm .pkl
_PARTY_RE = re.compile(r"^(?P<name>\d{8}_\d{2}-\d{2})\.pkl$")


def _party_name_from_point_ts(point_ts: str) -> str:
    """"20260712-143052" -> "20260712_14-30" (précision minute pour le nom de partie)."""
    date, tm = point_ts.split("-", 1)
    return f"{date}_{tm[0:2]}-{tm[2:4]}"


def _point_meta(gs: Dict[str, Any], point_ts: str, note: str, kind: str) -> Dict[str, Any]:
    turn = int(gs["turn"])
    player = int(gs["current_player"])
    phase = str(gs["phase"])
    steps = int(gs.get("unit_activation_count", 0))  # "#" = activations d'UNITÉ (pas episode_steps)
    label = f"T{turn} · {phase[:1].upper()}{phase[1:]} · #{steps}"
    return {
        "id": point_ts,
        "turn": turn,
        "player": player,
        "phase": phase,
        "episode_steps": steps,
        "ts": point_ts,
        "label": label,
        "note": note,
        "kind": kind,
    }


class SaveStore:
    def __init__(self, directory: str) -> None:
        self._dir = directory
        self._current: Optional[str] = None  # nom de la partie courante

    def set_directory(self, directory: str) -> None:
        """Change le répertoire des parties (change de dossier → plus de partie courante)."""
        self._dir = directory
        self._current = None

    def current_party(self) -> Optional[str]:
        return self._current

    def _path(self, name: str) -> str:
        return os.path.join(self._dir, f"{name}.pkl")

    def _read_party(self, name: str) -> Dict[str, Any]:
        with open(self._path(name), "rb") as f:
            return pickle.load(f)

    def _write_party(self, name: str, data: Dict[str, Any]) -> None:
        os.makedirs(self._dir, exist_ok=True)
        with open(self._path(name), "wb") as f:
            pickle.dump(data, f)

    def start_party(self, engine: Any, party_name: str, point_ts: str) -> Dict[str, Any]:
        """Crée une nouvelle partie (fichier) avec le save-point de départ (kind game_start). Devient courante."""
        gs = engine.game_state
        meta = _point_meta(gs, point_ts, "", "game_start")
        party = {"name": party_name, "points": [{"meta": meta, "state": capture_live_state(engine)}]}
        self._write_party(party_name, party)
        self._current = party_name
        return {"name": party_name}

    def add_point(self, engine: Any, point_ts: str, note: str = "", kind: str = "manual") -> Dict[str, Any]:
        """Ajoute un save-point à la partie courante (en crée une à la volée si aucune n'est courante)."""
        if self._current is None:
            self._current = _party_name_from_point_ts(point_ts)
        party = (
            self._read_party(self._current)
            if os.path.exists(self._path(self._current))
            else {"name": self._current, "points": []}
        )
        meta = _point_meta(engine.game_state, point_ts, note, kind)
        party["points"].append({"meta": meta, "state": capture_live_state(engine)})
        self._write_party(self._current, party)
        return meta

    def list_points(self) -> List[Dict[str, Any]]:
        """Save-points de la partie courante (pour Select), plus récents d'abord."""
        if self._current is None or not os.path.exists(self._path(self._current)):
            return []
        pts = [p["meta"] for p in self._read_party(self._current)["points"]]
        pts.sort(key=lambda m: m["ts"], reverse=True)
        return pts

    def list_parties(self) -> List[Dict[str, Any]]:
        """Liste des parties sauvegardées (pour Load), plus récentes d'abord."""
        if not os.path.isdir(self._dir):
            return []
        parties: List[Dict[str, Any]] = []
        for fn in os.listdir(self._dir):
            m = _PARTY_RE.match(fn)
            if m:
                parties.append({"name": m.group("name")})
        parties.sort(key=lambda p: p["name"], reverse=True)
        return parties

    def restore_point(self, engine: Any, point_id: str) -> Dict[str, Any]:
        """Restaure un save-point (par id) de la partie courante."""
        if self._current is None:
            raise ValueError("aucune partie courante")
        for p in self._read_party(self._current)["points"]:
            if p["meta"]["id"] == point_id:
                apply_live_state(engine, p["state"])
                return p["meta"]
        raise KeyError(f"save-point introuvable: {point_id}")

    def load_party_start(self, engine: Any, name: str) -> Dict[str, Any]:
        """Charge une partie à son game_start (ou son 1er point) et la rend courante."""
        if not _PARTY_RE.match(f"{name}.pkl"):
            raise ValueError(f"nom de partie invalide: {name!r}")
        if not os.path.exists(self._path(name)):
            raise FileNotFoundError(f"partie introuvable: {name}")
        points = self._read_party(name)["points"]
        if not points:
            raise ValueError(f"partie vide: {name}")
        start = next((p for p in points if p["meta"]["kind"] == "game_start"), points[0])
        apply_live_state(engine, start["state"])
        self._current = name
        return start["meta"]

    def delete_all(self) -> int:
        """Supprime toutes les parties. Retourne le nombre de fichiers effacés."""
        if not os.path.isdir(self._dir):
            return 0
        n = 0
        for fn in list(os.listdir(self._dir)):
            if _PARTY_RE.match(fn):
                os.remove(os.path.join(self._dir, fn))
                n += 1
        self._current = None
        return n
