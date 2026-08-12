"""Tests — UN SEUL ecrivain par courbe, et pas de courbe muette en silence.

CE QUI A ETE MANQUE. Deux tags avaient deux ecrivains, et personne ne l'a vu pendant
50 000 episodes :

  * ``game_critical/invalid_action_rate`` : ecrit par log_tactical_metrics (vrai calcul) ET par
    log_critical_dashboard, qui lisait un ``self.episode_tactical_data`` du tracker jamais
    alimente — ``total_actions`` valant toujours 0, il ecrivait un 0.0 constant. 100 000 points
    pour 50 000 episodes, une courbe alternant valeur reelle et zero.
  * ``02_combat/h_melee_model_kills`` : ecrit par log_tactical_metrics ET par
    compute_and_log_phase_metrics, appele AVANT lui (depuis log_episode_end), donc avec la
    moyenne de l'episode PRECEDENT. 99 999 points, deux series entrelacees.

POURQUOI AUCUN TEST NE L'A VU. Les tests existants relisent le writer via
``{key: value for key, value, step in scalars}`` : un dict ecrase les doublons, donc la seconde
ecriture disparait de l'assertion. Ce fichier compte les OCCURRENCES, jamais les valeurs seules.
Le controle est generique : il porte sur TOUS les tags emis a la fin d'un episode, donc il
attrapera le prochain doublon, pas seulement ces deux-la.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Tuple

import pytest

from ai.metrics_tracker import W40KMetricsTracker
from engine.macro_intents import ACTION_FAMILIES
from tests.unit.ai._fabriques import tactical_data


class _RecordingWriter:
    """Doublure typee du writer TensorBoard : conserve TOUTES les ecritures, doublons inclus."""

    def __init__(self) -> None:
        self.scalars: List[Tuple[str, float, int]] = []

    def add_scalar(self, key: str, value: float, step: int, /) -> None:
        self.scalars.append((key, value, step))

    def add_custom_scalars(self, layout: Dict[str, Any], /) -> None:
        pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def _tactical(**overrides: Any) -> Dict[str, Any]:
    """`tactical_data` complet d'un episode — fabrique partagee, voir `_fabriques.tactical_data`."""
    return tactical_data(**overrides)


def _tracker(tmp_path: Any, window: int = 1) -> Tuple[W40KMetricsTracker, _RecordingWriter]:
    """Vrai constructeur (pas ``__new__``) : un attribut retire du __init__ doit se voir ici.

    Les deux fenetres de lissage sont ramenees a ``window`` : ces tests portent sur
    l'appariement tag <-> valeur, pas sur la taille des fenetres de production (500/100), qui
    obligerait chaque cas a rejouer des centaines d'episodes. Les fenetres egales suppriment
    le doublon ``_100ep``, donc les comptages d'occurrences restent lisibles. Le comportement
    des fenetres, lui, a ses propres tests (``test_no_point_is_emitted_before...``).
    """
    tracker = W40KMetricsTracker(
        "ArmageddonAgent", log_dir=str(tmp_path), show_banner=False,
        perf_window=window, perf_window_fast=window,
    )
    recording = _RecordingWriter()
    tracker.writer = recording
    tracker.episode_count = 1
    return tracker, recording


def _episode(tracker: W40KMetricsTracker, tactical: Dict[str, Any]) -> None:
    """Sequence REELLE de fin d'episode du callback : log_episode_end puis log_tactical_metrics.

    L'ordre importe : c'est log_episode_end qui appelle compute_and_log_phase_metrics et
    log_critical_dashboard, les deux sites qui portaient les ecritures en double.
    """
    tracker.log_episode_end({
        "total_reward": 42.0, "episode_length": 100, "winner": 1, "controlled_player": 1,
        "deployment_mode": None,
    })
    tracker.log_tactical_metrics(tactical)


