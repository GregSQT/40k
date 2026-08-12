"""Verrous sur `pytest.ini` — la configuration du harnais qui rend des défauts VISIBLES.

Une option retirée de `pytest.ini` ne casse rien : la suite reste verte, elle regarde simplement
moins de choses. C'est le mode de disparition le plus silencieux qui soit.

Ces tests observent donc les filtres RÉELLEMENT ACTIFS pendant leur propre exécution, jamais une
copie reparsée du fichier : mesuré le 2026-08-12, un contrôle qui relisait `pytest.ini` et
rejouait ses filtres dans un `catch_warnings` restait vert sous `-p no:warnings`, c'est-à-dire
dans la configuration exacte qu'il existait pour interdire.
"""

from __future__ import annotations

import warnings

import pytest


def test_a_deprecation_warning_is_an_error_here() -> None:
    """L'avis de dépréciation d'une dépendance doit faire ÉCHOUER la suite, pas la commenter.

    Mesuré le 2026-08-12 : `get_schedule_fn()` était dépréciée depuis une version majeure entière
    de SB3 et s'affichait à chaque exécution, sans que rien ne la traite. Le training ne peut pas
    jouer ce rôle (les appels ont lieu au chargement du modèle, la sortie est noyée dans le log) :
    la suite est le seul endroit où ces avis sont lus.

    Le message reproduit celui de SB3 : un `UserWarning` NU, pas un `DeprecationWarning`
    (stable_baselines3/common/utils.py:166). Un filtre `error::DeprecationWarning` serait présent,
    lisible, et n'attraperait rien.
    """
    with pytest.raises(UserWarning, match="deprecated"):
        warnings.warn("get_schedule_fn() is deprecated, please use FloatSchedule() instead")


def test_the_filter_survives_a_multiline_message() -> None:
    """VERT VACANT : pytest confronte le message par `re.match`, où `.` ne franchit pas un saut de
    ligne. gymnasium et SB3 écrivent des avis sur plusieurs lignes ; sans `(?s)` dans le motif, le
    filtre est actif, le test ci-dessus passe, et ces avis-là continuent de défiler.
    """
    with pytest.raises(UserWarning):
        warnings.warn("The environment is out of date.\nThis API will be deprecated in v3.")


def test_the_filter_is_not_limited_to_the_exact_phrase_is_deprecated() -> None:
    """« will be deprecated », « deprecation notice » : le même avis, une autre tournure."""
    with pytest.raises(FutureWarning):
        warnings.warn("deprecation of the old loader, use the new one", FutureWarning)
