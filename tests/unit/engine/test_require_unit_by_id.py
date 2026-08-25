"""Tests for require_unit_by_id canonical function and its wrappers."""
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


# --- Verrous wrappers ---

def _make_gs_with_unit(extra_fields: dict | None = None) -> dict:
    unit: dict = {"id": "u1", "in_strategic_reserves": True}
    if extra_fields:
        unit.update(extra_fields)
    return {"unit_by_id": {"u1": unit}}


def test_unit_is_in_strategic_reserves_raises_on_unknown_id():
    """VERROU — id inconnu de unit_by_id = désynchronisation d'index, pas un cas métier."""
    from engine.phase_handlers.shared_utils import unit_is_in_strategic_reserves
    gs = _make_gs([{"id": "u1", "in_strategic_reserves": True}])
    with pytest.raises(ConfigurationError, match="u999"):
        unit_is_in_strategic_reserves(gs, "u999")


def test_unit_is_in_strategic_reserves_true_when_flag_set():
    from engine.phase_handlers.shared_utils import unit_is_in_strategic_reserves
    gs = _make_gs([{"id": "u1", "in_strategic_reserves": True}])
    assert unit_is_in_strategic_reserves(gs, "u1") is True


def test_unit_is_in_strategic_reserves_false_when_flag_absent():
    from engine.phase_handlers.shared_utils import unit_is_in_strategic_reserves
    gs = _make_gs([{"id": "u1"}])
    assert unit_is_in_strategic_reserves(gs, "u1") is False


def test_derive_squad_shooting_type_raises_on_unknown_id():
    """VERROU — désynchronisation détectée dès l'entrée de _derive_squad_shooting_type."""
    from engine.phase_handlers.shared_utils import _derive_squad_shooting_type  # type: ignore[attr-defined]
    gs = _make_gs([{"id": "u1"}])
    with pytest.raises(ConfigurationError, match="u999"):
        _derive_squad_shooting_type(gs, "u999")


def test_squad_model_shootable_weapon_indices_raises_on_unknown_id():
    """VERROU — désynchronisation détectée dès l'entrée de squad_model_shootable_weapon_indices."""
    from engine.phase_handlers.shared_utils import squad_model_shootable_weapon_indices
    gs = _make_gs([{"id": "u1"}])
    with pytest.raises(ConfigurationError, match="u999"):
        squad_model_shootable_weapon_indices(gs, "u999", {}, "normal")


def test_target_visible_to_a_friendly_unit_raises_on_unknown_target():
    """VERROU — target_sid inconnu de unit_by_id = désynchronisation."""
    from engine.phase_handlers.shared_utils import _target_visible_to_a_friendly_unit  # type: ignore[attr-defined]
    gs = _make_gs([{"id": "u1"}, {"id": "shooter1"}])
    with pytest.raises(ConfigurationError, match="u999"):
        _target_visible_to_a_friendly_unit(gs, "shooter1", "u999")


def test_shooting_unit_activation_start_raises_on_unknown_id():
    """VERROU — id inconnu de unit_by_id = désynchronisation d'index."""
    from engine.phase_handlers.shooting_handlers import shooting_unit_activation_start
    gs = {"unit_by_id": {"u1": {"id": "u1"}}}
    with pytest.raises(ConfigurationError, match="u999"):
        shooting_unit_activation_start(gs, "u999")


def test_build_alloc_groups_raises_on_unknown_target():
    """VERROU — target_sid inconnu de unit_by_id = désynchronisation d'index."""
    from engine.phase_handlers.shared_utils import _build_alloc_groups  # type: ignore[attr-defined]
    gs = {
        "unit_by_id": {"u1": {"id": "u1"}},
        "models_cache": {},
        "squad_models": {},
    }
    with pytest.raises(ConfigurationError, match="u999"):
        _build_alloc_groups(gs, "u999")
