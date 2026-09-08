"""T4 — 13.09 sur les entites ENNEMIES : `hidden` emis pour toutes, `los_can_see` = visible ET detectable.

Regle lue (Documentation/40k_rules/13 Terrain.pdf) :
- 13.09 Hidden : hideable (INFANTRY/BEASTS/SWARM) + within une zone obscurante + l unite n a fait
  aucune attaque a distance ce tour ni au tour precedent. « While a model is hidden, it can only be
  visible to enemy models that are within its detection range » — 15" par defaut. 13.09 modifie donc
  la VISIBILITE elle-meme, pas seulement une eligibilite posee apres coup.
- 13.10 Obscuring : les zones traversees dont l un des deux modeles fait partie sont EXCLUES du test,
  donc une cible A L INTERIEUR de la zone reste geometriquement visible depuis l exterieur.

Ce que ces tests verrouillent, et pourquoi :
`los_can_see` ne portait que 06.01 (`compute_unit_los`). La porte de detection ne vivait que dans
l eligibilite du tir (`valid_target_pool_build`), donc l observation annoncait `los_can_see = 1` sur
une cible que l action de tir refusait — l agent ne pouvait apprendre ni a entrer dans les 15", ni a
se cacher au-dela. `test_los_can_see_zero_implies_pool_exclusion` est le contrat D1 correspondant, et
`test_d1_survives_a_loss_mid_phase` l etend dans le temps : l observation recalculant 13.09 a chaud
quand le moteur lit un drapeau stocke, l accord des deux ne tient que si la PERTE d une figurine
rafraichit ce drapeau (13.09 est un etat continu, cf. `destroy_model`).

Contre-epreuves integrees :
- `test_hidden_enemy_within_detection_is_visible` : meme escouade, meme terrain, seule la DISTANCE
  change. Sans elle, un `los_can_see = 0` constant passerait les tests « loin ».
- `test_enemy_that_shot_is_not_hidden` : le volet « n a pas tire » de 13.09 rouvre la visibilite.
- `test_undeployed_entity_has_no_terrain_state` : §0.40 point 5, l entite pas encore posee n a pas
  d etat de terrain (ses figurines sont a la sentinelle -1,-1).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.w40k_core import W40KEngine
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index, unit_cont_index
from tests.unit.engine._config_helpers import build_engine_config, build_game_rules

BIN_HIDDEN = unit_bin_index("hidden")
BIN_LOS = unit_bin_index("los_can_see")
BIN_PRESENT = unit_bin_index("present")
CONT_EDGE = unit_cont_index("edge_distance")

# Zone de terrain obscurante, colonnes 28..36 / lignes 18..22. L ennemi y tient entierement.
_AREA_HEXES = [[c, r] for c in range(28, 37) for r in range(18, 23)]
_AREA_POLYGON = [[28, 18], [36, 18], [36, 22], [28, 22]]
# Mur dense (Solid 13.11) dans la zone : 13.09 exige une zone contenant du terrain dense.
# Place en (28,18), hors de la ligne de vue est-ouest utilisee par les tests (ligne 20).
_DENSE_WALL = [[28, 18]]

_ENEMY_POSITIONS = [(30, 20), (32, 20)]
#: Ennemi A CHEVAL sur le bord est de la zone (colonnes 28..36) : une figurine dedans, une dehors.
#: L escouade n est donc PAS cachee tant que l exposee vit — c est le seul etat depuis lequel une
#: PERTE peut faire basculer 13.09 en cours de phase.
_ENEMY_STRADDLING = [(36, 20), (38, 20)]
#: Colonnes du tireur. La figurine ennemie la plus proche est en colonne 32 et
#: ``detection_range`` vaut 15" (config/game_config.json), a 1 subhex par pouce dans ce fixture.
_COL_BEYOND_DETECTION = 54   # ~22" de la figurine ennemie la plus proche -> hors detection
_COL_WITHIN_DETECTION = 42   # ~10" -> dans la detection
#: Portee de l arme du tireur : 24", donc les DEUX distances sont a portee. C est ce qui rend le
#: test discriminant — a 22" la cible est hors detection mais BIEN dans la portee de l arme, donc
#: son exclusion ne peut pas venir d un simple depassement de portee.
_WEAPON_RANGE = 24


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": _WEAPON_RANGE,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
        # Requis par `weapon_availability_check` (0 = arme pas encore tiree) : le contrat D1
        # passe par le vrai chemin d eligibilite du moteur, pas par un raccourci.
        "shot": 0,
    }


def _unit_cfg(
    uid: int, player: int, positions: List[Tuple[int, int]], keywords: List[str]
) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": k} for k in keywords],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(
    shooter_col: int, enemy_positions: List[Tuple[int, int]] = _ENEMY_POSITIONS
) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    shooter_positions = [(shooter_col, 20), (shooter_col + 2, 20)]
    return {
        "board": {
            "default": {
                "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "inches_to_subhex": 1,
            }
        },
        # `build_game_rules` part des VRAIES regles (config/game_config.json), donc
        # `detection_range` = 15 est present sans que ce fixture ait a le recopier.
        "game_rules": build_game_rules(
            engagement_zone=1, engagement_zone_vertical=5, max_base_size_hex=35,
            unit_model_cohesion_range=2, unit_global_cohesion_range=9,
            squad_min_neighbors=1, cohesion_distance_mode="euclidean",
        ),
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            # Unite 1 = MON tireur, hors zone de terrain. Unite 2 = l ennemi, dans la zone.
            _unit_cfg(1, 1, shooter_positions, ["INFANTRY"]),
            _unit_cfg(2, 2, enemy_positions, ["INFANTRY"]),
        ],
    }


def _make_engine(
    shooter_col: int, enemy_positions: List[Tuple[int, int]] = _ENEMY_POSITIONS
) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config(shooter_col, enemy_positions)))
    eng.reset()
    gs = eng.game_state
    gs["terrain_areas"] = [{
        "id": "area1", "obscuring": True,
        "polygon_vertices": _AREA_POLYGON, "hexes": _AREA_HEXES,
    }]
    gs["dense_wall_hexes"] = _DENSE_WALL
    for key in ("_dense_wall_set_cache", "_obs_solid_terrain_areas", "_obscuring_area_sets_cache"):
        gs.pop(key, None)
    return eng


def _enemy_row(engine: W40KEngine):
    """Ligne du tenseur ENNEMI decrivant l unite 2, vue depuis l unite 1."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    slots = [i for i, r in enumerate(obs["enemies_bin"]) if float(r[BIN_PRESENT]) == 1.0]
    assert len(slots) == 1, f"fixture : 1 seul ennemi attendu, {len(slots)} presents"
    return obs["enemies_bin"][slots[0]], obs["enemies_cont"][slots[0]]


