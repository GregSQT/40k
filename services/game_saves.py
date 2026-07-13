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
import tempfile
from typing import Any, Dict, List, Optional

from services.game_snapshots import apply_live_state, capture_live_state

# Nom de fichier de partie auto (début de partie) : AAAAMMJJ_hh-mm (via _party_name_from_point_ts).
# Les forks peuvent porter un nom libre (sanitizé), donc le listing n'impose plus ce format.

# Caractères interdits dans un nom de fichier (Windows/Unix) + noms réservés Windows.
_FORBIDDEN_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Ordre de progression d'une partie : tour → phase → nb d'activations d'unité (compteur global
# monotone). Sert à déterminer les save-points « postérieurs » à un point de reprise (fork/écrasement).
_PHASE_RANK = {"deployment": 0, "command": 1, "move": 2, "shoot": 3, "charge": 4, "fight": 5}


def _phase_rank(phase: str) -> int:
    if phase not in _PHASE_RANK:
        raise ValueError(f"phase inconnue pour l'ordre de progression: {phase!r}")
    return _PHASE_RANK[phase]


def _progress_key_from_meta(meta: Dict[str, Any]) -> tuple:
    return (int(meta["turn"]), _phase_rank(str(meta["phase"])), int(meta["episode_steps"]))


def progress_key_from_gs(gs: Dict[str, Any]) -> tuple:
    """Clé de progression depuis l'état vivant (pour un point de reprise sans save-point, ex. rewind)."""
    return (int(gs["turn"]), _phase_rank(str(gs["phase"])), int(gs.get("unit_activation_count", 0)))


def sanitize_party_name(name: str) -> str:
    """Nom de fichier de partie sûr (fork) : retire les caractères interdits OS, refuse vide/réservé."""
    base = _FORBIDDEN_NAME_CHARS.sub("_", str(name)).strip(" .")
    if not base:
        raise ValueError("nom de sauvegarde vide ou invalide")
    if len(base) > 100:
        base = base[:100].strip(" .")
    if base.upper() in _WINDOWS_RESERVED:
        raise ValueError(f"nom de sauvegarde réservé par l'OS: {base!r}")
    return base


