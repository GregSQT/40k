#!/usr/bin/env python3
"""
ai/env_wrappers.py - Gym environment wrappers for training

Contains:
- BotControlledEnv: Bot-controlled opponent wrapper for evaluation
- SelfPlayWrapper: Self-play training wrapper with frozen model

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import gymnasium as gym
from typing import Callable, Dict, List, NamedTuple, Optional, Any, Tuple, TYPE_CHECKING, cast
import random
import os
import time
import hashlib
import numpy as np
from shared.data_validation import require_key, require_positive_int, require_present
from ai.curriculum import ramped_ratio
from shared.torch_safe_globals import register_torch_safe_globals
from engine.action_decoder import ActionValidationError
from engine.debug_trace import CH_BOT_LOOP, channel_enabled, trace

# Avant tout `MaskablePPO.load` de ce module : torch >= 2.6 charge en `weights_only=True`.
register_torch_safe_globals()


def _trace_sampled(count: int) -> bool:
    """Cadence d'echantillonnage des traces de boucle : les 5 premieres, puis une sur 25.

    Ecrite sept fois a la main, elle avait DEJA diverge (`< 5` sur un site, `<= 5` sur les six
    autres) : une boucle tracait quatre iterations, les autres cinq. Un seul point de verite.
    """
    return count <= 5 or count % 25 == 0
from engine.episode_schedule import episodes_per_env
from engine.agent_decision import read_pending_agent_decision
from engine import macro_intents as mi

if TYPE_CHECKING:
    from engine.w40k_core import W40KEngine

__all__ = ['BotControlledEnv', 'SelfPlayWrapper', 'unwrap_engine']
PLAYER_ONE_ID = 1
PLAYER_TWO_ID = 2


def _read_pending_oath_selection(game_state: Dict[str, Any]) -> Any:
    """Lecteur du mécanisme Oath, à la forme des autres : ``None`` = aucune désignation en attente."""
    return game_state.get("pending_oath_selection")  # get allowed : None = aucune


def _read_pending_coherency_removal(game_state: Dict[str, Any]) -> Any:
    """Lecteur du mécanisme retrait cohérence (03.03) : ``None`` = aucune suppression en attente."""
    return game_state.get("pending_coherency_removal")  # get allowed : None = aucun


def _read_pending_fight_weapon_select(game_state: Dict[str, Any]) -> Any:
    """Lecteur du mécanisme sélection arme CC (§0.69) : ``None`` = aucune sélection en attente."""
    return game_state.get("pending_fight_weapon_select")  # get allowed : None = aucune


def _read_pending_shoot_weapon_sel(game_state: Dict[str, Any]) -> Any:
    """Lecteur du split-fire tir (P3-8) — SHOOT_WEAPON_SEL : arme à sélectionner (pending_weapon None)."""
    sw = game_state.get("pending_shoot_weapon_split")  # get allowed : None = aucun split-fire
    return sw if sw is not None and sw.get("pending_weapon") is None else None  # get allowed


def _read_pending_shoot_split_target(game_state: Dict[str, Any]) -> Any:
    """Lecteur du split-fire tir (P3-8) — SHOOT_SLOT : cible à sélectionner (pending_weapon armé)."""
    sw = game_state.get("pending_shoot_weapon_split")  # get allowed : None = aucun split-fire
    return sw if sw is not None and sw.get("pending_weapon") is not None else None  # get allowed


#: LES POINTS DE CHOIX JOUEUR sur lesquels le moteur s'ARRÊTE, chacun avec la famille de slots qui
#: y répond et le libellé de son message d'erreur. UNE table, DEUX consommateurs — le prédicat
#: `engine_is_paused_on_player_choice` (sites à modèle) et le tirage
#: `random_action_for_pending_choice` (sites bot).
#:
#: POURQUOI UNE TABLE. Ces mécanismes étaient énumérés à la main sur chaque site. Quand l'Oath est
#: arrivé après les replis, les quatre sites testaient encore `pending_agent_decision` SEUL : ils
#: ont dû être corrigés d'un coup, et le crash mesuré (`convert_squad_action ... action 1024`)
#: était la facture. Un troisième mécanisme n'ajoute désormais qu'une LIGNE ici, et les deux
#: consommateurs le voient ensemble — ils ne peuvent plus diverger l'un de l'autre.
#:
#: L'ORDRE EST LE CONTRAT : décision agent d'abord, Oath ensuite, comme sur les sites d'origine.
_PLAYER_CHOICE_MECHANISMS: Tuple[
    Tuple[Callable[[Dict[str, Any]], Any], range, str], ...
] = (
    # (lecteur d'état, famille de slots qui répond, libellé du mécanisme)
    (read_pending_agent_decision, mi.CHOICE_SLOTS, "decision agent"),
    (_read_pending_oath_selection, mi.OATH_SLOTS, "designation d'Oath"),
    (_read_pending_coherency_removal, mi.COHERENCY_SLOTS, "retrait coherence"),
    (_read_pending_fight_weapon_select, mi.FIGHT_WEAPON_SLOTS, "arme CC"),
    (_read_pending_shoot_weapon_sel, mi.SHOOT_WEAPON_SEL_SLOTS, "split-fire arme TIR"),
    (_read_pending_shoot_split_target, mi.SHOOT_SLOTS, "split-fire cible TIR"),
)


def engine_is_paused_on_player_choice(game_state: Dict[str, Any]) -> bool:
    """True quand le moteur est ARRÊTÉ sur un point de choix joueur, donc que `ACTION_WAIT` est
    HORS MASQUE.

    C'est le prédicat des quatre replis « pool vide -> WAIT » de ce module. Le pool d'unités
    éligibles est vide dans cet état — non pas parce que la phase est finie, mais parce que le
    moteur attend une réponse — et sortir sur `ACTION_WAIT` rend alors une action que le masque
    n'ouvre pas : `convert_squad_action` lève, et le choix est perdu.

    Les mécanismes couverts sont ceux de `_PLAYER_CHOICE_MECHANISMS` :
      - `pending_agent_decision` (V11 §9.3 P2) : candidats joués par `CHOICE_i` ;
      - `pending_oath_selection` (chantier 03) : cible jouée par `OATH_SLOT_i`, désignation NON
        OPTIONNELLE — le masque n'ouvre donc ni WAIT ni zone intent.
    """
    return any(
        read(game_state) is not None for read, _slots, _label in _PLAYER_CHOICE_MECHANISMS
    )


def random_action_for_pending_choice(
    game_state: Dict[str, Any], action_mask: Any, wrapper: str
) -> Optional[int]:
    """L'action de TIRAGE qui répond au point de choix en attente, ou ``None`` s'il n'y en a pas.

    Le bot joue par tirage tout choix qu'il ne modélise pas — c'était jusqu'ici l'action de
    l'AGENT qui tranchait (`raw_action_int % len(options)`), donc l'agent décidait à la place de
    son adversaire.

    Lève si le mécanisme est en attente mais qu'aucun de ses slots n'est ouvert : c'est un état
    incohérent du masque, pas un cas à absorber par un repli.
    """
    for read, slots, label in _PLAYER_CHOICE_MECHANISMS:
        if read(game_state) is None:
            continue
        legal = [index for index in slots if bool(action_mask[index])]
        if not legal:
            raise RuntimeError(
                f"{wrapper}: {label} en attente sans aucun slot autorise par le masque."
            )
        return int(random.choice(legal))
    return None


class MaskDecision(NamedTuple):
    """Qui decide, et le masque SUR LEQUEL cette reponse a ete etablie.

    Le wrapper posait la question « a qui est la decision ? » puis, deux lignes plus loin,
    reconstruisait le masque a l'identique pour choisir l'action — la meme construction, sur le
    meme etat, deux fois. Rendre le masque avec la reponse supprime le second calcul.

    Ce n'est PAS un cache : rien n'est conserve entre deux pas, il n'y a donc rien a perimer. Un
    objet de ce type ne vaut que pour l'etat qui l'a produit, et sa validite se lit sur le site
    d'appel : entre sa production et sa consommation, il ne doit RIEN se passer qui touche
    `game_state`. LA REGLE, enoncee ici une seule fois et referencee ailleurs : tout appel a
    `env.step` (ou a `_build_observation`, qui mute aussi) remet la valeur portee a None, et
    l'appel suivant la recalcule.

    Pourquoi pas une memoisation sur un compteur de revision d'etat : le masque n'est pas pur (il
    tire le jet d'Advance au premier appel d'une activation et memoise la carte de cellules que le
    decodage rejouera). Une carte rejouee sur un etat qui a bouge fait executer au moteur un
    deplacement coherent mais FAUX, sans lever : l'agent apprendrait sur des transitions qui ne
    sont pas celles qu'on lui a montrees. Les filets de securite sont `W40K_MASK_VERIFY=1`
    (carte memoisee) et `W40K_MASK_VERIFY=2` (masque transmis lui-meme) — deux niveaux parce que
    le second coute une copie profonde par appel, cf. `engine.mask_verification`.

    Deux champs seulement, plus ce qui s'en derive : porter `has_valid_actions` et `eligible_count`
    en dur obligeait a les tenir coherents sur chaque site de construction.
    """

    decision_owner: Optional[int]
    action_mask: np.ndarray
    eligible_units: List[Dict[str, Any]]

    @property
    def has_valid_actions(self) -> bool:
        # `asarray` et pas `.any()` direct : les doublures de test rendent des listes.
        return bool(np.any(np.asarray(self.action_mask, dtype=bool)))

    @property
    def eligible_count(self) -> int:
        return len(self.eligible_units)


def mask_pair_of(
    decision: Optional[MaskDecision],
) -> Optional[tuple[np.ndarray, List[Dict[str, Any]]]]:
    """Le couple attendu par `W40KEngine._build_observation`, ou None si aucune decision portee.

    Fonction de module et pas methode : c'est le cas `None` — « aucune decision en main » — qu'elle
    sert, et il n'a pas de receveur.
    """
    if decision is None:
        return None
    return decision.action_mask, decision.eligible_units

# Membres du moteur que CES wrappers utilisent sur `self.engine`. C'est le contrat exact
# verifie par `unwrap_engine` : rien de plus (on n'exige pas ce qu'on n'appelle pas), rien de
# moins (chaque acces d'ici est couvert). Toute nouvelle utilisation de `self.engine.<x>` dans
# ce module doit etre ajoutee ici, sinon la verification cesse de prouver ce qu'elle affirme.
# CONSEQUENCE EN AVAL : ce tuple a DEUX consommateurs. Tout membre ajoute ici doit aussi etre
# expose par le double `_DummyEngine` des tests, sans quoi `unwrap_engine` refuse de construire
# les wrappers et tous les tests qui en montent un tombent d'un coup.
ENGINE_CONTRACT_ATTRS = (
    "game_state",
    "action_decoder",
    "config",
    "get_turn_step_limit",
    "step_with_mask",
    "get_action_mask",
    "auto_deployment_action",
    "_build_observation",
    "defer_observation",
    "_check_game_over",
    "_determine_winner_with_method",
)

#: Cles de l'`info` moteur qui decrivent l'action de l'AGENT et doivent survivre au step gym.
#:
#: Un step gym enchaine plusieurs steps moteur : celui de l'agent, puis ceux de l'adversaire
#: jusqu'au retour de la main. Gym n'a qu'un `info` a rendre, et c'est naturellement celui du
#: DERNIER step — donc celui de l'adversaire. Les consommateurs (MetricsCollectionCallback)
#: lisent pourtant ces cles-la comme decrivant l'agent, puisqu'elles cotoient
#: `is_controlled_action`. Elles sont donc relevees sur le step de l'agent et reappliquees
#: avant le retour.
#:
#: Ce qui n'est PAS ici et n'y a pas sa place : tout ce qui decrit l'ETAT DE SORTIE du step gym
#: (`episode`, `tactical_data`, `winner`, `action_logs`) — c'est bien le dernier step moteur qui
#: fait foi pour ceux-la.
AGENT_STEP_INFO_KEYS = (
    "action",
    "intent_value",
    "zone_control",
    "is_controlled_action",
    "phase",
    "success",
    "charge_succeeded",
)


def apply_agent_step_info(info: Dict[str, Any], agent_step_info: Dict[str, Any]) -> None:
    """Remplace EN BLOC les cles de `AGENT_STEP_INFO_KEYS` par celles du step de l'agent.

    Remplacer, et non `update` : une cle posee par l'adversaire mais ABSENTE du step de l'agent
    survivrait a une simple mise a jour, sous le `is_controlled_action=True` recolle juste a
    cote. Cas concret : l'agent tire (aucun `charge_succeeded` dans son info), l'adversaire
    enchaine sur une charge reussie — `charge_succeeded=True` resterait, et la charge de
    l'adversaire serait comptee comme celle de l'agent. Ces cles sont optionnelles par nature
    (posees par le resultat du handler, donc seulement quand elles s'appliquent) : leur ABSENCE
    porte autant d'information que leur valeur.
    """
    for key in AGENT_STEP_INFO_KEYS:
        info.pop(key, None)
    info.update(agent_step_info)


def unwrap_engine(env: Any, owner: str) -> "W40KEngine":
    """Deballe la pile de wrappers gym jusqu'au moteur, et PROUVE ce qu'elle trouve.

    L'ordre d'emballage (`BotControlledEnv(ActionMasker(W40KEngine))`, idem pour
    `SelfPlayWrapper`) n'est garanti nulle part : il est reconstruit a l'identique sur huit
    sites d'appel (ai/train.py, ai/training_utils.py, ai/bot_evaluation.py,
    scripts/roster_matchup_stats.py). Les deux deballages precedents en tiraient une
    affirmation jamais verifiee (`cast("W40KEngine", ...)`), et divergeaient meme entre eux :
    l'un pelait UN niveau, l'autre TOUS. Si l'ordre changeait, l'erreur ne surgissait pas ici
    mais au premier attribut manquant, des couches plus loin.

    On pele donc tous les `gym.Wrapper` (un env non emballe est un cas legitime : les tests
    passent le moteur nu), puis on verifie que le noyau expose bien ENGINE_CONTRACT_ATTRS.
    A defaut : erreur explicite nommant la pile traversee, le type atteint et les membres
    manquants — jamais de repli silencieux.

    Cout : O(profondeur de la pile), une seule fois par `__init__` de wrapper. Aucun cout sur
    le chemin chaud — `self.engine` est resolu a la construction, jamais par pas de simulation.
    """
    stack = []
    overriding_step = []
    current = env
    while isinstance(current, gym.Wrapper):
        stack.append(type(current).__name__)
        # Ces wrappers appellent `engine.step_with_mask` DIRECTEMENT (cf. `_engine_step`) : le
        # 5-uplet de gym n'a pas de place pour le masque. Court-circuiter la pile n'est sans effet
        # que si aucune couche traversee ne fait quoi que ce soit dans `step` — c'est le cas
        # d'`ActionMasker`, qui n'ajoute que `action_masks`. On le VERIFIE au lieu de le supposer :
        # une couche qui surchargerait `step` verrait son traitement saute en silence.
        if type(current).step is not gym.Wrapper.step:
            overriding_step.append(type(current).__name__)
        current = current.env
    if overriding_step:
        raise TypeError(
            f"{owner}: la pile gym ({' -> '.join(stack)}) contient une ou des couches qui "
            f"redefinissent `step` : {overriding_step}. Ce module appelle "
            f"`engine.step_with_mask` directement pour transmettre le masque, ce qui SAUTERAIT "
            f"leur traitement. Faire passer le masque par ces couches, ou les retirer de la pile."
        )
    missing = [attr for attr in ENGINE_CONTRACT_ATTRS if not hasattr(current, attr)]
    if missing:
        traversed = " -> ".join(stack + [type(current).__name__]) if stack else type(current).__name__
        raise TypeError(
            f"{owner}: le deballage de la pile gym ({traversed}) atteint "
            f"{type(current).__name__}, qui n'honore pas le contrat moteur : membres manquants "
            f"{missing}. Attendu : un W40KEngine (ou un double de test exposant "
            f"{list(ENGINE_CONTRACT_ATTRS)})."
        )
    # `cast` justifie : les sept membres que ce module utilise viennent d'etre verifies un a un
    # sur l'objet reellement atteint, et le noyau n'est plus un gym.Wrapper.
    return cast("W40KEngine", current)


class BotControlledEnv(gym.Wrapper):
    """Wrapper for bot-controlled Player 2 evaluation.

    Accepts either:
    - bot: single bot instance (for evaluation, deterministic opponent)
    - bots: list of bot instances (for training, random selection per episode)
    """

    def __init__(
        self,
        base_env,
        bot=None,
        unit_registry=None,
        bots=None,
        agent_seat_mode: str = "p1",
        agent_seat_p2_ratio: Optional[float] = None,
        global_seed: Optional[int] = None,
        env_rank: int = 0,
        episode_start_index: int = 0,
        self_play_opponent_enabled: bool = False,
        self_play_ratio_start: Optional[float] = None,
        self_play_ratio_end: Optional[float] = None,
        self_play_total_episodes: Optional[int] = None,
        self_play_warmup_episodes: Optional[int] = None,
        self_play_n_envs: Optional[int] = None,
        self_play_snapshot_path: Optional[str] = None,
        self_play_snapshot_refresh_episodes: Optional[int] = None,
        self_play_snapshot_device: Optional[str] = None,
        self_play_deterministic: bool = False,
        self_play_snapshot_frozen: bool = False,
        self_play_snapshot_label: Optional[str] = None,
        self_play_vec_normalize_enabled: bool = False,
        self_play_vec_normalize_eval_enabled: bool = False,
    ):
        super().__init__(base_env)
        # Support: bots=[...] for random selection, or bot=X for single opponent
        # Also accept legacy positional: BotControlledEnv(env, bot, unit_registry)
        if bots is not None and len(bots) > 0:
            self._bots = list(bots)
            self.bot = self._bots[0]
            self._use_random_bots = True
        elif bot is not None and not isinstance(bot, (list, tuple)):
            self._bots = None
            self.bot = bot
            self._use_random_bots = False
        else:
            raise ValueError("BotControlledEnv requires either 'bot' or 'bots' (non-empty list)")
        self.unit_registry = unit_registry
        self.episode_reward = 0.0
        self.episode_length = 0
        if agent_seat_mode not in {"p1", "p2", "random"}:
            raise ValueError(
                f"agent_seat_mode must be one of 'p1', 'p2', 'random' (got {agent_seat_mode!r})"
            )
        self.agent_seat_mode = agent_seat_mode
        if self.agent_seat_mode == "random":
            if global_seed is None:
                raise ValueError("global_seed is required when agent_seat_mode='random'")
            self._global_seed = int(global_seed)
        else:
            self._global_seed = None
        self._agent_seat_p2_ratio = self._resolve_seat_p2_ratio(agent_seat_p2_ratio)
        if episode_start_index < 0:
            raise ValueError(f"episode_start_index must be >= 0 (got {episode_start_index})")
        self._episode_index = int(episode_start_index)
        self._env_rank = int(env_rank)
        self.controlled_player = 1
        self.bot_player = 2
        self.episodes_agent_p1 = 0
        self.episodes_agent_p2 = 0
        self.timesteps_agent_p1 = 0
        self.timesteps_agent_p2 = 0
        self._self_play_opponent_enabled = bool(self_play_opponent_enabled)
        self._episode_uses_self_play_opponent = False
        self._self_play_ratio_current = 0.0
        self._self_play_episodes = 0
        self._bot_episodes = 0
        self._frozen_model = None
        self._frozen_model_mtime: Optional[float] = None
        self._episodes_since_snapshot_refresh = 0
        self._self_play_deterministic = bool(self_play_deterministic)
        # FIGE : l'adversaire de cet environnement est une archive qui ne bougera pas du run
        # (membre du pool d'une etape de curriculum, checkpoint etalon R0b). Il est charge UNE
        # fois et jamais relu. Sans ce drapeau, le seul moyen de ne pas le recharger etait de
        # poser un `refresh_episodes` plus grand que le nombre d'episodes du run — un nombre qui
        # ne veut rien dire, et que les appelants recopiaient chacun a leur facon.
        self._self_play_snapshot_frozen = bool(self_play_snapshot_frozen)
        self._self_play_vec_normalize_enabled = bool(self_play_vec_normalize_enabled)
        self._self_play_vec_normalize_eval_enabled = bool(self_play_vec_normalize_eval_enabled)
        if self._self_play_opponent_enabled:
            if self_play_ratio_start is None:
                raise KeyError(
                    "self_play_ratio_start is required when self_play_opponent_enabled=true"
                )
            if self_play_ratio_end is None:
                raise KeyError(
                    "self_play_ratio_end is required when self_play_opponent_enabled=true"
                )
            if self_play_total_episodes is None:
                raise KeyError(
                    "self_play_total_episodes is required when self_play_opponent_enabled=true"
                )
            if self_play_warmup_episodes is None:
                raise KeyError(
                    "self_play_warmup_episodes is required when self_play_opponent_enabled=true"
                )
            if self_play_n_envs is None:
                raise KeyError(
                    "self_play_n_envs is required when self_play_opponent_enabled=true : "
                    "`self_play_total_episodes` est un budget GLOBAL alors que la rampe est "
                    "pilotee par le compteur LOCAL a cet environnement "
                    "(cf. engine/episode_schedule.py)."
                )
            if self_play_snapshot_path is None or not str(self_play_snapshot_path).strip():
                raise KeyError(
                    "self_play_snapshot_path is required when self_play_opponent_enabled=true"
                )
            if not str(self_play_snapshot_label or "").strip():
                raise KeyError(
                    "self_play_snapshot_label is required when self_play_opponent_enabled=true"
                )
            if self._self_play_snapshot_frozen:
                if self_play_snapshot_refresh_episodes is not None:
                    raise ValueError(
                        "self_play_snapshot_refresh_episodes n'a pas de sens avec "
                        "self_play_snapshot_frozen=true : l'archive ne change pas, elle est "
                        "chargee une fois."
                    )
                resolved_refresh_episodes = 0
            elif self_play_snapshot_refresh_episodes is None:
                raise KeyError(
                    "self_play_snapshot_refresh_episodes is required when self_play_opponent_enabled=true"
                )
            else:
                resolved_refresh_episodes = int(self_play_snapshot_refresh_episodes)
            if self_play_snapshot_device is None or not str(self_play_snapshot_device).strip():
                raise KeyError(
                    "self_play_snapshot_device is required when self_play_opponent_enabled=true"
                )
            self._self_play_ratio_start = float(self_play_ratio_start)
            self._self_play_ratio_end = float(self_play_ratio_end)
            self._self_play_total_episodes = int(self_play_total_episodes)
            self._self_play_warmup_episodes = int(self_play_warmup_episodes)
            self._self_play_snapshot_path = str(self_play_snapshot_path)
            self._self_play_snapshot_label = str(self_play_snapshot_label).strip()
            self._self_play_snapshot_refresh_episodes = resolved_refresh_episodes
            self._self_play_snapshot_device = str(self_play_snapshot_device).strip().lower()
            if not (0.0 <= self._self_play_ratio_start <= 1.0):
                raise ValueError(
                    f"self_play_ratio_start must be in [0,1] "
                    f"(got {self._self_play_ratio_start})"
                )
            if not (0.0 <= self._self_play_ratio_end <= 1.0):
                raise ValueError(
                    f"self_play_ratio_end must be in [0,1] "
                    f"(got {self._self_play_ratio_end})"
                )
            if self._self_play_total_episodes <= 0:
                raise ValueError(
                    f"self_play_total_episodes must be > 0 "
                    f"(got {self._self_play_total_episodes})"
                )
            if self._self_play_warmup_episodes < 0:
                raise ValueError(
                    f"self_play_warmup_episodes must be >= 0 "
                    f"(got {self._self_play_warmup_episodes})"
                )
            if self._self_play_warmup_episodes > self._self_play_total_episodes:
                raise ValueError(
                    "self_play_warmup_episodes must be <= self_play_total_episodes "
                    f"(got {self._self_play_warmup_episodes} > "
                    f"{self._self_play_total_episodes})"
                )
            if (
                not self._self_play_snapshot_frozen
                and self._self_play_snapshot_refresh_episodes <= 0
            ):
                raise ValueError(
                    "self_play_snapshot_refresh_episodes must be > 0 "
                    f"(got {self._self_play_snapshot_refresh_episodes})"
                )
            if self._self_play_snapshot_device not in {"cpu", "auto"}:
                raise ValueError(
                    "self_play_snapshot_device must be either 'cpu' or 'auto' "
                    f"(got {self._self_play_snapshot_device!r})"
                )
            # PASSAGE EN BUDGET PAR ENVIRONNEMENT (pourquoi : engine/episode_schedule.py).
            # `_episode_index` ne compte que les episodes de CE wrapper. Les deux bornes se
            # convertissent ENSEMBLE, sinon le warmup mangerait toute la rampe.
            n_envs = require_positive_int(self_play_n_envs, "self_play_n_envs")
            self._self_play_total_episodes = episodes_per_env(self._self_play_total_episodes, n_envs)
            self._self_play_warmup_episodes = (
                episodes_per_env(self._self_play_warmup_episodes, n_envs)
                if self._self_play_warmup_episodes > 0 else 0
            )
        else:
            self._self_play_ratio_start = 0.0
            self._self_play_ratio_end = 0.0
            self._self_play_total_episodes = 1
            self._self_play_warmup_episodes = 0
            self._self_play_snapshot_path = ""
            self._self_play_snapshot_label = ""
            self._self_play_snapshot_refresh_episodes = 1
            self._self_play_snapshot_device = "auto"

        # Deballage verifie de la pile gym (cf. unwrap_engine).
        # self.env is set by gym.Wrapper.__init__ to base_env
        self.engine: "W40KEngine" = unwrap_engine(self.env, "BotControlledEnv")

        # DIAGNOSTIC: Track shoot phase decisions FOR BOT
        self.shoot_opportunities = 0  # Times shoot was available
        self.shoot_actions = 0        # Times bot actually shot
        self.wait_actions = 0          # Times bot waited in shoot phase

        # DIAGNOSTIC: Track shoot phase decisions FOR AI AGENT
        self.ai_shoot_opportunities = 0
        self.ai_shoot_actions = 0
        self.ai_wait_actions = 0
        # LOG TEMPORAIRE: time between step() return and next step() call (--debug)
        self._last_step_return_time = None
        # Decision servie a MaskablePPO par `action_masks()`, et REPRISE en entree du `step`
        # suivant — cf. la docstring d'`action_masks` pour le cycle de vie.
        self._served_decision: Optional[MaskDecision] = None

    def _run_bot_until_not_bot_turn(
        self,
        terminated: bool,
        truncated: bool,
        obs: Any,
        info: dict,
        debug_mode: bool,
        accumulate_reward: bool,
        cumulative_reward: float,
        decision: Optional[MaskDecision] = None,
    ) -> tuple[Any, bool, bool, dict, float, Optional[MaskDecision]]:
        """Execute consecutive bot turns until control leaves bot player or episode ends.

        `decision` (cf. `MaskDecision` pour la regle) : deja etablie pour l'etat courant, elle sert
        la premiere iteration. Rendue en dernier element quand la boucle sort parce que la decision
        a change de camp — l'appelant la reprend telle quelle.
        """
        bot_loop_count = 0
        # Borne des activations consecutives du bot sur un tour : meme source que le
        # moteur (derivee des figurines en jeu), sinon le bot serait coupe a tort des
        # qu'une escouade nombreuse a besoin de plus d'actions que l'ancienne constante.
        max_bot_iterations = self.engine.get_turn_step_limit()
        trace(CH_BOT_LOOP, debug_mode,
              "BotControlledEnv._run_bot_until_not_bot_turn enter env_rank=%s", self._env_rank)
        while not (terminated or truncated):
            if decision is None:
                decision = self._get_decision_owner_from_mask()
            decision_owner, has_valid_actions = decision.decision_owner, decision.has_valid_actions
            if debug_mode and _trace_sampled(bot_loop_count) and channel_enabled(CH_BOT_LOOP, debug_mode):
                trace(
                    CH_BOT_LOOP, debug_mode,
                    "BotControlledEnv._run_bot_until_not_bot_turn env_rank=%s loop=%s "
                    "decision_owner=%s has_valid_actions=%s phase=%s current_player=%s bot_player=%s",
                    self._env_rank, bot_loop_count, decision_owner, has_valid_actions,
                    str(require_key(self.engine.game_state, "phase")),
                    int(require_key(self.engine.game_state, "current_player")),
                    self.bot_player,
                )
            if decision_owner != self.bot_player:
                break
            if not has_valid_actions:
                raise RuntimeError(
                    "BotControlledEnv detected bot-owned eligible units with empty action mask. "
                    "Engine must expose at least one legal action for eligible owner."
                )
            bot_loop_count += 1
            if bot_loop_count > max_bot_iterations:
                current_phase = require_key(self.engine.game_state, "phase")
                print(
                    f"\n[DEBUG] BotControlledEnv: Infinite loop detected! "
                    f"Loop count: {bot_loop_count}, episode_length: {self.episode_length}, phase: {current_phase}",
                    flush=True,
                )
                raise RuntimeError(
                    f"BotControlledEnv infinite loop: {bot_loop_count} iterations, phase={current_phase}"
                )
            debug_bot = self.episode_length < 10
            bot_action, decision = self._get_opponent_action(debug=debug_bot, decision=decision)
            if debug_mode and _trace_sampled(bot_loop_count) and channel_enabled(CH_BOT_LOOP, debug_mode):
                trace(
                    CH_BOT_LOOP, debug_mode,
                    "BotControlledEnv._run_bot_until_not_bot_turn env_rank=%s loop=%s "
                    "bot_action=%s phase=%s before self.env.step",
                    self._env_rank, bot_loop_count, bot_action,
                    str(require_key(self.engine.game_state, "phase")),
                )
            t0_bot = time.perf_counter() if debug_mode else None
            # La decision en main (si elle a survecu au choix de l'adversaire, cf.
            # `_get_opponent_action`) est CONSOMMEE par le step : le moteur ne reconstruit pas le
            # masque de l'etat d'entree. Elle est remplacee par celle de l'etat de sortie — jamais
            # conservee au-dela, donc jamais perimee.
            obs, reward, terminated, truncated, info, decision = self._engine_step(
                bot_action, decision
            )
            if debug_mode and _trace_sampled(bot_loop_count):
                trace(
                    CH_BOT_LOOP, debug_mode,
                    "BotControlledEnv._run_bot_until_not_bot_turn env_rank=%s loop=%s "
                    "after self.env.step(bot_action=%s) terminated=%s truncated=%s",
                    self._env_rank, bot_loop_count, bot_action, terminated, truncated,
                )
            if accumulate_reward:
                cumulative_reward += float(reward)
                self.episode_reward += float(reward)
            if debug_mode and t0_bot is not None:
                ep = int(require_key(self.engine.game_state, "episode_number"))
                step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                duration_s = time.perf_counter() - t0_bot
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                except (OSError, IOError):
                    pass
            self.episode_length += 1
        # Idem : sortie par terminaison -> aucune decision rendue (cf. la borne jumelle dans
        # `_ensure_actionable_controlled_turn`). Le `break` « la decision a change de camp », lui,
        # rend bien la decision fraiche : c'est sa raison d'etre.
        if terminated or truncated:
            decision = None
        if debug_mode and channel_enabled(CH_BOT_LOOP, debug_mode):
            trace(
                CH_BOT_LOOP, debug_mode,
                "BotControlledEnv._run_bot_until_not_bot_turn exit env_rank=%s loops=%s "
                "terminated=%s truncated=%s phase=%s current_player=%s",
                self._env_rank, bot_loop_count, terminated, truncated,
                str(require_key(self.engine.game_state, "phase")),
                int(require_key(self.engine.game_state, "current_player")),
            )
        return obs, terminated, truncated, info, cumulative_reward, decision

    def _get_decision_owner_from_mask(self) -> MaskDecision:
        """
        Determine which player currently owns the decision from eligible units/action mask.

        Rend aussi le masque et le pool qui ont servi a repondre (cf. `MaskDecision`) : l'appelant
        immediatement adjacent les consomme au lieu de les reconstruire.
        """
        # Décision agent en attente (V11 §9.3 P2) : le pool d'unités éligibles est vide par
        # construction (le moteur est arrêté sur un point de choix), mais la décision APPARTIENT à
        # un joueur — celui du prompt. Sans ce cas, le wrapper conclurait « personne ne décide »
        # et tenterait de faire avancer une phase que la décision bloque.
        action_mask, eligible_units = self.engine.action_decoder.get_squad_action_mask_and_eligible_units(
            self.engine.game_state
        )
        return self._decision_from_mask(action_mask, eligible_units)

    def _decision_from_mask(
        self, action_mask: np.ndarray, eligible_units: List[Dict[str, Any]]
    ) -> MaskDecision:
        """Meme reponse, a partir d'un couple DEJA construit — aucune construction ici.

        Scinde de `_get_decision_owner_from_mask` pour que le masque rendu par
        `W40KEngine.step_with_mask` (etat de SORTIE) puisse repondre a « a qui est la decision
        maintenant ? » sans reconstruire. Mesure : 96,5 reconstructions par episode rendaient un
        couple bit-a-bit identique a celui que `step` venait de construire.

        Ne lit `game_state` que pour ce que le couple ne porte pas (decision en attente, phase,
        joueur courant) : ces lectures decrivent l'etat auquel le couple appartient.
        """
        # Une seule construction, avant le test de decision en attente : le decodeur traite ce cas
        # LUI-MEME (il rend le masque des CHOICE et un pool vide, cf. `action_decoder`), donc les
        # deux chemins demandaient deja le meme masque.
        pending_decision = read_pending_agent_decision(self.engine.game_state)
        if pending_decision is not None:
            return MaskDecision(
                int(require_key(pending_decision, "player")), action_mask, eligible_units
            )

        if not eligible_units:
            game_state = self.engine.game_state
            # Un mécanisme de choix en attente (cohérence, arme CC, Oath, decision agent déjà
            # traité ci-dessus) appartient toujours à `current_player`. Consulter la table évite
            # que l'ajout d'un mécanisme hors phase `command` passe inaperçu — le crash mesuré
            # (`convert_squad_action ... action 1024`) était la facture d'un tel oubli.
            if engine_is_paused_on_player_choice(game_state) or (
                game_state.get("phase") == "command"
                and np.any(np.asarray(action_mask, dtype=bool))
            ):
                current_player = int(require_key(game_state, "current_player"))
                return MaskDecision(current_player, action_mask, eligible_units)
            return MaskDecision(None, action_mask, eligible_units)

        owners = {int(require_key(unit, "player")) for unit in eligible_units}
        if len(owners) != 1:
            raise RuntimeError(
                f"Eligible unit pool has mixed owners: {owners}. "
                "Pool must contain units from a single acting side."
            )
        return MaskDecision(owners.pop(), action_mask, eligible_units)

    def _engine_step(
        self, action: int, decision: Optional[MaskDecision]
    ) -> tuple[Any, float, bool, bool, dict, Optional[MaskDecision]]:
        """Un step moteur, masque transmis dans les DEUX sens.

        Passe par `step_with_mask` et non par `self.env.step` : le 5-uplet de gym n'a de place ni
        pour le masque d'entree ni pour celui de sortie. `unwrap_engine` prouve qu'aucun wrapper
        traverse ne redefinit `step`, donc court-circuiter la pile est ici sans effet observable
        (cf. sa verification `step` non surchargee).

        `decision` : celle etablie pour l'etat COURANT, ou None. La regle de validite est celle de
        `MaskDecision` — l'appelant ne la passe que s'il peut prouver que rien n'a touche
        `game_state` depuis sa construction. `W40K_MASK_VERIFY=2` transforme cette preuve en
        mesure (cf. `W40KEngine._verify_supplied_mask`).

        Rend en dernier element la decision de l'etat de SORTIE quand le moteur a construit un
        masque dessus, None sinon — l'appelant la reprend telle quelle ou la construit.
        """
        obs, reward, terminated, truncated, info, out_mask = self.engine.step_with_mask(
            action, mask_and_eligible=mask_pair_of(decision)
        )
        out_decision = (
            self._decision_from_mask(out_mask[0], out_mask[1]) if out_mask is not None else None
        )
        return obs, float(reward), terminated, truncated, info, out_decision

    def _ensure_actionable_controlled_turn(
        self,
        terminated: bool,
        truncated: bool,
        obs: Any,
        info: dict,
        debug_mode: bool,
        accumulate_reward: bool,
        cumulative_reward: float,
        decision: Optional[MaskDecision] = None,
    ) -> tuple[Any, bool, bool, dict, float, Optional[MaskDecision]]:
        """
        Advance deterministic no-choice states so controlled player always gets a non-empty mask.

        Dernier element : cf. `_play_bot_until_control_returns`.
        """
        MAX_ENSURE_ITERATIONS = 2000
        iteration_count = 0
        decision_owner = has_valid_actions = eligible_count = None
        # `decision` (parametre) : deja etablie pour l'etat courant par l'appelant, ou None s'il
        # faut l'etablir (regle : `MaskDecision`). C'est aussi ce qu'on rend a l'appelant : seule la
        # sortie « le joueur controle a une action jouable » la laisse non nulle.
        while not (terminated or truncated):
            iteration_count += 1
            if iteration_count > MAX_ENSURE_ITERATIONS:
                phase = self.engine.game_state.get("phase", "?")
                cp = self.engine.game_state.get("current_player", "?")
                free = self.engine.game_state.get("zone_intent_free_steps_remaining", "?")
                raise RuntimeError(
                    f"_ensure_actionable_controlled_turn infinite loop detected: "
                    f"env_rank={self._env_rank} iterations={iteration_count} "
                    f"phase={phase} current_player={cp} decision_owner={decision_owner} "
                    f"has_valid_actions={has_valid_actions} eligible_count={eligible_count} "
                    f"free_steps={free}"
                )
            if decision is None:
                decision = self._get_decision_owner_from_mask()
            decision_owner = decision.decision_owner
            has_valid_actions = decision.has_valid_actions
            eligible_count = decision.eligible_count
            if debug_mode and _trace_sampled(iteration_count) and channel_enabled(CH_BOT_LOOP, debug_mode):
                trace(
                    CH_BOT_LOOP, debug_mode,
                    "BotControlledEnv._ensure_actionable_controlled_turn env_rank=%s iteration=%s "
                    "decision_owner=%s has_valid_actions=%s eligible_count=%s phase=%s "
                    "current_player=%s controlled_player=%s bot_player=%s",
                    self._env_rank, iteration_count, decision_owner, has_valid_actions, eligible_count,
                    str(require_key(self.engine.game_state, "phase")),
                    int(require_key(self.engine.game_state, "current_player")),
                    self.controlled_player, self.bot_player,
                )

            if decision_owner == self.bot_player:
                # La boucle bot repart de cette decision, et rend celle sur laquelle elle s'arrete :
                # sa sortie « la decision a change de camp » vient d'un masque frais, et rien ne
                # s'execute entre son `break` et l'iteration suivante ici.
                obs, terminated, truncated, info, cumulative_reward, decision = self._run_bot_until_not_bot_turn(
                    terminated=terminated,
                    truncated=truncated,
                    obs=obs,
                    info=info,
                    debug_mode=debug_mode,
                    accumulate_reward=accumulate_reward,
                    cumulative_reward=cumulative_reward,
                    decision=decision,
                )
                if debug_mode and _trace_sampled(iteration_count):
                    trace(
                        CH_BOT_LOOP, debug_mode,
                        "BotControlledEnv._ensure_actionable_controlled_turn env_rank=%s iteration=%s "
                        "branch=bot-run terminated=%s truncated=%s",
                        self._env_rank, iteration_count, terminated, truncated,
                    )
                continue

            if decision_owner == self.controlled_player:
                if has_valid_actions:
                    # DEPLOIEMENT `auto` : le MOTEUR choisit la pose, pas la politique (rampe
                    # `deployment_mode_schedule`). Cet etat est donc absorbe ICI, comme les tours du
                    # bot et les WAIT forces — le rendre a l'apprenant ferait entrer dans le rollout
                    # SB3 une transition dont l'action echantillonnee et le log_prob ne sont pas
                    # ceux qui ont ete joues, et PPO calculerait son ratio dessus.
                    # `auto_deployment_action` ne touche pas `game_state` : la decision reste
                    # valable pour le step qui suit (regle de `MaskDecision`).
                    auto_action = self.engine.auto_deployment_action(decision.action_mask)
                    if auto_action is not None:
                        step_decision, decision = decision, None
                        obs, reward, terminated, truncated, info, decision = self._engine_step(
                            auto_action, step_decision
                        )
                        if accumulate_reward:
                            cumulative_reward += float(reward)
                            self.episode_reward += float(reward)
                        self.episode_length += 1
                        continue
                    trace(
                        CH_BOT_LOOP, debug_mode,
                        "BotControlledEnv._ensure_actionable_controlled_turn env_rank=%s iteration=%s branch=controlled-ready",
                        self._env_rank, iteration_count,
                    )
                    # SEULE sortie qui laisse l'etat intact et un masque frais en main : celle-ci.
                    # Les autres ont deja remis `decision` a None avant de muter l'etat.
                    break
                # Controlled owner selected but no valid action: try explicit WAIT to advance.
            elif decision_owner is None:
                # No eligible units: can be phase transition edge or terminal.
                pass
            else:
                current_player = int(require_key(self.engine.game_state, "current_player"))
                raise RuntimeError(
                    f"Unexpected decision owner {decision_owner} in BotControlledEnv "
                    f"(controlled_player={self.controlled_player}, bot_player={self.bot_player}, "
                    f"current_player={current_player})"
                )

            # A partir d'ici, tous les chemins mutent l'etat — `_check_game_over` ecrit `game_over`,
            # puis viennent `_build_observation` ou `env.step`. La decision portee est perimee des
            # maintenant : on la retire AVANT la premiere mutation, pas entre deux (cf. `MaskDecision`).
            decision = None

            # If controlled player has no eligible units and game is over, terminate cleanly.
            if eligible_count == 0:
                self.engine.game_state["game_over"] = self.engine._check_game_over()
                if self.engine.game_state["game_over"]:
                    terminated = True
                    obs = self.engine._build_observation()
                    winner, win_method = self.engine._determine_winner_with_method()
                    info = {
                        "winner": winner,
                        "win_method": win_method,
                        "phase_auto_advanced": True,
                    }
                    break

            # No actionable decision for controlled player: force WAIT to advance phase/turn.
            t0_wait = time.perf_counter() if debug_mode else None
            if debug_mode and _trace_sampled(iteration_count):
                trace(
                    CH_BOT_LOOP, debug_mode,
                    "BotControlledEnv._ensure_actionable_controlled_turn env_rank=%s iteration=%s branch=forced-wait",
                    self._env_rank, iteration_count,
                )
            try:
                # `decision` vaut deja None ici (remise a None au-dessus, avant la premiere
                # mutation) : on ne transmet RIEN en entree. Deliberé — `_check_game_over` a pu
                # ecrire `game_over` juste avant, et prouver que le masque n'en depend pas
                # couterait plus que ce que ce chemin peu frequent rapporte. Le sens SORTIE, lui,
                # est gratuit : le masque de l'etat d'arrivee remonte.
                obs, reward, terminated, truncated, info, decision = self._engine_step(
                    mi.ACTION_WAIT, None
                )
            except RuntimeError as e:
                err = str(e)
                if "advance_phase failed" in err and "game_over" in err:
                    self.engine.game_state["game_over"] = True
                    terminated = True
                    obs = self.engine._build_observation()
                    winner, win_method = self.engine._determine_winner_with_method()
                    info = {
                        "winner": winner,
                        "win_method": win_method,
                        "phase_auto_advanced": True,
                    }
                    break
                raise
            if accumulate_reward:
                cumulative_reward += float(reward)
                self.episode_reward += float(reward)
            if debug_mode and t0_wait is not None:
                ep = int(require_key(self.engine.game_state, "episode_number"))
                step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                duration_s = time.perf_counter() - t0_wait
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                except (OSError, IOError):
                    pass
            self.episode_length += 1

        # Sortie par TERMINAISON (la condition du `while` tombe apres un step) : on ne rend AUCUNE
        # decision. Les steps ci-dessus rendent desormais celle de leur etat d'arrivee, et sur un
        # episode termine elle serait valide — mais la transmettre changerait le comportement :
        # l'observation terminale de `step()` est construite avec ce masque, et un masque fourni
        # rend inatteignable la branche `advance_phase` de `_build_observation`. Ce chemin doit
        # rester exactement celui d'avant (cf. `_play_bot_until_control_returns`, qui documente que
        # cette construction peut avancer une phase sur episode termine, sans consequence).
        if terminated or truncated:
            decision = None

        # CONTRAT DE SORTIE, verifie ICI et NULLE PART AILLEURS : soit l'episode est termine, soit
        # le joueur controle a une action jouable ET sa decision est en main. Les appelants s'y
        # fient au lieu de reconstruire le masque pour reposer la meme question. Deux raisons :
        # un controle en aval nourri par la valeur qui l'a produit ne controle rien, et un controle
        # en aval qui reconstruit le masque paye un pas de travail complet pour ne relire que deux
        # champs. Ici, la verification est gratuite — la decision est deja en main.
        if not (terminated or truncated):
            if (
                decision is None
                or decision.decision_owner != self.controlled_player
                or not decision.has_valid_actions
            ):
                current_player = self.engine.game_state.get("current_player")
                raise RuntimeError(
                    "BotControlledEnv._ensure_actionable_controlled_turn: sortie sans terminaison "
                    "et sans etat jouable pour le joueur controle — "
                    f"decision={None if decision is None else (decision.decision_owner, decision.has_valid_actions)}, "
                    f"controlled_player={self.controlled_player}, current_player={current_player}, "
                    f"iterations={iteration_count}. Une sortie de boucle a ete ajoutee sans "
                    "etablir ce contrat : les appelants (action de la politique, observation "
                    "reportee) le supposent tenu."
                )
        return obs, terminated, truncated, info, cumulative_reward, decision

    def _resolve_seat_p2_ratio(self, agent_seat_p2_ratio: Optional[float]) -> Optional[float]:
        """Part des episodes ou l'agent joue SECOND, quand `agent_seat_mode='random'`.

        POURQUOI CE REGLAGE EXISTE. Le tirage etait un pile ou face exact, et l'agent joue
        nettement moins bien en second : mesure du run x1_long du 2026-08-12, 0.707 de win-rate
        en jouant premier contre 0.586 en jouant second, 12 points stables jusqu'a la fin du
        run (cf. `ai.bot_evaluation.SEAT_KEYS`). Sur-echantillonner le siege faible est le seul
        levier d'exposition disponible ; sans lui, la seule alternative etait `agent_seat_mode:
        "p2"`, qui supprime purement et simplement l'autre siege et rend `00_critical/0_gap_p1-p2`
        aveugle — meme travers que la rampe de deploiement a 1.0, qui tuait sa courbe de controle.

        Le ratio ne s'applique QU'A L'ENTRAINEMENT : `ai/bot_evaluation.py` construit ses
        environnements sans le passer, donc l'evaluation garde son tirage equitable. C'est
        volontaire — le win-rate publie doit rester comparable entre runs, et un `combined`
        mesure sur une ventilation de sieges biaisee ne le serait plus.

        En mode fixe (`p1`/`p2`), la notion de ratio n'existe pas : retourne `None`. Un ratio
        non nul passe en mode fixe est une contradiction et leve ValueError.
        En mode `random`, `None` vaut 0.5 (tirage equitable historique) ; la CONFIG d'entrainement
        exige la cle explicitement (`ai/train.py`).
        """
        if self.agent_seat_mode != "random":
            if agent_seat_p2_ratio is not None:
                raise ValueError(
                    f"agent_seat_p2_ratio n'a de sens qu'avec agent_seat_mode='random' "
                    f"(mode={self.agent_seat_mode!r}, ratio={agent_seat_p2_ratio!r}) : un siege fixe "
                    f"ne se pondere pas, et accepter la valeur en la ignorant ferait mentir la config."
                )
            return None
        if agent_seat_p2_ratio is None:
            return 0.5
        if isinstance(agent_seat_p2_ratio, bool) or not isinstance(agent_seat_p2_ratio, (int, float)):
            raise TypeError(
                f"agent_seat_p2_ratio must be a number "
                f"(got {type(agent_seat_p2_ratio).__name__})"
            )
        ratio = float(agent_seat_p2_ratio)
        if not 0.0 <= ratio <= 1.0:
            raise ValueError(f"agent_seat_p2_ratio must be within [0.0, 1.0] (got {ratio})")
        return ratio

    def _resolve_controlled_player_for_episode(self) -> int:
        """Resolve controlled player for this episode from seat mode.

        En mode `random`, le siege est tire d'un hachage de (seed, rang d'env, index d'episode)
        compare a `_agent_seat_p2_ratio`. Le tirage retenait auparavant la PARITE de ce hachage,
        ce qui figeait la ventilation a 50/50 ; le seuil sur les 32 premiers bits — uniformes —
        rend le meme service pour n'importe quelle proportion. Consequence assumee : a ratio 0.5
        un run rejoue ne redonne pas siege pour siege la meme sequence qu'avant ce changement,
        seulement la meme distribution. Aucun invariant du depot ne porte sur le siege d'un
        episode nomme ; les courbes `seat_aware/*` portent sur les agregats.
        """
        if self.agent_seat_mode == "p1":
            return 1
        if self.agent_seat_mode == "p2":
            return 2
        # random mode : _resolve_seat_p2_ratio garantit un ratio non-None dans ce mode.
        ratio = self._agent_seat_p2_ratio
        assert ratio is not None
        seed_material = f"{self._global_seed}:{self._env_rank}:{self._episode_index}"
        seed_hash = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
        selector = int(seed_hash[:8], 16)
        return 2 if (selector / 2 ** 32) < ratio else 1

    def _apply_episode_seat(self) -> None:
        """Set controlled/opponent players in engine config and game_state."""
        self.controlled_player = self._resolve_controlled_player_for_episode()
        self.bot_player = 2 if self.controlled_player == 1 else 1
        self.engine.config["controlled_player"] = self.controlled_player
        self.engine.config["opponent_player"] = self.bot_player
        self.engine.config["agent_seat_mode"] = self.agent_seat_mode

    def _compute_pool_ratio_for_episode(self) -> float:
        """Part du POOL d'adversaires figes a l'episode courant. Le reste va aux bots.

        La rampe ne pilote plus le couple bots/self-play mais la FRONTIERE bots/pool : cet
        environnement s'est vu attribuer UN adversaire fige a la construction
        (`self_play_snapshot_path`, resolu par `ai/curriculum.assign_pool_members_to_envs`), et
        la composition interne du pool est realisee par la repartition des ENVIRONNEMENTS, en
        proportions fixes. Ce qui varie avec le temps, ici, c'est uniquement la probabilite de
        jouer contre cet adversaire plutot que contre un bot.

        Le calcul lui-meme vit dans `ai/curriculum.ramped_ratio` : c'est la meme rampe que celle
        que le curriculum declare etape par etape, et un warmup interprete differemment des deux
        cotes ne se verrait dans aucune courbe.
        """
        if not self._self_play_opponent_enabled:
            return 0.0
        return ramped_ratio(
            episode_index=self._episode_index,
            warmup_episodes=self._self_play_warmup_episodes,
            total_episodes=self._self_play_total_episodes,
            ratio_start=self._self_play_ratio_start,
            ratio_end=self._self_play_ratio_end,
        )

    def _reload_self_play_snapshot_if_needed(self, force: bool = False) -> None:
        """Load/reload frozen model snapshot used as self-play opponent."""
        if not self._self_play_opponent_enabled:
            return
        # Adversaire FIGE : une archive d'etape ou un checkpoint etalon. Il est charge au premier
        # episode qui en a besoin, puis plus jamais relu — c'est ce qui garde l'empreinte memoire
        # a UN modele par processus quand le pool en compte treize.
        if self._self_play_snapshot_frozen and self._frozen_model is not None and not force:
            return
        snapshot_path = self._self_play_snapshot_path
        if not os.path.exists(snapshot_path):
            raise FileNotFoundError(
                f"Self-play snapshot not found: {snapshot_path}. "
                "Training loop must publish snapshot before self-play episodes."
            )
        current_mtime = float(os.path.getmtime(snapshot_path))
        if (
            not force
            and self._frozen_model is not None
            and self._frozen_model_mtime is not None
            and current_mtime == self._frozen_model_mtime
            and self._episodes_since_snapshot_refresh < self._self_play_snapshot_refresh_episodes
        ):
            return
        from sb3_contrib import MaskablePPO
        from ai.vec_normalize_utils import _NormalizedFrozenModel, build_snapshot_normalizer
        raw_model = MaskablePPO.load(
            snapshot_path,
            device=self._self_play_snapshot_device,
        )
        normalizer = build_snapshot_normalizer(
            snapshot_path,
            self._self_play_vec_normalize_enabled,
            self._self_play_vec_normalize_eval_enabled,
        )
        self._frozen_model = _NormalizedFrozenModel(raw_model, normalizer)
        self._frozen_model_mtime = current_mtime
        self._episodes_since_snapshot_refresh = 0

    def _select_opponent_mode_for_episode(self) -> None:
        """Choose bot opponent or frozen self-play opponent for current episode."""
        self._episode_uses_self_play_opponent = False
        self._self_play_ratio_current = 0.0
        if not self._self_play_opponent_enabled:
            self._bot_episodes += 1
            return
        ratio = self._compute_pool_ratio_for_episode()
        self._self_play_ratio_current = ratio
        seed_material = f"{self._global_seed}:{self._env_rank}:{self._episode_index}:self_play"
        draw_hash = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
        draw = int(draw_hash[:8], 16) / float(0xFFFFFFFF)
        self._episode_uses_self_play_opponent = bool(draw < ratio)
        if self._episode_uses_self_play_opponent:
            self._reload_self_play_snapshot_if_needed(force=False)
            self._self_play_episodes += 1
        else:
            self._bot_episodes += 1

    def _get_self_play_opponent_action(self, decision: Optional[MaskDecision] = None) -> int:
        """Get action from frozen self-play opponent model.

        `decision` : masque deja construit pour cet etat par l'appelant adjacent (`MaskDecision`).
        Absente, on le construit.
        """
        if decision is not None:
            action_mask, eligible_units = decision.action_mask, decision.eligible_units
        else:
            action_mask, eligible_units = self.engine.action_decoder.get_squad_action_mask_and_eligible_units(
                self.engine.game_state
            )
        # Decision agent en attente (V11 §9.3 P2) : le pool est vide PAR CONSTRUCTION — le moteur
        # est arrete sur un point de choix, pas sur une activation. Sortir ici sur `ACTION_WAIT`
        # rendrait une action HORS MASQUE, et le moteur ne revalide pas : `convert_squad_action`
        # leve en move/shoot/charge/fight, et rend silencieusement `command_wait` en phase command
        # — la decision est alors perdue sans trace. On laisse donc passer jusqu'a
        # `predict(action_masks=...)`, ou le modele choisit un `CHOICE_i`. Jumeau de la branche
        # de `_get_bot_action` et de celle de `SelfPlayWrapper._get_frozen_model_action`.
        if not eligible_units and not engine_is_paused_on_player_choice(self.engine.game_state):
            return mi.ACTION_WAIT
        # La liste des actions legales n'etait construite que pour tester sa vacuite : le modele
        # recoit le masque tel quel.
        if not np.any(np.asarray(action_mask, dtype=bool)):
            raise RuntimeError(
                "BotControlledEnv self-play opponent encountered empty action mask. "
                "Engine must advance phase/turn instead of exposing empty masks."
            )
        if self._frozen_model is None:
            raise RuntimeError(
                "Self-play opponent model is not loaded while episode is in self-play mode."
            )
        # Les lignes intermediaires ne lisent que des locales : on transmet le masque au lieu de
        # laisser l'observation le reconstruire.
        obs = self.engine._build_observation(mask_and_eligible=(action_mask, eligible_units))
        action, _ = self._frozen_model.predict(
            obs,
            deterministic=self._self_play_deterministic,
            action_masks=action_mask,
        )
        return int(action)

    def _get_opponent_action(
        self, debug: bool = False, decision: Optional[MaskDecision] = None
    ) -> tuple[int, Optional[MaskDecision]]:
        """Action de l'adversaire, ET la decision encore valable APRES ce choix.

        Pourquoi ce second element plutot qu'une discipline au site d'appel : les deux branches ne
        se valent pas. Le bot ne fait que LIRE l'etat, sa decision survit. L'adversaire self-play,
        lui, construit une observation — donc MUTE l'etat (frontiere 14.02, journal VP,
        `advance_phase` sur pool vide) : la decision ne vaut plus, et le masque qu'elle porte ne
        peut pas etre transmis au step suivant. Rendre l'invalidation ici la met dans la SIGNATURE
        de la fonction qui mute, au lieu de la confier a la memoire de l'appelant. Le banc
        d'entrainement ne couvre pas la branche self-play : une discipline y aurait ete non testee.
        """
        if self._episode_uses_self_play_opponent:
            return self._get_self_play_opponent_action(decision=decision), None
        return self._get_bot_action(debug=debug, decision=decision), decision

    def _play_bot_until_control_returns(
        self, debug_mode: bool, decision: Optional[MaskDecision] = None
    ):
        """
        Advance environment until controlled player has an actionable decision state.

        This includes:
        - executing consecutive bot turns,
        - executing forced controlled WAIT when controlled player has no legal action.

        Returns:
            obs, cumulative_reward, terminated, truncated, info, ready_decision

        `ready_decision` : masque etabli sur l'etat de sortie quand le joueur controle a bien une
        action jouable, pour que l'appelant n'ait pas a le reconstruire (cf. `MaskDecision`) ;
        None sur toute autre sortie, et remise a None si l'observation est construite ici — un
        `_build_observation` mute l'etat (frontiere 14.02, journal VP, advance_phase sur pool vide).
        """
        trace(CH_BOT_LOOP, debug_mode,
              "BotControlledEnv._play_bot_until_control_returns enter env_rank=%s", self._env_rank)
        obs = None
        info = {}
        obs, terminated, truncated, info, cumulative_reward, ready_decision = self._ensure_actionable_controlled_turn(
            terminated=False,
            truncated=False,
            obs=obs,
            info=info,
            debug_mode=debug_mode,
            accumulate_reward=True,
            cumulative_reward=0.0,
            decision=decision,
        )
        if obs is None and not self.engine.defer_observation:
            # Keep vectorized env stacking stable: always return a real observation.
            #
            # POURQUOI cet appel ne peut PAS avancer la phase — la question se pose parce que le
            # `reset` passe ici (report desarme) et qu'il n'y a plus de controle apres :
            # `_build_observation` n'avance la phase que sur `not eligible_units and not mask.any()`.
            # Or on lui transmet le masque du contrat de sortie ci-dessus, dont le MASQUE est non
            # vide par construction (sinon la boucle aurait leve). L'avancement exigeant les DEUX
            # conditions, il suffit que le masque soit non vide. Ne PAS invoquer ici un pool non
            # vide : le contrat ne le garantit pas — une decision agent en attente et l'intention
            # de zone en phase command rendent toutes deux un pool vide avec un masque arme. La
            # branche d'avancement est donc hors d'atteinte, et l'etat rendu a la politique reste
            # celui que la boucle a etabli. Si un
            # jour on cessait de transmettre ce masque, ce raisonnement tomberait : la construction
            # recalculerait, pourrait avancer, et il faudrait re-verifier l'etat apres cet appel.
            # Sur episode TERMINE, la decision vaut None et cette construction peut avancer une
            # phase — comportement inchange, et sans consequence : `reset` reprend une tentative,
            # `step` rend `terminated`. Aucune politique ne decide sur cet etat.
            obs = self.engine._build_observation(mask_and_eligible=mask_pair_of(ready_decision))
            # Les autres mutations (frontiere 14.02, journal VP) ont bien eu lieu : la decision ne
            # vaut plus pour l'appelant, meme si le pool n'a pas bouge.
            ready_decision = None
        if debug_mode:
            trace(
                CH_BOT_LOOP, debug_mode,
                "BotControlledEnv._play_bot_until_control_returns exit env_rank=%s terminated=%s "
                "truncated=%s phase=%s current_player=%s controlled_player=%s",
                self._env_rank, terminated, truncated,
                str(require_key(self.engine.game_state, "phase")),
                int(require_key(self.engine.game_state, "current_player")),
                self.controlled_player,
            )
        return obs, float(cumulative_reward), terminated, truncated, info, ready_decision

    def reset(self, *, seed=None, options=None):
        # Meme cycle de vie que dans `step` : le depot meurt avant la premiere mutation.
        self._served_decision = None
        debug_mode = require_key(self.engine.game_state, "debug_mode")
        max_reset_attempts = 64
        last_failure: Optional[str] = None

        for attempt_idx in range(max_reset_attempts):
            self._apply_episode_seat()
            t0 = time.perf_counter() if debug_mode else None
            if debug_mode:
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(
                            f"RESET_START env_rank={self._env_rank} attempt={attempt_idx} "
                            f"episode_index={self._episode_index} seed={seed if attempt_idx == 0 else None!r} "
                            f"options_present={options is not None}\n"
                        )
                    trace(
                        CH_BOT_LOOP, debug_mode,
                        "BotControlledEnv.reset start env_rank=%s attempt=%s",
                        self._env_rank, attempt_idx,
                    )
                except (OSError, IOError):
                    pass
            obs, info = self.env.reset(
                seed=seed if attempt_idx == 0 else None,
                options=options,
            )
            self._episode_index += 1
            game_state = self.engine.game_state
            game_state["controlled_player"] = self.controlled_player
            game_state["opponent_player"] = self.bot_player
            if self.controlled_player == 1:
                self.episodes_agent_p1 += 1
            else:
                self.episodes_agent_p2 += 1
            info["controlled_player"] = self.controlled_player
            info["opponent_player"] = self.bot_player
            info["agent_seat_mode"] = self.agent_seat_mode
            if debug_mode and t0 is not None:
                reset_s = time.perf_counter() - t0
                ep = int(require_key(self.engine.game_state, "episode_number"))
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(
                            f"RESET_END env_rank={self._env_rank} attempt={attempt_idx} "
                            f"episode={ep} duration_s={reset_s:.6f}\n"
                        )
                        f.write(f"RESET_TIMING episode={ep} duration_s={reset_s:.6f}\n")
                    trace(
                        CH_BOT_LOOP, debug_mode,
                        "BotControlledEnv.reset end env_rank=%s attempt=%s duration_s=%.6f",
                        self._env_rank, attempt_idx, reset_s,
                    )
                except (OSError, IOError):
                    pass
            self.episode_reward = 0.0
            self.episode_length = 0

            # Random bot selection: SHA256 reproductible (Bot_refactor.md §4.B, D9).
            # Le tirage global seed n'est pas ensemence en entrainement (§1.2.d) : random.choice
            # n'etait donc pas reproductible. Sans coherence ici, annoncer « jitter reproductible »
            # serait faux — le bot tire ne l'est pas.
            if self._use_random_bots:
                bots = require_present(self._bots, "_bots")
                if self._global_seed is not None:
                    seed_material = (
                        f"{self._global_seed}:{self._env_rank}:{self._episode_index}:bot"
                    )
                    bot_hash = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
                    self.bot = bots[int(bot_hash[:8], 16) % len(bots)]
                else:
                    self.bot = random.choice(bots)
            # Jitter d'episode (§4.B) : multiplicatif sur les poids et les gains de comportement.
            # Stocke sur l'instance via apply_episode_jitter — jamais sur la config source.
            # Nul en evaluation par construction : bot_evaluation.py ne lit pas bot_doctrine_profiles.
            if self._use_random_bots and hasattr(self.bot, "apply_episode_jitter"):
                from ai.bot_doctrines import get_jitter_config
                jitter_cfg = get_jitter_config()
                j_move = jitter_cfg["movement_weight_jitter"]
                j_beh = jitter_cfg["behavior_parameter_jitter"]
                bot_key = getattr(self.bot, "MOVEMENT_BOT_KEY", "")
                ep_marker = (self._global_seed, self._env_rank, self._episode_index)
                base_seed = (
                    f"{self._global_seed}:{self._env_rank}:{self._episode_index}"
                    f":jitter:{bot_key}"
                )

                def _sha256_uniform(suffix: str) -> float:
                    h = hashlib.sha256(
                        f"{base_seed}:{suffix}".encode("utf-8")
                    ).hexdigest()
                    return int(h[:8], 16) / float(0xFFFFFFFF)

                movement_factors = tuple(
                    1.0 + j_move * (2.0 * _sha256_uniform(str(i)) - 1.0)
                    for i in range(6)
                )
                behavior_factor = 1.0 + j_beh * (2.0 * _sha256_uniform("beh") - 1.0)
                self.bot.apply_episode_jitter(
                    movement_factors,  # type: ignore[arg-type]
                    behavior_factor,
                    ep_marker,
                )
            if self._self_play_opponent_enabled:
                self._episodes_since_snapshot_refresh += 1
            self._select_opponent_mode_for_episode()

            # DIAGNOSTIC: Reset shoot tracking for new episode
            self.shoot_opportunities = 0
            self.shoot_actions = 0
            self.wait_actions = 0

            # DIAGNOSTIC: Reset AI shoot tracking
            self.ai_shoot_opportunities = 0
            self.ai_shoot_actions = 0
            self.ai_wait_actions = 0

            # Enforce reset contract for policy learning: return only controlled actionable states.
            bot_obs, _, terminated, truncated, bot_info, ready_decision = self._play_bot_until_control_returns(
                debug_mode=debug_mode
            )
            if bot_obs is not None:
                obs = bot_obs
            if bot_info:
                info.update(bot_info)
            if terminated or truncated:
                winner = self.engine.game_state.get("winner")
                episode_number = self.engine.game_state.get("episode_number")
                last_failure = (
                    "Episode ended before first controlled decision during reset "
                    f"(attempt={attempt_idx + 1}, controlled_player={self.controlled_player}, "
                    f"opponent_player={self.bot_player}, winner={winner}, "
                    f"episode_number={episode_number})"
                )
                continue

            self._last_step_return_time = None
            info["controlled_player"] = self.controlled_player
            info["opponent_player"] = self.bot_player
            info["agent_seat_mode"] = self.agent_seat_mode
            info["opponent_mode"] = (
                "self_play" if self._episode_uses_self_play_opponent else "bot"
            )
            info["self_play_snapshot_label"] = self._self_play_snapshot_label if self._episode_uses_self_play_opponent else ""
            info["self_play_ratio_current"] = self._self_play_ratio_current
            # PPO appelle `action_masks()` juste apres ce retour : on lui sert la decision etablie
            # par la boucle. `_play_bot_until_control_returns` l'a remise a None s'il a construit
            # l'observation lui-meme.
            self._deposit_served_decision(ready_decision, terminated, truncated)
            return obs, info

        raise RuntimeError(
            "BotControlledEnv reset exceeded max attempts without reaching a controlled actionable state "
            f"(max_reset_attempts={max_reset_attempts}). "
            f"Last failure: {last_failure}"
        )

    def _deposit_served_decision(
        self, decision: Optional[MaskDecision], terminated: bool, truncated: bool
    ) -> None:
        """Pose (ou non) la decision que `action_masks()` servira a PPO — precondition ICI.

        La precondition est verifiee au site du DEPOT et non chez les producteurs, parce que la
        question a laquelle `action_masks()` repond est precise : « quelles actions la POLITIQUE
        peut-elle choisir maintenant ? ». Seule une decision appartenant au joueur controle et
        portant au moins une action y repond. Deux cas legitimes ou ce n'est pas le cas :

        - episode termine ou tronque : plus aucune politique ne choisit sur cet etat (PPO passe par
          un reset avant de redemander un masque) ;
        - decision produite par un chemin intermediaire, appartenant a l'autre camp ou a personne.

        Ce n'est pas un repli qui masque une erreur, c'est le DOMAINE DE VALIDITE du depot : hors
        de lui, `action_masks()` construit, ce qui est le calcul normal. Mesure a la mise en place :
        sans ce filtre, un masque VIDE etait servi a PPO sur episode termine alors qu'un masque
        frais etait non vide.
        """
        if terminated or truncated or decision is None:
            self._served_decision = None
            return
        if decision.decision_owner != self.controlled_player or not decision.has_valid_actions:
            self._served_decision = None
            return
        self._served_decision = decision

    def action_masks(self) -> np.ndarray:
        """Masque servi a MaskablePPO — celui que la boucle vient d'etablir, pas un recalcul.

        POURQUOI CE POINT D'ENTREE. `get_action_masks` de sb3_contrib resout `action_masks` par
        `env.get_wrapper_attr(...)`, qui interroge le wrapper le PLUS EXTERNE d'abord : defini ici,
        il prime sur celui d'`ActionMasker` (place SOUS ce wrapper, cf. `ai/training_utils`), dont
        la fonction reconstruisait le masque sur le moteur nu. Mesure : 75,5 reconstructions par
        episode, dont 302 sur 302 rendaient le couple deja etabli par ce wrapper.

        SEUL DEPOT DU CHANTIER, et il est inevitable : PPO appelle cette methode quand il veut,
        depuis sa propre boucle — il n'y a aucune signature ou faire passer la valeur. Sa duree de
        vie est donc bornee par construction plutot que par une discipline : posee a la fin de
        `step`/`reset`, EFFACEE a leur entree, et rien d'autre ne tourne entre les deux que le
        passe avant de la politique. Sur un etat sans decision en main (episode termine avant la
        premiere decision controlee), on construit — c'est le calcul normal, pas un repli : il n'y
        a rien a servir, et rien d'errone a masquer.
        """
        if self._served_decision is not None:
            return self._served_decision.action_mask
        return self.engine.get_action_mask()

    def step(self, action):
        """Un step gym = plusieurs steps moteur (bot, WAIT forces) dont UNE seule observation est lue.

        Le report (``engine.defer_observation``) fait renvoyer ``None`` aux observations
        intermediaires ; l'observation finale — la seule que PPO consomme, y compris comme
        ``terminal_observation`` en fin d'episode — est construite ici, une fois, sur l'etat final.
        Voir ``W40KEngine._step_observation`` : les effets de bord de frontiere (controle
        d'objectif 14.02, VP) restent joues a chaque step moteur.
        """
        # Le depot decrit l'etat d'ENTREE de ce step : rien ne s'est execute depuis qu'il a ete
        # pose (fin du step precedent) hormis le passe avant de la politique. On le REPREND donc
        # comme decision de depart — c'est le meme couple que `_ensure_actionable_controlled_turn`
        # reconstruisait a l'entree — et on l'efface AVANT la premiere mutation : servir a PPO le
        # masque d'un etat revolu ferait choisir une action legale ailleurs, sans que rien ne leve.
        entry_decision = self._served_decision
        self._served_decision = None
        self.engine.defer_observation = True
        try:
            obs, reward, terminated, truncated, info, ready_decision = (
                self._step_with_deferred_observation(action, entry_decision)
            )
        finally:
            self.engine.defer_observation = False
        if obs is None:
            # Le masque du dernier etat a deja ete construit par la boucle qui a rendu la main
            # (`ready_decision`), et rien n'a touche `game_state` depuis — `defer_observation` est
            # un attribut du moteur, pas un element d'etat de jeu. On le transmet plutot que de le
            # reconstruire a l'identique. Vaut None quand l'episode s'est termine : l'observation
            # terminale se construit alors sur un masque frais.
            obs = self.engine._build_observation(mask_and_eligible=mask_pair_of(ready_decision))
        # Le masque reste servable APRES cette construction : elle mute l'etat (frontiere 14.02,
        # journal VP) mais ne change pas la LEGALITE des actions — c'est l'invariant que
        # `_build_observation_and_mask` documente, etabli par recalcul-comparaison. Le masque
        # transmis a la ligne au-dessus passe par la porte de verification de niveau 2 :
        # `W40K_MASK_VERIFY=2` (et non 1, qui ne controle que les donnees memoisees). Sa branche
        # `advance_phase` est hors d'atteinte ici parce que le MASQUE du contrat de sortie est non
        # vide, et que l'avancement exige les deux conditions — ne PAS invoquer un pool non vide,
        # que le contrat ne garantit pas (decision en attente, intention de zone : pool vide).
        self._deposit_served_decision(ready_decision, terminated, truncated)
        return obs, reward, terminated, truncated, info

    def _step_with_deferred_observation(self, action, entry_decision=None):
        # LOG TEMPORAIRE: time between previous step() return and this step() call (SB3 loop = predict + overhead, --debug)
        debug_mode = require_key(self.engine.game_state, "debug_mode")
        if debug_mode and self._last_step_return_time is not None:
            between_s = time.perf_counter() - self._last_step_return_time
            ep = int(require_key(self.engine.game_state, "episode_number"))
            step_idx = int(require_key(self.engine.game_state, "episode_steps"))
            try:
                debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(f"BETWEEN_STEP_TIMING episode={ep} step_index={step_idx} duration_s={between_s:.6f}\n")
            except (OSError, IOError):
                pass
        # Ensure it's really the controlled decision owner's turn before applying agent_action.
        terminated = False
        truncated = False
        obs = None
        reward = 0.0
        cumulative_reward = 0.0
        info = {}
        # Ce que l'INFO du step de l'agent doit rendre a l'appelant. Un step gym enchaine
        # plusieurs steps moteur (l'agent, puis l'adversaire jusqu'au retour de la main) et seul
        # le DERNIER info survit — celui de l'adversaire. Ces cles-la decrivent l'action de
        # l'AGENT ; sans ce report, elles decrivaient celle du bot sous un drapeau
        # `is_controlled_action` qui dit le contraire (la courbe de charges reussies d'alors
        # comptait celles du bot — elle est depuis comptee cote moteur sur `action_logs`, ou le
        # camp de chaque ligne est une donnee et non une deduction sur l'ordre des steps).
        agent_step_info: Dict[str, Any] = {}
        obs, bot_reward_before, terminated, truncated, info, ready_decision = self._play_bot_until_control_returns(
            debug_mode=debug_mode, decision=entry_decision
        )
        cumulative_reward += float(bot_reward_before)
        # DIAGNOSTIC: Track AI shoot phase decisions BEFORE executing action
        # PERFORMANCE: Only track if diagnostics are enabled (shoot stats will be collected)
        # Skip get_action_mask() call here to avoid redundant computation - action_masks are already computed
        # by ActionMasker wrapper and passed to model.predict() in bot_evaluation.py
        if not (terminated or truncated):
            game_state = self.engine.game_state
            current_phase = require_key(game_state, "phase")
            # Track actions for diagnostics WITHOUT calling get_action_mask() (performance optimization)
            # We can infer shoot opportunities from action type instead of checking mask
            if current_phase == "shoot":
                # Infer shoot opportunity from action type (shoot slots 19-23)
                # This avoids expensive get_action_mask() call
                if action in mi.SHOOT_SLOTS:  # Shoot actions (target slots 0-4)
                    self.ai_shoot_opportunities += 1  # If agent shot, opportunity existed
                    self.ai_shoot_actions += 1
                elif action == mi.ACTION_WAIT:  # Wait action
                    self.ai_wait_actions += 1

            # Execute agent action
            # LOG TEMPORAIRE: time full env.step() call (--debug) to compare with STEP_TIMING
            t0_agent = time.perf_counter() if debug_mode else None
            # La decision du contrat de sortie decrit EXACTEMENT l'etat sur lequel la politique
            # vient de choisir : entre son etablissement et ici, seules des lectures (diagnostics
            # de phase, compteurs de tir) se sont executees. On la CONSOMME donc en entree du step
            # — c'etait le premier poste de reconstruction du chantier (124,2 par episode, 100 %
            # rendant un couple identique). Elle est ensuite remplacee par celle de l'etat de
            # sortie : si l'episode se termine sur cette action, le jeu du bot APRES est saute et
            # c'est bien celle d'apres l'action qui doit sortir, jamais celle d'avant.
            obs, reward, terminated, truncated, info, ready_decision = self._engine_step(
                action, ready_decision
            )
            agent_step_info = {
                key: info[key] for key in AGENT_STEP_INFO_KEYS if key in info
            }
            cumulative_reward += float(reward)
            self.episode_reward += float(reward)
            if debug_mode and t0_agent is not None:
                ep = int(require_key(self.engine.game_state, "episode_number"))
                step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                duration_s = time.perf_counter() - t0_agent
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                except (OSError, IOError):
                    pass
            self.episode_length += 1

        # Execute bot turns only while episode is still running.
        if not (terminated or truncated):
            obs, bot_reward_after, terminated, truncated, info, ready_decision = self._play_bot_until_control_returns(
                debug_mode=debug_mode
            )
            cumulative_reward += float(bot_reward_after)

        if debug_mode:
            self._last_step_return_time = time.perf_counter()
        if terminated or truncated:
            if self.controlled_player == 1:
                self.timesteps_agent_p1 += self.episode_length
            else:
                self.timesteps_agent_p2 += self.episode_length
        apply_agent_step_info(info, agent_step_info)
        info["controlled_player"] = self.controlled_player
        info["opponent_player"] = self.bot_player
        info["agent_seat_mode"] = self.agent_seat_mode
        info["opponent_mode"] = (
            "self_play" if self._episode_uses_self_play_opponent else "bot"
        )
        info["self_play_snapshot_label"] = self._self_play_snapshot_label if self._episode_uses_self_play_opponent else ""
        info["self_play_ratio_current"] = self._self_play_ratio_current
        return obs, float(cumulative_reward), terminated, truncated, info, ready_decision

    def _select_bot_deploy_action(self, game_state, valid_actions, bot=None) -> int:
        """Action de PHASE DEPLOIEMENT (03.02) du bot : un slot de mise en place, jamais WAIT.

        Jumeau de l'ingress move (20.04) traite dans `_select_bot_move_action` : les deux sont des
        MISES EN PLACE, et c'est ici, au point de traduction masque -> pool jouable, que le pool se
        nettoie. UNE fois, pour tous les bots, au lieu d'une fois par bot.

        ⚠️ Le masque ouvre `ACTION_WAIT` au deploiement, et ce slot n'y est PAS une attente : le
        jouer met l'unite en RESERVES STRATEGIQUES (20.01,
        `ActionDecoder.get_squad_action_mask_and_eligible_units`). C'est une decision de LISTE,
        jamais de doctrine. La surcharge d'id est volontaire (`TOTAL_ACTION_SIZE` gele depuis le
        chantier 01), donc l'invariant ne peut pas descendre dans le decodeur : il vit ICI. MESURE
        de ce qu'il coutait quand chaque bot le portait lui-meme (chantier 04c) : TacticalBot — le
        HOLDOUT — mettait 400 deploiements sur 400 en reserves, et cinq bots ponderes 1 a 3 % des
        leurs via leur clause d'exploration evaluee AVANT leur branche `deployment`. Un point de
        passage unique rend la correction independante de l'ordre des clauses de chaque bot, et
        d'un 8e bot qu'on ajouterait demain sans y penser.
        """
        placement_actions = self._open_placement_slots(valid_actions)
        if not placement_actions:
            # Contrairement a l'ingress (pool vide = etat de jeu NORMAL, l'unite reste en
            # reserves), un deploiement sans aucun slot de pose est un defaut moteur : le decodeur
            # leve « Deployment deadlock » avant d'en arriver la. Erreur explicite, jamais un repli
            # en WAIT — qui mettrait justement l'unite en reserves.
            raise RuntimeError(
                "BotControlledEnv: masque de deploiement sans aucun slot de mise en place "
                f"{sorted(mi.DEPLOY_SLOTS)} ouvert (actions ouvertes : {valid_actions})."
            )
        actor = self.bot if bot is None else bot
        return self._ask_bot_placement(actor, placement_actions, game_state)

    @staticmethod
    def _open_placement_slots(valid_actions) -> list:
        """Poses ouvertes pour les deux sites de mise en place (deploiement 03.02, ingress 20.04).

        Delegue a `macro_intents.open_placement_slots`, qui porte desormais la regle pour TOUS
        ses appelants — les bots ici, et le deploiement automatique du joueur-agent cote moteur
        (`W40KEngine.step`, mode d'episode `auto`). Le filtre vivait ici tant que les bots en
        etaient les seuls clients ; un second client dans le moteur en aurait fait deux copies,
        exactement le defaut du chantier 04c d'un cran plus haut.

        Ce qui SEPARE les deux sites — le traitement du pool VIDE (erreur au deploiement,
        `ACTION_WAIT` a l'ingress) — leur reste propre, parce qu'il differe reellement.
        """
        return mi.open_placement_slots(valid_actions)

    def _ask_bot_placement(self, actor, placement_actions, game_state) -> int:
        """Interroge la politique de MISE EN PLACE du bot sur un pool DEJA nettoye.

        Point de passage unique des deux sites de mise en place — deploiement initial (03.02) et
        ingress move (20.04) — qui sont des jumeaux exacts cote moteur
        (`ActionDecoder.ingress_slot_candidates` : memes 5 strategies, memes slots 4-8, seule
        l'aire legale change). Un seul contrat en resulte pour `select_placement_action` : elle
        recoit TOUJOURS un pool non vide de slots 4-8, jamais un masque brut. Les bots n'ont donc
        plus a porter le filtre eux-memes — et, ce filtre etant ici, ils n'ont pas non plus a le
        re-verifier : un garde cote bot ne pourrait plus rien voir (cf. `_open_placement_slots`).

        On ne transmet QUE les slots ouverts lus dans le masque : un slot ferme ne peut donc pas
        etre choisi, meme par un bot qui ignorerait la liste qu'on lui passe —
        `validate_action_against_mask` le rattraperait, mais en abattant le run.
        """
        if not hasattr(actor, "select_placement_action"):
            # Meme contrat que `select_movement_destination` : erreur explicite, jamais un repli
            # silencieux qui ferait renoncer le bot a sa mise en place.
            raise RuntimeError(
                f"Bot {type(actor).__name__} n'implemente pas select_placement_action, "
                f"requis par toute mise en place (deploiement 03.02, ingress move 20.04)."
            )
        return int(actor.select_placement_action(placement_actions, game_state))

    def _select_bot_move_action(self, game_state, active_unit, valid_actions, bot=None) -> int:
        """Action de PHASE MOVE du bot : ingress move si l'escouade est en reserves, sinon
        traduction de son choix de destination en action-cellule legale (phase move spatiale).

        Les deux cas se decident sur `unit_is_in_strategic_reserves`, jamais sur « la liste des
        cellules est-elle vide » : cette question-la ne les distingue pas (une escouade posee et
        totalement bloquee a elle aussi zero cellule).

        Contrat strict (cf. audit spec §7bis, le repli silencieux a ete eradique) :
          - Le bot ne choisit QUE parmi les destinations reellement executables : celles portees
            par les cellules a True dans le masque du moteur (via la carte memoisee). Aucun dry-run
            maison, aucune geometrie recalculee — `spatial_grid` reste la source unique.
          - « Rester sur place » se signale en renvoyant l'ancre courante (le bot le fait quand il
            tient un objectif ou n'a nulle part ou aller) -> WAIT. `start_pos` etant exclu du pool
            (§4.6), l'ancre n'est jamais une destination legale : le signal est sans ambiguite.
          - Toute autre valeur hors des destinations legales est un bug d'invariant -> erreur
            explicite (jamais un repli silencieux en WAIT).
        """
        from engine.phase_handlers.shared_utils import (
            read_squad_move_cell_map,
            require_unit_position,
            unit_is_in_strategic_reserves,
        )

        squad_id = str(require_key(active_unit, "id"))
        actor = self.bot if bot is None else bot

        # INGRESS MOVE (20.04) — l'escouade active est en RESERVES. Elle n'est pas sur le
        # plateau, donc elle n'a AUCUNE cellule de move : le masque lui ouvre a la place les
        # slots de mise en place 4-8 (`ActionDecoder.ingress_slot_candidates`, jumeau exact du
        # deploiement) plus WAIT pour rester en reserves.
        #
        # ⚠️ Cette branche doit precede le calcul de `move_cells`, et le filtre `a in
        # mi.MOVE_CELLS` ne peut PAS servir a distinguer les deux cas : les ids des slots de mise
        # en place (DEPLOY_SLOTS = 4-8) sont NUMERIQUEMENT DANS la plage des cellules de move
        # (MOVE_CELLS = 0-1023). Un slot d'ingress ouvert se lit donc comme une cellule de move,
        # et le code d'avant ce chantier partait chercher sa destination dans la carte de
        # cellules — laquelle n'existe pas pour une escouade en reserves, le masque ayant rendu
        # la main avant de la construire. MESURE sur un episode complet : ValueError
        # « read_squad_move_cell_map: aucune carte de cellules pour squad 101 » au step 30. Le
        # bot ne DECLINAIT pas l'arrivee, il ABATTAIT le run — tout roster a reserves cote bot
        # etait injouable. Seul `unit_is_in_strategic_reserves` separe les deux familles.
        if unit_is_in_strategic_reserves(game_state, squad_id):
            placement_actions = self._open_placement_slots(valid_actions)
            if not placement_actions:
                # `ingress_slot_candidates` a rendu {} : aucune destination legale dans le pool
                # d'ingress a ce round (positions ennemies, clause de zone adverse avant le 3e
                # round). Etat de jeu NORMAL — l'unite reste en reserves et retentera au round
                # suivant — et seul WAIT est alors arme par le masque.
                return mi.ACTION_WAIT
            return self._ask_bot_placement(actor, placement_actions, game_state)

        move_cells = [a for a in valid_actions if a in mi.MOVE_CELLS]
        if not move_cells:
            # Aucune cellule de move jouable (budget nul / totalement bloque) : seul WAIT reste,
            # toujours arme par le masque en phase move. Etat legitime, pas une erreur.
            return mi.ACTION_WAIT

        # Carte cellule -> (destination, cout) construite ET memoisee par
        # get_squad_action_mask_and_eligible_units (appele juste avant). On rejoue EXACTEMENT ses
        # cellules : un cell_idx masque a True porte forcement une destination dans cette carte.
        cell_map = read_squad_move_cell_map(game_state, squad_id)
        dest_to_cell: dict = {}
        valid_destinations = []
        for cell_idx in move_cells:
            if cell_idx not in cell_map:
                raise RuntimeError(
                    f"BotControlledEnv move: cellule {cell_idx} a True dans le masque mais absente "
                    f"de la carte memoisee (squad {squad_id}). Masque et carte doivent partager la "
                    f"meme source (build_squad_move_cell_map)."
                )
            dest = cell_map[cell_idx][0]
            if dest not in dest_to_cell:
                dest_to_cell[dest] = cell_idx
                valid_destinations.append(dest)

        if not hasattr(actor, "select_movement_destination"):
            raise RuntimeError(
                f"Bot {type(actor).__name__} n'implemente pas select_movement_destination, "
                f"requis par l'action space spatial de la phase move."
            )
        chosen = actor.select_movement_destination(active_unit, valid_destinations, game_state)
        chosen = (int(chosen[0]), int(chosen[1]))

        if chosen == tuple(require_unit_position(squad_id, game_state)):
            # Signal « je tiens ma position » -> WAIT (legal en move).
            return mi.ACTION_WAIT

        cell = dest_to_cell.get(chosen)
        if cell is None:
            raise RuntimeError(
                f"Bot {type(actor).__name__}.select_movement_destination a renvoye {chosen}, "
                f"hors des {len(valid_destinations)} destinations legales du pool. Un bot ne peut "
                f"choisir que parmi les destinations masquees (aucun move maison, aucun repli WAIT)."
            )
        return cell

    def scripted_action_for_agent_side(self, bot) -> int:
        """Action que `bot` jouerait A LA PLACE DE L'AGENT sur l'etat courant.

        Sert au classement bot-contre-bot (`scripts/bot_ranking.py`) : sans elle, mesurer la force
        d'un bot exigeait un modele entraine comme joueur 1, donc un classement circulaire.
        Un SEUL chemin de decision existe pour les bots — celui de `_get_bot_action` — et c'est
        volontaire : deux implementations divergeraient, et le bot mesure ne serait plus celui
        joue en evaluation.

        ⚠️ Effet de bord assume : les compteurs de diagnostic tir/wait de ce wrapper sont ecrits
        par `_get_bot_action`, donc un appel ici les melange avec ceux du bot de P2.
        `get_shoot_stats()` n'a pas de sens sur un env pilote des deux cotes.
        """
        return self._get_bot_action(bot=bot)

    def _get_bot_action(self, debug=False, decision: Optional[MaskDecision] = None, bot=None) -> int:
        """`decision` : masque deja construit pour cet etat par l'appelant adjacent (`MaskDecision`).
        Absente, on le construit — c'est le cas des appels directs (tests).

        `bot` : acteur a interroger. Par defaut `self.bot` (le bot de P2). Le parametrer permet de
        faire jouer un AUTRE bot a la place de l'agent, cf. `scripted_action_for_agent_side`.

        Consequence a garder en tete : la carte cellule -> destination lue plus bas
        (`read_squad_move_cell_map`) est celle que CETTE construction a memoisee, d'ici ou de
        l'appelant.
        """
        actor = self.bot if bot is None else bot
        game_state = self.engine.game_state
        if decision is not None:
            action_mask, eligible_units = decision.action_mask, decision.eligible_units
        else:
            action_mask, eligible_units = self.engine.action_decoder.get_squad_action_mask_and_eligible_units(game_state)
        # POINT DE CHOIX JOUEUR en attente (décision agent V11 §9.3 P2, désignation d'Oath du
        # chantier 03) — traité AVANT le `not eligible_units` : le pool est vide PAR CONSTRUCTION
        # dans cet état, et le masque n'y ouvre AUCUN `ACTION_WAIT` (une désignation d'Oath n'est
        # pas optionnelle : « select one unit from your opponent's army »). Sans cette branche, le
        # repli « pool vide -> WAIT » ci-dessous renvoie une action HORS MASQUE et le décodeur lève.
        pending_choice_action = random_action_for_pending_choice(
            game_state, action_mask, "BotControlledEnv"
        )
        if pending_choice_action is not None:
            return pending_choice_action
        if not eligible_units:
            # Pool empty -> advance phase via WAIT/invalid action handling
            return mi.ACTION_WAIT
        valid_actions = [i for i in range(len(action_mask)) if action_mask[i]]

        if not valid_actions:
            # architecture_moteur.md: No hidden contracts on magic actions.
            # An empty mask here means the engine exposed a phase/turn with no
            # legal actions instead of advancing itself. This must be treated
            # as an explicit engine/flow error, not patched by returning a
            # dummy action.
            raise RuntimeError(
                "BotControlledEnv encountered an empty action mask. "
                "Engine must advance phase/turn instead of exposing "
                "no-op action spaces."
            )

        # DIAGNOSTIC: Track shoot phase opportunities
        current_phase = require_key(game_state, "phase")
        if current_phase == "shoot" and any(a in valid_actions for a in mi.SHOOT_SLOTS):
            self.shoot_opportunities += 1

        # CHOIX DE L'ESCOUADE A ACTIVER (V11 §0.48 element L2) — le masque est EXCLUSIF : il
        # n'ouvre que des `ACTIVATE_SLOTS`, donc AUCUNE des politiques de bot ci-dessous n'a
        # d'action a proposer (`_select_bot_move_action` cherche des cellules, il n'y en a pas).
        # Sans cette branche, le premier point de choix en phase move fait lever le bot.
        #
        # POLITIQUE DU BOT : le SLOT 0, toujours. Ce n'est pas un repli faute de mieux, c'est le
        # maintien DELIBERE de la baseline : le slot 0 porte l'ancre du pool, c'est-a-dire
        # exactement l'escouade que le moteur activait AVANT `L2` (`eligible_units[0]`). Faire
        # choisir le bot au hasard changerait l'adversaire en meme temps que l'agent, et le
        # delta de win-rate du lot ne mesurerait plus rien (meme lecon que §0.47 E4 sur les bots
        # d'evaluation). Une politique d'activation pour les bots est un chantier a part entiere.
        activation_slots = self.engine.action_decoder.activation_selection_slots(game_state)
        if activation_slots is not None:
            head_action = mi.ACTIVATE_SLOT_BASE
            if head_action not in activation_slots:
                raise RuntimeError(
                    "BotControlledEnv: choix d'activation en attente sans slot 0 ouvert — "
                    f"ouverts : {sorted(activation_slots)}. Le slot 0 porte l'ancre du pool, "
                    "il est ouvert par construction."
                )
            return head_action

        if current_phase == "deployment":
            bot_choice = self._select_bot_deploy_action(game_state, valid_actions, bot=actor)
        elif current_phase == "move":
            # Refonte spatiale : en move, les bits True du masque sont des CELLULES (0-1023), pas
            # des directions. Le bot ne peut pas choisir une cellule entiere sensement (« premiere
            # cellule legale » = coin arbitraire de la grille, root cause §3). Il choisit une
            # DESTINATION via son heuristique (select_movement_destination), et on la traduit en
            # cellule via la carte MEMOISEE par le moteur au masque (spatial_grid = source unique).
            bot_choice = self._select_bot_move_action(
                game_state, eligible_units[0], valid_actions, bot=actor
            )
        else:
            if not hasattr(actor, "select_action_with_state"):
                # Meme contrat que `select_movement_destination` ci-dessus : un bot qui ne voit
                # ni l'etat ni l'escouade activee ne peut choisir qu'au hasard ou par ordre de
                # slot. Erreur explicite plutot qu'un repli silencieux sur une politique aveugle.
                raise RuntimeError(
                    f"Bot {type(actor).__name__} n'implemente pas select_action_with_state, "
                    f"requis pour toute decision hors deplacement."
                )
            # L'escouade activee est TRANSMISE au bot : c'est elle (et non `current_player`) qui
            # determine le joueur dont le masque est construit — cf.
            # `get_squad_action_mask_and_eligible_units`, `our_player` lu dans
            # `units_cache[eligible_units[0]["id"]]`. En phase de combat, la selection 12.04
            # alterne entre les camps : le bot peut etre selecteur SANS etre joueur courant.
            bot_choice = actor.select_action_with_state(
                valid_actions, game_state, eligible_units[0]
            )

        try:
            bot_action = self.engine.action_decoder.normalize_action_input(
                raw_action=bot_choice,
                phase=current_phase,
                source="bot_controlled_env",
                action_space_size=len(action_mask),
            )
            self.engine.action_decoder.validate_action_against_mask(
                action_int=bot_action,
                action_mask=action_mask,
                phase=current_phase,
                source="bot_controlled_env",
                unit_id=(eligible_units[0]["id"] if eligible_units else None),
            )
        except ActionValidationError as e:
            raise RuntimeError(f"Bot action validation failed: {e}") from e

        # DIAGNOSTIC: Track actual shoot/wait decisions in shoot phase
        if current_phase == "shoot":
            if bot_action in mi.SHOOT_SLOTS:  # Shoot actions (target slots 0-4)
                self.shoot_actions += 1
            elif bot_action == mi.ACTION_WAIT:  # Wait action
                self.wait_actions += 1

        return bot_action

    def get_shoot_stats(self) -> dict:
        """Return shooting statistics for diagnostic analysis."""
        shoot_rate = (self.shoot_actions / self.shoot_opportunities * 100) if self.shoot_opportunities > 0 else 0
        wait_rate = (self.wait_actions / self.shoot_opportunities * 100) if self.shoot_opportunities > 0 else 0

        ai_shoot_rate = (self.ai_shoot_actions / self.ai_shoot_opportunities * 100) if self.ai_shoot_opportunities > 0 else 0
        ai_wait_rate = (self.ai_wait_actions / self.ai_shoot_opportunities * 100) if self.ai_shoot_opportunities > 0 else 0

        return {
            'shoot_opportunities': self.shoot_opportunities,
            'shoot_actions': self.shoot_actions,
            'wait_actions': self.wait_actions,
            'shoot_rate': shoot_rate,
            'wait_rate': wait_rate,
            'ai_shoot_opportunities': self.ai_shoot_opportunities,
            'ai_shoot_actions': self.ai_shoot_actions,
            'ai_wait_actions': self.ai_wait_actions,
            'ai_shoot_rate': ai_shoot_rate,
            'ai_wait_rate': ai_wait_rate
        }

    def get_seat_stats(self) -> dict:
        """Return seat distribution stats for audit."""
        total_episodes = self.episodes_agent_p1 + self.episodes_agent_p2
        total_timesteps = self.timesteps_agent_p1 + self.timesteps_agent_p2
        p1_episode_share = (self.episodes_agent_p1 / total_episodes * 100.0) if total_episodes > 0 else 0.0
        p2_episode_share = (self.episodes_agent_p2 / total_episodes * 100.0) if total_episodes > 0 else 0.0
        p1_timestep_share = (self.timesteps_agent_p1 / total_timesteps * 100.0) if total_timesteps > 0 else 0.0
        p2_timestep_share = (self.timesteps_agent_p2 / total_timesteps * 100.0) if total_timesteps > 0 else 0.0
        return {
            "agent_seat_mode": self.agent_seat_mode,
            "agent_seat_p2_ratio": self._agent_seat_p2_ratio,
            "episodes_agent_p1": self.episodes_agent_p1,
            "episodes_agent_p2": self.episodes_agent_p2,
            "episodes_vs_bots": self._bot_episodes,
            "episodes_vs_self_play": self._self_play_episodes,
            "timesteps_agent_p1": self.timesteps_agent_p1,
            "timesteps_agent_p2": self.timesteps_agent_p2,
            "episode_share_agent_p1_pct": p1_episode_share,
            "episode_share_agent_p2_pct": p2_episode_share,
            "timestep_share_agent_p1_pct": p1_timestep_share,
            "timestep_share_agent_p2_pct": p2_timestep_share,
        }


class SelfPlayWrapper(gym.Wrapper):
    """
    Wrapper for self-play training where Player 2 is controlled by a frozen copy of the model.

    Key features:
    - Player 1: Learning agent (receives gradient updates from SB3)
    - Player 2: Frozen opponent (uses copy of model from N episodes ago)
    - Frozen model updates periodically to keep opponent challenging
    - Naturally targets ~50% win rate as learning agent improves
    """

    def __init__(self, base_env, frozen_model=None, update_frequency=500,
                 allow_random_opponent: bool = False):
        """
        Args:
            base_env: W40KEngine wrapped in ActionMasker
            frozen_model: Frozen model piloting Player 2
            update_frequency: Episodes between frozen model updates
            allow_random_opponent: Autorise EXPLICITEMENT un P2 aleatoire quand
                `frozen_model is None`. Reserve aux tests. V11 §10.4 : c'etait
                auparavant le comportement par defaut et SILENCIEUX — des runs entiers
                se sont entraines contre du hasard sans qu'aucun log ne le signale.
        """
        super().__init__(base_env)
        self.frozen_model = frozen_model
        self.allow_random_opponent = allow_random_opponent
        self.update_frequency = update_frequency
        self.episodes_since_update = 0
        self.total_episodes = 0

        # Deballage verifie de la pile gym (cf. unwrap_engine).
        # Wrapping order: SelfPlayWrapper(ActionMasker(W40KEngine))
        # self.env is set by gym.Wrapper.__init__ to base_env (ActionMasker)
        self.engine: "W40KEngine" = unwrap_engine(self.env, "SelfPlayWrapper")

        # Episode tracking
        self.episode_reward = 0.0
        self.episode_length = 0

        # Self-play statistics
        self.player1_wins = 0
        self.player2_wins = 0
        self.draws = 0
        # LOG TEMPORAIRE: time between step() return and next step() call (--debug)
        self._last_step_return_time = None

    def reset(self, *, seed=None, options=None):
        """Reset environment for new episode."""
        # LOG TEMPORAIRE: time reset() when --debug (to explain slow step index 0)
        debug_mode = require_key(self.engine.game_state, "debug_mode")
        t0 = time.perf_counter() if debug_mode else None
        if debug_mode:
            try:
                debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(
                        f"RESET_START episode={int(self.engine.game_state.get('episode_number', 0))} "  # get allowed
                        f"seed={seed!r} options_present={options is not None}\n"
                    )
            except (OSError, IOError):
                pass
        obs, info = self.env.reset(seed=seed, options=options)
        if debug_mode and t0 is not None:
            reset_s = time.perf_counter() - t0
            ep = int(require_key(self.engine.game_state, "episode_number"))
            try:
                debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(f"RESET_END episode={ep} duration_s={reset_s:.6f}\n")
                    f.write(f"RESET_TIMING episode={ep} duration_s={reset_s:.6f}\n")
            except (OSError, IOError):
                pass
        self.episode_reward = 0.0
        self.episode_length = 0
        self._last_step_return_time = None
        return obs, info

    def step(self, action):
        """
        Execute one step in the environment.

        If it's Player 1's turn: Execute the provided action
        If it's Player 2's turn: Use frozen model action instead
        """
        # LOG TEMPORAIRE: time between previous step() return and this step() call (SB3 loop = predict + overhead, --debug)
        debug_mode = require_key(self.engine.game_state, "debug_mode")
        if debug_mode and self._last_step_return_time is not None:
            between_s = time.perf_counter() - self._last_step_return_time
            ep = int(require_key(self.engine.game_state, "episode_number"))
            step_idx = int(require_key(self.engine.game_state, "episode_steps"))
            try:
                debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(f"BETWEEN_STEP_TIMING episode={ep} step_index={step_idx} duration_s={between_s:.6f}\n")
            except (OSError, IOError):
                pass
        # CRITICAL: First handle any pending Player 2 turns before Player 1's action
        # This shouldn't happen normally, but safety check
        obs = None
        reward = 0.0
        terminated = False
        truncated = False
        info = {}

        agent_step_info: Dict[str, Any] = {}

        # Track P1 actions for diagnostic
        p1_actions_before = 0
        p1_terminal_reward = 0.0  # Capture lose penalty if P1 ends game before P0 acts
        # Garde anti-boucle-infinie derive de game_rules. Portee = les activations
        # CONSECUTIVES d'un joueur avant que P0 reprenne la main : la borne naturelle est
        # celle d'un TOUR (max_steps_per_turn * marge), pas celle d'un episode entier.
        max_iterations = self.engine.get_turn_step_limit()
        while not (terminated or truncated) and self.engine.game_state["current_player"] == 2:
            p1_actions_before += 1
            if p1_actions_before > max_iterations:
                current_phase = require_key(self.engine.game_state, "phase")
                print(f"\n[DEBUG] SelfPlayEnvWrapper: Infinite loop detected in P1 before loop! Count: {p1_actions_before}, episode_length: {self.episode_length}, phase: {current_phase}", flush=True)
                raise RuntimeError(f"SelfPlayEnvWrapper infinite loop (P1 before): {p1_actions_before} iterations, phase={current_phase}")
            player1_action = self._get_frozen_model_action()
            # LOG TEMPORAIRE: time full env.step() (--debug)
            t0_p1 = time.perf_counter() if debug_mode else None
            obs, reward, terminated, truncated, info = self.env.step(player1_action)
            if debug_mode and t0_p1 is not None:
                ep = int(require_key(self.engine.game_state, "episode_number"))
                step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                duration_s = time.perf_counter() - t0_p1
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                except (OSError, IOError):
                    pass
            self.episode_length += 1

            # If P1's action ended the game before P0 could act, capture the reward
            if terminated or truncated:
                p1_terminal_reward = reward

        # Now execute Player 0's action (if game not over)
        p0_reward = p1_terminal_reward  # Start with any terminal reward from P1's pre-emptive kill
        if not (terminated or truncated):
            # LOG TEMPORAIRE: time full env.step() (--debug)
            t0_p0 = time.perf_counter() if debug_mode else None
            obs, reward, terminated, truncated, info = self.env.step(action)
            if debug_mode and t0_p0 is not None:
                ep = int(require_key(self.engine.game_state, "episode_number"))
                step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                duration_s = time.perf_counter() - t0_p0
                try:
                    debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                    with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                except (OSError, IOError):
                    pass
            p0_reward = float(reward)  # CRITICAL: Save P0's reward before P1 overwrites it
            # Meme releve que dans BotControlledEnv, et pour la meme raison : les steps de P1
            # qui suivent vont remplacer `info`, et les cles qui decrivent l'action de P0 (la
            # phase ou elle a ete jouee, sa reussite, une charge aboutie) se liraient alors
            # comme celles de l'adversaire.
            agent_step_info = {key: info[key] for key in AGENT_STEP_INFO_KEYS if key in info}
            self.episode_reward += float(reward)
            self.episode_length += 1

            # DIAGNOSTIC: Log P0's reward for debugging (disabled for cleaner output)
            # if self.total_episodes < 3 and abs(reward) > 0.1:
            #     phase = self.engine.game_state.get("phase", "?")
            #     print(f"      [P0 Reward] action={agent_action}, reward={reward:.2f}, phase={phase}")

            # Handle any Player 1 turns that follow
            p1_actions_after = 0
            while not (terminated or truncated) and self.engine.game_state["current_player"] == 2:
                p1_actions_after += 1
                if p1_actions_after > max_iterations:
                    current_phase = require_key(self.engine.game_state, "phase")
                    print(f"\n[DEBUG] SelfPlayEnvWrapper: Infinite loop detected in P1 after loop! Count: {p1_actions_after}, episode_length: {self.episode_length}, phase: {current_phase}", flush=True)
                    raise RuntimeError(f"SelfPlayEnvWrapper infinite loop (P1 after): {p1_actions_after} iterations, phase={current_phase}")
                player1_action = self._get_frozen_model_action()
                # CRITICAL FIX: Capture reward when P1's action ends game!
                # When P1 kills last P0 unit, reward contains P0's LOSE penalty
                # LOG TEMPORAIRE: time full env.step() (--debug)
                t0_p1_after = time.perf_counter() if debug_mode else None
                obs, p1_step_reward, terminated, truncated, info = self.env.step(player1_action)
                if debug_mode and t0_p1_after is not None:
                    ep = int(require_key(self.engine.game_state, "episode_number"))
                    step_idx = int(require_key(self.engine.game_state, "episode_steps"))
                    duration_s = time.perf_counter() - t0_p1_after
                    try:
                        debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug.log")
                        with open(debug_path, "a", encoding="utf-8", errors="replace") as f:
                            f.write(f"WRAPPER_STEP_TIMING episode={ep} step_index={step_idx} duration_s={duration_s:.6f}\n")
                    except (OSError, IOError):
                        pass
                self.episode_length += 1
                p1_actions_after += 1

                # If P1's action ended the game, P0 needs the situational reward (win/lose)
                # The engine returns P0's perspective reward even for P1's actions
                if terminated or truncated:
                    p0_reward += float(p1_step_reward)  # Add win/lose bonus to P0's total

            # DIAGNOSTIC: Log if P1 took actions (disabled for cleaner output)
            # if (p1_actions_before + p1_actions_after) > 0 and self.total_episodes < 3:
            #     phase = self.engine.game_state.get("phase", "?")
            #     print(f"    [SelfPlay] P0 action={agent_action}, P1 took {p1_actions_before}+{p1_actions_after} actions, phase={phase}")

        # CRITICAL: Return P0's reward to SB3, not P1's!
        reward = p0_reward
        apply_agent_step_info(info, agent_step_info)

        # Track episode end statistics
        if terminated or truncated:
            self.total_episodes += 1
            self.episodes_since_update += 1

            # Track wins/losses
            winner = require_present(require_key(info, "winner"), "winner")
            if winner == PLAYER_ONE_ID:
                self.player1_wins += 1
            elif winner == PLAYER_TWO_ID:
                self.player2_wins += 1
            else:
                self.draws += 1

        if debug_mode:
            self._last_step_return_time = time.perf_counter()
        return obs, reward, terminated, truncated, info

    def _get_frozen_model_action(self) -> int:
        """
        Get action from frozen model for Player 2.
        """
        if self.frozen_model is None:
            action_mask, eligible_units = self.engine.action_decoder.get_squad_action_mask_and_eligible_units(self.engine.game_state)
            # POINT DE CHOIX JOUEUR en attente : le pool est vide PAR CONSTRUCTION, mais
            # `ACTION_WAIT` est hors masque dans cet état — le renvoyer léverait. Symétrique du
            # cas traité dans `BotControlledEnv._get_bot_action`. La branche avec `frozen_model`
            # laisse `predict(action_masks=…)` choisir le slot : elle affirmait le faire alors
            # qu'elle sortait sur `ACTION_WAIT` avant d'y arriver — corrigé plus bas, et verrouillé
            # par `test_frozen_model_is_asked_to_answer_a_pending_decision`.
            pending_choice_action = random_action_for_pending_choice(
                self.engine.game_state, action_mask, "SelfPlayWrapper"
            )
            if pending_choice_action is not None:
                return pending_choice_action
            if not eligible_units:
                # Pool empty -> advance phase via WAIT/invalid action handling
                return mi.ACTION_WAIT
            valid_actions = [i for i in range(len(action_mask)) if action_mask[i]]
            if not valid_actions:
                # architecture_moteur.md: Empty masks indicate a flow/phase bug;
                # SelfPlayWrapper must not silently inject dummy actions.
                raise RuntimeError(
                    "SelfPlayWrapper encountered an empty action mask for Player 2. "
                    "Engine must advance phase/turn instead of exposing empty masks."
                )
            if not self.allow_random_opponent:
                # V11 §10.4 : pas de repli silencieux sur des actions aleatoires.
                # `update_frozen_model` n'ayant aucun appelant, ce repli restait actif
                # du premier au dernier episode et rendait tout win-rate insignifiant.
                raise RuntimeError(
                    "SelfPlayWrapper: aucun frozen_model pour Player 2. Un adversaire "
                    "aleatoire n'est pas un adversaire d'entrainement valide (V11 §10.4). "
                    "Fournir un frozen_model, utiliser BotControlledEnv (bot_training), "
                    "ou passer allow_random_opponent=True explicitement (tests)."
                )
            return random.choice(valid_actions)

        # Use frozen model to predict action WITH action masking
        # CRITICAL: MaskablePPO requires action_masks parameter for proper masked inference
        action_mask, eligible_units = self.engine.action_decoder.get_squad_action_mask_and_eligible_units(self.engine.game_state)
        # Decision agent en attente : pool vide par construction, et `ACTION_WAIT` est hors masque.
        # Cette branche sortait ici sans jamais atteindre `predict` — c'est la moitie du cas §9.3 P2
        # que la branche sans modele traitait deja, et que son commentaire declarait a tort tenue.
        if not eligible_units and not engine_is_paused_on_player_choice(self.engine.game_state):
            # Pool empty -> advance phase via WAIT/invalid action handling
            return mi.ACTION_WAIT
        # Jumeau de `_get_self_play_opponent_action` : rien ne touche l'etat entre le masque et
        # cette observation, on transmet au lieu de reconstruire.
        obs = self.engine._build_observation(mask_and_eligible=(action_mask, eligible_units))

        # MaskablePPO.predict() expects action_masks as keyword argument
        # CRITICAL: Use deterministic=False so P1 explores like P0 (fair self-play)
        action, _ = self.frozen_model.predict(obs, deterministic=False, action_masks=action_mask)

        return int(action)

    def update_frozen_model(self, new_model):
        """
        Update the frozen model with a copy of the current learning model.
        Should be called periodically (e.g., every N episodes).

        Note: This method is deprecated. Use the persistent_frozen_model approach
        in the training loop instead, which properly saves/loads via temp file.
        """
        # Set directly - the caller is responsible for providing an independent copy
        self.frozen_model = new_model
        self.episodes_since_update = 0
        print(f"  🔄 Self-play: Updated frozen opponent (Episode {self.total_episodes})")

    def should_update_frozen_model(self) -> bool:
        """Check if it's time to update the frozen model."""
        return self.episodes_since_update >= self.update_frequency

    def get_win_rate_stats(self) -> dict:
        """Get win rate statistics for Player 1 (learning agent)."""
        total_games = self.player1_wins + self.player2_wins + self.draws
        if total_games == 0:
            return {
                'player1_wins': 0,
                'player2_wins': 0,
                'draws': 0,
                'player1_win_rate': 0.0,
                'total_games': 0
            }

        return {
            'player1_wins': self.player1_wins,
            'player2_wins': self.player2_wins,
            'draws': self.draws,
            'player1_win_rate': self.player1_wins / total_games * 100,
            'total_games': total_games
        }

    def close(self):
        """Close the wrapped environment."""
        self.env.close()
