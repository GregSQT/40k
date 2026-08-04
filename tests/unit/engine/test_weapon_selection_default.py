"""V11 T-C — le défaut de sélection d'armes respecte enfin 04.01 et 04.02.

Trois écarts corrigés (constat `V11_entity_encoder_pointer.md` §1.3 / §1.4) :

| Avant | Règle | |
|---|---|---|
| une figurine ne tirait qu'**une** arme | **04.01** « you can select **one or more** ranged weapons that model has » | violation |
| toutes ses armes visaient la **même** cible | **04.02** « for each weapon selected: select one enemy unit to be the target **of that weapon** » | violation |
| l'arme tirée était l'index 0, jamais choisie | 04.01 | décision non prise |

Cause : `squad_declare_shoot` lisait `selectedRngWeaponIndex`, un champ écrit **uniquement**
par le flux PvP manuel — il valait donc 0 pendant toute la partie en gym.

Le quatrième point est l'heuristique de mêlée `_auto_select_cc_weapon_for_fig`, que P1 avait
rendue FAUSSE : elle notait les armes sur leurs stats brutes et ignorait [ANTI-X],
[DEVASTATING WOUNDS], [SUSTAINED HITS], [LETHAL HITS], [TWIN-LINKED]. Elle passe désormais par
`attack_sequence.expected_damage_per_attack`, le même modèle que la boucle de résolution.

⚠️ Ce n'est PAS le choix d'arme par l'agent (différé en P2/P3, cf. §5.3) : c'est le **défaut**,
qui était une violation de règle. Le rendre correct est ce qui rendra le *regret* mesurable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers import shared_utils
from engine.phase_handlers.shared_utils import (
    squad_declare_shoot,
    squad_shooting_unit_activation_start,
)
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


def _weapon(name: str, *, rng: int = 24, rules: List[str] | None = None, **over: Any) -> Dict[str, Any]:
    w = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": rng,
         "WEAPON_RULES": list(rules or []), "display_name": name}
    w.update(over)
    return w


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]], *,
              rng_weapons: List[Dict[str, Any]] | None = None,
              keywords: List[str] | None = None) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 2, "HP_MAX": 2, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 2 * len(specs), "HP_MAX": 2, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": rng_weapons if rng_weapons is not None else [_weapon("Gun")],
        "CC_WEAPONS": [{"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
                        "WEAPON_RULES": [], "display_name": "Blade"}],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [{"keywordId": k} for k in (keywords or ["INFANTRY"])],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _engine(units: List[Dict[str, Any]]) -> W40KEngine:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    cfg = {
        "board": {"default": {"cols": 120, "rows": 40, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                       "max_base_size_hex": 35, "unit_model_cohesion_range": 2,
                       "unit_global_cohesion_range": 9, "squad_min_neighbors": 1,
                       "cohesion_distance_mode": "euclidean"},
        "charge": {"charge_max_distance": 12},
        "move": {"can_move_through_enemy_engagement_zone": True,
                 "can_move_through_enemy_model": False,
                 "can_move_through_friendly_model": True},
        "pve_mode": False, "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": units,
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg))
    eng.reset()
    eng.game_state["phase"] = "shoot"
    return eng


def _declare(eng: W40KEngine, priority: str, slots: List[str]) -> List[Dict[str, Any]]:
    squad_shooting_unit_activation_start(eng.game_state, "1")
    return squad_declare_shoot(eng.game_state, "1", priority, slots)


# ------------------------------------------------------------------ 04.01


def test_a_model_declares_all_of_its_usable_weapons() -> None:
    """04.01 « one or more » : une figurine à 3 armes en déclare 3, pas 1.

    ROUGE avant le fix : un seul intent, sur l'arme d'index 0.
    """
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[
            _weapon("A", rng=30), _weapon("B", rng=30), _weapon("C", rng=30),
        ]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    intents = _declare(eng, "2", ["2"])
    assert sorted(i["weapon_index"] for i in intents) == [0, 1, 2]


def test_a_weapon_out_of_range_is_simply_not_declared() -> None:
    """Discrimination : seules les armes qui atteignent une cible sont déclarées."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[
            _weapon("Short", rng=2), _weapon("Long", rng=40),
        ]),
        _unit_cfg(2, 2, [(30, 10)]),
    ])
    intents = _declare(eng, "2", ["2"])
    assert [i["weapon_index"] for i in intents] == [1], "seule l'arme longue portee atteint la cible"


