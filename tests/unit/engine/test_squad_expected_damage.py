"""Dégâts espérés d'une ACTIVATION d'escouade — la SOMME de ce que portent ses figurines.

Deux défauts successifs, tous deux corrigés ici :

1. Les bots décidaient sur `max(NB × DMG)` d'une seule arme, sans jet pour toucher ni
   Force/Endurance ni AP/sauvegarde ni effectif. `squad_expected_damage` a remplacé ce proxy.
2. Sa première version prenait la meilleure arme de l'ESCOUADE et la **multipliait** par
   l'effectif. Or le profil d'armes porté par l'objet `unit` n'est que celui du soldat de base :
   sergents, armes spéciales et personnages attachés n'y figurent pas. Une escouade menée par un
   personnage passait donc pour bien moins dangereuse qu'elle ne l'est — mesuré sur
   `scenario_bot-01` : 50 paires (attaquant, cible, phase) sur 90 fausses, médiane 0,50× la vraie
   valeur, pire cas 0,18×.

Le verrou du défaut n° 2 est `test_the_special_weapons_of_a_mixed_squad_are_counted` : c'est le
seul test que la multiplication ne peut pas passer. Les autres tiennent les invariants déjà
acquis (effectif vivant, tir ≠ mêlée, pas de repli).

Socle du chantier `Documentation/Implémentation/A_faire/bots_refonte_panel.md`.
"""
from __future__ import annotations

from typing import Any, Dict, Sequence

import pytest

from engine.weapon_damage_cache import squad_expected_damage


def _state(ranged_damage: Sequence[float], *, alive: int | None = None) -> Dict[str, Any]:
    """État minimal : une escouade « 1 » dont la figurine `i` inflige `ranged_damage[i]`.

    La mêlée vaut la moitié du tir, pour que les deux modes ne puissent pas être confondus.

    Les figurines au-delà de `alive` sont absentes de `models_cache` : c'est exactement ainsi
    que le moteur représente les pertes (les morts en sont retirés), et c'est ce que la somme
    doit lire — pas `squad_models`, qui garde l'effectif initial.
    """
    model_ids = [f"1#{i}" for i in range(len(ranged_damage))]
    living = model_ids if alive is None else model_ids[:alive]
    cache: Dict[Any, Any] = {}
    for mid, dmg in zip(model_ids, ranged_damage):
        cache[(mid, 1, "101")] = (0, dmg)
        cache[(mid, 0, "101")] = (0, dmg / 2.0)
    return {
        "_best_weapon_cache": cache,
        "squad_models": {"1": model_ids, "101": ["101#0"]},
        "models_cache": {mid: {"HP_CUR": 2} for mid in living},
    }


def test_the_special_weapons_of_a_mixed_squad_are_counted() -> None:
    """LE verrou. Une escouade hétérogène vaut la somme de ses figurines, pas un profil × N.

    Quatre soldats de base à 0,5 et un sergent à 4,0 : la vérité est 6,0. Reprendre l'ancienne
    règle — meilleure arme × effectif — donnerait 4,0 × 5 = 20,0 en lisant le sergent, ou
    0,5 × 5 = 2,5 en lisant le soldat de base (ce que faisait le code, puisque l'objet `unit`
    ne porte que ce profil-là). Aucune multiplication ne peut tomber sur 6,0 : c'est ce qui
    rend ce test irremplaçable par les suivants.
    """
    state = _state([0.5, 0.5, 0.5, 0.5, 4.0])

    assert squad_expected_damage(state, "1", "101", True) == pytest.approx(6.0)
    assert squad_expected_damage(state, "1", "101", False) == pytest.approx(3.0)


def test_damage_scales_with_the_number_of_living_models() -> None:
    """Dix figurines identiques frappent dix fois plus fort qu'une."""
    one = squad_expected_damage(_state([0.5]), "1", "101", True)
    ten = squad_expected_damage(_state([0.5] * 10), "1", "101", True)

    assert one == pytest.approx(0.5)
    assert ten == pytest.approx(5.0)


def test_the_dead_no_longer_shoot() -> None:
    """L'effectif lu est le VIVANT, pas celui du roster.

    Verrou du piège inverse : sommer sur `squad_models` sans filtrer donnerait 10 à une escouade
    réduite à 3 survivants, et le bot surestimerait une escouade décimée jusqu'à sa mort.
    """
    state = _state([1.0] * 10, alive=3)

    assert squad_expected_damage(state, "1", "101", True) == pytest.approx(3.0)


def test_the_dead_taken_are_the_ones_the_cache_still_knows() -> None:
    """Les pertes retirent LEUR contribution, pas une part moyenne.

    Si le sergent tombe, l'escouade perd ses 4,0 et pas 6,0/5. Un comptage par effectif ne
    saurait pas distinguer les deux, et surestimerait une escouade qui vient de perdre sa
    pièce maîtresse — le cas où l'erreur coûte le plus cher.
    """
    quatre_soldats_et_un_sergent = _state([0.5, 0.5, 0.5, 0.5, 4.0], alive=4)

    assert squad_expected_damage(quatre_soldats_et_un_sergent, "1", "101", True) == pytest.approx(2.0)


def test_melee_and_ranged_are_two_distinct_lookups() -> None:
    """Le mode d'attaque change la ligne de cache lue, pas seulement un coefficient."""
    state = _state([2.0] * 4)

    assert squad_expected_damage(state, "1", "101", True) == pytest.approx(8.0)
    assert squad_expected_damage(state, "1", "101", False) == pytest.approx(4.0)


def test_a_weapon_that_cannot_wound_yields_zero_without_touching_the_roster() -> None:
    """Zéro est un RÉSULTAT (aucune arme ne blesse la cible), pas un repli."""
    state = _state([0.0] * 5)

    assert squad_expected_damage(state, "1", "101", True) == 0.0


def test_a_squad_wiped_out_deals_nothing() -> None:
    """Plus une figurine vivante : zéro, et sans lever — l'escouade existe encore au roster."""
    state = _state([3.0] * 4, alive=0)

    assert squad_expected_damage(state, "1", "101", True) == 0.0


def test_a_missing_cache_raises_instead_of_inventing_a_harmless_enemy() -> None:
    """T1 : sans cache, on lève. Rendre 0.0 ferait passer toute unité pour inoffensive."""
    state = _state([1.0, 1.0])
    del state["_best_weapon_cache"]

    with pytest.raises(RuntimeError, match="_best_weapon_cache"):
        squad_expected_damage(state, "1", "101", True)


def test_an_attacker_absent_from_squad_models_raises() -> None:
    """Même règle : une escouade inconnue est une divergence d'invariant, pas un zéro."""
    state = _state([1.0, 1.0])
    del state["squad_models"]["1"]

    with pytest.raises(KeyError, match="squad_models"):
        squad_expected_damage(state, "1", "101", True)
