import json
import os
from collections import defaultdict, deque
from pathlib import Path
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
from ai.truncation_log import TruncationLog
from config_loader import get_config_loader
from tests.unit.ai._fabriques import tactical_data

# Agent de reference de ces tests : il porte le training config lu ci-dessous ET la config de
# rewards que `__init__` charge dans le verrou `test_stub_matches_the_attributes_of_a_real_tracker`.
_AGENT_KEY = "ArmageddonAgent_x1"
_AGENT_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    f"config/agents/{_AGENT_KEY}/{_AGENT_KEY}_training_config.json",
)

# ENUMERE depuis le fichier, jamais fige en dur : un tuple ecrit a la main laisse silencieusement
# passer tout profil ajoute ensuite -- c'est exactement ce qui est arrive a `x1_long`
# (2026-08-02), qui a echappe a ce verrou alors qu'il etait la raison meme de son existence.
with open(_AGENT_CONFIG, encoding="utf-8-sig") as _f:
    ARMAGEDDON_PROFILES = tuple(k for k, v in json.load(_f).items() if isinstance(v, dict))


def test_every_training_profile_carries_its_smoothing_windows() -> None:
    """TOUS les profils resolvent leurs fenetres de lissage, via _training_common.json.

    Le test lit le VRAI fichier de config, pas une doublure : une section oubliee dans un
    profil ne se verrait qu'au lancement du run concerne, c'est-a-dire apres coup. Meme
    forme de verrou que tests/unit/engine/test_deployment_mode_schedule.py, et pour la meme
    raison — c'est deja par ce trou que deux profils avaient diverge en silence.

    Le doublon reactif a ete DESACTIVE le 2026-07-31 (`perf_window_fast == perf_window`, les 21
    courbes `_250ep` doublant les dashboards sans etre lues), puis REACTIVE a 100 le 2026-09-07 :
    la seule courbe reactive qui restait, `game_critical/win_rate_100ep`, etait ecrite en dur par
    le callback, hors du reglage et sur l'axe des pas. La reactivation la rend au tracker.
    Le test ne fige aucune des deux valeurs — c'est un reglage de run — seulement leur coherence.
    """
    # L'énumération doit couvrir le fichier, sinon ce test affiche « tout va bien » sur un
    # sous-ensemble : une liste vide, ou refigée en dur, passerait sans rien regarder.
    with open(_AGENT_CONFIG, encoding="utf-8-sig") as f:
        in_file = {k for k, v in json.load(f).items() if isinstance(v, dict)}
    assert in_file, "aucun profil lu dans le fichier de config"
    assert set(ARMAGEDDON_PROFILES) == in_file, (
        f"profils non couverts : {sorted(in_file - set(ARMAGEDDON_PROFILES))} — l'énumération "
        f"doit être DÉRIVÉE du fichier, jamais écrite à la main."
    )
    loader = get_config_loader()
    for profile in ARMAGEDDON_PROFILES:
        training_config = loader.load_agent_training_config("ArmageddonAgent_x1", profile)
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
    # Identite du run. Aucun ecrivain ne s'en sert ici — le writer est une doublure et le
    # journal de troncatures est sans dossier (voir plus bas) — mais l'attribut EXISTE sur un
    # vrai tracker, et `test_stub_matches_the_attributes_of_a_real_tracker` l'exige a ce titre.
    t.agent_key = "StubAgent"
    t.log_dir = "<stub: aucun dossier de run>"
    # Fenetres de lissage ramenees a 1 : ces tests verifient qu'un chemin d'execution emet la
    # bonne courbe, pas la taille des fenetres de production (500/100), qui les obligerait a
    # rejouer des centaines d'episodes. Egales, elles suppriment aussi le doublon `_100ep`.
    t.PERF_WINDOW = 1
    t.PERF_WINDOW_FAST = 1
    t.episode_count = 12
    t.step_count = 0
    # `log_dir=None` : comptage sans journal, le mode prevu pour qui n'a pas de dossier de run
    # (cf. ai/truncation_log.py). Ces tests verifient les courbes emises, pas la trace disque —
    # un vrai `log_dir` ferait ecrire un `truncations.jsonl` dans l'arborescence du depot.
    t.truncation_log = TruncationLog(None)
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
        "grad_share_policies": [],
    }
    t.ppo_capture_count = 0
    t._last_ppo_health_capture = -1
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
    # Idem, pour 02_combat/b_kill_rewards. Valeur de la config ArmageddonAgent au moment ou ce
    # stub la reprend (result_bonuses.kill_target) : aucun test ne l'observe aujourd'hui, mais
    # celui qui l'observera un jour doit lire un facteur plausible, pas un nombre invente.
    t.reward_kill_target = 2.0
    t._selfplay_wins = {}
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
    # Suivi des capacites par episode (chantier 06) — structure posee par __init__ a l'init
    # du tracker. Le stub reproduit la forme exacte pour que `test_stub_matches_the_attributes`
    # reste le verrou.
    t._abilities_tracking = {
        'total_episodes': 0,
        'counts': defaultdict(int),
        'exposures': defaultdict(int),
    }
    # `W40KMetricsTracker._reset_zone_intent_state(t)` etait appele ici, pour poser l'etat
    # zone-intent par sa propre methode comme `__init__` le fait. Retire le 2026-09-09 : l'etat
    # et la methode sont partis avec les neuf courbes d'intention.
    return t


