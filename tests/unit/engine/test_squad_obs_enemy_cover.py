"""Verrou : l'observation porte le COUVERT EXACT de chaque ennemi, vu depuis l'observateur.

Trou fermé ici. Rien dans l'observation ne disait qu'une cible bénéficie du couvert (13.08),
alors que c'est directement le `-1 BS` de mon tir — donc l'espérance de dégâts. Le canal
« couvert » de la grille dit *où* sont les cases couvrantes, mais la fenêtre égocentrique
s'arrête au budget d'Advance (~12″ mesuré) quand une arme porte à 24″ : la cible tirable est
le plus souvent HORS de la grille.

Décision d'implémentation verrouillée ici : la source est `compute_unit_los`, la source
AUTORITATIVE du moteur — la même que `_cover_worsened_bs` (résolution du `-1 BS`) et que
l'affichage frontend. Une première version proposait un proxy « toutes mes figurines dans une
terrain area » : c'est UNE des deux conditions alternatives de 13.08, donc un bit à 0 aurait
voulu dire « indéterminé » et non « pas de couvert ». Ces tests prouvent que les DEUX branches
sont couvertes — c'est ce qu'un proxy intrinsèque échouerait à faire (cf.
`test_cover_via_partial_visibility_only`).

`los_can_see` accompagne `cover_vs_observer` pour lever son ambiguïté : sans lui, 0 se lit
« invisible » aussi bien que « visible sans couvert ».
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index
from engine.w40k_core import W40KEngine

BIN_PRESENT = unit_bin_index("present")
BIN_CAN_SEE = unit_bin_index("los_can_see")
BIN_COVER = unit_bin_index("cover_vs_observer")
BIN_IS_ALLY = unit_bin_index("is_ally")

# Zone de terrain rectangulaire, colonnes 28..36 / lignes 18..22 (fixture de
# test_squad_obs_terrain_flags, meme geometrie).
_AREA_HEXES = [[c, r] for c in range(28, 37) for r in range(18, 23)]
_AREA_POLYGON = [[28, 18], [36, 18], [36, 22], [28, 22]]


def _terrain_area(obscuring: bool) -> Dict[str, Any]:
    return {
        "id": "area1", "obscuring": obscuring,
        "polygon_vertices": _AREA_POLYGON, "hexes": _AREA_HEXES,
    }


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]]) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(mine: List[Tuple[int, int]], enemy: List[Tuple[int, int]]) -> Dict[str, Any]:
    obs_params = {
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
    }
    return {
        "board": {"default": {
            "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
            "wall_hexes": [], "inches_to_subhex": 1,
        }},
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
        },
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
        "units": [_unit_cfg(1, 1, mine), _unit_cfg(2, 2, enemy)],
    }


def _make_engine(cfg: Dict[str, Any], *, area: bool, obscuring: bool = False) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=cfg)
    eng.reset()
    gs = eng.game_state
    gs["terrain_areas"] = [_terrain_area(obscuring)] if area else []
    gs["dense_wall_hexes"] = []
    for key in ("_dense_wall_set_cache", "_obs_solid_terrain_areas",
                "_obscuring_area_sets_cache", "_unit_los_pair_cache"):
        gs.pop(key, None)
    return eng


def _enemy_bits(engine) -> Tuple[float, float]:
    """(los_can_see, cover_vs_observer) du premier slot ennemi present."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    eb = obs["enemies_bin"]
    row = next(i for i in range(ObservationBuilder.K_ENEMY_SLOTS) if eb[i][BIN_PRESENT] == 1.0)
    return float(eb[row][BIN_CAN_SEE]), float(eb[row][BIN_COVER])


def test_enemy_in_the_open_is_visible_without_cover():
    """Reference : ligne de vue degagee, aucun terrain -> vu, pas de couvert."""
    eng = _make_engine(_config([(10, 20)], [(20, 20)]), area=False)
    can_see, cover = _enemy_bits(eng)
    assert can_see == 1.0, "ennemi a vue degagee non vu"
    assert cover == 0.0, "couvert accorde sans aucun terrain"


def test_enemy_inside_a_terrain_area_has_cover():
    """13.08 branche 1 : la cible INFANTRY est within a terrain area -> couvert."""
    eng = _make_engine(_config([(10, 20)], [(30, 20)]), area=True)
    can_see, cover = _enemy_bits(eng)
    assert can_see == 1.0, "cible dans la zone mais invisible : geometrie du test cassee"
    assert cover == 1.0, "13.08 branche 1 non appliquee"


def _micro_engine(wall: List[List[int]]) -> W40KEngine:
    """Board MICRO (inches_to_subhex=5, socle 16 -> empreinte 169 hexes), sans terrain area.

    Le socle multi-hex est indispensable a ce cas : avec une figurine sur UN hex,
    `fully_visible` vaut toujours `can_see` (un footprint d'un hex est vu ou ne l'est pas), donc
    la branche 2 de 13.08 est structurellement inatteignable. C'est ce qu'une premiere version de
    ce test avait manque — elle affirmait tester la branche 2 sur un board a 1 hex par figurine
    et ne verifiait en realite qu'un accord trivial.
    """
    cfg = _config([(10, 20)], [(40, 20)])
    cfg["board"]["default"]["inches_to_subhex"] = 5
    cfg["board"]["default"]["wall_hexes"] = wall
    for unit in cfg["units"]:
        unit["BASE_SHAPE"] = "round"
        unit["BASE_SIZE"] = 16
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=cfg)
    eng.reset()
    gs = eng.game_state
    gs["terrain_areas"] = []
    gs["dense_wall_hexes"] = []
    gs.pop("_unit_los_pair_cache", None)
    return eng


