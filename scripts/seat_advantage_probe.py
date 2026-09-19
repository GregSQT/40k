#!/usr/bin/env python3
"""Décomposition de l'avantage du PREMIER JOUEUR, en miroir bot contre le même bot.

POURQUOI CET OUTIL EXISTE
    Mesuré le 2026-09-19 : en miroir (même bot des deux côtés, seul le siège change), le joueur
    qui joue premier gagnait 0,588 contre 0,398 sur `terrain-mc1`. L'écart était DANS LE JEU, pas
    dans l'agent : aucune politique apprise n'intervient, et le réglage `agent_seat_p2_ratio`
    (0,75) ne faisait que compenser l'agent sans toucher à la cause.

    C'est cet outil qui a désigné la cause — l'instant de marquage de la mission — et la mission
    a été corrigée le même jour : le second joueur marque désormais à la fin de son tour à chaque
    round, comme le veut 26 Primary missions. L'outil reste le juge de tout réglage ultérieur du
    siège, et la variante `p2-scores-at-command` rejoue l'ancien régime pour que les chiffres
    publiés avant et après restent comparables.

    ⚠️ CE QUI EST DÉJÀ RÉFUTÉ, ne pas le remesurer : l'information du DERNIER DÉPLOYEUR. Le
    déploiement alterne depuis le joueur 1 (`_resolve_next_deployer_after_success`), donc le
    joueur 2 finit en dernier seulement à effectifs égaux — vrai pour les scénarios holdout 01
    (SM/SM) et 04 (Ork/Ork), faux pour 02 et 03 (5 unités Space Marines contre 6 Orks). Or
    l'avance du joueur 1 y est la même : 0,588 / 0,613 / 0,590 / 0,605. Le dernier mot au
    déploiement ne compense rien de mesurable.

CE QU'IL MESURE, PAR ÉPISODE
    - le vainqueur et le siège, donc le win-rate ABSOLU par siège ;
    - les points de victoire et la valeur d'armée survivante des DEUX joueurs à chaque FRONTIÈRE
      DE TOUR DE JOUEUR, donc l'instant où l'écart se creuse (prime de premier marquage contre
      accumulation) et la part d'attrition (« alpha strike » : le premier joueur tire le premier
      et retire de la valeur avant d'être touché en retour).

    ⚠️ LA FRONTIÈRE EST RELEVÉE SUR LE STEP MOTEUR, jamais sur le step gym. Un step gym couvre
    PLUSIEURS steps moteur (tour du bot, WAIT forcés — cf. `BotControlledEnv.step`) : relevé là,
    « fin du round 1 » contenait déjà le marquage du joueur 1 au round 2 (mesuré : 10 VP à un
    instant où le scoring n'a pas commencé). L'enveloppe est posée sur
    `W40KEngine.step_with_mask`, qui est le step moteur du gym.

CE QU'IL NE FAIT PAS
    Aucune écriture dans `config/`, `ai/models/` ni le moteur. La variante `no-p1-turn2-score`
    est un CONTREFACTUEL posé DANS LE PROCESSUS DE MESURE (enveloppe de
    `GameStateManager.apply_primary_objective_scoring`), jamais un comportement livré : elle
    répond à « que devient l'avance si le premier joueur ne marque pas au round 2 ? ».

    Aucun repli sur une donnée absente : `winner` et `controlled_player` sont lus par
    `require_key`, un épisode non terminé LÈVE au lieu d'être compté en défaite.

    ⚠️ LE RÉSULTAT N'EST PAS REPRODUCTIBLE AU BIT PRÈS, même à graine fixée. Mesuré : deux
    exécutions identiques rendent 0,593 et 0,606 sur 1 200 parties (le hachage des chaînes de
    CPython est randomisé par processus, et les départages de bot en dépendent). Toute variante
    se compare donc sur au moins 1 200 parties, et un écart sous 2 points N'EST PAS un résultat.
    L'erreur-type est publiée à côté de chaque chiffre pour cette raison.

USAGE
    python3 scripts/seat_advantage_probe.py --episodes 50
    python3 scripts/seat_advantage_probe.py --episodes 50 --variant p2-scores-at-command
    python3 scripts/seat_advantage_probe.py --episodes 50 --terrain terrain-mc2.json
    python3 scripts/seat_advantage_probe.py --episodes 50 --mission objectives_control

`--mission` n'a AUJOURD'HUI qu'une valeur acceptable, et c'est déjà celle de tous les scénarios :
les cinq autres missions de `config/primary_objective/` sont au format `scoring_events`, qu'aucun
fichier de `engine/` ne lit. L'option existe pour le jour où une seconde mission sera scorable ;
`_require_supported_mission` refuse les autres à l'ouverture plutôt qu'au premier tour marquant.

PLATEAU : `W40K_BOARD_PATH` est posé AVANT tout import du moteur, depuis le suffixe `_x<N>` de
l'agent — sans lui `config/config.json` impose le plateau x5 et la mesure ne se compare à rien
(même règle que `ai/train.py` et `scripts/seat_matrix_probe.py`).

THREADS : le bloc `training_env` de `config/config.json` est posé avant tout import de torch ;
sans lui les workers se marchent dessus (mesuré en S27 : 12 workers à 38 threads sur 16 cœurs).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

#: Variantes de contrefactuel. `none` = le jeu tel qu'il est livré.
#:
#: `p2-scores-at-command` REJOUE L'ANCIENNE RÈGLE, celle d'avant le 2026-09-19 : le second joueur
#: marquait à sa phase de commandement comme le premier, sauf au round 5. Or marquer à sa phase de
#: commandement n'a pas la même valeur selon le siège — quand le premier joueur compte au round R,
#: chacun a joué R-1 tours ; quand le second compte au round R, son adversaire en a joué R. Le
#: second comptait donc toujours après un tour adverse de plus que le sien.
#:
#: La mission applique désormais la règle officielle (26 Primary_missions : « The player who has
#: the second turn scores VP as described above, but does so at the end of their turn instead of
#: at the end of their Command phase »), sans restriction de round. Cette variante existe pour que
#: l'écart reste MESURABLE après coup : elle est le seul moyen de rejouer l'ancien régime sans
#: revenir en arrière dans le moteur, et c'est elle qui rend comparables les chiffres publiés
#: avant et après le changement.
VARIANTS: Tuple[str, ...] = ("none", "no-p1-turn2-score", "p2-scores-at-command")


def board_path_for_agent(agent: str) -> str:
    """Répertoire de plateau déduit du suffixe `_x<N>` de la clé d'agent ; lève sans suffixe."""
    from config_loader import BOARD_DIR_BY_INCHES_TO_SUBHEX

    match = re.search(r"_x(\d+)", agent)
    if match is None:
        raise ValueError(
            f"Impossible de déduire la résolution depuis le nom d'agent '{agent}' "
            "(suffixe _x1 / _x5 attendu)."
        )
    resolution = int(match.group(1))
    if resolution not in BOARD_DIR_BY_INCHES_TO_SUBHEX:
        raise ValueError(f"Résolution {resolution} inconnue pour l'agent '{agent}'.")
    return BOARD_DIR_BY_INCHES_TO_SUBHEX[resolution]


