"""Tests for require_unit_by_id canonical function."""
import pytest
from shared.data_validation import ConfigurationError
from engine.game_utils import require_unit_by_id


def _make_gs(units: list) -> dict:
    """Build minimal game_state with unit_by_id index."""
    return {"unit_by_id": {u["id"]: u for u in units}}


def test_returns_unit_when_found():
    unit = {"id": "u1", "name": "Marine"}
    gs = _make_gs([unit])
    assert require_unit_by_id(gs, "u1") is unit


def test_raises_configuration_error_when_absent():
    gs = _make_gs([{"id": "u1", "name": "Marine"}])
    with pytest.raises(ConfigurationError, match="u999"):
        require_unit_by_id(gs, "u999")


def test_error_message_includes_unit_id():
    gs = _make_gs([])
    with pytest.raises(ConfigurationError) as exc:
        require_unit_by_id(gs, "bad-id")
    assert "bad-id" in str(exc.value)


def test_raises_configuration_error_when_unit_by_id_missing():
    with pytest.raises(ConfigurationError, match="unit_by_id"):
        require_unit_by_id({}, "u1")


def test_no_str_coercion_int_id_not_found():
    """Passing int instead of str is a caller bug; no silent coercion."""
    gs = _make_gs([{"id": "1", "name": "Marine"}])
    with pytest.raises(ConfigurationError):
        require_unit_by_id(gs, 1)  # type: ignore[arg-type]
