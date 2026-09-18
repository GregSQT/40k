"""Compteurs TensorBoard `06_fight/b_ c_ d_ e_` — du journal d'actions à la courbe (lot melee-100).

`W40KEngine._build_terminal_info` dérive les compteurs d'`action_logs` synthétiques :
  - `b_engaging_consolidations_{agent,opponent}` : consolidations `[ENGAGING]` par camp ;
  - `c_new_foes_subies` : New Foes gelés (`newFoesFrozen`) par les consos engaging de l'agent ;
  - `d_fights_multi_niveaux` : activations (tour, escouade) de l'agent où attaquant et cible ne
    sont pas au même étage (`attackerLevels` / `targetLevels` du log combat) ;
  - `e_engaged_idle_models` : figurines de l'agent engagées sans attaque (`fight_declaration`).
Puis `W40KMetricsTracker.log_tactical_metrics` les émet.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest


def _combat(turn: int, shooter: str, player: int, atk_levels: List[int], tgt_levels: List[int]) -> Dict[str, Any]:
    return {
        "type": "combat", "phase": "fight", "turn": turn, "shooterId": shooter, "player": player,
        "shootDetails": [], "attackerLevels": atk_levels, "targetLevels": tgt_levels,
    }


def _conso(player: int, mode: str, new_foes: int | None = None) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"type": "consolidation", "phase": "fight", "turn": 1, "unitId": "u", "player": player, "consolidationMode": mode}
    if new_foes is not None:
        entry["newFoesFrozen"] = new_foes
    return entry


def _decl(player: int, idle: int) -> Dict[str, Any]:
    return {
        "type": "fight_declaration", "phase": "fight", "turn": 1, "unitId": "u", "player": player,
        "engagedModels": idle + 2, "strikingModels": 2, "engagedIdleModels": idle,
    }


_LOGS: List[Dict[str, Any]] = [
    # Consolidations : 2 engaging agent (3 + 0 New Foes), 1 engaging adversaire, 1 ongoing agent.
    _conso(1, "engaging", 3), _conso(1, "engaging", 0), _conso(2, "engaging", 5), _conso(1, "ongoing"),
    # Combats : deux lignes de la MÊME activation (T1, escouade 1) à étages différents → 1 ;
    # une activation au même étage → 0 ; cible détruite (liste vide) → non jugée ; adversaire ignoré.
    _combat(1, "1", 1, [0], [1]), _combat(1, "1", 1, [0], [1]), _combat(2, "1", 1, [0], [0]),
    _combat(2, "3", 1, [0], []), _combat(1, "101", 2, [0], [1]),
    # Figurines engagées sans attaque : agent 1 + 2, adversaire 4 (ignoré).
    _decl(1, 1), _decl(1, 2), _decl(2, 4),
]


def test_terminal_counters_are_derived_from_action_logs():
    """La passe de `_build_terminal_info` (extraite en `_fight_counters_from_action_logs`) compte
    ce que le journal porte, camp de l'agent seulement."""
    from engine import w40k_core

    counters = w40k_core.W40KEngine._fight_counters_from_action_logs(_LOGS, controlled_player=1)

    assert counters == {
        "engaging_consolidations_agent": 2,
        "engaging_consolidations_opponent": 1,
        "new_foes_suffered": 3,
        "multi_level_fight_activations": 1,
        "engaged_idle_models": 3,
    }
    # Symétrie : vu de P2, les rôles s'inversent.
    counters_p2 = w40k_core.W40KEngine._fight_counters_from_action_logs(_LOGS, controlled_player=2)
    assert counters_p2["engaging_consolidations_agent"] == 1
    assert counters_p2["new_foes_suffered"] == 5
    assert counters_p2["engaged_idle_models"] == 4
    assert counters_p2["multi_level_fight_activations"] == 1


def test_missing_levels_in_a_combat_log_raise():
    """Un log combat sans `attackerLevels` est un émetteur oublié, pas un 0 silencieux."""
    from engine import w40k_core
    from shared.data_validation import ConfigurationError

    bad = {"type": "combat", "phase": "fight", "turn": 1, "shooterId": "1", "player": 1, "shootDetails": []}
    with pytest.raises(ConfigurationError, match="attackerLevels"):
        w40k_core.W40KEngine._fight_counters_from_action_logs([bad], controlled_player=1)


def test_tracker_emits_the_four_curves(tmp_path):
    """Les cinq tags `06_fight/b_…e_` sont écrits par `log_tactical_metrics` depuis un
    `tactical_data` RÉEL (partie jouée, `test_reserves_metrics._cached_play`) : la clé vient du
    moteur, la courbe du tracker — le contrat de bout en bout."""
    from tests.unit.engine.test_reserves_metrics import _REFERENCE_SEED, _cached_play, _recorded_scalars

    tactical = _cached_play(_REFERENCE_SEED)
    for key in (
        "engaging_consolidations_agent", "engaging_consolidations_opponent", "new_foes_suffered",
        "multi_level_fight_activations", "engaged_idle_models",
    ):
        assert key in tactical, key
    assert int(tactical["engaged_idle_models"]) == 0, "D+ : toute figurine engagée frappe"
    written = _recorded_scalars(tactical, tmp_path)
    for tag in (
        "06_fight/b_engaging_consolidations_agent", "06_fight/b_engaging_consolidations_opponent",
        "06_fight/c_new_foes_subies", "06_fight/d_fights_multi_niveaux",
        "06_fight/e_engaged_idle_models",
    ):
        assert any(t.startswith(tag) for t in written), (tag, sorted(t for t in written if t.startswith("06_fight")))