def apply_training_env(config_path: Path) -> None:
    """Pose le bloc `training_env` de `config/config.json` dans l'environnement du processus."""
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    for key, value in config["training_env"].items():
        os.environ.setdefault(str(key), str(value))


def _install_variant(variant: str) -> None:
    """Pose le contrefactuel demandé DANS CE PROCESSUS. `none` ne touche à rien.

    Enveloppe et non copie : le chemin de scoring reste celui de la production, seule la
    condition d'entrée change. Une réimplémentation du scoring mesurerait un autre jeu.
    """
    if variant == "none":
        return
    if variant not in VARIANTS:
        raise ValueError(f"Variante inconnue : {variant!r} (attendu : {VARIANTS})")

    from engine.game_state import GameStateManager
    from shared.data_validation import require_key

    if "variant" in _INSTALLED:
        return
    _INSTALLED.add("variant")
    original = GameStateManager.apply_primary_objective_scoring

    if variant == "no-p1-turn2-score":
        def _scoring(self, game_state, scoring_phase):  # type: ignore[no-untyped-def]
            if (
                int(require_key(game_state, "turn")) == 2
                and int(require_key(game_state, "current_player")) == 1
            ):
                return None
            return original(self, game_state, scoring_phase)
    else:
        _scoring = original

        # ANCIEN RÉGIME : le second joueur marque à sa phase de commandement, sauf au round 5.
        #
        # Une seule pièce suffit, et c'est l'inverse de ce que demandait le contrefactuel d'avant
        # le changement : on bascule le `timing` du second joueur sur la phase du PREMIER, sauf
        # au round 5 où la mission livrée le faisait déjà marquer en fin de tour. Le site d'appel
        # de fin de tour existe désormais à chaque round, mais il ne verse rien quand la phase
        # attendue du siège est la phase de commandement — `_apply_primary_objective_scoring_single`
        # sort sur la comparaison de phase, exactement comme il le faisait aux rounds 2 à 4 avant.
        import copy

        original_single = GameStateManager._apply_primary_objective_scoring_single

        def _single(self, game_state, scoring_phase, primary_objective):  # type: ignore[no-untyped-def]
            if (
                int(require_key(game_state, "current_player")) == 2
                and int(require_key(game_state, "turn")) != 5
            ):
                primary_objective = copy.deepcopy(primary_objective)
                timing = require_key(primary_objective, "timing")
                timing["second_player_phase"] = require_key(timing, "first_player_phase")
            return original_single(self, game_state, scoring_phase, primary_objective)

        GameStateManager._apply_primary_objective_scoring_single = _single  # type: ignore[method-assign]

    GameStateManager.apply_primary_objective_scoring = _scoring  # type: ignore[method-assign]


