"""Une cible qu'on ne peut pas blesser est ÉCARTÉE, jamais préférée.

Bug mesuré le 2026-08-11 sur `_score_contester` (doctrines Racer et Endgame) : le score d'une
cible valide vaut `-distance_objectif × 100 + dégâts`, donc **négatif** dès que la cible n'est pas
posée sur un objectif. Rendre `0.0` pour « aucune arme ne peut la blesser » en faisait alors le
**meilleur** score du lot — le bot visait en priorité les escouades contre lesquelles il ne pouvait
rien, et tirait dans le vide tant qu'il en restait une sur la table.

`_best_slot_action` écarte une cible dont le score est `None` ; c'est la seule réponse juste,
« inattaquable » n'étant pas une qualité de cible mais une absence de cible.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from ai.bot_doctrines import _score_contester


class _FakeMap:
    """Carte de distance à l'aire d'objectif : `map[col, row]` → distance."""

    def __init__(self, distances: Dict[tuple, int]) -> None:
        self._distances = distances

    def __getitem__(self, key) -> int:
        return self._distances[tuple(key)]


ATTACKER = {"id": "1", "player": 1}


def _state(damage_by_target: Dict[str, float]) -> Dict[str, Any]:
    """État minimal : deux cibles, l'une sur un objectif et blessable, l'autre invulnérable."""
    return {
        "objectives": [{"id": 1}],
        "_damage": damage_by_target,
        "units_cache": {
            "1": {"col": 0, "row": 0, "player": 1},
            # `hurtable` est LOIN de l'objectif (distance 3) → son score sera négatif.
            "hurtable": {"col": 5, "row": 5, "player": 2},
            # `immune` est sur l'objectif, mais rien ne peut l'entamer.
            "immune": {"col": 1, "row": 1, "player": 2},
        },
        "_maps": [_FakeMap({(5, 5): 3, (1, 1): 0})],
    }


@pytest.fixture(autouse=True)
def _stub_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Court-circuite les deux seules dépendances moteur des scores testés."""
    import ai.bot_doctrines as doctrines

    monkeypatch.setattr(
        doctrines, "_damage_on",
        lambda gs, att, tgt, ranged: float(gs["_damage"][str(tgt)]),
    )
    monkeypatch.setattr(
        doctrines, "require_unit_position",
        lambda sid, gs: (gs["units_cache"][str(sid)]["col"], gs["units_cache"][str(sid)]["row"]),
    )
    monkeypatch.setattr(doctrines, "objective_distance_maps", lambda gs: gs["_maps"])


def test_contester_discards_a_target_it_cannot_wound() -> None:
    """Le cœur du bug : `None` écarte, `0.0` aurait gagné le classement."""
    state = _state({"hurtable": 4.0, "immune": 0.0})

    assert _score_contester(ATTACKER, True)("immune", {}, state) is None


def test_contester_prefers_the_wounded_one_even_when_it_is_further_from_the_objective() -> None:
    """VERROU DU BUG : la cible blessable et LOIN (score négatif) doit l'emporter sur
    l'invulnérable posée SUR l'objectif. Avec `0.0` c'était l'inverse, et c'est ce qui faisait
    tirer les bots dans le vide."""
    state = _state({"hurtable": 4.0, "immune": 0.0})
    score = _score_contester(ATTACKER, True)

    hurtable = score("hurtable", {}, state)
    immune = score("immune", {}, state)

    assert hurtable is not None and hurtable < 0.0, "le score d'une cible éloignée EST négatif"
    assert immune is None, "sinon 0.0 > score négatif et l'invulnérable gagne"


def test_contester_still_ranks_reachable_targets_by_distance_to_the_objective() -> None:
    """La doctrine reste intacte : à dégâts comparables, le plus proche d'un objectif l'emporte."""
    state = _state({"hurtable": 4.0, "immune": 4.0})
    score = _score_contester(ATTACKER, True)

    immune = score("immune", {}, state)
    hurtable = score("hurtable", {}, state)

    assert immune is not None and hurtable is not None, "les deux cibles sont blessables ici"
    assert immune > hurtable

