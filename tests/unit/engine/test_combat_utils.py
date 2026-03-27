import pytest

from engine.combat_utils import get_unit_coordinates


def test_get_unit_coordinates_normalizes_numeric_strings() -> None:
    unit = {"col": "4.0", "row": "2"}
    assert get_unit_coordinates(unit) == (4, 2)


def test_get_unit_coordinates_raises_key_error_when_missing_row() -> None:
    unit = {"col": 4}
    with pytest.raises(KeyError):
        get_unit_coordinates(unit)
