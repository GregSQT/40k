#!/usr/bin/env python3
"""Les 5 bits de mots-clés de CATÉGORIE de l'observation d'entité ↔ `UNIT_KEYWORDS`.

`kw_infantry`, `kw_vehicle`, `kw_monster`, `kw_fly`, `kw_psyker` sont émis par
`observation_builder._encode_unit_entity` depuis `unit_keywords_upper` — la source
qu'exécute la résolution de [ANTI-X] 24.03, et non `compute_hideable`.

Avant eux, l'observation décrivait le keyword ciblé par [ANTI-X] côté ARME (`wpn_rule_ids`,
vocabulaire `WEAPON_RULE_BITS + ANTI_RULE_IDS`) sans jamais dire si la CIBLE le portait : la
règle était structurellement inapprenable. Même trou pour le volet MONSTER/VEHICLE de 10.06 et
pour les gates de terrain 13.06/13.08/13.09.

Trois défauts sont verrouillés ici :

1. **Permutation du mapping** — chaque mot-clé doit allumer SON bit et lui seul. Sans le « lui
   seul », deux bits lisant le même mot-clé resteraient indétectables.
2. **Entités ennemies muettes** — le bit doit être émis pour TOUTE entité, pas seulement pour
   l'unité active : c'est la cible d'un tir qui décide de [ANTI-X], jamais le tireur.
3. **Absence silencieuse de `UNIT_KEYWORDS`** — `unit_keywords_upper` rend sciemment un ensemble
   vide sur une unité sans la clé ; ici cela écrirait « aucune catégorie » sans rien lever.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from ai.unit_registry import UnitRegistry
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import UNIT_BIN_FIELDS, unit_bin_index
from engine.w40k_core import W40KEngine
from shared.data_validation import ConfigurationError
from tests.unit.engine._config_helpers import build_engine_config

#: bit d'observation → mot-clé de datasheet qui doit l'allumer.
BIT_TO_KEYWORD = {
    "kw_infantry": "INFANTRY",
    "kw_vehicle": "VEHICLE",
    "kw_monster": "MONSTER",
    "kw_fly": "FLY",
    "kw_psyker": "PSYKER",
}


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
    }


def _unit_cfg(
    uid: int, player: int, positions: List[Tuple[int, int]], keywords: List[Dict[str, str]]
) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": keywords,
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(ally_keywords, enemy_keywords) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {
            "default": {
                "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "inches_to_subhex": 1,
            }
        },
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
        "units": [
            _unit_cfg(1, 1, [(30, 20), (32, 20)], ally_keywords),
            _unit_cfg(2, 2, [(80, 20)], enemy_keywords),
        ],
    }


def _engine(ally_keywords, enemy_keywords) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config(ally_keywords, enemy_keywords)))
    eng.reset()
    return eng


def _bits(engine: W40KEngine, family: str, row: int) -> Dict[str, float]:
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    binv = obs[family][row]
    return {bit: float(binv[unit_bin_index(bit)]) for bit in BIT_TO_KEYWORD}


@pytest.mark.parametrize("bit,keyword", sorted(BIT_TO_KEYWORD.items()))
def test_each_keyword_lights_only_its_own_bit(bit: str, keyword: str) -> None:
    """Un mot-clé allume SON bit, et lui seul — c'est la permutation qui est verrouillée."""
    engine = _engine([{"keywordId": keyword}], [{"keywordId": "INFANTRY"}])

    bits = _bits(engine, "allies_bin", 0)

    assert bits[bit] == 1.0, f"{keyword} déclaré mais le bit '{bit}' est éteint"
    allumes_a_tort = sorted(b for b, v in bits.items() if v == 1.0 and b != bit)
    assert allumes_a_tort == [], f"{keyword} allume aussi {allumes_a_tort}"


@pytest.mark.parametrize("bit,keyword", sorted(BIT_TO_KEYWORD.items()))
def test_keywords_are_emitted_for_enemy_entities(bit: str, keyword: str) -> None:
    """Le bit est porté par la CIBLE : sans lui côté ennemi, [ANTI-X] reste inapprenable."""
    engine = _engine([{"keywordId": "INFANTRY"}], [{"keywordId": keyword}])

    bits = _bits(engine, "enemies_bin", 0)

    assert bits[bit] == 1.0, f"entité ennemie {keyword} : bit '{bit}' éteint"


@pytest.mark.parametrize("written", ["vehicle", "VEHICLE", " Vehicle "])
def test_keyword_reading_is_case_and_space_insensitive(written: str) -> None:
    """Le corpus de rosters mélange les casses ; la normalisation est celle de [ANTI-X]."""
    engine = _engine([{"keywordId": written}], [{"keywordId": "INFANTRY"}])

    assert _bits(engine, "allies_bin", 0)["kw_vehicle"] == 1.0


def test_unit_without_any_category_keyword_lights_nothing() -> None:
    """Une datasheet sans mot-clé de catégorie n'allume rien — 0 n'est pas une valeur par défaut."""
    engine = _engine([{"keywordId": "ADEPTUS ASTARTES"}], [{"keywordId": "INFANTRY"}])

    assert _bits(engine, "allies_bin", 0) == {bit: 0.0 for bit in BIT_TO_KEYWORD}


def test_missing_unit_keywords_raises() -> None:
    """T1 : la clé absente lève, au lieu d'écrire « aucune catégorie » en silence."""
    engine = _engine([{"keywordId": "INFANTRY"}], [{"keywordId": "INFANTRY"}])
    unit = next(u for u in engine.game_state["units"] if str(u["id"]) == "1")
    del unit["UNIT_KEYWORDS"]

    with pytest.raises(ConfigurationError, match="UNIT_KEYWORDS"):
        engine.obs_builder.build_squad_observation(engine.game_state, "1")


@pytest.mark.parametrize("bit,keyword", sorted(BIT_TO_KEYWORD.items()))
def test_registry_datasheets_light_their_bit(bit: str, keyword: str) -> None:
    """Contrat sur le registre RÉEL : une datasheet portant le mot-clé allume bien son bit."""
    units = UnitRegistry().units
    carriers = {
        name: unit["UNIT_KEYWORDS"]
        for name, unit in units.items()
        if any(
            str(entry["keywordId"]).strip().upper() == keyword
            for entry in unit["UNIT_KEYWORDS"]
        )
    }
    # Énumération non vide : sans porteur réel, l'assertion suivante serait verte à vide.
    assert carriers, f"aucune datasheet du registre ne porte {keyword} — le contrat ne teste rien"

    name, keywords = sorted(carriers.items())[0]
    engine = _engine(keywords, [{"keywordId": "INFANTRY"}])

    assert _bits(engine, "allies_bin", 0)[bit] == 1.0, f"{name} porte {keyword}, bit '{bit}' éteint"


def test_present_stays_the_last_field() -> None:
    """Convention §0.37 : `present` est le DERNIER champ, les bits insérés ne l'ont pas bougé."""
    assert UNIT_BIN_FIELDS[-1] == "present"
