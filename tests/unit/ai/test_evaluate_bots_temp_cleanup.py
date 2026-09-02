"""OSError lors de la suppression du snapshot temporaire doit remonter (T1).

Avant le fix, un `except OSError: pass` autour de `os.remove(_temp_model_path)`
avalait silencieusement les erreurs (NFS lock, problème de permission sur /tmp),
laissant des .zip orphelins s'accumuler sans trace.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def test_evaluate_against_bots_temp_zip_oserror_propagates(tmp_path) -> None:
    """os.remove sur le zip temporaire doit lever OSError, pas l'avaler.

    Scénario : model_path=None → snapshot tempfile créé → _temp_model_path fixé →
    try bloc lève RuntimeError (via _load_bot_eval_params patché) → finally :
    os.remove soulève OSError → avec le fix, l'OSError remplace le RuntimeError
    et remonte chez l'appelant.
    """
    from ai.bot_evaluation import evaluate_against_bots

    temp_zip = str(tmp_path / "snap.zip")
    (tmp_path / "snap.zip").touch()

    fake_model = MagicMock()

    fake_config = MagicMock()
    fake_config.load_config.return_value = {"progress_bar": {"bot_eval_width": 80}}
    fake_config.load_agent_training_config.return_value = {
        "agent_seat_mode": "p1",
        "vec_normalize": {"enabled": False},
        "vec_normalize_eval": {"enabled": False, "training": False, "norm_reward": False},
    }

    # get_vec_normalize_path renvoie un chemin .pkl qui n'existe pas → le branch
    # `if os.path.exists(_temp_vec_path):` reste False, seul os.remove(.zip) est exercé.
    with (
        patch("config_loader.get_config_loader", return_value=fake_config),
        patch("tempfile.mkstemp", return_value=(0, temp_zip)),
        patch("os.close"),
        patch("ai.bot_evaluation._load_bot_eval_params", side_effect=RuntimeError("inner-fail")),
        patch("os.remove", side_effect=OSError("NFS lock simulé")),
        patch("os.path.exists", side_effect=lambda p: p == temp_zip),
    ):
        with pytest.raises(OSError, match="NFS lock simulé"):
            evaluate_against_bots(
                model=fake_model,
                training_config_name="x1",
                rewards_config_name="ArmageddonAgent_x1",
                n_episodes=1,
                controlled_agent="ArmageddonAgent_x1",
            )
