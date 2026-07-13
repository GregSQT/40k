"""Snapshots temporels d'une partie PvP (rewind / playback par phase).

Un snapshot est capturé au DÉBUT de chaque phase (identité = (turn, player, phase)).
Il contient une copie profonde de la partie mutable de ``engine.game_state`` ainsi que
des attributs gameplay mutables de l'engine (flags d'init de phase, compteurs, etc.).

Les clés/attributs STATIQUES (topologie, table d'armes, config, scénario, managers) ne sont
PAS copiés : ils sont ré-attachés par référence depuis l'engine vivant au moment du restore.
Ceci évite des copies lourdes à chaque phase et garantit que les sous-managers (qui reçoivent
``game_state`` en paramètre) restent cohérents.

Aucun fallback masquant une erreur : toute clé demandée absente lève.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

# Ordre canonique des phases dans un tour de joueur (pour l'ordre chronologique / purge).
PHASE_ORDER: Tuple[str, ...] = ("deployment", "command", "move", "shoot", "charge", "fight")

# --- Clés de game_state STATIQUES (non copiées, gardées vivantes au restore) ---------------
# Uniquement des clés RÉELLEMENT invariantes pendant une partie OU des caches purs sûrs à
# garder vivants. Sur-lister ici = bug de restore ; sous-lister = simple surcoût de copie.
_GS_STATIC_KEYS = frozenset({
    "los_topology", "pathfinding_topology", "wall_edge_topology",
    "wall_hexes", "dense_wall_hexes", "weapon_damage_table", "config",
    "board_cols", "board_rows", "inches_to_subhex", "max_range",
    "terrain_areas", "objectives", "primary_objective",
    "rewards_configs", "reward_configs", "hex_los_cache",
    "_cache_instance_id",
})

# --- Attributs d'engine STATIQUES (non copiés) : managers, config, scénario, spaces --------
# Tout autre attribut plain-data (bool/int/float/str/dict/list/set/tuple) est capturé.
# Les objets (managers, gym spaces, registry, modèle) sont ignorés via le garde isinstance.
_ENGINE_STATIC_ATTRS = frozenset({
    "game_state",
    "config", "training_config", "training_config_name",
    "rewards_config", "rewards_config_name",
    "_current_scenario_file", "_scenario_files", "_random_scenario_mode",
    "current_mode_code",
})

_ENGINE_PLAIN_TYPES = (bool, int, float, str, type(None), dict, list, set, tuple)


def _gs_key(game_state: Dict[str, Any]) -> Tuple[int, int, str]:
    return (
        int(game_state["turn"]),
        int(game_state["current_player"]),
        str(game_state["phase"]),
    )


def _ordinal(turn: int, player: int, phase: str) -> Tuple[int, int, int]:
    """Ordre chronologique global : tour, puis P1 avant P2, puis ordre des phases."""
    if phase not in PHASE_ORDER:
        raise KeyError(f"phase inconnue pour l'ordre snapshot: {phase!r}")
    return (int(turn), int(player), PHASE_ORDER.index(phase))


class GameSnapshotStore:
    def __init__(self) -> None:
        # clé (turn, player, phase) -> {"game_state": {...}, "engine_attrs": {...}, "meta": {...}}
        self._snaps: Dict[Tuple[int, int, str], Dict[str, Any]] = {}

    # ---- Capture -------------------------------------------------------------------------
    def reset(self) -> None:
        self._snaps.clear()

    def maybe_capture(self, engine: Any) -> bool:
        """Capture l'état si (turn, player, phase) n'a jamais été vu. Retourne True si capturé."""
        gs = engine.game_state
        phase = str(gs["phase"])
        if phase not in PHASE_ORDER:
            return False
        key = _gs_key(gs)
        if key in self._snaps:
            return False

        gs_copy = {
            k: copy.deepcopy(v)
            for k, v in gs.items()
            if k not in _GS_STATIC_KEYS
        }
        engine_attrs: Dict[str, Any] = {}
        for k, v in vars(engine).items():
            if k in _ENGINE_STATIC_ATTRS:
                continue
            if not isinstance(v, _ENGINE_PLAIN_TYPES):
                continue
            engine_attrs[k] = copy.deepcopy(v)

        vp = gs.get("victory_points") or {}
        meta = {
            "turn": key[0],
            "player": key[1],
            "phase": key[2],
            "score": {str(p): int(s) for p, s in vp.items()},
            "ordinal": list(_ordinal(*key)),
        }
        self._snaps[key] = {"game_state": gs_copy, "engine_attrs": engine_attrs, "meta": meta}
        return True

    # ---- Lecture -------------------------------------------------------------------------
    def list_meta(self) -> List[Dict[str, Any]]:
        metas = [dict(s["meta"]) for s in self._snaps.values()]
        metas.sort(key=lambda m: tuple(m["ordinal"]))
        return metas

    def has(self, turn: int, player: int, phase: str) -> bool:
        return (int(turn), int(player), str(phase)) in self._snaps

    def _get(self, turn: int, player: int, phase: str) -> Dict[str, Any]:
        key = (int(turn), int(player), str(phase))
        if key not in self._snaps:
            raise KeyError(f"snapshot introuvable: {key}")
        return self._snaps[key]

    # ---- Reconstruction d'un game_state complet ------------------------------------------
    def build_game_state(self, engine: Any, turn: int, player: int, phase: str) -> Dict[str, Any]:
        """game_state complet = clés statiques de l'engine vivant + partie mutable du snapshot."""
        snap = self._get(turn, player, phase)
        live = engine.game_state
        rebuilt = {k: live[k] for k in live if k in _GS_STATIC_KEYS}
        rebuilt.update(copy.deepcopy(snap["game_state"]))
        return rebuilt

    def engine_attrs(self, turn: int, player: int, phase: str) -> Dict[str, Any]:
        return copy.deepcopy(self._get(turn, player, phase)["engine_attrs"])

    # ---- Restore (reprise) ---------------------------------------------------------------
    def apply_resume(self, engine: Any, turn: int, player: int, phase: str) -> None:
        """Remplace l'état vivant de l'engine par le snapshot et purge l'historique postérieur."""
        rebuilt = self.build_game_state(engine, turn, player, phase)
        attrs = self.engine_attrs(turn, player, phase)
        engine.game_state = rebuilt
        for k, v in attrs.items():
            setattr(engine, k, v)
        _sync_derived_engine_attrs(engine)
        self.purge_after(turn, player, phase)

    def purge_after(self, turn: int, player: int, phase: str) -> None:
        """Supprime tous les snapshots strictement postérieurs au point donné (inclusif conservé)."""
        cutoff = _ordinal(turn, player, phase)
        for key in [k for k in self._snaps if _ordinal(*k) > cutoff]:
            del self._snaps[key]