def test_stub_matches_the_attributes_of_a_real_tracker(tmp_path: Path) -> None:
    """VERROU : `_tracker_stub` porte EXACTEMENT l'etat qu'un vrai tracker construit.

    Le stub court-circuite `__init__` (via `__new__`) et recopie l'etat a la main : il est
    rapide et decouple de la config disque, mais il DERIVE en silence. Les deux sens ont
    deja mordu ce fichier, et aucun des deux ne se signale tout seul :
      - attribut AJOUTE a `__init__` et absent du stub : le seul signal est un
        `AttributeError` le jour ou un chemin teste le lit (arrive sur `truncation_log` ;
        trois autres avaient derive de la meme facon sans que rien ne le dise) ;
      - attribut RETIRE du tracker et laisse dans le stub : aucun signal du tout, la
        doublure decrit un objet qui n'existe plus et les tests restent verts sur un etat
        mort (arrive sur `episode_tactical_data`, cf. le commentaire dans `_tracker_stub`).

    Le verrou compare les NOMS, pas les valeurs : les valeurs du stub sont une fixture
    deliberement differente de la production (fenetres a 1, 12 episodes d'historique). Un
    attribut ajoute a `__init__` et inutile a ces tests fera donc rouge ici — c'est voulu, il
    devient une ligne a poser sciemment plutot qu'une panne differee.

    Le vrai tracker est construit UNE fois, ici seulement : c'est ce qui permet aux 16 autres
    tests de garder un stub sans I/O ni lecture de la config d'agent.
    """
    real = W40KMetricsTracker(
        _AGENT_KEY,
        log_dir=str(tmp_path),
        show_banner=False,
        perf_window=1,
        perf_window_fast=1,
    )
    expected = set(vars(real))
    # Le SummaryWriter tient un fichier d'evenements ouvert dans tmp_path.
    real.writer.close()

    assert expected, "un vrai tracker sans attribut : le verrou ne regarderait rien"
    posed = set(vars(_tracker_stub()))
    missing = sorted(expected - posed)
    obsolete = sorted(posed - expected)
    assert not missing, (
        "_tracker_stub ne pose pas " + ", ".join(missing) + " : ces attributs existent sur un "
        "vrai tracker. Les ajouter au stub (ou retirer leur usage du tracker)."
    )
    assert not obsolete, (
        "_tracker_stub pose " + ", ".join(obsolete) + " : ces attributs n'existent plus sur un "
        "vrai tracker. Les retirer du stub, qui ferait sinon passer un etat mort pour valide."
    )


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

    # `step` EXIGE : l'eval intermediaire (callback) et l'eval finale (ai/train.py) alimentent
    # la meme courbe depuis deux instants differents, chacune sur SON abscisse.
    t.log_scenario_split_scores({"training_bot_1": 0.9, "hard_bot_1": 0.2}, step=4200)
    points = {k: s for k, _, s in _dw(t).scalars if k.startswith("bot_split/")}
    assert points == {"bot_split/training_bot_1": 4200, "bot_split/hard_bot_1": 4200}