def _pool(engine: W40KEngine, *, refresh: bool = True) -> List[str]:
    """Pool de cibles du tireur, par le chemin REEL de l action de tir.

    ``refresh`` rejoue le balayage complet de debut de phase (``compute_hidden_statuses``, qui
    pose le drapeau que lit la porte 13.09) puis ``build_unit_los_cache`` a l activation du
    tireur. Le passer a ``False`` observe le moteur EN COURS de phase, ou ce balayage n a plus
    lieu : seul le rafraichissement cible de ``destroy_model`` a pu mettre le statut a jour.
    """
    from engine.phase_handlers.shooting_handlers import (
        build_unit_los_cache, compute_hidden_statuses, valid_target_pool_build,
    )
    from engine.game_utils import require_unit_by_id
    if refresh:
        compute_hidden_statuses(engine.game_state)
    build_unit_los_cache(engine.game_state, "1")
    return valid_target_pool_build(
        engine.game_state, require_unit_by_id(engine.game_state, "1"), 0, 0, 0
    )


def _flags(engine: W40KEngine) -> Dict[str, float]:
    binv, cont = _enemy_row(engine)
    return {
        "hidden": float(binv[BIN_HIDDEN]),
        "los": float(binv[BIN_LOS]),
        "edge": float(cont[CONT_EDGE]),
    }


def test_hidden_enemy_beyond_detection_is_not_visible():
    """13.09 : ennemi cache au-dela de la detection range -> `los_can_see = 0` malgre la LoS.

    Contre-epreuve de vacuite : on verifie que la distance observee depasse REELLEMENT 15" et
    reste sous la portee de l arme (24"). Sans ces deux bornes, un `los_can_see = 0` du a un
    obstacle ou a un hors-portee passerait pour un succes de 13.09.
    """
    f = _flags(_make_engine(_COL_BEYOND_DETECTION))
    assert f["edge"] > 15.0, f"fixture : distance {f['edge']} pas au-dela de la detection 15\""
    assert f["edge"] <= _WEAPON_RANGE, f"fixture : distance {f['edge']} hors portee d arme"
    assert f["hidden"] == 1.0
    assert f["los"] == 0.0


def test_hidden_enemy_within_detection_is_visible():
    """Meme escouade, meme terrain, distance reduite : la detection rouvre la visibilite."""
    f = _flags(_make_engine(_COL_WITHIN_DETECTION))
    assert f["edge"] <= 15.0, f"fixture : distance {f['edge']} deja hors detection"
    assert f["hidden"] == 1.0
    assert f["los"] == 1.0


@pytest.mark.parametrize("shot_key", ["units_shot", "units_shot_previous_turn"])
def test_enemy_that_shot_is_not_hidden(shot_key: str):
    """13.09 : l unite qui a tire ce tour OU au precedent n est plus cachee, donc redevient visible.

    C est le volet de 13.09 qui ne depend d aucune geometrie : a distance INCHANGEE (hors
    detection), le seul fait d avoir tire remet `los_can_see` a 1.
    """
    eng = _make_engine(_COL_BEYOND_DETECTION)
    eng.game_state.setdefault(shot_key, set()).add("2")
    f = _flags(eng)
    assert f["edge"] > 15.0
    assert f["hidden"] == 0.0
    assert f["los"] == 1.0


