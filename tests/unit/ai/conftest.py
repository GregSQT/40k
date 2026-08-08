"""Helpers partagés des tests d'IA (extracteur d'entités, têtes pointeur, données tactiques).

`squad_obs_space()` était recopié À L'IDENTIQUE dans `test_pointer_head.py` et
`test_entity_encoder_extractor.py` : les deux fichiers construisent l'espace d'observation
squad réel pour instancier `SpatialCombinedExtractor`. Une clé ou une forme ajoutée à
`ObservationBuilder.squad_obs_shapes()` devait donc être répercutée dans deux copies, et une
copie oubliée n'aurait pas rougi — elle aurait juste testé un espace périmé.

`tactical_data()` est là pour la même raison, et pour un motif qui s'est répété quatre fois :
`log_tactical_metrics` lit son dict en STRICT, et trois fixtures écrites à la main le
recopiaient. Chaque clé stricte ajoutée au tracker (`action_family_counts`,
`deployment_cache_counts`, `controlled_objective_samples`, puis les trois `reserves_*`) cassait
les trois copies, une par une, à chaque fois. Une seule fabrique désormais.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict

import gymnasium as gym
import numpy as np

from engine.action_decoder import ActionDecoder
from engine.macro_intents import ACTION_FAMILIES
from engine.observation_builder import ObservationBuilder
from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE


@lru_cache(maxsize=1)
def squad_obs_space() -> gym.spaces.Dict:
    """Espace d'observation squad réel, `grid` comprise.

    Mémoïsé : sa construction (une trentaine de `Box` derrière `squad_obs_shapes()`) coûte
    quelques millisecondes et les env jouets le redemandent à chaque `reset`/`step`. L'objet
    rendu est traité en LECTURE SEULE par les appelants — un espace gym n'est pas muté.
    """
    spaces = {}
    for key, shape in ObservationBuilder.squad_obs_shapes().items():
        low, high = (-1.0, 1.0) if key.endswith("_bin") else (-np.inf, np.inf)
        spaces[key] = gym.spaces.Box(low=low, high=high, shape=shape, dtype=np.float32)
    spaces["grid"] = gym.spaces.Box(
        low=0.0, high=1.0, shape=(GRID_CHANNELS, GRID_SIZE, GRID_SIZE), dtype=np.float32
    )
    return gym.spaces.Dict(spaces)


def tactical_data(**overrides: Any) -> Dict[str, Any]:
    """`tactical_data` d'un episode, tel que le moteur l'emet a la terminaison.

    Porte TOUTES les cles que `log_tactical_metrics` lit — elles sont toutes STRICTES, il n'y
    a plus de lecture optionnelle. Les valeurs par defaut sont non nulles et DISTINCTES la ou
    deux courbes voisines lisent deux cles differentes : deux defauts egaux rendraient un
    echange de tags invisible. Que le moteur fournisse bien ces cles est verifie sur un episode
    REEL par `test_reserves_metrics.py::test_the_engine_feeds_every_key_the_tracker_reads` :
    cette fabrique est ECRITE A LA MAIN, elle ne prouve rien du cote moteur.
    """
    data: Dict[str, Any] = {
        "shots_fired": 10, "hits": 6,
        "damage_dealt": 12, "damage_received": 7,
        "units_lost": 2, "units_killed": 3, "total_enemy_units": 4, "total_ally_units": 5,
        "shoot_kills": 2, "melee_kills": 1,
        "shoot_value_killed": 200.0, "melee_value_killed": 100.0,
        "charge_attempts": 4, "charge_successes": 3,
        "charge_attempts_opponent": 2, "charge_successes_opponent": 1,
        "move_actions": 9, "move_flees": 1, "move_waits": 3,
        "shoot_activations": 5, "shoot_waits": 2,
        "enemy_value_destroyed": 300.0, "ally_value_lost": 200.0,
        "total_ally_value": 1000.0, "total_enemy_value": 900.0,
        "initial_ally_models": 12, "initial_enemy_models": 15,
        "models_lost": 5, "models_killed": 6,
        "valid_actions": 40, "invalid_actions": 5,
        # NON NULS, et c'est le point : `actions/share_*` est garde par `if family_total > 0`
        # et les deux `perf/*_rate` par un denominateur de consultations non nul. Une fabrique
        # toute a zero laissait ces courbes du cote SILENCIEUX de leur garde — supprimer leurs
        # `add_scalar` n'aurait fait rougir aucun test, exactement le defaut que ce dossier
        # combat. `test_the_guarded_curves_are_on_the_open_side_of_their_guard` le verrouille.
        "action_family_counts": {
            name: index + 1 for index, name in enumerate(ACTION_FAMILIES)
        },
        "deployment_cache_counts": {
            name: index + 1
            for index, name in enumerate(ActionDecoder.empty_deployment_cache_counts())
        },
        "victory_points_diff_controlled_minus_opponent": 5.0,
        "victory_points_opponent_episode": 27.0,
        "victory_points_controlled_episode": 32.0,
        "controlled_objective_samples": [2.0, 1.0, 2.0, 2.0],
        "opponent_objective_samples": [1.0, 2.0, 1.0, 1.0],
        "forced_unit_episode_has_controlled": 0,
        "forced_unit_instances_controlled": 0,
        "forced_unit_counts_controlled": {},
        "reserves_placed_agent": 5,
        "reserves_deployed_agent": 3,
        "reserves_destroyed_turn3": 1,
    }
    data.update(overrides)
    return data