def test_log_faction_bot_win_rates_publishes_the_bot_x_faction_cross() -> None:
    """V11 §0.55 / §10.6 : le croisement `bot_eval/faction/<faction>/vs_<bot>` est publie.

    Ni `bot_eval/vs_<bot>` (rosters melanges) ni `bot_eval/faction/<faction>` (adversaires
    melanges) ne disent si une faiblesse contre un bot tient a UN roster. Le holdout
    `tactical`, de poids nul, est absent de l'agregat par faction : c'est precisement lui
    que ce croisement doit rendre lisible par roster.

    Les deux familles sont emises par DEUX methodes, appelees ici comme les 3 sites de
    production le font : c'est cet enchainement que le test verrouille, pas une signature.
    """
    t = _tracker_stub()
    t.log_faction_scores({"Spacemarine": 0.6, "Ork": 0.4}, 0.2, step=7)
    t.log_faction_bot_win_rates(
        {
            "Spacemarine": {"control": 0.25, "tactical": 0.75},
            "Ork": {"control": 0.5, "tactical": 1.0},
        },
        step=7,
    )
    emitted = {k: (v, s) for k, v, s in _dw(t).scalars}
    assert emitted["bot_eval/faction/spacemarine"] == (0.6, 7)
    assert emitted["bot_eval/faction/spacemarine/vs_control"] == (0.25, 7)
    assert emitted["bot_eval/faction/spacemarine/vs_tactical"] == (0.75, 7)
    assert emitted["bot_eval/faction/ork/vs_control"] == (0.5, 7)
    assert emitted["bot_eval/faction/ork/vs_tactical"] == (1.0, 7)
    assert emitted["00_critical/0_gap_sm-ork"] == (0.2, 7)
    # Le croisement porte une information que l'agregat efface : ici l'agent domine avec les
    # Space Marines (gap > 0) tout en etant PLUS faible contre `control` avec eux qu'avec les
    # Orks. Une lecture par faction seule concluerait l'inverse.
    assert (
        emitted["bot_eval/faction/spacemarine/vs_control"][0]
        < emitted["bot_eval/faction/ork/vs_control"][0]
    )


def test_faction_tag_segment_is_shared_by_both_curve_families() -> None:
    """UNE regle faction -> segment de tag, pour l'agregat comme pour le croisement.

    Recopier `.lower()` dans chaque famille est le motif jumeau du depot : la faction
    COMPOSITE est le cas qui le revele, parce que c'est le seul ou `.lower()` et
    `_metric_slug` divergent (`ork+spacemarine` contre `ork_spacemarine`). Le segment est
    volontairement `.lower()` : passer au slug renommerait une courbe deja tracee.
    """
    t = _tracker_stub()
    t.log_faction_scores({"Ork+Spacemarine": 0.5}, None, step=3)
    t.log_faction_bot_win_rates({"Ork+Spacemarine": {"control": 0.5}}, step=3)
    keys = [k for k, _, _ in _dw(t).scalars]
    assert "bot_eval/faction/ork+spacemarine" in keys
    assert "bot_eval/faction/ork+spacemarine/vs_control" in keys
    # Le croisement est bien un SOUS-arbre du meme segment : un prefixe divergent rendrait
    # les deux familles illisibles ensemble dans TensorBoard.
    assert keys[1].startswith(keys[0] + "/")


