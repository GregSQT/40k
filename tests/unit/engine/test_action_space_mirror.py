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


def test_charge_pair_slots_count():
    """V11 §9 P3 L9 : C(K_e, 2) paires de charge — encode/decode round-trip.

    CHARGE_PAIR_SLOT_COUNT = C(CHARGE_SLOT_COUNT, 2). L'index est continu et bijectif
    sur toutes les paires (i, j) avec i < j.
    """
    n = mi.CHARGE_SLOT_COUNT
    expected_pairs = n * (n - 1) // 2
    assert mi.CHARGE_PAIR_SLOT_COUNT == expected_pairs
    assert su.SQUAD_ACTION_CHARGE_PAIR_SLOT_COUNT == expected_pairs
    assert mi.CHARGE_PAIR_SLOT_BASE == mi.CHARGE_SLOT_BASE + mi.CHARGE_SLOT_COUNT
    assert su.SQUAD_ACTION_CHARGE_PAIR_SLOT_BASE == (
        su.SQUAD_ACTION_CHARGE_SLOT_BASE + su.SQUAD_ACTION_CHARGE_SLOT_COUNT
    )
    # Round-trip encode → decode sur toutes les paires.
    from engine.macro_intents import charge_pair_encode, charge_pair_decode
    seen = set()
    for i in range(n):
        for j in range(i + 1, n):
            idx = charge_pair_encode(i, j)
            assert 0 <= idx < expected_pairs, f"hors plage : ({i},{j}) → {idx}"
            assert (i, j) == charge_pair_decode(idx), f"round-trip échoue pour ({i},{j})"
            seen.add(idx)
    assert len(seen) == expected_pairs, "collision ou trou dans l'encodage"


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
    assert mi.CHARGE_PAIR_SLOT_BASE == su.SQUAD_ACTION_CHARGE_PAIR_SLOT_BASE
    assert mi.CHARGE_PAIR_SLOT_COUNT == su.SQUAD_ACTION_CHARGE_PAIR_SLOT_COUNT
    assert mi.FIGHT_SLOT_BASE == su.SQUAD_ACTION_FIGHT_SLOT_BASE
    assert mi.FIGHT_SLOT_COUNT == su.SQUAD_ACTION_FIGHT_SLOT_COUNT
    assert mi.ACTION_FIGHT_NO_TARGET == su.SQUAD_ACTION_FIGHT_NO_TARGET


def test_zone_intent_starts_right_after_the_micro_actions():
    """Aucun trou ni recouvrement entre micro (0..SIZE-1) et macro zone_intent."""
    assert mi.BASE_ZONE_INTENT == su.SQUAD_ACTION_SIZE


def test_oath_slots_mirror_the_enemy_slot_mapping():
    """Chantier 01 : une action d'Oath = un slot ennemi, le MEME que le tir (invariant D1).

    Oath of Moment designe « one unit from your opponent's army » : un candidat DEJA OBSERVE,
    donc une dimension d'action + pointeur, jamais un `CHOICE_k`. Desolidariser les comptes
    ferait pointer l'action d'Oath i et la ligne i du tenseur ennemi sur deux escouades
    differentes, sans que rien ne leve.
    """
    assert mi.OATH_SLOT_COUNT == mi.SHOOT_SLOT_COUNT
    assert su.SQUAD_ACTION_OATH_SLOT_COUNT == su.SQUAD_ACTION_SHOOT_SLOT_COUNT
    assert mi.OATH_SLOT_COUNT == su.SQUAD_ACTION_OATH_SLOT_COUNT


def test_activate_slots_mirror_the_ally_slot_mapping():
    """V11 §0.48 element L2 : une action d'activation = une ligne ALLIEE de l'observation.

    Meme raison que les slots d'Oath cote ennemi (invariant D1) : le slot `i` designe l'escouade
    decrite par `allies_*[i]`. Desolidariser les comptes ferait pointer l'action `ACTIVATE_SLOT_i`
    et la ligne `i` du tenseur allie sur deux escouades differentes, sans que rien ne leve —
    l'agent activerait B en croyant activer A.
    """
    from engine.observation_builder import ObservationBuilder
    from engine.observation_entities import K_ALLY_SLOTS

    assert mi.ACTIVATE_SLOT_COUNT == K_ALLY_SLOTS
    assert su.SQUAD_ACTION_ACTIVATE_SLOT_COUNT == K_ALLY_SLOTS
    assert mi.ACTIVATE_SLOT_COUNT == su.SQUAD_ACTION_ACTIVATE_SLOT_COUNT
    # La cardinalite REELLE du tenseur, pas seulement la constante : c'est elle que l'action indexe.
    assert ObservationBuilder.squad_obs_shapes()["allies_cont"][0] == mi.ACTIVATE_SLOT_COUNT


