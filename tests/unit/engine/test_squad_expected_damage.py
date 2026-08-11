"""Dégâts espérés d'une ACTIVATION d'escouade — le facteur « figurines » qui manquait.

`lookup_best_weapon` rend un dégât PAR FIGURINE (sa clé offensive porte `NB`, le nombre
d'attaques d'une figurine). Les bots d'évaluation, eux, décident au niveau de l'ESCOUADE : sans
multiplication par l'effectif vivant, dix Boyz valent un Boy, et le choix de cible est faux.

Ces tests portent sur `squad_expected_damage`, le socle du chantier de refonte du panel
(`Documentation/Implémentation/A_faire/bots_refonte_panel.md`).
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.weapon_damage_cache import squad_expected_damage


def _state(*, per_model_damage: float, alive: int, total: int) -> Dict[str, Any]:
    """État minimal : un cache de paires, `squad_models` et `models_cache`.

    `total - alive` figurines sont absentes de `models_cache` : c'est exactement ainsi que le
    moteur représente les pertes (les morts en sont retirés), et c'est ce que le comptage doit
    lire — pas la longueur de `squad_models`, qui garde l'effectif initial.
    """
    model_ids = [f"1#{i}" for i in range(total)]
    return {
        "_best_weapon_cache": {("1", 1, "101"): (0, per_model_damage),
                               ("1", 0, "101"): (0, per_model_damage / 2.0)},
        "squad_models": {"1": model_ids, "101": ["101#0"]},
        "models_cache": {mid: {"HP_CUR": 2} for mid in model_ids[:alive]},
    }


def test_damage_scales_with_the_number_of_living_models() -> None:
    """Dix figurines frappent dix fois plus fort qu'une — c'est le défaut corrigé."""
    one = squad_expected_damage(_state(per_model_damage=0.5, alive=1, total=1), "1", "101", True)
    ten = squad_expected_damage(_state(per_model_damage=0.5, alive=10, total=10), "1", "101", True)

    assert one == pytest.approx(0.5)
    assert ten == pytest.approx(5.0)


def test_the_dead_no_longer_shoot() -> None:
    """L'effectif lu est le VIVANT, pas celui du roster.

    Verrou du piège inverse : compter `len(squad_models[sid])` donnerait 10 à une escouade
    réduite à 3 survivants, et le bot surestimerait une escouade décimée jusqu'à sa mort.
    """
    state = _state(per_model_damage=1.0, alive=3, total=10)

    assert squad_expected_damage(state, "1", "101", True) == pytest.approx(3.0)


def test_melee_and_ranged_are_two_distinct_lookups() -> None:
    """Le mode d'attaque change la ligne de cache lue, pas seulement un coefficient."""
    state = _state(per_model_damage=2.0, alive=4, total=4)

    assert squad_expected_damage(state, "1", "101", True) == pytest.approx(8.0)
    assert squad_expected_damage(state, "1", "101", False) == pytest.approx(4.0)


def test_a_weapon_that_cannot_wound_yields_zero_without_touching_the_roster() -> None:
    """Zéro est un RÉSULTAT (aucune arme ne blesse la cible), pas un repli — et il n'exige pas
    que l'escouade attaquante soit lisible."""
    state = _state(per_model_damage=0.0, alive=5, total=5)

    assert squad_expected_damage(state, "1", "101", True) == 0.0


def test_a_missing_cache_raises_instead_of_inventing_a_harmless_enemy() -> None:
    """T1 : sans cache, on lève. Rendre 0.0 ferait passer toute unité pour inoffensive."""
    state = _state(per_model_damage=1.0, alive=2, total=2)
    del state["_best_weapon_cache"]

    with pytest.raises(RuntimeError, match="_best_weapon_cache"):
        squad_expected_damage(state, "1", "101", True)


def test_an_attacker_absent_from_squad_models_raises() -> None:
    """Même règle : une escouade inconnue est une divergence d'invariant, pas un zéro."""
    state = _state(per_model_damage=1.0, alive=2, total=2)
    del state["squad_models"]["1"]

    with pytest.raises(KeyError, match="squad_models"):
        squad_expected_damage(state, "1", "101", True)