def test_the_declaration_no_longer_reads_the_selected_weapon_index() -> None:
    """Le champ `selectedRngWeaponIndex` (écrit par le seul flux PvP) ne pilote plus le gym."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[_weapon("A", rng=30), _weapon("B", rng=30)]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    eng.game_state["models_cache"]["1#0"]["selectedRngWeaponIndex"] = 1
    intents = _declare(eng, "2", ["2"])
    assert sorted(i["weapon_index"] for i in intents) == [0, 1], (
        "la declaration ne doit plus dependre de l'arme 'selectionnee'"
    )


# ------------------------------------------------------------------ 04.02


def test_each_weapon_picks_its_own_target() -> None:
    """04.02 : deux armes d'une même figurine peuvent viser DEUX unités différentes.

    L'arme courte n'atteint que l'ennemi proche, la longue n'atteint que le lointain —
    la cible prioritaire ne peut donc pas être imposée aux deux.
    """
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[
            _weapon("Short", rng=6), _weapon("Long", rng=60),
        ]),
        _unit_cfg(2, 2, [(14, 10)]),   # proche
        _unit_cfg(3, 2, [(60, 10)]),   # lointain
    ])
    intents = _declare(eng, "3", ["3", "2"])
    by_weapon = {i["weapon_index"]: i["target_unit_id"] for i in intents}
    assert by_weapon[1] == "3", "l'arme longue portee vise la cible prioritaire"
    assert by_weapon[0] == "2", "l'arme courte portee se rabat sur la cible qu'elle atteint"


def test_target_size_is_captured_per_weapon() -> None:
    """Chaque intent porte la taille de SA cible (04.05 [BLAST] la consomme)."""
    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[_weapon("Short", rng=6), _weapon("Long", rng=60)]),
        _unit_cfg(2, 2, [(14, 10), (15, 10), (16, 10)]),   # 3 figurines
        _unit_cfg(3, 2, [(60, 10)]),                        # 1 figurine
    ])
    intents = _declare(eng, "3", ["3", "2"])
    sizes = {i["weapon_index"]: i["target_squad_size_at_declaration"] for i in intents}
    assert sizes[0] == 3 and sizes[1] == 1


# ------------------------------------------------------------------ 24.07


def test_close_quarters_and_other_weapons_are_not_mixed() -> None:
    """24.07 (SIDEARMS) : hors MONSTER/VEHICLE, une figurine choisit une famille, pas les deux."""
    from engine.utils.weapon_helpers import weapon_has_rule

    eng = _engine([
        _unit_cfg(1, 1, [(10, 10)], rng_weapons=[
            _weapon("Rifle", rng=30),
            _weapon("CQ", rng=30, rules=["CLOSE_QUARTERS"]),
        ]),
        _unit_cfg(2, 2, [(20, 10)]),
    ])
    intents = _declare(eng, "2", ["2"])
    weapons = eng.game_state["models_cache"]["1#0"]["RNG_WEAPONS"]
    families = {weapon_has_rule(weapons[i["weapon_index"]], "CLOSE_QUARTERS") for i in intents}
    assert len(families) == 1, "une figurine ne melange pas [CLOSE-QUARTERS] et ses autres armes"


# ------------------------------------------------------------------ heuristique mêlée


def _best_melee(weapons: List[Dict[str, Any]], target_unit: Dict[str, Any]) -> int:
    fig = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "CC_WEAPONS": weapons}
    idx = shared_utils._auto_select_cc_weapon_for_fig(fig, 4, 3, 7, target_unit)
    assert idx is not None
    return idx


def _melee(name: str, *, rules: List[str] | None = None, **over: Any) -> Dict[str, Any]:
    w = {"display_name": name, "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 2,
         "WEAPON_RULES": list(rules or [])}
    w.update(over)
    return w


def test_melee_heuristic_prefers_an_anti_weapon_against_the_matching_keyword() -> None:
    """[ANTI-INFANTRY 2+] rend une arme faible meilleure contre de l'infanterie.

    ROUGE avant le fix : l'heuristique notait sur les stats brutes et choisissait toujours
    l'arme la plus forte, quelle que soit la cible.
    """
    weapons = [_melee("Brutal", STR=6), _melee("Anti", STR=3, rules=["ANTI_INFANTRY:2"])]
    infantry = {"id": "2", "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}]}
    assert _best_melee(weapons, infantry) == 1


def test_melee_heuristic_ignores_an_anti_weapon_against_another_keyword() -> None:
    """Discrimination : contre un VEHICLE, [ANTI-INFANTRY] ne s'applique pas."""
    weapons = [_melee("Brutal", STR=6), _melee("Anti", STR=3, rules=["ANTI_INFANTRY:2"])]
    vehicle = {"id": "2", "UNIT_KEYWORDS": [{"keywordId": "VEHICLE"}]}
    assert _best_melee(weapons, vehicle) == 0


def test_melee_heuristic_values_devastating_wounds() -> None:
    """À stats égales, [DEVASTATING WOUNDS] (blessure critique non sauvegardable) l'emporte."""
    weapons = [_melee("Plain"), _melee("Devastating", rules=["DEVASTATING_WOUNDS"])]
    target = {"id": "2", "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}]}
    assert _best_melee(weapons, target) == 1


def test_melee_heuristic_values_sustained_hits() -> None:
    """À stats égales, [SUSTAINED HITS 2] l'emporte (touches supplémentaires sur critique)."""
    weapons = [_melee("Plain"), _melee("Sustained", rules=["SUSTAINED_HITS:2"])]
    target = {"id": "2", "UNIT_KEYWORDS": []}
    assert _best_melee(weapons, target) == 1


def test_melee_heuristic_raises_on_invalid_damage_instead_of_defaulting() -> None:
    """Plus de repli silencieux : un DMG non résoluble est une donnée invalide, il lève."""
    weapons = [_melee("Broken", DMG="D7")]
    with pytest.raises(ValueError):
        _best_melee(weapons, {"id": "2", "UNIT_KEYWORDS": []})