# --- Capture / restore d'un état vivant arbitraire (utilisé par les saves manuelles) ---------
# Contrairement à ``maybe_capture`` (lié aux frontières de phase), ces helpers capturent/appliquent
# l'état vivant à un instant quelconque, avec la MÊME sémantique statique/mutable.

def capture_live_state(engine: Any) -> Dict[str, Any]:
    """Capture la partie mutable de l'état vivant (game_state hors clés statiques + attrs plain de l'engine)."""
    gs = engine.game_state
    gs_copy = {k: copy.deepcopy(v) for k, v in gs.items() if k not in _GS_STATIC_KEYS}
    engine_attrs: Dict[str, Any] = {}
    for k, v in vars(engine).items():
        if k in _ENGINE_STATIC_ATTRS:
            continue
        if not isinstance(v, _ENGINE_PLAIN_TYPES):
            continue
        engine_attrs[k] = copy.deepcopy(v)
    return {"game_state": gs_copy, "engine_attrs": engine_attrs}


def _sync_derived_engine_attrs(engine: Any) -> None:
    """Re-mirror des attributs d'engine dérivés du game_state après un remplacement d'état.

    ``current_mode_code`` est stocké dans game_state ET miroité en attribut d'engine (lu par
    ``_attach_player_types`` et les gates de capture snapshot). Il est exclu de la capture (statique),
    donc après un restore l'attribut doit être re-synchronisé depuis l'état restauré."""
    mode = engine.game_state.get("current_mode_code")
    if isinstance(mode, str) and mode:
        engine.current_mode_code = mode


def rebuild_game_state(engine: Any, captured: Dict[str, Any]) -> Dict[str, Any]:
    """Reconstruit un game_state complet (clés statiques du live + mutable capturé) SANS muter l'engine.

    Utilisé pour le mode 'view' (aperçu non destructif) : swap temporaire de engine.game_state."""
    live = engine.game_state
    rebuilt = {k: live[k] for k in live if k in _GS_STATIC_KEYS}
    rebuilt.update(copy.deepcopy(captured["game_state"]))
    return rebuilt


def apply_live_state(engine: Any, captured: Dict[str, Any]) -> None:
    """Remplace l'état vivant de l'engine par un état capturé (clés statiques ré-attachées depuis le live)."""
    engine.game_state = rebuild_game_state(engine, captured)
    for k, v in copy.deepcopy(captured["engine_attrs"]).items():
        setattr(engine, k, v)
    _sync_derived_engine_attrs(engine)
