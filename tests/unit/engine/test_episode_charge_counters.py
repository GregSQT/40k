"""Tests — les quatre compteurs de CHARGE d'``episode_tactical_data``.

``charge_attempts`` / ``charge_successes`` et leurs jumeaux ``*_opponent`` remplacent
``combat/c_charge_successes``, qui ne comptait que les REUSSITES de l'agent, et les comptait
depuis les ``info`` d'un step gym cote callback. Deux defauts, un seul remplacant :

1. Sans le compte de TENTATIVES, un agent qui ne declare jamais de charge et un agent qui les
   declare toutes de trop loin produisent la MEME courbe basse. C'est exactement la question
   posee quand la melee d'un run ne progresse pas — et l'ancienne mesure ne pouvait pas y
   repondre.
2. Le chemin callback avait deja produit le defaut « charges du BOT comptees sous le drapeau
   de l'agent » (cf. tests/unit/ai/test_wrapper_agent_step_info.py). Le comptage vit desormais
   dans le moteur, sur ``action_logs``, la meme source que shoot_kills / melee_kills, ou le
   camp de chaque ligne est une donnee du journal et non une deduction sur l'ordre des steps.

CE FICHIER JOUE DE VRAIS EPISODES, sur le scenario melee de ``scripts/smoke_t5_bare`` — le
seul montage du depot ou une charge est reellement declarable (il place un Carnifex a portee
de charge, ce dont ``test_squad_charge_target_parity`` fait deja son critere). La ventilation
seat-aware, elle, se verrouille dans ``test_episode_combat_counters`` : son harnais en memoire
est le seul a pouvoir instancier les DEUX sieges.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from smoke_t5_bare import MELEE_SCENARIO  # noqa: E402

from ai.metrics_tracker import W40KMetricsTracker  # noqa: E402
from ai.unit_registry import UnitRegistry  # noqa: E402
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT  # noqa: E402
from engine.w40k_core import W40KEngine  # noqa: E402

#: Graines essayees pour obtenir la situation EXIGEE par chaque test. Borne stricte et message
#: d'echec explicite : si un correctif de regles fait qu'aucune ne produit plus de charge, le
#: test le dit au lieu de devenir silencieusement vacant (cf. l'entete de
#: test_episode_combat_counters sur les tests qui esperent leur situation au lieu de l'exiger).
_SEEDS = (1, 2, 3, 4, 5, 6, 7, 8)


@pytest.fixture(scope="module")
def melee_scenario_file():
    """Scenario ecrit UNE fois pour tout le module : son contenu (`MELEE_SCENARIO`) est constant.

    Portee module et pas fonction parce que `_cached_play` indexe ses episodes sur la seule
    graine : le chemin doit designer le meme scenario d'un test a l'autre.
    """
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "melee.json"
        path.write_text(json.dumps(MELEE_SCENARIO))
        yield str(path)


def _play(
    scenario_file: str, seed: int, inject: List[Dict[str, Any]] | None = None,
) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Joue un episode complet en actions legales tirees au sort ; rend (moteur, tactical_data).

    `inject` ajoute des lignes au journal juste apres le reset. ``action_logs`` n'est remis a
    zero QUE par ``reset()`` et n'est jamais purge en cours d'episode : ces lignes sont donc
    encore la quand le moteur fait sa passe de comptage a la terminaison.
    """
    engine = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", scenario_file=scenario_file,
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    engine.reset(seed=seed)
    if inject:
        engine.game_state["action_logs"].extend(inject)
    rng = np.random.default_rng(seed)
    info: Dict[str, Any] = {}
    for _ in range(4000):
        legal = np.flatnonzero(engine.get_action_mask())
        action = int(rng.choice(legal)) if legal.size else SQUAD_ACTION_WAIT
        _obs, _reward, terminated, truncated, info = engine.step(action)
        if terminated or truncated:
            break
    assert "tactical_data" in info, "l'episode ne s'est pas termine : pas de tactical_data"
    return engine, info["tactical_data"]


#: Episodes deja joues, indexes par (graine, variante). Un episode est STRICTEMENT deterministe
#: — config figee, `reset(seed=…)`, `default_rng(seed)` — donc le rejouer redonne le meme
#: resultat bit a bit : les six tests qui cherchent leur situation parmi les graines partagent
#: ici le meme travail au lieu de le refaire chacun (31 episodes joues -> 10).
#:
#: `variante` : les episodes joues sous un patch de regles (jet de charge impose) ne sont PAS les
#: memes que les episodes nus — ils ne doivent jamais se melanger dans ce cache. Chaque contexte
#: qui change le comportement du moteur porte donc sa propre etiquette.
#:
#: Sur du PARTAGE, donc en LECTURE SEULE : aucun test ne mute le moteur ni le `tactical_data`
#: rendus (ceux qui derivent des valeurs en font une copie, `{**tactical, …}`). Le chemin
#: `inject`, lui, ecrit dans `action_logs` : il n'est jamais mis en cache.
_EPISODES: Dict[Tuple[int, str], Tuple[W40KEngine, Dict[str, Any]]] = {}


