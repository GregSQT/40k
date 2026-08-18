"""Tests for services/wsgi.py helpers."""
import pytest


class TestResolveWaitressTrustedProxy:
    """_resolve_waitress_trusted_proxy reads W40K_TRUSTED_PROXIES for waitress."""

    def _call(self, monkeypatch, value):
        if value is None:
            monkeypatch.delenv("W40K_TRUSTED_PROXIES", raising=False)
        else:
            monkeypatch.setenv("W40K_TRUSTED_PROXIES", value)
        from services.wsgi import _resolve_waitress_trusted_proxy
        return _resolve_waitress_trusted_proxy()

    def test_unset_returns_none(self, monkeypatch):
        result = self._call(monkeypatch, None)
        assert result is None

    def test_empty_string_returns_none(self, monkeypatch):
        result = self._call(monkeypatch, "")
        assert result is None

    def test_whitespace_only_returns_none(self, monkeypatch):
        result = self._call(monkeypatch, "   ")
        assert result is None

    def test_single_ip_returned_as_is(self, monkeypatch):
        result = self._call(monkeypatch, "172.28.0.10")
        assert result == "172.28.0.10"

    def test_single_ip_stripped(self, monkeypatch):
        result = self._call(monkeypatch, "  172.28.0.10  ")
        assert result == "172.28.0.10"

    def test_multiple_ips_returns_first(self, monkeypatch):
        result = self._call(monkeypatch, "172.28.0.10,10.0.0.1")
        assert result == "172.28.0.10"

    def test_multiple_ips_with_spaces_returns_first(self, monkeypatch):
        result = self._call(monkeypatch, "172.28.0.10 , 10.0.0.1")
        assert result == "172.28.0.10"

    def test_leading_comma_raises(self, monkeypatch):
        with pytest.raises(SystemExit):
            self._call(monkeypatch, ",10.0.0.1")


class TestResolvePositiveInt:
    """_resolve_positive_int reads an env variable as a positive integer."""

    def _call(self, monkeypatch, value):
        var = "W40K_PORT"
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, value)
        from services.wsgi import _resolve_positive_int
        return _resolve_positive_int(var, 42)

    def test_unset_returns_default(self, monkeypatch):
        result = self._call(monkeypatch, None)
        assert result == 42

    def test_valid_int_returned(self, monkeypatch):
        result = self._call(monkeypatch, "5001")
        assert result == 5001

    def test_non_integer_raises(self, monkeypatch):
        with pytest.raises(SystemExit):
            self._call(monkeypatch, "abc")

    def test_zero_raises(self, monkeypatch):
        with pytest.raises(SystemExit):
            self._call(monkeypatch, "0")

    def test_negative_raises(self, monkeypatch):
        with pytest.raises(SystemExit):
            self._call(monkeypatch, "-1")