def test_undeployed_entity_has_no_terrain_state():
    """§0.40 point 5 : une entite pas encore posee n a pas d etat de terrain (sentinelle -1,-1)."""
    eng = _make_engine(_COL_WITHIN_DETECTION)
    assert _flags(eng)["hidden"] == 1.0, "contre-epreuve : cachee tant qu elle est posee"
    from engine.game_utils import require_unit_by_id
    require_unit_by_id(eng.game_state, "2")["deployed_on_turn"] = None
    assert _flags(eng)["hidden"] == 0.0


def test_los_can_see_zero_implies_pool_exclusion():
    """Contrat D1 : `los_can_see = 0` => le moteur refuse la cible ; = 1 => il l accepte ici.

    L oracle est `valid_target_pool_build`, la fonction que l action de tir execute. Le sens fort
    est l implication (l eligibilite exige AUSSI la portee, 10.04, etc.) ; l egalite n est
    verifiee que parce que ce fixture neutralise toutes les autres causes d exclusion — un seul
    ennemi, a portee, aucun allie au contact, tireur non engage.

    Anti-vacuite : le cas PROCHE doit rendre un pool NON VIDE. Sans cette assertion, un pool
    toujours vide (mauvaise phase, mauvais arguments) rendrait l implication trivialement vraie.
    """
    near = _make_engine(_COL_WITHIN_DETECTION)
    near_pool = _pool(near)
    assert near_pool, "anti-vacuite : le pool proche doit etre NON VIDE"
    assert "2" in near_pool
    assert _flags(near)["los"] == 1.0

    far = _make_engine(_COL_BEYOND_DETECTION)
    assert _flags(far)["los"] == 0.0
    assert "2" not in _pool(far), "13.09 : la cible cachee hors detection est refusee par le moteur"


def test_d1_survives_a_loss_mid_phase():
    """Contrat D1 en cours de phase : une PERTE ne desaccorde pas l observation et le moteur.

    Le contrat D1 ci-dessus est verifie au debut de la phase de tir, quand le balayage complet
    vient de poser le statut. Or l observation recalcule 13.09 a chaud a chaque step tandis que le
    moteur lit un drapeau stocke : sans rafraichissement a la perte, les deux se separent des la
    premiere figurine tuee, et c est le cas NOMINAL — les pertes vont d abord aux figurines les
    plus exposees.

    Ici l escouade ennemie est a cheval sur le bord de la zone obscurante, donc PAS cachee : les
    deux tireurs la voient et peuvent la prendre pour cible malgre les 15" depassees. Tuer la
    figurine exposee la rend cachee, donc intirable a cette distance. Le pool est relu SANS
    rejouer le balayage de debut de phase (`refresh=False`), ce qui est la situation reelle d un
    tireur qui s active apres la perte.

    Discriminance : les deux figurines ennemies sont deja au-dela de la detection (16" et 18") et
    en deca de la portee de l arme (24"). Ce n est donc pas la distance qui fait basculer
    l eligibilite — elle reste du meme cote des deux seuils — mais le seul statut 13.09.
    """
    from engine.phase_handlers.shared_utils import destroy_model
    from engine.game_utils import require_unit_by_id

    eng = _make_engine(_COL_BEYOND_DETECTION, _ENEMY_STRADDLING)
    gs = eng.game_state

    # Avant la perte : une figurine hors zone => escouade non cachee => visible ET ciblable.
    before = _flags(eng)
    assert before["hidden"] == 0.0, "fixture : la figurine exposee doit empecher le statut cache"
    assert 15.0 < before["edge"] <= _WEAPON_RANGE, (
        f"fixture : distance {before['edge']} doit etre hors detection mais a portee"
    )
    assert before["los"] == 1.0
    assert "2" in _pool(eng), "anti-vacuite : sans la cible au depart, la suite ne mesurerait rien"

    exposed = next(
        mid for mid in gs["squad_models"]["2"]
        if (int(gs["models_cache"][mid]["col"]), int(gs["models_cache"][mid]["row"])) == (38, 20)
    )
    destroy_model(gs, exposed, reason="combat")

    # Apres la perte, SANS balayage de debut de phase : les deux oracles doivent basculer ensemble.
    after = _flags(eng)
    assert after["hidden"] == 1.0, "13.09 : il ne reste que des figurines en zone obscurante"
    assert 15.0 < after["edge"] <= _WEAPON_RANGE, (
        f"fixture : distance {after['edge']} doit rester hors detection et a portee"
    )
    assert after["los"] == 0.0
    assert "2" not in _pool(eng, refresh=False), (
        "D1 : le moteur doit refuser la cible que l observation vient de declarer invisible"
    )
    assert require_unit_by_id(gs, "2")["hidden"] is True
