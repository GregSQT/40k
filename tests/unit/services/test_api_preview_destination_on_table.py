"""Garde des previews « depuis une position » : la sentinelle HORS TABLE doit être nommée.

Les previews `preview_shoot_from_position` / `preview_hidden_from_position` repositionnent
virtuellement l'unité en (destCol, destRow) avant de mesurer sa géométrie. À la sentinelle
`(-1,-1)` des réserves (20.01), la mesure levait tout au fond de `spatial_relations` sur une
entrée de `units_cache` — qui ne porte pas de clé `id` — donc sur un message `escouade '?'`
incapable de désigner l'unité ou l'appelant fautif. Ces tests verrouillent le garde qui lève
en amont, là où l'unité et la destination sont encore nommables.
"""

import pytest

from services.api_server import _require_preview_destination_on_table


class _EngineStub:
    """Minimum utilisé par le garde : l'état de partie et la résolution d'unité."""

    def __init__(self, unit):
        self.game_state = {"phase": "move", "current_player": 1}
        self._unit = unit

    def _get_unit_by_id(self, unit_id):
        return self._unit


def _unit_in_reserves():
    return {"deployed_on_turn": None, "in_strategic_reserves": True}


def test_destination_on_table_does_not_raise():
    engine = _EngineStub({"deployed_on_turn": 1, "in_strategic_reserves": False})
    _require_preview_destination_on_table(engine, "12", 10, 20, "preview_shoot_from_position")


def test_sentinel_destination_raises_and_names_unit_and_state():
    engine = _EngineStub(_unit_in_reserves())
    with pytest.raises(ValueError) as excinfo:
        _require_preview_destination_on_table(
            engine, "12", -1, -1, "preview_shoot_from_position"
        )
    message = str(excinfo.value)
    assert "preview_shoot_from_position" in message
    assert "'12'" in message
    assert "destCol=-1" in message
    assert "in_strategic_reserves=True" in message
    assert "phase=move" in message


@pytest.mark.parametrize(("dest_col", "dest_row"), [(-1, 5), (5, -1)])
def test_single_negative_coordinate_is_enough_to_raise(dest_col, dest_row):
    """Une seule coordonnée sentinelle suffit : `entry_is_on_battlefield` ne teste que `col`,
    donc un `row` négatif seul passait la garde du bas et mesurait une position impossible."""
    engine = _EngineStub(_unit_in_reserves())
    with pytest.raises(ValueError):
        _require_preview_destination_on_table(
            engine, "7", dest_col, dest_row, "preview_hidden_from_position"
        )


def test_absent_unit_still_produces_a_usable_message():
    engine = _EngineStub(None)
    with pytest.raises(ValueError) as excinfo:
        _require_preview_destination_on_table(
            engine, "99", -1, -1, "preview_hidden_from_position"
        )
    assert "unité absente" in str(excinfo.value)
