from collections import deque
from typing import Any, Dict, List, Tuple

import pytest

import ai.metrics_tracker as mt
from ai.metrics_tracker import (
    TrainingMonitor,
    W40KMetricsTracker,
    create_metrics_tracker,
    resolve_perf_windows,
    validate_perf_windows,
)
from config_loader import get_config_loader

ARMAGEDDON_PROFILES = ("x1", "x5_append", "x5_new", "x1_debug", "x5_debug")


def test_every_training_profile_carries_its_smoothing_windows() -> None:
    """Les CINQ profils resolvent leurs fenetres de lissage, via _training_common.json.

    Le test lit le VRAI fichier de config, pas une doublure : une section oubliee dans un
    profil ne se verrait qu'au lancement du run concerne, c'est-a-dire apres coup. Meme
    forme de verrou que tests/unit/engine/test_deployment_mode_schedule.py, et pour la meme
    raison — c'est deja par ce trou que deux profils avaient diverge en silence.

    Le doublon reactif est DESACTIVE depuis 2026-07-31 (`perf_window_fast == perf_window`) :
    les 21 courbes `_250ep` doublaient les dashboards 00_critical/01_VP/02_combat sans etre
    lues. Le test verifie donc la coherence des deux fenetres, plus leur ecart.
    """
    loader = get_config_loader()
    for profile in ARMAGEDDON_PROFILES:
        training_config = loader.load_agent_training_config("ArmageddonAgent", profile)
        window, fast = resolve_perf_windows(training_config)
        assert fast <= window, f"{profile}: la fenetre reactive ne peut pas depasser le fond"
        assert window >= 100, f"{profile}: fenetre de fond trop courte pour trancher une tendance"


def test_smoothing_windows_are_required_not_defaulted() -> None:
    """Une section absente ou incomplete LEVE — jamais de repli silencieux sur 500/250.

    Un defaut muet ici rendrait le reglage inoperant sans le dire : le run afficherait des
    courbes lissees autrement que ce que le config demande, et rien ne le signalerait.
    """
    with pytest.raises(Exception):
        resolve_perf_windows({})
    with pytest.raises(Exception):
        resolve_perf_windows({"metrics_smoothing": {"perf_window": 500}})
    with pytest.raises(TypeError):
        resolve_perf_windows({"metrics_smoothing": 500})
    with pytest.raises(ValueError):
        validate_perf_windows(100, 250)  # reactive plus lisse que le fond
    with pytest.raises(ValueError):
        validate_perf_windows(0, 0)
    # Egales : reglage legitime, le doublon reactif est simplement desactive.
    assert validate_perf_windows(500, 500) == (500, 500)


class _DummyWriter:
    """Doublure du writer TensorBoard, TYPEE : c'est ce qui rend le controle portant.

    Une doublure aux parametres implicitement `Any` satisferait n'importe quel protocole —
    le vert serait vacant. Ici l'affectation `t.writer = _DummyWriter()` est verifiee contre
    `MetricsWriter` (ai/metrics_tracker.py), donc toute derive du contrat echoue.
    `add_custom_scalars` est declare bien qu'aucun test de ce fichier ne l'appelle : il fait
    partie des quatre methodes du contrat, l'omettre rendrait la doublure non conforme.
    """

    def __init__(self) -> None:
        self.scalars: List[Tuple[str, float, int]] = []
        self.custom_layouts: List[Dict[str, Any]] = []
        self.flushed = 0
        self.closed = 0

    def add_scalar(self, key: str, value: float, step: int, /) -> None:
        self.scalars.append((key, value, step))

    def add_custom_scalars(self, layout: Dict[str, Any], /) -> None:
        self.custom_layouts.append(layout)

    def flush(self) -> None:
        self.flushed += 1

    def close(self) -> None:
        self.closed += 1


def _dw(t: W40KMetricsTracker) -> _DummyWriter:
    """Relit la doublure posee par `_tracker_stub`.

    `assert isinstance` et non `cast` : le cast affirmait sans verifier, dans le sens retour
    d'un aller-retour qui trahissait l'absence de type. Ici le retrecissement est REEL, donc
    un stub qui poserait un autre writer echouerait au lieu de passer silencieusement.
    """
    writer = t.writer
    assert isinstance(writer, _DummyWriter)
    return writer


