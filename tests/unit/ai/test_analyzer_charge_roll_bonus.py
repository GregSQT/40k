"""Pas de faux négatif charge_roll_bonus quand unit_id réutilisé entre épisodes parallèles.

En entraînement parallèle, step.log entrelace des épisodes de rosters différents. L'unité 102
peut être des Boyz (12 socles, Bigboss en 102#10) dans l'épisode A, puis des EradicatorHeavyBolter
(3 socles) dans l'épisode B. Avant le fix, `positions_by_model_for` ignorait `current_line_models`
et retournait les données périmées de l'épisode A : Bigboss vivant → `unit_effect_in_force`
retournait True pour `charge_roll_bonus` → 22 faux négatifs (token absent sur ligne SM).

Fix : `positions_by_model_for` préfère `current_line_models` (état de la ligne courante) sur
`positions_by_model` (état N-1, potentiellement pollué par un épisode précédent).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Tuple

from ai.analyzer_perfig import positions_by_model_for, unit_effect_in_force


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: EradicatorHeavyBolter SM : 3 socles, aucun ne porte charge_roll_bonus.
SM_MODELS: Dict[str, Tuple[int, int]] = {
    "102#0": (19, 22),
    "102#1": (19, 21),
    "102#2": (20, 22),
}

#: Boyz Orks : 11 socles dont Bigboss en index 10, qui porte charge_roll_bonus.
BOYZ_MODELS: Dict[str, Tuple[int, int]] = {f"102#{i}": (7 + i, 47) for i in range(11)}

UNIT_RULES_BY_TYPE = {
    "Bigboss": {"charge_roll_bonus"},
    "EradicatorHeavyBolter": set(),
    "Boyz": set(),
}

MODEL_TYPES_BOYZ = {**{f"102#{i}": "Boyz" for i in range(10)}, "102#10": "Bigboss"}

MODEL_TYPES_SM = {
    "102#0": "EradicatorHeavyBolter",
    "102#1": "EradicatorHeavyBolter",
    "102#2": "EradicatorHeavyBolter",
}

MODEL_TYPES_MIXED = {**MODEL_TYPES_BOYZ, **MODEL_TYPES_SM}


def _state(current_line_models: Any = None) -> Any:
    """State standard : Boyz périmés dans positions_by_model, current_line_models paramétrable.

    Défaut `None` → {} (pas de ligne courante = scénario pré-fix).
    Passer `{"102": SM_MODELS}` pour simuler la contamination inter-épisode.
    """
    return SimpleNamespace(
        positions_by_model={"102": BOYZ_MODELS},
        current_line_models={} if current_line_models is None else current_line_models,
        model_types=MODEL_TYPES_MIXED,
        pending_model_removals={},
    )


def _config() -> Any:
    return SimpleNamespace(unit_rules_by_type=UNIT_RULES_BY_TYPE)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_positions_by_model_for_prefere_current_line_models():
    """current_line_models prime sur positions_by_model (contamination inter-épisode)."""
    state = _state({"102": SM_MODELS})
    result = positions_by_model_for(state, "102")
    assert result == SM_MODELS, (
        "positions_by_model_for doit retourner current_line_models[102] (SM), pas les Boyz périmés"
    )


def test_positions_by_model_for_repli_quand_current_absent():
    """Repli sur positions_by_model si current_line_models ne contient pas l'unité."""
    state = _state()
    result = positions_by_model_for(state, "102")
    assert result == BOYZ_MODELS


def test_unit_effect_in_force_false_pour_sm_avec_contamination():
    """VERROU principal : charge_roll_bonus = False pour une charge SM même avec Boyz dans N-1.

    Scénario exact des 22 erreurs : current_line_models = 3 Eradicator SM, positions_by_model =
    Boyz + Bigboss périmé. Sans le fix, Bigboss est trouvé → True → faux négatif.
    Avec le fix, current_line_models prime → 3 EradicatorHeavyBolter → False.
    """
    state = _state({"102": SM_MODELS})
    result = unit_effect_in_force(state, _config(), "102", "charge_roll_bonus")
    assert result is False, (
        "Eradicator SM ne porte pas charge_roll_bonus : must return False, pas True (Bigboss périmé)"
    )


def test_unit_effect_in_force_true_pour_boyz_sans_contamination():
    """Contre-épreuve : Boyz réels (Bigboss vivant) → charge_roll_bonus = True."""
    state = SimpleNamespace(
        positions_by_model={},
        current_line_models={"102": BOYZ_MODELS},
        model_types=MODEL_TYPES_BOYZ,
        pending_model_removals={},
    )
    result = unit_effect_in_force(state, _config(), "102", "charge_roll_bonus")
    assert result is True, "Bigboss vivant dans current_line_models → True"


def test_unit_effect_in_force_none_quand_unit_absente():
    """Indécidable (None) si l'unité n'apparaît ni dans current_line_models ni positions_by_model."""
    state = SimpleNamespace(
        positions_by_model={},
        current_line_models={},
        model_types={},
        pending_model_removals={},
    )
    result = unit_effect_in_force(state, _config(), "102", "charge_roll_bonus")
    assert result is None


def test_positions_by_model_for_dict_vide_ne_retombe_pas_sur_n_moins_1():
    """current_line_models[unit_id] == {} → retourner {} sans retomber sur positions_by_model.

    Distinguer None (absent) de {} (présent, 0 modèle vivant) : si tous les modèles sont morts
    dans l'épisode courant, les données périmées de N-1 (autre épisode) ne doivent pas s'appliquer.
    """
    state = SimpleNamespace(
        positions_by_model={"102": BOYZ_MODELS},
        current_line_models={"102": {}},
        model_types=MODEL_TYPES_BOYZ,
        pending_model_removals={},
    )
    result = positions_by_model_for(state, "102")
    assert result == {}, "dict vide dans current_line_models doit être retourné, pas les Boyz de N-1"
