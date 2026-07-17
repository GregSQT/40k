"""§4.5 — `macro_intents.py` est le miroir EXACT de `shared_utils.py` (SQUAD_ACTION_*).

La spec impose que les deux restent synchronisés (`macro_intents` se déclare lui-même « miroir
exact »), mais RIEN ne le vérifiait : une désynchronisation ferait viser aux bots/`ai/` une action
différente de celle que le moteur masque. Ce test ferme le trou.
"""

from engine import macro_intents as mi
from engine.phase_handlers import shared_utils as su
from engine.spatial_grid import GRID_CELL_COUNT


def test_move_cells_mirror():
    assert mi.MOVE_CELL_BASE == su.SQUAD_ACTION_MOVE_CELL_BASE
    assert mi.MOVE_CELL_COUNT == su.SQUAD_ACTION_MOVE_CELL_COUNT


def test_move_cell_count_matches_the_grid():
    """L'action space de move EST la grille : toute cellule doit être adressable."""
    assert mi.MOVE_CELL_COUNT == GRID_CELL_COUNT
    assert su.SQUAD_ACTION_MOVE_CELL_COUNT == GRID_CELL_COUNT


def test_named_actions_mirror():
    assert mi.ACTION_WAIT == su.SQUAD_ACTION_WAIT
    assert mi.SHOOT_SLOT_BASE == su.SQUAD_ACTION_SHOOT_SLOT_BASE
    assert mi.SHOOT_SLOT_COUNT == su.SQUAD_ACTION_SHOOT_SLOT_COUNT
    assert mi.ACTION_CHARGE == su.SQUAD_ACTION_CHARGE
    assert mi.ACTION_FIGHT == su.SQUAD_ACTION_FIGHT


def test_zone_intent_starts_right_after_the_micro_actions():
    """Aucun trou ni recouvrement entre micro (0..SIZE-1) et macro zone_intent."""
    assert mi.BASE_ZONE_INTENT == su.SQUAD_ACTION_SIZE


def test_total_action_size():
    assert mi.TOTAL_ACTION_SIZE == su.SQUAD_ACTION_SIZE + mi.MAX_OBJECTIVES * 3
    assert mi.TOTAL_ACTION_SIZE == 1047


def test_micro_action_ids_are_contiguous_and_unique():
    """Chaque id micro est utilisé une fois et une seule : pas de collision d'action."""
    ids = list(mi.MOVE_CELLS) + [mi.ACTION_WAIT] + list(mi.SHOOT_SLOTS) + [mi.ACTION_CHARGE, mi.ACTION_FIGHT]
    assert len(ids) == len(set(ids)), "collision d'id d'action"
    assert sorted(ids) == list(range(su.SQUAD_ACTION_SIZE)), "les ids micro ne pavent pas [0, SIZE)"


def test_zone_intent_decoding_roundtrip():
    for zone_idx in range(mi.MAX_OBJECTIVES):
        for intent in range(3):
            action = mi.BASE_ZONE_INTENT + zone_idx * 3 + intent
            assert mi.is_zone_intent_action(action)
            assert mi.decode_zone_intent_action(action) == (zone_idx, intent)


def test_micro_actions_are_not_zone_intents():
    for action in (mi.MOVE_CELL_BASE, mi.ACTION_WAIT, mi.ACTION_CHARGE, mi.ACTION_FIGHT):
        assert not mi.is_zone_intent_action(action)
