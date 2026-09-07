from itertools import product

import pytest

from engine.combat_utils import (
    DICE_OUTCOMES,
    calculate_hex_distance,
    calculate_wound_target,
    check_los_cached,
    expected_capped_dice_value,
    expected_dice_value,
    get_hex_neighbors,
    get_unit_by_id,
    normalize_coordinate,
    normalize_coordinates,
    resolve_dice_value,
    set_unit_coordinates,
)


def test_resolve_dice_value_returns_int_unchanged() -> None:
    assert resolve_dice_value(4, "ctx") == 4


def test_resolve_dice_value_raises_on_unsupported_expression() -> None:
    with pytest.raises(ValueError, match=r"Unsupported dice expression"):
        resolve_dice_value("D8", "ctx")


def test_resolve_dice_value_rolls_2d6(monkeypatch: pytest.MonkeyPatch) -> None:
    rolls = iter([2, 5])
    monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
    assert resolve_dice_value("2D6", "ctx") == 7


def test_expected_dice_value_known_mappings_and_invalid() -> None:
    assert expected_dice_value("D3", "ctx") == 2.0
    assert expected_dice_value("D6+3", "ctx") == 6.5
    assert expected_dice_value(9, "ctx") == 9.0
    with pytest.raises(ValueError, match=r"Unsupported dice expression"):
        expected_dice_value("3D6", "ctx")


