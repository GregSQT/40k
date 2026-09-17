"""Fabriques partagées des tests d'IA (espace d'observation squad, données tactiques,
`AnalyzerConfig`).

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

POURQUOI CE FICHIER PLUTÔT QUE `conftest.py`, où ces trois fabriques vivaient. Un `conftest.py`
qu'on IMPORTE en plus d'être collecté est chargé DEUX FOIS : une fois par le harnais sous le nom
`conftest`, une fois par l'importateur sous `tests.unit.ai.conftest` — `tests/` n'ayant pas
d'`__init__.py`, les deux chemins ne se rejoignent pas dans `sys.modules`. Mesuré : deux objets
module distincts, donc deux caches `lru_cache` (l'espace d'observation construit deux fois par
worker) et surtout tout état de module ajouté là divergerait en SILENCE entre la copie que
voient les fixtures et celle qu'importent les tests. Le `conftest.py` voisin ne garde donc que
ce qui doit y être : ses fixtures.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Set, Tuple

import gymnasium as gym
import numpy as np

from ai.analyzer_config import AnalyzerConfig
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
        "move_actions": 9, "move_flees": 1, "move_waits": 3, "move_advances": 4,
        "shoot_activations": 5, "shoot_waits": 2,
        "fight_activations": 3, "final_turn": 5,
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
        # NON NULS pour la meme raison que les deux blocs ci-dessus, et c'est le cas le plus
        # coûteux : `forcing/unit_episode_exposure/*` et `forcing/unit_instance_mean/*` ne sont
        # emises QUE dans la boucle sur `forced_unit_counts_controlled`. Un dict vide laissait
        # ces deux courbes hors d'atteinte de tout test du depot — on pouvait les supprimer, ou
        # les echanger, sans rien faire rougir. Deux unites aux comptes DISTINCTS entre eux : un
        # ratio d'episodes branche sur la moyenne d'instances se voit.
        "forced_unit_episode_has_controlled": 1,
        "forced_unit_instances_controlled": 5,
        "forced_unit_counts_controlled": {"Intercessor": 2, "Ork Boyz": 3},
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
        "effect_display_tokens": {},
        "rule_to_units": {},
        "weapon_rule_to_weapons": {},
        # `token -> {"ranged"|"melee" -> types porteurs}` : l'applicabilité des règles d'armes.
        "weapon_rule_to_units": {},
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
        "cc_atk_by_weapon_global": {},
        "unit_toughness_by_type": {},
        # Bonus E Waaagh par type (BannerNob) — vide par défaut, aucune fixture ne le teste ici.
        "toughness_bonus_waaagh_by_type": {},
        # Coéquipiers d'escouade par type (pour _pair_is_conditional cross-unit) — vide par défaut.
        "squadmates_by_type": {},
        # Mots-clés en majuscules par type d'unité (Primitive B : Dakkablitz, etc.) — vide par défaut.
        "unit_upper_keywords_by_type": {},
        # 07.02 — nombre de tours max ; 0 = non disponible (valeur neutre pour les tests
        # qui ne testent pas la durée de la partie).
        "max_turns": 0,
        # Comportement 10e par défaut ; 0 = pas de cap.
        "bonus_malus_cap": 0,
        # Bonus d'attaques de Finest Hour (once_per_battle_melee_buff) par type ; vide par défaut.
        "once_per_battle_melee_bonus_by_type": {},
        # Bonus d'attaques en WAAAGH! par type (Da Biggest and da Best) ; vide par défaut.
        "melee_atk_bonus_waaagh_by_type": {},
    }
    unknown = set(overrides) - set(fields)
    if unknown:
        raise TypeError(f"champs inconnus d'AnalyzerConfig : {sorted(unknown)}")
    fields.update(overrides)
    return AnalyzerConfig(**fields)


def pose_etat_du_run(
    scale: int,
    *,
    ez_subhex: int | str,
    ez_vertical_inches: float | str | None = None,
    metric_engagement: str = "hex",
    board_dims: tuple[int, int] | None = None,
    cohesion_model_subhex: int | str | None = None,
    cohesion_global_subhex: int | str | None = None,
    cohesion_min_neighbors: int | str = 1,
) -> None:
    """Fixe l'état du run dans le module `ai.analyzer` pour les tests qui n'appellent pas
    `parse_step_log` (les getters d'analyzer lèvent si l'état n'a pas été initialisé).

    Cinq sites le faisaient à la main — `set_analyzer_board_scale` + `set_run_rules` avec un dict
    de 6 ou 7 clés dont les copies avaient divergé sur `engagement_zone_vertical_inches`. Ce
    motif est concentré ici.

    Les clés `cohesion.*` sont OPTIONNELLES : ``None`` les omet (simule un log antérieur au
    tracking de cohérence, ce qui saute le check). Passer `cohesion_model_subhex` active les
    trois ; `cohesion_global_subhex` utilise 9× l'échelle par défaut si omis.
    """
    import ai.analyzer as an
    from ai.analyzer_config import set_run_rules

    an.set_analyzer_board_scale(scale)
    if board_dims is not None:
        an.set_analyzer_board_dims(*board_dims)
    rules: Dict[str, str] = {"engagement_zone_subhex": str(ez_subhex)}
    if ez_vertical_inches is not None:
        rules["engagement_zone_vertical_inches"] = str(ez_vertical_inches)
    if cohesion_model_subhex is not None:
        _global = cohesion_global_subhex if cohesion_global_subhex is not None else 9 * scale
        rules["cohesion.model_subhex"] = str(cohesion_model_subhex)
        rules["cohesion.global_subhex"] = str(_global)
        rules["cohesion.min_neighbors"] = str(cohesion_min_neighbors)
    rules.update({
        "metric.engagement": metric_engagement,
        "metric.ranged": "euclidean",
        "move.thru_ez": "True",
        "move.thru_enemy": "False",
        "move.thru_friendly": "True",
    })
    set_run_rules(rules)


def entete_step_log(
    body: str = "",
    *,
    inches_to_subhex: int = 5,
    board: str = "cols=220 rows=300",
    hex_radius: str = "2.78",
    margin: int = 1,
    walls: str = "",
    units: str = "",
    objectives: str | None = "",
    rosters: str = "",
    ez_vertical_inches: float | None = 5.0,
    metric_engagement: str = "hex",
    metric_ranged: str = "euclidean",
    log_grammar: int | None = None,
) -> str:
    """Entête complet d'un step.log à épisode unique, pour les tests qui appellent `parse_step_log`.

    Était `_log` dans test_analyzer_scale_vehicle_fly.py — version publique. La ligne
    `Run rules:` est générée dynamiquement (clés triées, conformes au StepLogger) : un jeton
    ajouté par le StepLogger ne brise que ce fichier, pas les ~25 fichiers qui la recopiaient.

    `ez_vertical_inches=None` omet la clé : utile pour les tests qui vérifient le comportement
    sans seuil vertical (l'analyzer est 2D dans ce cas).

    `objectives=None` omet la ligne Objectives : les épisodes sans ce marqueur ne requièrent pas
    de snapshot `T<n> OBJECTIVE CONTROL:`.

    `log_grammar=None` (défaut) OMET la ligne `Log grammar:` — le lecteur lève alors la version 1
    et prend ses chemins de repli. C'est le régime historique de cette fabrique, gardé tel quel :
    ~25 fichiers en dépendent. Le renseigner produit un journal qui DÉCLARE sa grammaire, seul
    moyen d'exercer les branches que le vrai StepLogger emprunte en production (il écrit toujours
    la ligne). Sans ce paramètre, ces branches-là n'étaient atteintes par aucun test.
    """
    ez = 2 * inches_to_subhex
    rules: Dict[str, str] = {
        "cohesion.global_subhex": str(9 * inches_to_subhex),
        "cohesion.min_neighbors": "1",
        "cohesion.model_subhex": str(ez),
        "engagement_zone_subhex": str(ez),
    }
    if ez_vertical_inches is not None:
        rules["engagement_zone_vertical_inches"] = str(ez_vertical_inches)
    rules.update({
        "metric.engagement": metric_engagement,
        "metric.ranged": metric_ranged,
        "move.thru_enemy": "False",
        "move.thru_ez": "True",
        "move.thru_friendly": "True",
    })
    rules_txt = " ".join(f"{k}={v}" for k, v in sorted(rules.items()))
    if objectives is None:
        objectives_line = ""
    else:
        obj = objectives or ";".join(f"(150,{r})" for r in range(150, 156))
        objectives_line = f"[10:00:00] Objectives: rect b NW:{obj}\n"
    rosters_line = f"[10:00:00] Rosters: {rosters}\n" if rosters else ""
    grammar_line = "" if log_grammar is None else f"[10:00:00] Log grammar: {log_grammar}\n"
    return (
        "=== STEP-BY-STEP ACTION LOG ===\n"
        "================================================================================\n\n"
        "[10:00:00] === EPISODE 1 START ===\n"
        "[10:00:00] Scenario: scenario_bot-01\n"
        "[10:00:00] Opponent: SelfplayBot\n"
        f"{rosters_line}"
        f"[10:00:00] Walls: {walls}\n"
        f"{objectives_line}"
        f"[10:00:00] Board: {board} inches_to_subhex={inches_to_subhex} hex_radius={hex_radius} margin={margin}\n"
        f"[10:00:00] Run rules: {rules_txt}\n"
        # Même position que chez le producteur (`StepLogger.log_episode_start` : juste après
        # `Run rules:`), pour que le lecteur voie l'entête dans l'ordre réel.
        f"{grammar_line}"
        f"{units}"
        "[10:00:00] === ACTIONS START ===\n"
        f"{body}"
    )


EPISODE_TAIL = (
    "[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
    "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s\n"
)


from tests.unit.engine._state_builders import gs_with_units


def weapon_rule_usage(stats: dict, rule: str) -> dict:
    """Extrait les compteurs d'usage d'une règle d'arme depuis les stats analyzer.

    Était `_usage` dans test_analyzer_weapon_rules_lot2*.py — version publique partagée.
    """
    return {k: sum(v.values()) for k, v in stats["weapon_rule_usage"].items() if k[0] == rule}


def units_cache_entry(
    col: int, row: int, *, player: int, models: Dict | None = None, hp_cur: int = 9
) -> Dict[str, Any]:
    """`units_cache` entry pour les tests step.log / analyzer.

    `occupied_hexes_by_model` est ce dont `_models_segment_for_unit` tire le segment
    `[MODELS: A1@(c,r,z0)]` — sans lui l'analyzer ne connaît pas le NOMBRE de figurines
    de l'escouade, donc pas le plafond de tirs, donc pas la fenêtre RAPID FIRE.

    `floor_height_by_model` est écrite AVEC elle, jamais seule : les deux cartes sont le
    contrat de la couche per-figurine (position + altitude, §03.04), et le moteur exige
    la seconde dès que la première est là. Plateau plat ici → 0.0 partout.

    `hp_cur` : HP total de l'unité, lu en `require_key` par
    `_compute_enemy_adjacent_cache_for_player_from_units_cache` pour sauter les unités
    mortes.
    """
    entry: Dict[str, Any] = {
        "BASE_SHAPE": "round", "BASE_SIZE": 6, "col": col, "row": row,
        "occupied_hexes": {(col, row)}, "VALUE": 10.0, "player": player, "HP_CUR": hp_cur,
        # HP_MAX : Wounds du profil de base, toujours posé en production (game_state.py) ; lu
        # par `_build_target_meta` depuis S11 (plafond de l'espérance de dégâts).
        "HP_MAX": hp_cur,
    }
    if models:
        entry["occupied_hexes_by_model"] = dict(models)
        entry["floor_height_by_model"] = {mid: 0.0 for mid in models}
    return entry


PROBE_TRAINING_CONFIG = "x1_long"
PROBE_REWARDS_CONFIG = "ArmageddonAgent_x1"


def exploiter_probe_callback(archive: Any, n_workers: int | None = 4, **overrides: Any) -> Any:
    """`ExploiterProbeCallback` prêt à sonder, `model` doublé.

    Ces onze arguments étaient retapés à l'identique dans `test_checkpoint_eval_parallel.py`
    (deux fois) et `test_probe_eval_pool_lifetime.py` : tout argument requis ajouté au
    constructeur cassait trois blocs, un par un.

    `**overrides` pour que les tests qui ont besoin d'une cadence ou d'un budget particuliers
    (`test_probe_resume_offset.py`) les posent SANS recopier le reste de la liste — sinon ils
    rouvrent exactement la brèche que cette fabrique ferme.

    Import différé : `ai.training_callbacks` tire stable-baselines3, que les tests d'analyzer
    important ce module n'ont aucune raison de charger.
    """
    from unittest.mock import MagicMock

    from ai.training_callbacks import ExploiterProbeCallback

    params: Dict[str, Any] = dict(
        target_archive_path=str(archive),
        training_config_name=PROBE_TRAINING_CONFIG,
        rewards_config_name=PROBE_REWARDS_CONFIG,
        metrics_tracker=None,
        probe_every_episodes=100,
        probe_cheap_n=10,
        probe_confirm_n=20,
        win_rate_target=0.6,
        budget_cap=1000,
        intermediate_n_workers=n_workers,
        log_fn=lambda *_a, **_k: None,
    )
    params.update(overrides)
    probe = ExploiterProbeCallback(**params)
    probe.model = MagicMock()
    return probe


#: Bloc `early_stop` VALIDE, seuils volontairement distincts les uns des autres : un test qui
#: échangerait deux seuils dans le code de décision doit rougir. Les épisodes sont petits pour
#: que les tests puissent franchir les deux paliers sans simuler des dizaines de milliers
#: d'épisodes. La fenêtre vaut 3, comme le curriculum livré.
POOL_EARLY_STOP_CFG: Dict[str, Any] = {
    "probe_window": 3,
    "promote_score_vs_champion": 0.60,
    "promote_score_vs_others": 0.55,
    "promote_min_episodes": 500,
    "destroy_score_vs_champion": 0.40,
    "destroy_min_episodes": 200,
    "full_pool_probe_every": 1,
    # Cadence, instantanés et plateau (2026-09-17). Pas d'instantané par défaut : le modèle des
    # fabriques est un MagicMock, dont `get_env()` ferait boucler `save_vec_normalize` ; les
    # tests d'instantané posent leurs seuils et doublent l'écriture.
    "probe_every_episodes": 100,
    "snapshot_thresholds": [],
    "plateau": {
        "patience_probes": 2, "min_delta": 0.02, "min_episodes": 500, "check_budget_cap": 2000,
    },
}


def pool_early_stopping_callback(archive: Any, n_workers: int | None = 4, **overrides: Any) -> Any:
    """Jumeau de `exploiter_probe_callback` pour `PoolEarlyStoppingCallback`.

    Les deux callbacks partagent `_EvalPoolOwnerMixin`, donc tout test de cycle de vie du pool
    les exerce en paire — les fabriques vont par paire pour la même raison.

    `parity_label` vaut None par défaut : la fabrique rend un callback de run NEUF
    (`episode_origin=0`), qui n'a aucune parité d'ouverture à tenir. Un test de reprise à chaud
    passe `episode_origin` ET `parity_label` — le constructeur refuse l'un sans l'autre, ce qui
    est exactement le verrou voulu.
    """
    from unittest.mock import MagicMock

    from ai.training_callbacks import PoolEarlyStoppingCallback

    params: Dict[str, Any] = dict(
        pool_archives=[(str(archive), "champion")],
        stage_name="P-test",
        champion_label="champion",
        early_stop_cfg=dict(POOL_EARLY_STOP_CFG),
        eval_freq_episodes=100,
        n_eval_episodes=10,
        training_config_name=PROBE_TRAINING_CONFIG,
        rewards_config_name=PROBE_REWARDS_CONFIG,
        metrics_tracker=None,
        parity_label=None,
        parity_range=(0.40, 0.60),
        intermediate_n_workers=n_workers,
        snapshot_model_path=str(archive).rsplit("_", 1)[0] + ".zip"
        if str(archive).endswith(".zip") else str(archive) + ".zip",
    )
    params.update(overrides)
    callback = PoolEarlyStoppingCallback(**params)
    callback.model = MagicMock()
    return callback


def table_de_recompense(agent_key: str = "TestAgent", **overrides: Any) -> Dict[str, Any]:
    """Une table de récompense minimale, telle que `prepare_run_artifacts` l'exige.

    Le prologue d'un run établit le CONTRAT du modèle (`ai/training_contract.py`), qui lit la
    sous-table de l'agent — et lève si elle manque, comme `RewardCalculator` en production. Les
    tests du prologue ne s'intéressent pas au contenu de cette table : ils ont juste besoin d'une
    table VALIDE, et six d'entre eux la construiraient à l'identique.

    VALIDE veut dire PORTANT `base_actions` : c'est ce qu'`agent_reward_table` exige à l'écriture
    du contrat, parce que la production l'exige à chaque action d'unité (`RewardCalculator`,
    engine/reward_calculator.py:820). La sous-table rendue était `{}` : l'empreinte du contrat en
    sortait vide, donc le contrat écrit au premier appel était refusé à la relecture par le second
    (`section `reward_keys` vide`). Les VALEURS, elles, n'entrent jamais dans le contrat.

    Les `overrides` peuplent la sous-table de l'agent, pas la racine : c'est le seul niveau que le
    contrat regarde, donc le seul qu'un test ait une raison de faire varier.
    """
    sous_table: Dict[str, Any] = {"base_actions": {"charge_fail": -1.0}}
    sous_table.update(overrides)
    return {agent_key: sous_table}


#: Dump d'update PPO COMPLET, tel que `MetricsCollectionCallback` passe
#: `model.logger.name_to_value` à `W40KMetricsTracker.log_training_metrics` — `train/ent_coef`
#: compris, que le callback injecte lui-même dans sa copie du dict.
#:
#: COMPLET est le point : chaque test qui l'écrivait à la main n'y mettait que les clés qu'il
#: regardait, et trois copies de même nom (`_UPDATE_STATS`) divergeaient déjà — l'une portait
#: `time/fps`, une autre non, une troisième ni `train/approx_kl_max` ni `train/grad_clip_fraction`.
#: Or ce que ces tests verrouillent est précisément le JEU de clés que le tracker consomme : une
#: clé retirée d'une seule copie ne rougit nulle part. Une seule source désormais.
_PPO_UPDATE_STATS: Dict[str, float] = {
    "train/learning_rate": 3e-4,
    "train/policy_gradient_loss": -0.2,
    "train/value_loss": 0.3,
    "train/entropy_loss": 0.05,
    "train/ent_coef": 0.01,
    "train/clip_fraction": 0.2,
    "train/approx_kl": 0.01,
    "train/approx_kl_max": 0.034,
    "train/n_minibatches_done": 9,
    "train/explained_variance": 0.42,
    "train/n_updates": 10,
    "train/gradient_norm": 0.8,
    "train/grad_clip_fraction": 0.15,
    "diag/grad_share_policy_mb0": 0.235,
    "time/fps": 100.0,
}


def ppo_update_stats(**overrides: float) -> Dict[str, float]:
    """Copie NEUVE du dump d'update PPO complet (cf. `_PPO_UPDATE_STATS`).

    Neuve à chaque appel : `log_training_metrics` reçoit ce dict d'un appelant qui le possède, et
    un test qui muterait la constante partagée contaminerait ses voisins.
    """
    stats = dict(_PPO_UPDATE_STATS)
    stats.update(overrides)
    return stats


class RecordingWriter:
    """Doublure TYPÉE du writer TensorBoard : retient `(tag, valeur, abscisse)` de chaque écriture.

    TYPÉE parce que c'est ce qui rend la doublure portante : des paramètres implicitement `Any`
    satisferaient n'importe quel protocole, et `tracker_avec_writer_espion` vérifie l'affectation
    contre `MetricsWriter` (ai/metrics_tracker.py). Les QUATRE méthodes du contrat sont déclarées,
    y compris celles qu'un appelant donné n'exerce pas : en omettre une rendrait la doublure non
    conforme au protocole, donc muette sur sa dérive.

    Retient les doublons : un tag émis deux fois pour un même instant est un défaut que ces tests
    cherchent, pas un détail à dédoublonner ici.
    """

    def __init__(self) -> None:
        self.scalars: List[Tuple[str, float, int]] = []
        self.custom_layouts: List[Dict[str, Any]] = []
        self.flushed = 0
        self.closed = 0

    def add_scalar(self, tag: str, scalar_value: float, global_step: int, /) -> None:
        self.scalars.append((tag, float(scalar_value), int(global_step)))

    def add_custom_scalars(self, layout: Dict[str, Any], /) -> None:
        self.custom_layouts.append(layout)

    def flush(self) -> None:
        self.flushed += 1

    def close(self) -> None:
        self.closed += 1

    def tags(self) -> Set[str]:
        """Les tags écrits, sans leurs valeurs ni leur abscisse."""
        return {tag for tag, _valeur, _abscisse in self.scalars}


def tracker_avec_writer_espion(
    tmp_path: Any, *, window: int = 1, episode_count: int = 1
) -> Tuple[Any, RecordingWriter]:
    """Un VRAI `W40KMetricsTracker` (pas `__new__`) dont seul le writer est espionné.

    VRAI constructeur : c'est lui qui prouve quelque chose sur l'état du tracker. Une doublure
    d'état recopierait à la main les compteurs que ces tests interrogent, et un attribut retiré
    du `__init__` — `initial_step_count` vient de l'être — ne s'y verrait pas.

    Le writer réel construit par `__init__` est FERMÉ avant d'être remplacé : il tient un fichier
    d'événements ouvert sous `tmp_path`, que rien ne refermerait ensuite.

    `window` ramène les deux fenêtres de lissage à 1 : ces tests portent sur l'appariement
    tag/valeur/abscisse, pas sur la taille des fenêtres de production (500/100), qui obligerait
    chaque cas à rejouer des centaines d'épisodes. Égales, elles suppriment aussi le doublon
    `_100ep`, donc les comptages d'occurrences restent lisibles.

    `episode_count` est posé explicitement et vaut 1 par défaut : une abscisse à 0 rendrait muette
    toute assertion d'axe, un writer qui n'écrirait rien la satisfaisant aussi bien qu'un writer
    correct.

    Import différé : `ai.metrics_tracker` tire torch, que les tests d'analyzer important ce
    module n'ont aucune raison de charger.
    """
    from ai.metrics_tracker import W40KMetricsTracker

    tracker = W40KMetricsTracker(
        "ArmageddonAgent_x1",
        log_dir=str(tmp_path),
        show_banner=False,
        perf_window=window,
        perf_window_fast=window,
    )
    tracker.writer.close()
    espion = RecordingWriter()
    tracker.writer = espion
    tracker.episode_count = episode_count
    return tracker, espion
