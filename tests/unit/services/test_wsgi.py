"""Tests for services/wsgi.py helpers."""
import pytest


class TestResolveWaitressTrustedProxy:
    """_resolve_waitress_trusted_proxy reads W40K_TRUSTED_PROXIES for waitress."""

    def _call(self, monkeypatch, value):
        if value is None:
            monkeypatch.delenv("W40K_TRUSTED_PROXIES", raising=False)
        else:
            monkeypatch.setenv("W40K_TRUSTED_PROXIES", value)
        from importlib import import_module, reload
        import services.wsgi as wsgi_mod
        reload(wsgi_mod)
        return wsgi_mod._resolve_waitress_trusted_proxy()

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
