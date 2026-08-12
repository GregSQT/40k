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
import pytest

# Sous ce nom-là, et pas `analyzer_config` : ce module définit plus bas une FABRIQUE de
# `AnalyzerConfig` qui porte ce nom, et elle écraserait l'alias — les remises à zéro
# ci-dessous se seraient posées sur la fonction, sans rien réinitialiser ni rien signaler.
import ai.analyzer_config as ai_analyzer_config
from ai.analyzer_config import AnalyzerConfig
from engine.action_decoder import ActionDecoder
from engine.macro_intents import ACTION_FAMILIES
from engine.observation_builder import ObservationBuilder
from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE


@pytest.fixture(autouse=True)
def _etat_du_run_analyse_remis_a_zero():
    """L'état du run ANALYSÉ (échelle, règles, plateau) est « non posé » à l'entrée de chaque
    test, et l'est de nouveau à sa sortie.

    Ces trois valeurs vivent dans des globales de module (`ai/analyzer_config.py`) : en
    production `parse_step_log` les repose à chaque passe depuis l'entête du journal, mais un
    test qui les pose à la main les LAISSAIT au module pour tous ses voisins du même worker. Le
    voisin qui avait oublié de les poser passait alors en vert — et rougissait le jour où `-n`
    changeait sa place dans la file (mesuré le 2026-08-12 sur le BFS de chemin).

    Remise à `None`, et non à des valeurs « raisonnables » : les getters LÈVENT sans entête, et
    c'est exactement le garde-fou qu'il faut préserver — un plateau ou une échelle par défaut
    rendrait des verdicts faux en silence, ce que ces globales existent pour empêcher.

    Des DEUX côtés du test : à l'entrée pour ne rien hériter d'un voisin (y compris d'un autre
    dossier partageant le worker), à la sortie pour ne rien lui laisser.
    """
    def _remettre_a_zero() -> None:
        ai_analyzer_config._run_inches_to_subhex = None
        ai_analyzer_config._run_rules = None
        ai_analyzer_config._run_board_dims = None

    _remettre_a_zero()
    yield
    _remettre_a_zero()


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

    Porte TOUTES les cles que `log_tactical_metrics` lit (toutes strictes — voir sa docstring).
    Les valeurs par defaut sont non nulles et DISTINCTES la ou deux courbes voisines lisent deux
    cles differentes : deux defauts egaux rendraient un echange de tags invisible.

    ECRITE A LA MAIN, et elle doit le rester. Deriver du `_empty_episode_tactical_data()` du
    moteur ne marcherait pas, et pas seulement parce qu'il ne couvre que 19 des cles : ses cles
    sont les ACCUMULATEURS, qui doivent preexister pour etre incrementes. Les autres sont des
    calculs de TERMINAISON, ecrits une fois. Les pre-declarer a 0 changerait « le bloc de
    terminaison a oublie d'ecrire cette cle » en « la courbe publie 0 » — le silence de 50 000
    episodes, reintroduit par la porte de service. Que le moteur fournisse bien ces cles se
    verifie sur un episode REEL :
    `test_reserves_metrics.py::test_the_engine_feeds_every_key_the_tracker_reads`.
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
        # Dix valeurs DISTINCTES, et c'est ce qui fait le test d'appariement : cinq mesures x
        # deux camps: un tag branche sur la cle du voisin -- ou sur le mauvais camp -- se voit.
        "reserves_placed_agent": 5,
        "reserves_placed_opponent": 6,
        "reserves_deployed_agent": 3,
        "reserves_deployed_opponent": 4,
        "reserves_destroyed_turn3_agent": 1,
        "reserves_destroyed_turn3_opponent": 2,
        "reserves_ingress_offers_agent": 11,
        "reserves_ingress_offers_opponent": 12,
        "reserves_ingress_declined_agent": 7,
        "reserves_ingress_declined_opponent": 8,
        "reserves_ingress_no_destination_agent": 9,
        "reserves_ingress_no_destination_opponent": 10,
        # Distances de charge (11.04) : UN bloc, pas dix-huit cles a plat. Valeurs DISTINCTES
        # d'une mesure a l'autre et d'un camp a l'autre, pour la meme raison que les reserves
        # ci-dessus — une courbe branchee sur la mesure voisine, ou sur le mauvais camp, se voit.
        "charge_distance": {
            "agent": {
                "nearest_sum": 12.0, "nearest_n": 4.0,
                "target_sum": 21.0, "target_n": 3.0,
                "success_sum": 10.0, "success_n": 2.0,
                "fail_sum": 11.0, "fail_n": 1.0,
                "long": 2.0,
            },
            "opponent": {
                "nearest_sum": 30.0, "nearest_n": 5.0,
                "target_sum": 32.0, "target_n": 4.0,
                "success_sum": 24.0, "success_n": 3.0,
                "fail_sum": 8.0, "fail_n": 1.0,
                "long": 1.0,
            },
        },
    }
    data.update(overrides)
    return data


