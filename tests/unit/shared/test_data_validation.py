import pytest

from shared.data_validation import ConfigurationError, require_key, require_present


def test_require_key_raises_configuration_error_when_missing() -> None:
    with pytest.raises(ConfigurationError, match=r"Required key 'MOVE'"):
        require_key({}, "MOVE")


def test_require_present_raises_configuration_error_when_none() -> None:
    with pytest.raises(ConfigurationError, match=r"Required value 'weapon_profile'"):
        require_present(None, "weapon_profile")
