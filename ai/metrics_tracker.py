#!/usr/bin/env python3
"""
ai/metrics_tracker.py - W40K Training Metrics Tracker
Professional dual 3-tier metric organization for game performance and training health

DUAL TIER SYSTEM (41 Total Metrics):

🎮 GAME PERFORMANCE SYSTEM (25 metrics)
  🔥 game_critical/ (5) - Core gameplay success indicators
     - win_rate_100ep, episode_reward, episode_length, 
       units_killed_vs_lost_ratio, invalid_action_rate
  
  🎯 game_tactical/ - Tactical decision quality
     - shooting_accuracy, damage_efficiency, unit_trade_ratio,
       movement_efficiency, shooting_participation
  
  🔬 game_detailed/ (12+) - Deep tactical analysis
     - reward_decomposition (5), phase_performance (4),
       aiturn_compliance (3+)

⚙️ TRAINING HEALTH SYSTEM (16 metrics)
  🔥 training_critical/ (6) - Algorithm health indicators
     - policy_loss, value_loss, explained_variance,
       clip_fraction, approx_kl, fps
  
  🔍 training_diagnostic/ (5) - Hyperparameter monitoring
     - learning_rate, entropy_coef, entropy_loss, n_updates, gradient_norm
  
  🔬 training_detailed/ (5+) - Deep algorithm diagnostics
     - advantage metrics, policy gradient details, value function analysis
"""

import numpy as np
from collections import Counter, defaultdict, deque
from torch.utils.tensorboard.writer import SummaryWriter
import os
from typing import Any, Deque, Dict, List, Optional, Protocol, Sequence, Tuple, Tuple
from shared.data_validation import require_key
# SOURCE UNIQUE des noms de bots (cf. l'en-tete de `ai/bot_registry.py`) : ce module portait la
# QUATRIEME table du depot, ecrite a la main et restee sur le panel d'origine.
from ai.bot_evaluation import write_ckpt_scalars
from ai.bot_registry import ALL_BOT_KEYS, BENCHMARK_BOT_KEYS, SELECTION_BOT_KEYS
from ai.truncation_log import TruncationLog, agent_log_dir
from engine.action_decoder import ActionDecoder
from engine.constants import DRAW_WINNER
from engine.w40k_core import CHARGE_DISTANCE_MEASURES
from config_loader import get_config_loader


#: Largeur de la fenetre glissante des metriques zone-intent, en EPISODES.
#:
#: Le nombre de free steps par episode a un ecart-type de ~18,5 sur un run de reference, ce qui
#: rend la valeur brute illisible. Moyenner sur 100 episodes ramene l'ecart-type des moyennes a
#: ~0,94 ; 200 episodes ne descendent qu'a ~0,87 et 830 (un rollout) qu'a ~0,78 : le gain est
#: epuise bien avant. Constante FIXE et non derivee de n_steps/n_envs, pour que la courbe reste
#: comparable entre configurations d'entrainement.
#:
#: La largeur porte aussi I(intent ; controle) : ~2000 free steps pour 9 cellules, soit un biais
#: positif de la mesure empirique de ~0,001 bit. Reduire cette constante degraderait ce biais.
ZONE_INTENT_WINDOW_EPISODES = 100

#: Etats de controle d'un objectif renvoyes par `engine.macro_intents.get_objective_control`
#: (-1.0 adversaire, 0.0 neutre/conteste, 1.0 joueur courant), remappes en index 0..2.
ZONE_CONTROL_CARDINALITY = 3

#: INTENT_INVADE / INTENT_DEFEND / INTENT_ATTACK.
INTENT_CARDINALITY = 3


def validate_perf_windows(perf_window: int, perf_window_fast: int) -> tuple[int, int]:
    """Controle le couple de fenetres de lissage et le retourne en entiers.

    Egales, les deux fenetres DESACTIVENT le doublon reactif : `_emit_windowed` ne l'emet
    qu'a fenetre strictement plus courte, sans quoi le dashboard afficherait deux courbes
    superposees qui se liraient comme une confirmation mutuelle alors qu'elles n'en sont
    qu'une. C'est un reglage legitime, pas une tolerance : c'est ainsi qu'on revient a une
    seule courbe par mesure. Une fenetre reactive PLUS LONGUE que la fenetre de fond n'a en
    revanche aucun sens et leve.
    """
    window = int(perf_window)
    fast = int(perf_window_fast)
    if window < 1 or fast < 1:
        raise ValueError(
            f"metrics_smoothing windows must be >= 1 (got perf_window={window}, "
            f"perf_window_fast={fast})"
        )
    if fast > window:
        raise ValueError(
            f"metrics_smoothing.perf_window_fast ({fast}) cannot exceed perf_window "
            f"({window}) — the reactive curve must not be smoother than the baseline."
        )
    return window, fast


def resolve_perf_windows(training_config: Dict[str, Any]) -> tuple[int, int]:
    """Fenetres de lissage lues dans le training config de l'agent. Cles EXIGEES.

    La section `metrics_smoothing` se met a `null` dans un profil pour hériter de
    config/agents/_training_common.json, comme les autres reglages partages.
    """
    smoothing = require_key(training_config, "metrics_smoothing")
    if not isinstance(smoothing, dict):
        raise TypeError(
            f"training_config.metrics_smoothing must be a mapping "
            f"(got {type(smoothing).__name__})"
        )
    return validate_perf_windows(
        require_key(smoothing, "perf_window"),
        require_key(smoothing, "perf_window_fast"),
    )


class MetricsWriter(Protocol):
    """Les QUATRE methodes que le tracker demande a son writer TensorBoard.

    Releve exhaustif des usages de `self.writer` (tracker) et de
    `metrics_tracker.writer` (ai/training_callbacks.py l.958, 2149, 2231) : `add_scalar`,
    `add_custom_scalars`, `flush`, `close`. Rien d'autre — ni `add_histogram`, ni
    `add_graph`, ni `log_dir`, ni le contexte de fichier d'evenements.

    Annoncer `SummaryWriter` obligeait chaque test a un cast dans les DEUX sens sur le meme
    attribut (`cast(SummaryWriter, doublure)` en ecriture, `cast(_DummyWriter, t.writer)` en
    relecture) : l'aller-retour est la marque d'un type absent, pas d'un type trop faible.

    Parametres positionnels seuls (`/`) : le protocole ne contraint que ce que les appels
    utilisent reellement. `SummaryWriter.add_scalar` les nomme `tag, scalar_value,
    global_step`, une doublure les nommerait autrement — imposer des noms rejetterait des
    porteurs valides sans rien verifier de plus.

    Conformite du vrai writer verifiee par pyright a l'affectation
    `self.writer: MetricsWriter = SummaryWriter(...)`, pas par declaration : un protocole que
    seule la doublure honorerait ne vaudrait rien. Nuance a connaitre : torch n'annote pas ces
    methodes, donc seuls les NOMS et l'arite sont reellement contraints cote SummaryWriter.
    """

    def add_scalar(self, tag: str, scalar_value: float, global_step: int, /) -> None: ...

    def add_custom_scalars(self, layout: Dict[str, Any], /) -> None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


