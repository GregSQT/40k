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


def test_charge_slots_mirror_the_enemy_slot_mapping():
    """V11 §9 P3-2 : une action de charge = un slot ennemi, le MEME que le tir (invariant D1).

    Meme raison que pour la melee : desolidariser les comptes ferait pointer l'action de charge
    i et la ligne i du tenseur ennemi sur deux escouades differentes, sans que rien ne leve.
    """
    assert mi.CHARGE_SLOT_COUNT == mi.SHOOT_SLOT_COUNT
    assert su.SQUAD_ACTION_CHARGE_SLOT_COUNT == su.SQUAD_ACTION_SHOOT_SLOT_COUNT


def test_fight_slots_mirror_the_enemy_slot_mapping():
    """V11 §9 P3-1 : une action de combat = un slot ennemi, le MEME que le tir (invariant D1).

    Les desolidariser ferait pointer l'action de combat i et la ligne i du tenseur ennemi sur
    deux escouades differentes, sans que rien ne leve.
    """
    assert mi.FIGHT_SLOT_COUNT == mi.SHOOT_SLOT_COUNT
    assert su.SQUAD_ACTION_FIGHT_SLOT_COUNT == su.SQUAD_ACTION_SHOOT_SLOT_COUNT


def test_shoot_slot_count_covers_the_measured_worst_case():
    """§1.1 : 5 slots pour 6 escouades mesurees = une unite invisible ET intirable.

    Le nombre de slots doit rester au-dessus du pire cas des rosters reels. La tete pointeur
    rend un slot supplementaire gratuit en parametres — le rogner n'a plus aucune contrepartie.
    """
    assert mi.SHOOT_SLOT_COUNT >= 20


def test_named_actions_mirror():
    assert mi.ACTION_WAIT == su.SQUAD_ACTION_WAIT
    assert mi.SHOOT_SLOT_BASE == su.SQUAD_ACTION_SHOOT_SLOT_BASE
    assert mi.SHOOT_SLOT_COUNT == su.SQUAD_ACTION_SHOOT_SLOT_COUNT
    assert mi.CHARGE_SLOT_BASE == su.SQUAD_ACTION_CHARGE_SLOT_BASE
    assert mi.CHARGE_SLOT_COUNT == su.SQUAD_ACTION_CHARGE_SLOT_COUNT
    assert mi.FIGHT_SLOT_BASE == su.SQUAD_ACTION_FIGHT_SLOT_BASE
    assert mi.FIGHT_SLOT_COUNT == su.SQUAD_ACTION_FIGHT_SLOT_COUNT
    assert mi.ACTION_FIGHT_NO_TARGET == su.SQUAD_ACTION_FIGHT_NO_TARGET


def test_zone_intent_starts_right_after_the_micro_actions():
    """Aucun trou ni recouvrement entre micro (0..SIZE-1) et macro zone_intent."""
    assert mi.BASE_ZONE_INTENT == su.SQUAD_ACTION_SIZE


def test_total_action_size():
    """L'action space se termine par les CHOICE_i du mecanisme de decision (V11 §9.3 P2)."""
    assert mi.CHOICE_BASE == su.SQUAD_ACTION_SIZE + mi.MAX_OBJECTIVES * 3
    assert mi.TOTAL_ACTION_SIZE == mi.CHOICE_BASE + mi.CHOICE_COUNT
    assert mi.TOTAL_ACTION_SIZE == 1107


def test_choice_slots_close_the_action_space():
    """Les CHOICE ne recouvrent aucun zone intent et ferment l'espace, sans trou."""
    assert list(mi.CHOICE_SLOTS) == list(range(mi.CHOICE_BASE, mi.TOTAL_ACTION_SIZE))
    assert not mi.is_zone_intent_action(mi.CHOICE_BASE)
    assert mi.is_zone_intent_action(mi.CHOICE_BASE - 1)
    for offset in range(mi.CHOICE_COUNT):
        assert mi.is_agent_decision_action(mi.CHOICE_BASE + offset)
        assert mi.decode_agent_decision_action(mi.CHOICE_BASE + offset) == offset
    assert not mi.is_agent_decision_action(mi.CHOICE_BASE - 1)
    assert not mi.is_agent_decision_action(mi.TOTAL_ACTION_SIZE)


def test_micro_action_ids_are_contiguous_and_unique():
    """Chaque id micro est utilisé une fois et une seule : pas de collision d'action."""
    ids = (
        list(mi.MOVE_CELLS)
        + [mi.ACTION_WAIT]
        + list(mi.SHOOT_SLOTS)
        + list(mi.CHARGE_SLOTS)
        + list(mi.FIGHT_SLOTS)
        + [mi.ACTION_FIGHT_NO_TARGET]
    )
    assert len(ids) == len(set(ids)), "collision d'id d'action"
    assert sorted(ids) == list(range(su.SQUAD_ACTION_SIZE)), "les ids micro ne pavent pas [0, SIZE)"


def test_zone_intent_decoding_roundtrip():
    for zone_idx in range(mi.MAX_OBJECTIVES):
        for intent in range(3):
            action = mi.BASE_ZONE_INTENT + zone_idx * 3 + intent
            assert mi.is_zone_intent_action(action)
            assert mi.decode_zone_intent_action(action) == (zone_idx, intent)


def test_micro_actions_are_not_zone_intents():
    for action in (
        mi.MOVE_CELL_BASE,
        mi.ACTION_WAIT,
        mi.CHARGE_SLOT_BASE,
        mi.FIGHT_SLOT_BASE,
        mi.ACTION_FIGHT_NO_TARGET,
    ):
        assert not mi.is_zone_intent_action(action)
