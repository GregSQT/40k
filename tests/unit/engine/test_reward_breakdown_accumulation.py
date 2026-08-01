"""Tests — la ventilation de recompense est cumulee PAR LE MOTEUR sur tout l'episode.

CE QUI A ETE MANQUE. `RewardCalculator` pose la ventilation de CHAQUE step moteur dans
`game_state["last_reward_breakdown"]`, et le step suivant l'ecrase. Le moteur la recopiait dans
`info["reward_breakdown"]`, ou le callback d'entrainement etait cense l'accumuler. Mais le
callback ne voit qu'UN info par step GYM, et les wrappers d'adversaire (BotControlledEnv,
SelfPlayWrapper) rejouent l'adversaire APRES l'action de l'agent en remplacant `info` par celui
du dernier step moteur : la ventilation de l'action de l'agent etait jetee a chaque fois, et
rien du tout n'etait accumule quand l'adversaire ne jouait pas.

Cumulee cote moteur, elle voyage dans `episode_tactical_data` — donc dans `info["tactical_data"]`
du step terminal, que les wrappers preservent puisque c'est de lui qu'ils tirent deja `episode`
et `winner`.

POURQUOI AUCUN TEST NE L'A VU : aucun ne suivait la ventilation au-dela du step moteur.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from engine.reward_calculator import RewardCalculator
from engine.w40k_core import (
    DENSE_REWARD_BREAKDOWN_COMPONENTS,
    REWARD_BREAKDOWN_COMPONENTS,
    W40KEngine,
    empty_reward_breakdown_totals,
)
from tests.unit.engine.test_episode_combat_counters import (
    DEVASTATING,
    _build,
    _config,
    _run_to_end,
    _unit,
)


def _breakdown(**overrides: float) -> Dict[str, float]:
    data = {key: 0.0 for key in REWARD_BREAKDOWN_COMPONENTS}
    data.update(overrides)
    data['total'] = sum(data[key] for key in REWARD_BREAKDOWN_COMPONENTS)
    return data


def _episode_with_scripted_rewards(
    monkeypatch: pytest.MonkeyPatch, breakdowns: List[Dict[str, float]]
) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Joue un episode ou CHAQUE step moteur pose une ventilation connue, cyclee dans l'ordre.

    Scripter la recompense est le seul moyen d'asserter des totaux exacts : ce qui est teste ici
    est l'ACCUMULATION, pas le montant que le calculateur decide.
    """
    posted: List[int] = []

    def _fake_calculate_reward(self, success, result, game_state):
        _ = (success, result)
        breakdown = dict(breakdowns[len(posted) % len(breakdowns)])
        posted.append(1)
        game_state['last_reward_breakdown'] = breakdown
        return breakdown['total']

    monkeypatch.setattr(RewardCalculator, "calculate_reward", _fake_calculate_reward)

    units = [_unit(1, 1, 7, 6, DEVASTATING), _unit(3, 2, 8, 6, DEVASTATING)]
    engine = _build(_config(units, controlled_player=1))
    tactical = _run_to_end(engine, lambda legal: legal[0])
    assert posted, "aucun step moteur n'a pose de ventilation : le montage ne teste rien"
    return engine, tactical


def test_every_engine_step_is_summed_into_the_episode_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Les totaux valent la somme des ventilations posees, step par step.

    Aucune n'est perdue — c'etait le defaut : seule la derniere de chaque step gym survivait,
    et c'etait celle de l'adversaire.
    """
    per_step = _breakdown(base_actions=0.3, objective=2.0)
    _engine, tactical = _episode_with_scripted_rewards(monkeypatch, [per_step])

    totals = tactical['reward_breakdown']
    steps = round(totals['objective'] / 2.0)
    assert steps >= 2, "episode trop court pour distinguer une somme d'un dernier step"
    assert totals['base_actions'] == pytest.approx(0.3 * steps)
    assert totals['objective'] == pytest.approx(2.0 * steps)
    assert totals['penalties'] == pytest.approx(0.0)


def test_positive_flow_is_captured_step_by_step_not_from_the_net(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`*_positive` cumule les seules parts positives : le net ne les rend plus derivables.

    Montage : un step qui rapporte +0,3 (un tir), un step qui coute -0,1 (une attente). Le net
    de `base_actions` est donc a peine positif, mais le flux positif vaut 0,3 par tir — c'est
    lui, et lui seul, que la part d'objectif peut prendre au denominateur.
    """
    _engine, tactical = _episode_with_scripted_rewards(
        monkeypatch, [_breakdown(base_actions=0.3), _breakdown(base_actions=-0.1)]
    )

    totals = tactical['reward_breakdown']
    positive_steps = round(totals['base_actions_positive'] / 0.3)
    assert positive_steps >= 1
    negative_total = totals['base_actions'] - totals['base_actions_positive']
    assert negative_total < 0.0, "le montage doit produire des steps NEGATIFS, sinon il ne teste rien"
    assert totals['base_actions_positive'] > totals['base_actions']


def test_the_breakdown_travels_in_the_terminal_tactical_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Elle sort par `info["tactical_data"]`, la seule voie que les wrappers preservent.

    C'est ce qui la rend insensible au step moteur qui termine le step gym : `tactical_data`
    n'est pose qu'a la terminaison, et c'est de lui que les wrappers tirent deja `episode`.
    """
    _engine, tactical = _episode_with_scripted_rewards(
        monkeypatch, [_breakdown(result_bonuses=1.0)]
    )

    totals = tactical['reward_breakdown']
    assert set(totals) == set(empty_reward_breakdown_totals())
    assert totals['result_bonuses'] > 0.0
    for key in DENSE_REWARD_BREAKDOWN_COMPONENTS:
        assert f'{key}_positive' in totals
    assert 'situational_positive' not in totals, (
        "situational paie le RESULTAT, pas un comportement : il n'a pas de flux positif dense"
    )