#: Timeline de l'épisode courant, alimentée par l'enveloppe de `step_with_mask` posée par
#: `_install_timeline`. Remise à zéro par le worker à chaque `reset`.
_TIMELINE: List[Dict[str, int]] = []

#: VP réellement attribués, relevés à l'instant de l'attribution par `_install_vp_events`.
#: SÉPARÉ de la timeline, et c'est la raison d'être des deux instruments : le moteur enchaîne
#: plusieurs phases DANS LE MÊME step (cascade `phase_complete`), donc le marquage du début du
#: tour d'un joueur est déjà fait quand la frontière de tour devient observable. Mesuré : 8,75 VP
#: attribués au joueur 1 dans le segment du tour du joueur 2. La frontière reste bonne pour
#: l'ATTRITION (les morts tombent au milieu d'une phase, pas dans la cascade) ; elle ne l'est pas
#: pour le SCORE, qui se relève donc là où il est versé.
_VP_EVENTS: List[Dict[str, int]] = []

#: Enveloppes déjà posées DANS CE PROCESSUS. Un worker traite plusieurs tâches, et chaque tâche
#: réinstalle : sans ce registre, la seconde tâche empilerait une seconde enveloppe sur la
#: première et compterait chaque versement de VP deux fois.
_INSTALLED: set = set()


def _canonical_index(turn: int, player: int) -> int:
    """Rang du tour de joueur dans la suite (1,1), (1,2), (2,1)… — strictement croissant."""
    return (int(turn) - 1) * 2 + (int(player) - 1)


def _opens_new_turn(
    last: Optional[Tuple[int, int]], turn: int, player: int, phase: str
) -> bool:
    """Vrai si `(turn, player)` OUVRE un tour de joueur qu'on n'a pas encore relevé.

    Trois refus, chacun sur un défaut mesuré :

    - pendant le déploiement, `current_player` alterne à chaque pose (déploiement alterné) et
      aucun de ces basculements n'est un tour de joueur ;
    - avant le premier relevé, seul (1, 1) ouvre la suite : commencer ailleurs décalerait tout
      l'épisode d'un demi-round ;
    - ensuite, le couple doit AVANCER dans l'ordre canonique. Reculer ou rester, c'est un
      aller-retour interne au tour (allocation de pertes en tir, désignation de cohérence,
      sous-phases de combat) — 116 relevés pour 16 épisodes sans ce filtre. Avancer de plus d'un
      rang est accepté : un tour sans rien à y faire est résolu en un seul step moteur et reste
      invisible, et exiger le successeur immédiat désynchronisait la timeline pour tout le reste
      de l'épisode.
    """
    if phase == "deployment":
        return False
    if last is None:
        return (turn, player) == (1, 1)
    return _canonical_index(turn, player) > _canonical_index(*last)


def _install_vp_events() -> None:
    """Relève (round, joueur, VP versés) à l'instant exact de l'attribution.

    Enveloppe `GameStateManager.apply_primary_objective_scoring`, l'entrée unique du scoring du
    primaire. Posée APRÈS la variante, donc elle mesure ce qui a RÉELLEMENT été versé, contrefactuel
    compris.
    """
    from engine.game_state import GameStateManager
    from shared.data_validation import require_key

    if "vp_events" in _INSTALLED:
        return
    _INSTALLED.add("vp_events")
    original = GameStateManager.apply_primary_objective_scoring

    def _wrapped(self, game_state, scoring_phase):  # type: ignore[no-untyped-def]
        victory_points = require_key(game_state, "victory_points")
        before = {player: int(require_key(victory_points, player)) for player in (1, 2)}
        outcome = original(self, game_state, scoring_phase)
        gained = {
            player: int(require_key(victory_points, player)) - before[player]
            for player in (1, 2)
        }
        if any(gained.values()):
            _VP_EVENTS.append({
                "turn": int(require_key(game_state, "turn")),
                "player": int(require_key(game_state, "current_player")),
                "vp_gained_p1": gained[1],
                "vp_gained_p2": gained[2],
            })
        return outcome

    GameStateManager.apply_primary_objective_scoring = _wrapped  # type: ignore[method-assign]