class W40KMetricsTracker:
    """
    Tracks essential training metrics for W40K agents with tensorboard integration.
    Streamlined to 20 critical metrics, removing redundant calculations.
    """

    #: Fenetres de lissage des courbes de PERFORMANCE. Deux fenetres par mesure, jamais une :
    #:   - PERF_WINDOW      : la fenetre de fond, celle qui tranche une tendance ;
    #:   - PERF_WINDOW_FAST : le doublon reactif, tag suffixe `_100ep`, qui montre l'evolution
    #:                        recente et repond des le centieme episode.
    #: AUCUN point n'est emis tant que la fenetre n'est pas PLEINE. La version precedente
    #: retournait la moyenne de TOUT l'historique sous la fenetre : les 500 premiers points de
    #: chaque courbe etaient une moyenne cumulative, qui converge en DESCENDANT depuis son
    #: echantillon de depart bruite. Cette descente ne mesure que le remplissage de la fenetre,
    #: mais elle a l'allure exacte d'un agent qui se degrade — et elle a ete lue comme telle.
    #: Un point absent ne ment pas ; un point qui n'a pas le meme sens que son voisin, si.
    #: Les deux valeurs viennent du training config de l'agent (`metrics_smoothing`, cf.
    #: `resolve_perf_windows`) : elles se regient par run, sans toucher au code. Elles sont
    #: posees sur l'INSTANCE par __init__ — la classe n'en porte aucune, pour qu'un appelant
    #: qui oublierait de les fournir tombe tout de suite au lieu d'hériter d'un 500 muet.

    #: Series accumulees par `_game_push` et emises sur deux fenetres par `_emit_game`
    #: (dashboards 01_VP/ et 02_combat/).
    #: Constante de classe et non litteral dans __init__ : les doublures de test qui
    #: reconstruisent l'objet a la main recopiaient la liste, et toute courbe ajoutee ici
    #: les faisait tomber en KeyError sur un detail sans rapport avec ce qu'elles testent.
    GAME_HISTORY_KEYS = (
        'vp_diff', 'vp_bot', 'objectives_held', 'objectives_held_diff',
        'kill_rewards', 'obj_rewards',
        'models_killed_ratio', 'models_lost_ratio',
        'value_killed_ratio', 'value_lost_ratio',
        'units_killed_ratio', 'units_lost_ratio',
        'value_destroyed', 'value_lost',
        'shoot_kills', 'melee_kills', 'shoot_value_killed', 'melee_value_killed',
        'charge_attempts', 'charge_successes',
        'charge_attempts_bot', 'charge_successes_bot',
        'move_actions', 'move_flees', 'move_advances', 'move_opportunities',
        'shoot_activations', 'shoot_opportunities',
        # Distances de charge (11.04) : une serie par somme ET par effectif, les deux camps.
        # Elles vont par paires dans `_emit_ratio_of_means` — c'est exactement la forme qu'il
        # attend, un numerateur et un denominateur qui sont tous deux des RESULTATS d'episode.
        *(
            f'charge_{_measure}_{_side}'
            for _side in ('agent', 'opponent')
            for _measure in CHARGE_DISTANCE_MEASURES
        ),
        # Cout du cache de scoring du deploiement (V11 §0.46 axe A).
        'deploy_cache_lookups', 'deploy_cache_full_builds', 'deploy_cache_incremental_failed',
        # Activations de combat par tour (06_fight/a_activations_per_turn).
        'fight_activations', 'fight_final_turn',
    )

    #: Modes de deploiement ventiles (cf. `deployment_mode_schedule`, w40k_core).
    #: 'auto' a remplace 'fixed' le 2026-08-08 : les deux modes jouent desormais une VRAIE
    #: phase de deploiement, seul change QUI decide des poses (le moteur, ou la politique).
    DEPLOY_MODES = ('active', 'auto')

    #: Series ventilees par mode de deploiement -> prefixe de tag 00_critical.
    #: Le mode est SUFFIXE au tag (`..._active` / `..._auto`) et non porte par une lettre
    #: distincte : les deux courbes d'une meme mesure se trient alors cote a cote et se
    #: superposent d'un clic, ce qui est la seule lecture qui reponde a la question posee.
    #:
    #: POURQUOI CETTE VENTILATION. `deployment_mode_schedule` fait monter la part d'episodes en
    #: deploiement ACTIF de 0% a 80% sur la duree du run. La tache mesuree change donc en
    #: continu, alors que l'EVALUATION, elle, impose toujours un deploiement. Une courbe agregee
    #: melange les deux populations dans des proportions mouvantes : elle s'aplatit et se
    #: disperse quand l'agent progresse mais que la tache durcit a la meme vitesse, ce qui est
    #: indiscernable d'un agent qui plafonne. Ventilee, chaque population redevient lisible.
    #:
    #: Trois series et non huit : 00_critical en compte deja une douzaine, et doubler la
    #: categorie la rend illisible. `vp_diff` et `value_trade_ratio` sont ecartees comme
    #: largement redondantes avec la difference d'objectifs et la recompense.
    DEPLOY_SPLIT_SERIES = {
        'reward': '00_critical/p_reward_deploy',
        'obj_held_diff': '00_critical/q_obj_held_diff_deploy',
        'win': '00_critical/r_win_rate_deploy',
    }

    #: Cle d'historique `_game_history` -> serie ventilee. Le branchement se fait dans
    #: `_emit_game`, point de passage UNIQUE des courbes 01_VP/ et 02_combat/ : ventiler sur les
    #: huit sites d'appel aurait laisse diverger l'appariement tag <-> historique, qui est
    #: precisement ce que `_emit_ratio` documente comme se cassant en silence.
    DEPLOY_SPLIT_GAME_KEYS = {
        'objectives_held_diff': 'obj_held_diff',
    }


    def __init__(
        self,
        agent_key: str,
        log_dir: str = "./tensorboard/",
        initial_episode_count: int = 0,
        initial_step_count: int = 0,
        show_banner: bool = True,
        *,
        perf_window: int,
        perf_window_fast: int,
    ):
        self.PERF_WINDOW, self.PERF_WINDOW_FAST = validate_perf_windows(
            perf_window, perf_window_fast
        )
        self.agent_key = agent_key
        self.log_dir = agent_log_dir(log_dir, agent_key)
        self.writer: MetricsWriter = SummaryWriter(self.log_dir)
        self._setup_custom_scalars_layout()

        # Load reward values from agent rewards config (avoid hardcoding training variables)
        # Strip phase suffix to find the config directory (e.g. CoreAgent_phase1 → CoreAgent)
        _base_key = agent_key
        for _sfx in ('_phase1', '_phase2', '_phase3', '_phase4'):
            if _base_key.endswith(_sfx):
                _base_key = _base_key[:-len(_sfx)]
                break
        _config_loader = get_config_loader()
        _rewards_cfg = _config_loader.load_agent_rewards_config(_base_key)
        _agent_rewards = require_key(_rewards_cfg, _base_key)
        _objective_rewards = require_key(_agent_rewards, "objective_rewards")
        # Facteur d'echelle du versement d'objectif : le reward vaut EXACTEMENT ce facteur fois
        # les VP marques (cf. _calculate_objective_reward_per_turn). Les trois reglages qui
        # occupaient cette place (reward_per_objective / use_objective_lead /
        # reward_for_objective_lead) decrivaient une formule LINEAIRE que ce fichier rejouait sur
        # les echantillons — un miroir de la formule du moteur, donc une divergence en attente.
        self.objective_reward_factor: float = float(
            require_key(_objective_rewards, "objective_reward_factor")
        )
        self.reward_kill_target: float = float(
            require_key(require_key(_agent_rewards, "result_bonuses"), "kill_target")
        )

        # Rolling window for win rate only (100 episodes)
        self.win_rate_window = deque(maxlen=500)
        
        # Reward-victory correlation: (reward, outcome_flag) pairs for last N episodes.
        # outcome_flag: 1 = agent win, 0 = agent loss, -1 = draw.
        self.episode_reward_winner_pairs = deque(maxlen=200)
        
        # FULL TRAINING DURATION TRACKING
        self.all_episode_rewards = []    # Complete reward history
        self.all_episode_wins = []       # Complete win/loss history
        self.all_episode_lengths = []    # Complete episode length history
        
        # Per-snapshot self-play win rate tracking (label -> history list)
        self._selfplay_wins: Dict[str, List[float]] = {}

        # Episode tracking
        self.episode_count = initial_episode_count
        self.step_count = initial_step_count
        # Troncatures : episodes coupes par le garde anti-runaway du moteur (V11 §0.61).
        # Le COMPTE comme la TRACE appartiennent a ai/truncation_log.py, parce que le mode
        # « eval seule » doit compter sans construire de tracker. Ce qui reste ici, c'est la
        # COURBE — la seule part qui soit une metrique TensorBoard.
        self.truncation_log = TruncationLog(self.log_dir)
        

        # L'accumulateur self.position_scores occupait cette place, avec log_position_score et
        # les deux courbes qu'il alimentait (game_tactical/avg_position_score,
        # combat/a_position_score). Il n'a plus de producteur depuis le commit 329d140e
        # "move reward deleted" (2026-02-01), qui a supprime la recompense de mouvement basee
        # sur calculate_position_score, la cle position_score du reward_breakdown et 17 lignes
        # de Documentation/Reference/training/metriques.md. Le dernier appelant (ai/training_callbacks.py) est
        # tombe a son tour. Suppression cote produit deja actee : rien a rebrancher.

        # NEW: tour_de_jeu.md compliance tracking
        self.compliance_data = {
            'units_per_step': [],
            'phase_end_reasons': [],
            'tracking_violations': []
        }
        
        # NEW: Reward mapper effectiveness
        self.reward_mapper_stats = {
            'shooting_priority_correct': 0,
            'shooting_priority_total': 0,
            'movement_tactical_bonuses': 0,
            'movement_actions': 0,
            'mapper_failures': 0
        }
        
        # `self.phase_stats` occupait cette place, accumule par `log_phase_performance` (partie
        # avec elle). Les taux de participation par phase se calculent desormais sur les
        # compteurs que le moteur tire d'`action_logs`, dans `log_tactical_metrics`.

        # NEW: Combat effectiveness metrics (per RL_TRAINING_ROADMAP.md)
        # These metrics tell you if the agent learns combat properly.
        # `shoot_kills` / `melee_kills` / `charge_successes` ont vecu ici, incrementes par
        # `log_combat_kill` depuis le callback. Les deux premiers n'avaient plus aucun appelant
        # (les kills viennent d'`action_logs` via log_tactical_metrics) ; le troisieme nourrissait
        # `combat/c_charge_successes`, remplace par le couple 02_combat/m_+n_ compte cote MOTEUR
        # sur la meme source que tous les autres compteurs de combat. Le chemin callback est
        # celui qui avait deja produit le defaut « charges du BOT comptees sous le drapeau de
        # l'agent » (cf. tests/unit/ai/test_wrapper_agent_step_info.py) : une mesure de jeu
        # reconstruite depuis les `info` d'un step gym ne peut pas savoir de qui elle parle.
        self.combat_effectiveness = {
            'victory_points_cumulative': 0.0  # Cumulative victory points at episode end
        }

        # Rolling history for smoothed combat metrics. Ne restent ici que les series a fenetre
        # NON standard : les kills et VALUE par phase, tous lisses sur 500 comme le reste du
        # dashboard, sont passes a `_game_history` / `_emit_game`, qui fait exactement le
        # meme append + fenetre + moyenne — deux mecaniques de lissage identiques cote a cote
        # obligeaient chaque nouvelle courbe a choisir entre elles sans raison.
        self.combat_history = {
            'victory_points_cumulative': []
        }
        
        # NEW: Hyperparameter tracking for PPO tuning
        self.hyperparameter_tracking = {
            'learning_rates': [],
            'entropy_losses': [],
            'policy_losses': [],
            'value_losses': [],
            'clip_fractions': [],
            'approx_kls': [],
            'explained_variances': []  # For tuning dashboard
        }
        
        # NEW: Gradient norm tracking for 00_critical/ dashboard
        self.latest_gradient_norm = None
        
        # NEW: Bot evaluation combined score for 00_critical/ dashboard
        self.bot_eval_combined = None

        # Phase 2 : metriques zone-intent, fenetre GLISSANTE de ZONE_INTENT_WINDOW_EPISODES
        # episodes, loggee a CHAQUE fin d'episode comme toutes les autres courbes 00_critical.
        #
        # `_zone_steps_since_episode_end` accumule les free steps ecoulés entre deux fins
        # d'episode, toutes instances d'environnement confondues. C'est volontaire : le tracker
        # est unique et recoit n_envs episodes entrelaces, donc AUCUN free step n'est
        # attribuable a un episode precis. Seul le ratio steps/episodes sur une fenetre a un
        # sens ; une lecture point-par-point de cette courbe n'en a jamais eu.
        #
        # La table de contingence controle x intent suit la meme fenetre, une entree par episode
        # ecoule. Elle sert a I(intent ; controle) : 0 bit = le choix d'intent est independant de
        # l'etat du plateau, donc la tete zone-intent n'a rien appris.
        self._reset_zone_intent_state()

        # Unit-rule forcing instrumentation (episode exposure + bot-eval impact)
        self.forcing_tracking = {
            'episodes_total': 0,
            'episodes_with_forced_unit': 0,
            'forced_unit_instances_total': 0,
            'per_unit_episode_counts': {},   # unit_name -> episodes where present
            'per_unit_instance_counts': {},  # unit_name -> total instances
            'baseline_combined': None,       # first combined after forcing exposure starts
            'baseline_worst_bot': None,      # first worst_bot_score after forcing exposure starts
        }

        # Abilities rule usage — compteurs cumulés et exposition (voir log_abilities_metrics).
        # Clé "total_episodes" : dénominateur commun aux deux taux.
        # Clé "counts" : utilisations cumulées par épisode (numérateur du mean).
        # Clé "exposures" : épisodes où la règle était dans le roster (numérateur du taux).
        self._abilities_tracking: Dict[str, Any] = {
            'total_episodes': 0,
            'counts': defaultdict(int),    # rule_side -> int, cumulé
            'exposures': defaultdict(int), # rule_side -> int, cumulé
        }



        # Rolling histories for 01_VP/ + 02_combat/ smoothing (window=500)
        self._game_history: Dict[str, List[float]] = {k: [] for k in self.GAME_HISTORY_KEYS}

        # Ventilation par mode de deploiement (cf. DEPLOY_SPLIT_SERIES). Un historique PAR mode :
        # la fenetre de lissage compte donc PERF_WINDOW episodes DE CE MODE, et les deux courbes
        # n'ont pas le meme axe temporel. C'est voulu — une fenetre raccourcie pour le mode rare
        # rendrait les deux series non comparables entre elles, ce qui est pire que le decalage.
        self._deploy_history: Dict[str, Dict[str, List[float]]] = {
            series: {mode: [] for mode in self.DEPLOY_MODES}
            for series in self.DEPLOY_SPLIT_SERIES
        }
        #: 1.0 par episode en deploiement actif, 0.0 en fixe. Moyenne glissante = part reelle
        #: d'episodes actifs, seule lecture qui permette d'interpreter l'ecart entre les deux
        #: courbes de chaque serie.
        self._deploy_active_flags: List[float] = []
        #: Mode de l'episode en cours de log, pose en tete de `log_episode_end` AVANT toute
        #: emission. None = scheduler inactif -> aucune courbe ventilee n'est ecrite (pas de
        #: bucket par defaut qui melangerait des episodes hors perimetre).
        self._episode_deploy_mode: Optional[str] = None
        
        # `self.episode_tactical_data` (total_actions / invalid_actions / valid_actions a 0)
        # occupait cette place. Aucun ecrivain : les compteurs d'actions vivent dans
        # MetricsCollectionCallback, qui les passe a log_tactical_metrics par argument. Le seul
        # lecteur etait le second ecrivain de game_critical/invalid_action_rate dans
        # log_critical_dashboard : total_actions valant toujours 0, il ecrivait un 0.0 constant
        # a CHAQUE episode sur le meme tag que le vrai calcul (log_tactical_metrics), soit
        # 100 000 points pour 50 000 episodes et une courbe alternant valeur reelle / zero.
        # Supprime avec son unique lecteur.

        # Seat-aware tracking (controlled player can be P1 or P2 per episode)
        self.seat_aware = {
            'episodes_agent_p1': 0,
            'episodes_agent_p2': 0,
            'wins_agent_p1': 0.0,
            'wins_agent_p2': 0.0,
        }
        
        if show_banner:
            print(f"✅ Metrics tracker initialized for {agent_key} -> {self.log_dir}")
            print(f"📊 Metric System:")
            print(f"   🎯 00_critical/ - Essential hyperparameter tuning metrics")
            print(f"   🎮 game_critical/ (5) - Core gameplay indicators")
            print(f"   ⚙️  training_critical/ (6) - PPO algorithm health")
            print(f"   💡 TIP: Start with 00_critical/ - everything you need for tuning")
    
    def _setup_custom_scalars_layout(self) -> None:
        """Register Custom Scalars dashboard layout in TensorBoard (called once at init)."""
        layout = {
            "00_critical + Seuils": {
                "g_explained_variance": ["Multiline", [
                    "00_critical/g_explained_variance",
                    "thresholds/explained_variance_min",
                ]],
                "h_clip_fraction": ["Multiline", [
                    "00_critical/h_clip_fraction",
                    "thresholds/clip_fraction_min",
                    "thresholds/clip_fraction_max",
                    "thresholds/clip_fraction_warn",
                ]],
                "i_approx_kl": ["Multiline", [
                    "00_critical/i_approx_kl",
                    "thresholds/kl_min",
                    "thresholds/kl_max",
                ]],
                "j_entropy_loss": ["Multiline", [
                    "00_critical/j_entropy_loss",
                    "thresholds/entropy_target_min",
                    "thresholds/entropy_target_max",
                ]],
            }
        }
        self.writer.add_custom_scalars(layout)

    def _log_thresholds(self, step: int) -> None:
        """Log constant threshold reference lines for 00_critical metrics."""
        self.writer.add_scalar("thresholds/explained_variance_min", 0.30, step)
        self.writer.add_scalar("thresholds/clip_fraction_min", 0.10, step)
        self.writer.add_scalar("thresholds/clip_fraction_max", 0.30, step)
        self.writer.add_scalar("thresholds/clip_fraction_warn", 0.40, step)
        self.writer.add_scalar("thresholds/kl_min", 0.005, step)
        self.writer.add_scalar("thresholds/kl_max", 0.020, step)
        self.writer.add_scalar("thresholds/entropy_target_min", -2.0, step)
        self.writer.add_scalar("thresholds/entropy_target_max", -0.5, step)

    @property
    def truncation_counts(self) -> Dict[str, "Counter[str]"]:
        """Compte des troncatures, ventile par portee puis par raison (cf. TruncationLog)."""
        return self.truncation_log.counts

    def _emit_truncation_curve(self) -> None:
        """Courbe `00_critical/t_truncated_episodes` — emise a CHAQUE fin d'episode.

        Ce qu'un tableau de bord doit dire ici, c'est « ce nombre doit valoir 0 ». Emise
        seulement quand une troncature arrive, la courbe etait absente du cas nominal, donc
        indiscernable d'une metrique jamais branchee. Comme toutes les autres courbes
        `00_critical/`, elle porte un point par episode.

        Portee ENTRAINEMENT seule : l'abscisse est `episode_count`, qui ne compte que ces
        episodes-la. Le compte d'eval vit dans le bilan de fin de run, pas sur cet axe.

        Le cumul est celui de CE run, pas du dossier : la remise a zero d'un `--append` se lit
        comme ce qu'elle est, un nouveau run. L'historique inter-runs, lui, est dans
        `truncations.jsonl`, dont chaque ligne porte son `run`.
        """
        self.writer.add_scalar(
            '00_critical/t_truncated_episodes',
            sum(self.truncation_counts["training"].values()),
            self.episode_count,
        )

    def log_truncated_episode(self, reason: str, payload: Dict[str, Any]) -> None:
        """Episode d'ENTRAINEMENT coupe par le garde anti-runaway (cf. ai/truncation_log.py).

        `episode_count` avance : c'est ce compteur qui part dans `_run_state.json`, et le run,
        lui, s'arrete sur la somme des `dones` — troncatures comprises. Ne pas l'incrementer
        faisait reprendre la rampe de deploiement plus bas qu'elle n'etait arrivee.
        Les courbes de reward et de longueur, elles, ne recoivent rien : l'episode n'a pas fini.

        La courbe `00_critical/` reste unique, toutes raisons confondues.
        """
        self.episode_count += 1
        self.truncation_log.record("training", reason, payload)
        self._emit_truncation_curve()

    def log_eval_truncations(self, entries: Sequence[Dict[str, Any]]) -> None:
        """Troncatures relevees pendant une EVALUATION (gating ou holdout final).

        Elles arrivent en LOT : l'eval tourne dans des process workers et ne remonte qu'a la fin
        de la campagne. Sans cette route, une boucle qui ne se reproduit qu'en eval
        (`deterministic=True`, rosters du holdout) etait invisible — le moteur pose `winner = -1`
        sur une troncature, donc elle se comptait en NUL et le bilan affichait « 0 troncature ».
        Un feu vert faux est pire que pas de bilan.

        `episode_count` n'avance PAS : un episode d'eval n'est pas un episode joue par le modele
        en apprentissage, et ce compteur est celui qui est persiste dans `_run_state.json`.
        """
        self.truncation_log.record_eval_batch(entries)

    def truncation_summary_lines(self) -> List[str]:
        """Bilan de fin de run. Seule facade : le compte et le journal restent internes."""
        return self.truncation_log.summary_lines()

    def log_episode_end(self, episode_data: Dict[str, Any]):
        """Log core episode metrics - reward, win rate, and episode length"""
        self.episode_count += 1
        self._emit_truncation_curve()

        # Extract data
        total_reward = require_key(episode_data, 'total_reward')
        winner = require_key(episode_data, 'winner')
        episode_length = require_key(episode_data, 'episode_length')
        controlled_player = int(require_key(episode_data, 'controlled_player'))

        # Mode de deploiement de l'episode, pose AVANT toute emission : `_emit_game` le lit
        # pendant `log_tactical_metrics`, appele juste apres cette methode par le callback.
        deployment_mode = require_key(episode_data, 'deployment_mode')
        if deployment_mode is not None and deployment_mode not in self.DEPLOY_MODES:
            raise ValueError(
                f"episode_data['deployment_mode'] must be one of {self.DEPLOY_MODES} or None "
                f"(got {deployment_mode!r})"
            )
        self._episode_deploy_mode = deployment_mode
        if deployment_mode is not None:
            self._deploy_active_flags.append(1.0 if deployment_mode == 'active' else 0.0)
            if len(self._deploy_active_flags) > self.PERF_WINDOW:
                self._deploy_active_flags.pop(0)
            self._emit_windowed(
                '00_critical/s_deploy_active_share', self._deploy_active_flags
            )

        # GAME CRITICAL: Episode reward - Individual episode rewards
        self.writer.add_scalar('game_critical/episode_reward', total_reward, self.episode_count)
        self.all_episode_rewards.append(total_reward)
        self._emit_deploy_split('reward', total_reward)

        # GAME CRITICAL: Win rate - Cumulative win rate (FULL DURATION)
        if winner is not None:
            agent_won = 1.0 if winner == controlled_player else 0.0
            self.all_episode_wins.append(agent_won)
            self.win_rate_window.append(agent_won)
            self._emit_deploy_split('win', agent_won)
            if winner == DRAW_WINNER:
                outcome_flag = -1
            elif winner == controlled_player:
                outcome_flag = 1
            else:
                outcome_flag = 0
            self.episode_reward_winner_pairs.append((total_reward, outcome_flag))
            
            # Calculate cumulative win rate over ENTIRE training
            cumulative_win_rate = float(np.mean(self.all_episode_wins))
            self.writer.add_scalar('game_critical/win_rate_overall', cumulative_win_rate, self.episode_count)
            
            # GAME CRITICAL: Rolling win rate - PRIMARY METRIC
            self._emit_windowed('game_critical/win_rate', self.all_episode_wins)

            # SEAT-AWARE: cumulative win rates by controlled seat + global
            if controlled_player == 1:
                self.seat_aware['episodes_agent_p1'] += 1
                self.seat_aware['wins_agent_p1'] += agent_won
            elif controlled_player == 2:
                self.seat_aware['episodes_agent_p2'] += 1
                self.seat_aware['wins_agent_p2'] += agent_won
            else:
                raise ValueError(f"controlled_player must be 1 or 2 (got {controlled_player})")

            total_seat_episodes = (
                self.seat_aware['episodes_agent_p1'] + self.seat_aware['episodes_agent_p2']
            )
            total_seat_wins = self.seat_aware['wins_agent_p1'] + self.seat_aware['wins_agent_p2']
            if total_seat_episodes > 0:
                self.writer.add_scalar(
                    'seat_aware/winrate_global',
                    float(total_seat_wins / total_seat_episodes),
                    self.episode_count
                )
            if self.seat_aware['episodes_agent_p1'] > 0:
                self.writer.add_scalar(
                    'seat_aware/winrate_agent_p1',
                    float(self.seat_aware['wins_agent_p1'] / self.seat_aware['episodes_agent_p1']),
                    self.episode_count
                )
            if self.seat_aware['episodes_agent_p2'] > 0:
                self.writer.add_scalar(
                    'seat_aware/winrate_agent_p2',
                    float(self.seat_aware['wins_agent_p2'] / self.seat_aware['episodes_agent_p2']),
                    self.episode_count
                )
            self.writer.add_scalar(
                'seat_aware/episodes_agent_p1',
                float(self.seat_aware['episodes_agent_p1']),
                self.episode_count
            )
            self.writer.add_scalar(
                'seat_aware/episodes_agent_p2',
                float(self.seat_aware['episodes_agent_p2']),
                self.episode_count
            )
        
        # GAME CRITICAL: Episode length - Episode duration stability
        if episode_length > 0:
            self.writer.add_scalar('game_critical/episode_length', episode_length, self.episode_count)
            self.all_episode_lengths.append(episode_length)  # Track for tuning dashboard
        
        # CRITICAL: Compute and log phase performance metrics at episode end
        self.compute_and_log_phase_metrics()
        
        # NEW: Log critical dashboard (10 essential hyperparameter tuning metrics)
        self.log_critical_dashboard()
        
        self.writer.flush()
    
    @staticmethod
    def _push_window(h: List[float], value: float, window: int) -> List[float]:
        """Ajoute `value` dans `h` et tronque a `window` elements ; retourne `h`."""
        h.append(value)
        if len(h) > window:
            h.pop(0)
        return h

    def _game_push(self, key: str, value: float) -> List[float]:
        """Ajoute une valeur a l'historique de `key` et retourne l'historique tronque."""
        return self._push_window(self._game_history[key], value, self.PERF_WINDOW)

    @staticmethod
    def _window_mean(values: Sequence[float], window: int) -> Optional[float]:
        """Moyenne des `window` dernieres valeurs, ou None tant que la fenetre n'est pas pleine.

        Le None n'est pas une valeur manquante a remplacer : c'est le refus d'emettre un point
        qui n'aurait pas le meme sens que les suivants (cf. PERF_WINDOW).
        """
        if len(values) < window:
            return None
        return float(np.mean(values[-window:]))

    def _emit_windowed(self, tag: str, values: Sequence[float]) -> None:
        """Emet la mesure sur ses DEUX fenetres : `tag` (fond) et `tag_<N>ep` (reactif).

        Toutes les courbes de performance partagent le MEME couple de fenetres. Une seule y a
        eu sa fenetre en dur (un litteral de 200) : des que la fenetre reactive du config l'a
        depasse, elle a perdu son doublon sans que rien ne le signale — une fenetre en dur
        dans un reglage devenu configurable ne peut que diverger de lui.
        """
        window = self.PERF_WINDOW
        slow = self._window_mean(values, window)
        if slow is not None:
            self.writer.add_scalar(tag, slow, self.episode_count)
        fast_window = min(self.PERF_WINDOW_FAST, window)
        if fast_window < window:
            fast = self._window_mean(values, fast_window)
            if fast is not None:
                self.writer.add_scalar(f"{tag}_{fast_window}ep", fast, self.episode_count)

    def _emit_deploy_split(self, series: str, value: float) -> None:
        """Accumule `value` dans l'historique du mode courant et emet la courbe ventilee.

        Ne fait RIEN quand le mode est None : le scheduler est inactif (profil sans rampe, ou
        scenario hors split training), donc l'episode n'appartient a aucune des deux populations
        comparees. L'imputer d'office a `fixed` — le mode que le JSON applique alors — melerait
        des episodes qu'aucun tirage n'a places la, et l'ecart mesure ne voudrait plus rien dire.
        """
        mode = self._episode_deploy_mode
        if mode is None:
            return
        if mode not in self._deploy_history[series]:
            raise ValueError(
                f"deployment_mode must be one of {self.DEPLOY_MODES} or None (got {mode!r})"
            )
        history = self._deploy_history[series][mode]
        self._emit_windowed(
            f"{self.DEPLOY_SPLIT_SERIES[series]}_{mode}",
            self._push_window(history, float(value), self.PERF_WINDOW),
        )

    def _emit_game(self, tag: str, key: str, value: float) -> None:
        """Accumule `value` dans l'historique de `key` puis emet les deux courbes de `tag`."""
        self._emit_windowed(tag, self._game_push(key, value))
        # Point de branchement UNIQUE de la ventilation par mode de deploiement : toute courbe
        # de DEPLOY_SPLIT_GAME_KEYS est ventilee ici, au moment ou sa valeur est calculee.
        # L'emettre depuis `log_critical_dashboard` la decalerait d'un episode — ce dashboard est
        # appele DEPUIS `log_episode_end`, donc AVANT `log_tactical_metrics` qui produit ces
        # valeurs (cf. l'ordre des deux appels dans MetricsCollectionCallback).
        if key in self.DEPLOY_SPLIT_GAME_KEYS:
            self._emit_deploy_split(self.DEPLOY_SPLIT_GAME_KEYS[key], value)

    def _emit_ratio(self, tag: str, key: str, numerator: float, denominator: float) -> None:
        """Emet un ratio lisse, et RIEN si son denominateur est nul.

        RESERVE aux ratios dont le denominateur est une constante de l'episode (effectif ou
        VALUE de depart) : lisser le rapport par episode n'y perd rien, le denominateur ne
        depend pas de ce qu'a fait l'agent. Un denominateur nul y est un etat de JEU possible
        (aucune unite dans ce camp), pas une erreur : il n'y a rien a mesurer, et un 0.0 emis
        a sa place se lirait comme « l'agent n'a rien detruit ».
        Un ratio dont le denominateur est un RESULTAT d'episode ne passe pas par ici — toute
        garde y ecarte une population entiere et biaise la courbe (cf. a_value_trade_ratio).

        La forme est factorisee parce que l'appariement tag <-> cle d'historique est ce qui se
        casse en silence quand on recopie le bloc : deux courbes se retrouvent alors melangees
        dans la meme fenetre glissante.
        """
        if denominator > 0:
            self._emit_game(tag, key, numerator / denominator)

    def _emit_ratio_of_means(
        self, tag: str, numerator_hist: Sequence[float], denominator_hist: Sequence[float]
    ) -> None:
        """Emet, fenetre par fenetre, le rapport des MOYENNES de deux series deja accumulees.

        RESERVE aux ratios dont le denominateur est un RESULTAT d'episode (pertes subies,
        charges tentees) et non une constante de scenario. Le rapport par episode n'y est pas
        moyennable : il n'existe pas pour les episodes ou le denominateur est nul, et TOUTE
        facon de traiter ces episodes biaise la courbe — les ecarter retire une population
        entiere, y verser un 0.0 compte comme un echec un episode ou rien n'a ete tente.
        Sommer les deux cotes sur la fenetre n'exclut RIEN : chaque episode y pese ce qu'il
        vaut, et le rapport reste defini des que la fenetre contient un seul denominateur non
        nul. Une fenetre entiere a denominateur nul n'a pas de rapport a afficher, pas un 0.
        Le rapport se calcule fenetre par fenetre : prendre celui de la fenetre longue pour la
        courte melangerait deux populations d'episodes.
        """
        windows = [(self.PERF_WINDOW, '')]
        if self.PERF_WINDOW_FAST < self.PERF_WINDOW:
            windows.append((self.PERF_WINDOW_FAST, f'_{self.PERF_WINDOW_FAST}ep'))
        for window, suffix in windows:
            numerator_mean = self._window_mean(numerator_hist, window)
            denominator_mean = self._window_mean(denominator_hist, window)
            if numerator_mean is None or denominator_mean is None or denominator_mean <= 0:
                continue
            self.writer.add_scalar(
                f'{tag}{suffix}', numerator_mean / denominator_mean, self.episode_count
            )

    def log_tactical_metrics(self, tactical_data: Dict[str, Any]):
        """Log tactical performance metrics - combat effectiveness and decision quality.

        TOUTES les cles lues ici sont EXIGEES (`require_key`), jamais gardees par un
        `if <cle> in tactical_data`. Une telle garde ne distingue pas « le moteur ne remplit
        plus cette cle » de « il n'y avait rien a mesurer » : elle eteint la courbe en silence,
        exactement le defaut qui a tenu deux tags muets pendant 50 000 episodes (voir l'en-tete
        de tests/unit/ai/test_metrics_single_writer.py). Le contrat moteur -> tracker est verifie
        sur un episode REEL par tests/unit/engine/test_reserves_metrics.py.
        Les gardes qui restent sont METIER (`> 0`, liste vide) : elles disent qu'il n'y a rien a
        tracer, pas que la donnee manque.
        """

        # GAME TACTICAL: Shooting accuracy - Hit rate
        shots_fired = require_key(tactical_data, 'shots_fired')
        if shots_fired > 0:
            hits = require_key(tactical_data, 'hits')
            accuracy = hits / shots_fired
            self.writer.add_scalar('04_shoot/b_accuracy', accuracy, self.episode_count)
        
        # GAME DETAILED: Damage dealt - Offensive power
        damage_dealt = require_key(tactical_data, 'damage_dealt')
        if damage_dealt > 0:
            self.writer.add_scalar('game_detailed/damage_dealt', damage_dealt, self.episode_count)
        
        # GAME DETAILED: Damage received - Defensive capability
        damage_received = require_key(tactical_data, 'damage_received')
        self.writer.add_scalar('game_detailed/damage_received', damage_received, self.episode_count)
        
        # GAME TACTICAL: Damage efficiency - Trade effectiveness
        if damage_received > 0 and damage_dealt > 0:
            damage_efficiency = damage_dealt / damage_received
            self.writer.add_scalar('02_combat/q_damage_efficiency', damage_efficiency, self.episode_count)
        
        units_lost = require_key(tactical_data, 'units_lost')
        units_killed = require_key(tactical_data, 'units_killed')

        # 0_COMBAT — ratios d'attrition, la MEME mesure a trois granularites (unites,
        # figurines, VALUE) et pour les DEUX camps. Les compteurs bruts ne sont pas
        # comparables d'un roster a l'autre : « 6 figurines tuees » ne dit rien sans
        # l'effectif en face. Le moteur exporte partout le meme couple (perdu, effectif de
        # depart) ; ici on ne fait que diviser.
        # Le compte de kills du journal ne pourrait pas servir de numerateur a c_ : il ignore
        # les retraits hors attaque (hazard, coherence) que d_ compte forcement cote allie, et
        # les deux courbes n'auraient plus la meme base. L'attribution des kills reste sur g_/h_.
        for tag, hist_key, numerator, denominator in (
            ('02_combat/c_models_killed_ratio', 'models_killed_ratio',
             float(require_key(tactical_data, 'models_killed')),
             float(require_key(tactical_data, 'initial_enemy_models'))),
            ('02_combat/d_models_lost_ratio', 'models_lost_ratio',
             float(require_key(tactical_data, 'models_lost')),
             float(require_key(tactical_data, 'initial_ally_models'))),
            ('02_combat/e_value_killed_ratio', 'value_killed_ratio',
             float(require_key(tactical_data, 'enemy_value_destroyed')),
             float(require_key(tactical_data, 'total_enemy_value'))),
            ('02_combat/f_value_lost_ratio', 'value_lost_ratio',
             float(require_key(tactical_data, 'ally_value_lost')),
             float(require_key(tactical_data, 'total_ally_value'))),
            ('02_combat/k_units_killed_ratio', 'units_killed_ratio',
             float(units_killed), float(require_key(tactical_data, 'total_enemy_units'))),
            ('02_combat/l_units_lost_ratio', 'units_lost_ratio',
             float(units_lost), float(require_key(tactical_data, 'total_ally_units'))),
        ):
            self._emit_ratio(tag, hist_key, numerator, denominator)

        # Kill breakdown by phase (from engine action_logs via tactical_data — reliable, per-episode per-env)
        shoot_kills = int(require_key(tactical_data, 'shoot_kills'))
        melee_kills = int(require_key(tactical_data, 'melee_kills'))
        self._emit_game('02_combat/g_shoot_model_kills', 'shoot_kills', shoot_kills)
        self._emit_game('02_combat/h_melee_model_kills', 'melee_kills', melee_kills)
        kill_rewards_ep = (shoot_kills + melee_kills) * self.reward_kill_target
        self._emit_game('02_combat/b_kill_rewards', 'kill_rewards', kill_rewards_ep)

        # VALUE des figurines tuees, ventilee par phase : g_/h_ comptent des tetes, i_/j_
        # comptent ce qu'elles valaient. Les deux ensemble separent l'agent qui fauche des
        # figurines a 4 points de celui qui abat le monstre a 120 — un seul des deux
        # chiffres ne le dit pas.
        shoot_value = float(require_key(tactical_data, 'shoot_value_killed'))
        melee_value = float(require_key(tactical_data, 'melee_value_killed'))
        self._emit_game('02_combat/i_shoot_value_killed', 'shoot_value_killed', shoot_value)
        self._emit_game('02_combat/j_melee_value_killed', 'melee_value_killed', melee_value)

        # CHARGES — le volume tente et le taux de reussite, POUR LES DEUX CAMPS.
        #
        # Ce que ce couple separe, et qu'aucune autre courbe ne separait : un agent qui ne va
        # jamais au contact parce qu'il ne DECLARE pas de charge, d'un agent qui en declare
        # autant que l'adversaire mais les RATE (2D6 insuffisant, donc charges lancees de trop
        # loin). Les kills de melee, seuls, confondent les deux — ils sont bas dans les deux cas.
        # La colonne adverse est la reference sans laquelle un taux brut ne se lit pas : le
        # meme 40% est bon ou mauvais selon ce que le scenario permet.
        #
        # Le TAUX passe par `_emit_ratio_of_means` et non `_emit_ratio` : son denominateur est
        # le nombre de tentatives de l'episode, un resultat, pas une constante de scenario
        # (un episode sans aucune charge tentee n'a pas de taux — ni a exclure, ni a compter 0).
        charge_attempts = float(require_key(tactical_data, 'charge_attempts'))
        charge_attempts_bot = float(require_key(tactical_data, 'charge_attempts_opponent'))
        self._emit_game('02_combat/m_charge_attempts', 'charge_attempts', charge_attempts)
        self._emit_game('02_combat/o_charge_attempts_bot', 'charge_attempts_bot', charge_attempts_bot)
        successes_hist = self._game_push(
            'charge_successes', float(require_key(tactical_data, 'charge_successes'))
        )
        successes_bot_hist = self._game_push(
            'charge_successes_bot', float(require_key(tactical_data, 'charge_successes_opponent'))
        )
        self._emit_ratio_of_means(
            '02_combat/n_charge_success_rate',
            successes_hist,
            self._game_history['charge_attempts'],
        )
        self._emit_ratio_of_means(
            '02_combat/p_charge_success_rate_bot',
            successes_bot_hist,
            self._game_history['charge_attempts_bot'],
        )

        # PARTICIPATION PAR PHASE — la part des occasions saisies, phase par phase.
        #
        # Ces trois courbes ont ete emises par `log_phase_performance`, methode restee sans
        # aucun appelant de production : elles n'existaient dans aucun run (verifie sur les
        # 124 tags d'un run de 50 000 episodes). Elles sont recomptees cote MOTEUR sur
        # `action_logs`, comme tout le reste de ce dashboard — le callback deduisait la phase
        # et le camp de l'`info` d'un step gym, qui en enchaine plusieurs.
        #
        # Meme traitement de ratio que les charges, et pour la meme raison : le denominateur
        # (les occasions d'agir) est un RESULTAT d'episode. Un episode sans une seule
        # activation de tir n'a pas de taux de participation — ni a ecarter, ni a compter 0.
        #
        # La CHARGE n'a volontairement pas son taux de participation : cf. w40k_core, son
        # denominateur compterait les fois ou le moteur a expose la phase, pas les occasions de
        # charger. `m_charge_attempts` et sa colonne adverse repondent sans cette ambiguite.
        move_actions = float(require_key(tactical_data, 'move_actions'))
        move_waits = float(require_key(tactical_data, 'move_waits'))
        shoot_activations = float(require_key(tactical_data, 'shoot_activations'))
        move_hist = self._game_push('move_actions', move_actions)
        flee_hist = self._game_push('move_flees', float(require_key(tactical_data, 'move_flees')))
        move_advances_hist = self._game_push('move_advances', float(require_key(tactical_data, 'move_advances')))
        move_opportunities = self._game_push('move_opportunities', move_actions + move_waits)
        shoot_hist = self._game_push('shoot_activations', shoot_activations)
        shoot_opportunities = self._game_push(
            'shoot_opportunities',
            shoot_activations + float(require_key(tactical_data, 'shoot_waits')),
        )
        # 03_move/ : participation (unités ayant bougé / occasions), advance rate, flee rate.
        # `move_actions` est le dénominateur d'advance_rate et flee_rate : seules les activations
        # réelles peuvent être une advance ou une fuite — une occasion ratée (wait) ne l'est pas.
        self._emit_ratio_of_means('03_move/a_participation', move_hist, move_opportunities)
        self._emit_ratio_of_means('03_move/b_advance_rate', move_advances_hist, move_hist)
        self._emit_ratio_of_means('03_move/c_flee_rate', flee_hist, move_hist)
        # 04_shoot/ : participation (unités avec cibles ayant tiré), précision.
        # `shoot_waits` ne compte que les unités qui avaient des cibles valides (LoS inclus) mais
        # ont passé leur activation — le taux est donc déjà conditionnel au LoS sans compteur dédié.
        self._emit_ratio_of_means('04_shoot/a_participation', shoot_hist, shoot_opportunities)

        # COMBAT VALUE METRICS: Episode-level attrition in VALUE points.
        enemy_value_destroyed = float(require_key(tactical_data, 'enemy_value_destroyed'))
        ally_value_lost = float(require_key(tactical_data, 'ally_value_lost'))
        self.writer.add_scalar('combat/f_value_destroyed', enemy_value_destroyed, self.episode_count)
        self.writer.add_scalar('combat/g_value_lost', ally_value_lost, self.episode_count)
        # Un SEUL tag pour cette mesure. Elle en a porte trois : `combat/h_value_trade_ratio`
        # (historique) et `0_game/h_value_trade_ratio` (reecrit a un autre instant par
        # log_critical_dashboard, donc deux series entrelacees) ont ete supprimes avec le
        # namespace 0_game/, comme tous les autres tags de la refonte : deplaces, pas dupliques.
        # Rapport des MOYENNES et non moyenne des rapports : cf. `_emit_ratio_of_means`.
        self._emit_ratio_of_means(
            '02_combat/a_value_trade_ratio',
            self._game_push('value_destroyed', enemy_value_destroyed),
            self._game_push('value_lost', ally_value_lost),
        )
        
        # GAME CRITICAL: Unit trade ratio (killed/lost) - Core success metric
        if units_lost > 0 and units_killed > 0:
            trade_ratio = units_killed / units_lost
            self.writer.add_scalar('game_critical/units_killed_vs_lost_ratio', trade_ratio, self.episode_count)
        
        # GAME CRITICAL: Invalid action rate - tour_de_jeu.md compliance
        valid_actions = require_key(tactical_data, 'valid_actions')
        invalid_actions = require_key(tactical_data, 'invalid_actions')
        total_actions = valid_actions + invalid_actions
        
        if total_actions > 0:
            invalid_rate = invalid_actions / total_actions
            self.writer.add_scalar('game_critical/invalid_action_rate', invalid_rate, self.episode_count)
            # `game_tactical/action_efficiency` vivait ici et valait `valid / total`, c'est-à-dire
            # exactement `1 - invalid_rate` — même dénominateur, même garde, aucune information
            # propre. Sur le run du 2026-08-11 elle était plate à 1.0 sur les 50 001 épisodes,
            # comme son complément à 0.0. Supprimée et NON remplacée : ce que ce couple mesure se
            # lit sur `invalid_action_rate`, la seule des deux dont le zéro est la bonne nouvelle.

        # USAGE PAR FAMILLE D'ACTION — la part de chaque DECISION dans ce que l'agent joue.
        #
        # Ce que ces courbes repondent, et qu'aucune autre ne repondait : « l'agent utilise-t-il
        # cette dimension d'action ? ». Une famille a 0 en permanence est une decision MORTE
        # (mal masquee, mal observee, ou jamais preferee) ; une famille a 1 est une decision
        # degeneree. Les deux sont des defauts que le win-rate ne distingue pas d'un agent
        # simplement faible — et qui, sans ces courbes, ne se voient qu'en fin de run.
        #
        # C'est aussi ce qui rend un lot de tranches P3 diagnosticable en UN SEUL run : chaque
        # decision ajoutee a sa propre courbe, donc sa propre signature de panne.
        family_counts = require_key(tactical_data, 'action_family_counts')
        family_total = sum(family_counts.values())
        if family_total > 0:
            for family, count in family_counts.items():
                self.writer.add_scalar(
                    f'actions/share_{family}', count / family_total, self.episode_count
                )

        # COUT DU CACHE DE SCORING DU DEPLOIEMENT (V11 §0.46 axe A).
        #
        # Ces quatre issues n'etaient tracees que sous `debug_mode`, donc jamais mesurees sur un
        # run reel. Elles portent un COUT : un `full_build` reconstruit toutes les expositions
        # LoS de la zone de deploiement, un `incremental` ne touche que le delta d'une pose.
        #
        # `full_build_rate` est la courbe a surveiller — si elle monte vers 1.0, le cache ne
        # sert plus a rien et le deploiement repaie son scoring complet a chaque consultation.
        # Le denominateur est un RESULTAT d'episode (un episode en placement fixe ne consulte
        # jamais ce cache), d'ou le rapport des moyennes et non la moyenne des rapports : cf.
        # `_emit_ratio_of_means`, une fenetre sans aucune consultation n'a pas de taux, pas un 0.
        cache_counts = require_key(tactical_data, 'deployment_cache_counts')
        cache_lookups = float(sum(cache_counts.values()))
        # Somme des issues DECLAREES comme reconstructions, jamais `total - incremental` : une
        # cinquieme issue qui ne serait pas un rebuild (« cache servi tel quel ») serait comptee
        # comme tel par la soustraction, sur une courbe publiee que personne ne re-derive.
        cache_full_builds = float(sum(
            require_key(cache_counts, outcome)
            for outcome in ActionDecoder.FULL_BUILD_CACHE_OUTCOMES
        ))
        lookups_hist = self._game_push('deploy_cache_lookups', cache_lookups)
        full_builds_hist = self._game_push('deploy_cache_full_builds', cache_full_builds)
        failed_hist = self._game_push(
            'deploy_cache_incremental_failed',
            float(require_key(cache_counts, 'full_build_incremental_failed')),
        )
        self._emit_ratio_of_means('perf/a_deploy_cache_full_build_rate', full_builds_hist, lookups_hist)
        # Le rebuild qui a PAYE l'incremental avant de le jeter : le seul des trois chemins de
        # reconstruction qui soit du travail purement perdu. Rapporte aux consultations, pas aux
        # rebuilds — c'est sa part du cout total qui compte, pas sa part des echecs.
        self._emit_ratio_of_means('perf/b_deploy_cache_wasted_rate', failed_hist, lookups_hist)
        # Sans garde sur l'episode courant : `_emit_windowed` publie la moyenne de la FENETRE, qui
        # contient de toute facon les episodes en placement fixe (0 consultation). Conditionner
        # trouait la courbe un episode sur deux et faisait croire a une mesure absente.
        self._emit_windowed('perf/c_deploy_cache_lookups', lookups_hist)

        # 0_GAME: VP differential and objective samples
        vp_diff = float(require_key(tactical_data, 'victory_points_diff_controlled_minus_opponent'))
        self._emit_game('01_VP/a_vp_diff', 'vp_diff', vp_diff)

        # Objectifs tenus : echantillonnes par tour marque cote moteur
        # (GameStateManager._sample_objectives_held). Cles EXIGEES, jamais `.get()` : le garde
        # `if isinstance(list) and samples` qui les protegeait a tenu ces deux courbes muettes
        # pendant 50 000 episodes sans jamais le signaler.
        # Une liste vide reste un cas de JEU legitime (episode termine avant le premier tour
        # marquant, scenario sans objectif primaire) : rien a logguer, mais l'absence de cle
        # est un etat corrompu et doit lever.
        samples = require_key(tactical_data, 'controlled_objective_samples')
        opp_samples = require_key(tactical_data, 'opponent_objective_samples')
        if samples:
            self._emit_game('01_VP/e_objectives_held', 'objectives_held', float(np.mean(samples)))
        if samples and opp_samples:
            diff = float(np.mean(samples)) - float(np.mean(opp_samples))
            self._emit_game('01_VP/d_objectives_held_diff', 'objectives_held_diff', diff)

            # f_obj_rewards : le montant verse par
            # RewardCalculator._calculate_objective_reward_per_turn sur l'episode. Il vaut
            # `facteur x VP marques` PAR CONSTRUCTION, donc il se LIT sur les VP au lieu de se
            # rejouer : cette ligne rejouait la formule du versement sur les echantillons, un
            # miroir qui redevenait faux a chaque changement de forme du reward (c'est
            # exactement ce qui vient d'arriver au passage lineaire -> escalier).
            # Limite connue, celle du versement lui-meme : au round 5, le SECOND joueur marque a
            # la fin de la phase fight alors que le reward est calcule a la frontiere
            # command -> move — les deux comptages peuvent differer sur ce seul marquage.
            obj_rewards_ep = self.objective_reward_factor * float(
                require_key(tactical_data, 'victory_points_controlled_episode')
            )
            self._emit_game('01_VP/f_obj_rewards', 'obj_rewards', obj_rewards_ep)

        self._emit_game(
            '01_VP/c_vp_bot',
            'vp_bot',
            float(require_key(tactical_data, 'victory_points_opponent_episode')),
        )

        # FORCING METRICS: Exposure of units with configured UNIT_RULES.
        forced_episode_has_controlled = int(require_key(tactical_data, 'forced_unit_episode_has_controlled'))
        forced_unit_instances_controlled = int(require_key(tactical_data, 'forced_unit_instances_controlled'))
        forced_unit_counts_controlled = require_key(tactical_data, 'forced_unit_counts_controlled')
        if not isinstance(forced_unit_counts_controlled, dict):
            raise TypeError(
                "tactical_data['forced_unit_counts_controlled'] must be a dict "
                f"(got {type(forced_unit_counts_controlled).__name__})"
            )

        self.forcing_tracking['episodes_total'] += 1
        self.forcing_tracking['forced_unit_instances_total'] += forced_unit_instances_controlled
        if forced_episode_has_controlled not in (0, 1):
            raise ValueError(
                f"forced_unit_episode_has_controlled must be 0 or 1 "
                f"(got {forced_episode_has_controlled})"
            )
        self.forcing_tracking['episodes_with_forced_unit'] += forced_episode_has_controlled

        # Ces trois compteurs viennent d'etre incrementes ci-dessus avec des entiers : pas de
        # cast defensif, il masquerait un jour un compteur devenu flottant au lieu de lever.
        episodes_total = self.forcing_tracking['episodes_total']
        episodes_with_forced = self.forcing_tracking['episodes_with_forced_unit']
        forcing_ratio = episodes_with_forced / episodes_total
        mean_instances = self.forcing_tracking['forced_unit_instances_total'] / episodes_total

        self.writer.add_scalar('forcing/episodes_with_forced_unit_ratio', forcing_ratio, self.episode_count)
        self.writer.add_scalar('forcing/forced_unit_instances_mean', mean_instances, self.episode_count)
        self.writer.add_scalar(
            'forcing/episodes_with_forced_unit',
            float(episodes_with_forced),
            self.episode_count
        )

        per_unit_episode_counts = require_key(self.forcing_tracking, 'per_unit_episode_counts')
        per_unit_instance_counts = require_key(self.forcing_tracking, 'per_unit_instance_counts')
        for unit_name, raw_count in forced_unit_counts_controlled.items():
            unit_count = int(raw_count)
            if unit_count <= 0:
                raise ValueError(
                    f"forced_unit_counts_controlled['{unit_name}'] must be > 0 (got {unit_count})"
                )
            if unit_name not in per_unit_episode_counts:
                per_unit_episode_counts[unit_name] = 0
            if unit_name not in per_unit_instance_counts:
                per_unit_instance_counts[unit_name] = 0
            per_unit_episode_counts[unit_name] = int(per_unit_episode_counts[unit_name]) + 1
            per_unit_instance_counts[unit_name] = int(per_unit_instance_counts[unit_name]) + unit_count

            unit_slug = self._metric_slug(unit_name)
            unit_episode_ratio = per_unit_episode_counts[unit_name] / episodes_total
            unit_instance_mean = per_unit_instance_counts[unit_name] / episodes_total
            self.writer.add_scalar(
                f'forcing/unit_episode_exposure/{unit_slug}',
                unit_episode_ratio,
                self.episode_count
            )
            self.writer.add_scalar(
                f'forcing/unit_instance_mean/{unit_slug}',
                unit_instance_mean,
                self.episode_count
            )
    
        # Réserves stratégiques (20.01/20.04) — clés garanties par _empty_episode_tactical_data().
        # UNE COURBE PAR CAMP, sur les cinq mesures. `destroyed_turn3` etait publie seul et
        # documente « tous joueurs » alors que le moteur ne comptait que l'agent : la perte de
        # reserves du bot n'existait sur aucune courbe, donc rien ne permettait de verifier ce
        # que son code promet (il arrive des qu'un slot s'ouvre, cf. env_wrappers).
        #
        # `declined` et `no_destination` separent ce que `destroyed_turn3` confond : un slot
        # d'arrivee etait ouvert et l'unite est restee (DECISION), ou le pool etait vide (aucune
        # decision possible). Les lire ENSEMBLE est le seul moyen de savoir si une reserve
        # perdue est un choix ou une impasse geometrique.
        for _metric in (
            'placed', 'deployed', 'destroyed_turn3',
            'ingress_offers', 'ingress_declined', 'ingress_no_destination',
        ):
            for _side in ('agent', 'opponent'):
                self.writer.add_scalar(
                    f'reserves/{_metric}_{_side}',
                    float(require_key(tactical_data, f'reserves_{_metric}_{_side}')),
                    self.episode_count,
                )

        # Distances de CHARGE (11.04), par camp. Ce que la mesure sert : le step.log du
        # 2026-08-11 avait montre 41 % de declarations a >= 9" pour un 2D6 qui n'atteint 9 que
        # 27,8 % du temps, mediane des ratees a 9" contre 5" pour les reussies — mais il avait
        # fallu re-deriver ces distances a la main. Elles sont desormais mesurees a l'instant
        # ou la regle les regarde.
        #
        # Chaque courbe est un RAPPORT DE MOYENNES sur la fenetre glissante, comme
        # `n_charge_success_rate` juste au-dessus et pour la raison que documente
        # `_emit_ratio_of_means` : son denominateur est un RESULTAT d'episode. Un episode sans
        # charge n'a pas de distance moyenne, et toute façon de le traiter isolement biaise la
        # courbe — l'ecarter retire une population, y verser 0.0 le compte comme une charge au
        # contact. Sommer les deux cotes sur la fenetre n'exclut rien.
        #
        # Le VOLUME de charges, lui, n'est pas republie ici : `02_combat/m_charge_attempts` et
        # `o_charge_attempts_bot` le portent deja, et ces courbes-ci se derivent des MEMES
        # lignes de journal. Une seconde courbe du meme compte n'aurait pu que diverger.
        _charge_distance = require_key(tactical_data, 'charge_distance')
        for _side in ('agent', 'opponent'):
            _side_data = require_key(_charge_distance, _side)
            _hist = {
                _measure: self._game_push(
                    f'charge_{_measure}_{_side}', float(require_key(_side_data, _measure))
                )
                for _measure in CHARGE_DISTANCE_MEASURES
            }
            for _name, _num, _den in (
                ('a_nearest_enemy_inches', 'nearest_sum', 'nearest_n'),
                ('b_target_inches', 'target_sum', 'target_n'),
                ('c_target_inches_success', 'success_sum', 'success_n'),
                ('d_target_inches_fail', 'fail_sum', 'fail_n'),
                # DENOMINATEUR = les charges qui ont VISE une cible, pas toutes les tentatives.
                # Une charge declaree qui n'atteint aucune cible (11.02.3) n'a pas de distance :
                # la compter en bas de la fraction sans jamais pouvoir la compter en haut ferait
                # baisser la part a mesure que ces cas se multiplient — soit exactement le
                # phenomene que la courbe existe pour montrer, dilue par lui-meme.
                ('e_declarations_ge9_share', 'long', 'target_n'),
            ):
                self._emit_ratio_of_means(
                    f'05_charge/{_name}_{_side}', _hist[_num], _hist[_den]
                )

        # 06_fight/ : activations de combat par tour.
        # fight_activations = paires (tour, escouade) uniques sur l'épisode, dérivées des logs
        # "combat". final_turn est le tour de terminaison — dénominateur naturel pour normaliser.
        fight_activations_hist = self._game_push(
            'fight_activations', float(require_key(tactical_data, 'fight_activations'))
        )
        final_turn_hist = self._game_push(
            'fight_final_turn', float(require_key(tactical_data, 'final_turn'))
        )
        self._emit_ratio_of_means('06_fight/a_activations_per_turn', fight_activations_hist, final_turn_hist)

    def log_abilities_metrics(self, tactical_data: Dict[str, Any]) -> None:
        """Règles d'unité appliquées — Famille A (action_log) + Famille B (shot_records).

        Deux courbes par règle par camp :
        - `abilities/<rule>_agent` : nombre de déclenchements sur CET épisode (brut, 0 possible).
        - `abilities/<rule>_agent_exposure_rate` : fraction d'épisodes où l'unité possédant la
          règle était dans le roster de l'agent.

        Sans la courbe d'exposition, un zéro sur le compteur ne distingue pas
        « jamais déclenchée » de « jamais dans le roster ».
        """
        counts = require_key(tactical_data, 'abilities_counts')
        exposure = require_key(tactical_data, 'abilities_exposure')

        acc = self._abilities_tracking
        acc['total_episodes'] += 1
        total_eps: int = acc['total_episodes']
        acc_counts: Dict[str, int] = acc['counts']
        acc_exposures: Dict[str, int] = acc['exposures']

        for key, val in counts.items():
            count_int = int(val)
            acc_counts[key] += count_int
            # Courbe brute par épisode : utile pour détecter des pics d'utilisation.
            self.writer.add_scalar(f"abilities/{key}", float(count_int), self.episode_count)

        for key, val in exposure.items():
            exp_int = int(val)
            if exp_int not in (0, 1):
                raise ValueError(
                    f"abilities_exposure['{key}'] doit être 0 ou 1 (reçu {exp_int})"
                )
            acc_exposures[key] += exp_int
            # Taux cumulé d'épisodes où la règle était dans le roster.
            exposure_rate = acc_exposures[key] / total_eps
            self.writer.add_scalar(
                f"abilities/{key}_exposure_rate", exposure_rate, self.episode_count
            )

    def log_training_step(self, step_data: Dict[str, Any]):
        """Log training step metrics - exploration rate and loss"""
        self.step_count += 1
        
        # La courbe training_diagnostic/exploration_rate occupait cette place. exploration_rate
        # est l'epsilon d'une politique epsilon-greedy (DQN) ; le depot n'instancie que
        # MaskablePPO, un actor-critic qui explore par l'entropie de sa politique et n'a pas cet
        # attribut. L'unique producteur de la cle (ai/training_callbacks.py, garde par
        # hasattr(model, 'exploration_rate')) n'etait donc jamais entre, et a ete supprime.

        # TRAINING DETAILED: General loss - Neural network training loss
        if 'loss' in step_data:
            self.writer.add_scalar('training_detailed/loss', step_data['loss'], self.step_count)
        
        # TRAINING DIAGNOSTIC: Learning rate tracking
        if 'learning_rate' in step_data:
            self.writer.add_scalar('training_diagnostic/learning_rate', step_data['learning_rate'], self.step_count)
    
    def log_reward_decomposition(self, reward_data: Dict[str, Any]):
        """Log reward decomposition for debugging reward engineering.

        METRIQUES (6):
        - reward/base_actions_total
        - reward/result_bonuses_total
        - reward/objective_total
        - reward/situational_total
        - reward/penalties_total
        - reward/objective_share  (part de l'objectif dans ce que l'episode a RAPPORTE)

        `objective_share` est la mesure qui motive tout le reste : la victoire se decide aux
        VP d'objectifs (game_state.determine_winner_with_method), donc une part d'objectif
        marginale signifie que l'agent est paye pour autre chose que pour gagner.
        """
        if not reward_data:
            return

        # Validate required fields - raise errors for missing data, NO DEFAULTS.
        # `*_positive` accompagne chaque composante DENSE : c'est le flux positif cumule pas a
        # pas par le callback, la seule forme utilisable pour une part (cf. plus bas).
        required_fields = [
            'base_actions', 'result_bonuses', 'objective', 'situational', 'penalties',
            'base_actions_positive', 'result_bonuses_positive', 'objective_positive',
        ]
        for field in required_fields:
            if field not in reward_data:
                raise KeyError(
                    f"Missing required field '{field}' in reward_data. "
                    f"Got keys: {list(reward_data.keys())}. "
                    f"All reward calculations must provide complete breakdown."
                )
            if not isinstance(reward_data[field], (int, float)):
                raise TypeError(
                    f"Reward field '{field}' must be numeric, "
                    f"got {type(reward_data[field])}: {reward_data[field]}"
                )

        base_actions = reward_data['base_actions']
        result_bonuses = reward_data['result_bonuses']
        objective = reward_data['objective']
        situational = reward_data['situational']
        penalties = reward_data['penalties']
        
        # `self.reward_components` (historique de 100 episodes par composante) etait alimente
        # ici et relu par PERSONNE : les cinq courbes ci-dessous sont per-episode, elles ne
        # lissent rien. Supprime avec son accumulateur.
        x = self.episode_count
        self.writer.add_scalar('reward/base_actions_total', float(base_actions), x)
        self.writer.add_scalar('reward/result_bonuses_total', float(result_bonuses), x)
        self.writer.add_scalar('reward/objective_total', float(objective), x)
        self.writer.add_scalar('reward/situational_total', float(situational), x)
        self.writer.add_scalar('reward/penalties_total', float(penalties), x)

        # Part de l'objectif dans ce qui RAPPORTE sur l'episode. `situational` (le terminal
        # +-50) est exclu : il recompense le RESULTAT, pas le comportement qui y mene, et sa
        # masse ecraserait la comparaison entre les deux signaux denses qu'on veut arbitrer.
        # `penalties` est exclu pour deux raisons : il est negatif, et il n'est pas disjoint de
        # `base_actions` (wait / charge_fail sont ecrits dans les DEUX par reward_calculator).
        #
        # Le denominateur somme les FLUX POSITIFS accumules pas a pas, jamais les totaux nets :
        # `base_actions` melange sur un episode les +0,3 de chaque tir et les -0,1 de chaque
        # attente, et un agent passif peut cumuler +18 de combat pour un net de -2. Filtrer les
        # totaux nets sur leur signe — ce que faisait la version precedente — jetait alors les
        # 18 points entiers du denominateur et gonflait la part de l'objectif exactement quand
        # les recompenses d'action sont les plus denses.
        # Numerateur = le flux positif de l'objectif lui aussi : la part reste dans [0,1] sans
        # rien supposer du signe des composantes.
        objective_positive = float(reward_data['objective_positive'])
        positive_total = (
            float(reward_data['base_actions_positive'])
            + float(reward_data['result_bonuses_positive'])
            + objective_positive
        )
        if positive_total > 0.0:
            self.writer.add_scalar('reward/objective_share', objective_positive / positive_total, x)
        # Denominateur nul = aucune recompense positive sur l'episode : il n'y a pas de part a
        # mesurer. On n'ecrit RIEN plutot qu'un 0.0, qui se lirait « part d'objectif nulle » et
        # serait indiscernable du cas ou l'agent n'a rien gagne du tout.

        # NOTE : 01_VP/f_obj_rewards est calcule dans log_tactical_metrics depuis les
        # echantillons d'objectifs tenus, et non depuis episode_reward_components (cette chaine
        # ne tient pas avec n_envs=48).

    def log_aiturn_compliance(self, compliance_data: Dict[str, Any]):
        """Log tour_de_jeu.md compliance validation metrics.
        
        GAME DETAILED METRICS (4):
        - game_detailed/aiturn_units_per_step
        - game_detailed/aiturn_eligibility_based_ends  
        - game_detailed/aiturn_duplicate_activations
        - game_detailed/aiturn_pool_corruption
        """
        # GAME DETAILED: Units per step (should always be 1.0)
        units_activated = require_key(compliance_data, 'units_activated_this_step')
        self.compliance_data['units_per_step'].append(units_activated)
        if len(self.compliance_data['units_per_step']) > 1000:
            self.compliance_data['units_per_step'].pop(0)
        
        avg_units_per_step = float(np.mean(self.compliance_data['units_per_step']))
        self.writer.add_scalar('game_detailed/aiturn_units_per_step', avg_units_per_step, self.episode_count)
        
        # GAME DETAILED: Phase end reason
        phase_end_reason = require_key(compliance_data, 'phase_end_reason')
        if phase_end_reason == 'eligibility':
            self.compliance_data['phase_end_reasons'].append(1)
        elif phase_end_reason == 'step_count':
            self.compliance_data['phase_end_reasons'].append(0)
        
        if len(self.compliance_data['phase_end_reasons']) > 100:
            self.compliance_data['phase_end_reasons'].pop(0)
        
        if self.compliance_data['phase_end_reasons']:
            eligibility_rate = float(np.mean(self.compliance_data['phase_end_reasons']))
            self.writer.add_scalar('game_detailed/aiturn_eligibility_based_ends', eligibility_rate, self.episode_count)
        
        # GAME DETAILED: Tracking violations
        duplicate_attempts = require_key(compliance_data, 'duplicate_activation_attempts')
        pool_corruption = require_key(compliance_data, 'pool_corruption_detected')
        
        self.writer.add_scalar('game_detailed/aiturn_duplicate_activations', duplicate_attempts, self.episode_count)
        self.writer.add_scalar('game_detailed/aiturn_pool_corruption', pool_corruption, self.episode_count)
    
    def log_reward_mapper_effectiveness(self, mapper_data: Dict[str, Any]):
        """Log reward mapper validation metrics.
        
        GAME DETAILED METRICS (4):
        - game_detailed/reward_mapper_shooting_priority
        - game_detailed/reward_mapper_movement_bonus_rate
        - game_detailed/reward_mapper_calculation_failures
        - game_detailed/reward_mapper_target_selection
        """
        # Track shooting priority decisions
        if 'shooting_priority_correct' in mapper_data:
            self.reward_mapper_stats['shooting_priority_correct'] += mapper_data['shooting_priority_correct']
            self.reward_mapper_stats['shooting_priority_total'] += 1
        
        # Track movement tactical bonuses
        if 'movement_had_tactical_bonus' in mapper_data:
            if mapper_data['movement_had_tactical_bonus']:
                self.reward_mapper_stats['movement_tactical_bonuses'] += 1
            self.reward_mapper_stats['movement_actions'] += 1
        
        # Track mapper failures
        if 'mapper_failed' in mapper_data and mapper_data['mapper_failed']:
            self.reward_mapper_stats['mapper_failures'] += 1
        
        # GAME DETAILED: Log to tensorboard
        if self.reward_mapper_stats['shooting_priority_total'] > 0:
            adherence = self.reward_mapper_stats['shooting_priority_correct'] / self.reward_mapper_stats['shooting_priority_total']
            self.writer.add_scalar('game_detailed/reward_mapper_shooting_priority', adherence, self.episode_count)
        
        if self.reward_mapper_stats['movement_actions'] > 0:
            bonus_rate = self.reward_mapper_stats['movement_tactical_bonuses'] / self.reward_mapper_stats['movement_actions']
            self.writer.add_scalar('game_detailed/reward_mapper_movement_bonus_rate', bonus_rate, self.episode_count)
        
        self.writer.add_scalar('game_detailed/reward_mapper_calculation_failures', self.reward_mapper_stats['mapper_failures'], self.episode_count)
    
    def log_victory_points_cumulative(self, points: float):
        """Log cumulative victory points for the controlled player at episode end.

        Args:
            points: Cumulative victory points for the learning agent for the episode.
        """
        self.combat_effectiveness['victory_points_cumulative'] = float(points)

    # `log_phase_performance` occupait cette place : elle accumulait, phase par phase, les
    # couples (agi, attendu) que `compute_and_log_phase_metrics` transformait en
    # `game_tactical/movement_efficiency`, `shooting_participation` et
    # `game_detailed/flee_rate`. Elle n'avait plus AUCUN appelant de production — les trois
    # courbes n'existaient dans aucun run. Les memes taux sont desormais calcules dans
    # `log_tactical_metrics`, depuis les compteurs que le moteur tire d'`action_logs` : la
    # phase et le camp y sont des donnees de chaque ligne, la ou cette methode les recevait
    # d'un `info` de step gym qui enchaine plusieurs steps moteur.

    def compute_and_log_phase_metrics(self):
        """Emet les VP cumules de l'episode, lisses sur la fenetre de performance.

        Les taux de participation par phase (`game_tactical/movement_efficiency`,
        `shooting_participation`, `game_detailed/flee_rate`) etaient calcules ici depuis
        `self.phase_stats`, accumule par `log_phase_performance` — methode sans appelant de
        production, donc des courbes qui n'existaient dans aucun run. Ils sont desormais
        calcules dans `log_tactical_metrics`, sur les compteurs du moteur. Le quatrieme,
        `game_tactical/charge_rate`, n'a pas ete repris : son denominateur ne mesurait pas ce
        qu'il pretendait (cf. w40k_core), et le volume `02_combat/m_charge_attempts` avec sa
        colonne adverse le remplace.

        Le nom de cette methode ne decrit plus que ce qu'elle fait ; elle garde sa place dans
        la sequence de fin d'episode (appelee DEPUIS `log_episode_end`, donc AVANT
        `log_tactical_metrics` — cet ordre est ce qui a deja fait ecrire ici la moyenne de
        l'episode PRECEDENT sur un tag de kills).
        """
        # VP cumules de l'episode. Seule serie qui reste ici : les kills tir/melee et leur
        # VALUE sont comptes cote moteur et emis par log_tactical_metrics (source fiable,
        # par episode et par env), et `combat/c_charge_successes` a suivi le meme chemin —
        # remplace par `02_combat/m_charge_attempts` + `n_charge_success_rate` et leurs jumeaux
        # `_bot`, comptes eux aussi sur `action_logs`. Un compte de reussites SANS le compte de
        # tentatives ne distinguait pas l'agent qui ne charge pas de celui qui rate ses
        # charges — exactement la question qu'on posait a cette courbe. Rupture de continuite
        # assumee : la mesure a change de source.
        #
        # Troncature a PERF_WINDOW, la fenetre que `_emit_windowed` exige PLEINE, et non a un
        # 500 en dur : les deux etaient egaux par coincidence de config. Un `perf_window` regle
        # au-dela de 500 aurait tronque cet historique SOUS la longueur requise, et
        # `01_VP/b_vp_agent` n'aurait plus jamais emis un seul point — sans erreur, sans courbe.
        # `_game_push` tronque deja a PERF_WINDOW : celui-ci etait le jumeau reste en arriere.
        #
        # Un SECOND add_scalar sur la courbe de kills de melee (ex-`0_game/l_melee_kills`,
        # aujourd'hui `02_combat/h_melee_model_kills`) a vecu ici, sur la meme serie que
        # log_tactical_metrics. compute_and_log_phase_metrics etant appele DEPUIS
        # log_episode_end, donc AVANT log_tactical_metrics de l'episode courant, il ecrivait la
        # moyenne de l'episode PRECEDENT : deux series entrelacees sur un meme tag (99 999
        # points pour 50 000 episodes), d'ou une courbe en zigzag sans rapport avec les kills
        # de melee. Le seul ecrivain restant est log_tactical_metrics, qui logge apres l'append.
        vp_history = self.combat_history['victory_points_cumulative']
        vp_history.append(self.combat_effectiveness['victory_points_cumulative'])
        if len(vp_history) > self.PERF_WINDOW:
            vp_history.pop(0)
        self._emit_windowed('01_VP/b_vp_agent', vp_history)

        # Reset combat effectiveness and flags for next episode
        self.combat_effectiveness = {
            'victory_points_cumulative': 0.0
        }
    
    def log_training_metrics(self, model_stats: Dict[str, Any]):
        """
        Log PPO hyperparameter and algorithm health metrics from stable-baselines3.
        
        TRAINING CRITICAL METRICS (6):
        - training_critical/policy_loss - PPO policy gradient loss
        - training_critical/value_loss - Value function loss component
        - training_critical/explained_variance - Value function prediction quality
        - training_critical/clip_fraction - Fraction of policy updates clipped
        - training_critical/approx_kl - KL divergence between old/new policy
        - training_critical/fps - Training speed
        
        TRAINING DIAGNOSTIC METRICS (5):
        - training_diagnostic/learning_rate - Current learning rate value
        - training_diagnostic/entropy_coef - Current entropy coefficient
        - training_diagnostic/entropy_loss - Entropy bonus loss
        - training_diagnostic/n_updates - Total policy updates count
        - training_diagnostic/gradient_norm - Gradient magnitude (if available)
        
        Args:
            model_stats: Dictionary from stable-baselines3 logger (model.logger.name_to_value)
        """
        
        # TRAINING DIAGNOSTIC: Learning rate (critical for convergence monitoring)
        if 'train/learning_rate' in model_stats:
            lr = model_stats['train/learning_rate']
            self.hyperparameter_tracking['learning_rates'].append(lr)
            self.writer.add_scalar('training_diagnostic/learning_rate', lr, self.step_count)
        
        # TRAINING CRITICAL: Policy gradient loss (PPO policy loss component)
        if 'train/policy_gradient_loss' in model_stats:
            policy_loss = model_stats['train/policy_gradient_loss']
            self.hyperparameter_tracking['policy_losses'].append(policy_loss)
            self.writer.add_scalar('training_critical/policy_loss', policy_loss, self.step_count)
        
        # TRAINING CRITICAL: Value function loss (critic loss component)
        if 'train/value_loss' in model_stats:
            value_loss = model_stats['train/value_loss']
            self.hyperparameter_tracking['value_losses'].append(value_loss)
            self.writer.add_scalar('training_critical/value_loss', value_loss, self.step_count)
        
        # TRAINING DIAGNOSTIC: Entropy loss (exploration bonus component)
        if 'train/entropy_loss' in model_stats:
            entropy_loss = model_stats['train/entropy_loss']
            self.hyperparameter_tracking['entropy_losses'].append(entropy_loss)
            self.writer.add_scalar('training_diagnostic/entropy_loss', entropy_loss, self.step_count)

        # TRAINING DIAGNOSTIC: Log entropy coefficient independently from entropy_loss
        # so schedule diagnostics remain available even if entropy_loss is missing.
        if 'train/ent_coef' in model_stats:
            ent_coef = model_stats['train/ent_coef']
            self.writer.add_scalar('training_diagnostic/entropy_coef', ent_coef, self.step_count)
        
        # TRAINING CRITICAL: Clip fraction (how often PPO clips policy updates)
        if 'train/clip_fraction' in model_stats:
            clip_fraction = model_stats['train/clip_fraction']
            self.hyperparameter_tracking['clip_fractions'].append(clip_fraction)
            self.writer.add_scalar('training_critical/clip_fraction', clip_fraction, self.step_count)
        
        # TRAINING CRITICAL: Approximate KL divergence (policy change magnitude)
        if 'train/approx_kl' in model_stats:
            approx_kl = model_stats['train/approx_kl']
            self.hyperparameter_tracking['approx_kls'].append(approx_kl)
            self.writer.add_scalar('training_critical/approx_kl', approx_kl, self.step_count)
        
        # TRAINING CRITICAL: Explained variance (value function quality)
        if 'train/explained_variance' in model_stats:
            explained_var = model_stats['train/explained_variance']
            self.hyperparameter_tracking['explained_variances'].append(explained_var)
            self.writer.add_scalar('training_critical/explained_variance', explained_var, self.step_count)
        
        # TRAINING DIAGNOSTIC: Total policy updates count
        if 'train/n_updates' in model_stats:
            n_updates = model_stats['train/n_updates']
            self.writer.add_scalar('training_diagnostic/n_updates', n_updates, self.step_count)
        
        # TRAINING DIAGNOSTIC: Gradient norm (gradient explosion/vanishing check)
        if 'train/gradient_norm' in model_stats:
            grad_norm = model_stats['train/gradient_norm']
            self.latest_gradient_norm = grad_norm  # Store for 00_critical/ dashboard
            self.writer.add_scalar('training_diagnostic/gradient_norm', grad_norm, self.step_count)
        
        # TRAINING CRITICAL: Frames per second (training efficiency)
        if 'time/fps' in model_stats:
            fps = model_stats['time/fps']
            self.writer.add_scalar('training_critical/fps', fps, self.step_count)
        
        # Update step count for next logging
        self.step_count += 1
    
    def log_critical_dashboard(self):
        """
        🎯 CRITICAL DASHBOARD - metriques essentielles au tuning des hyperparametres PPO.

        ECRIT ICI (8 tags) :

        PERFORMANCE D'EPISODE -- lissees sur `perf_window` :
        - 00_critical/d_win_rate             - Training opponent performance
        - 00_critical/e_episode_reward_smooth  - Learning progress
        (le doublon a fenetre courte `_<perf_window_fast>ep` n'existe que si les deux
         fenetres du training config different ; elles sont egales par defaut)

        SANTE PPO -- moyennes sur les 20 derniers updates :
        - 00_critical/f_loss_mean           - |policy_loss| + |value_loss|, sante globale
        - 00_critical/g_explained_variance  - >0.3 -> Value function working
        - 00_critical/h_clip_fraction       - [0.1-0.3] -> Tune learning_rate
        - 00_critical/i_approx_kl           - <0.02 -> Policy stability
        - 00_critical/j_entropy_loss        - Decroissant -> Tune ent_coef
        - 00_critical/m_value_loss_smooth   - Smoothed critic loss

        ECRIT PAR `_log_zone_intent_metrics`, appele en fin de cette methode (2 tags) :
        - 00_critical/n_intent_zone_steps          - free steps zone-intent par episode
        - 00_critical/o_intent_control_dependency  - I(intent;controle)/H(controle), non emis
                                                     quand H(controle) == 0

        ECRIT AILLEURS, volontairement -- inventaire complet du namespace :
        - `log_bot_evaluations`, au moment de l'evaluation (attendre l'episode suivant
          publierait une valeur perimee) : 0_gap_sm-ork, a_bot_eval_combined,
          b_worst_bot_score, c_holdout_hard_mean.
        - `training_callbacks` (BotEvaluationCallback), qui seul connait ces deux etats :
          0_eval_timeout_episodes (emis UNIQUEMENT si une eval a ete tronquee ; ce point
          d'eval n'alimente alors aucun autre signal) et o_robust_current_score.
        - `_emit_deploy_split`, appele au moment ou chaque valeur est calculee : les emettre
          ici les decalerait d'un episode (ce dashboard tourne AVANT log_tactical_metrics).
          Cf. DEPLOY_SPLIT_SERIES pour le pourquoi de la ventilation.
          p_reward_deploy_{active,fixed}, q_obj_held_diff_deploy_{active,fixed},
          r_win_rate_deploy_{active,fixed}, s_deploy_active_share.
        - `_emit_truncation_curve` : t_truncated_episodes, cumul des episodes coupes par le
          garde anti-runaway du moteur. Emis a part, sur les DEUX fins d'episode : un episode
          tronque ne passe pas par ce dashboard (il n'alimente aucune courbe de jeu), et un
          episode normal doit quand meme poser son point, sans quoi la courbe n'existe pas
          dans le cas nominal. Doit valoir 0 (V11 §0.61).

        NOTE: position_score a ete supprime (voir la trace dans __init__), pas deplace.
        `k_gradient_norm` a ete retire du dashboard (redondant avec h + i, cf. plus bas) ;
        la lettre `l` n'a jamais ete attribuee dans ce namespace.
        """
        
        # Minimum data requirement (lowered to 1 for immediate feedback)
        min_episodes = 1
        if len(self.all_episode_rewards) < min_episodes:
            return  # Not enough data yet
        
        # ==========================================
        # GAME PERFORMANCE (2 metrics)
        # ==========================================
        
        # 1. Win Rate - SORTS FIRST alphabetically
        # Le tag suffixe `_100ep` portait jusqu'ici une fenetre de 500 : son nom mentait. Il
        # designe desormais la fenetre qu'il annonce, et la fenetre de fond prend le nom nu.
        self._emit_windowed('00_critical/d_win_rate', self.all_episode_wins)

        # 2. Episode Reward (smoothed) - Training signal strength
        self._emit_windowed('00_critical/e_episode_reward_smooth', self.all_episode_rewards)

        # ==========================================
        # PPO HEALTH (6 metrics)
        # ==========================================

        # 3. Clip Fraction - Policy update scale
        if len(self.hyperparameter_tracking['clip_fractions']) >= 1:
            clip_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['clip_fractions'], window_size=20
            )
            self.writer.add_scalar('00_critical/h_clip_fraction', clip_smooth, self.episode_count)

        # 4. Approx KL - Policy change magnitude
        if len(self.hyperparameter_tracking['approx_kls']) >= 1:
            kl_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['approx_kls'], window_size=20
            )
            self.writer.add_scalar('00_critical/i_approx_kl', kl_smooth, self.episode_count)

        # 5. Explained Variance - Value function quality
        if len(require_key(self.hyperparameter_tracking, 'explained_variances')) >= 1:
            ev_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['explained_variances'], window_size=20
            )
            self.writer.add_scalar('00_critical/g_explained_variance', ev_smooth, self.episode_count)

        # 6. Entropy Loss - Exploration health
        if len(self.hyperparameter_tracking['entropy_losses']) >= 1:
            entropy_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['entropy_losses'], window_size=20
            )
            self.writer.add_scalar('00_critical/j_entropy_loss', entropy_smooth, self.episode_count)

        # 7. Loss Mean (combined policy + value loss) - Training stability
        if (len(self.hyperparameter_tracking['policy_losses']) >= 1 and
            len(self.hyperparameter_tracking['value_losses']) >= 1):
            # Calculate combined loss
            recent_policy = self.hyperparameter_tracking['policy_losses'][-20:]
            recent_value = self.hyperparameter_tracking['value_losses'][-20:]
            combined_losses = [abs(p) + abs(v) for p, v in zip(recent_policy, recent_value)]
            loss_mean = float(np.mean(combined_losses))
            value_loss_smooth = float(np.mean(recent_value))
            self.writer.add_scalar('00_critical/f_loss_mean', loss_mean, self.episode_count)
            self.writer.add_scalar('00_critical/m_value_loss_smooth', value_loss_smooth, self.episode_count)
        
        # ==========================================
        # HORS 00_critical : ecrit dans game_critical/ et game_detailed/
        # ==========================================
        # `k_gradient_norm` occupait cette place : retire du dashboard, redondant avec
        # h_clip_fraction + i_approx_kl.

        # Reward-Victory Gap (reward alignment: mean reward when won vs lost)
        # Gap > 20-30 = good alignment; Gap < 10 = reward may not correlate with victory
        if len(self.episode_reward_winner_pairs) >= 20:
            recent = list(self.episode_reward_winner_pairs)[-100:]
            rewards_when_won = [r for r, outcome in recent if outcome == 1]
            rewards_when_lost = [r for r, outcome in recent if outcome == 0]
            if len(rewards_when_won) >= 5 and len(rewards_when_lost) >= 5:
                mean_won = float(np.mean(rewards_when_won))
                mean_lost = float(np.mean(rewards_when_lost))
                gap = mean_won - mean_lost
                self.writer.add_scalar('game_critical/reward_when_won', mean_won, self.episode_count)
                self.writer.add_scalar('game_critical/reward_when_lost', mean_lost, self.episode_count)
                self.writer.add_scalar('game_detailed/reward_victory_gap', gap, self.episode_count)

        # 12. Bot Evaluation Combined Score (logged immediately in log_bot_evaluations())
        # NOTE: This metric is logged in log_bot_evaluations() to avoid duplicate/stale values
        # Do not log here - let log_bot_evaluations() handle it
        
        # game_critical/invalid_action_rate a UN SEUL ecrivain : log_tactical_metrics, qui lit
        # les compteurs d'actions de l'episode passes par le callback. Le doublon qui occupait
        # cette place lisait un self.episode_tactical_data jamais alimente (voir la trace dans
        # __init__) et ecrasait la vraie courbe avec des zeros.

        self._log_thresholds(self.episode_count)

        # Phase 2: zone intent metrics (sliding window)
        self._log_zone_intent_metrics(self.episode_count)

    def _reset_zone_intent_state(self) -> None:
        """Initialise l'etat zone-intent (fenetre glissante + accumulateurs de l'episode courant)."""
        self._zone_steps_since_episode_end: int = 0
        self._zone_steps_window: Deque[int] = deque(maxlen=ZONE_INTENT_WINDOW_EPISODES)
        self._intent_contingency_window: Deque[List[int]] = deque(maxlen=ZONE_INTENT_WINDOW_EPISODES)
        self._intent_contingency_since_episode_end: List[int] = [0] * (
            ZONE_CONTROL_CARDINALITY * INTENT_CARDINALITY
        )

    def log_zone_intent_step(self, intent_value: int, zone_control: float) -> None:
        """
        Compte un free step zone-intent. ECRIVAIN UNIQUE : le callback d'entrainement, qui lit
        `info['intent_value']` et `info['zone_control']` (voir training_callbacks). Le moteur a
        longtemps compte EN PLUS via un `_metrics_tracker` pose sur l'env ; ce chemin n'etait
        arme qu'a n_envs==1, donc `--step` comptait double et l'entrainement multi-env non.

        Args:
            intent_value: 0=INVADE, 1=DEFEND, 2=ATTACK
            zone_control: -1.0 objectif adverse, 0.0 neutre/conteste, 1.0 controle par l'agent
        """
        if intent_value not in (0, 1, 2):
            raise ValueError(f"Invalid intent_value for zone intent step: {intent_value}")
        if zone_control not in (-1.0, 0.0, 1.0):
            raise ValueError(f"Invalid zone_control for zone intent step: {zone_control}")

        self._zone_steps_since_episode_end += 1
        control_idx = int(zone_control) + 1  # -1/0/1 -> 0/1/2
        self._intent_contingency_since_episode_end[control_idx * INTENT_CARDINALITY + intent_value] += 1

    def _log_zone_intent_metrics(self, step: int) -> None:
        """
        Emet les metriques zone-intent sur la fenetre glissante et fait avancer celle-ci d'un
        episode. Appelee a chaque `log_episode_end` via `log_critical_dashboard`.
        """
        self._zone_steps_window.append(self._zone_steps_since_episode_end)
        self._zone_steps_since_episode_end = 0
        self._intent_contingency_window.append(self._intent_contingency_since_episode_end)
        self._intent_contingency_since_episode_end = [0] * (ZONE_CONTROL_CARDINALITY * INTENT_CARDINALITY)

        n_steps_per_ep = sum(self._zone_steps_window) / len(self._zone_steps_window)
        self.writer.add_scalar("00_critical/n_intent_zone_steps", n_steps_per_ep, step)

        table = [0] * (ZONE_CONTROL_CARDINALITY * INTENT_CARDINALITY)
        for episode_table in self._intent_contingency_window:
            for cell, count in enumerate(episode_table):
                table[cell] += count
        total_intents = sum(table)

        if total_intents == 0:
            # Aucun free step sur la fenetre : les ratios et l'information mutuelle n'ont pas
            # d'echantillon. Ne rien emettre plutot que des zeros, qui se liraient comme
            # "distribution uniforme, MI nulle" — soit exactement le diagnostic recherche.
            return

        _control_marginal, intent_marginal = self._marginals(table)
        self.writer.add_scalar("combat/intent_invade_ratio", intent_marginal[0], step)
        self.writer.add_scalar("combat/intent_defend_ratio", intent_marginal[1], step)
        self.writer.add_scalar("combat/intent_attack_ratio", intent_marginal[2], step)

        # Ingredients de la mesure, emis pour eux-memes : l'entropie du CONTROLE dit si le
        # plateau offrait seulement de quoi conditionner un choix.
        mutual_info = self._intent_control_mutual_info(table)
        control_entropy = self._control_entropy(table)
        self.writer.add_scalar("combat/intent_mutual_info_bits", mutual_info, step)
        self.writer.add_scalar("combat/intent_control_entropy_bits", control_entropy, step)

        if control_entropy > 0.0:
            # I est bornee par H(controle), PAS par log2(3) : sur un plateau ou tous les
            # objectifs sont neutres au moment des free steps, H = 0 et I = 0 quelle que soit la
            # politique. Emettre I seule ferait lire "la tete n'a rien appris" la ou il n'y avait
            # rien a apprendre. On normalise donc : U = I / H(controle) est la FRACTION de
            # l'incertitude d'intent expliquee par l'etat, 1.0 = intent entierement determine.
            self.writer.add_scalar(
                "00_critical/o_intent_control_dependency", mutual_info / control_entropy, step
            )
        # H(controle) == 0 : aucun contraste d'etat sur la fenetre, la question n'a pas de sens.
        # Emettre 0.0 la designerait a tort la politique.

        aligned, aligned_baseline = self._intent_shaping_alignment(table)
        self.writer.add_scalar("combat/intent_shaping_aligned_ratio", aligned, step)
        self.writer.add_scalar("combat/intent_shaping_aligned_baseline", aligned_baseline, step)

    @staticmethod
    def _marginals(table: Sequence[int]) -> Tuple[List[float], List[float]]:
        """Distributions marginales (controle, intent) de la table de contingence 3x3."""
        total = sum(table)
        if total == 0:
            raise ValueError("Zone intent marginals require a non-empty contingency table")
        control = [
            sum(table[c * INTENT_CARDINALITY + i] for i in range(INTENT_CARDINALITY)) / total
            for c in range(ZONE_CONTROL_CARDINALITY)
        ]
        intent = [
            sum(table[c * INTENT_CARDINALITY + i] for c in range(ZONE_CONTROL_CARDINALITY)) / total
            for i in range(INTENT_CARDINALITY)
        ]
        return control, intent

    @classmethod
    def _control_entropy(cls, table: Sequence[int]) -> float:
        """
        H(controle) en BITS : le contraste d'etat que le plateau a REELLEMENT offert aux free
        steps de la fenetre.

        C'est le plafond de I(intent ; controle). Mesure faite sur le vrai moteur : en jeu
        aleatoire les figurines quittent les objectifs et les free steps, joues en command phase
        avant tout mouvement du tour, ne voient plus que du neutre — H tombe a 0 et aucune
        politique, si bonne soit-elle, ne peut produire une I non nulle. D'ou la publication de
        H a cote du diagnostic : sans elle, "rien appris" et "rien a apprendre" se confondent.
        """
        control, _intent = cls._marginals(table)
        return float(-sum(p * np.log2(p) for p in control if p > 0.0))

    @classmethod
    def _intent_control_mutual_info(cls, table: Sequence[int]) -> float:
        """
        I(intent ; controle) en BITS a partir de la table de contingence 3x3.

        0 bit = le choix d'intent est statistiquement independant de l'etat de l'objectif : la
        tete zone-intent joue la meme distribution quel que soit le plateau, donc elle n'a rien
        appris. Une valeur > 0 prouve le conditionnement mais PAS son sens — un agent qui ferait
        systematiquement l'inverse du shaping obtiendrait une MI elevee. C'est
        `_intent_shaping_alignment` qui donne le sens.

        A NE PAS LIRE SEULE : bornee par H(controle) (cf. `_control_entropy`), pas par log2(3).
        Le diagnostic publie en 00_critical est le rapport I / H(controle).
        """
        total = sum(table)
        control, intent = cls._marginals(table)

        mutual_info = 0.0
        for c in range(ZONE_CONTROL_CARDINALITY):
            for i in range(INTENT_CARDINALITY):
                joint = table[c * INTENT_CARDINALITY + i]
                if joint == 0:
                    continue  # 0 * log(0) = 0, terme nul et non defini
                p_joint = joint / total
                mutual_info += p_joint * np.log2(p_joint / (control[c] * intent[i]))
        return float(mutual_info)

    @classmethod
    def _intent_shaping_alignment(cls, table: Sequence[int]) -> Tuple[float, float]:
        """
        Part des free steps dont le couple (controle, intent) est paye par
        `RewardCalculator.settle_zone_intent_declaration` — DEFEND sur objectif tenu, INVADE sur
        objectif adverse, INVADE sur objectif neutre — ET la valeur de reference a laquelle la
        comparer.

        La reference est ce que la MEME politique obtiendrait si elle choisissait son intent
        sans regarder le plateau (produit des marginales observees). Elle n'est pas constante :
        elle depend de la frequence des trois etats de controle, qui varie d'une fenetre a
        l'autre. Publier le ratio seul le rendrait illisible — "0.42, c'est bien ou pas ?" n'a
        de reponse qu'en regard de cette ligne.
        """
        control, intent = cls._marginals(table)
        total = sum(table)

        control_owned, control_neutral, control_enemy = 2, 1, 0  # controle 1.0 / 0.0 / -1.0
        intent_invade, intent_defend = 0, 1
        paid = (
            (control_owned, intent_defend),
            (control_enemy, intent_invade),
            (control_neutral, intent_invade),
        )
        aligned = sum(table[c * INTENT_CARDINALITY + i] for c, i in paid) / total
        baseline = sum(control[c] * intent[i] for c, i in paid)
        return aligned, baseline

    def log_bot_eval_cost(
        self, duration_seconds: float, episodes_played: int, step: int
    ) -> None:
        """Ce que CETTE evaluation a coute : duree, et debit en episodes par seconde.

        POURQUOI CETTE COURBE EXISTE. `bot_eval_freq` et `bot_eval_intermediate` se reglent sur
        le cout d'une evaluation, et ce cout n'etait mesure NULLE PART : la duree
        (`eval_duration_seconds`) n'etait imprimee que sur erreur ou sur timeout, donc jamais
        dans le cas nominal. Les notes de config s'appuyaient sur un chiffre herite d'un commit
        de 2026-07, jamais re-mesure — et deux estimations en desaccord d'un facteur ~4,5
        cohabitaient le 2026-08-11 sans que rien ne permette de trancher.

        LE DEBIT, et pas seulement la duree : une evaluation intermediaire (600 episodes) et une
        finale (3600) ne se comparent pas en secondes. `episodes_per_second` est la seule des
        deux qui reponde a « combien coutera un point de mesure de plus », qui est la question
        que le reglage pose. Le denominateur est le nombre d'episodes REELLEMENT joues, hors
        abandons (`total_episodes_played`) : les episodes tues sur timeout n'ont pas ete joues,
        les compter gonflerait le debit d'autant.

        ⚠️ Ces valeurs dependent du regime de mesure : la journalisation pas-a-pas (`--step`) et
        `W40K_PERF_TIMING=1` ralentissent l'evaluation. Une mesure prise sous instrumentation ne
        sert pas a regler une cadence de production.
        """
        if episodes_played <= 0:
            raise ValueError(
                f"log_bot_eval_cost: episodes_played doit etre > 0 (got {episodes_played}) — "
                "une evaluation sans episode joue n'a pas de cout a publier."
            )
        if duration_seconds <= 0.0:
            raise ValueError(
                f"log_bot_eval_cost: duration_seconds doit etre > 0 (got {duration_seconds})."
            )
        self.writer.add_scalar('perf/d_bot_eval_seconds', float(duration_seconds), step)
        self.writer.add_scalar(
            'perf/e_bot_eval_episodes_per_second',
            float(episodes_played) / float(duration_seconds),
            step,
        )

    def log_bot_evaluations(self, bot_results: Dict[str, float], step: Optional[int] = None):
        """
        Log bot evaluation results to both 00_critical/ and bot_eval/ namespaces.

        Args:
            bot_results: Dict with keys 'random', 'greedy', 'defensive', 'combined'
            step: Optional step for x-axis (e.g. eval_marker). If None, uses episode_count.
        """
        x = step if step is not None else self.episode_count
        # Une courbe `bot_eval/vs_<bot>` par adversaire MESURE, quel qu'il soit. La liste vient du
        # registre : cette methode enumerait les six bots d'origine un par un, en dur, si bien que
        # les cinq styles refondus (racer, endgame, alpha, attrition, decapitation) ont joue leurs
        # episodes le 2026-08-11 sans produire une seule courbe. Le nom du scalaire est inchange
        # pour tous les bots existants — les courbes deja tracees ne se coupent pas en deux.
        # V11 §10.5 : les holdouts en ont une eux aussi. C'est LE win-rate qui mesure la competence
        # et non l'exploitation apprise (§10.6) ; ils sont mesures et affiches, jamais selectionnes.
        for bot_name in sorted(ALL_BOT_KEYS):
            if bot_name in bot_results:
                self.writer.add_scalar(f'bot_eval/vs_{bot_name}', bot_results[bot_name], x)
        # worst_bot_score alimente 00_critical/b_worst_bot_score et suit la selection : il itere
        # donc sur les bots de SELECTION, holdouts exclus (V11 §10.5) — un `min` sur des NOMS de
        # bots n'est pas protege par le poids nul de `bot_eval_weights`.
        # Le regroupement « palier 2 » (aggressive_smart + defensive_smart + adaptive) et son
        # scalaire bot_eval/tier2_combined ont ete SUPPRIMES avec deux de leurs trois bots :
        # une moyenne sur un seul adversaire n'est plus un palier, c'est `vs_adaptive`.
        bot_score_keys = [k for k in sorted(SELECTION_BOT_KEYS) if k in bot_results]
        if len(bot_score_keys) >= 3:
            worst_bot_score = min(bot_results[k] for k in bot_score_keys)
            self.writer.add_scalar('bot_eval/worst_bot_score', worst_bot_score, x)
            self.writer.add_scalar('00_critical/b_worst_bot_score', worst_bot_score, x)
            if self.forcing_tracking['episodes_total'] > 0:
                if self.forcing_tracking['baseline_worst_bot'] is None:
                    self.forcing_tracking['baseline_worst_bot'] = float(worst_bot_score)
                baseline_worst = float(require_key(self.forcing_tracking, 'baseline_worst_bot'))
                self.writer.add_scalar(
                    'forcing/delta_worst_bot_vs_forcing_start',
                    float(worst_bot_score) - baseline_worst,
                    x
                )
        if 'holdout_hard_mean' in bot_results:
            holdout_hard_mean = float(bot_results['holdout_hard_mean'])
            self.writer.add_scalar('bot_eval/holdout_hard_mean', holdout_hard_mean, x)
            self.writer.add_scalar('00_critical/c_holdout_hard_mean', holdout_hard_mean, x)

        # Store combined score and log immediately to both namespaces
        if 'combined' in bot_results:
            self.bot_eval_combined = bot_results['combined']
            # Log to bot_eval/ namespace
            self.writer.add_scalar('bot_eval/combined', bot_results['combined'], x)
            # Log IMMEDIATELY to 00_critical/ namespace (don't wait for next episode)
            self.writer.add_scalar('00_critical/a_bot_eval_combined', bot_results['combined'], x)
            if self.forcing_tracking['episodes_total'] > 0:
                if self.forcing_tracking['baseline_combined'] is None:
                    self.forcing_tracking['baseline_combined'] = float(bot_results['combined'])
                baseline_combined = float(require_key(self.forcing_tracking, 'baseline_combined'))
                self.writer.add_scalar(
                    'forcing/delta_combined_vs_forcing_start',
                    float(bot_results['combined']) - baseline_combined,
                    x
                )

    def log_faction_scores(
        self,
        faction_scores: Dict[str, float],
        roster_gap: Optional[float],
        step: Optional[int] = None,
    ) -> None:
        """
        Log le win-rate pondere par faction jouee par l'agent, et leur ecart.

        `00_critical/0_gap_sm-ork` = combined(Space Marines) - combined(Orks) :
          > 0 -> l'agent domine avec les Space Marines
          < 0 -> l'agent domine avec les Orks
          ~ 0 -> parite entre les deux rosters
        Cet ecart est le seul indicateur qui distingue un agent equilibre d'un agent
        specialise : `a_bot_eval_combined` moyenne les deux factions et affiche la meme
        valeur dans les deux cas. `roster_gap` vaut None quand le pool d'evaluation ne
        couvre pas les deux factions — aucune courbe n'est alors tracee (cf.
        ai.bot_evaluation.ROSTER_GAP_FACTIONS, qui porte aussi le SENS de la soustraction).
        """
        if not isinstance(faction_scores, dict):
            raise TypeError(
                f"faction_scores must be dict (got {type(faction_scores).__name__})"
            )
        x = step if step is not None else self.episode_count
        for faction, score in faction_scores.items():
            self.writer.add_scalar(
                f'bot_eval/faction/{self._faction_tag_segment(faction)}', float(score), x
            )
        if roster_gap is not None:
            self.writer.add_scalar('00_critical/0_gap_sm-ork', float(roster_gap), x)

    @staticmethod
    def _faction_tag_segment(faction: str) -> str:
        """Segment de tag TensorBoard d'une faction — UNE regle pour les deux familles.

        `.lower()` et non `_metric_slug` : une faction COMPOSITE (« Ork+Spacemarine », cf.
        ai.bot_evaluation._agent_faction_from_engine) est deja publiee sous
        `bot_eval/faction/ork+spacemarine`. Passer au slug la renommerait `ork_spacemarine`,
        c'est-a-dire changer le nom d'une courbe deja tracee. La regle est donc figee ici, a
        un seul endroit, plutot que recopiee par chaque famille de tags.
        """
        return str(faction).lower()

    def log_selfplay_win(self, label: str, agent_won: float) -> None:
        """Emet `03_selfplay/{label}` — win rate glissant contre chaque snapshot du pool.

        La fenetre est PERF_WINDOW episodes DE CE LABEL, pas tous episodes confondus : un label
        rare ne dilue pas les autres et n'emetra un premier point qu'une fois sa fenetre pleine.
        """
        if not label:
            return
        self._emit_windowed(
            f"03_selfplay/{label}",
            self._push_window(self._selfplay_wins.setdefault(label, []), float(agent_won), self.PERF_WINDOW),
        )

    def log_faction_bot_win_rates(
        self,
        faction_bot_win_rates: Dict[str, Dict[str, float]],
        step: Optional[int] = None,
    ) -> None:
        """
        Log le CROISEMENT `bot_eval/faction/<faction>/vs_<bot>` (V11 §0.55, [§10.6]).

        Sans lui, `bot_eval/vs_<bot>` melange les rosters et `bot_eval/faction/<faction>`
        melange les adversaires : aucune des deux courbes ne dit si une faiblesse contre un
        bot tient a UN roster ou aux deux.

        ⚠️ Ce croisement n'est PAS la decomposition de `bot_eval/faction/<faction>`, malgre le
        prefixe commun : l'agregat est PONDERE par `bot_eval_weights` et exclut donc le
        holdout (poids 0.0), tandis que ces cellules sont des win-rates BRUTS et incluent le
        holdout. Leur moyenne ne redonne pas l'agregat, et c'est voulu.

        Methode dediee, comme `log_holdout_split_metrics` / `log_scenario_split_scores` : une
        ventilation par point d'entree. La greffer sur `log_faction_scores` obligerait chaque
        nouvelle ventilation a rallonger sa signature.
        """
        if not isinstance(faction_bot_win_rates, dict):
            raise TypeError(
                f"faction_bot_win_rates must be dict "
                f"(got {type(faction_bot_win_rates).__name__})"
            )
        x = step if step is not None else self.episode_count
        for faction, per_bot in faction_bot_win_rates.items():
            for bot_name, win_rate in per_bot.items():
                self.writer.add_scalar(
                    f'bot_eval/faction/{self._faction_tag_segment(faction)}/vs_{bot_name}',
                    float(win_rate),
                    x,
                )

    def log_roster_bot_win_rates(
        self,
        side: str,
        roster_bot_win_rates: Dict[str, Dict[str, float]],
        step: Optional[int] = None,
    ) -> None:
        """Log le croisement `bot_eval/roster/<side>/<roster_id>/vs_<bot>` (chantier 04c).

        Ce que `bot_eval/faction/<faction>/vs_<bot>` ne donne pas : deux VARIANTES d'une meme
        faction — typiquement la meme liste avec et sans reserves strategiques — y sont
        confondues sous une seule courbe. Lire l'agregat apres l'ajout des reserves rendrait
        toute baisse inattribuable : liste plus faible, ou agent qui ne sait pas defendre contre
        une arrivee ? Ces deux causes ont des courbes distinctes ici.

        `side` porte une question DIFFERENTE de chaque cote, d'ou deux arbres de tags separes :
          - `agent`    : l'agent sait-il UTILISER ses propres reserves ?
          - `opponent` : sait-il ENCAISSER une arrivee adverse ?

        Comme `log_faction_bot_win_rates`, ces cellules sont des win-rates BRUTS incluant le
        holdout : leur moyenne ne redonne pas un agregat pondere, et c'est voulu.
        """
        if side not in {"agent", "opponent"}:
            raise ValueError(
                f"log_roster_bot_win_rates: side doit valoir 'agent' ou 'opponent', pas {side!r}"
            )
        if not isinstance(roster_bot_win_rates, dict):
            raise TypeError(
                f"roster_bot_win_rates must be dict "
                f"(got {type(roster_bot_win_rates).__name__})"
            )
        x = step if step is not None else self.episode_count
        for roster_id, per_bot in roster_bot_win_rates.items():
            for bot_name, win_rate in per_bot.items():
                self.writer.add_scalar(
                    f'bot_eval/roster/{side}/{self._metric_slug(roster_id)}/vs_{bot_name}',
                    float(win_rate),
                    x,
                )

    def log_seat_scores(
        self,
        seat_scores: Dict[str, float],
        seat_gap: Optional[float] = None,
        step: Optional[int] = None,
    ) -> None:
        """Log le combined par SIEGE et leur ecart (`00_critical/0_gap_p1-p2`).

        CE QU'AUCUNE AUTRE COURBE NE DONNAIT. `agent_seat_mode: "random"` fait jouer l'agent
        premier ou second a parts egales, et l'entrainement mesure deja les deux separement
        (`seat_aware/winrate_agent_p1` / `_p2`). L'EVALUATION, elle, les melangeait : son
        `combined` — le chiffre dont derive le score robuste qui SELECTIONNE le modele livre —
        etait aveugle a l'ecart. Mesure du run x1_long du 2026-08-12 : 0.707 en jouant premier
        contre 0.586 en jouant second, 12 points stables jusqu'a la fin du run. Un combined de
        0.909 peut donc cacher un 0.95/0.87, et rien ne le montrait cote evaluation.

        Sens de la soustraction, fige par `ai.bot_evaluation.SEAT_KEYS` :
          > 0 -> l'agent est meilleur en jouant PREMIER
          < 0 -> meilleur en jouant SECOND
          ~ 0 -> parite entre les deux sieges
        `seat_gap` vaut None quand un seul siege est couvert (`agent_seat_mode` a "p1" ou "p2") :
        aucune courbe n'est alors tracee, plutot qu'un score absolu deguise en ecart — meme regle
        que `roster_gap` dans `log_faction_scores`.

        Ces scores sont PONDERES par `bot_eval_weights`, comme `results["combined"]` et comme les
        agregats par faction : c'est ce qui les rend directement comparables entre eux. Le
        croisement brut siege x bot vit dans `log_seat_bot_win_rates`.
        """
        if not isinstance(seat_scores, dict):
            raise TypeError(f"seat_scores must be dict (got {type(seat_scores).__name__})")
        x = step if step is not None else self.episode_count
        for seat, score in seat_scores.items():
            self.writer.add_scalar(f'bot_eval/seat/{seat}', float(score), x)
        if seat_gap is not None:
            self.writer.add_scalar('00_critical/0_gap_p1-p2', float(seat_gap), x)

    def log_seat_bot_win_rates(
        self,
        seat_bot_win_rates: Dict[str, Dict[str, float]],
        step: Optional[int] = None,
    ) -> None:
        """Log le croisement `bot_eval/seat/<seat>/vs_<bot>`.

        Ce que `bot_eval/seat/<seat>` ne dit pas : si le desavantage du second siege vient de TOUS
        les adversaires ou d'un seul. La question est concrete — un bot qui prend l'initiative sur
        les objectifs punit surtout le joueur qui subit le premier tour — et l'agregat pondere la
        noie.

        Comme `log_faction_bot_win_rates`, ces cellules sont des win-rates BRUTS incluant le
        holdout : leur moyenne ne redonne pas l'agregat pondere, et c'est voulu.
        """
        if not isinstance(seat_bot_win_rates, dict):
            raise TypeError(
                f"seat_bot_win_rates must be dict "
                f"(got {type(seat_bot_win_rates).__name__})"
            )
        x = step if step is not None else self.episode_count
        for seat, per_bot in seat_bot_win_rates.items():
            for bot_name, win_rate in per_bot.items():
                self.writer.add_scalar(
                    f'bot_eval/seat/{seat}/vs_{bot_name}', float(win_rate), x
                )

    def log_checkpoint_evaluations(
        self,
        ckpt_results: Dict[str, Any],
        step: Optional[int] = None,
    ) -> None:
        """Win-rate vs chaque checkpoint figé (R0b).

        Publie `bot_eval/vs_ckpt_<key>` pour chaque entrée (ratios + compteurs W/L/D).
        Agrégats dans `00_critical/` calculés sur les seuls ratios :
        - `00_critical/ckpt_min`  : barreau le plus difficile (le modèle le plus fort)
        - `00_critical/ckpt_mean` : moyenne sur tous les barreaux

        Hors sélection et hors gate : indicateur uniquement.
        Ne publie rien si ckpt_results est vide.
        """
        if not ckpt_results:
            return
        x = step if step is not None else self.episode_count
        write_ckpt_scalars(self.writer, ckpt_results, x)

    def log_behavioral_profile(
        self,
        profile: Dict[str, Dict[str, Dict[str, Any]]],
        step: Optional[int] = None,
    ) -> None:
        """Profile comportemental par adversaire et par issue.

        Profile structure : {bot_name: {issue_label: {metric: value}}}
        Publie sous `bot_eval/profile/<bot>/<metric>` (issue non visible en TensorBoard —
        la ventilation se fait dans la serie temporelle par le marqueur d'episode).
        Chaque (bot, metric) produit sa propre courbe ; les issues sont additionnees.
        """
        x = step if step is not None else self.episode_count
        if not isinstance(profile, dict):
            return
        for bot_name, issues_data in profile.items():
            if not isinstance(issues_data, dict):
                continue
            aggregated: Dict[str, float] = {}
            for issue_label, metrics in issues_data.items():
                if not isinstance(metrics, dict):
                    continue
                for metric, value in metrics.items():
                    if not isinstance(value, (int, float)):
                        continue
                    aggregated[metric] = aggregated.get(metric, 0.0) + float(value)
            for metric, value in aggregated.items():
                self.writer.add_scalar(f"bot_eval/profile/{bot_name}/{metric}", value, x)

    def log_holdout_split_metrics(self, split_metrics: Dict[str, float]) -> None:
        """Log holdout split aggregates to TensorBoard."""
        if 'holdout_regular_mean' in split_metrics:
            self.writer.add_scalar(
                'bot_eval/holdout_regular_mean',
                float(split_metrics['holdout_regular_mean']),
                self.episode_count
            )
        if 'holdout_hard_mean' in split_metrics:
            self.writer.add_scalar(
                'bot_eval/holdout_hard_mean',
                float(split_metrics['holdout_hard_mean']),
                self.episode_count
            )
        if 'holdout_overall_mean' in split_metrics:
            self.writer.add_scalar(
                'bot_eval/holdout_overall_mean',
                float(split_metrics['holdout_overall_mean']),
                self.episode_count
            )

    def log_scenario_split_scores(self, split_scores: Dict[str, float]) -> None:
        """Log per-scenario split scores under dedicated category."""
        for key, value in split_scores.items():
            self.writer.add_scalar(
                f'bot_split/{key}',
                float(value),
                self.episode_count
            )

    def _calculate_smoothed_metric(self, values: List[float], window_size: int = 20) -> float:
        """
        Calculate exponentially weighted moving average (EWMA) for smooth trend visualization.
        
        Args:
            values: List of raw metric values
            window_size: Window size for smoothing (default: 20 episodes)
        
        Returns:
            Smoothed value using EWMA
        """
        if not values:
            return 0.0
        
        if len(values) < window_size:
            # Not enough data - return simple mean
            return float(np.mean(values))
        
        # Use last N values for rolling mean
        recent_values = values[-window_size:]
        return float(np.mean(recent_values))

    @staticmethod
    def _metric_slug(name: str) -> str:
        """Convert a unit name to a TensorBoard-safe metric suffix."""
        normalized = "".join(ch if ch.isalnum() else "_" for ch in str(name)).strip("_").lower()
        if not normalized:
            raise ValueError(f"Cannot build metric slug from empty unit name: {name!r}")
        return normalized
    
    def get_performance_summary(self) -> Dict[str, float]:
        """Get current performance summary for monitoring"""
        summary = {}
        
        # Recent win rate (last 100 episodes)
        if len(self.win_rate_window) >= 10:
            summary['win_rate_100ep'] = np.mean(self.win_rate_window)
        
        # Overall statistics
        if len(self.all_episode_rewards) >= 10:
            summary['avg_reward_overall'] = np.mean(self.all_episode_rewards)
            summary['total_episodes'] = len(self.all_episode_rewards)
        
        if len(self.all_episode_wins) >= 10:
            summary['win_rate_overall'] = np.mean(self.all_episode_wins)
        
        # Hyperparameter health indicators
        if len(self.hyperparameter_tracking['learning_rates']) >= 10:
            summary['current_learning_rate'] = self.hyperparameter_tracking['learning_rates'][-1]
        
        if len(self.hyperparameter_tracking['entropy_losses']) >= 10:
            summary['avg_entropy_loss'] = np.mean(self.hyperparameter_tracking['entropy_losses'][-100:])
        
        if len(self.hyperparameter_tracking['clip_fractions']) >= 10:
            summary['avg_clip_fraction'] = np.mean(self.hyperparameter_tracking['clip_fractions'][-100:])
        
        if len(self.hyperparameter_tracking['approx_kls']) >= 10:
            summary['avg_approx_kl'] = np.mean(self.hyperparameter_tracking['approx_kls'][-100:])
        
        return summary
    
    def close(self):
        """Close tensorboard writer"""
        self.writer.close()