def _cached_play(
    scenario_file: str, seed: int, variant: str = "",
) -> Tuple[W40KEngine, Dict[str, Any]]:
    """`_play` memoise sur (graine, variante). Voir `_EPISODES` pour le contrat de partage."""
    key = (seed, variant)
    if key not in _EPISODES:
        _EPISODES[key] = _play(scenario_file, seed)
    return _EPISODES[key]


def _charge_logs(
    engine: W40KEngine, player: int, types: Tuple[str, ...] = ("charge", "charge_fail"),
) -> List[Dict[str, Any]]:
    """Les tentatives de charge du camp `player` (`charge` = reussie, `charge_fail` = ratee)."""
    return [lg for lg in engine.game_state["action_logs"]
            if lg.get("type") in types and int(lg["player"]) == player]


def _seat(engine: W40KEngine) -> Tuple[int, int]:
    controlled = int(engine.config["controlled_player"])
    return controlled, (2 if controlled == 1 else 1)


def _assert_counters_match_journal(engine: W40KEngine, tactical: Dict[str, Any]) -> None:
    """Les quatre compteurs egalent le journal, camp par camp. Vrai meme a zero."""
    controlled, opponent = _seat(engine)
    assert tactical["charge_attempts"] == len(_charge_logs(engine, controlled))
    assert tactical["charge_successes"] == len(_charge_logs(engine, controlled, ("charge",)))
    assert tactical["charge_attempts_opponent"] == len(_charge_logs(engine, opponent))
    assert tactical["charge_successes_opponent"] == len(
        _charge_logs(engine, opponent, ("charge",))
    )


@pytest.mark.parametrize("seed", _SEEDS[:4])
def test_the_counters_match_the_journal(melee_scenario_file, seed) -> None:
    """Coherence croisee : compteurs = journal, sur des episodes dont on ne presuppose rien.

    Des EGALITES uniquement, donc vraies meme sur un episode sans la moindre charge — c'est ce
    qui permet de les faire tourner sur plusieurs graines sans parier sur leur contenu.
    """
    engine, tactical = _cached_play(melee_scenario_file, seed)
    _assert_counters_match_journal(engine, tactical)
    # Une reussite est une tentative, des deux cotes : le taux ne peut pas depasser 1.
    assert tactical["charge_successes"] <= tactical["charge_attempts"]
    assert tactical["charge_successes_opponent"] <= tactical["charge_attempts_opponent"]


def _episode_with(
    melee_scenario_file, require, what, variant: str = "",
) -> Tuple[W40KEngine, Dict[str, Any]]:
    tried: List[int] = []
    for seed in _SEEDS:
        engine, tactical = _cached_play(melee_scenario_file, seed, variant)
        if require(engine, tactical):
            return engine, tactical
        tried.append(seed)
    raise AssertionError(
        f"aucune graine {tried} n'a produit {what} : le montage ne cree plus la situation "
        f"qu'il pretend observer — a corriger, ce test ne doit pas verifier le vide"
    )


