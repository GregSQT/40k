import pytest

dlos = pytest.importorskip("ai.debug_los")


def test_debug_los_returns_false_when_intermediate_wall_blocks(monkeypatch, capsys) -> None:
    monkeypatch.setattr(dlos, "get_hex_line", lambda a, b, c, d: [(1, 1), (2, 1), (3, 1)])
    result = dlos.debug_los(1, 1, 3, 1, {(2, 1)})
    out = capsys.readouterr().out
    assert result is False
    assert "LoS BLOCKED" in out
    assert "(2, 1)" in out


def test_debug_los_returns_true_when_only_endpoints_are_walls(monkeypatch, capsys) -> None:
    monkeypatch.setattr(dlos, "get_hex_line", lambda a, b, c, d: [(1, 1), (2, 1), (3, 1)])
    # Start/end walls do not block per function contract.
    result = dlos.debug_los(1, 1, 3, 1, {(1, 1), (3, 1)})
    out = capsys.readouterr().out
    assert result is True
    assert "LoS CLEAR" in out
