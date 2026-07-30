"""Tests — UN SEUL ecrivain par courbe, et pas de courbe muette en silence.

CE QUI A ETE MANQUE. Deux tags avaient deux ecrivains, et personne ne l'a vu pendant
50 000 episodes :

  * ``game_critical/invalid_action_rate`` : ecrit par log_tactical_metrics (vrai calcul) ET par
    log_critical_dashboard, qui lisait un ``self.episode_tactical_data`` du tracker jamais
    alimente — ``total_actions`` valant toujours 0, il ecrivait un 0.0 constant. 100 000 points
    pour 50 000 episodes, une courbe alternant valeur reelle et zero.
  * ``0_combat/h_melee_model_kills`` : ecrit par log_tactical_metrics ET par
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
    """``tactical_data`` complet d'un episode, tel que le moteur l'emet a la terminaison."""
    data: Dict[str, Any] = {
        "shots_fired": 10, "hits": 6,
        "damage_dealt": 12, "damage_received": 7,
        "units_lost": 2, "units_killed": 3, "total_enemies": 4, "total_ally_units": 5,
        "shoot_kills": 2, "melee_kills": 1,
        "shoot_value_killed": 200.0, "melee_value_killed": 100.0,
        "enemy_value_destroyed": 300.0, "ally_value_lost": 200.0,
        "total_ally_value": 1000.0, "total_enemy_value": 900.0,
        "initial_ally_models": 12, "initial_enemy_models": 15,
        "surviving_ally_models": 7, "surviving_enemy_models": 9,
        "valid_actions": 40, "invalid_actions": 5,
        "victory_points_diff_controlled_minus_opponent": 5.0,
        "victory_points_opponent_episode": 27.0,
        "controlled_objective_samples": [2.0, 1.0, 2.0, 2.0],
        "opponent_objective_samples": [1.0, 2.0, 1.0, 1.0],
        "forced_unit_episode_has_controlled": 0,
        "forced_unit_instances_controlled": 0,
        "forced_unit_counts_controlled": {},
    }
    data.update(overrides)
    return data


def _tracker(tmp_path: Any) -> Tuple[W40KMetricsTracker, _RecordingWriter]:
    """Vrai constructeur (pas ``__new__``) : un attribut retire du __init__ doit se voir ici."""
    tracker = W40KMetricsTracker("ArmageddonAgent", log_dir=str(tmp_path), show_banner=False)
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
    })
    tracker.log_tactical_metrics(tactical)


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
    assert counts["0_combat/h_melee_model_kills"] == 1


def test_melee_kills_carries_this_episode_value_not_the_previous_one(tmp_path: Any) -> None:
    """La valeur emise est celle de l'episode COURANT, pas la moyenne de l'episode d'avant.

    C'etait le second symptome du doublon : l'ecrivain supprime logguait avant l'append.
    Deux episodes de suite, avec des kills differents, pour que le decalage soit visible.
    """
    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical(melee_kills=0, shoot_kills=0))
    recording.scalars.clear()
    _episode(tracker, _tactical(melee_kills=4, shoot_kills=0))

    melee = [value for key, value, _step in recording.scalars if key == "0_combat/h_melee_model_kills"]
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
    assert by_key["0_VP/e_objectives_held"] == pytest.approx(1.5)
    assert by_key["0_VP/d_objectives_held_diff"] == pytest.approx(0.5)


def test_obj_rewards_equals_what_the_reward_calculator_actually_pays(tmp_path: Any) -> None:
    """0_VP/f_obj_rewards = le montant REELLEMENT verse par tour, terme d'avance inclus.

    La formule rejouee ici est celle de RewardCalculator._calculate_objective_reward_per_turn,
    sur les memes echantillons (pris au meme instant que le versement). Sans le terme d'avance,
    la courbe sous-estimerait le versement de moitie — c'est ce qu'elle faisait avant.
    """
    from config_loader import get_config_loader

    cfg = get_config_loader().load_agent_rewards_config("ArmageddonAgent")["ArmageddonAgent"]
    per_objective = float(cfg["objective_rewards"]["reward_per_objective"])
    lead_reward = float(cfg["objective_rewards"]["reward_for_objective_lead"])
    use_lead = bool(cfg["objective_rewards"]["use_objective_lead"])

    # Donnees CHOISIES pour discriminer forfait et proportionnel : 1 seul tour d'avance mais
    # +2 d'ecart cumule. Avec [2,3,1,2]/[2,1,2,1] les deux formules donnaient 20 par
    # coincidence, et le controle passait dans les deux cas.
    mine = [3.0, 1.0, 1.0, 1.0]
    theirs = [1.0, 1.0, 1.0, 1.0]
    expected = sum(per_objective * m for m in mine)
    if use_lead:
        turns_ahead = sum(1 for m, t in zip(mine, theirs) if m > t)
        assert turns_ahead == 1 and (sum(mine) - sum(theirs)) == 2.0
        expected += lead_reward * turns_ahead

    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical(
        controlled_objective_samples=mine, opponent_objective_samples=theirs,
    ))

    by_key = {key: value for key, value, _step in recording.scalars}
    assert by_key["0_VP/f_obj_rewards"] == pytest.approx(expected)


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


def test_an_empty_sample_list_stays_silent_without_raising(tmp_path: Any) -> None:
    """Liste VIDE = cas de jeu legitime (episode fini avant le premier tour marquant)."""
    tracker, recording = _tracker(tmp_path)
    _episode(tracker, _tactical(
        controlled_objective_samples=[], opponent_objective_samples=[],
    ))

    keys = {key for key, _value, _step in recording.scalars}
    assert "0_VP/e_objectives_held" not in keys
    assert "0_VP/d_objectives_held_diff" not in keys
