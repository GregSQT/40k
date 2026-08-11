"""Le registre des bots ne peut pas diverger de lui-même.

`ai/bot_registry.py` déclare deux choses qui doivent rester d'accord :
  - des **tuples de clés** (`LEGACY_BOT_KEYS`, `DOCTRINE_BOT_KEYS`, `HOLDOUT_BOT_KEYS`), lisibles
    sans importer le moteur — c'est ce dont `ai/training_callbacks.py` a besoin pour ses
    constantes de module ;
  - une **table clé → classe** (`bot_classes()`), qui elle importe tout.

Ce fichier est le verrou que la docstring du registre promettait. Il a été écrit APRÈS avoir été
cité — la review du 2026-08-11 a relevé la référence à un test inexistant. Une référence à un
verrou absent est pire que pas de référence : elle rassure à tort.

Ce que la divergence coûterait, mesuré le 2026-08-11 : un bot présent dans les classes mais absent
des clés joue ses 600 épisodes sans qu'aucune ligne `vs <bot>` ne soit imprimée, et sans compter
dans le `worst_bot`. La mesure tourne, ses résultats sont invisibles.
"""
from __future__ import annotations

import pytest

from ai import bot_registry


def test_the_key_tuples_and_the_class_table_describe_the_same_panel() -> None:
    """`random` mis à part, toute clé déclarée a une classe, et réciproquement."""
    declared = set(
        bot_registry.LEGACY_BOT_KEYS
        + bot_registry.DOCTRINE_BOT_KEYS
        + bot_registry.HOLDOUT_BOT_KEYS
    )

    assert declared == set(bot_registry.bot_classes())


def test_all_bot_keys_is_exactly_the_declared_panel_plus_random() -> None:
    """`ALL_BOT_KEYS` est ce que les résumés itèrent : rien ne doit y manquer ni s'y ajouter."""
    declared = set(
        bot_registry.LEGACY_BOT_KEYS
        + bot_registry.DOCTRINE_BOT_KEYS
        + bot_registry.HOLDOUT_BOT_KEYS
    )

    assert bot_registry.ALL_BOT_KEYS == declared | {"random"}


def test_every_key_has_a_display_name_and_no_orphan_remains() -> None:
    """Un nom d'affichage manquant fait lever la journalisation TensorBoard ; un nom orphelin
    survit à la suppression du bot et réapparaît au prochain qui reprend la clé."""
    assert set(bot_registry.BOT_DISPLAY_NAMES) == bot_registry.ALL_BOT_KEYS


def test_the_three_families_do_not_overlap() -> None:
    """Un bot est ancien, refondu OU holdout — jamais deux à la fois.

    Le recouvrement ne serait pas cosmétique : `SELECTION_BOT_NAMES` retire les holdouts de
    `ALL_BOT_NAMES`, donc un bot déclaré dans deux familles disparaîtrait du signal de sélection
    tout en continuant d'être joué.
    """
    legacy = set(bot_registry.LEGACY_BOT_KEYS)
    doctrine = set(bot_registry.DOCTRINE_BOT_KEYS)
    holdout = set(bot_registry.HOLDOUT_BOT_KEYS)

    assert legacy & doctrine == set()
    assert legacy & holdout == set()
    assert doctrine & holdout == set()


@pytest.mark.parametrize("bot_key", sorted(bot_registry.ALL_BOT_KEYS - {"random"}))
def test_every_registered_bot_builds(bot_key: str) -> None:
    """Le registre CONSTRUIT vraiment ce qu'il déclare — une classe importable ne suffit pas.

    Randomness à 0.0 pour tous : `LookaheadHoldoutBot` refuse toute autre valeur (un mètre étalon
    ne joue pas aux dés), et les autres l'acceptent.
    """
    bot = bot_registry.build_bot(bot_key, {bot_key: 0.0})

    assert type(bot).__name__ == bot_registry.BOT_DISPLAY_NAMES[bot_key]


def test_an_unknown_key_raises_and_lists_the_valid_ones() -> None:
    with pytest.raises(ValueError, match="Unknown bot_type"):
        bot_registry.build_bot("sprinter", {"sprinter": 0.0})


def test_a_missing_randomness_entry_raises_instead_of_defaulting() -> None:
    """V11 §10.5 : plus de défaut silencieux à 0.15 — il donnait à un bot une part de hasard que
    personne n'avait demandée et que personne ne voyait dans la config."""
    with pytest.raises(KeyError, match="bot_eval_randomness"):
        bot_registry.build_bot("racer", {})