def test_log_faction_bot_win_rates_refuses_what_it_cannot_publish() -> None:
    """Une ventilation qui n'est pas un dict leve, au lieu d'etre ignoree en silence.

    Une courbe absente se lit « pas encore mesure », jamais « appelant casse » : c'est cette
    confusion que le garde interdit.
    """
    t = _tracker_stub()
    with pytest.raises(TypeError, match="faction_bot_win_rates must be dict"):
        t.log_faction_bot_win_rates([("Ork", "control", 0.5)])  # type: ignore[arg-type]


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
    # La factory resout le dossier de l'agent ELLE-MEME : le config porte la racine TensorBoard,
    # et le constructeur du tracker ne suffixe plus rien en silence — il ecrit exactement ou on
    # lui dit (cf. tests/unit/ai/test_tensorboard_single_run_dir.py).
    assert created["log_dir"] == os.path.join("/tmp/tb", "CoreAgent")
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

    # Fabrique PARTAGEE (tests/unit/ai/_fabriques.py) : `log_tactical_metrics` lit toutes ses
    # cles en STRICT, donc toute fixture ecrite a la main doit les porter TOUTES. Trois copies
    # manuelles ont casse une par une a chaque cle ajoutee au tracker — il n'en reste qu'une.
    t.log_tactical_metrics(tactical_data(
        forced_unit_episode_has_controlled=1,
        forced_unit_instances_controlled=2,
        forced_unit_counts_controlled={"My Unit": 2},
    ))
    keys = [k for k, _, _ in _dw(t).scalars]
    assert "04_shoot/b_accuracy" in keys
    assert "01_VP/e_objectives_held" in keys
    assert "02_combat/a_value_trade_ratio" in keys
    assert "forcing/episodes_with_forced_unit_ratio" in keys


def test_le_forcing_par_unite_separe_l_exposition_de_l_intensite() -> None:
    """VERROU des deux courbes du forcing qui vivent DANS la boucle par unite.

    `forcing/unit_episode_exposure/*` (part des episodes ou l'unite a ete forcee) et
    `forcing/unit_instance_mean/*` (nombre moyen d'instances forcees par episode) ne sont emises
    que si `forced_unit_counts_controlled` n'est pas vide. Tant que la fabrique partagee y
    laissait un dict vide, AUCUN test du depot ne les atteignait : les supprimer, ou brancher
    l'une sur le compteur de l'autre, restait vert.

    TROIS EPISODES, et aucun n'est decoratif :
      1. les deux unites forcees — les deux courbes existent, avec des valeurs distinctes ;
      2. AUCUNE unite forcee — seul episode qui separe `episodes_total` (3) de
         `episodes_with_forced_unit` (2). Sans lui, les deux compteurs restent egaux et le
         denominateur des expositions n'est pas verrouille : le brancher sur le mauvais des
         deux passait inapercu ;
      3. Ork Boyz seul — son exposition (2/3) et son intensite (4/3) divergent enfin l'une de
         l'autre, ce qu'un episode unique ne montre pas, et l'Intercessor absent de cet
         episode-la ne publie RIEN.
    """
    t = _tracker_stub()
    t.compute_and_log_phase_metrics = lambda: None
    t.log_critical_dashboard = lambda: None

    t.log_tactical_metrics(tactical_data())
    premier = {k: v for k, v, _ in _dw(t).scalars}
    assert premier["forcing/unit_episode_exposure/intercessor"] == 1.0
    assert premier["forcing/unit_episode_exposure/ork_boyz"] == 1.0
    assert premier["forcing/unit_instance_mean/intercessor"] == 2.0
    assert premier["forcing/unit_instance_mean/ork_boyz"] == 3.0

    t.log_tactical_metrics(tactical_data(
        forced_unit_episode_has_controlled=0,
        forced_unit_instances_controlled=0,
        forced_unit_counts_controlled={},
    ))

    deja_publie = len(_dw(t).scalars)
    t.log_tactical_metrics(tactical_data(
        forced_unit_instances_controlled=1,
        forced_unit_counts_controlled={"Ork Boyz": 1},
    ))
    nouveaux = {k: v for k, v, _ in _dw(t).scalars[deja_publie:]}
    # Ork Boyz force dans 2 episodes sur 3, pour 3 + 1 instances : les deux courbes se separent,
    # et chacune se lit sur le NOMBRE D'EPISODES (3), jamais sur les episodes forces (2).
    assert nouveaux["forcing/unit_episode_exposure/ork_boyz"] == pytest.approx(2 / 3)
    assert nouveaux["forcing/unit_instance_mean/ork_boyz"] == pytest.approx(4 / 3)
    assert "forcing/unit_instance_mean/intercessor" not in nouveaux, (
        "une unite non forcee cet episode-la n'a pas de point a publier : la courbe est CREUSE, "
        "et republier son ancienne valeur ferait mentir la moyenne au pas suivant"
    )


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


