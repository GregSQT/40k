"""Construction d'un ``game_state`` SYNTHÉTIQUE pour les tests moteur — sans scénario ni moteur.

POURQUOI CE MODULE. Trois fichiers de tests (engagement 3D du combat, pile-in AUTO, clairance
par-figurine) montaient le même harnais à quelques lignes près : un dict d'unité complété par
``unit_invariants()``, un état complété par ``turn_state_invariants()``, la config, le plateau,
puis ``build_units_cache``. À la troisième copie, un piège corrigé quelque part est un piège
toujours vivant ailleurs — c'est le seuil d'extraction habituel de ce répertoire (cf.
``_config_helpers`` et ``conftest.board_x5``, extraits pour ce motif).

CE QUI RESTE À L'APPELANT. Tout ce qui EST le sujet du test : le terrain, la géométrie des
positions, les caches de phase que sa phase exige (``build_enemy_adjacent_hexes``), les clés
d'état propres à sa phase (``charge_roll_values``, ``deployment_pools``…). Ce module ne connaît que
le socle commun ; il l'expose par ``**overrides`` plutôt qu'en devinant.

⚠️ CE N'EST PAS UN MOTEUR. Un état construit ici démarre TOUJOURS en placement fixe et ne passe par
aucun fichier de scénario : un test qui veut observer une phase de déploiement réelle doit passer
par ``_config_helpers.ACTIVE_DEPLOYMENT_SCENARIO`` (cf. le VERT VACANT documenté là-bas).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from engine.phase_handlers.shared_utils import build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants
from tests.unit.engine._config_helpers import build_game_rules, build_move_rules

#: Hauteur de figurine par défaut (pouces). Toute unité de roster en porte une, et l'engagement 3D
#: (§03.04) comme la clairance (§13.06) lèvent sans elle : l'omettre rendrait les états de test
#: incapables d'atteindre les chemins verticaux.
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
    figurines = [dict(m) for m in models]
    unit: Dict[str, Any] = {
        **unit_invariants(),
        "id": uid, "player": player,
        "col": int(figurines[0]["col"]), "row": int(figurines[0]["row"]),
        "HP_CUR": len(figurines), "HP_MAX": len(figurines),
        "VALUE": 100, "OC": 1, "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1, "ATTACK_LEFT": 1, "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": MODEL_HEIGHT,
        "MOVE": 6, "UNIT_RULES": [],
        "models": [{"level": 0, "VALUE": 10, **m} for m in figurines],
    }
    unit.update(overrides)
    return unit


def synthetic_state(
    units: List[Dict[str, Any]],
    *,
    inches_to_subhex: int = 1,
    board_cols: int = 60,
    board_rows: int = 60,
    terrain_areas: Sequence[Mapping[str, Any]] = (),
    game_rules: Mapping[str, Any] = (),  # type: ignore[assignment]
    **overrides: Any,
) -> Dict[str, Any]:
    """``game_state`` de test, caches construits (``build_units_cache``).

    ``game_rules`` : surcharges des règles RÉELLES (``build_game_rules``). Un test qui recopie un
    sous-ensemble de règles à la main tourne sur des règles figées, et toute clé nouvellement
    requise par le moteur lui manque en silence.

    ``inches_to_subhex`` : 1 = géométrie HEX (``geometry_is_hex``), au-dessus = EUCLIDIENNE. Le
    choix n'est pas cosmétique — à x1 tout le chemin multi-niveaux est court-circuité, et un test
    vertical monté à x1 passe au vert sans exécuter ce qu'il croit vérifier.
    """
    state: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": {
            "game_rules": build_game_rules(**dict(game_rules)),
            "move": build_move_rules(),
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": board_cols, "board_rows": board_rows,
        "current_player": 1,
        "wall_hexes": set(),
        "terrain_areas": [dict(a) for a in terrain_areas],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(), "units_fled": set(), "units_advanced": set(),
        "units_selected_to_fight": set(),
        "_unit_move_version": 0,
        "inches_to_subhex": int(inches_to_subhex),
        "action_logs": [],
        "action_log_seq": 0,
        "current_turn": 1,
    }
    state.update(overrides)
    build_units_cache(state)
    return state