def _tracker_stub() -> W40KMetricsTracker:
    t = W40KMetricsTracker.__new__(W40KMetricsTracker)
    t.writer = _DummyWriter()
    # Fenetres de lissage ramenees a 1 : ces tests verifient qu'un chemin d'execution emet la
    # bonne courbe, pas la taille des fenetres de production (500/100), qui les obligerait a
    # rejouer des centaines d'episodes. Egales, elles suppriment aussi le doublon `_100ep`.
    t.PERF_WINDOW = 1
    t.PERF_WINDOW_FAST = 1
    t.episode_count = 12
    t.step_count = 0
    t.win_rate_window = deque([1.0] * 12, maxlen=100)
    t.episode_reward_winner_pairs = deque(maxlen=200)
    t.all_episode_rewards = [1.0] * 12
    t.all_episode_wins = [1.0] * 12
    t.all_episode_lengths = [10] * 12
    t.hyperparameter_tracking = {
        "learning_rates": [3e-4] * 12,
        "entropy_losses": [0.1] * 12,
        "policy_losses": [],
        "value_losses": [],
        "clip_fractions": [0.2] * 12,
        "approx_kls": [0.01] * 12,
        "explained_variances": [],
    }
    t.compliance_data = {
        "units_per_step": [],
        "phase_end_reasons": [],
        "tracking_violations": [],
    }
    t.reward_mapper_stats = {
        "shooting_priority_correct": 0,
        "shooting_priority_total": 0,
        "movement_tactical_bonuses": 0,
        "movement_actions": 0,
        "mapper_failures": 0,
    }
    t.phase_stats = {
        "movement": {"moved": 0, "waited": 0, "fled": 0},
        "shooting": {"shot": 0, "skipped": 0},
        "charge": {"charged": 0, "skipped": 0},
        "fight": {"fought": 0, "skipped": 0},
    }
    t.combat_effectiveness = {
        "victory_points_cumulative": 0.0,
    }
    t.combat_history = {
        "victory_points_cumulative": [],
    }
    t.forcing_tracking = {
        "episodes_total": 0,
        "episodes_with_forced_unit": 0,
        "forced_unit_instances_total": 0,
        "per_unit_episode_counts": {},
        "per_unit_instance_counts": {},
        "baseline_combined": None,
        "baseline_worst_bot": None,
    }
    t.latest_gradient_norm = None
    t.bot_eval_combined = None
    # t.episode_tactical_data occupait cette place : supprime du tracker avec son unique
    # lecteur (le 2e ecrivain de invalid_action_rate). Le reposer ici ferait passer un stub
    # pour un etat valide qui ne l'est plus.
    # Lu de la config d'agent par __init__ : f_obj_rewards vaut ce facteur fois les VP marques.
    t.objective_reward_factor = 3.0
    t._game_history = {k: [] for k in W40KMetricsTracker.GAME_HISTORY_KEYS}
    # Ventilation par mode de deploiement : etat construit depuis les constantes de CLASSE, pas
    # recopie, pour que l'ajout d'une serie ne fasse pas tomber ces tests sur un detail sans
    # rapport avec ce qu'ils verifient (meme raison que GAME_HISTORY_KEYS ci-dessus).
    t._deploy_history = {
        series: {mode: [] for mode in W40KMetricsTracker.DEPLOY_MODES}
        for series in W40KMetricsTracker.DEPLOY_SPLIT_SERIES
    }
    t._deploy_active_flags = []
    t._episode_deploy_mode = None
    t.seat_aware = {
        "episodes_agent_p1": 0,
        "episodes_agent_p2": 0,
        "wins_agent_p1": 0.0,
        "wins_agent_p2": 0.0,
    }
    return t


def test_metric_slug_and_smoothed_metric() -> None:
    assert W40KMetricsTracker._metric_slug("My Unit#1") == "my_unit_1"
    with pytest.raises(ValueError, match=r"empty unit name"):
        W40KMetricsTracker._metric_slug("___")

    t = _tracker_stub()
    assert t._calculate_smoothed_metric([]) == 0.0
    assert t._calculate_smoothed_metric([1, 3], window_size=20) == 2.0
    assert t._calculate_smoothed_metric([1, 2, 3, 4], window_size=2) == 3.5


