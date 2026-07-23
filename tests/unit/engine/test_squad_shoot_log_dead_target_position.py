"""Le log d'un groupe (arme, cible) doit porter la VRAIE position de la cible, même quand
celle-ci a été détruite pendant l'allocation.

Régression verrouillée (2026-07-23). `_emit_squad_shoot_log` est émis en FIN d'allocation
(`_finalize_manual_allocation`), donc APRÈS le retrait de l'escouade cible détruite du
`units_cache`. Il relisait `units_cache[target].get("col", 0)` → l'escouade absente donnait
un fallback anti-erreur `(0,0)` (ex. « Unit 4(0,0) FOUGHT ... » dans un step.log réel), ce qui
polluait ensuite la cohérence position/log de l'analyzer.

Correctif : la position de l'ancre cible est capturée à la CRÉATION du groupe d'arme (cible
alors vivante) dans `g["target_col"]/g["target_row"]`, et l'émission l'utilise sans relire le
cache — plus aucun fallback masquant.
"""
from __future__ import annotations

from typing import Any, Dict

from engine.phase_handlers.shared_utils import SHOOT_CTX, _emit_squad_shoot_log


TARGET_COL, TARGET_ROW = 5, 7


def _game_state_target_removed() -> Dict[str, Any]:
    """units_cache SANS la cible « 2 » (simule l'escouade détruite et retirée à l'allocation) ;
    l'attaquant « 1 » reste présent avec sa position."""
    return {
        "units": [
            {"id": 1, "unitType": "Intercessor"},
            {"id": 2, "unitType": "AssaultIntercessor"},
        ],
        "units_cache": {
            "1": {"col": 3, "row": 3, "player": 1},
            # "2" absente : c'est précisément l'état qui produisait (0,0).
        },
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
    }


def _weapon_group() -> Dict[str, Any]:
    """Groupe (arme, cible) tel que produit par la couche d'allocation, avec la position cible
    capturée AVANT destruction (le correctif)."""
    return {
        "attacker_squad_id": "1",
        "weapon_name": "Bolt Rifle",
        "weapon_names": ["Bolt Rifle"],
        "target_sid": "2",
        "target_col": TARGET_COL,
        "target_row": TARGET_ROW,
        "bs": 3,
        "display_wth": 4,
        "display_save_th": 5,
        "player": 1,
        "attacks": 2,
        "damage": 3,
        "kills": 1,
        "killed_model_ids": ["2#0"],
        "shooter_mids": ["1#0"],
        "shots": [{"targetCol": TARGET_COL, "targetRow": TARGET_ROW}],
    }


def test_log_uses_captured_target_position_not_zero_zero() -> None:
    gs = _game_state_target_removed()
    _emit_squad_shoot_log(gs, _weapon_group(), SHOOT_CTX)

    assert len(gs["action_logs"]) == 1
    msg = gs["action_logs"][0]["message"]
    # La position de la cible dans le message est celle capturée, jamais le fallback (0,0).
    assert f"({TARGET_COL},{TARGET_ROW})" in msg
    assert "(0,0)" not in msg
    # Le raw_log porte aussi les bonnes coordonnées (consommées par le StepLogger).
    assert gs["action_logs"][0]["targetCol"] == TARGET_COL
    assert gs["action_logs"][0]["targetRow"] == TARGET_ROW


def test_missing_captured_position_raises_instead_of_silent_zero() -> None:
    """Sans position capturée, on veut une erreur explicite (CLAUDE.md : aucun fallback
    masquant), pas un retour silencieux à (0,0)."""
    import pytest

    gs = _game_state_target_removed()
    g = _weapon_group()
    del g["target_col"]
    with pytest.raises(Exception):
        _emit_squad_shoot_log(gs, g, SHOOT_CTX)