def test_no_point_is_emitted_before_the_window_is_full(tmp_path: Any) -> None:
    """Une courbe de performance se tait tant que sa fenetre n'est pas pleine.

    CE QUI A ETE MANQUE. Sous la fenetre, le lissage retournait la moyenne de TOUT
    l'historique. Les 500 premiers points de chaque courbe etaient donc une moyenne
    cumulative, qui converge en DESCENDANT depuis son echantillon de depart bruite : sur un
    run de 1000 episodes, la moitie de la courbe etait une decroissance mecanique, lue comme
    une degradation de l'agent. Aucune donnee ne la contredisait, puisque toutes les courbes
    du dashboard portaient le meme artefact.

    Le montage discrimine les deux formules : rewards 0, 0, 0, 30, 30 avec une fenetre de 3.
      - moyenne de la fenetre (attendu)  : 10.0 puis 20.0 — et RIEN sur les deux premiers
      - moyenne cumulative (le defaut)   : 0.0, 0.0, 0.0, 7.5, 12.0 — cinq points, tous faux
    """
    tracker, recording = _tracker(tmp_path, window=3)
    for reward in (0.0, 0.0, 0.0, 30.0, 30.0):
        tracker.log_episode_end({
            "total_reward": reward, "episode_length": 100, "winner": 1, "controlled_player": 1,
            "deployment_mode": None,
        })

    emitted = [
        (value, step) for key, value, step in recording.scalars
        if key == "00_critical/e_episode_reward_smooth"
    ]
    # `_tracker` demarre a episode_count=1 et log_episode_end incremente AVANT d'ecrire :
    # les cinq episodes portent les steps 2 a 6, dont seuls les trois derniers sont emis.
    assert [step for _value, step in emitted] == [4, 5, 6], (
        "un point par episode a partir du troisieme, aucun avant"
    )
    assert [value for value, _step in emitted] == [
        pytest.approx(0.0), pytest.approx(10.0), pytest.approx(20.0)
    ]


def test_each_perf_curve_is_doubled_by_a_reactive_window(tmp_path: Any) -> None:
    """Chaque courbe de performance sort en DEUX exemplaires : fenetre de fond et `_Nep`.

    Sans ce test, ramener les deux fenetres a la meme valeur — ce que font les autres cas de
    ce fichier — supprimerait le doublon partout sans qu'une seule assertion ne bouge.
    """
    tracker, recording = _tracker(tmp_path, window=4)
    tracker.PERF_WINDOW_FAST = 2
    for _ in range(4):
        _episode(tracker, _tactical())

    keys = {key for key, _value, _step in recording.scalars}
    for tag in (
        "00_critical/e_episode_reward_smooth",   # historique complet
        "00_critical/d_win_rate",                # historique complet
        "01_VP/c_vp_bot",                        # _emit_game
        "02_combat/e_value_killed_ratio",        # _emit_ratio
        "02_combat/a_value_trade_ratio",         # rapport de deux moyennes
    ):
        assert tag in keys, f"{tag} manquant (fenetre de fond)"
        assert f"{tag}_2ep" in keys, f"{tag}_2ep manquant (fenetre reactive)"


def test_no_tag_is_written_twice_in_one_episode(tmp_path: Any) -> None:
    """Aucune courbe ne recoit deux points pour le meme episode."""
    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical())

    counts = Counter(key for key, _value, _step in recording.scalars)
    duplicates = {key: n for key, n in counts.items() if n > 1}
    assert duplicates == {}, f"tags ecrits plusieurs fois pour un seul episode : {duplicates}"


def test_the_two_historical_duplicates_are_emitted_exactly_once(tmp_path: Any) -> None:
    """Les deux tags du defaut sont bien EMIS — une fois chacun.

    Sans cette moitie, le controle precedent passerait aussi en supprimant les deux courbes.
    """
    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical())

    counts = Counter(key for key, _value, _step in recording.scalars)
    assert counts["game_critical/invalid_action_rate"] == 1
    assert counts["02_combat/h_melee_model_kills"] == 1


def test_melee_kills_carries_this_episode_value_not_the_previous_one(tmp_path: Any) -> None:
    """La valeur emise est celle de l'episode COURANT, pas la moyenne de l'episode d'avant.

    C'etait le second symptome du doublon : l'ecrivain supprime logguait avant l'append.
    Deux episodes de suite, avec des kills differents, pour que le decalage soit visible.
    """
    tracker, recording = _tracker(tmp_path, window=2)
    _episode(tracker, _tactical(melee_kills=0, shoot_kills=0))
    recording.scalars.clear()
    _episode(tracker, _tactical(melee_kills=4, shoot_kills=0))

    melee = [value for key, value, _step in recording.scalars if key == "02_combat/h_melee_model_kills"]
    assert melee == [pytest.approx(2.0)], (
        "la courbe doit valoir la moyenne des DEUX episodes (0 puis 4), pas 0.0"
    )


def test_invalid_action_rate_is_the_real_rate(tmp_path: Any) -> None:
    """La valeur emise est le vrai ratio, pas le 0.0 de l'ecrivain fantome."""
    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical(valid_actions=40, invalid_actions=10))

    rates = [
        value for key, value, _step in recording.scalars
        if key == "game_critical/invalid_action_rate"
    ]
    assert rates == [pytest.approx(0.2)]