def test_performance_summary_contains_expected_keys() -> None:
    t = _tracker_stub()
    summary = t.get_performance_summary()
    assert summary["win_rate_100ep"] == 1.0
    assert summary["avg_reward_overall"] == 1.0
    assert summary["total_episodes"] == 12
    assert summary["win_rate_overall"] == 1.0
    assert summary["current_learning_rate"] == 3e-4
    assert abs(summary["avg_entropy_loss"] - 0.1) < 1e-9
    assert abs(summary["avg_clip_fraction"] - 0.2) < 1e-9
    assert abs(summary["avg_approx_kl"] - 0.01) < 1e-9


def test_training_monitor_health_alerts() -> None:
    monitor = TrainingMonitor({"min_win_rate": 0.6})
    alerts = monitor.check_training_health(
        {"win_rate_100ep": 0.4, "win_rate_overall": 0.3, "total_episodes": 50}
    )
    assert any("Win rate" in a for a in alerts)
    assert any("Overall win rate low" in a for a in alerts)
    assert any("Early training stage" in a for a in alerts)


def test_log_holdout_and_scenario_split_scores() -> None:
    t = _tracker_stub()
    t.log_holdout_split_metrics(
        {"holdout_regular_mean": 0.5, "holdout_hard_mean": 0.4, "holdout_overall_mean": 0.45}
    )
    keys = [k for k, _, _ in _dw(t).scalars]
    assert "bot_eval/holdout_regular_mean" in keys
    assert "bot_eval/holdout_hard_mean" in keys
    assert "bot_eval/holdout_overall_mean" in keys

    t.log_scenario_split_scores({"training_bot_1": 0.9, "hard_bot_1": 0.2})
    keys2 = [k for k, _, _ in _dw(t).scalars]
    assert "bot_split/training_bot_1" in keys2
    assert "bot_split/hard_bot_1" in keys2


def _reward_data(**overrides: Any) -> Dict[str, Any]:
    """Ventilation complete d'un episode, telle que le callback l'emet."""
    data: Dict[str, Any] = {
        "base_actions": 1.0, "result_bonuses": 0.5, "objective": 0.2,
        "situational": 0.1, "penalties": -0.1,
        "base_actions_positive": 1.0, "result_bonuses_positive": 0.5,
        "objective_positive": 0.2,
    }
    data.update(overrides)
    return data


def test_log_reward_decomposition_validation() -> None:
    t = _tracker_stub()
    with pytest.raises(KeyError, match=r"Missing required field"):
        t.log_reward_decomposition({"base_actions": 1})

    # Les flux positifs sont EXIGES au meme titre que les totaux : sans eux la part
    # d'objectif ne serait calculable que sur des totaux nettes, ce qui la fausse.
    with pytest.raises(KeyError, match=r"base_actions_positive"):
        t.log_reward_decomposition(
            {
                "base_actions": 1, "result_bonuses": 1, "objective": 1,
                "situational": 1, "penalties": 1,
            }
        )

    with pytest.raises(TypeError, match=r"must be numeric"):
        t.log_reward_decomposition(_reward_data(base_actions="x"))


def test_objective_share_uses_positive_flows_not_netted_totals() -> None:
    """La part d'objectif se calcule sur les flux POSITIFS, jamais sur les totaux nettes.

    Montage : un agent qui tire beaucoup ET attend beaucoup. `base_actions` vaut +18 de
    combat et -20 d'attente, soit un net de -2. Filtrer les totaux sur leur signe — ce que
    faisait la version precedente — jetait les 18 points entiers du denominateur et donnait
    10/(10+4) = 0,71 au lieu de 10/(10+18+4) = 0,3125.
    """
    t = _tracker_stub()
    t.log_reward_decomposition(_reward_data(
        base_actions=-2.0, base_actions_positive=18.0,
        result_bonuses=4.0, result_bonuses_positive=4.0,
        objective=10.0, objective_positive=10.0,
    ))

    shares = [v for key, v, _ in _dw(t).scalars if key == "reward/objective_share"]
    assert shares == [pytest.approx(10.0 / 32.0)]


def test_objective_share_stays_silent_without_any_positive_reward() -> None:
    """Aucune recompense positive : il n'y a pas de part a mesurer, surtout pas un 0.0."""
    t = _tracker_stub()
    t.log_reward_decomposition(_reward_data(
        base_actions=-3.0, base_actions_positive=0.0,
        result_bonuses=0.0, result_bonuses_positive=0.0,
        objective=0.0, objective_positive=0.0,
    ))

    keys = [key for key, _v, _ in _dw(t).scalars]
    assert "reward/objective_share" not in keys