def analyzer_config(**overrides: Any) -> AnalyzerConfig:
    """`AnalyzerConfig` RÉEL, tables vides, pour les tests des lecteurs de journal.

    Les tests construisaient chacun leur classe `_Config` portant les deux ou trois attributs
    consultés par la fonction testée. Un canard n'est pas un contrat : le jour où un lecteur
    consulte une quatrième table, ces stubs lèvent un `AttributeError` au lieu de rougir sur ce
    qui a changé, et le vérificateur de types ne voit rien venir (il refusait déjà chacun de ces
    appels). On instancie donc la vraie dataclasse, et les tables restent VIDES : une table vide
    dit « ce test ne renseigne rien ici », ce qui est exactement ce que ces fixtures veulent dire.

    `resolve_rule_id` lève : aucun de ces tests ne passe par la résolution de règles, et un
    appel inattendu doit se voir plutôt que rendre une valeur inventée.
    """
    def _no_rule_resolution(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "resolve_rule_id appelé sans avoir été fourni à analyzer_config(...)"
        )

    fields: Dict[str, Any] = {
        "unit_registry": None,
        "config_loader": None,
        "unit_weapons_cache": {},
        "unit_attack_limits": {},
        "unit_combi_by_weapon": {},
        "unit_rules_by_type": {},
        "unit_move_after_shooting_distance_by_type": {},
        "unit_is_fly_by_type": {},
        "unit_is_monster_or_vehicle_by_type": {},
        "unit_socle_by_type": {},
        "unit_choice_effect_to_source_rules": {},
        "display_rule_name_to_ids": {},
        "rule_to_units": {},
        "weapon_rule_to_weapons": {},
        "resolve_rule_id": _no_rule_resolution,
        # Échelle de référence du dépôt (`inches_to_subhex` de `config/board_config.json`) :
        # aucune des fixtures qui passent par ici ne mesure de distance, mais l'échelle n'a pas
        # de valeur neutre — la nommer vaut mieux que la laisser à zéro.
        "inches_to_subhex": 5,
        "rng_nb_by_weapon_global": {},
        "cc_nb_by_weapon_global": {},
        "rapid_fire_by_weapon_global": {},
        # [BLAST] 24.05 / [CLEAVE] 24.06 : mêmes cartes que `rapid_fire`, et présentes ici pour
        # la même raison — un champ requis d'`AnalyzerConfig` absent de cette fixture fait lever
        # TOUTES les fixtures analyzer, pas seulement celles qui touchent aux dés additionnels.
        "blast_by_weapon_global": {},
        "cleave_by_weapon_global": {},
        "sustained_hits_by_weapon_global": {},
        "weapon_range_global": {},
        "weapon_is_close_quarters_global": {},
        "rng_str_by_weapon_global": {},
        "cc_str_by_weapon_global": {},
        "unit_toughness_by_type": {},
    }
    unknown = set(overrides) - set(fields)
    if unknown:
        raise TypeError(f"champs inconnus d'AnalyzerConfig : {sorted(unknown)}")
    fields.update(overrides)
    return AnalyzerConfig(**fields)