def test_objective_curves_are_emitted_from_the_engine_samples(tmp_path: Any) -> None:
    """Les deux courbes d'objectifs tenus sortent, avec la moyenne des echantillons.

    Elles n'ont jamais recu un point en 50 000 episodes : c'est le controle qui l'interdit.
    """
    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical(
        controlled_objective_samples=[2.0, 2.0, 1.0, 1.0],
        opponent_objective_samples=[1.0, 1.0, 1.0, 1.0],
    ))

    by_key = {key: value for key, value, _step in recording.scalars}
    assert by_key["01_VP/e_objectives_held"] == pytest.approx(1.5)
    assert by_key["01_VP/d_objectives_held_diff"] == pytest.approx(0.5)


def test_obj_rewards_equals_what_the_reward_calculator_actually_pays(tmp_path: Any) -> None:
    """01_VP/f_obj_rewards = le montant REELLEMENT verse par tour.

    Le versement vaut `objective_reward_factor x VP marques` par construction
    (RewardCalculator._calculate_objective_reward_per_turn) : la courbe se LIT donc sur les VP
    de l'episode. Elle rejouait auparavant la formule du versement sur les echantillons — un
    miroir de la formule du moteur, qui est devenu faux des que celle-ci est passee du lineaire
    a l'escalier plafonne de la mission.

    CONTROLE DISCRIMINANT : les echantillons d'objectifs sont volontairement INCOHERENTS avec
    les VP fournis (4 tours a 1-3 objectifs ne peuvent pas produire 32 VP). Toute formule qui
    les relirait donnerait autre chose que 96 — seule la lecture des VP passe.
    """
    from config_loader import get_config_loader

    cfg = get_config_loader().load_agent_rewards_config("ArmageddonAgent")["ArmageddonAgent"]
    factor = float(cfg["objective_rewards"]["objective_reward_factor"])
    assert factor > 0.0, "facteur nul : le controle ne mesurerait rien"

    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical(
        victory_points_controlled_episode=32.0,
        controlled_objective_samples=[3.0, 1.0, 1.0, 1.0],
        opponent_objective_samples=[1.0, 1.0, 1.0, 1.0],
    ))

    by_key = {key: value for key, value, _step in recording.scalars}
    assert by_key["01_VP/f_obj_rewards"] == pytest.approx(factor * 32.0)


def test_a_missing_objective_samples_key_raises(tmp_path: Any) -> None:
    """Cle absente = etat corrompu, erreur explicite — jamais une courbe muette.

    C'est le garde `if isinstance(samples, list) and samples` qui a masque le defaut pendant
    50 000 episodes : il rendait indistinguables « personne ne remplit la liste » et « l'agent
    ne tient aucun objectif ».
    """
    tracker, _recording = _tracker(tmp_path)
    tactical = _tactical()
    del tactical["controlled_objective_samples"]

    with pytest.raises(Exception, match="controlled_objective_samples"):
        tracker.log_tactical_metrics(tactical)


def test_each_reserves_curve_carries_its_own_tactical_key(tmp_path: Any) -> None:
    """Les DIX courbes reserves/* sortent, chacune appariee a SA cle (20.01/20.04).

    Sans ce controle, les cles du fixture n'assertaient rien : remplacer les `add_scalar(
    'reserves/...')` par `pass` laissait ce fichier vert, et les courbes muettes. Ce controle
    porte sur l'appariement tag <-> cle cote tracker ; que le MOTEUR alimente bien ces
    compteurs est verifie a part (tests/unit/engine/test_reserves_metrics.py).

    Cinq mesures x DEUX CAMPS depuis le 2026-08-11. Les dix valeurs de la fixture sont
    distinctes deux a deux : c'est ce qui fait echouer un tag branche sur la cle voisine, et
    surtout un tag `_agent` alimente par la cle `_opponent` -- l'erreur exacte que la boucle
    d'emission peut introduire.
    """
    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical())

    by_key = {key: value for key, value, _step in recording.scalars}
    attendu = {
        "reserves/placed_agent": 5.0, "reserves/placed_opponent": 6.0,
        "reserves/deployed_agent": 3.0, "reserves/deployed_opponent": 4.0,
        "reserves/destroyed_turn3_agent": 1.0, "reserves/destroyed_turn3_opponent": 2.0,
        "reserves/ingress_offers_agent": 11.0, "reserves/ingress_offers_opponent": 12.0,
        "reserves/ingress_declined_agent": 7.0, "reserves/ingress_declined_opponent": 8.0,
        "reserves/ingress_no_destination_agent": 9.0,
        "reserves/ingress_no_destination_opponent": 10.0,
    }
    for tag, valeur in attendu.items():
        assert by_key[tag] == pytest.approx(valeur), tag


