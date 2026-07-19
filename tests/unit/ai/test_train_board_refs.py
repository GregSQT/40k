"""T3 (V11_agent_rework.md) — chemins board + config training (R1, R2, 1bis/1ter).

Verrouille :
- R2 : _list_available_board_refs résout via config_loader.get_board_dir()
  (nom de dossier board != {cols}x{rows}), plus aucune reconstruction subhex.
- _expand_random_ref_weights : refs inconnues -> erreur explicite ; expansion valide.
- R1 : --training-config manquant -> erreur explicite listant les phases.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai.train as train


def _fake_loader_with_board_dir(board_dir: Path):
    """Loader minimal exposant get_board_dir() (et get_board_size volontairement piégé)."""
    def _get_board_size():
        raise AssertionError("get_board_size must NOT be used to resolve board refs (R2)")

    return SimpleNamespace(get_board_dir=lambda: board_dir, get_board_size=_get_board_size)


def test_list_available_board_refs_uses_board_dir(tmp_path, monkeypatch):
    # Nom de dossier board volontairement différent des dimensions subhex.
    board_dir = tmp_path / "44x60x5"
    walls_dir = board_dir / "walls"
    walls_dir.mkdir(parents=True)
    (walls_dir / "walls-33.json").write_text("{}", encoding="utf-8")
    (walls_dir / "walls-mc1.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(train, "get_config_loader", lambda: _fake_loader_with_board_dir(board_dir))

    refs = train._list_available_board_refs("walls")
    assert refs == ["walls-33.json", "walls-mc1.json"]


def test_list_available_board_refs_missing_dir_raises(tmp_path, monkeypatch):
    board_dir = tmp_path / "44x60x5"
    board_dir.mkdir(parents=True)  # pas de sous-dossier walls/
    monkeypatch.setattr(train, "get_config_loader", lambda: _fake_loader_with_board_dir(board_dir))

    with pytest.raises(FileNotFoundError, match="walls directory not found"):
        train._list_available_board_refs("walls")


def test_list_available_board_refs_bad_kind_raises():
    with pytest.raises(ValueError, match="Unsupported ref_kind"):
        train._list_available_board_refs("nope")


def test_expand_random_ref_weights_unknown_ref_raises(monkeypatch):
    monkeypatch.setattr(
        train, "_list_available_board_refs",
        lambda ref_kind: ["walls-33.json", "walls-mc1.json"],
    )
    with pytest.raises(ValueError, match="unknown refs for board walls"):
        train._expand_random_ref_weights(
            configured_weights={"walls-11.json": 0.5, "default": 0.5},
            ref_kind="walls",
            config_key_name="scenario_sampling.train_wall_ref_weights",
        )


def test_expand_random_ref_weights_valid_expansion(monkeypatch):
    monkeypatch.setattr(
        train, "_list_available_board_refs",
        lambda ref_kind: ["walls-33.json", "walls-mc1.json", "walls-none.json"],
    )
    expanded = train._expand_random_ref_weights(
        configured_weights={"default": 1.0},
        ref_kind="walls",
        config_key_name="scenario_sampling.train_wall_ref_weights",
    )
    names = [name for name, _ in expanded]
    assert names == ["walls-33.json", "walls-mc1.json", "walls-none.json"]
    assert sum(w for _, w in expanded) == pytest.approx(1.0)
    for _, w in expanded:
        assert w == pytest.approx(1.0 / 3.0)


def test_require_training_config_phase_missing_raises():
    class _Cfg:
        def load_agent_training_config(self, agent_key, phase):
            assert phase is None
            return {"x1": {}, "x1_debug": {}, "_comment": "ignore"}

    with pytest.raises(ValueError) as exc:
        train._require_training_config_phase(_Cfg(), "CoreAgent", None)
    msg = str(exc.value)
    assert "--training-config is required" in msg
    assert "x1" in msg and "x1_debug" in msg
    assert "_comment" not in msg  # clés underscore exclues


def test_require_training_config_phase_present_ok():
    class _Cfg:
        def load_agent_training_config(self, agent_key, phase):
            raise AssertionError("must not load config when phase provided")

    # Ne lève pas, ne charge pas la config.
    train._require_training_config_phase(_Cfg(), "CoreAgent", "x1_debug")


def test_require_training_config_phase_no_agent_ok():
    class _Cfg:
        def load_agent_training_config(self, agent_key, phase):
            raise AssertionError("must not load config without agent")

    train._require_training_config_phase(_Cfg(), None, None)