def test_grad_clip_fraction_emis_dans_training_diagnostic() -> None:
    """VERROU : `training_diagnostic/grad_clip_fraction` est publie quand present dans model_stats.

    La branche 1608-1612 de `log_training_metrics` n'etait jamais exercee par les tests existants
    (aucun ne passait `train/grad_clip_fraction`). Un typo dans la cle ou dans le tag passerait
    inapercue.
    """
    t = _tracker_stub()
    t.log_training_metrics(
        {
            "train/gradient_norm": 0.8,
            "train/grad_clip_fraction": 0.15,
        }
    )
    keys = [k for k, _, _ in _dw(t).scalars]
    assert "training_diagnostic/grad_clip_fraction" in keys, (
        "training_diagnostic/grad_clip_fraction absent alors que train/grad_clip_fraction fourni"
    )
    vals = [v for k, v, _ in _dw(t).scalars if k == "training_diagnostic/grad_clip_fraction"]
    assert vals == [0.15], f"valeur attendue 0.15, obtenu {vals}"


def test_les_deux_courbes_ppo_brutes_de_00_critical_sont_emises() -> None:
    """VERROU : `l_approx_kl_max` et `m_explained_var` portent la valeur BRUTE de l'update.

    Les deux existent parce qu'un lissage les rendrait muettes sur ce qu'on leur demande :
    `l` est la KL qui declenche l'early-stop de PPO (un pic sur un seul update), et `m` est la
    jumelle non lissee de `h_explained_variance`. Les faire passer par
    `_calculate_smoothed_metric` reproduirait donc les courbes qui existent deja.
    """
    t = _tracker_stub()
    t.log_training_metrics({
        "train/approx_kl": 0.01,
        "train/approx_kl_max": 0.034,
        "train/explained_variance": 0.42,
    })

    scalars = _dw(t).scalars
    assert [v for k, v, _ in scalars if k == "00_critical/l_approx_kl_max"] == [0.034]
    assert [v for k, v, _ in scalars if k == "00_critical/m_explained_var"] == [0.42]


def test_l_approx_kl_max_reste_muette_sans_ppo_patche() -> None:
    """VERROU : pas de `train/approx_kl_max` -> pas de courbe, PAS une valeur de repli.

    Seul `ai/patched_ppo.py` publie ce tag. Retomber sur `train/approx_kl` (la MOYENNE) ou sur
    un 0.0 ferait lire une KL maximale la ou aucune n'a ete mesuree — le dashboard annoncerait
    une marge d'early-stop confortable sur un run qui n'en sait rien.
    """
    t = _tracker_stub()
    t.log_training_metrics({"train/approx_kl": 0.01, "train/explained_variance": 0.42})

    keys = [k for k, _, _ in _dw(t).scalars]
    assert "00_critical/l_approx_kl_max" not in keys
    assert "00_critical/m_explained_var" in keys, "m ne depend pas du PPO patche"


def test_gradient_norm_nan_est_ecarte() -> None:
    """VERROU : un NaN dans `train/gradient_norm` ou `train/grad_clip_fraction` (early-stop KL)
    ne pollue ni TensorBoard ni `latest_gradient_norm`.

    `_grad_norm_stats` retourne (nan, nan) quand la liste de normes est vide — ce qui arrive si
    PPO coupe les epochs avant le premier `loss.backward()`. Les deux NaN doivent etre filtres,
    comme `diag/grad_share_policy_mb0`.
    """
    import math as _math
    t = _tracker_stub()
    t.latest_gradient_norm = 1.2  # valeur finie precedente
    t.log_training_metrics({
        "train/gradient_norm": float("nan"),
        "train/grad_clip_fraction": float("nan"),
    })
    keys = [k for k, _, _ in _dw(t).scalars]
    assert "training_diagnostic/gradient_norm" not in keys, (
        "NaN publie sur training_diagnostic/gradient_norm — doit etre ecarte"
    )
    assert "training_diagnostic/grad_clip_fraction" not in keys, (
        "NaN publie sur training_diagnostic/grad_clip_fraction — doit etre ecarte"
    )
    assert _math.isfinite(t.latest_gradient_norm), (
        f"latest_gradient_norm ecrase par NaN : {t.latest_gradient_norm}"
    )


