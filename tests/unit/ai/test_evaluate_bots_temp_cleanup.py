"""OSError lors de la suppression du snapshot temporaire doit remonter (T1).

Avant le fix, un `except OSError: pass` autour de `os.remove(_temp_model_path)`
avalait silencieusement les erreurs (NFS lock, problème de permission sur /tmp),
laissant des .zip orphelins s'accumuler sans trace.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


def _make_training_cfg() -> dict:
    return {
        "agent_seat_mode": "p1",
        "vec_normalize": {"enabled": False},
        "vec_normalize_eval": {
            "enabled": False,
            "training": False,
            "norm_reward": False,
        },
    }


def _make_global_cfg() -> dict:
    return {"progress_bar": {"bot_eval_width": 80}}


def test_evaluate_against_bots_temp_zip_oserror_propagates(tmp_path) -> None:
    """os.remove sur le zip temporaire doit lever OSError, pas l'avaler.

    Scénario : model_path=None → snapshot tempfile créé → _temp_model_path fixé →
    try bloc lève RuntimeError (via _load_bot_eval_params patché) → finally :
    os.remove soulève OSError → avec le fix, l'OSError remplace le RuntimeError
    et remonte chez l'appelant.
    """
    import pytest

    from ai.bot_evaluation import evaluate_against_bots

    temp_zip = str(tmp_path / "snap.zip")
    open(temp_zip, "w").close()

    fake_model = MagicMock()

    fake_config = MagicMock()
    fake_config.load_config.return_value = _make_global_cfg()
    fake_config.load_agent_training_config.return_value = _make_training_cfg()

    original_os_remove = os.remove

    def _patched_remove(path: str) -> None:
        if path == temp_zip:
            raise OSError("NFS lock simulé")
        original_os_remove(path)

    # get_vec_normalize_path renvoie un chemin .pkl qui n'existe pas → le branch
    # `if os.path.exists(_temp_vec_path):` reste False, seul os.remove(.zip) est exercé.
    with (
        patch("config_loader.get_config_loader", return_value=fake_config),
        patch("tempfile.mkstemp", return_value=(0, temp_zip)),
        patch("os.close"),
        patch("ai.bot_evaluation._load_bot_eval_params", side_effect=RuntimeError("inner-fail")),
        patch("os.remove", side_effect=_patched_remove),
        patch("os.path.exists", side_effect=lambda p: p == temp_zip),
    ):
        with pytest.raises(OSError, match="NFS lock simulé"):
            evaluate_against_bots(
                model=fake_model,
                training_config_name="x1",
                rewards_config_name="ArmageddonAgent",
                n_episodes=1,
                controlled_agent="ArmageddonAgent",
            )