def test_dice_outcomes_matches_what_resolve_dice_value_can_roll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VERROU : la table des issues decrit le MEME de que le tirage reel.

    `resolve_dice_value` garde ses branches en dur au lieu de tirer dans `DICE_OUTCOMES` : pour
    "2D6" il consomme DEUX `random.randint`, et passer a un tirage unique parmi 36 issues
    changerait la consommation de RNG, donc les parties rejouees a graine fixe. Les deux
    descriptions du de coexistent donc volontairement, et c'est ce test qui interdit qu'elles
    divergent — sans lui, une expression ajoutee d'un seul cote passerait inapercue.

    Comparaison en MULTISET (`sorted`) et non en ensemble, parce que "2D6" tire ses 36 sommes a
    des frequences INEGALES : un ensemble accepterait les 11 sommes distinctes et laisserait
    passer une table qui les croirait equiprobables. Le repli de "D3", lui, reste uniforme —
    y ecrire 1,2,3 ne changerait aucune esperance, le multiset y verrouille seulement que la
    table demeure le reflet fidele du tirage.
    """
    for expr, table in DICE_OUTCOMES.items():
        n_dice = 2 if expr == "2D6" else 1
        rolled = []
        for combo in product(range(1, 7), repeat=n_dice):
            it = iter(combo)
            monkeypatch.setattr("random.randint", lambda a, b, _it=it: next(_it))
            rolled.append(resolve_dice_value(expr, "ctx"))
        assert sorted(rolled) == sorted(table), expr


def test_expected_capped_dice_value_caps_each_outcome_not_the_mean() -> None:
    """05.04 : le plafond porte sur chaque jet, donc `E[min(de, PV)]`, pas `min(E[de], PV)`.

    Les valeurs attendues sont ecrites en dur (et non recalculees depuis la table) pour que le
    test echoue si la table ET la fonction derivaient ensemble.
    """
    # D6 contre 3 PV : 1,2,3,3,3,3 -> 2,5. `min(E, PV)` aurait rendu 3,0 (sur-credit de 20 %).
    assert expected_capped_dice_value("D6", 3, "ctx") == pytest.approx(2.5)
    # D3 contre 2 PV : 1,1,2,2,2,2 -> 5/3. `min(E, PV)` aurait rendu 2,0.
    assert expected_capped_dice_value("D3", 2, "ctx") == pytest.approx(5 / 3)
    assert expected_capped_dice_value("D6+1", 4, "ctx") == pytest.approx(3.5)


def test_expected_capped_dice_value_weights_2d6_over_its_36_outcomes() -> None:
    """"2D6" a 36 issues de sommes inegalement probables, pas 6 faces.

    Toute formule en 1/6 rendrait ici 6,0 (le plafond) au lieu de 196/36 : c'est le cas que le
    comptage par faces d'un D6 unique ne peut pas voir.
    """
    assert expected_capped_dice_value("2D6", 6, "ctx") == pytest.approx(196 / 36)
    assert expected_capped_dice_value("2D6", 2, "ctx") == pytest.approx(2.0)


def test_expected_capped_dice_value_degenerate_caps_and_int_and_invalid() -> None:
    # Plafond hors d'atteinte du de : aucune issue rabotee, donc l'esperance nue.
    assert expected_capped_dice_value("D6", 6, "ctx") == expected_dice_value("D6", "ctx")
    assert expected_capped_dice_value("2D6", 12, "ctx") == expected_dice_value("2D6", "ctx")
    # Plafond sous le minimum du de : toutes les issues rabotees, donc le plafond.
    assert expected_capped_dice_value("D6+3", 2, "ctx") == 2.0
    # Degat fixe : un de a une seule face.
    assert expected_capped_dice_value(3, 2, "ctx") == 2.0
    assert expected_capped_dice_value(3, 5, "ctx") == 3.0
    with pytest.raises(ValueError, match=r"Unsupported dice expression"):
        expected_capped_dice_value("3D6", 2, "ctx")
    with pytest.raises(TypeError, match=r"Invalid dice value type"):
        expected_capped_dice_value(None, 2, "ctx")  # type: ignore[arg-type]


def test_get_unit_by_id_requires_index_and_looks_up_by_str_id() -> None:
    game_state = {"unit_by_id": {"12": {"id": "12"}}}
    assert get_unit_by_id(game_state, "12") == {"id": "12"}
    assert get_unit_by_id(game_state, "13") is None
    with pytest.raises(Exception):
        get_unit_by_id({}, "12")


def test_get_hex_neighbors_even_and_odd_columns() -> None:
    even_neighbors = get_hex_neighbors(2, 3)
    odd_neighbors = get_hex_neighbors(3, 3)
    assert len(even_neighbors) == 6
    assert len(odd_neighbors) == 6
    assert (3, 2) in even_neighbors  # even NE
    assert (4, 3) in odd_neighbors   # odd NE


def test_get_hex_neighbors_fast_path_matches_normalized_path() -> None:
    """Le chemin rapide entier de `get_hex_neighbors` ne doit RIEN changer d'observable.

    Il interroge le cache avec la cle brute avant de normaliser (boucle interne des BFS du
    moteur). Ce test epingle les trois familles d'entrees que la normalisation seule traitait :
    un `float` entier, un `float` a tronquer et une chaine doivent rendre EXACTEMENT le meme
    voisinage, dans le meme ordre, que l'entier correspondant.
    """
    reference = get_hex_neighbors(3, 4)
    assert get_hex_neighbors(3.0, 4.0) == reference
    assert get_hex_neighbors(3.7, 4) == reference  # int(3.7) == 3, jamais un arrondi a 4
    assert get_hex_neighbors("3", "4") == reference
    # Meme controle sur une colonne PAIRE : le voisinage depend de la parite, un chemin rapide
    # qui se tromperait de cle ne se verrait pas sur une seule parite.
    assert get_hex_neighbors(2.0, 3.0) == get_hex_neighbors(2, 3)
    assert get_hex_neighbors(3, 4) is reference  # cache hit : retourne le meme objet, chemin rapide


def test_get_hex_neighbors_rejects_unhashable_with_the_normalizer_error() -> None:
    """Une coordonnee non normalisable leve l'erreur du NORMALISEUR, pas celle du cache.

    Verrou du garde `type(...) is int` : sans lui, la cle brute partirait dans un `dict.get`
    et un type non hashable leverait « unhashable type », masquant le diagnostic explicite de
    `normalize_coordinate` sur lequel les appelants s'appuient.
    """
    with pytest.raises(TypeError, match=r"Invalid coordinate type"):
        get_hex_neighbors([1], 2)
    with pytest.raises(TypeError, match=r"Invalid coordinate type"):
        get_hex_neighbors(1, {"row": 2})


def test_normalize_coordinate_and_coordinates_error_paths() -> None:
    assert normalize_coordinate("5.0") == 5
    assert normalize_coordinates("7", 8.0) == (7, 8)
    with pytest.raises(TypeError, match=r"Invalid coordinate type"):
        normalize_coordinate({"x": 1})
    with pytest.raises(ValueError, match=r"Invalid coordinate string"):
        normalize_coordinate("abc")


def test_set_unit_coordinates_updates_unit_with_normalized_values() -> None:
    unit = {"id": "u1", "col": 0, "row": 0}
    set_unit_coordinates(unit, "6.0", 9.0)
    assert unit["col"] == 6
    assert unit["row"] == 9


def test_calculate_hex_distance_basic_cases() -> None:
    assert calculate_hex_distance(0, 0, 0, 0) == 0
    assert calculate_hex_distance(0, 0, 1, 0) == 1
    assert calculate_hex_distance(0, 0, 2, 0) >= 1


def test_check_los_cached_returns_float_and_validates_inputs() -> None:
    shooter = {"id": "s1", "los_cache": {"t1": True}}
    target = {"id": "t1"}
    assert check_los_cached(shooter, target, {}) == 1.0

    with pytest.raises(KeyError, match=r"Target missing required 'id'"):
        check_los_cached(shooter, {}, {})
    with pytest.raises(ValueError, match=r"los_cache missing for shooter"):
        check_los_cached({"id": "s2"}, target, {})


def test_calculate_wound_target_w40k_thresholds() -> None:
    assert calculate_wound_target(8, 4) == 2
    assert calculate_wound_target(5, 4) == 3
    assert calculate_wound_target(4, 4) == 4
    assert calculate_wound_target(2, 5) == 6
    assert calculate_wound_target(3, 5) == 5
