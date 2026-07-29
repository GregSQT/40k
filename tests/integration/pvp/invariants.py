"""Invariants transversaux du game_state PvP (tranche T2).

Ces contrôles portent sur le state SÉRIALISÉ renvoyé par l'API, c'est-à-dire exactement
ce que le front reçoit — pas sur les structures internes du moteur.

Ils sont revalidés après CHAQUE action par ``GameClient`` (voir ``conftest.py``) : la
plupart des bugs de flux n'apparaissent pas au tour 1 mais après une séquence d'actions.

Aucune règle 40k n'est assertée ici : uniquement de la cohérence structurelle et
référentielle, vraie quelle que soit la règle appliquée. Les assertions de règles
appartiennent aux tranches T3+, avec référence au PDF correspondant.
"""

from __future__ import annotations

from typing import Any, Dict, List

PHASES = {"deployment", "command", "move", "shoot", "charge", "fight"}

# Pools réservés au joueur actif : leur contenu doit lui appartenir.
ACTIVE_PLAYER_POOLS = (
    "move_activation_pool",
    "shoot_activation_pool",
    "charge_activation_pool",
    "command_activation_pool",
)

# Pools de la phase fight : l'alternance 12.01-12.03 y fait figurer les unités des DEUX
# joueurs selon la sous-phase — on n'y vérifie donc que l'existence des unités.
ANY_PLAYER_POOLS = (
    "fight_eligible_units",
    "charging_activation_pool",
    "active_alternating_activation_pool",
    "non_active_alternating_activation_pool",
)


def _fail(context: str, message: str) -> None:
    raise AssertionError(f"[invariant après {context!r}] {message}")


def _alive(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(u["id"]): u for u in state["units"] if u["HP_CUR"] > 0}


def assert_state_invariants(state: Dict[str, Any], context: str = "?") -> None:
    """Lève AssertionError au premier invariant violé, en nommant l'action fautive."""
    _assert_scalars(state, context)
    _assert_unit_identity(state, context)
    _assert_hp_bounds(state, context)
    _assert_hp_squad_sum(state, context)
    _assert_positions(state, context)
    _assert_referential_integrity(state, context)
    _assert_pools(state, context)


def _assert_scalars(state: Dict[str, Any], context: str) -> None:
    if state["phase"] not in PHASES:
        _fail(context, f"phase inconnue : {state['phase']!r} (attendu l'une de {sorted(PHASES)})")
    if int(state["current_player"]) not in (1, 2):
        _fail(context, f"current_player = {state['current_player']!r}")
    if int(state["turn"]) < 1:
        _fail(context, f"turn = {state['turn']!r} (doit être >= 1)")


def _assert_unit_identity(state: Dict[str, Any], context: str) -> None:
    ids = [str(u["id"]) for u in state["units"]]
    if len(ids) != len(set(ids)):
        duplicates = sorted({uid for uid in ids if ids.count(uid) > 1})
        _fail(context, f"ids d'unités dupliqués : {duplicates}")


def _assert_hp_bounds(state: Dict[str, Any], context: str) -> None:
    for model_id, model in state["models_cache"].items():
        hp_cur, hp_max = model["HP_CUR"], model["HP_MAX"]
        if not 0 <= hp_cur <= hp_max:
            _fail(context, f"figurine {model_id} : HP_CUR={hp_cur} hors de [0, {hp_max}]")


def _assert_hp_squad_sum(state: Dict[str, Any], context: str) -> None:
    """HP d'unité == somme des figurines, pour les escouades homogènes seulement.

    Avec un leader attaché (unitType différent dans models_cache), le HP_CUR d'unité ne
    compte pas le leader : l'égalité ne s'applique pas et n'est donc pas assertée là.
    """
    models_cache = state["models_cache"]
    for unit in state["units"]:
        model_ids = state["squad_models"][str(unit["id"])]
        if not model_ids:
            continue
        types = {models_cache[m]["unitType"] for m in model_ids}
        if len(types) != 1:
            continue
        total = sum(models_cache[m]["HP_CUR"] for m in model_ids)
        if total != unit["HP_CUR"]:
            _fail(
                context,
                f"unité {unit['id']} : HP_CUR={unit['HP_CUR']} != somme des figurines={total}",
            )


