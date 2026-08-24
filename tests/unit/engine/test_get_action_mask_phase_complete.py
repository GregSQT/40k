"""Régression : get_action_mask ne doit pas boucler à l'infini quand fight_phase_end
retourne phase_complete=False (ex: pending_coherency_removal).

Scénario : fight phase, masque vide, fight_phase_end retourne toujours phase_complete=False.
Attendu : get_action_mask retourne sans boucler.
"""
from unittest.mock import MagicMock, patch

import numpy as np


def _make_engine_in_fight_phase(mask_value: bool = False):
    """Construit un moteur minimal en phase fight avec un masque donné."""
    eng = MagicMock()
    eng.game_state = {"phase": "fight", "game_over": False}

    mask = np.array([mask_value] * 10, dtype=bool)
    eng.action_decoder.get_squad_action_mask_and_eligible_units.return_value = (mask, [])
    eng._check_game_over.return_value = False

    # Importe la vraie méthode et la lie à notre mock
    from engine.w40k_core import W40KEngine
    eng.get_action_mask = lambda: W40KEngine.get_action_mask(eng)
    return eng


def test_get_action_mask_breaks_when_phase_not_complete():
    """fight_phase_end retourne phase_complete=False → la boucle doit s'arrêter, pas boucler."""
    eng = _make_engine_in_fight_phase(mask_value=False)

    call_count = 0

    def fake_fight_phase_end(gs):
        nonlocal call_count
        call_count += 1
        if call_count > 5:
            raise RuntimeError("get_action_mask boucle à l'infini sur phase_complete=False")
        return {"phase_complete": False, "awaiting_coherency_removal": True}

    with patch("engine.phase_handlers.fight_handlers.fight_phase_end", side_effect=fake_fight_phase_end):
        result = eng.get_action_mask()

    # fight_phase_end doit être appelé UNE SEULE fois puis la boucle break
    assert call_count == 1, f"fight_phase_end appelé {call_count} fois, attendu 1"
    assert not np.any(result), "le masque doit rester vide (aucune action fight disponible)"


def test_get_action_mask_continues_when_phase_complete():
    """fight_phase_end retourne phase_complete=True → get_action_mask écrit next_phase dans game_state["phase"]."""
    eng = _make_engine_in_fight_phase(mask_value=False)

    call_count = 0

    def fake_fight_phase_end(gs):
        nonlocal call_count
        call_count += 1
        # La vraie fonction ne touche PAS gs["phase"] — get_action_mask le fait via next_phase
        return {"phase_complete": True, "phase_transition": True, "next_phase": "command"}

    with patch("engine.phase_handlers.fight_handlers.fight_phase_end", side_effect=fake_fight_phase_end):
        result = eng.get_action_mask()

    # fight_phase_end appelé exactement une fois ; sans la mise à jour de phase dans get_action_mask
    # la boucle le rappellerait une seconde fois (double-incrément de tour).
    assert call_count == 1, f"fight_phase_end appelé {call_count} fois, attendu 1"
    assert eng.game_state["phase"] == "command", "get_action_mask doit écrire next_phase dans game_state"