_PPO_CURVE_TAGS: tuple[str, ...] = (
    "00_critical/f_loss_mean",
    "00_critical/g_grad_share_policy_mb0",
    "00_critical/h_explained_variance",
    "00_critical/i_clip_fraction",
    "00_critical/j_approx_kl",
    "00_critical/k_entropy_loss",
)

_UPDATE_STATS: Dict[str, float] = {
    "train/learning_rate": 3e-4,
    "train/policy_gradient_loss": -0.2,
    "train/value_loss": 0.3,
    "train/entropy_loss": 0.05,
    "train/clip_fraction": 0.2,
    "train/approx_kl": 0.01,
    "train/explained_variance": 0.4,
    "diag/grad_share_policy_mb0": 0.235,
}


def test_les_courbes_de_sante_ppo_suivent_la_cadence_de_l_update() -> None:
    """VERROU : un point par UPDATE PPO, pas un par episode.

    `hyperparameter_tracking` n'est alimente que par `log_training_metrics`, soit une fois par
    update, alors que `log_critical_dashboard` tourne a CHAQUE fin d'episode — 74 par update sur
    x1_long. Sans la garde `ppo_capture_is_new`, chaque valeur repartait 74 fois : mesure sur
    run_20260906-123804, 39 430 points pour 529 valeurs distinctes. Le curseur de lissage de
    TensorBoard comptant des POINTS, il aurait fallu le regler sur ~1500 pour couvrir la fenetre
    de 20 updates de `_calculate_smoothed_metric`.

    Les huit lignes `thresholds/*` sont sous la meme garde, mais gatees en plus par
    `ppo_capture_count > 0` : elles ne s'emettent donc qu'a partir du DEUXIEME detection-event
    (sentinel -1 consomme par le premier dashboard, vrai update au second). Les courbes elles
    s'emettent des le premier dashboard car les listes sont pre-remplies dans ce test.
    """
    t = _tracker_stub()
    # Le stub laisse quatre listes vides ; les remplir met les six courbes dans le meme etat,
    # sans quoi `f_loss_mean`, `g_grad_share_policy_mb0` et `h_explained_variance` compteraient
    # un point de retard.
    t.hyperparameter_tracking["policy_losses"] = [-0.2] * 12
    t.hyperparameter_tracking["value_losses"] = [0.3] * 12
    t.hyperparameter_tracking["explained_variances"] = [0.4] * 12
    t.hyperparameter_tracking["grad_share_policies"] = [0.235] * 12

    # Verrou discriminabilite : si ces deux valeurs convergent, les assertions d'axe deviennent
    # muettes — le test doit echouer si le stub est modifie de facon a les egaliser.
    assert t.episode_count != t.step_count, (
        f"stub invalide : episode_count={t.episode_count} == step_count={t.step_count}"
    )

    curve_tags = _PPO_CURVE_TAGS
    threshold_tags = (
        "thresholds/clip_fraction_min",
        "thresholds/clip_fraction_max",
        "thresholds/kl_max",
        "thresholds/explained_variance_min",
    )
    all_tags = curve_tags + threshold_tags

    def _counts() -> Dict[str, int]:
        keys = [k for k, _, _ in _dw(t).scalars]
        return {tag: keys.count(tag) for tag in all_tags}

    # Premier cycle : ppo_capture_count=0, sentinel -1 → courbes emises (1 point), seuils NON
    # (ppo_capture_count > 0 = False). C'est la seule asymetrie du test.
    for _ in range(20):
        t.log_critical_dashboard()
    assert _counts() == {tag: 1 for tag in curve_tags} | {tag: 0 for tag in threshold_tags}

    # Deuxieme cycle : apres le premier update PPO (count=1), seuils et courbes s'emettent.
    t.log_training_metrics(dict(_UPDATE_STATS))
    for _ in range(20):
        t.log_critical_dashboard()
    assert _counts() == {tag: 2 for tag in curve_tags} | {tag: 1 for tag in threshold_tags}

    # Troisieme cycle : second update PPO.
    t.log_training_metrics(dict(_UPDATE_STATS))
    for _ in range(20):
        t.log_critical_dashboard()
    assert _counts() == {tag: 3 for tag in curve_tags} | {tag: 2 for tag in threshold_tags}

    # 60 fins d'episode pour 2 updates : ce sont bien les updates qui cadencent, pas les episodes.
    assert t.ppo_capture_count == 2

    # L'abscisse de CHAQUE courbe PPO doit etre episode_count (12), pas step_count (0).
    # Verrou contre un remplacement accidentel de l'axe sur n'importe laquelle des cinq courbes.
    all_scalars = _dw(t).scalars
    for tag in curve_tags:
        steps = {step for k, _v, step in all_scalars if k == tag}
        assert steps == {t.episode_count}, (
            f"{tag} : abscisse = {steps}, attendu {{episode_count={t.episode_count}}}"
        )

    # Les seuils doivent partager la meme abscisse que les courbes qu'ils annotent.
    # La boucle precedente a prouve que chaque courbe a steps == {t.episode_count}.
    for tag in threshold_tags:
        steps = {step for k, _v, step in all_scalars if k == tag}
        assert steps == {t.episode_count}, (
            f"desalignement {tag} : {steps}, attendu {{episode_count={t.episode_count}}}"
        )