def _assert_positions(state: Dict[str, Any], context: str) -> None:
    cols, rows = state["board_cols"], state["board_rows"]
    for unit_id, unit in _alive(state).items():
        if not (0 <= unit["col"] < cols and 0 <= unit["row"] < rows):
            _fail(context, f"unité {unit_id} hors board : ({unit['col']}, {unit['row']}) / {cols}x{rows}")
    for model_id, model in state["models_cache"].items():
        if model["HP_CUR"] <= 0:
            continue
        if not (0 <= model["col"] < cols and 0 <= model["row"] < rows):
            _fail(context, f"figurine {model_id} hors board : ({model['col']}, {model['row']})")


def _assert_referential_integrity(state: Dict[str, Any], context: str) -> None:
    """units ↔ squad_models ↔ models_cache ↔ units_cache doivent se refermer."""
    known_units = {str(u["id"]) for u in state["units"]}
    models_cache = state["models_cache"]
    squad_models = state["squad_models"]

    for unit_id in _alive(state):
        if unit_id not in squad_models:
            _fail(context, f"unité vivante {unit_id} absente de squad_models")
        if unit_id not in state["units_cache"]:
            _fail(context, f"unité vivante {unit_id} absente de units_cache")

    for unit_id, model_ids in squad_models.items():
        if unit_id not in known_units:
            _fail(context, f"squad_models référence une unité inconnue : {unit_id}")
        for model_id in model_ids:
            if model_id not in models_cache:
                _fail(context, f"squad_models[{unit_id}] référence une figurine absente de models_cache : {model_id}")
            owner = str(models_cache[model_id]["squad_id"])
            if owner != unit_id:
                _fail(context, f"figurine {model_id} : squad_id={owner} mais listée sous l'unité {unit_id}")

    for model_id, model in models_cache.items():
        squad_id = str(model["squad_id"])
        if squad_id not in squad_models:
            _fail(context, f"figurine {model_id} : squad_id {squad_id} absent de squad_models")
        if model_id not in [str(m) for m in squad_models[squad_id]]:
            _fail(context, f"figurine {model_id} non listée dans squad_models[{squad_id}]")

    for unit_id in state["units_cache"]:
        if str(unit_id) not in known_units:
            _fail(context, f"units_cache référence une unité inconnue : {unit_id}")


def _assert_pools(state: Dict[str, Any], context: str) -> None:
    alive = _alive(state)
    active_player = int(state["current_player"])

    for pool_name in ACTIVE_PLAYER_POOLS:
        if pool_name not in state:
            continue
        for unit_id in _ids(state[pool_name]):
            if unit_id not in alive:
                _fail(context, f"{pool_name} contient {unit_id} : unité morte ou inexistante")
            if int(alive[unit_id]["player"]) != active_player:
                _fail(
                    context,
                    f"{pool_name} contient {unit_id} (joueur {alive[unit_id]['player']}) "
                    f"alors que le joueur actif est {active_player}",
                )

    for pool_name in ANY_PLAYER_POOLS:
        if pool_name not in state:
            continue
        for unit_id in _ids(state[pool_name]):
            if unit_id not in alive:
                _fail(context, f"{pool_name} contient {unit_id} : unité morte ou inexistante")

    # Une unité qui a fui a été sélectionnée pour bouger (09.02) : le moteur pose les deux
    # marques, ``units_fled`` est un sous-ensemble de ``units_moved``.
    orphan_fled = sorted(set(_ids(state["units_fled"])) - set(_ids(state["units_moved"])))
    if orphan_fled:
        _fail(context, f"unités dans units_fled mais pas dans units_moved : {orphan_fled}")

    # Une unité ne peut pas être à la fois « à activer » et « déjà activée ».
    if "move_activation_pool" in state:
        done = set(_ids(state["units_moved"])) | set(_ids(state["units_fled"]))
        clash = sorted(set(_ids(state["move_activation_pool"])) & done)
        if clash:
            _fail(context, f"unités à la fois dans move_activation_pool et déjà déplacées : {clash}")
    if "shoot_activation_pool" in state:
        clash = sorted(set(_ids(state["shoot_activation_pool"])) & set(_ids(state["units_shot"])))
        if clash:
            _fail(context, f"unités à la fois dans shoot_activation_pool et units_shot : {clash}")
    if "charge_activation_pool" in state:
        clash = sorted(set(_ids(state["charge_activation_pool"])) & set(_ids(state["units_charged"])))
        if clash:
            _fail(context, f"unités à la fois dans charge_activation_pool et units_charged : {clash}")


def _ids(raw: List[Any]) -> List[str]:
    return [str(item) for item in raw]
