"""Verrou 04.02 : la cible doit être engagée avec LA FIGURINE, pas avec l'escouade.

« Each target must be **engaged with the model that has that weapon** » (04.02 SELECT TARGETS /
WHILE FIGHTING). Le pool de combat du chemin gym (`get_fighting_models` → `squad_declare_fight`)
testait l'engagement contre **n'importe quelle** escouade ennemie. Une escouade coincée entre A et
B qui déclarait B faisait donc frapper B par ses figurines qui ne touchent que A : des attaques
gratuites, portées à une distance que la règle refuse.

Le jumeau PvP (`fight_handlers._model_can_fight_target`) est cible-conscient depuis toujours —
c'est exactement le motif « miroir corrigé d'un seul côté ». Ce fichier verrouille les deux
sémantiques de `get_fighting_models` :
  - avec `target_squad_id` → engagement contre CETTE cible (déclaration de combat) ;
  - sans → engagement contre n'importe quel ennemi (`fight_eligible` de l'observation, qui se
    calcule avant tout choix de cible).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import (
    get_fighting_models,
    squad_declare_fight,
    squad_fight_unit_activation_start,
)
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
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


def _config() -> Dict[str, Any]:
    """Mes 2 figurines prises en tenaille : chacune ne touche QU'UN des deux ennemis.

    Positions (colonnes, même ligne) : ennemi 2 en 29 · moi en 30 et 32 · ennemi 3 en 33.
    Écarts d'ancre : 1 pour les paires engagées, 3 pour les paires croisées — au-delà du seuil
    bord-à-bord quelle que soit la métrique résolue (à 2 subhex l'euclidienne engage encore).
    """
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
            _unit_cfg(1, 1, [(30, 20), (32, 20)]),
            _unit_cfg(2, 2, [(29, 20)]),
            _unit_cfg(3, 2, [(33, 20)]),
        ],
    }


@pytest.fixture
def engine() -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config()))
    eng.reset()
    return eng


def test_the_fixture_really_puts_each_model_on_a_different_enemy(engine: W40KEngine):
    """VERT VACANT : sans cette prémisse, les assertions suivantes passeraient à vide.

    Si les deux figurines étaient engagées avec les deux ennemis (ou avec aucun), filtrer par
    cible ne changerait rien et le test ne mordrait sur rien.
    """
    assert set(get_fighting_models(engine.game_state, "1")) == {"1#0", "1#1"}, (
        "fixture : les deux figurines doivent être au combat"
    )


def test_only_the_model_engaged_with_the_declared_target_is_in_the_pool(engine: W40KEngine):
    """`target_squad_id` restreint le pool à la cible désignée (04.02)."""
    gs = engine.game_state
    assert set(get_fighting_models(gs, "1", "2")) == {"1#0"}
    assert set(get_fighting_models(gs, "1", "3")) == {"1#1"}


def test_declaring_a_target_never_produces_an_intent_from_a_model_out_of_reach(
    engine: W40KEngine,
):
    """Le pool filtré atteint bien la DÉCLARATION, pas seulement la primitive.

    C'est le point qui a manqué : le prédicat cible-conscient existait déjà côté PvP, mais le
    chemin gym ne l'appelait pas. Un intent porté par `1#0` contre l'escouade 3 est une attaque
    à 3 subhex de sa cible.
    """
    gs = engine.game_state
    squad_fight_unit_activation_start(gs, "1")
    intents = squad_declare_fight(gs, "1", "3")

    assert intents, "la figurine engagée avec 3 doit bien déclarer"
    assert {i["model_id"] for i in intents} == {"1#1"}
    assert all(i["target_unit_id"] == "3" for i in intents)
    # On n'observe PAS `ATTACK_LEFT` de `1#0` : l'activation le pose pour toute l'escouade avant
    # toute déclaration, et il n'est consommé que par les intents (`attacks_left_attr`, moteur
    # d'allocation). Une figurine sans intent n'est jamais visitée — le laisser à 1 ne produit
    # aucune attaque, et l'assertion aurait verrouillé un détail d'activation, pas la règle.


def test_a_friendly_or_unknown_target_raises(engine: W40KEngine):
    """T1 : une cible non ennemie est une erreur d'appelant, pas un pool vide silencieux.

    Rendre `[]` ferait passer « personne ne peut frapper » pour un verdict de règle, alors que
    c'est un bug de câblage du caller.
    """
    with pytest.raises(ValueError, match="pas une escouade ennemie"):
        get_fighting_models(engine.game_state, "1", "1")
    with pytest.raises(ValueError, match="pas une escouade ennemie"):
        get_fighting_models(engine.game_state, "1", "999")
