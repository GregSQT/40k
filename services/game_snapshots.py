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
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from shared.data_validation import require_key

# Ordre canonique des phases dans un tour de joueur (pour l'ordre chronologique / purge).
PHASE_ORDER: Tuple[str, ...] = ("deployment", "command", "move", "shoot", "charge", "fight")

# --- Clés de game_state STATIQUES (non copiées, gardées vivantes au restore) ---------------
# Uniquement des clés RÉELLEMENT invariantes pendant une partie OU des caches purs sûrs à
# garder vivants. Sur-lister ici = bug de restore ; sous-lister = simple surcoût de copie.
_GS_STATIC_KEYS = frozenset({
    "wall_hexes", "dense_wall_hexes", "weapon_damage_table", "config",
    "board_cols", "board_rows", "inches_to_subhex", "max_range",
    "terrain_areas", "objectives", "primary_objective",
    # Zones de déploiement : posées par le reset depuis le SCÉNARIO, jamais réécrites de la
    # partie (aucun écrivain hors reset). Deux raisons de les déclarer statiques :
    # 1. RESTORE — `build_game_state` reconstruit l'état à partir des seules clés statiques
    #    VIVANTES plus la copie du snapshot. Ces zones ont vécu dans `deployment_state` jusqu'au
    #    2026-08-05 : un pickle capturé avant ce déplacement n'a pas la clé racine, et sans cette
    #    ligne elle disparaîtrait du state reconstruit — le premier clic de déploiement lèverait
    #    `Required key 'deployment_pools'`. Les prendre de l'engine vivant règle la reprise des
    #    parties persistées d'avant le changement, sans code de migration.
    # 2. COÛT — ~33 000 tuples immuables, deepcopy à CHAQUE capture de phase sinon.
    "deployment_pools",
    "rewards_configs", "reward_configs", "hex_los_cache",
    # Grilles de blocage de la LoS vectorisée (murs + areas obscurantes) : dérivées du seul
    # terrain, donc invariantes pendant une partie et sûres à garder vivantes au restore. Non
    # listées, elles se feraient deepcopy à CHAQUE capture — 330 Ko de décor immuable par
    # snapshot sur un plateau x5.
    "_los_blocking_grids_cache",
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
} | {
    # L'engine garde, en attributs ``_scenario_X``, les données de scénario qui alimentent la clé
    # ``game_state["X"]`` (même donnée, parfois sous une autre forme : murs bruts vs murs étendus).
    # Quand X est déjà déclarée statique ci-dessus, son doublon d'engine l'est par construction —
    # sinon il repasse par ``vars(engine)`` et se fait recopier à chaque capture (mesuré sur une
    # partie réelle : 233 Ko et 37 ms par capture, soit ~90% du coût, pour du décor immuable).
    # Dérivé de _GS_STATIC_KEYS (source de vérité unique) : ajouter une clé statique y suffit.
    f"_scenario_{key}" for key in _GS_STATIC_KEYS
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
    # Clause de détachement d'Oath et Faction d'Armée : elles vivent dans `config`, donc dans les
    # clés STATIQUES, et
    # c'est juste — elle appartient au roster et ne change pas d'un tour à l'autre. Elle change
    # pourtant EN AMONT de la partie, quand un joueur choisit un autre roster en déploiement
    # (`api_server._execute_change_roster_action`). Un état capturé avant ce choix décrit donc
    # l'armée d'AVANT : le restituer sans sa clause rendrait le roster du scénario avec le +1 au
    # jet de blessure de l'armée abandonnée. Capturée à part, et non sortie de `config` : la
    # donnée reste celle du roster, elle n'est pas de l'état de jeu.
    return {
        "game_state": gs_copy,
        "engine_attrs": engine_attrs,
        "uses_codex_detachment": copy.deepcopy(
            require_key(gs, "config").get("uses_codex_detachment")  # get allowed : None = scénario muet
        ),
        "army_faction": copy.deepcopy(
            require_key(gs, "config").get("army_faction")  # get allowed : None = scénario muet
        ),
    }


# --- Empreinte de scénario : les clés statiques dont dépend l'état capturé -----------------
# Un état capturé ne contient que le mutable ; les clés statiques sont ré-attachées depuis l'engine
# vivant au restore. Appliquer un état sur un AUTRE plateau est silencieusement faux (unités dans des
# murs, LoS/pathfinding calculés sur la mauvaise carte) : l'empreinte permet de le REFUSER.
# Sources uniquement : les topologies (los/pathfinding/wall_edge) en dérivent — les empreinter serait
# redondant et coûteux.
_FINGERPRINT_KEYS: Tuple[str, ...] = (
    "board_cols", "board_rows", "inches_to_subhex",
    "wall_hexes", "dense_wall_hexes", "terrain_areas",
    "objectives", "primary_objective",
)


def _normalize(value: Any) -> Any:
    """Normalise une valeur en structure JSON à ordre déterministe (empreinte stable d'un run à
    l'autre). Un type non prévu lève : une empreinte silencieusement approximative ne protège rien."""
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted(json.dumps(_normalize(v), sort_keys=True) for v in value)
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    raise TypeError(f"type non empreintable dans le scénario: {type(value).__name__}")


def scenario_fingerprint(engine: Any) -> Dict[str, Any]:
    """Empreinte du plateau d'un engine : stockée dans la meta d'une row de save, comparée au load.

    ``scenario_file`` est informatif (message d'erreur) : le chemin seul ne prouve rien, un fichier de
    scénario modifié depuis la save produirait un digest différent — ce qui est exactement le but."""
    gs = engine.game_state
    payload = {k: _normalize(gs[k]) for k in _FINGERPRINT_KEYS}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"digest": digest, "scenario_file": engine._current_scenario_file}


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
    for _roster_key in ("uses_codex_detachment", "army_faction"):  # absents des vieux pickles
        # Écrit DANS l'objet config vivant, jamais dans une copie : `engine.config` et
        # `game_state["config"]` sont le MÊME dict, et deux copies de contenu égal se
        # désynchroniseraient au premier écrivain suivant. `rebuild_game_state` (mode 'view'),
        # lui, ne touche à rien : un aperçu n'attaque pas, donc ne lit jamais cette clause.
        if _roster_key not in captured:
            continue
        require_key(engine.game_state, "config")[_roster_key] = copy.deepcopy(
            captured[_roster_key]
        )
    for k, v in copy.deepcopy(captured["engine_attrs"]).items():
        setattr(engine, k, v)
    _sync_derived_engine_attrs(engine)
