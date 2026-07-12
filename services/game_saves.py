"""Saves manuelles d'une partie PvP (un fichier plat par save).

Une save = capture de l'état vivant de l'engine à un instant arbitraire (typiquement une frontière
d'activation d'unité = un « event »). Écrite en pickle sous ``logs/pvp_saves/``.

Les métadonnées (turn, player, phase, episode_steps, timestamp) sont encodées dans le NOM de fichier
afin que le listing du menu Select se construise sans désérialiser les états.

Aucun fallback masquant une erreur : un id/nom invalide lève.
"""

from __future__ import annotations

import json
import os
import pickle
import re
from typing import Any, Dict, List

from services.game_snapshots import apply_live_state, capture_live_state

# nom : save__T{turn}_P{player}_{phase}_e{steps}__{timestamp}.pkl
_FILENAME_RE = re.compile(
    r"^save__T(?P<turn>\d+)_P(?P<player>\d+)_(?P<phase>[a-z]+)_e(?P<steps>\d+)__(?P<ts>\d{8}-\d{6})\.pkl$"
)


def _meta_from_match(m: "re.Match[str]", filename: str) -> Dict[str, Any]:
    turn = int(m.group("turn"))
    phase = m.group("phase")
    steps = int(m.group("steps"))
    ts = m.group("ts")
    label = f"T{turn} · {phase[:1].upper()}{phase[1:]} · #{steps}"
    return {
        "id": filename,
        "turn": turn,
        "player": int(m.group("player")),
        "phase": phase,
        "episode_steps": steps,
        "ts": ts,
        "label": label,
    }


class SaveStore:
    def __init__(self, directory: str) -> None:
        self._dir = directory

    def set_directory(self, directory: str) -> None:
        """Change le répertoire des saves (les saves existantes de l'ancien dossier ne sont pas déplacées)."""
        self._dir = directory

    def _note_path(self, pkl_filename: str) -> str:
        """Sidecar JSON portant la note optionnelle (le nom de fichier ne peut pas la porter)."""
        return os.path.join(self._dir, pkl_filename[:-4] + ".json")

    def _read_sidecar(self, pkl_filename: str) -> Dict[str, str]:
        p = self._note_path(pkl_filename)
        if not os.path.exists(p):
            return {"note": "", "kind": "manual"}
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"note": str(data.get("note", "")), "kind": str(data.get("kind", "manual"))}

    def save_current(
        self, engine: Any, timestamp: str, note: str = "", kind: str = "manual"
    ) -> Dict[str, Any]:
        """Capture l'état vivant et l'écrit dans un fichier (+ sidecar de note). Retourne la meta créée.

        ``timestamp`` (format ``YYYYmmdd-HHMMSS``) est fourni par l'appelant (l'engine/serveur ne
        dépend pas d'une horloge testable dans ce module). ``note`` est optionnelle."""
        gs = engine.game_state
        turn = int(gs["turn"])
        player = int(gs["current_player"])
        phase = str(gs["phase"])
        steps = int(gs.get("episode_steps", 0))
        filename = f"save__T{turn}_P{player}_{phase}_e{steps}__{timestamp}.pkl"
        if not _FILENAME_RE.match(filename):
            raise ValueError(f"métadonnées de save invalides pour le nom: {filename!r}")
        os.makedirs(self._dir, exist_ok=True)
        path = os.path.join(self._dir, filename)
        captured = capture_live_state(engine)
        with open(path, "wb") as f:
            pickle.dump(captured, f)
        with open(self._note_path(filename), "w", encoding="utf-8") as f:
            json.dump({"note": note, "kind": kind}, f, ensure_ascii=False)
        meta = _meta_from_match(_FILENAME_RE.match(filename), filename)
        meta["note"] = note
        meta["kind"] = kind
        return meta

    def list_meta(self) -> List[Dict[str, Any]]:
        """Métadonnées de toutes les saves (plus récentes d'abord), sans charger les états."""
        if not os.path.isdir(self._dir):
            return []
        metas: List[Dict[str, Any]] = []
        for fn in os.listdir(self._dir):
            m = _FILENAME_RE.match(fn)
            if m:
                metas.append({**_meta_from_match(m, fn), **self._read_sidecar(fn)})
        metas.sort(key=lambda x: x["ts"], reverse=True)
        return metas

    def delete_all(self) -> int:
        """Supprime toutes les saves (pickles + sidecars de note). Retourne le nombre de saves effacées."""
        if not os.path.isdir(self._dir):
            return 0
        n = 0
        for fn in list(os.listdir(self._dir)):
            if _FILENAME_RE.match(fn):
                os.remove(os.path.join(self._dir, fn))
                note = self._note_path(fn)
                if os.path.exists(note):
                    os.remove(note)
                n += 1
        return n

    def load(self, engine: Any, save_id: str) -> None:
        """Remplace l'état vivant de l'engine par la save ``save_id`` (= nom de fichier)."""
        if not _FILENAME_RE.match(save_id):
            raise ValueError(f"id de save invalide: {save_id!r}")
        path = os.path.join(self._dir, save_id)
        if not os.path.exists(path):
            raise FileNotFoundError(f"save introuvable: {save_id}")
        with open(path, "rb") as f:
            captured = pickle.load(f)
        apply_live_state(engine, captured)
