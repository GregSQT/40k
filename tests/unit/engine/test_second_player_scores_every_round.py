"""Le second joueur marque le primaire À LA FIN DE SON TOUR, à chaque battle round.

`test_objective_scoring.py` verrouille la DÉCISION (quelle phase attend quel siège). Ce fichier
verrouille le SITE D'APPEL : la phase de combat doit demander le versement à la fin du tour du
second joueur dans tous les rounds, et pas seulement quand la limite de rounds est atteinte.

Les deux moitiés sont nécessaires et aucune ne couvre l'autre. Avant le 2026-09-19, l'appel
`apply_primary_objective_scoring(game_state, "fight")` ne vivait QUE dans la branche de la limite
de rounds : même avec la bonne règle de siège, le second joueur n'aurait rien marqué aux rounds 2
à 4, personne ne le lui demandant.

Les deux progressions de fin de phase de combat sont exercées. La V11 est celle du gym ; la V10
reste atteignable, et n'en verrouiller qu'une ferait dépendre les points de victoire de la version
de phase active.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.fight_handlers import (
    _fight_end_progression_v10,
    _fight_v11_end_progression,
)

#: Rounds où le primaire se marque (`scoring.start_turn` vaut 2, la bataille dure 5 rounds).
SCORING_ROUNDS = (2, 3, 4)


@pytest.fixture(autouse=True)
def _pin_board(board_x5):
    """Les zones d'objectif de ces terrains n'ont de sens qu'hors x1."""


def _place_player_on_an_objective(engine, player: int) -> str:
    """Amène une escouade de `player` sur une zone d'objectif. Rend son id.

    Sans cette mise en scène, le versement rendrait zéro point et le test serait vert à vide :
    il passerait aussi bien avec un appel manquant qu'avec un appel présent.
    """
    from engine.game_state import objective_hex_zones
    from engine.phase_handlers.shared_utils import place_model_at_effective_level

    game_state = engine.game_state
    zones = list(objective_hex_zones(game_state))
    assert zones, "le scénario doit porter au moins une zone d'objectif"
    squad_id = next(
        sid for sid, entry in game_state["units_cache"].items()
        if int(entry["player"]) == player
    )
    for _obj_id, hex_set in zones:
        cells = sorted(hex_set)
        models = game_state["squad_models"][squad_id]
        if len(cells) < len(models):
            continue
        for model_id, (col, row) in zip(models, cells):
            place_model_at_effective_level(game_state, model_id, int(col), int(row), 0)
        return squad_id
    raise AssertionError("aucune zone d'objectif n'accueille l'escouade entière")


def _scored_by(game_state: Dict[str, Any], player: int) -> int:
    return int(game_state["victory_points"][player])


@pytest.mark.parametrize("battle_round", SCORING_ROUNDS)
@pytest.mark.parametrize(
    "progression", [_fight_v11_end_progression, _fight_end_progression_v10],
    ids=["v11", "v10"],
)
def test_la_fin_du_tour_du_second_joueur_verse_le_primaire(
    make_active_deployment_engine, battle_round, progression
):
    """Hors limite de rounds, la fin du tour du joueur 2 doit quand même verser."""
    engine = make_active_deployment_engine(seed=0)
    game_state = engine.game_state
    _place_player_on_an_objective(engine, 2)
    game_state["turn"] = battle_round
    game_state["current_player"] = 2
    game_state["units_fought"] = set()
    game_state["units_selected_to_fight"] = set()
    before = _scored_by(game_state, 2)

    progression(game_state)

    assert _scored_by(game_state, 2) > before, (
        f"round {battle_round} : le second joueur n'a rien marqué à la fin de son tour"
    )
    assert int(game_state["turn"]) == battle_round + 1, (
        "le round doit avancer : ce n'est pas la limite de rounds"
    )
    assert not game_state.get("game_over"), "la bataille ne s'achève qu'à la limite de rounds"


@pytest.mark.parametrize(
    "progression", [_fight_v11_end_progression, _fight_end_progression_v10],
    ids=["v11", "v10"],
)
def test_la_fin_du_tour_du_premier_joueur_ne_verse_rien(
    make_active_deployment_engine, progression
):
    """VERT VACANT écarté : le versement est bien conditionné au siège, pas posé partout.

    Le premier joueur marque à sa phase de commandement. Si la fin de tour versait pour les deux,
    il marquerait deux fois par round et le test précédent passerait quand même.
    """
    engine = make_active_deployment_engine(seed=0)
    game_state = engine.game_state
    _place_player_on_an_objective(engine, 1)
    game_state["turn"] = 3
    game_state["current_player"] = 1
    game_state["units_fought"] = set()
    game_state["units_selected_to_fight"] = set()
    before = _scored_by(game_state, 1)

    progression(game_state)

    assert _scored_by(game_state, 1) == before, (
        "le premier joueur ne marque pas à la fin de son tour"
    )
