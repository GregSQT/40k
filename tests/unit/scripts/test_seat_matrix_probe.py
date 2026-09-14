"""Verrous de `scripts/seat_matrix_probe.py` (S27, plafonnement_p1.md §9.5) — lecture du résultat."""
from __future__ import annotations

import pytest

import json
import os

from scripts.seat_matrix_probe import apply_training_env, board_path_for_agent, summarize


def test_summarize_reprend_le_score_et_les_compteurs_de_l_archive() -> None:
    result = {"P0": 0.62, "P0_wins": 186, "P0_losses": 112, "P0_draws": 2, "P0_timeouts": 0}
    summary = summarize(result, "P0")
    assert summary == {"label": "P0", "win_rate": 0.62, "wins": 186, "losses": 112, "draws": 2}


def test_summarize_refuse_un_resultat_sans_le_label_demande() -> None:
    # Un dict d'`evaluate_against_checkpoints` sans le score de l'archive demandée n'est pas
    # un résultat : `filter_compatible_archives` a pu écarter l'archive en silence.
    with pytest.raises(KeyError, match="P0"):
        summarize({"P1": 0.5}, "P0")


def test_le_plateau_suit_le_suffixe_de_resolution_de_l_agent() -> None:
    # Sans cette déduction, `config/config.json` impose le plateau x5 et la grille d'observation
    # à taille fixe ne refuse rien : des modèles x1 joueraient à x5 en silence.
    assert board_path_for_agent("ArmageddonAgent_x1_expl") == "board/44x60x1"
    assert board_path_for_agent("ArmageddonAgent_x5") == "board/44x60x5"


@pytest.mark.parametrize("agent", ["ArmageddonAgent", "ArmageddonAgent_x7"])
def test_un_agent_sans_resolution_connue_est_refuse(agent: str) -> None:
    with pytest.raises(ValueError, match=agent):
        board_path_for_agent(agent)


def test_training_env_pose_les_limites_de_threads_sans_ecraser_l_appelant(tmp_path, monkeypatch) -> None:
    # Mesuré le 2026-09-14 : sans ce bloc, 12 workers × 38 threads sur 16 cœurs, 300 parties
    # jamais finies en 63 min. `setdefault` : une valeur déjà posée par l'appelant gagne.
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"training_env": {"OMP_NUM_THREADS": 1, "TORCH_LOGS": "-dynamo"}}))
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    monkeypatch.setenv("TORCH_LOGS", "deja-la")
    applied = apply_training_env(str(cfg))
    assert os.environ["OMP_NUM_THREADS"] == "1"
    assert os.environ["TORCH_LOGS"] == "deja-la"
    assert applied == {"OMP_NUM_THREADS": "1", "TORCH_LOGS": "deja-la"}


def test_training_env_absent_est_refuse(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"torch": {}}))
    with pytest.raises(KeyError):
        apply_training_env(str(cfg))
