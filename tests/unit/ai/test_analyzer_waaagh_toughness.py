"""target_bodyguard_toughness : BannerNob gagne +1E pendant le Waaagh.

Avant le fix, `toughness_bonus_while_waaagh` n'était pas pris en compte dans
`target_bodyguard_toughness`. Le contrôle de blessure comparait l'E de base (T4 BannerNob)
à la F de l'attaquant, sans appliquer le bonus Waaagh (+1T) — produisant de faux
`wound_threshold_mismatch` quand le BannerNob (T5 en Waaagh) requiert 5+ pour blesser.

Fix : vérifier `active_effects[target_player]["waaagh"] == "on"` et ajouter le bonus par
figurine vivante de la pool (model_types, jamais deviné).

Scénario :
  - Cible : BannerNob (unit_type="BannerNob", T=4, bonus_waaagh=+1)
  - Waaagh actif pour le joueur cible (active_effects[2]["waaagh"] == "on")
  - Attendu : target_bodyguard_toughness → 5 (4+1)
  - Sans Waaagh → 4
"""
from __future__ import annotations

from types import SimpleNamespace


def _state(waaagh_on: bool) -> SimpleNamespace:
    return SimpleNamespace(
        positions_by_model={"1": {"1#0": (10, 10)}},
        model_types={"1#0": "BannerNob"},
        unit_models_alive={"1": 1},
        unit_player={"1": 2},
        active_effects={2: {"waaagh": "on" if waaagh_on else "off"}},
    )


def _config() -> SimpleNamespace:
    # unit_registry.units requis par _model_is_character (dérivation CHARACTER depuis UNIT_RULES)
    unit_registry = SimpleNamespace(units={"BannerNob": {"UNIT_RULES": []}})
    return SimpleNamespace(
        unit_toughness_by_type={"BannerNob": 4},
        toughness_bonus_waaagh_by_type={"BannerNob": 1},
        unit_rules_by_type={"BannerNob": set()},
        character_unit_types=set(),
        unit_registry=unit_registry,
    )


def test_waaagh_on_ajoute_bonus_toughness():
    """Waaagh actif → BannerNob passe de T4 à T5."""
    from ai.analyzer_wound import target_bodyguard_toughness

    result = target_bodyguard_toughness(_state(waaagh_on=True), _config(), "1")
    assert result == 5, f"Attendu T5 (BannerNob + Waaagh), obtenu {result}"


def test_waaagh_off_toughness_de_base():
    """Waaagh inactif → E de base non bonifiée."""
    from ai.analyzer_wound import target_bodyguard_toughness

    result = target_bodyguard_toughness(_state(waaagh_on=False), _config(), "1")
    assert result == 4, f"Attendu T4 (sans Waaagh), obtenu {result}"