def test_cover_via_partial_visibility_only():
    """13.08 branche 2 — celle qu'un proxy « within a terrain area » MANQUERAIT.

    Mur PARTIEL entre les deux unites : la cible reste visible (>= 1 hex de son empreinte) mais
    n'est plus *entierement* visible, donc elle a le benefice du couvert **sans aucune terrain
    area sur la table**. Un bit derive de l'appartenance a une zone vaudrait 0 ici, et l'agent
    croirait tirer sans malus alors que la resolution applique -1 BS.
    """
    from engine.phase_handlers.shooting_handlers import compute_unit_los

    eng = _micro_engine([[c, r] for c in (25, 26) for r in range(14, 20)])
    gs = eng.game_state
    assert not gs["terrain_areas"], "ce test doit prouver un couvert SANS terrain area"

    los = compute_unit_los(gs, gs["unit_by_id"]["1"], gs["unit_by_id"]["2"])
    # Ancrage : on est bien dans le cas « visible mais pas entierement ».
    assert los["can_see"] is True, "geometrie cassee : la cible doit rester visible"
    assert los["fully_visible"] is False, "geometrie cassee : la cible doit etre partiellement masquee"
    assert los["cover"] is True, "13.08 branche 2 non appliquee par le moteur"

    can_see, cover = _enemy_bits(eng)
    assert can_see == 1.0
    assert cover == 1.0, "la branche 2 de 13.08 n'atteint pas l'observation"


def test_no_cover_when_fully_visible_on_a_micro_board():
    """Contre-epreuve du precedent : sans mur, meme geometrie -> aucun couvert."""
    eng = _micro_engine([])
    can_see, cover = _enemy_bits(eng)
    assert can_see == 1.0
    assert cover == 0.0, "couvert accorde alors que la cible est entierement visible"


def test_fully_blocked_enemy_is_neither_seen_nor_covered():
    """Mur COMPLET : plus de visibilite -> `can_see`=0 et `cover`=0 (13.08 exige de voir)."""
    eng = _micro_engine([[c, r] for c in (25, 26) for r in range(8, 34)])
    can_see, cover = _enemy_bits(eng)
    assert can_see == 0.0, "cible entierement masquee declaree visible"
    assert cover == 0.0


def test_matches_the_engine_resolution_source_on_every_enemy():
    """La feature EGALE `compute_unit_los` — la source du `-1 BS` — pour tous les slots."""
    from engine.phase_handlers.shooting_handlers import compute_unit_los

    for area in (False, True):
        eng = _make_engine(_config([(10, 20), (11, 20)], [(30, 20), (31, 20)]), area=area)
        gs = eng.game_state
        obs = eng.obs_builder.build_squad_observation(gs, "1")
        eb = obs["enemies_bin"]
        from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

        slots = get_enemy_slot_mapping(gs, 1)
        checked = 0
        for i, esid in enumerate(slots):
            if esid is None or esid not in gs["units_cache"]:
                continue
            los = compute_unit_los(gs, gs["unit_by_id"]["1"], gs["unit_by_id"][str(esid)])
            assert float(eb[i][BIN_CAN_SEE]) == (1.0 if los["can_see"] else 0.0)
            assert float(eb[i][BIN_COVER]) == (1.0 if los["cover"] else 0.0)
            checked += 1
        assert checked > 0, "aucun slot ennemi verifie"


def test_cover_implies_can_see():
    """Invariant : `cover` sans `can_see` serait incoherent (13.08 exige de pouvoir tirer)."""
    for area in (False, True):
        eng = _make_engine(_config([(10, 20)], [(30, 20)]), area=area)
        can_see, cover = _enemy_bits(eng)
        assert not (cover == 1.0 and can_see == 0.0)


def test_bits_are_not_emitted_for_allies():
    """Ces bits decrivent une PAIRE observateur -> ennemi : ils n'ont aucun sens pour un allie.

    Y compris pour l'unite active elle-meme (ligne 0 du bloc amis) : « ai-je le couvert » n'est
    pas defini sans choisir un tireur — c'est `in_cover` (intrinseque) qui porte cette question.
    """
    eng = _make_engine(_config([(10, 20)], [(30, 20)]), area=True)
    ab = eng.obs_builder.build_squad_observation(eng.game_state, "1")["allies_bin"]
    for row in range(ObservationBuilder.K_ALLY_SLOTS):
        assert ab[row][BIN_CAN_SEE] == 0.0, f"allies[{row}] : bit de paire emis"
        assert ab[row][BIN_COVER] == 0.0, f"allies[{row}] : bit de paire emis"
    assert ab[0][BIN_IS_ALLY] == 1.0, "ligne 0 doit etre l'unite active (amie)"


def test_cover_follows_the_enemy_moving_into_terrain():
    """Feature VIVANTE : le couvert suit le deplacement reel de la cible.

    Passe par `update_model_position`, le chemin d'ecriture qui declenche le choke-point
    d'invalidation LoS — sans quoi le pair-cache servirait la valeur d'avant le mouvement.
    C'est le scenario `reactive_move` : un ennemi qui bouge PENDANT mon tour.
    """
    from engine.phase_handlers.shared_utils import update_model_position

    eng = _make_engine(_config([(10, 20)], [(20, 20)]), area=True)
    gs = eng.game_state
    before_see, before_cover = _enemy_bits(eng)
    assert before_see == 1.0 and before_cover == 0.0, "etat initial inattendu (hors zone, a vue)"

    mid = gs["squad_models"]["2"][0]
    update_model_position(gs, mid, 30, 20)

    after_see, after_cover = _enemy_bits(eng)
    assert after_cover == 1.0, "couvert non mis a jour apres entree dans la zone (cache perime)"
    assert after_see == 1.0