def _assert_safe_party_name(name: str) -> None:
    """Refuse toute traversée de chemin / séparateur dans un nom de partie manipulé."""
    if name != os.path.basename(name) or name in ("", ".", ".."):
        raise ValueError(f"nom de partie invalide: {name!r}")


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

    def set_current(self, name: str) -> None:
        """Définit la partie courante (contexte de navigation Select), sans muter l'engine."""
        self._current = name

    def _path(self, name: str) -> str:
        return os.path.join(self._dir, f"{name}.pkl")

    def _read_party(self, name: str) -> Dict[str, Any]:
        with open(self._path(name), "rb") as f:
            return pickle.load(f)

    def _write_party(self, name: str, data: Dict[str, Any]) -> None:
        """Écriture atomique : fichier temporaire (même répertoire) + os.replace, pour ne jamais
        corrompre une partie existante si un crash survient en cours d'écriture (fork/troncature/save)."""
        os.makedirs(self._dir, exist_ok=True)
        path = self._path(name)
        fd, tmp = tempfile.mkstemp(dir=self._dir, prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                pickle.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

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
        """Liste des parties sauvegardées (pour Load), plus récentes d'abord.
        Inclut les forks à nom libre (tout fichier .pkl), pas seulement les noms horodatés."""
        if not os.path.isdir(self._dir):
            return []
        parties: List[Dict[str, Any]] = []
        for fn in os.listdir(self._dir):
            if fn.endswith(".pkl") and os.path.isfile(os.path.join(self._dir, fn)):
                parties.append({"name": fn[:-4]})
        parties.sort(key=lambda p: p["name"], reverse=True)
        return parties

    def point(self, point_id: str) -> Dict[str, Any]:
        """Retourne le save-point {meta, state} (partie courante) SANS l'appliquer (pour l'aperçu view)."""
        if self._current is None:
            raise ValueError("aucune partie courante")
        for p in self._read_party(self._current)["points"]:
            if p["meta"]["id"] == point_id:
                return p
        raise KeyError(f"save-point introuvable: {point_id}")

    def restore_point(self, engine: Any, point_id: str) -> Dict[str, Any]:
        """Restaure un save-point (par id) de la partie courante (commit destructif)."""
        p = self.point(point_id)
        apply_live_state(engine, p["state"])
        return p["meta"]

    def party_start_point(self, name: str) -> Dict[str, Any]:
        """Retourne le save-point de départ d'une partie {meta, state} SANS l'appliquer (aperçu view)."""
        _assert_safe_party_name(name)
        if not os.path.exists(self._path(name)):
            raise FileNotFoundError(f"partie introuvable: {name}")
        points = self._read_party(name)["points"]
        if not points:
            raise ValueError(f"partie vide: {name}")
        return next((p for p in points if p["meta"]["kind"] == "game_start"), points[0])

    def load_party_start(self, engine: Any, name: str) -> Dict[str, Any]:
        """Charge une partie à son game_start (commit destructif) et la rend courante."""
        start = self.party_start_point(name)
        apply_live_state(engine, start["state"])
        self._current = name
        return start["meta"]

    def point_progress_key(self, point_id: str) -> tuple:
        """Clé de progression d'un save-point de la partie courante (point de reprise Select→Resume)."""
        return _progress_key_from_meta(self.point(point_id)["meta"])

    def party_start_progress_key(self, name: str) -> tuple:
        """Clé de progression du game_start d'une partie (point de reprise Load→Resume)."""
        return _progress_key_from_meta(self.party_start_point(name)["meta"])

    def has_posterior_points(self, name: str, resume_key: tuple) -> bool:
        """True s'il existe des save-points STRICTEMENT postérieurs à ``resume_key`` dans la partie."""
        _assert_safe_party_name(name)
        if not os.path.exists(self._path(name)):
            return False
        pts = self._read_party(name)["points"]
        return any(_progress_key_from_meta(p["meta"]) > resume_key for p in pts)

    def truncate_after(self, name: str, resume_key: tuple) -> int:
        """Retire de la partie les save-points strictement postérieurs à ``resume_key``. Retourne le nb retiré."""
        _assert_safe_party_name(name)
        party = self._read_party(name)
        kept = [p for p in party["points"] if _progress_key_from_meta(p["meta"]) <= resume_key]
        removed = len(party["points"]) - len(kept)
        party["points"] = kept
        self._write_party(name, party)
        return removed

    def _unique_party_name(self, base: str) -> str:
        """Nom de fichier libre : suffixe « (2) », « (3) »… tant qu'un fichier du même nom existe."""
        candidate = base
        i = 2
        while os.path.exists(self._path(candidate)):
            candidate = f"{base} ({i})"
            i += 1
        return candidate

    def fork_backup(self, name: str, resume_key: tuple, archive_name: str = "") -> Dict[str, Any]:
        """Fork : archive la timeline COMPLÈTE sous un nom libre (optionnel), puis tronque la partie
        courante au point de reprise (elle devient la branche de travail). Le nom est sanitizé et
        rendu unique (jamais de doublon/écrasement) ; nom vide/invalide → nom auto par défaut."""
        _assert_safe_party_name(name)
        raw = archive_name.strip() if isinstance(archive_name, str) else ""
        default = f"{name} (sauvegarde)"
        try:
            base = sanitize_party_name(raw) if raw else sanitize_party_name(default)
        except ValueError:
            base = sanitize_party_name(default)
        archive = self._unique_party_name(base)
        party = self._read_party(name)
        self._write_party(archive, {"name": archive, "points": party["points"]})
        removed = self.truncate_after(name, resume_key)
        return {"archive": archive, "removed": removed}

    def delete_all(self) -> int:
        """Supprime toutes les parties (y compris forks à nom libre). Retourne le nombre de fichiers effacés."""
        if not os.path.isdir(self._dir):
            return 0
        n = 0
        for fn in list(os.listdir(self._dir)):
            if fn.endswith(".pkl") and os.path.isfile(os.path.join(self._dir, fn)):
                os.remove(os.path.join(self._dir, fn))
                n += 1
        self._current = None
        return n