def test_a_failed_charge_counts_as_an_attempt_and_not_as_a_success(
    melee_scenario_file,
) -> None:
    """Une charge DECLAREE mais ratee incremente les tentatives, pas les reussites.

    C'est le verrou central : l'ancienne mesure rendait 0 dans cette situation, exactement
    comme pour un agent qui ne charge jamais. Il faut donc un episode ou le camp controle a
    rate au moins une charge — sinon les deux compteurs seraient egaux et le test ne
    distinguerait pas les deux implementations.

    Le JET est IMPOSE a 2, jamais espere d'une graine (meme doctrine que
    `test_units_charged_means_charge_move`) : « a result of 2 (a double 1) is never sufficient »
    (encart FAILED CHARGES du PDF 11), donc TOUTE charge declaree echoue sous ce patch. Depuis
    58c30dba (« la charge visait le contact du CENTRE ennemi, pas l'engagement range »), aucune
    graine de `_SEEDS` ne produisait plus d'echec naturel et le garde-fou anti-test-vacant de
    `_episode_with` se levait. Ce qui reste demande a la graine — qu'une charge soit DECLAREE —
    est justement ce que ce garde-fou exige encore.

    L'echec traverse la vraie branche moteur (`squad_charge`, « aucun plan valide pour ce jet ») :
    la ligne `charge_fail` que la passe de comptage lit est emise par le MOTEUR, pas fabriquee
    par le test.
    """
    with patch("engine.phase_handlers.shared_utils.roll_charge_distance", return_value=2):
        engine, tactical = _episode_with(
            melee_scenario_file,
            lambda _eng, td: td["charge_attempts"] > 0,
            "une charge declaree du camp controle (jet impose a 2, donc ratee)",
            # Etiquette de cache : ces episodes sont joues sous patch, ils ne valent pas les
            # episodes nus des autres tests et ne doivent jamais leur etre servis.
            variant="charge_roll_forced_to_2",
        )
    controlled, _opponent = _seat(engine)

    failed = len(_charge_logs(engine, controlled, ("charge_fail",)))
    assert failed > 0, "montage casse : aucune charge ratee"
    # Egalites camp par camp, les quatre compteurs contre le journal du moteur.
    _assert_counters_match_journal(engine, tactical)
    # Ce que l'ancienne mesure aurait rendu ici — strictement moins que les tentatives.
    assert tactical["charge_successes"] < tactical["charge_attempts"]


