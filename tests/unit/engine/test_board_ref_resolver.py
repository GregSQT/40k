"""V11 T4 — Résolveur `board_ref` (game_state).

Vérifie la décision de design n°4 : les refs partagées (walls/terrain) se résolvent soit via un
scénario situé sous `config/board/<board>/scenario/` (voie PvP, inchangée), soit via une clé
`board_ref` explicite (banque par-agent). Absence des deux OU board_ref invalide/inexistant =
erreur explicite (aucun fallback).

Les deux branches sont testées : la branche `scenario/` fige le comportement d'avant-fix
(neutralité PvP), la branche `board_ref` fige le fix T4.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.game_state import GameStateManager

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BOARD = "44x60x5"
BOARD_DIR = PROJECT_ROOT / "config" / "board" / BOARD
# Scénario legacy PvP (parent == 'scenario/')
PVP_SCEN = str(BOARD_DIR / "scenario" / "scenario_pvp_test.json")
# Scénario banque par-agent (hors dossier 'scenario/')
BANK_SCEN = str(
    PROJECT_ROOT / "config" / "agents" / "CoreAgent" / "scenarios" / "training" / "scenario_training_bot-01.json"
)


@pytest.fixture
def gsm() -> GameStateManager:
    return GameStateManager(config={})


# ── _resolve_board_dir : la matrice (a)(b)(c)(d) ────────────────────────────────

def test_resolve_board_dir_scenario_parent_no_board_ref(gsm):
    """(a) parent 'scenario/' sans board_ref → dossier board parent (voie PvP inchangée)."""
    assert gsm._resolve_board_dir(PVP_SCEN, None, "walls") == BOARD_DIR


def test_resolve_board_dir_board_ref_outside_scenario(gsm):
    """(b) board_ref valide, scénario hors 'scenario/' → config/board/<board_ref>/."""
    assert gsm._resolve_board_dir(BANK_SCEN, BOARD, "terrain_ref") == BOARD_DIR


def test_resolve_board_dir_neither_is_explicit_error(gsm):
    """(c) ni parent 'scenario/' ni board_ref → ValueError explicite."""
    with pytest.raises(ValueError, match="board_ref"):
        gsm._resolve_board_dir(BANK_SCEN, None, "terrain_ref")


def test_resolve_board_dir_missing_board_ref_is_explicit_error(gsm):
    """(d) board_ref pointant un board inexistant → FileNotFoundError explicite."""
    with pytest.raises(FileNotFoundError, match="board directory not found"):
        gsm._resolve_board_dir(BANK_SCEN, "does_not_exist_44x60x5", "terrain_ref")


@pytest.mark.parametrize("bad", ["../44x60x5", "sub/dir", "/abs/board", ""])
def test_resolve_board_dir_unsafe_board_ref(gsm, bad):
    """board_ref doit être un NOM de board seul (pas de chemin) → erreur explicite."""
    with pytest.raises(ValueError):
        gsm._resolve_board_dir(BANK_SCEN, bad, "walls")


# ── Routage effectif via les consommateurs (terrain_ref / wall_ref random) ──────

def test_read_terrain_file_via_board_ref(gsm):
    """_read_terrain_file route vers config/board/<board_ref>/terrain/ quand board_ref est fourni."""
    data, path = gsm._read_terrain_file("terrain-train-01.json", BANK_SCEN, board_ref=BOARD)
    assert path == BOARD_DIR / "terrain" / "terrain-train-01.json"
    assert "deployment_zones" in data


def test_read_terrain_file_no_board_ref_outside_scenario_errors(gsm):
    """Sans board_ref et hors 'scenario/', terrain_ref est irrésolvable → erreur explicite."""
    with pytest.raises(ValueError, match="board_ref"):
        gsm._read_terrain_file("terrain-train-01.json", BANK_SCEN, board_ref=None)


def test_random_wall_ref_via_board_ref(gsm):
    """wall_ref 'random' pioche dans config/board/<board_ref>/walls/ via board_ref (T4)."""
    walls = gsm._load_shared_walls_from_ref("random", BANK_SCEN, board_ref=BOARD)
    assert isinstance(walls, list)


def test_pvp_terrain_ref_still_resolves_without_board_ref(gsm):
    """Neutralité PvP : un scénario sous 'scenario/' résout terrain_ref SANS board_ref."""
    data, path = gsm._read_terrain_file("terrain-mc1.json", PVP_SCEN, board_ref=None)
    assert path == BOARD_DIR / "terrain" / "terrain-mc1.json"
