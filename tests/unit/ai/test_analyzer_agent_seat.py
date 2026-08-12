"""Le siège de l'agent est LU dans le journal, plus jamais supposé être P1.

`controlled_player_mode` (ai/train.py) accepte `p1`, `p2` et `random`, et `game_state` place
l'agent au siège demandé (`agent_id_start = 1 if controlled_player == 1 else 101`).
`bot_evaluation` attribuait déjà juste, en comparant le vainqueur à `controlled_player` — donc
le gating aussi, qui lit `results["control"]`. Le seul consommateur qui n'avait pas la donnée
était `ai/analyzer.py`, qui écrivait « Agent (P1) » / « Bot (P2) » en dur.

Mesuré sur un run de 600 épisodes du 2026-08-08 : l'agent tenait le siège P2 dans 180 d'entre
eux, et l'analyzer y comptait ses victoires dans la colonne du bot — 33,3 % affichés pour
45,3 % réels, soit 12 points d'écart sur le chiffre lu à l'œil pour juger un modèle.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import ai.analyzer as an

from tests.unit.ai._fabriques import entete_step_log


def _episode_n(num: int, agent_seat: int | None, winner: int) -> str:
    rosters = (
        f"scale=500pts AGENT_PLAYER={agent_seat} AGENT=a (a.json) OPPONENT=o (o.json)"
        if agent_seat is not None else ""
    )
    return entete_step_log(
        f"[10:00:09] EPISODE END: Winner={winner}, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s\n",
        rosters=rosters,
        walls="none",
        ez_vertical_inches=None,
        objectives=None,
    )


def _run(tmp_path: Path, episodes: list) -> dict:
    path = tmp_path / "step.log"
    path.write_text("".join(episodes), encoding="utf-8")
    return an.parse_step_log(str(path))


def test_victoire_attribuee_au_siege_de_lagent_pas_a_p1(tmp_path: Path) -> None:
    """Deux épisodes gagnés par P1, mais l'agent n'occupe P1 que dans le premier.

    VERROU : c'est le scénario exact du run de 600 épisodes. L'ancien code comptait 2 victoires
    « Agent » ; le compte juste est 1 victoire agent et 1 victoire bot.
    """
    stats = _run(tmp_path, [
        _episode_n(1, agent_seat=1, winner=1),
        _episode_n(2, agent_seat=2, winner=1),
    ])

    by_seat = stats["win_methods_by_seat"]
    assert sum(by_seat["agent"].values()) == 1, by_seat
    assert sum(by_seat["bot"].values()) == 1, by_seat
    # Le compteur par SIÈGE reste renseigné : il sert aux sections d'erreurs, où le numéro de
    # joueur est la seule grandeur qui ait un sens.
    assert sum(stats["win_methods"][1].values()) == 2
    assert stats["agent_seat_counts"] == {1: 1, 2: 1}


def test_wins_by_scenario_suit_le_siege(tmp_path: Path) -> None:
    stats = _run(tmp_path, [
        _episode_n(1, agent_seat=2, winner=2),
        _episode_n(2, agent_seat=2, winner=1),
    ])
    wins = stats["wins_by_scenario"]["scenario_bot-01"]
    assert (wins["agent"], wins["bot"]) == (1, 1), wins
    # Les deux victoires sont réparties 1/1 entre les SIÈGES aussi, mais dans l'autre sens.
    assert (wins["p1"], wins["p2"]) == (1, 1), wins


def test_journal_sans_agent_player_est_refuse(tmp_path: Path) -> None:
    """VERROU ANTI-DÉFAUT : sans la donnée, on REFUSE d'analyser au lieu de supposer P1.

    Supposer est exactement ce qui a produit les 12 points d'écart. Un journal antérieur au
    format doit être régénéré, comme pour l'instantané `OBJECTIVE CONTROL`.
    """
    with pytest.raises(ValueError, match="AGENT_PLAYER"):
        _run(tmp_path, [_episode_n(1, agent_seat=None, winner=1)])


def test_le_siege_ne_fuit_pas_dun_episode_a_lautre(tmp_path: Path) -> None:
    """Le 2ᵉ épisode perd sa ligne `Rosters:` : il doit LEVER, pas hériter du siège du 1ᵉʳ."""
    with pytest.raises(ValueError, match="AGENT_PLAYER"):
        _run(tmp_path, [
            _episode_n(1, agent_seat=1, winner=1),
            _episode_n(2, agent_seat=None, winner=2),
        ])
