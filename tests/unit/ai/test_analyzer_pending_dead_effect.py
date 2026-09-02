"""unit_effect_in_force ne doit pas voir les modèles tués via ALLOC_MODEL.

Avant le fix, un leader (Warboss, Bigboss, ChaplainJumpPack) tué par `ALLOC_MODEL`
restait dans `positions_by_model` jusqu'à ce qu'une AUTRE unité émette `[MODELS:]`.
`unit_effect_in_force` le trouvait vivant et retournait True pour ses règles — faux positif
systématique sur les lignes de tir/mêlée entre le moment de la mort et la ligne suivante
d'un autre acteur.

Fix : filtrer `pending_model_removals` avant d'itérer les socles.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Optional, Set, Tuple


def _make_state(
    unit_id: str,
    model_id: str,
    model_type: str,
    pending: bool,
) -> Any:
    """État minimal pour unit_effect_in_force : une escouade avec un seul modèle."""
    pos: Dict[str, Dict[str, Tuple[int, int]]] = {
        unit_id: {model_id: (10, 10)},
    }
    pending_removals: Dict[str, Set[str]] = {}
    if pending:
        pending_removals[unit_id] = {model_id}
    return SimpleNamespace(
        positions_by_model=pos,
        current_line_models={},
        model_types={model_id: model_type},
        pending_model_removals=pending_removals,
    )


def _make_config(model_type: str, effect_rule: str) -> Any:
    return SimpleNamespace(
        unit_rules_by_type={model_type: {effect_rule}},
    )


def test_effet_visible_quand_modele_vivant():
    """Le leader vivant rend True pour sa propre règle."""
    from ai.analyzer_perfig import unit_effect_in_force

    state = _make_state("1", "1#0", "Warboss", pending=False)
    config = _make_config("Warboss", "hit_roll_bonus_fight")
    result = unit_effect_in_force(state, config, "1", "hit_roll_bonus_fight")
    assert result is True


def test_effet_invisible_quand_modele_pending_dead():
    """Leader tué via ALLOC_MODEL (pending) → effet non en vigueur."""
    from ai.analyzer_perfig import unit_effect_in_force

    state = _make_state("1", "1#0", "Warboss", pending=True)
    config = _make_config("Warboss", "hit_roll_bonus_fight")
    result = unit_effect_in_force(state, config, "1", "hit_roll_bonus_fight")
    # Tous les modèles connus sont pending → indécidable (None), pas True
    assert result is None


def test_effet_faux_si_survivants_sans_la_regle():
    """Escouade avec un bodyguard vivant (Boyz) mais plus de Warboss : effet False."""
    from ai.analyzer_perfig import unit_effect_in_force

    unit_id = "1"
    state_obj = SimpleNamespace(
        positions_by_model={
            unit_id: {"1#0": (10, 10), "1#1": (11, 10)},  # 1#0 = Warboss, 1#1 = Boyz
        },
        current_line_models={},
        model_types={"1#0": "Warboss", "1#1": "Boyz"},
        pending_model_removals={unit_id: {"1#0"}},  # Warboss pending dead
    )
    config = SimpleNamespace(
        unit_rules_by_type={
            "Warboss": {"hit_roll_bonus_fight"},
            "Boyz": set(),
        },
    )
    result = unit_effect_in_force(state_obj, config, unit_id, "hit_roll_bonus_fight")
    # 1#0 est pending → ignoré ; 1#1 (Boyz) ne porte pas la règle → False
    assert result is False
