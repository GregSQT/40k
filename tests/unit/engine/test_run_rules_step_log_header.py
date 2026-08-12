"""Entete `run_rules` de step.log : metriques journalisees = metriques APPLIQUEES.

`_run_rules_for_step_log` journalise les regles en vigueur pour que l'analyzer n'aille pas
relire `config/game_config.json`, edite entre deux runs. Piege verrouille ici :
`self.game_state["config"]` n'est PAS `game_config.json` — le moteur n'y recopie que
`game_rules` / `move` / `charge`. Y lire `distance_metric` levait un KeyError des que
`--step` etait actif.
"""

from typing import Any, Dict, cast

import pytest

import config_loader as config_loader_module
from engine.w40k_core import W40KEngine
from shared.data_validation import ConfigurationError

from tests.unit.engine._config_helpers import build_game_rules, build_move_rules


class _FakeEngine:
    """Porteur minimal de `game_state` : `_run_rules_for_step_log` ne lit rien d'autre."""

    def __init__(self, inches_to_subhex: int) -> None:
        self.game_state = {
            "inches_to_subhex": inches_to_subhex,
            "config": {
                "game_rules": build_game_rules(engagement_zone=2 * inches_to_subhex),
                "move": build_move_rules(
                    can_move_through_enemy_engagement_zone=True,
                    can_move_through_enemy_model=False,
                    can_move_through_friendly_model=True,
                ),
            },
        }


def _run_rules(engine: _FakeEngine) -> Dict[str, Any]:
    """`_run_rules_for_step_log` ne touche que `self.game_state` — le `cast` le dit a pyright."""
    return W40KEngine._run_rules_for_step_log(cast(W40KEngine, engine))


@pytest.fixture(autouse=True)
def config_euclidean(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force les metriques configurees a `euclidean`.

    Le test CONSTRUIT la configuration qu'il observe : sinon basculer `game_config.json` sur
    `hex` rendrait la bascule de resolution indetectable (le x1 rendrait `hex` pour la
    mauvaise raison).
    """
    monkeypatch.setattr(
        config_loader_module.ConfigLoader,
        "get_game_config",
        lambda self: {"distance_metric": {"ranged": "euclidean", "engagement": "euclidean"}},
    )


@pytest.mark.parametrize(
    "inches_to_subhex, attendu",
    [(5, "euclidean"), (1, "hex")],
    ids=["x5_suit_la_config", "x1_force_hex_malgre_la_config"],
)
def test_metriques_journalisees(inches_to_subhex: int, attendu: str):
    """A x1 la geometrie est hex quelle que soit la config ; au-dessus, la config s'applique."""
    engine = _FakeEngine(inches_to_subhex)
    # Garde de pertinence : le fake reproduit bien le config APPAUVRI du moteur, sinon le test
    # ne verrouillerait pas la regression qu'il vise.
    assert "distance_metric" not in engine.game_state["config"]
    rules = _run_rules(engine)
    assert rules["metric.ranged"] == attendu
    assert rules["metric.engagement"] == attendu


def test_regles_de_move_et_ez_viennent_du_game_state():
    rules = _run_rules(_FakeEngine(5))
    assert rules["engagement_zone_subhex"] == 10
    assert rules["move.thru_ez"] is True
    assert rules["move.thru_enemy"] is False
    assert rules["move.thru_friendly"] is True


def test_cle_manquante_leve_au_lieu_de_defaut_silencieux():
    fake = _FakeEngine(5)
    del fake.game_state["config"]["move"]["can_move_through_enemy_model"]
    with pytest.raises(ConfigurationError):
        _run_rules(fake)
