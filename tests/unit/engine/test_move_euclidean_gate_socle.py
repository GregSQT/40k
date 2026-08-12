"""Le champ géodésique euclidien du pool de move est réservé au socle MONO-HEX (03, §4.1).

VERROU d'une ligne qui n'en avait aucun (mesuré le 2026-08-12) : dans
`movement_build_valid_destinations_pool`, la garde du chemin euclidien any-angle s'écrivait
`base_size == 1 and unit["BASE_SHAPE"] == "round"` — le corps littéral de
`hex_utils.socle_is_single_hex`, qui se déclare source unique du prédicat. La remplacer par
`and True` laissait VERTS tous les fichiers de test du mouvement : ils tournent en métrique `hex`
(board x1), donc la condition entière était fausse avant d'atteindre le prédicat.

CE QUI DISCRIMINE RÉELLEMENT CETTE GARDE — et pourquoi le socle témoin est `square`/1 et non
`oval` : le chemin euclidien est déjà sous-tendu par `is_single_hex = _geometry_is_hex or
base_size == 1`. Un socle `oval` porte une PAIRE `[grand axe, petit axe]` (invariant du socle,
`require_base_size`), donc `base_size == 1` y est faux et l'oval part sur le chemin MULTI-HEX
sans jamais atteindre la garde : un test à socle oval serait VERT quel que soit le prédicat.
Le seul socle qui atteint la garde en la faisant basculer est celui dont la taille est le
scalaire 1 et la forme n'est PAS ronde — `square`/1. C'est aussi la seule chose que la garde
ajoute à `is_single_hex`, et elle compte : `socle_is_single_hex` est conservateur par
construction (cf. sa docstring), un `square`/1 y vaut `False`.

PORTÉE DE CE VERROU, à savoir avant de s'y appuyer : la branche qu'il garde n'est atteinte par
AUCUNE datasheet du dépôt. Le plus petit `BASE_SIZE` de roster vaut 10, que `_scale_socle` rend
≥ 5 à x5 et ≥ 10 à x10, tandis qu'à x1 `resolve_gym_split_metric` force la métrique `hex`. Ce
fichier verrouille donc la GARDE (une copie de prédicat qui a déjà divergé quatre fois dans ce
dépôt), pas un comportement de partie ; la question de faire vivre ou de supprimer ce chemin
géodésique mono-hex est remontée en arbitrage le 2026-08-12.

L'écart observable est la VERTICALE : le budget géodésique est `MOVE × 1.5` en unités
`_hex_center`, où un pas nord coûte `sqrt(3)` ≈ 1,732. Le chemin euclidien atteint donc moins
loin vers le nord que le BFS hex, qui compte 1 par pas.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

from engine import phase_handlers
from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

#: Board x5 : `geometry_is_hex` est FAUX, donc la métrique configurée s'applique et le socle
#: n'est pas normalisé en `round`/1 (cf. `game_state._scale_socle`).
INCHES_TO_SUBHEX = 5
START = (25, 25)
MOVE = 6


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test Bolter"}


def _unit_cfg(
    uid: int, player: int, col: int, row: int, base_shape: str, base_size: Any
) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3, "HP_MAX": 3, "MOVE": MOVE, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": base_shape, "BASE_SIZE": base_size, "MODEL_HEIGHT": 2.5,
    }


def _make_engine(base_shape: str, base_size: Any) -> W40KEngine:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [],
                              "inches_to_subhex": INCHES_TO_SUBHEX}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                       "max_base_size_hex": 35},
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _unit_cfg(1, 1, START[0], START[1], base_shape, base_size),
            _unit_cfg(2, 2, 55, 55, base_shape, base_size),
        ],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(config))
    eng.reset()
    eng.game_state["phase"] = "move"
    from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes
    build_enemy_adjacent_hexes(eng.game_state, 1)
    build_enemy_adjacent_hexes(eng.game_state, 2)
    return eng


def _pool(engine: W40KEngine, metric: str) -> set:
    """Pool de l'unité 1 avec la métrique de move FORCÉE.

    On patche le SÉLECTEUR (`movement_handlers._move_distance_metric`) et non la config : à x5 la
    métrique effective sort de `combat_utils.resolve_gym_split_metric`, qui lit le config-loader
    global — le mutiler contaminerait les autres tests du process.
    """
    with patch.object(
        phase_handlers.movement_handlers, "_move_distance_metric", return_value=metric
    ):
        return set(movement_build_valid_destinations_pool(engine.game_state, "1", read_only=True))


def test_non_round_single_size_base_stays_on_the_hex_bfs_in_euclidean_metric():
    """`square`/1 : la garde doit refuser le champ euclidien → pool IDENTIQUE au BFS hex.

    Sans le prédicat, ce socle basculerait sur le champ géodésique any-angle, dont la portée
    verticale est plus courte (cf. docstring du module) : le pool rétrécit et l'égalité tombe.
    """
    eng = _make_engine("square", 1)
    hex_pool = _pool(eng, "hex")
    euclid_pool = _pool(eng, "euclidean")

    assert hex_pool, "pool vide : le test ne mesurerait rien"
    assert euclid_pool == hex_pool
    # La case atteinte en MOVE pas plein nord : dans le pool hex, hors de portée géodésique.
    assert (START[0], START[1] - MOVE) in euclid_pool


def test_round_single_size_base_does_take_the_euclidean_field():
    """Garde-fou anti-VERT-VACANT : le chemin euclidien est bien atteignable dans ce montage.

    Même board, même budget, seule la FORME du socle change. Si cette assertion tombait, le test
    frère ci-dessus passerait sans jamais rien discriminer.
    """
    eng = _make_engine("round", 1)
    hex_pool = _pool(eng, "hex")
    euclid_pool = _pool(eng, "euclidean")

    assert euclid_pool != hex_pool
    assert (START[0], START[1] - MOVE) in hex_pool
    assert (START[0], START[1] - MOVE) not in euclid_pool
