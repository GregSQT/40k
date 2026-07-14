"""Timeline d'une partie PvP : 1 fichier par PARTIE = journal append-only de rows.

Modèle unifié (remplace l'ancien couple save-points / snapshots) :
- Une partie = un fichier ``{nom}.pkl`` : un magic d'en-tête puis une suite d'enregistrements append.
- Un enregistrement = ``[8o taille meta][meta pickle][8o taille state][state pickle]``. Le préfixe de
  longueur permet de LISTER les metas sans jamais désérialiser les states (seek par-dessus) → Select /
  playback / has_posterior restent quasi gratuits même sur une timeline par action.
- Une row = {meta, state} : état vivant capturé (copie profonde) + métadonnées (turn/phase/#, note, kind).
- ``kind`` ∈ {game_start, turn, phase, action, manual}. Les rows ``action`` (par activation d'unité)
  alimentent le playback ⏮⏭ mais sont MASQUÉES du menu Select (game_start / turn / phase / manual).
- ``Select`` navigue les rows de la partie COURANTE ; ``Load`` charge une autre partie (à son game_start).
- Resume : commit sur une row + fork/écrasement des rows postérieures.

Robustesse : append O(1) (pas de réécriture), écriture atomique pour les réécritures complètes
(start/troncature/fork), RLock pour la concurrence (writer async vs lectures/réécritures). Lecture
défensive STRICTE : seule une row de QUEUE incomplète (crash pendant un append) est ignorée — toute
autre erreur de dépickle (ex. classe déplacée) REMONTE (pas de fallback masquant un bug).
"""

from __future__ import annotations

import logging
import os
import pickle
import queue
import re
import struct
import tempfile
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from services.game_snapshots import apply_live_state, capture_live_state

_log = logging.getLogger(__name__)

# Magic d'en-tête du format timeline (distingue de l'ancien format single-pickle).
_MAGIC = b"W40KTL01"
_LEN = struct.Struct(">Q")  # préfixe de longueur : entier 64 bits big-endian

# Rows exclues du menu Select (trop nombreuses) mais présentes dans le playback ⏮⏭.
_SELECT_HIDDEN_KINDS = {"action"}

# Fichier de TRAVAIL : nom réservé, unique par répertoire, réutilisé/écrasé à chaque partie tant
# qu'aucune save manuelle (autosave OFF) → enregistre toute la timeline en continu (playback ⏮⏭)
# SANS proliférer de fichiers. Masqué de Load/Select. Promu (rename atomique) en partie nommée à la
# 1re save manuelle, ou immédiatement au start si l'autosave est active.
_WORKING_NAME = "__working__"

# Caractères interdits dans un nom de fichier (Windows/Unix) + noms réservés Windows.
_FORBIDDEN_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Ordre de progression d'une partie : tour → phase → nb d'activations d'unité (compteur global
# monotone). Sert à déterminer les rows « postérieures » à un point de reprise (fork/écrasement).
_PHASE_RANK = {"deployment": 0, "command": 1, "move": 2, "shoot": 3, "charge": 4, "fight": 5}


def _phase_rank(phase: str) -> int:
    if phase not in _PHASE_RANK:
        raise ValueError(f"phase inconnue pour l'ordre de progression: {phase!r}")
    return _PHASE_RANK[phase]


def _progress_key_from_meta(meta: Dict[str, Any]) -> tuple:
    return (int(meta["turn"]), _phase_rank(str(meta["phase"])), int(meta["episode_steps"]))


def progress_key_from_gs(gs: Dict[str, Any]) -> tuple:
    """Clé de progression depuis l'état vivant (pour un point de reprise sans row, ex. rewind)."""
    return (int(gs["turn"]), _phase_rank(str(gs["phase"])), int(gs.get("unit_activation_count", 0)))


def sanitize_party_name(name: str) -> str:
    """Nom de fichier de partie sûr : retire les caractères interdits OS, refuse vide/réservé."""
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