def test_the_bot_eval_cost_curves_carry_duration_and_throughput(tmp_path: Any) -> None:
    """Les deux courbes de cout d'evaluation sortent, appariees a leur grandeur.

    Ce que `bot_eval_freq` coute n'etait mesure NULLE PART : `eval_duration_seconds` n'etait
    imprimee que sur erreur ou sur timeout, donc jamais dans le cas nominal, et les notes de
    config s'appuyaient sur un chiffre herite jamais re-mesure.

    Les deux valeurs sont volontairement distinctes ici (600 episodes en 300 s = 2,0 ep/s) :
    a debit 1,0 les deux tags pourraient etre croises sans qu'aucune assertion n'en souffre.
    """
    tracker, recording = _tracker(tmp_path)
    tracker.log_bot_eval_cost(300.0, 600, step=10_000)

    by_key = {key: (value, step) for key, value, step in recording.scalars}
    assert by_key["perf/d_bot_eval_seconds"] == (pytest.approx(300.0), 10_000)
    assert by_key["perf/e_bot_eval_episodes_per_second"] == (pytest.approx(2.0), 10_000)

    # Un cout sans episode joue ou sans duree n'est pas « zero », c'est une donnee corrompue :
    # publier 0.0 se lirait « evaluation instantanee » et fausserait le reglage qu'elle sert.
    for episodes, duration in ((0, 300.0), (600, 0.0), (-1, 300.0)):
        with pytest.raises(ValueError):
            tracker.log_bot_eval_cost(duration, episodes, step=10_000)


def test_the_guarded_curves_are_on_the_open_side_of_their_guard(tmp_path: Any) -> None:
    """Les courbes gardees par un compteur non nul SORTENT sur la fixture partagee.

    `actions/share_*` est garde par `if family_total > 0`, et les deux `perf/*_rate` par un
    denominateur de consultations non nul. Tant que la fixture laissait ces compteurs a zero,
    les trois familles restaient du cote SILENCIEUX de leur garde : supprimer leurs
    `add_scalar` n'aurait fait rougir aucun test. Ce controle est ce qui rend les valeurs non
    nulles de `_fabriques.tactical_data` obligatoires — les remettre a zero le rend ROUGE.
    """
    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical())

    keys = {key for key, _value, _step in recording.scalars}
    for family in ACTION_FAMILIES:
        assert f"actions/share_{family}" in keys, f"actions/share_{family} muette"
    assert "perf/a_deploy_cache_full_build_rate" in keys
    assert "perf/b_deploy_cache_wasted_rate" in keys

    # Les parts d'action forment une distribution : elles somment a 1.
    shares = sum(
        value for key, value, _step in recording.scalars
        if key.startswith("actions/share_")
    )
    assert shares == pytest.approx(1.0)


def test_an_empty_sample_list_stays_silent_without_raising(tmp_path: Any) -> None:
    """Liste VIDE = cas de jeu legitime (episode fini avant le premier tour marquant)."""
    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical(
        controlled_objective_samples=[], opponent_objective_samples=[],
    ))

    keys = {key for key, _value, _step in recording.scalars}
    assert "01_VP/e_objectives_held" not in keys
    assert "01_VP/d_objectives_held_diff" not in keys


def test_value_trade_ratio_is_the_ratio_of_the_two_smoothed_totals(tmp_path: Any) -> None:
    """02_combat/a_value_trade_ratio = VALUE detruite cumulee / VALUE perdue cumulee.

    Le denominateur de cette courbe est un RESULTAT d'episode, pas une constante de scenario :
    lisser le rapport par episode obligerait a ecarter une population entiere — les episodes
    sans perte (les MEILLEURS) si on garde le rapport, les episodes sans destruction (les
    PIRES) si on y verse un 0.0. Les deux biaisent, en sens contraire.

    Le montage discrimine les trois formules : detruit 300/perdu 200 puis detruit 0/perdu 100.
      - rapport des sommes (attendu)     : 300 / 300 = 1.0
      - moyenne des rapports par episode : (1.5 + 0.0) / 2 = 0.75
      - ancienne garde (les deux > 0)    : 1.5 (le second episode n'existe pas)
    """
    tracker, recording = _tracker(tmp_path, window=2)
    _episode(tracker, _tactical(enemy_value_destroyed=300.0, ally_value_lost=200.0))
    recording.scalars.clear()
    _episode(tracker, _tactical(enemy_value_destroyed=0.0, ally_value_lost=100.0))

    ratios = [v for key, v, _step in recording.scalars if key == "02_combat/a_value_trade_ratio"]
    assert ratios == [pytest.approx(1.0)]


def test_value_trade_ratio_stays_silent_while_nothing_has_been_lost(tmp_path: Any) -> None:
    """Aucune perte sur toute la fenetre : il n'y a pas de rapport a afficher — surtout pas 0."""
    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical(enemy_value_destroyed=120.0, ally_value_lost=0.0))

    keys = {key for key, _value, _step in recording.scalars}
    assert "02_combat/a_value_trade_ratio" not in keys