def test_les_courbes_de_jeu_gardent_leur_point_par_episode() -> None:
    """VERROU : la garde de cadence PPO ne doit PAS deborder sur les courbes d'episode.

    `log_critical_dashboard` ecrit le bloc `game_critical/reward_when_*` HORS de la garde
    `ppo_capture_is_new`, donc il se lit par episode. L'aspirer sous la garde le figerait entre
    deux updates — 74 episodes sans point sur x1_long.

    ANCRAGE, troisieme fois : ce test a suivi les courbes par-episode que cette methode ecrit.
    `d_win_rate` et `e_episode_reward_smooth` d'abord, puis `o_intent_zone_steps` (suite 18), et
    maintenant `reward_when_won` — les metriques d'intention sont parties le 2026-09-09 avec la
    famille d'actions. Contrairement aux precedentes, celle-ci est CONDITIONNEE (>= 20 paires
    dont >= 5 de chaque issue), d'ou l'amorce ci-dessous : sans elle le test serait VERT VACANT,
    a compter zero point sur zero point.
    """
    t = _tracker_stub()
    for i in range(20):
        t.episode_reward_winner_pairs.append((10.0 if i % 2 else -5.0, i % 2))

    for _ in range(20):
        t.log_critical_dashboard()

    keys = [k for k, _, _ in _dw(t).scalars]
    assert keys.count("game_critical/reward_when_won") == 20


def test_aucun_seuil_emis_avant_la_premiere_capture_ppo() -> None:
    """VERROU : `_log_thresholds` ne doit pas emettre de point orphelin au tout premier dashboard.

    Au demarrage : ppo_capture_count=0, _last_ppo_health_capture=-1. Le premier appel a
    `log_critical_dashboard` entre dans ppo_capture_is_new=True, mais aucun update PPO n'a eu lieu.
    La garde `ppo_capture_count > 0` empeche l'emission des seuils. Les cinq courbes PPO sont elles
    protegees par `len(liste) >= 1` (listes vides ici). Les deux jeux de garde doivent etre coherents :
    ni seuils orphelins, ni courbes orphelines.
    """
    t = _tracker_stub()
    # Vider toutes les listes : simule le demarrage avant le premier update PPO.
    for key in t.hyperparameter_tracking:
        t.hyperparameter_tracking[key] = []

    t.log_critical_dashboard()

    keys = [k for k, _, _ in _dw(t).scalars]
    threshold_keys = [k for k in keys if k.startswith("thresholds/")]
    assert threshold_keys == [], (
        f"seuils emis avant la premiere capture PPO : {threshold_keys}"
    )
    ppo_curve_keys = [k for k in keys if k in _PPO_CURVE_TAGS]
    assert ppo_curve_keys == [], (
        f"courbes PPO emises avec listes vides : {ppo_curve_keys}"
    )


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
    base = tactical_data()
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