# test_log_position_score_and_close occupait cette place. Il verrouillait log_position_score et
# la courbe game_tactical/avg_position_score, supprimees faute de producteur depuis le commit
# 329d140e "move reward deleted". Seule la partie utile est conservee ci-dessous : close().
def test_close_closes_the_writer() -> None:
    t = _tracker_stub()
    t.close()
    assert _dw(t).closed == 1


def test_create_metrics_tracker_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    created = {}

    class DummyTracker:
        def __init__(self, agent_key, log_dir, *, perf_window, perf_window_fast):
            created["agent_key"] = agent_key
            created["log_dir"] = log_dir
            created["windows"] = (perf_window, perf_window_fast)

    monkeypatch.setattr(mt, "W40KMetricsTracker", DummyTracker)
    tracker = create_metrics_tracker("CoreAgent", {
        "tensorboard_log": "/tmp/tb",
        "metrics_smoothing": {"perf_window": 400, "perf_window_fast": 200},
    })
    assert created["agent_key"] == "CoreAgent"
    assert created["log_dir"] == "/tmp/tb"
    assert created["windows"] == (400, 200), "les fenetres du config doivent etre transmises"
    assert isinstance(tracker, DummyTracker)


def test_log_episode_end_and_tactical_metrics_runtime_paths() -> None:
    t = _tracker_stub()
    t.compute_and_log_phase_metrics = lambda: None
    t.log_critical_dashboard = lambda: None
    t.log_episode_end(
        {
            "total_reward": 3.0,
            "winner": 1,
            "episode_length": 20,
            "controlled_player": 1,
            "deployment_mode": None,
        }
    )
    assert t.episode_count == 13
    assert _dw(t).flushed == 1
    assert t.seat_aware["episodes_agent_p1"] == 1

    t.log_tactical_metrics(
        {
            "shots_fired": 4,
            "hits": 2,
            "total_enemy_units": 2,
            "units_killed": 1,
            "damage_dealt": 3,
            "damage_received": 1,
            "units_lost": 1,
            "total_ally_units": 2,
            "enemy_value_destroyed": 8.0,
            "ally_value_lost": 4.0,
            "total_ally_value": 20.0,
            "total_enemy_value": 16.0,
            "initial_ally_models": 4,
            "initial_enemy_models": 4,
            "models_lost": 1,
            "models_killed": 2,
            "valid_actions": 8,
            "invalid_actions": 2,
            "wait_actions": 1,
            "forced_unit_episode_has_controlled": 1,
            "forced_unit_instances_controlled": 2,
            "forced_unit_counts_controlled": {"My Unit": 2},
            "victory_points_diff_controlled_minus_opponent": 1.0,
            "charges_declared": 2,
            "charges_succeeded": 1,
            # Cles EXIGEES depuis que les objectifs tenus sont echantillonnes cote moteur
            # (voir tests/unit/engine/test_objective_held_samples.py) : leur absence est un
            # etat corrompu, plus une courbe silencieusement muette.
            "controlled_objective_samples": [2.0, 1.0],
            "opponent_objective_samples": [1.0, 1.0],
            # f_obj_rewards vaut `objective_reward_factor x VP marques` : la courbe se lit sur
            # les VP de l'episode au lieu de rejouer la formule du versement.
            "victory_points_controlled_episode": 20.0,
        }
    )
    keys = [k for k, _, _ in _dw(t).scalars]
    assert "game_tactical/shooting_accuracy" in keys
    assert "01_VP/e_objectives_held" in keys
    assert "02_combat/a_value_trade_ratio" in keys
    assert "forcing/episodes_with_forced_unit_ratio" in keys


