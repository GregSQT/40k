"""En métrique euclidean, AUCUN socle ne mesure son move en pas d'hexagone (règle 03, §4.1).

Le pool de move a deux routes : un BFS hexagonal qui compte 1 par pas, et un champ géodésique
continu qui mesure une longueur réelle. Le choix de route est celui de la MÉTRIQUE, pas celui du
socle — c'est ce que ce fichier verrouille, sur les deux formes de socle mono-hex.

HISTORIQUE, parce que c'est ce qui rend le verrou nécessaire (2026-08-12). Une troisième route
vivait dans `movement_build_valid_destinations_pool` : un `geodesic_field` sans empreinte, gardé
par `métrique euclidean ET socle mono-hex`, où la condition de socle était le corps LITTÉRAL de
`hex_utils.socle_is_single_hex` — sa 4e copie. Deux défauts en un :
  - la copie classait mono-hex un socle non rond de taille scalaire 1, dont l'empreinte n'est pas
    forcément l'ancre. Aucun test ne le voyait : ils tournent tous en métrique `hex`, donc la
    garde était fausse avant d'atteindre la condition de socle (muter celle-ci en `and True`
    laissait VERTE toute la suite du mouvement) ;
  - la route elle-même était inatteignable en partie (métrique forcée `hex` à x1, socle >= 5 cases
    à x5) et dupliquait la géométrie continue de `_euclidean_ground_anchor_multihex`.
Elle a été supprimée : le choix de route vit maintenant dans `_mono_hex_bfs_shortcut`, un seul
corps pour les deux branches (sol et FLY), et le raccourci BFS y est gardé par la MÉTRIQUE. Un
socle mono-hex en euclidean part donc sur le chemin continu — la seule route qui applique la
règle 03 en longueur.

CE QUE CE FICHIER MESURE. Le budget géodésique vaut `MOVE × 1.5` en unités `_hex_center`, où un
pas plein nord coûte `sqrt(3)` ≈ 1,732 : la case à MOVE pas au nord est donc dans le pool du BFS
hex et HORS de portée continue. C'est l'écart observable qui distingue les deux routes.

Le socle témoin est `square`/1 et non `oval` : un oval porte une PAIRE `[grand axe, petit axe]`
(invariant du socle, `require_base_size`), il n'est jamais mono-hex et ne discrimine donc aucune
des deux gardes. La taille scalaire 1 à x5 n'est produite par aucune datasheet du dépôt (plus
petit `BASE_SIZE` = 10) : ce fichier verrouille le ROUTAGE, pas un comportement de partie.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

from engine import phase_handlers
from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

#: Board x5 : `geometry_is_hex` est FAUX, donc la métrique configurée s'applique et le socle n'est
#: pas normalisé en `round`/1 (cf. `game_state._scale_socle`).
INCHES_TO_SUBHEX = 5
START = (25, 25)
MOVE = 6
#: Case à MOVE pas plein nord : dans le pool du BFS hex, hors de portée du champ continu.
DUE_NORTH = (START[0], START[1] - MOVE)


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test Bolter"}


def _unit_cfg(
    uid: int, player: int, col: int, row: int, base_shape: str, base_size: Any,
    *, fly: bool = False,
) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        # Vol déclaré : 21.03 retranche 2" du budget, soit 2 × inches_to_subhex subhex. On les
        # rajoute au profil pour que les deux routes comparent le MÊME budget que la version au sol.
        "HP_CUR": 3, "HP_MAX": 3,
        "MOVE": MOVE + (2 * INCHES_TO_SUBHEX if fly else 0), "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [{"keywordId": "fly"}] if fly else [],
        "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": base_shape, "BASE_SIZE": base_size, "MODEL_HEIGHT": 2.5,
    }


def _make_engine(base_shape: str, base_size: Any, *, fly: bool = False) -> W40KEngine:
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
            _unit_cfg(1, 1, START[0], START[1], base_shape, base_size, fly=fly),
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
    if fly:
        # Déclaration 21.03 pour le move en cours — SOURCE UNIQUE lue par `took_to_the_skies`.
        eng.game_state["units_took_to_skies"] = {"1"}
    return eng


def _pool(engine: W40KEngine, metric: str, *, read_only: bool = True) -> set:
    """Pool de l'unité 1 avec la métrique de move FORCÉE.

    On patche le SÉLECTEUR (`movement_handlers._move_distance_metric`) et non la config : la
    métrique effective sort de `combat_utils.resolve_gym_split_metric`, qui lit le config-loader
    global — le muter contaminerait les autres tests du process.

    ``read_only=False`` fait aussi écrire l'état de preview (`move_preview_footprint_zone`), qui
    vit APRÈS la sortie anticipée du chemin read_only et ne serait sinon jamais exécuté ici.
    """
    with patch.object(
        phase_handlers.movement_handlers, "_move_distance_metric", return_value=metric
    ):
        return set(
            movement_build_valid_destinations_pool(engine.game_state, "1", read_only=read_only)
        )


@pytest.mark.parametrize("fly", [False, True], ids=["ground", "fly"])
@pytest.mark.parametrize("base_shape", ["round", "square"])
def test_single_hex_base_does_not_measure_its_move_in_hex_steps_in_euclidean(
    base_shape: str, fly: bool
):
    """Socle mono-hex : en euclidean, le pool vient du chemin continu, pas du raccourci hex.

    Les deux routes ont leur propre choix (sol et FLY 21.03), et elles avaient le même défaut :
    décider sur le socle seul, si bien qu'un mono-hex mesurait en pas d'hexagone au milieu d'une
    partie euclidienne. Le budget est le même des deux côtés — pour le vol, le -2" de 21.03 est
    rajouté au profil.

    L'assertion sur le pool `hex` n'est pas décorative : c'est elle qui prouve que la case témoin
    est bien atteignable à ce budget, donc que son absence du pool euclidien mesure la métrique et
    non un board trop petit (vert vacant).
    """
    eng = _make_engine(base_shape, 1, fly=fly)
    hex_pool = _pool(eng, "hex")
    euclid_pool = _pool(eng, "euclidean")

    assert DUE_NORTH in hex_pool, "case témoin hors du pool hex : le test ne mesurerait rien"
    assert DUE_NORTH not in euclid_pool
    assert euclid_pool, "pool euclidien vide : le chemin continu n'a rien produit"


@pytest.mark.parametrize(
    "fly,metric",
    [(False, "euclidean"), (True, "euclidean"), (True, "hex")],
    ids=["ground-euclidean", "fly-euclidean", "fly-hex"],
)
def test_preview_footprint_zone_follows_the_same_route(fly: bool, metric: str):
    """La preview est écrite APRÈS le pool, par un site qui teste lui aussi la route.

    Elle ne peut pas DISCRIMINER la route ici — l'empreinte d'un socle mono-hex vaut son ancre,
    donc « union des empreintes des ancres » et « ensemble des ancres » sont le même ensemble. Ce
    test exécute donc ces lignes et vérifie le seul sens qui soit un invariant : la preview COUVRE
    le pool AU SOL (le niveau 0 ; les destinations d'étage vivent dans un autre état, que la preview
    n'éclaire pas), sinon une case jouable resterait éteinte. L'inclusion inverse n'en est PAS un — le
    bornage rigide d'escouade retire des ancres du pool en laissant la zone complète, exprès, pour
    que le fantôme PvP ne clignote pas au bord du plateau.
    """
    eng = _make_engine("round", 1, fly=fly)
    pool = _pool(eng, metric, read_only=False)
    zone = eng.game_state["move_preview_footprint_zone"]

    assert pool, "pool vide : l'inclusion ci-dessous serait vacante"
    assert START in zone, "la case de départ manque à la preview"
    assert pool <= zone, "des destinations du pool ne sont pas éclairées par la preview"
    if metric == "euclidean":
        # Exact ici, et seulement ici : l'empreinte d'un socle mono-hex n'a pas de rayon, donc la
        # zone ne peut pas déborder plus loin que ses ancres, elles-mêmes bornées en longueur.
        assert DUE_NORTH not in zone, "la preview propose une case hors de portée continue"
    else:
        # Le cas `fly-hex` est le SEUL qui exécute la preview mono-hex de la branche FLY : en
        # euclidean le chemin vectorisé rend la main avant, et le régime `read_only` sort encore
        # plus tôt. Sans lui, le repli mort retiré de cette branche ne serait vérifié par personne.
        assert DUE_NORTH in zone, "le disque hex atteint cette case : la preview doit l'éclairer"