class TrainingMonitor:
    """Monitor training health and provide alerts based on essential metrics"""
    
    def __init__(self, thresholds: Dict[str, float]):
        self.thresholds = thresholds
    
    def check_training_health(self, metrics_summary: Dict[str, float]) -> List[str]:
        """Check training health and return alerts"""
        alerts = []
        
        # Check win rate (recent 100 episodes)
        if 'win_rate_100ep' in metrics_summary:
            win_rate = metrics_summary['win_rate_100ep']
            min_win_rate = require_key(self.thresholds, 'min_win_rate')
            if win_rate < min_win_rate:
                alerts.append(f"⚠️ Win rate ({win_rate:.1%}) below threshold ({min_win_rate:.1%})")
        
        # Check overall win rate
        if 'win_rate_overall' in metrics_summary:
            overall_win_rate = metrics_summary['win_rate_overall']
            if overall_win_rate < 0.4:
                alerts.append(f"⚠️ Overall win rate low ({overall_win_rate:.1%}) - may need training adjustment")
        
        # Check episode count
        if 'total_episodes' in metrics_summary:
            total_episodes = metrics_summary['total_episodes']
            if total_episodes < 100:
                alerts.append(f"ℹ️ Early training stage ({total_episodes} episodes) - metrics may be unstable")
        
        return alerts

# Integration function for existing training loop
def create_metrics_tracker(agent_key: str, config: Dict[str, Any]) -> W40KMetricsTracker:
    """Factory function to create metrics tracker with config"""
    log_dir = require_key(config, 'tensorboard_log')
    perf_window, perf_window_fast = resolve_perf_windows(config)
    return W40KMetricsTracker(
        agent_key, log_dir, perf_window=perf_window, perf_window_fast=perf_window_fast
    )