def test_compliance_mapper_phase_and_training_metrics_paths() -> None:
    t = _tracker_stub()
    t.log_aiturn_compliance(
        {
            "units_activated_this_step": 1,
            "phase_end_reason": "eligibility",
            "duplicate_activation_attempts": 0,
            "pool_corruption_detected": 0,
        }
    )
    t.log_reward_mapper_effectiveness(
        {
            "shooting_priority_correct": 1,
            "movement_had_tactical_bonus": True,
            "mapper_failed": False,
        }
    )
    t.log_phase_performance({"phase": "move", "action": "move", "was_flee": True})
    t.log_phase_performance({"phase": "shoot", "action": "shoot"})
    t.log_phase_performance({"phase": "charge", "action": "charge"})
    t.log_phase_performance({"phase": "fight", "action": "combat"})
    t.log_victory_points_cumulative(12.0)
    t.compute_and_log_phase_metrics()

    t.log_training_metrics(
        {
            "train/learning_rate": 3e-4,
            "train/policy_gradient_loss": -0.2,
            "train/value_loss": 0.3,
            "train/entropy_loss": 0.05,
            "train/ent_coef": 0.01,
            "train/clip_fraction": 0.2,
            "train/approx_kl": 0.01,
            "train/explained_variance": 0.4,
            "train/n_updates": 10,
            "train/gradient_norm": 1.2,
            "time/fps": 100,
        }
    )
    assert t.step_count == 1

    t.forcing_tracking["episodes_total"] = 1
    t.log_bot_evaluations(
        {"random": 0.5, "greedy": 0.6, "defensive": 0.4, "combined": 0.5, "holdout_hard_mean": 0.3},
        step=99,
    )
    keys = [k for k, _, _ in _dw(t).scalars]
    assert "00_critical/b_worst_bot_score" in keys
    assert "00_critical/a_bot_eval_combined" in keys


def test_log_episode_end_rejects_invalid_controlled_player() -> None:
    t = _tracker_stub()
    with pytest.raises(ValueError, match=r"controlled_player must be 1 or 2"):
        t.log_episode_end(
            {
                "total_reward": 1.0,
                "winner": 1,
                "episode_length": 10,
                "controlled_player": 3,
                "deployment_mode": None,
            }
        )


def test_log_tactical_metrics_forcing_validation_errors() -> None:
    t = _tracker_stub()
    base = {
        "shots_fired": 1,
        "hits": 1,
        "total_enemy_units": 1,
        "units_killed": 1,
        "damage_dealt": 1,
        "damage_received": 1,
        "units_lost": 1,
        "total_ally_units": 1,
        "enemy_value_destroyed": 1.0,
        "ally_value_lost": 1.0,
        "total_ally_value": 10.0,
        "total_enemy_value": 10.0,
        "initial_ally_models": 1,
        "initial_enemy_models": 1,
        "models_lost": 0,
        "models_killed": 0,
        "valid_actions": 1,
        "invalid_actions": 0,
        "wait_actions": 0,
        "victory_points_diff_controlled_minus_opponent": 0.0,
        "charges_declared": 0,
        "charges_succeeded": 0,
        "controlled_objective_samples": [1.0],
        "opponent_objective_samples": [1.0],
        "victory_points_controlled_episode": 5.0,
    }

    with pytest.raises(TypeError, match=r"forced_unit_counts_controlled.*dict"):
        t.log_tactical_metrics(
            {
                **base,
                "forced_unit_episode_has_controlled": 1,
                "forced_unit_instances_controlled": 1,
                "forced_unit_counts_controlled": [],
            }
        )

    with pytest.raises(ValueError, match=r"must be 0 or 1"):
        t.log_tactical_metrics(
            {
                **base,
                "forced_unit_episode_has_controlled": 2,
                "forced_unit_instances_controlled": 1,
                "forced_unit_counts_controlled": {"UnitA": 1},
            }
        )

    with pytest.raises(ValueError, match=r"must be > 0"):
        t.log_tactical_metrics(
            {
                **base,
                "forced_unit_episode_has_controlled": 1,
                "forced_unit_instances_controlled": 1,
                "forced_unit_counts_controlled": {"UnitA": 0},
            }
        )


def test_log_training_step_records_optional_fields() -> None:
    t = _tracker_stub()
    # exploration_rate a ete retire de step_data et de log_training_step : c'est l'epsilon d'une
    # politique epsilon-greedy (DQN), et seul MaskablePPO est instancie ici.
    t.log_training_step({"loss": 1.3, "learning_rate": 3e-4})
    keys = [k for k, _, _ in _dw(t).scalars]
    assert "training_detailed/loss" in keys
    assert "training_diagnostic/learning_rate" in keys
    assert t.step_count == 1
