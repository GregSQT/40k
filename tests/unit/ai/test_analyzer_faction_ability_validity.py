"""§1.7 de l'analyzer : une capacité de FACTION est une règle VALIDE, pas une faute.

Pourquoi ce fichier existe. `rule_to_units` n'était construit que depuis les `UNIT_RULES` des
datasheets, et une capacité de faction (08.04 : Waaagh!, Oath of Moment) n'y figure dans AUCUNE
— c'est le mot-clé de faction qui la porte (`unit_has_waaagh_ability`). Dès que le handler de
charge s'est mis à relever l'usage du Waaagh! (charge après Advance permise par 08.04, un coup
parfaitement légal), `special_rules_invalid` comptait chacun de ces relevés : la ligne 1.7
passait au rouge sur toute partie orke, et la synthèse avec elle.

Règles citées : Documentation/40k_rules/08 Command phase (Waaagh!, Oath of Moment).
"""

from __future__ import annotations

import ai.analyzer_config as analyzer_config
from engine.game_state import FACTION_ABILITY_KEYWORD_BY_RULE_ID


def _config():
    # L'échelle du run est normalement posée depuis l'entête `Board:` du step.log ; ici aucune
    # géométrie n'est mesurée, seule la table des règles est lue.
    analyzer_config.set_run_inches_to_subhex(1)
    return analyzer_config.load_analyzer_config()


def test_faction_abilities_are_attached_to_their_keyword_carriers():
    """Le porteur d'une capacité de faction est le KEYWORD, pas une entrée de datasheet."""
    cfg = _config()
    for rule_id, faction_keyword in FACTION_ABILITY_KEYWORD_BY_RULE_ID.items():
        carriers = cfg.rule_to_units.get(rule_id, set())
        expected = {
            ut for ut, kws in cfg.unit_rules_by_type.items()
            if faction_keyword in _faction_keywords(cfg, ut)
        }
        assert expected, f"prémisse : aucun type d'unité ne porte {faction_keyword}"
        assert carriers == expected, (
            f"{rule_id} devrait être valide pour EXACTEMENT les unités {faction_keyword}"
        )


def _faction_keywords(cfg, unit_type):
    from engine.game_state import unit_faction_keywords
    from ai.unit_registry import UnitRegistry

    return unit_faction_keywords(UnitRegistry().units[unit_type])


def test_a_waaagh_charge_is_not_counted_invalid():
    """Le prédicat DE PRODUCTION (`special_rule_usage_is_valid`) appliqué à un relevé réel.

    Sans le complément de faction, `("waaagh", <unité orke>)` satisfait le prédicat d'invalidité
    et la ligne 1.7 affiche `INVALID` sur une charge légale.

    Le prédicat est APPELÉ, jamais recopié : une version recopiée du critère reste verte quand la
    production change d'avis — mesuré, elle l'est restée quand le verdict §1.7 est passé du
    post-traitement au relevé (19.04).
    """
    from ai.analyzer_rules import special_rule_usage_is_valid

    cfg = _config()
    ork_unit = next(iter(sorted(cfg.rule_to_units["waaagh"])))
    assert special_rule_usage_is_valid(
        "waaagh", ork_unit, {ork_unit}, cfg.rule_to_units
    ), f"usage légal du Waaagh! par {ork_unit} compté comme faute"
    # Escouade dont AUCUNE figurine vivante ne porte la capacité de faction : la faute reste une
    # faute, le complément de faction ne blanchit pas tout le plateau.
    non_ork = sorted(set(cfg.unit_rules_by_type) - cfg.rule_to_units["waaagh"])[0]
    assert not special_rule_usage_is_valid(
        "waaagh", non_ork, {non_ork}, cfg.rule_to_units
    ), f"{non_ork} ne porte pas Waaagh! : son usage doit rester INVALID"