def test_log_selfplay_win_emet_par_label() -> None:
    """log_selfplay_win emet 03_selfplay/{label} une fois la fenetre pleine (PERF_WINDOW=1)."""
    t = _tracker_stub()  # PERF_WINDOW=1 : la fenetre est pleine des le 1er appel
    t.log_selfplay_win("P1", 1.0)
    t.log_selfplay_win("P2", 0.0)
    t.log_selfplay_win("P1", 0.0)

    keys = [k for k, _, _ in _dw(t).scalars]
    assert "03_selfplay/P1" in keys, "win rate de P1 absent"
    assert "03_selfplay/P2" in keys, "win rate de P2 absent"


def test_log_selfplay_win_label_vide_est_ignore() -> None:
    """Un label vide (episode bot) ne doit rien emettre."""
    t = _tracker_stub()
    t.log_selfplay_win("", 1.0)
    assert not _dw(t).scalars, "aucun scalar attendu pour un label vide"


def test_log_selfplay_win_valeur_correcte() -> None:
    """Avec PERF_WINDOW=1, le dernier appel donne le win rate exact (0.0 ou 1.0)."""
    t = _tracker_stub()
    t.log_selfplay_win("E1", 1.0)
    t.log_selfplay_win("E1", 0.0)  # ecrase la fenetre de taille 1

    scalars = {k: v for k, v, _ in _dw(t).scalars}
    assert scalars["03_selfplay/E1"] == pytest.approx(0.0), "la valeur doit etre la moyenne de la fenetre"


def test_log_selfplay_win_emet_fenetre_fast() -> None:
    """La fenetre reactive (PERF_WINDOW_FAST ep) est emise quand PERF_WINDOW_FAST < PERF_WINDOW."""
    t = _tracker_stub()
    t.PERF_WINDOW = 5
    t.PERF_WINDOW_FAST = 3
    for _ in range(3):
        t.log_selfplay_win("F1", 1.0)

    keys = [k for k, _, _ in _dw(t).scalars]
    assert "03_selfplay/F1_3ep" in keys, "tag reactif absent apres remplissage de la fenetre fast"


# ── SONDES DE POOL : LE TAG DOIT NOMMER LA FENETRE QU'IL PORTE ─────────────────────────────


def test_log_pool_probe_names_the_window_it_carries() -> None:
    """Le tag de la moyenne porte `probe_window`, qui est CONFIGURABLE.

    Il valait `_3ep` en dur alors que `early_stop.probe_window` accepte toute valeur >= 2 : une
    fenetre de 5 publiait sa moyenne sous un nom annoncant 3. Les commentaires qui designent cette
    courbe comme la grandeur de decision (ai/curriculum.py, ai/training_callbacks.py) pointaient
    alors un tag qui contredit ce qu'il contient, et deux runs a fenetres differentes
    superposaient deux grandeurs distinctes sur une seule courbe.
    """
    t = _tracker_stub()
    t.log_pool_probe("P1", 0.51, 0.53, 1000, 5)

    keys = [k for k, _, _ in _dw(t).scalars]
    assert "pool_eval/vs_p1_5ep" in keys, f"le tag doit nommer la fenetre 5 : {keys}"
    assert "pool_eval/vs_p1_3ep" not in keys, "le 3 en dur ne doit plus apparaitre"
    assert "pool_eval/vs_p1" in keys, "la brute reste publiee a cote"


def test_log_pool_probe_omits_the_mean_on_a_single_probe() -> None:
    """`rolling_mean` None : rien a publier, la moyenne serait identique a la brute."""
    t = _tracker_stub()
    t.log_pool_probe("P1", 0.51, None, 1000, 3)

    keys = [k for k, _, _ in _dw(t).scalars]
    assert keys == ["pool_eval/vs_p1"], f"seule la brute doit sortir : {keys}"


def test_log_pool_probe_refuses_a_window_of_one() -> None:
    """Une fenetre d'une sonde rend une moyenne identique au brut : le tag mentirait."""
    t = _tracker_stub()
    with pytest.raises(ValueError, match="au moins 2"):
        t.log_pool_probe("P1", 0.51, 0.51, 1000, 1)