def _install_timeline() -> None:
    """Relève l'état aux FRONTIÈRES DE TOUR DE JOUEUR, sur le step moteur.

    Une seule enveloppe, posée une fois par processus. Le coût par step est une comparaison de
    deux entiers ; la valeur d'armée — qui parcourt les unités — n'est calculée qu'AUX
    frontières, soit dix fois par épisode au lieu de plusieurs milliers.
    """
    from engine.game_state import army_value_by_player
    from engine.w40k_core import W40KEngine
    from shared.data_validation import require_key

    if "timeline" in _INSTALLED:
        return
    _INSTALLED.add("timeline")
    original = W40KEngine.step_with_mask

    def _record(game_state: Dict[str, Any], turn: int, player: int) -> None:
        victory_points = require_key(game_state, "victory_points")
        value = army_value_by_player(game_state)
        _TIMELINE.append({
            "turn": turn,
            "player": player,
            "vp_p1": int(require_key(victory_points, 1)),
            "vp_p2": int(require_key(victory_points, 2)),
            "value_p1": int(value[1]),
            "value_p2": int(value[2]),
        })

    def _observe(game_state: Dict[str, Any]) -> None:
        """Retient le début d'un tour de joueur, et RIEN d'autre.

        `current_player` ne suffit pas comme frontière : il bascule AUSSI à l'intérieur d'un tour,
        aux points d'arrêt rendus au camp d'en face — allocation de pertes en tir
        (`shooting_handlers`), désignation de cohérence et sous-phases de combat
        (`fight_handlers`), et à chaque pose pendant le déploiement alterné. Mesuré : 116 relevés
        pour 16 épisodes avant ce filtre.

        Le seul ordre qui compte est CANONIQUE — (1,1), (1,2), (2,1), (2,2)… — et il commence
        quand le déploiement est fini. Un couple observé n'est retenu que s'il AVANCE dans cet
        ordre ; tout aller-retour est ignoré.

        « Avance », et non « est le suivant » : un tour de joueur peut être ENTIÈREMENT résolu
        dans un seul step moteur quand il n'y a rien à y faire (cascade `phase_complete` —
        `W40KEngine.execute_semantic_action` enchaîne plusieurs phases dans la même action). Le
        couple intermédiaire n'est alors visible de personne. Exiger le successeur immédiat
        désynchronisait la timeline pour le reste de l'épisode : mesuré sur 1 épisode de 1 200,
        où le tour du joueur 1 au round 5 manquait. Un tour sauté n'a simplement aucun segment,
        ce qui est la bonne lecture — il n'y a ni marquage ni destruction à lui attribuer.
        """
        turn = int(require_key(game_state, "turn"))
        player = int(require_key(game_state, "current_player"))
        last = (_TIMELINE[-1]["turn"], _TIMELINE[-1]["player"]) if _TIMELINE else None
        if _opens_new_turn(last, turn, player, str(require_key(game_state, "phase"))):
            _record(game_state, turn, player)

    def _wrapped(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        _observe(self.game_state)
        outcome = original(self, *args, **kwargs)
        _observe(self.game_state)
        return outcome

    W40KEngine.step_with_mask = _wrapped  # type: ignore[method-assign]


def _close_timeline(game_state: Dict[str, Any]) -> None:
    """Ferme la timeline sur l'état FINAL, sinon le dernier tour de joueur n'a pas de segment."""
    from engine.game_state import army_value_by_player
    from shared.data_validation import require_key

    if not _TIMELINE:
        return
    last = _TIMELINE[-1]
    victory_points = require_key(game_state, "victory_points")
    value = army_value_by_player(game_state)
    _TIMELINE.append({
        "turn": last["turn"] if last["player"] == 1 else last["turn"] + 1,
        "player": 2 if last["player"] == 1 else 1,
        "vp_p1": int(require_key(victory_points, 1)),
        "vp_p2": int(require_key(victory_points, 2)),
        "value_p1": int(value[1]),
        "value_p2": int(value[2]),
    })


def _segments(timeline: List[Dict[str, int]]) -> List[Dict[str, int]]:
    """Convertit la timeline en SEGMENTS « tour du joueur P au round R ».

    Un segment porte la valeur d'armée DÉTRUITE pendant ce tour de joueur, dans chaque camp. Les
    VP n'y figurent pas : ils viennent de `_VP_EVENTS`, pour la raison écrite là-bas.
    """
    segments: List[Dict[str, int]] = []
    for previous, current in zip(timeline, timeline[1:]):
        segments.append({
            "turn": previous["turn"],
            "player": previous["player"],
            "value_lost_p1": previous["value_p1"] - current["value_p1"],
            "value_lost_p2": previous["value_p2"] - current["value_p2"],
        })
    return segments


def _require_supported_mission(mission: str) -> None:
    """Refuse une mission que le moteur ne sait pas scorer, AVANT de lancer la mesure.

    `config/primary_objective/` porte deux formats. Seul celui à clés `scoring` / `timing` est
    lu (`GameStateManager._apply_primary_objective_scoring_single`) ; les cinq missions à
    `scoring_events` (Battlefield Dominance, Immovable Object, Meatgrinder…) ne sont PAS
    implémentées — aucun fichier de `engine/` ni de `ai/` ne mentionne cette clé. Lancer la sonde
    dessus lèverait au premier tour marquant, plusieurs minutes plus tard, sur un message qui ne
    dirait pas pourquoi.
    """
    path = PROJECT_ROOT / "config" / "primary_objective"
    candidates = sorted(path.glob("*.json"))
    supported, unsupported = [], []
    for candidate in candidates:
        with open(candidate, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        (supported if "scoring" in data else unsupported).append(str(data["id"]))
    if mission in supported:
        return
    if mission in unsupported:
        raise ValueError(
            f"Mission '{mission}' au format 'scoring_events' : le moteur ne l'implémente pas "
            f"(aucun lecteur de cette clé dans engine/). Missions scorables : {supported}."
        )
    raise ValueError(f"Mission '{mission}' introuvable dans {path} (connues : {supported + unsupported}).")


def _scenario_variants(
    scenarios: List[str], terrain: Optional[str], mission: Optional[str]
) -> List[str]:
    """Réécrit les scénarios avec un autre terrain et/ou une autre mission, hors de `config/`.

    Les fichiers produits ne sont JAMAIS écrits dans `config/` : un scénario de sonde qui s'y
    glisserait entrerait dans la rotation d'entraînement (l'énumération de `ai/training_utils.py`
    ramasse `scenario_*.json`).

    ⚠️ L'ARBORESCENCE `agents/<clé>/scenarios/<split>/` EST OBLIGATOIRE, et c'est pour ça que
    `out_dir` n'est pas libre : la clé d'agent et le split sont dérivés du CHEMIN du scénario
    (`ai/train.py::_count_units_from_roster_scenario`, `ValueError: Cannot resolve agent key from
    scenario path`), et les refs de roster du scénario sont validées contre ce split. Même
    montage que les surcharges de `wall_ref` du chemin d'entraînement, et même racine
    (`ai.scenario_scratch`, sous le dépôt) : un scénario matérialisé dans `/tmp` fait refuser
    l'épisode dès que le step logging est actif, son chemin n'étant pas journalisable.
    """
    if terrain is None and mission is None:
        return scenarios
    from ai.scenario_scratch import make_scenario_scratch_dir

    scratch_root = Path(make_scenario_scratch_dir("w40k_seatprobe_"))
    rewritten: List[str] = []
    for path in scenarios:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if terrain is not None:
            data["terrain_ref"] = terrain
        if mission is not None:
            data["primary_objectives"] = [mission]
        parts = Path(os.path.abspath(path)).parts
        agent_key = parts[parts.index("agents") + 1]
        split = parts[parts.index("scenarios", parts.index("agents") + 2) + 1]
        target_dir = scratch_root / "agents" / agent_key / "scenarios" / split
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / os.path.basename(path)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
        rewritten.append(str(target))
    print(f"   scénarios réécrits dans {scratch_root}")
    return rewritten


def _episode_seed(base_seed: int, bot: str, scenario_index: int, ep_idx: int) -> int:
    """Graine reproductible et distincte par (bot, scénario, épisode).

    `zlib.crc32` et non `hash()` : le hachage de CPython est randomisé par processus, une graine
    qui en dépendrait changerait d'un lancement à l'autre.
    """
    import zlib

    digest = zlib.crc32(bot.encode("utf-8"))
    return ((base_seed * 1_000_003) ^ (digest & 0x7FFFFFFF)) + scenario_index * 7919 + ep_idx


def _play(
    *,
    bot: str,
    scenario_file: str,
    scenario_index: int,
    n_episodes: int,
    base_seed: int,
    randomness: Dict[str, float],
    env_kwargs: Dict[str, Any],
    max_steps_per_episode: int,
    variant: str,
) -> Dict[str, Any]:
    """Joue `n_episodes` du MÊME bot des deux côtés et relève le déroulé round par round."""
    import random

    import numpy as np

    _install_variant(variant)
    _install_vp_events()
    _install_timeline()

    from ai.bot_evaluation import _create_eval_env
    from ai.bot_registry import build_bot
    from engine.constants import DRAW_WINNER
    from shared.data_validation import require_key

    agent_bot = build_bot(bot, randomness)
    # SIÈGE TIRÉ PAR TÂCHE, et c'est ce qui rend le contrôle de chemin de décision lisible.
    # `BotControlledEnv._resolve_controlled_player_for_episode` tire le siège d'un hachage de
    # (graine, rang d'env, index d'épisode) — et rien d'autre. Toutes les tâches partagent le rang
    # 0 et l'index de départ 0, donc une graine commune leur donnait à toutes LA MÊME suite de
    # sièges : l'épisode i jouait le même siège dans les 24 tâches, et le bot du siège agent ne
    # changeait jamais de côté à index donné. Mélanger la graine avec (bot, scénario) décorrèle le
    # siège du chemin de décision, ce que la ligne de contrôle prétend mesurer.
    env = _create_eval_env(
        bot_name=bot,
        bot_type=bot,
        randomness_config=randomness,
        scenario_file=scenario_file,
        **{**env_kwargs, "agent_seat_seed": _episode_seed(base_seed, bot, scenario_index, 0)},
    )
    tally: "Counter[str]" = Counter()
    # `segments["<round>:<joueur>"]` = ce qui a changé PENDANT ce tour de joueur, cumulé.
    segments: Dict[str, "Counter[str]"] = {}
    try:
        for ep_idx in range(n_episodes):
            seed = _episode_seed(base_seed, bot, scenario_index, ep_idx)
            random.seed(seed)
            np.random.seed(seed)
            _TIMELINE.clear()
            _VP_EVENTS.clear()
            _obs, info = env.reset(seed=seed)
            seat = int(require_key(info, "controlled_player"))
            done = False
            steps = 0

            while not done and steps < max_steps_per_episode:
                action = env.scripted_action_for_agent_side(agent_bot)
                _obs, _reward, terminated, truncated, info = env.step(action)
                done = bool(terminated) or bool(truncated)
                steps += 1
            if not done:
                raise RuntimeError(
                    f"Épisode non terminé en {max_steps_per_episode} pas "
                    f"({bot}, {os.path.basename(scenario_file)}) — le compter en défaite "
                    "fausserait la mesure."
                )
            tally["episodes"] += 1
            tally["truncated"] += int(bool(truncated))
            _close_timeline(env.engine.game_state)
            for segment in _segments(_TIMELINE):
                bucket = segments.setdefault(f"{segment['turn']}:{segment['player']}", Counter())
                bucket["episodes"] += 1
                for field in ("value_lost_p1", "value_lost_p2"):
                    bucket[field] += segment[field]
            for event in _VP_EVENTS:
                bucket = segments.setdefault(f"{event['turn']}:{event['player']}", Counter())
                for field in ("vp_gained_p1", "vp_gained_p2"):
                    bucket[field] += event[field]

            winner = require_key(info, "winner")
            tally[f"seat{seat}_episodes"] += 1
            tally["p1_wins"] += int(winner == 1)
            tally["p2_wins"] += int(winner == 2)
            tally["draws"] += int(winner == DRAW_WINNER)
            # Le bot du siège AGENT et celui du siège adverse passent par deux chemins de
            # décision distincts (`scripted_action_for_agent_side` contre le bot du wrapper) :
            # ventiler par siège du bot agent est le CONTRÔLE de cette dissymétrie. Si l'avance
            # suit le siège 1 dans les deux allocations, elle ne vient pas du chemin de décision.
            tally[f"seat{seat}_wins"] += int(winner == seat)
    finally:
        env.close()
    return {
        "bot": bot,
        "scenario": os.path.basename(scenario_file),
        "tally": dict(tally),
        "segments": {k: dict(v) for k, v in segments.items()},
    }


def _standard_error(successes: int, total: int) -> Optional[float]:
    if total <= 0:
        return None
    p = successes / total
    return math.sqrt(p * (1.0 - p) / total)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Décomposition de l'avantage du premier joueur (miroir bot, sans agent)."
    )
    parser.add_argument("--agent", default="ArmageddonAgent_x1")
    parser.add_argument("--training-config", default="x1")
    parser.add_argument("--scenario-pool", default="holdout", choices=["holdout", "training"])
    parser.add_argument("--episodes", type=int, default=50,
                        help="Épisodes par bot ET par scénario.")
    parser.add_argument("--variant", default="none", choices=list(VARIANTS))
    parser.add_argument("--terrain", default=None,
                        help="Remplace terrain_ref des scénarios (ex. terrain-mc2.json).")
    parser.add_argument("--mission", default=None,
                        help="Remplace primary_objectives. Seule mission scorable par le moteur "
                             "aujourd'hui : objectives_control (cf. _require_supported_mission).")
    parser.add_argument("--bots", default=None, help="Liste séparée par des virgules.")
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--out", default=None, help="Chemin d'export JSON du relevé complet.")
    args = parser.parse_args()

    if args.episodes <= 0:
        raise ValueError("--episodes doit être > 0")
    if args.mission is not None:
        _require_supported_mission(args.mission)

    os.environ["W40K_BOARD_PATH"] = board_path_for_agent(args.agent)
    apply_training_env(PROJECT_ROOT / "config" / "config.json")

    from ai.bot_evaluation import _load_bot_eval_params
    from ai.training_utils import get_scenario_list_for_phase
    from config_loader import get_config_loader
    from shared.data_validation import require_key

    config_loader = get_config_loader()
    eval_params = _load_bot_eval_params(config_loader, args.agent, args.training_config)
    randomness = require_key(eval_params, "randomness")
    bots = (
        [b.strip() for b in args.bots.split(",") if b.strip()]
        if args.bots
        else sorted(require_key(eval_params, "weights").keys())
    )
    training_config = config_loader.load_agent_training_config(args.agent, args.training_config)
    scenarios = get_scenario_list_for_phase(
        config_loader, args.agent, args.training_config, args.scenario_pool
    )
    if not scenarios:
        raise RuntimeError(
            f"Aucun scénario pour agent={args.agent} pool={args.scenario_pool} — rien à mesurer."
        )
    scenarios = _scenario_variants(scenarios, args.terrain, args.mission)

    game_rules = require_key(config_loader.get_game_config(), "game_rules")
    max_steps_per_episode = int(require_key(game_rules, "max_turns")) * 400
    env_kwargs = {
        "training_config_name": args.training_config,
        "rewards_config_name": args.agent,
        "controlled_agent": args.agent,
        "base_agent_key": args.agent,
        "debug_mode": False,
        "agent_seat_mode": require_key(training_config, "agent_seat_mode"),
        "agent_seat_seed": args.seed,
    }

    tasks = [
        (bot, scenario_index, scenario_file)
        for bot in bots
        for scenario_index, scenario_file in enumerate(scenarios)
    ]
    total_episodes = len(tasks) * args.episodes
    print(
        f"🎲 Miroir bot — {len(bots)} bots × {len(scenarios)} scénario(s) × {args.episodes} = "
        f"{total_episodes} épisodes"
    )
    print(
        f"   pool={args.scenario_pool} · variante={args.variant} · "
        f"terrain={args.terrain or 'scénario'} · mission={args.mission or 'scénario'}"
    )

    results: List[Dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers or os.cpu_count()) as pool:
        futures = {
            pool.submit(
                _play,
                bot=bot,
                scenario_file=scenario_file,
                scenario_index=scenario_index,
                n_episodes=args.episodes,
                base_seed=args.seed,
                randomness=randomness,
                env_kwargs=env_kwargs,
                max_steps_per_episode=max_steps_per_episode,
                variant=args.variant,
            ): (bot, scenario_file)
            for bot, scenario_index, scenario_file in tasks
        }
        for done_count, future in enumerate(as_completed(futures), start=1):
            result = future.result()  # propage les exceptions sans les avaler
            results.append(result)
            tally = result["tally"]
            played = tally["p1_wins"] + tally["p2_wins"] + tally["draws"]
            print(
                f"   [{done_count}/{len(tasks)}] {result['bot']:12s} {result['scenario']:28s} "
                f"P1 {tally['p1_wins']}/{played}",
                flush=True,
            )

    total: "Counter[str]" = Counter()
    per_scenario: Dict[str, "Counter[str]"] = {}
    segments_total: Dict[Tuple[int, int], "Counter[str]"] = {}
    for result in results:
        total.update(result["tally"])
        per_scenario.setdefault(result["scenario"], Counter()).update(result["tally"])
        for key, bucket in result["segments"].items():
            turn_str, player_str = key.split(":")
            segments_total.setdefault((int(turn_str), int(player_str)), Counter()).update(bucket)

    played = total["p1_wins"] + total["p2_wins"] + total["draws"]
    p1_rate = total["p1_wins"] / played
    stderr = _standard_error(total["p1_wins"], played)
    print("\n📊 Win-rate ABSOLU par siège")
    for scenario, bucket in sorted(per_scenario.items()):
        n = bucket["p1_wins"] + bucket["p2_wins"] + bucket["draws"]
        print(
            f"   {scenario:30s} P1 {bucket['p1_wins'] / n:.3f}  P2 {bucket['p2_wins'] / n:.3f}  "
            f"nuls {bucket['draws']:3d}  n={n}"
        )
    print(
        f"   {'TOTAL':30s} P1 {p1_rate:.3f}  P2 {total['p2_wins'] / played:.3f}  "
        f"nuls {total['draws']:3d}  n={played}  erreur-type {stderr * 100:.2f} pt"
    )
    # CONTRÔLE : le bot du siège agent et celui du siège adverse passent par deux chemins de
    # décision distincts. Si l'avance suit le SIÈGE dans les deux allocations, elle ne vient pas
    # du chemin. Une allocation vide ne contrôle rien, et l'afficher « 0/0 » le laisserait croire.
    if not total["seat1_episodes"] or not total["seat2_episodes"]:
        raise RuntimeError(
            f"le bot du siège agent n'a occupé qu'un seul siège "
            f"({total['seat1_episodes']} au siège 1, {total['seat2_episodes']} au siège 2) : "
            "le contrôle de chemin de décision est impossible, augmenter --episodes"
        )
    print(
        f"   contrôle chemin de décision : siège 1 "
        f"{total['seat1_wins']}/{total['seat1_episodes']} "
        f"({total['seat1_wins'] / total['seat1_episodes']:.3f}) · siège 2 "
        f"{total['seat2_wins']}/{total['seat2_episodes']} "
        f"({total['seat2_wins'] / total['seat2_episodes']:.3f})"
    )
    print(f"   troncatures : {total['truncated']}")

    print("\n📈 Par TOUR DE JOUEUR — moyennes par épisode")
    print("   (VP marqués pendant ce tour · valeur d'armée DÉTRUITE pendant ce tour)")
    print(f"   {'round':>5} {'joueur':>7} {'VP P1':>7} {'VP P2':>7} "
          f"{'détruit chez P1':>16} {'détruit chez P2':>16}")
    episodes = total["episodes"]
    cumulative = {"vp_gained_p1": 0.0, "vp_gained_p2": 0.0,
                  "value_lost_p1": 0.0, "value_lost_p2": 0.0}
    for key in sorted(segments_total):
        bucket = segments_total[key]
        if bucket["episodes"] > episodes:
            raise RuntimeError(
                f"segment {key} couvert par {bucket['episodes']} épisodes sur {episodes} : "
                "un tour de joueur ne peut pas être relevé deux fois dans la même partie"
            )
        if bucket["episodes"] < episodes:
            # Tour EFFONDRÉ dans un seul step moteur (cf. `_observe`) : rien à y attribuer. La
            # moyenne reste divisée par le nombre total d'épisodes, ce qui est la bonne lecture,
            # et la couverture est publiée pour que l'anomalie ne soit pas muette.
            print(f"   (couverture du segment {key} : {bucket['episodes']}/{episodes})")
        row = {field: bucket[field] / episodes for field in cumulative}
        for field in cumulative:
            cumulative[field] += row[field]
        print(
            f"   {key[0]:>5} {key[1]:>7} {row['vp_gained_p1']:>7.2f} {row['vp_gained_p2']:>7.2f} "
            f"{row['value_lost_p1']:>16.1f} {row['value_lost_p2']:>16.1f}"
        )
    print(
        f"   {'CUMUL':>13} {cumulative['vp_gained_p1']:>7.2f} "
        f"{cumulative['vp_gained_p2']:>7.2f} {cumulative['value_lost_p1']:>16.1f} "
        f"{cumulative['value_lost_p2']:>16.1f}"
    )

    if args.out:
        payload = {
            "meta": {
                "agent": args.agent,
                "training_config": args.training_config,
                "pool": args.scenario_pool,
                "episodes_per_task": args.episodes,
                "variant": args.variant,
                "terrain": args.terrain,
                "mission": args.mission,
                "seed": args.seed,
                "board_path": os.environ["W40K_BOARD_PATH"],
            },
            "total": dict(total),
            "p1_win_rate": p1_rate,
            "standard_error": stderr,
            "per_scenario": {k: dict(v) for k, v in per_scenario.items()},
            "segments": {
                f"{turn}:{player}": dict(bucket)
                for (turn, player), bucket in sorted(segments_total.items())
            },
            "per_task": results,
        }
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1)
        print(f"\n💾 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