def row_meta(gs: Dict[str, Any], row_ts: str, note: str, kind: str) -> Dict[str, Any]:
    """Métadonnées d'une row (id = ts fourni par l'appelant ; doit être unique dans la partie)."""
    turn = int(gs["turn"])
    player = int(gs["current_player"])
    phase = str(gs["phase"])
    steps = int(gs.get("unit_activation_count", 0))  # "#" = activations d'UNITÉ
    label = f"T{turn} · {phase[:1].upper()}{phase[1:]} · #{steps}"
    vp = gs.get("victory_points") or {}
    return {
        "id": row_ts,
        "turn": turn,
        "player": player,
        "phase": phase,
        "episode_steps": steps,
        "ts": row_ts,
        "label": label,
        "note": note,
        "kind": kind,
        "score": {str(p): int(s) for p, s in vp.items()},
    }


def _pack_record(row: Dict[str, Any]) -> bytes:
    """Sérialise une row en ``[len meta][meta][len state][state]``."""
    mb = pickle.dumps(row["meta"])
    sb = pickle.dumps(row["state"])
    return _LEN.pack(len(mb)) + mb + _LEN.pack(len(sb)) + sb


class SaveStore:
    def __init__(self, directory: str) -> None:
        self._dir = directory
        self._current: Optional[str] = None  # nom de la partie courante (peut être le working)
        # Nom définitif visé à la promotion du working (calculé au start). None hors partie working.
        self._promote_target: Optional[str] = None
        # Sérialise tous les accès disque (writer async vs lectures / réécritures fork/troncature).
        self._lock = threading.RLock()
        # File d'attente des rows à écrire + thread writer unique (append async, hors thread de jeu).
        self._queue: "queue.Queue[Tuple[str, Dict[str, Any]]]" = queue.Queue()
        self._writer: Optional[threading.Thread] = None
        self._writer_lock = threading.Lock()

    def set_directory(self, directory: str) -> None:
        """Change le répertoire des parties (change de dossier → plus de partie courante)."""
        self._dir = directory
        self._current = None
        self._promote_target = None

    def current_party(self) -> Optional[str]:
        return self._current

    def is_working(self) -> bool:
        """True si la partie courante est le fichier de travail (non encore promu en save nommée)."""
        return self._current == _WORKING_NAME

    def set_current(self, name: str) -> None:
        """Définit la partie courante (contexte de navigation Select), sans muter l'engine."""
        self._current = name
        self._promote_target = None

    def _path(self, name: str) -> str:
        return os.path.join(self._dir, f"{name}.pkl")

    # --- IO append-log : magic + enregistrements [len meta][meta][len state][state] ---

    @staticmethod
    def _read_len(f, size: int) -> Optional[int]:
        """Lit un préfixe de longueur ; None si queue tronquée (moins de 8 octets)."""
        raw = f.read(8)
        if len(raw) < 8:
            return None
        (n,) = _LEN.unpack(raw)
        # Le bloc annoncé dépasse la fin du fichier → enregistrement de queue incomplet (crash append).
        if f.tell() + n > size:
            return None
        return n

    def _scan(self, name: str, load_state: bool) -> List[Dict[str, Any]]:
        """Parcourt les enregistrements. ``load_state=False`` → renvoie les metas en sautant les states
        (aucune désérialisation d'état) ; ``True`` → renvoie les rows {meta, state}."""
        out: List[Dict[str, Any]] = []
        with self._lock, open(self._path(name), "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if f.read(len(_MAGIC)) != _MAGIC:
                return self._read_legacy(f, load_state)
            while True:
                mlen = self._read_len(f, size)
                if mlen is None:
                    break
                meta = pickle.loads(f.read(mlen))  # octets complets → une erreur ici = vraie corruption
                slen = self._read_len(f, size)
                if slen is None:
                    break  # state de queue incomplet → row ignorée
                if load_state:
                    out.append({"meta": meta, "state": pickle.loads(f.read(slen))})
                else:
                    f.seek(slen, 1)  # saute le state sans le désérialiser
                    out.append(meta)
        return out

    @staticmethod
    def _read_legacy(f, load_state: bool) -> List[Dict[str, Any]]:
        """Rétrocompat : ancien format single-pickle ``{name, points:[{meta,state}]}``."""
        f.seek(0)
        try:
            header = pickle.load(f)
        except EOFError:
            return []
        if not (isinstance(header, dict) and "points" in header):
            raise ValueError("format de partie inconnu (ni timeline, ni ancien format)")
        pts = header.get("points") or []
        return [p if load_state else p["meta"] for p in pts]

    def _find(self, name: str, match: Callable[[Dict[str, Any]], bool]) -> Dict[str, Any]:
        """Renvoie la 1re row {meta, state} dont la meta satisfait ``match``, en ne désérialisant que
        SON state (les autres sont sautés). Lève KeyError si aucune ne matche."""
        with self._lock, open(self._path(name), "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if f.read(len(_MAGIC)) != _MAGIC:
                for row in self._read_legacy(f, True):
                    if match(row["meta"]):
                        return row
                raise KeyError("row introuvable")
            while True:
                mlen = self._read_len(f, size)
                if mlen is None:
                    break
                meta = pickle.loads(f.read(mlen))
                slen = self._read_len(f, size)
                if slen is None:
                    break
                if match(meta):
                    return {"meta": meta, "state": pickle.loads(f.read(slen))}
                f.seek(slen, 1)
        raise KeyError("row introuvable")

    def _write_all(self, name: str, rows: List[Dict[str, Any]]) -> None:
        """Réécriture atomique complète (magic + enregistrements) : start / troncature / fork."""
        with self._lock:
            os.makedirs(self._dir, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._dir, prefix=f".{name}.", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(_MAGIC)
                    for r in rows:
                        f.write(_pack_record(r))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self._path(name))
            except BaseException:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise

    def _append(self, name: str, row: Dict[str, Any]) -> None:
        """Append d'un seul enregistrement en fin de fichier (O(1), pas de réécriture)."""
        with self._lock:
            path = self._path(name)
            if not os.path.exists(path):
                raise FileNotFoundError(f"partie inexistante pour append: {name}")
            with open(path, "ab") as f:
                f.write(_pack_record(row))
                f.flush()
                os.fsync(f.fileno())

    # --- Capture (sync) : à appeler sous le lock engine, puis appendée (éventuellement en async) ---

    def make_row(self, engine: Any, row_ts: str, kind: str, note: str = "") -> Dict[str, Any]:
        """Construit une row {meta, state} par COPIE PROFONDE de l'état (sûr pour un append différé).

        Draine ``game_state['log_delta']`` (events du combat log accumulés depuis la row précédente)
        dans ``meta['log_delta']`` puis le vide : chaque event du log est ainsi stocké UNE seule fois
        (delta linéaire, pas de cumul par row). Le Game Log d'un point est reconstruit par concaténation
        des deltas des rows antérieures (``reconstruct_log``). Vidé AVANT capture pour ne pas dupliquer
        le delta dans le state (le state ne sert jamais à reconstruire le log)."""
        gs = engine.game_state
        meta = row_meta(gs, row_ts, note, kind)
        pending = gs.get("log_delta")
        meta["log_delta"] = list(pending) if isinstance(pending, list) else []
        gs["log_delta"] = []
        return {"meta": meta, "state": capture_live_state(engine)}

    def append_prepared_row(self, name: str, row: Dict[str, Any]) -> None:
        """Append d'une row déjà capturée (appelé par le writer async)."""
        _assert_safe_party_name(name)
        self._append(name, row)

    # --- Writer async : le jeu enqueue une row déjà capturée, un thread unique l'append au disque ---

    def _ensure_writer(self) -> None:
        with self._writer_lock:
            if self._writer is None or not self._writer.is_alive():
                self._writer = threading.Thread(
                    target=self._writer_loop, name="save-timeline-writer", daemon=True
                )
                self._writer.start()

    def _writer_loop(self) -> None:
        while True:
            name, row = self._queue.get()
            try:
                self.append_prepared_row(name, row)
            except Exception:  # noqa: BLE001 — on logue, on ne perd pas le thread ni les rows suivantes
                _log.exception("échec d'append d'une row de timeline (partie %r)", name)
            finally:
                self._queue.task_done()

    def enqueue_row(self, name: str, row: Dict[str, Any]) -> None:
        """Met en file une row DÉJÀ capturée (deepcopy) pour écriture asynchrone. Ne bloque pas le jeu."""
        self._ensure_writer()
        self._queue.put((name, row))

    def flush(self) -> None:
        """Bloque jusqu'à ce que toutes les rows en attente soient écrites. À appeler AVANT toute
        troncature/fork/Load pour ne pas ré-appender une row périmée après coup."""
        self._queue.join()

    # --- Création / ajout ---

    def start_party(self, engine: Any, party_name: str, point_ts: str) -> Dict[str, Any]:
        """Démarre une partie dans le fichier de TRAVAIL (écrase le working précédent avec la row
        game_start) → pas de prolifération de fichiers tant qu'aucune save. ``party_name`` est le nom
        définitif visé à la promotion (1re save manuelle ou autosave). La partie courante devient le
        working ; il est promu plus tard via ``promote()``."""
        row = self.make_row(engine, point_ts, "game_start", "")
        with self._lock:
            self._write_all(_WORKING_NAME, [row])
            self._current = _WORKING_NAME
            self._promote_target = party_name
        return {"name": _WORKING_NAME}

    def promote(self) -> Optional[str]:
        """Promeut le fichier de travail en partie nommée (rename atomique O(1)) → visible dans
        Select/Load. Idempotent : no-op si la partie courante n'est pas le working. Retourne le nom
        promu (ou le nom courant si déjà promu).

        ``flush()`` HORS du lock (le writer async a besoin du lock pour drainer sa file → le flusher
        sous lock serait un deadlock) : draine la file d'append pour ne pas ré-appender une row dans le
        working recréé après le rename. La sérialisation au niveau engine (appelants sous engine lock)
        empêche l'enqueue d'une nouvelle row entre le flush et le rename."""
        if not self.is_working():
            return self._current
        self.flush()
        with self._lock:
            base = self._promote_target or _WORKING_NAME
            name = self._unique_party_name(base)
            os.replace(self._path(_WORKING_NAME), self._path(name))
            self._current = name
            self._promote_target = None
            return name

    def add_point(self, engine: Any, point_ts: str, note: str = "", kind: str = "manual") -> Dict[str, Any]:
        """Ajoute une row à la partie courante (append). Une save manuelle sur le working le promeut
        d'abord en partie nommée (le point manuel matérialise la save complète)."""
        if self.is_working():
            self.promote()
        if self._current is None:
            self._current = _party_name_from_point_ts(point_ts)
        row = self.make_row(engine, point_ts, kind, note)
        if not os.path.exists(self._path(self._current)):
            self._write_all(self._current, [row])
        else:
            self._append(self._current, row)
        return row["meta"]

    # --- Listings (metas seuls : aucun state désérialisé) ---

    @staticmethod
    def _display_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
        """Meta allégée pour l'affichage front (Select / playback) : retire ``log_delta`` (le combat
        log, volumineux et inutile pour lister/naviguer — il n'est reconstruit qu'au Load/rewind)."""
        return {k: v for k, v in meta.items() if k != "log_delta"}

    def list_points(self) -> List[Dict[str, Any]]:
        """Rows de la partie courante pour le menu SELECT (masque les rows ``action``), récentes d'abord."""
        if self._current is None or not os.path.exists(self._path(self._current)):
            return []
        metas = [
            self._display_meta(m)
            for m in self._scan(self._current, False)
            if m["kind"] not in _SELECT_HIDDEN_KINDS
        ]
        metas.sort(key=lambda m: m["ts"], reverse=True)
        return metas

    def list_all_rows(self, name: Optional[str] = None) -> List[Dict[str, Any]]:
        """TOUTES les rows (metas) d'une partie dans l'ordre du jeu — pour le playback ⏮▶⏭."""
        target = name if name is not None else self._current
        if target is None or not os.path.exists(self._path(target)):
            return []
        return [self._display_meta(m) for m in self._scan(target, False)]

    def reconstruct_log(self, name: str, up_to_key: Optional[tuple]) -> List[Dict[str, Any]]:
        """Reconstruit le combat log d'une partie jusqu'au point ``up_to_key`` (inclus) en concaténant
        les ``meta['log_delta']`` des rows dans l'ordre du jeu. ``up_to_key=None`` → toute la partie.

        Ne désérialise QUE les metas (states sautés) → reconstruction bon marché même sur une timeline
        par action. Rétrocompat : une row sans ``log_delta`` (ancienne partie) contribue une liste vide."""
        target = name if name is not None else self._current
        if target is None or not os.path.exists(self._path(target)):
            return []
        out: List[Dict[str, Any]] = []
        for meta in self._scan(target, False):
            if up_to_key is not None and _progress_key_from_meta(meta) > up_to_key:
                continue
            delta = meta.get("log_delta")
            if isinstance(delta, list):
                out.extend(delta)
        return out

    def list_parties(self) -> List[Dict[str, Any]]:
        """Liste des parties sauvegardées (pour Load), plus récentes d'abord (tout fichier .pkl)."""
        if not os.path.isdir(self._dir):
            return []
        parties: List[Dict[str, Any]] = []
        for fn in os.listdir(self._dir):
            if fn.endswith(".pkl") and fn[:-4] != _WORKING_NAME and os.path.isfile(os.path.join(self._dir, fn)):
                parties.append({"name": fn[:-4]})
        parties.sort(key=lambda p: p["name"], reverse=True)
        return parties

    # --- Accès / restauration (ne charge que le state ciblé) ---

    def point(self, point_id: str) -> Dict[str, Any]:
        """Row {meta, state} de la partie courante (par id) SANS l'appliquer (aperçu view)."""
        if self._current is None:
            raise ValueError("aucune partie courante")
        return self._find(self._current, lambda m: m["id"] == point_id)

    def restore_point(self, engine: Any, point_id: str) -> Dict[str, Any]:
        """Restaure une row (par id) de la partie courante (commit destructif)."""
        r = self.point(point_id)
        apply_live_state(engine, r["state"])
        return r["meta"]

    def party_start_point(self, name: str) -> Dict[str, Any]:
        """Row de départ d'une partie {meta, state} SANS l'appliquer (aperçu view)."""
        _assert_safe_party_name(name)
        if not os.path.exists(self._path(name)):
            raise FileNotFoundError(f"partie introuvable: {name}")
        metas = self._scan(name, False)
        if not metas:
            raise ValueError(f"partie vide: {name}")
        start_id = next((m["id"] for m in metas if m["kind"] == "game_start"), metas[0]["id"])
        return self._find(name, lambda m: m["id"] == start_id)

    def load_party_start(self, engine: Any, name: str) -> Dict[str, Any]:
        """Charge une partie à son game_start (commit destructif) et la rend courante."""
        start = self.party_start_point(name)
        apply_live_state(engine, start["state"])
        self._current = name
        self._promote_target = None
        return start["meta"]

    # --- Divergence (fork / écrasement au Resume) — metas seuls sauf la réécriture ---

    def point_progress_key(self, point_id: str) -> tuple:
        """Clé de progression d'une row de la partie courante (point de reprise Select→Resume)."""
        if self._current is None:
            raise ValueError("aucune partie courante")
        for m in self._scan(self._current, False):
            if m["id"] == point_id:
                return _progress_key_from_meta(m)
        raise KeyError(f"row introuvable: {point_id}")

    def party_start_progress_key(self, name: str) -> tuple:
        """Clé de progression du game_start d'une partie (point de reprise Load→Resume)."""
        return _progress_key_from_meta(self.party_start_point(name)["meta"])

    def has_posterior_points(self, name: str, resume_key: tuple) -> bool:
        """True s'il existe des rows STRICTEMENT postérieures à ``resume_key`` (metas seuls)."""
        _assert_safe_party_name(name)
        if not os.path.exists(self._path(name)):
            return False
        return any(_progress_key_from_meta(m) > resume_key for m in self._scan(name, False))

    def truncate_after(self, name: str, resume_key: tuple) -> int:
        """Retire les rows strictement postérieures à ``resume_key``. Retourne le nb retiré."""
        _assert_safe_party_name(name)
        with self._lock:
            rows = self._scan(name, True)
            kept = [r for r in rows if _progress_key_from_meta(r["meta"]) <= resume_key]
            removed = len(rows) - len(kept)
            self._write_all(name, kept)
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
        courante au point de reprise. Nom sanitizé + rendu unique (jamais de doublon/écrasement) ;
        nom vide/invalide → nom auto par défaut."""
        _assert_safe_party_name(name)
        raw = archive_name.strip() if isinstance(archive_name, str) else ""
        default = f"{name} (sauvegarde)"
        try:
            base = sanitize_party_name(raw) if raw else sanitize_party_name(default)
        except ValueError:
            base = sanitize_party_name(default)
        with self._lock:
            archive = self._unique_party_name(base)
            self._write_all(archive, self._scan(name, True))
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
        self._promote_target = None
        return n
