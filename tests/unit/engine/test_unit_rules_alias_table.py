"""Table rule_id -> id technique construite UNE fois au chargement du registre unit_rules.

La chaine d'alias est suivie au chargement (`_build_unit_rules_technical_ids`), plus a chaque
appel de `_resolve_effect_rule_id_to_technical` : un cycle ou un alias vers un id absent leve
donc des le premier acces au registre, et la resolution n'est plus qu'un lookup.

Le registre est monkeypatche sur le loader ET le cache module est remis a None : `monkeypatch`
restaure les deux a la sortie, un test ne laisse jamais la table factice derriere lui.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

import engine.phase_handlers.shared_utils as shared_utils
from config_loader import get_config_loader


def _install_registry(monkeypatch: pytest.MonkeyPatch, registry: Dict[str, Dict[str, Any]]) -> None:
    monkeypatch.setattr(shared_utils, "_unit_rules_registry_cache", None)
    monkeypatch.setattr(get_config_loader(), "load_unit_rules_config", lambda: registry)


def test_alias_chain_resolves_to_the_terminal_technical_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """A -> B -> C : 'A' et 'B' resolvent 'C', 'C' se resout lui-meme."""
    _install_registry(monkeypatch, {"A": {"alias": "B"}, "B": {"alias": " C "}, "C": {}})

    assert shared_utils._resolve_effect_rule_id_to_technical("A") == "C"
    assert shared_utils._resolve_effect_rule_id_to_technical(" B ") == "C"
    assert shared_utils._resolve_effect_rule_id_to_technical("C") == "C"


def test_alias_cycle_raises_at_first_registry_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """A -> B -> A : ValueError des le premier `_get_unit_rules_registry`, avant toute resolution."""
    _install_registry(monkeypatch, {"A": {"alias": "B"}, "B": {"alias": "A"}, "C": {}})

    with pytest.raises(ValueError, match="alias cycle"):
        shared_utils._get_unit_rules_registry()
    # Rien n'a ete mis en cache : l'acces suivant retente et echoue de la meme facon.
    assert shared_utils._unit_rules_registry_cache is None
    with pytest.raises(ValueError, match="alias cycle"):
        shared_utils._resolve_effect_rule_id_to_technical("C")


def test_alias_to_missing_id_raises_key_error_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """A -> Z absent : KeyError au chargement, meme pour un id sans alias."""
    _install_registry(monkeypatch, {"A": {"alias": "Z"}, "B": {}})

    with pytest.raises(KeyError, match="'A' aliases unknown rule id 'Z'"):
        shared_utils._resolve_effect_rule_id_to_technical("B")


def test_unknown_rule_id_still_raises_key_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_registry(monkeypatch, {"A": {}})

    with pytest.raises(KeyError, match="Unknown rule id 'nope'"):
        shared_utils._resolve_effect_rule_id_to_technical("nope")


@pytest.mark.parametrize("bad", ["", "   ", None, 3])
def test_invalid_rule_id_input_raises_value_error(monkeypatch: pytest.MonkeyPatch, bad: Any) -> None:
    _install_registry(monkeypatch, {"A": {}})

    with pytest.raises(ValueError, match="non-empty string"):
        shared_utils._resolve_effect_rule_id_to_technical(bad)  # type: ignore[arg-type]


def test_real_registry_table_matches_a_walk_of_the_alias_chain() -> None:
    """VERT VACANT : la table du vrai config/unit_rules.json couvre tout le registre et suit les alias."""
    monkey_free_registry = get_config_loader().load_unit_rules_config()
    table = shared_utils._build_unit_rules_technical_ids(monkey_free_registry)
    assert set(table) == set(monkey_free_registry)
    aliased = {rule_id for rule_id, cfg in monkey_free_registry.items() if "alias" in cfg}
    assert aliased, "le registre reel n'a plus aucun alias : ce test ne prouverait rien"
    for rule_id in aliased:
        assert table[rule_id] != rule_id
        assert "alias" not in monkey_free_registry[table[rule_id]]
