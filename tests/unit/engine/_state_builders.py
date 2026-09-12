"""Construction d'un ``game_state`` SYNTHÉTIQUE pour les tests moteur — sans scénario ni moteur.

CE QUI RESTE À L'APPELANT. Tout ce qui EST le sujet du test : le terrain, la géométrie des
positions, les caches de phase que sa phase exige (``build_enemy_adjacent_hexes``), les clés
d'état propres à sa phase (``charge_roll_values``, ``deployment_pools``…). Ce module ne connaît que
le socle commun ; il l'expose par ``**overrides`` plutôt qu'en devinant.

⚠️ CE N'EST PAS UN MOTEUR. Un état construit ici démarre TOUJOURS en placement fixe et ne passe par
aucun fichier de scénario : un test qui veut observer une phase de déploiement réelle doit passer
par ``_config_helpers.ACTIVE_DEPLOYMENT_SCENARIO`` (cf. le VERT VACANT documenté là-bas).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from engine.phase_handlers.shared_utils import build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants
from tests.unit.engine._config_helpers import build_game_rules, build_move_rules

def units_cache_entry(col: int, row: int, *, value: float = 10.0, player: int = 1, hp: int = 1) -> Dict[str, Any]:
    """Entrée ``units_cache`` minimale : socle rond taille 1, hex occupé, VALUE et player pilotables.

    Utilisé par les tests tir/mêlée qui construisent ``units_cache`` à la main plutôt que via
    ``build_units_cache`` — tous appellent la même structure, d'où ce helper partagé.

    ``hp`` : HP_CUR et HP_MAX, identiques (unité à plein). HP_CUR est requis par
    ``_build_target_meta`` pour initialiser ``hp_before`` dans ``targets_meta``
    avant l'allocation des pertes.
    """
    return {
        "BASE_SHAPE": "round", "BASE_SIZE": 1,
        "col": col, "row": row,
        "occupied_hexes": {(col, row)} if col >= 0 and row >= 0 else set(),
        "VALUE": value, "player": player,
        "HP_CUR": hp, "HP_MAX": hp,
    }


#: Hauteur de figurine par défaut (pouces). Toute unité de roster en porte une, et l'engagement 3D
#: (§03.04) comme la clairance (§13.06) lèvent sans elle : l'omettre rendrait les états de test
#: incapables d'atteindre les chemins verticaux. Les tests qui la CITENT l'importent d'ici — trois
#: déclarations de la même valeur, c'est trois endroits à corriger le jour où elle change.
MODEL_HEIGHT = 2.5


def synthetic_unit(
    uid: str,
    player: int,
    models: Sequence[Mapping[str, Any]],
    **overrides: Any,
) -> Dict[str, Any]:
    """Unité de test complète, avec une figurine par entrée de ``models``.

    Chaque entrée de ``models`` porte au minimum ``col``/``row`` ; ``level``, ``VALUE``,
    ``BASE_SIZE``, ``MODEL_HEIGHT`` … s'y ajoutent pour décrire une figurine qui DIVERGE de son
    escouade (personnage attaché). L'ancre de l'unité suit la PREMIÈRE figurine, invariant que
    ``build_units_cache`` exige.

    ``overrides`` : toute clé d'unité que le test pilote (``MOVE``, ``BASE_SIZE``,
    ``UNIT_KEYWORDS``, ``MODEL_HEIGHT``…).
    """
    if not models:
        raise ValueError(f"synthetic_unit({uid}): une unité sans figurine n'a pas d'ancre")
    unit: Dict[str, Any] = {
        **unit_invariants(),
        "id": uid, "player": player,
        "col": int(models[0]["col"]), "row": int(models[0]["row"]),
        "HP_CUR": len(models), "HP_MAX": len(models),
        "VALUE": 100, "OC": 1, "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1, "ATTACK_LEFT": 1, "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": MODEL_HEIGHT,
        "MOVE": 6, "UNIT_RULES": [],
        "models": [{"level": 0, "VALUE": 10, **m} for m in models],
    }
    unit.update(overrides)
    return unit


def synthetic_state(
    units: List[Dict[str, Any]],
    *,
    phase: str,
    game_rules: Mapping[str, Any],
    move_rules: Mapping[str, Any] = MappingProxyType({}),
    inches_to_subhex: int = 1,
    board_cols: int = 60,
    board_rows: int = 60,
    terrain_areas: Sequence[Mapping[str, Any]] = (),
    **overrides: Any,
) -> Dict[str, Any]:
    """``game_state`` de test, caches construits (``build_units_cache``).

    ``phase`` et ``game_rules`` sont OBLIGATOIRES : les deux sont passés par 100 % des appelants,
    et un paramètre universel caché dans ``**overrides`` n'apparaît ni dans la signature ni à la
    relecture — celui qui l'oublie ne le voit nulle part.

    ``game_rules`` / ``move_rules`` : surcharges des règles RÉELLES (``build_game_rules`` /
    ``build_move_rules``). Un test qui recopie un sous-ensemble de règles à la main tourne sur des
    règles figées, et toute clé nouvellement requise par le moteur lui manque en silence. Les
    toggles de traversée 03.01 (``move_rules``) sont surchargeables au même titre : les familles
    move et charge les pilotent.

    ``inches_to_subhex`` : 1 = géométrie HEX (``geometry_is_hex``), au-dessus = EUCLIDIENNE. Le
    choix n'est pas cosmétique — à x1 tout le chemin multi-niveaux est court-circuité, et un test
    vertical monté à x1 passe au vert sans exécuter ce qu'il croit vérifier.
    """
    state: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": {
            "game_rules": build_game_rules(**dict(game_rules)),
            "move": build_move_rules(**dict(move_rules)),
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": board_cols, "board_rows": board_rows,
        "current_player": 1,
        "phase": phase,
        "wall_hexes": set(),
        "terrain_areas": [dict(a) for a in terrain_areas],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_selected_to_fight": set(),
        "inches_to_subhex": int(inches_to_subhex),
        "action_logs": [],
        "action_log_seq": 0,
        "current_turn": 1,
    }
    state.update(overrides)
    build_units_cache(state)
    return state


Cell = Tuple[int, int]


def fight_squad_vs_enemies_state(
    squad: Sequence[Cell], enemies: Sequence[Cell], *, fight_subphase: Optional[str] = None,
) -> Dict[str, Any]:
    """Phase fight, règles RÉELLES (EZ 2, cohésion 2, ``inches_to_subhex`` = 1), plateau 44×60 :
    l'escouade « 1 » (joueur 1) aux cases ``squad``, un ennemi mono-figurine « 2 », « 3 », … (joueur
    2) par case de ``enemies``. ``fight_subphase`` : étape courante quand le test en dépend
    (``"pile_in"`` : le plan_state pile-in la relit pour distinguer l'overrun 12.06)."""
    units = [synthetic_unit("1", 1, [{"col": c, "row": r} for c, r in squad])]
    for i, (c, r) in enumerate(enemies):
        units.append(synthetic_unit(str(2 + i), 2, [{"col": c, "row": r}]))
    overrides: Dict[str, Any] = {}
    if fight_subphase is not None:
        overrides["fight_subphase"] = fight_subphase
    return synthetic_state(
        units, phase="fight", game_rules={}, inches_to_subhex=1, board_cols=44, board_rows=60,
        **overrides,
    )


def ground_plan(*entries: Tuple[str, Cell]) -> List[Tuple[str, int, int, int]]:
    """Plan par-figurine normalisé ``(mid, col, row, level)`` au sol (niveau 0)."""
    return [(mid, c, r, 0) for mid, (c, r) in entries]


def squad_model_cells(gs: Dict[str, Any], squad_id: str) -> Dict[str, Cell]:
    """``{model_id: (col, row)}`` courant des figurines de l'escouade (``squad_models`` →
    ``models_cache``) — comparaison avant/après d'un move."""
    mc = gs["models_cache"]
    return {m: (int(mc[m]["col"]), int(mc[m]["row"])) for m in gs["squad_models"][squad_id]}


def gs_with_units(shooter_sid: str = "1", target_sid: str = "2") -> Dict[str, Any]:
    """game_state minimal avec unit_by_id pour require_unit_by_id (tests de couvert/LoS)."""
    return {"unit_by_id": {shooter_sid: {"id": shooter_sid}, target_sid: {"id": target_sid}}}