def test_total_action_size():
    """L'action space se termine par les slots d'ACTIVATION (V11 §0.48 element L2).

    ⚠️ `TOTAL_ACTION_SIZE` etait GELE a 1127 depuis le chantier 01 (les chantiers 02 a 06
    n'utilisent que des dimensions deja declarees). `L2` est le SEUL chantier du lot autorise a le
    bouger : il ajoute une famille d'actions entiere — choisir QUI activer — qui n'existait sous
    aucune forme. 1127 -> 1139.

    ⚠️ 1139 -> 1159 le 2026-08-16, pour la MEME raison et avec la meme autorisation explicite :
    le tir indirect 10.07 ajoute une famille d'actions entiere — choisir le TYPE DE TIR (10.02) —
    qui n'existait sous aucune forme, le type etant jusque-la DERIVE de l'etat. Le
    ré-entraînement qu'impose ce changement de dimension a ete acte par l'utilisateur avant
    l'ecriture (option A). Les 20 slots s'inserent dans le bloc MICRO, donc tout le macro se
    decale de 20 ; ce test est celui qui a pris la collision quand ils avaient d'abord ete poses
    apres `ACTION_FIGHT_NO_TARGET`, la ou commencaient les intentions de zone.
    """
    assert mi.CHOICE_BASE == su.SQUAD_ACTION_SIZE + mi.MAX_OBJECTIVES * 3
    assert mi.OATH_SLOT_BASE == mi.CHOICE_BASE + mi.CHOICE_COUNT
    assert mi.ACTIVATE_SLOT_BASE == mi.OATH_SLOT_BASE + mi.OATH_SLOT_COUNT
    assert mi.TOTAL_ACTION_SIZE == mi.ACTIVATE_SLOT_BASE + mi.ACTIVATE_SLOT_COUNT
    assert mi.TOTAL_ACTION_SIZE == 1349


def test_choice_then_oath_then_activate_slots_close_the_action_space():
    """CHOICE, Oath puis activation ferment l'espace, sans trou ni recouvrement."""
    assert list(mi.CHOICE_SLOTS) == list(range(mi.CHOICE_BASE, mi.OATH_SLOT_BASE))
    assert list(mi.OATH_SLOTS) == list(range(mi.OATH_SLOT_BASE, mi.ACTIVATE_SLOT_BASE))
    assert list(mi.ACTIVATE_SLOTS) == list(range(mi.ACTIVATE_SLOT_BASE, mi.TOTAL_ACTION_SIZE))
    assert not mi.is_zone_intent_action(mi.CHOICE_BASE)
    assert not mi.is_zone_intent_action(mi.OATH_SLOT_BASE)
    assert not mi.is_zone_intent_action(mi.ACTIVATE_SLOT_BASE)
    assert mi.is_zone_intent_action(mi.CHOICE_BASE - 1)
    for offset in range(mi.CHOICE_COUNT):
        assert mi.is_agent_decision_action(mi.CHOICE_BASE + offset)
        assert mi.decode_agent_decision_action(mi.CHOICE_BASE + offset) == offset
    assert not mi.is_agent_decision_action(mi.CHOICE_BASE - 1)
    # Ni un slot d'Oath ni un slot d'activation n'est un candidat de decision : ils ne doivent
    # pas etre decodes comme tels.
    assert not mi.is_agent_decision_action(mi.OATH_SLOT_BASE)
    assert not mi.is_agent_decision_action(mi.ACTIVATE_SLOT_BASE)
    assert not mi.is_agent_decision_action(mi.TOTAL_ACTION_SIZE)


def test_micro_action_ids_are_contiguous_and_unique():
    """Chaque id micro est utilisé une fois et une seule : pas de collision d'action."""
    ids = (
        list(mi.MOVE_CELLS)
        + [mi.ACTION_WAIT]
        + list(mi.SHOOT_SLOTS)
        + list(mi.CHARGE_SLOTS)
        # L9 (2026-08-20) : les paires de charge C(20,2) ont leurs propres slots, DANS le bloc micro,
        # entre les slots de charge unique et les slots de mêlée.
        + list(mi.CHARGE_PAIR_SLOTS)
        + list(mi.FIGHT_SLOTS)
        + [mi.ACTION_FIGHT_NO_TARGET]
        # 10.07 (2026-08-16) : le tir indirect a ses propres slots, DANS le bloc micro.
        + list(mi.SHOOT_INDIRECT_SLOTS)
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
