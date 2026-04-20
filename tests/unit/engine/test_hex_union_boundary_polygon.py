from shared.data_validation import ConfigurationError

from engine.hex_union_boundary_polygon import compute_move_preview_mask_loops_world


def _gs_with_board(hex_radius: float = 10.0, margin: float = 5.0) -> dict:
    """Même forme que ``game_state`` W40K : uniquement ``config.board.default``."""
    return {
        "config": {
            "board": {
                "default": {
                    "hex_radius": hex_radius,
                    "margin": margin,
                }
            }
        }
    }


def test_compute_mask_loops_two_adjacent_hexes() -> None:
    gs = _gs_with_board()
    cells = {(0, 0), (1, 0)}
    loops = compute_move_preview_mask_loops_world(cells, gs)
    assert loops is not None
    assert len(loops) == 1
    assert len(loops[0]) == 10


def test_compute_mask_single_hex() -> None:
    loops = compute_move_preview_mask_loops_world({(0, 0)}, _gs_with_board())
    assert loops is not None
    assert len(loops) == 1
    assert len(loops[0]) == 6


def test_compute_mask_empty() -> None:
    assert compute_move_preview_mask_loops_world(set(), _gs_with_board()) is None


def test_requires_config_board_shape() -> None:
    """Pas de lecture à la racine : ``config`` / ``board`` obligatoires."""
    import pytest

    with pytest.raises(ConfigurationError):
        compute_move_preview_mask_loops_world(
            {(0, 0)},
            {"board": {"default": {"hex_radius": 1.0, "margin": 0.0}}},
        )