def test_both_camps_are_counted_separately(melee_scenario_file) -> None:
    """Les charges de l'adversaire vont dans les compteurs `_opponent`, jamais dans ceux de l'agent.

    Le montage exige des tentatives DES DEUX cotes : sans elles, l'egalite au journal tiendrait
    a zero d'un cote et ne dirait rien de la ventilation.
    """
    engine, tactical = _episode_with(
        melee_scenario_file,
        lambda _eng, td: td["charge_attempts"] > 0 and td["charge_attempts_opponent"] > 0,
        "des tentatives de charge des DEUX camps",
    )
    _assert_counters_match_journal(engine, tactical)

    controlled, opponent = _seat(engine)
    total = len(_charge_logs(engine, controlled)) + len(_charge_logs(engine, opponent))
    assert tactical["charge_attempts"] + tactical["charge_attempts_opponent"] == total
    # Aucun des deux camps n'a absorbe l'autre.
    assert tactical["charge_attempts"] > 0
    assert tactical["charge_attempts_opponent"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Emission des courbes
# ─────────────────────────────────────────────────────────────────────────────

class _RecordingWriter:
    """Writer de test : retient les scalaires au lieu de les ecrire sur disque."""

    def __init__(self) -> None:
        self.scalars: List[Tuple[str, float, int]] = []

    def add_scalar(self, tag: str, value: Any, step: int) -> None:
        self.scalars.append((tag, float(value), int(step)))

    def add_custom_scalars(self, layout: Dict[str, Any], /) -> None:
        pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def _recording_tracker(tmp_path: Any) -> Tuple[W40KMetricsTracker, _RecordingWriter]:
    """Vrai tracker, writer remplace, fenetres de lissage a 1.

    ``_emit_windowed`` n'emet qu'a fenetre PLEINE : aux fenetres de production (500/100) il
    faudrait rejouer des centaines d'episodes avant qu'un point sorte. Egales, elles
    suppriment aussi le doublon reactif ``_<fast>ep``, donc chaque tag n'apparait qu'une fois.
    """
    tracker = W40KMetricsTracker(
        "ArmageddonAgent", log_dir=str(tmp_path), show_banner=False,
        perf_window=1, perf_window_fast=1,
    )
    recording = _RecordingWriter()
    tracker.writer = recording
    tracker.episode_count = 1
    return tracker, recording


def test_the_four_charge_curves_are_emitted(melee_scenario_file, tmp_path) -> None:
    """Volumes bruts (m_, o_) et taux de reussite (n_, p_) sortent avec les valeurs de l'episode."""
    _engine, tactical = _episode_with(
        melee_scenario_file,
        lambda _eng, td: td["charge_attempts"] > 0 and td["charge_attempts_opponent"] > 0,
        "des tentatives de charge des DEUX camps",
    )

    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    by_key = {key: value for key, value, _step in recording.scalars}
    assert by_key["02_combat/m_charge_attempts"] == pytest.approx(tactical["charge_attempts"])
    assert by_key["02_combat/o_charge_attempts_bot"] == pytest.approx(
        tactical["charge_attempts_opponent"]
    )
    assert by_key["02_combat/n_charge_success_rate"] == pytest.approx(
        tactical["charge_successes"] / tactical["charge_attempts"]
    )
    assert by_key["02_combat/p_charge_success_rate_bot"] == pytest.approx(
        tactical["charge_successes_opponent"] / tactical["charge_attempts_opponent"]
    )


def test_the_success_rate_is_absent_when_nothing_was_attempted(
    melee_scenario_file, tmp_path
) -> None:
    """Aucune charge tentee : le taux n'est pas emis — et surtout pas emis a 0.

    Un 0.0 se lirait « l'agent a rate toutes ses charges » alors qu'il n'en a declare aucune.
    C'est la raison d'etre de ``_emit_ratio_of_means`` : ce ratio a pour denominateur un
    RESULTAT d'episode, il n'existe donc pas pour tout episode. Le VOLUME, lui, doit bien
    sortir a 0 — c'est justement lui qui dit que l'agent ne charge pas.
    """
    _engine, tactical = _episode_with(
        melee_scenario_file,
        lambda _eng, td: td["charge_attempts_opponent"] > 0,
        "des tentatives de charge du camp adverse",
    )
    tactical = {**tactical, "charge_attempts": 0, "charge_successes": 0}

    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    emitted = {key for key, _value, _step in recording.scalars}
    assert "02_combat/n_charge_success_rate" not in emitted
    assert "02_combat/m_charge_attempts" in emitted
    # Le camp d'en face a charge : SA courbe de taux sort. Sans cette assertion, l'absence
    # ci-dessus serait aussi bien celle d'un tag jamais ecrit.
    assert "02_combat/p_charge_success_rate_bot" in emitted


# ─────────────────────────────────────────────────────────────────────────────
# Participation par phase — les quatre courbes qui n'existaient dans aucun run
#
# `log_phase_performance` n'avait plus aucun appelant de production : les quatre taux
# n'apparaissaient dans AUCUN des 124 tags d'un run de 50 000 episodes. Ils sont recomptes
# cote moteur sur `action_logs`. Ces tests verifient les deux choses qui manquaient : que les
# compteurs correspondent au journal, et que les courbes SORTENT.
# ─────────────────────────────────────────────────────────────────────────────

def _logs(engine: W40KEngine, player: int, log_type: str, phase: str | None = None) -> int:
    return sum(1 for lg in engine.game_state["action_logs"]
               if lg.get("type") == log_type and int(lg["player"]) == player
               and (phase is None or lg.get("phase") == phase))


def test_the_phase_participation_counters_match_the_journal(melee_scenario_file) -> None:
    """Deplacements, fuites, attentes : compteurs = journal, pour le camp controle SEUL."""
    engine, tactical = _episode_with(
        melee_scenario_file,
        lambda _eng, td: td["move_actions"] > 0 and td["shoot_waits"] > 0,
        "un episode ou l'agent bouge et renonce a tirer au moins une fois",
    )
    controlled, opponent = _seat(engine)

    assert tactical["move_actions"] == _logs(engine, controlled, "move")
    assert tactical["move_waits"] == _logs(engine, controlled, "wait", "move")
    assert tactical["shoot_waits"] == _logs(engine, controlled, "wait", "shoot")
    assert tactical["move_flees"] == sum(
        1 for lg in engine.game_state["action_logs"]
        if lg.get("type") == "move" and int(lg["player"]) == controlled and lg["was_flee"]
    )
    # Rien du camp d'en face n'a fui vers les compteurs de l'agent.
    assert tactical["move_actions"] != _logs(engine, controlled, "move") + _logs(
        engine, opponent, "move"
    ) or _logs(engine, opponent, "move") == 0


def _shoot_line(turn: int, shooter: str, player: int) -> Dict[str, Any]:
    """Ligne de tir minimale : le contrat que la passe de comptage lit, et rien de plus.

    `damage` a 0 et `shootDetails` vide pour ne peser sur AUCUN autre compteur — ce test ne
    parle que du denombrement des activations.
    """
    return {"type": "shoot", "phase": "shoot", "player": player, "turn": turn,
            "shooterId": shooter, "damage": 0, "shootDetails": [],
            "message": "injected", "timestamp": "server_time"}


def test_shoot_activations_count_squads_not_journal_lines(melee_scenario_file) -> None:
    """Une escouade qui tire trois armes compte pour UNE participation, pas trois.

    Le journal emet une ligne par groupe (arme, cible) : compter les lignes gonflerait le
    numerateur de `shooting_participation` au-dela de son denominateur, qui compte des
    activations — un taux au-dessus de 1. Le scenario ne produit pas naturellement une
    escouade tirant plusieurs armes dans le meme tour (verifie sur les 8 graines), la
    situation est donc CONSTRUITE : trois lignes pour une meme (tour, escouade), plus une
    quatrieme a un autre tour, soit 4 lignes pour 2 activations.
    """
    injected = [_shoot_line(1, "injected-squad", 1) for _ in range(3)]
    injected.append(_shoot_line(2, "injected-squad", 1))
    engine, tactical = _play(melee_scenario_file, _SEEDS[0], inject=injected)
    controlled, _opponent = _seat(engine)
    assert controlled == 1, "les lignes injectees sont posees au nom du joueur 1"

    expected = {(int(lg["turn"]), str(lg["shooterId"]))
                for lg in engine.game_state["action_logs"]
                if lg.get("type") == "shoot" and int(lg["player"]) == controlled}
    assert tactical["shoot_activations"] == len(expected)
    # 4 lignes injectees pour 2 activations : les deux comptes DOIVENT differer, sinon le test
    # ne separe pas le denombrement par ligne du denombrement par activation.
    assert tactical["shoot_activations"] < _logs(engine, controlled, "shoot")
    assert _logs(engine, controlled, "shoot") - tactical["shoot_activations"] >= 2


def test_the_phase_participation_curves_are_emitted(
    melee_scenario_file, tmp_path
) -> None:
    """Les trois courbes mortes sortent de nouveau, avec les valeurs de l'episode.

    La charge n'en a PAS : son taux de participation compterait les fois ou le moteur a expose
    la phase, pas les occasions de charger. Le controle qu'elle ne sort pas est plus bas.
    """
    _engine, tactical = _episode_with(
        melee_scenario_file,
        lambda _eng, td: td["move_actions"] > 0 and td["shoot_activations"] > 0,
        "un episode ou l'agent bouge et tire",
    )

    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    by_key = {key: value for key, value, _step in recording.scalars}
    move_total = tactical["move_actions"] + tactical["move_waits"]
    assert by_key["game_tactical/movement_efficiency"] == pytest.approx(
        tactical["move_actions"] / move_total
    )
    assert by_key["game_detailed/flee_rate"] == pytest.approx(
        tactical["move_flees"] / move_total
    )
    assert by_key["game_tactical/shooting_participation"] == pytest.approx(
        tactical["shoot_activations"]
        / (tactical["shoot_activations"] + tactical["shoot_waits"])
    )


def test_a_phase_never_reached_emits_no_participation_rate(
    melee_scenario_file, tmp_path
) -> None:
    """Aucune occasion d'agir dans une phase : pas de taux, et surtout pas un 0.

    Un 0.0 se lirait « l'agent n'a jamais bouge alors qu'il le pouvait », alors qu'il n'a
    jamais eu la main. Meme raison que pour le taux de charge : le denominateur est un
    RESULTAT d'episode.
    """
    _engine, tactical = _episode_with(
        melee_scenario_file,
        lambda _eng, td: td["move_actions"] > 0,
        "un episode ou l'agent bouge",
    )
    tactical = {**tactical, "move_actions": 0, "move_waits": 0, "move_flees": 0}

    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    emitted = {key for key, _value, _step in recording.scalars}
    assert "game_tactical/movement_efficiency" not in emitted
    assert "game_detailed/flee_rate" not in emitted
    # Les autres phases, elles, ont bien eu lieu : leurs taux sortent. Sans ca, l'absence
    # ci-dessus serait celle d'un tag jamais ecrit.
    assert "game_tactical/shooting_participation" in emitted


def test_the_charge_has_no_participation_rate(melee_scenario_file, tmp_path) -> None:
    """`game_tactical/charge_rate` n'est PAS emis, meme sur un episode plein de charges.

    Le taux existait dans la premiere version de ces metriques. Son denominateur comptait les
    fois ou le moteur a EXPOSE la phase de charge, pas les occasions de charger : quand le pool
    est vide, aucun step n'est joue, donc aucun `wait` n'est journalise et le tour n'entre nulle
    part. Le volume `m_charge_attempts` et sa colonne adverse repondent sans cette ambiguite.
    Ce test empeche le taux de revenir par inadvertance.
    """
    _engine, tactical = _episode_with(
        melee_scenario_file,
        lambda _eng, td: td["charge_attempts"] > 0,
        "un episode ou l'agent declare au moins une charge",
    )

    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    emitted = {key for key, _value, _step in recording.scalars}
    assert "game_tactical/charge_rate" not in emitted
    # Le volume, lui, sort bien : l'absence ci-dessus n'est pas celle de toute mesure de charge.
    assert "02_combat/m_charge_attempts" in emitted
    assert "02_combat/o_charge_attempts_bot" in emitted
