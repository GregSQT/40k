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
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import numpy as np
import pytest

from smoke_t5_bare import MELEE_SCENARIO

from ai.metrics_tracker import W40KMetricsTracker  # noqa: E402
from ai.unit_registry import UnitRegistry  # noqa: E402
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT  # noqa: E402
from engine.w40k_core import W40KEngine  # noqa: E402
from tests._state_invariants import charge_log_line  # noqa: E402

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


def _pick_action(engine: W40KEngine, legal: Any, rng: np.random.Generator) -> int:
    """Charge : la premiere action legale autre que `wait`. Toute autre phase : tirage au sort."""
    if not legal.size:
        return SQUAD_ACTION_WAIT
    if engine.game_state["phase"] == "charge":
        declared = [int(a) for a in legal if int(a) != SQUAD_ACTION_WAIT]
        if declared:
            return declared[0]
    return int(rng.choice(legal))


def _play(
    scenario_file: str, seed: int, inject: List[Dict[str, Any]] | None = None,
) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Joue un episode complet en actions legales tirees au sort ; rend (moteur, tactical_data).

    UNE exception au tirage : en phase de CHARGE, l'action jouee est la premiere legale qui
    n'est pas `wait`, donc une declaration de charge. C'est le sujet meme du fichier : tirer au
    sort la seule action qu'il mesure revient a esperer d'une graine ce qu'il pretend observer.
    Le scenario decide de l'occasion, la politique decide seulement de la saisir — meme partage
    que `_play_until` dans test_episode_combat_counters. Toutes les autres phases restent tirees
    au sort : c'est d'elles que viennent les situations de deplacement et de tir exigees plus bas.

    MESURE sur les 8 graines de `_SEEDS`, apres que 17.01 (traversee MONSTER/VEHICLE) a change
    les trajectoires : en tirage integral, AUCUN episode n'a de charge des deux camps (les tests
    de ventilation etaient devenus vacants) ; sous cette politique, les graines 1 et 8 en ont,
    la premiere avec 2 tentatives de l'agent contre 4 de l'adversaire.

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
        action = _pick_action(engine, legal, rng)
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

    CE QUI A CHANGE LE 2026-08-11. Le pipeline gym a ete aligne sur 11.02 : le jet 2D6 a lieu a
    l'ACTIVATION, et le masque n'ouvre que les cibles que ce jet permet d'atteindre (11.04). Une
    charge DECLAREE en gym ne peut donc plus echouer, et un jet impose a 2 n'en fait plus
    declarer aucune — l'ancien montage ne produit plus la situation qu'il observait.

    La passe de comptage, elle, doit toujours savoir lire un `charge_fail` : le chemin PvP/PvE
    (roll-first) en emet encore, quand le jet de l'activation n'amene aucune cible a portee. La
    ligne est donc INJECTEE dans le journal, comme le fait deja le test des activations de tir
    plus bas — ce qui est verrouille ici est la passe de comptage de `w40k_core`, pas la branche
    moteur qui l'emet (celle-la est verrouillee par le test d'alignement de ce fichier).
    """
    turn = 2
    injected = [
        {**_charge_line(1, "charge_fail", roll=2), "turn": turn},
        {**_charge_line(1, "charge", roll=9), "turn": turn},
    ]
    engine, tactical = _play(melee_scenario_file, _SEEDS[0], inject=injected)
    controlled, _opponent = _seat(engine)
    assert controlled == 1, "les lignes injectees sont posees au nom du joueur 1"

    failed = len(_charge_logs(engine, controlled, ("charge_fail",)))
    assert failed > 0, "montage casse : aucune charge ratee dans le journal"
    # Egalites camp par camp, les quatre compteurs contre le journal du moteur.
    _assert_counters_match_journal(engine, tactical)
    # Ce que l'ancienne mesure aurait rendu ici — strictement moins que les tentatives.
    assert tactical["charge_successes"] < tactical["charge_attempts"]


def test_a_charge_with_a_chosen_target_never_fails_in_gym(melee_scenario_file) -> None:
    """ALIGNEMENT 11.02 : une fois la CIBLE choisie, une charge gym ne peut plus rater.

    Le jet a lieu a l'activation et le masque ne propose que les cibles que ce jet atteint
    (11.04 « within the maximum distance ») ; masque et commit interrogent le MEME oracle
    (`charge_target_is_reachable` -> `charge_build_valid_plan`). Aucun `charge_fail` ne peut donc
    porter le motif « no valid charge plan for roll ». Avant le 2026-08-11, le masque ouvrait tout
    ennemi a 12" et les des tranchaient ensuite : mesure sur 8 episodes en actions aleatoires,
    17 charges declarees pour 3 reussies (18 %) contre 4 pour 4 apres alignement.

    CE QUI A CHANGE LE 2026-08-12, et pourquoi ce test ne compare plus les deux compteurs : le
    second mode d'echec de 11.02 — declarer puis n'avoir AUCUNE cible a portee du jet — est
    desormais journalise (`roll_too_short`), alors qu'il sortait en `wait` invisible. Les
    tentatives peuvent donc legitimement depasser les reussites, et l'egalite d'avant mesurait
    l'absence d'un journal, pas une propriete du jeu. Mesure a l'appui, graine 1 : l'adversaire y
    rate 1 charge sur 1 tentative, que l'ancien montage comptait 0 sur 0.
    """
    for seed in _SEEDS[:4]:
        engine, tactical = _cached_play(melee_scenario_file, seed)
        controlled, opponent = _seat(engine)
        for player in (controlled, opponent):
            for log in _charge_logs(engine, player, ("charge_fail",)):
                assert log["charge_failed_reason"] == "roll_too_short", (
                    f"graine {seed}, joueur {player} : charge ratee APRES choix de cible "
                    f"({log['charge_failed_reason']}) — le masque a promis une cible que le "
                    "commit a refusee (rupture masque/execution)"
                )
        assert tactical["charge_successes"] <= tactical["charge_attempts"]
        assert tactical["charge_successes_opponent"] <= tactical["charge_attempts_opponent"]


def test_a_roll_that_reaches_nothing_is_a_failed_charge_and_not_a_wait(
    melee_scenario_file,
) -> None:
    """11.02 : declarer puis ne rien pouvoir viser est une charge RATEE, pas une attente.

    Jet IMPOSE a 2 — « a result of 2 (a double 1) is never sufficient » (encart FAILED CHARGES du
    PDF 11) : toute escouade activee en phase de charge se retrouve donc sans aucune cible a
    portee, et le masque ne lui laisse que WAIT. 11.02.3 tranche l'issue : « Otherwise, your unit
    does not make a charge move. In either case, the charge is then resolved » — la charge est
    resolue, donc ratee, et l'activation est consommee.

    CE QUE CE TEST VERROUILLE, et ce qu'il rendait AVANT le 2026-08-12 : l'evenement sortait en
    `wait`, `charge_attempts` ne le voyait pas, et `02_combat/n_charge_success_rate` valait 1.000
    — valeur UNIQUE sur les 49 502 points du run x1_long de 50 000 episodes, des deux cotes. Une
    courbe qui ne peut plus varier ne peut plus alerter. Ce test etait alors ecrit a l'envers : il
    exigeait `charge_attempts == 0` sous ce meme patch, c'est-a-dire l'absence de la mesure.

    La RECOMPENSE n'est pas le sujet ici et ne change pas : le masque n'ouvrant que WAIT, la regle
    d'attente forcee rend 0.0 (verrou dans test_forced_wait_not_penalised).
    """
    with patch("engine.phase_handlers.shared_utils.roll_charge_distance", return_value=2):
        seen_failures = 0
        for seed in _SEEDS[:2]:
            engine, tactical = _play(melee_scenario_file, seed)
            controlled, opponent = _seat(engine)
            assert tactical["charge_successes"] == 0, (
                f"graine {seed} : une charge a REUSSI avec un jet de 2, qui n'atteint jamais "
                "l'engagement (encart FAILED CHARGES, PDF 11)"
            )
            assert tactical["charge_successes_opponent"] == 0, f"graine {seed} : idem adversaire"
            _assert_counters_match_journal(engine, tactical)
            for player in (controlled, opponent):
                for log in _charge_logs(engine, player, ("charge_fail",)):
                    seen_failures += 1
                    assert log["charge_failed_reason"] == "roll_too_short", log
                    # Aucune cible a nommer : l'escouade a declare et n'a rien pu viser. C'est ce
                    # qui distingue cette ligne de celle du jet insuffisant POUR une cible.
                    assert "targetId" not in log, log
                    assert int(log["charge_roll"]) == 2, log
        assert seen_failures > 0, (
            "montage casse : aucune activation de charge sous un jet de 2, donc rien de mesure — "
            "ce test ne doit pas verifier le vide"
        )


def _charge_line(player: int, kind: str, roll: int = 9) -> Dict[str, Any]:
    """Ligne de journal de charge, du type et du camp voulus.

    CONSTRUIRE plutot qu'esperer d'une graine (T4). Depuis l'alignement 11.02, une charge
    declaree en gym reussit toujours et les deux camps chargent rarement dans le meme episode :
    les montages qui parcouraient les graines a la recherche de la situation ne la trouvaient
    plus. Ce que ces tests verrouillent est la passe de COMPTAGE de `w40k_core` (elle lit
    `action_logs`), pas la façon dont ces lignes naissent.

    Le CONTRAT de la ligne (les champs que la production lit sans repli) vient du socle partage
    `charge_log_line` : il vivait ici, et sa copie dans `test_episode_combat_counters` n'a pas
    suivi le chantier 11.04 — elle a rougi a la livraison suivante. Ne reste ici que ce qui est
    propre a ce fichier : le tour 2.
    """
    return charge_log_line(player, kind, roll=roll, turn=2)


#: Journal injecte : volumes DIFFERENTS d'un camp a l'autre (4 contre 6) et taux AUX EXTREMES
#: (4/4 contre 0/6). Les deux differences comptent — a volumes egaux, `m_`/`o_` pourraient etre
#: croises sans qu'aucune assertion n'en souffre ; a taux egaux, `n_`/`p_` le pourraient aussi.
#:
#: Les extremes, et pas seulement des taux distincts : l'episode joue AJOUTE ses propres charges
#: a ces lignes. Un premier jeu a 2/3 contre 3/5 s'est retrouve a 2/3 contre 4/6 — soit deux
#: taux egaux — des qu'une charge naturelle est tombee du bon cote. Ici, aucune charge
#: supplementaire ne peut rapprocher 1.0 de 0.0 au point de les confondre.
_CHARGES_DES_DEUX_CAMPS = (
    [_charge_line(1, "charge") for _ in range(4)]
    + [_charge_line(2, "charge_fail", roll=3) for _ in range(6)]
)


def test_both_camps_are_counted_separately(melee_scenario_file) -> None:
    """Les charges de l'adversaire vont dans les compteurs `_opponent`, jamais dans ceux de l'agent."""
    engine, tactical = _play(
        melee_scenario_file, _SEEDS[0], inject=list(_CHARGES_DES_DEUX_CAMPS)
    )
    controlled, opponent = _seat(engine)
    assert controlled == 1, "les lignes injectees sont posees au nom du joueur 1"
    _assert_counters_match_journal(engine, tactical)

    total = len(_charge_logs(engine, controlled)) + len(_charge_logs(engine, opponent))
    assert tactical["charge_attempts"] + tactical["charge_attempts_opponent"] == total
    # Aucun des deux camps n'a absorbe l'autre, et les VOLUMES different : un croisement des
    # deux compteurs se verrait.
    assert tactical["charge_attempts"] >= 4
    assert tactical["charge_attempts_opponent"] >= 6
    assert tactical["charge_attempts"] != tactical["charge_attempts_opponent"]


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
    # Volumes ET taux DIFFERENTS d'un camp a l'autre (3 charges a 2/3 contre 5 a 3/5), sinon
    # `m_`/`o_` d'un cote et `n_`/`p_` de l'autre pourraient etre croises sans que la moindre
    # assertion en souffre. Construits par le journal injecte : depuis l'alignement 11.02, aucune
    # graine ne produit plus naturellement des charges des deux camps en nombres differents.
    _engine, tactical = _play(
        melee_scenario_file, _SEEDS[0], inject=list(_CHARGES_DES_DEUX_CAMPS)
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

    # Les deux TAUX different deja par construction (2/3 contre 3/5), donc un croisement de
    # `n_` et `p_` se voit sur les egalites ci-dessus. La seconde emission sur des succes
    # fabriques n'a plus lieu d'etre : elle ne servait qu'a separer deux tags que l'episode
    # naturel confondait.
    assert tactical["charge_successes"] / tactical["charge_attempts"] != pytest.approx(
        tactical["charge_successes_opponent"] / tactical["charge_attempts_opponent"]
    ), "taux identiques : les deux tags de taux pourraient etre croises sans rien casser"


def test_the_success_rate_is_absent_when_nothing_was_attempted(
    melee_scenario_file, tmp_path
) -> None:
    """Aucune charge tentee : le taux n'est pas emis — et surtout pas emis a 0.

    Un 0.0 se lirait « l'agent a rate toutes ses charges » alors qu'il n'en a declare aucune.
    C'est la raison d'etre de ``_emit_ratio_of_means`` : ce ratio a pour denominateur un
    RESULTAT d'episode, il n'existe donc pas pour tout episode. Le VOLUME, lui, doit bien
    sortir a 0 — c'est justement lui qui dit que l'agent ne charge pas.
    """
    _engine, tactical = _play(
        melee_scenario_file, _SEEDS[0], inject=list(_CHARGES_DES_DEUX_CAMPS)
    )
    tactical = {**tactical, "charge_attempts": 0, "charge_successes": 0}
    assert tactical["charge_attempts_opponent"] > 0, "le camp d'en face doit avoir charge"

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


def test_move_advances_counts_advance_type_only(melee_scenario_file) -> None:
    """move_advances = deplacements de type 'advance' du camp controle, pas tous les moves.

    Un move normal ou une fuite ne doivent PAS y contribuer — seule la valeur 'advance'
    du champ move_type compte.
    """
    engine, tactical = _episode_with(
        melee_scenario_file,
        lambda _eng, td: td["move_actions"] > 0,
        "un episode ou l'agent bouge",
    )
    controlled, _ = _seat(engine)

    expected_advances = sum(
        1 for lg in engine.game_state["action_logs"]
        if lg.get("type") == "move"
        and int(lg["player"]) == controlled
        and lg.get("move_type") == "advance"
    )
    assert tactical["move_advances"] == expected_advances
    # Le verrou : si tout est normal (pas d'advance), le compteur doit etre 0, pas un fantasme.
    assert tactical["move_advances"] <= tactical["move_actions"]


def test_fight_activations_counts_unique_unit_turn_pairs(melee_scenario_file) -> None:
    """fight_activations = paires (tour, escouade) uniques sur les logs 'combat' du controleur.

    Une escouade qui attaque avec plusieurs armes produit plusieurs logs 'combat' dans le meme
    tour. Sans deduplication, le compteur gonflerait au-dela du nombre d'unites combattantes.
    """
    engine, tactical = _episode_with(
        melee_scenario_file,
        lambda _eng, td: td["melee_kills"] > 0,
        "un episode ou l'agent tue au moins une figurine en melee",
    )
    controlled, _ = _seat(engine)

    expected = {
        (int(lg["turn"]), str(lg["shooterId"]))
        for lg in engine.game_state["action_logs"]
        if lg.get("type") == "combat" and int(lg["player"]) == controlled
    }
    assert tactical["fight_activations"] == len(expected)


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
    assert by_key["03_move/a_participation"] == pytest.approx(
        tactical["move_actions"] / move_total
    )
    assert by_key["03_move/c_flee_rate"] == pytest.approx(
        tactical["move_flees"] / tactical["move_actions"]
    )
    assert by_key["04_shoot/a_participation"] == pytest.approx(
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
    tactical = {**tactical, "move_actions": 0, "move_waits": 0, "move_flees": 0, "move_advances": 0}

    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    emitted = {key for key, _value, _step in recording.scalars}
    assert "03_move/a_participation" not in emitted
    assert "03_move/b_advance_rate" not in emitted
    assert "03_move/c_flee_rate" not in emitted
    # Les autres phases, elles, ont bien eu lieu : leurs taux sortent. Sans ca, l'absence
    # ci-dessus serait celle d'un tag jamais ecrit.
    assert "04_shoot/a_participation" in emitted


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


def test_move_log_missing_move_type_raises(melee_scenario_file) -> None:
    """Une ligne move sans move_type leve ConfigurationError (T1 : pas de silences sur champ obligatoire).

    Avant le correctif, log.get("move_type") retournait None et le log etait silencieusement
    ignore au lieu de lever une erreur. Le verrou : injecter un log move valide (was_flee
    present) mais sans move_type doit faire echouer la terminaison de l'episode.
    """
    from shared.data_validation import ConfigurationError
    with pytest.raises(ConfigurationError, match="move_type"):
        _play(melee_scenario_file, seed=1, inject=[
            {"type": "move", "player": "1", "was_flee": False},
        ])


def test_fight_activations_per_turn_is_windowed_ratio(melee_scenario_file, tmp_path) -> None:
    """06_fight/a_activations_per_turn passe par _emit_ratio_of_means, pas add_scalar direct.

    Avant le correctif, la courbe etait emise brute (scalar par episode), inconsistante avec
    les metriques 03_move et 04_shoot. Le verrou : avec window=2, la courbe ne doit PAS sortir
    apres UN seul episode — _emit_ratio_of_means attend que la fenetre soit pleine, alors
    qu'un add_scalar direct emetterait des le premier episode. La valeur sur 2 episodes est
    aussi verifiee.
    """
    _engine, tactical = _episode_with(
        melee_scenario_file,
        lambda _eng, td: td["fight_activations"] > 0 and td["final_turn"] > 0,
        "un episode avec au moins une activation de combat",
    )

    tracker = W40KMetricsTracker(
        "ArmageddonAgent", log_dir=str(tmp_path), show_banner=False,
        perf_window=2, perf_window_fast=2,
    )
    recording = _RecordingWriter()
    tracker.writer = recording
    tracker.episode_count = 1

    # Premier episode : fenetre pas encore pleine, la courbe ne doit PAS sortir.
    tracker.log_tactical_metrics(tactical)
    emitted_after_1 = {key for key, _value, _step in recording.scalars}
    assert "06_fight/a_activations_per_turn" not in emitted_after_1, (
        "la courbe ne doit pas sortir avant que la fenetre de 2 soit pleine"
    )

    # Deuxieme episode (meme donnee) : fenetre pleine, la courbe doit sortir.
    tracker.episode_count = 2
    tracker.log_tactical_metrics(tactical)
    by_key = {key: value for key, value, _step in recording.scalars}
    assert "06_fight/a_activations_per_turn" in by_key, (
        "la courbe doit etre emise apres deux episodes (fenetre de 2 pleine)"
    )
    expected = tactical["fight_activations"] / tactical["final_turn"]
    assert by_key["06_fight/a_activations_per_turn"] == pytest.approx(expected)
