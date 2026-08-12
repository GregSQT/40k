"""Couche per-figurine de l'analyzer (V11) : parsing [MODELS:], résolution d'arme
escouade hétérogène, comptage per-modèle, géométrie de combat per-socle.

Verrouille les corrections apportées aux faux positifs ancre-à-ancre :
- l'analyzer raisonnait unité = 1 point (ancre) ; le jeu V11 est per-figurine.
"""
from __future__ import annotations

import pytest

from ai.analyzer_perfig import (
    parse_models_segment,
    parse_base_token,
    resolve_weapon_characteristic,
    resolve_weapon_value,
    weapon_profile_names,
    squads_min_edge_distance,
)


# --------------------------------------------------------------------------- #
# T2 — parsing du segment [MODELS:]                                            #
# --------------------------------------------------------------------------- #
def test_parse_models_groups_by_unit_id_prefix():
    seg = "Unit 1(85,164) SHOT [MODELS: 1#2@(85,164,z0) 1#3@(91,171,z0) 101#0@(2,146,z0)] [SUCCESS]"
    parsed = parse_models_segment(seg)
    assert parsed == {
        "1": {"1#2": (85, 164), "1#3": (91, 171)},
        "101": {"101#0": (2, 146)},
    }


def test_parse_models_absent_returns_none():
    assert parse_models_segment("Unit 1(1,1) MOVED from (0,0) to (1,1) [SUCCESS]") is None


def test_parse_models_dead_socles_absent_from_list():
    # 1#0 / 1#1 morts : la liste commence à 1#2 (règle « socles morts disparaissent »).
    seg = "[MODELS: 1#2@(85,164,z0) 1#5@(79,168,z0)]"
    parsed = parse_models_segment(seg)
    assert parsed is not None
    assert set(parsed["1"].keys()) == {"1#2", "1#5"}


def test_parse_base_token_round_and_oval():
    assert parse_base_token("base=round/6") == ("round", 6)
    assert parse_base_token("base=oval/[20, 14]") == ("oval", [20, 14])


# --------------------------------------------------------------------------- #
# Class C — résolution d'arme pour escouade hétérogène                         #
# --------------------------------------------------------------------------- #
def test_resolve_weapon_per_unit_first():
    assert resolve_weapon_value("Shoota", {"Shoota": 2}, {"Shoota": 9}) == 2


def test_resolve_weapon_composite_profile_takes_max():
    # « A / B » = profils fusionnés par le moteur ; NB = max des composantes.
    assert resolve_weapon_value(
        "Shoota / Kustom Shoota", {"Shoota": 2}, {"Shoota": 2, "Kustom Shoota": 3}
    ) == 3


def test_resolve_weapon_global_fallback():
    # Arme d'un model-type du squad, absente de l'entrée unit_type -> carte globale.
    assert resolve_weapon_value("Crozius Arcanum", {}, {"Crozius Arcanum": 5}) == 5


def test_resolve_weapon_unresolved_returns_none():
    # Vraie donnée manquante -> None (l'erreur doit remonter, pas de valeur par défaut).
    assert resolve_weapon_value("Inconnue", {}, {}) is None


# --------------------------------------------------------------------------- #
# 05.02 — résolution d'une CARACTÉRISTIQUE (Force) : aucune agrégation         #
# --------------------------------------------------------------------------- #
def test_profile_names_splits_the_engine_composite():
    assert weapon_profile_names("Choppa") == ("Choppa",)
    assert weapon_profile_names("Shoota / Kustom Shoota") == ("Shoota", "Kustom Shoota")


def test_characteristic_reads_the_model_datasheet():
    assert resolve_weapon_characteristic("Choppa", {"Choppa": 4}) == {"Choppa": 4}


def test_characteristic_keeps_each_composite_profile_apart():
    """Le cas RÉEL : `DreadnoughtRedemptor`, Heavy Onslaught Gatling Cannon F6 et Onslaught
    Gatling Cannon F5, mêmes ATK/AP/DMG/règles — le moteur les fusionne dès que les deux
    blessent la cible sur le même seuil. Le `max()` des PLAFONDS rendait F6, une Force que le
    profil F5 de la même ligne ne porte pas ; rendre les deux laisse l'appelant conclure sur des
    Forces réelles, sans en inventer ni en perdre une.
    """
    per_unit = {"Heavy Onslaught Gatling Cannon": 6, "Onslaught Gatling Cannon": 5}
    resolved = resolve_weapon_characteristic(
        "Heavy Onslaught Gatling Cannon / Onslaught Gatling Cannon", per_unit
    )
    assert resolved == per_unit, "les profils ont été agrégés en une seule valeur"


def test_characteristic_marks_a_profile_absent_from_this_datasheet():
    """Composite inter-datasheets (règle 19) : chaque figurine ne connaît que SON profil.

    L'absence est RENDUE (`None`) et non comblée — un emprunt à une autre datasheet serait la
    Force d'un socle qui n'a pas frappé avec cette arme-là.
    """
    assert resolve_weapon_characteristic("Choppa / Big Choppa", {"Choppa": 4}) == {
        "Choppa": 4, "Big Choppa": None,
    }


def test_characteristic_keys_on_the_profiles_even_when_the_whole_name_is_known():
    """Contrat de CLÉS : l'appelant énumère les profils avec `weapon_profile_names` et indexe
    le résultat avec. Rendre ici le nom ENTIER pour un `display_name` contenant lui-même « / »
    lui vaudrait un `KeyError` — l'analyse entière tombe. Non vérifiable est le bon verdict.
    """
    resolved = resolve_weapon_characteristic("A / B", {"A / B": 9, "A": 4})
    assert set(resolved) == {"A", "B"}, "une clé hors du découpage des profils a été rendue"


def test_characteristic_has_no_global_map_parameter():
    """Verrou de conception : l'emprunt inter-datasheets doit être IMPOSSIBLE, pas non branché."""
    import inspect

    params = list(inspect.signature(resolve_weapon_characteristic).parameters)
    assert params == ["weapon_name", "per_unit_map"], (
        "une carte d'agrégation a été rouverte sur la résolution des caractéristiques"
    )


# --------------------------------------------------------------------------- #
# Class A — géométrie de combat per-socle                                      #
# --------------------------------------------------------------------------- #
def test_squads_engaged_per_socle_where_anchor_would_miss():
    """Deux escouades round/6 : leurs ANCRES sont loin (edge >> engagement_zone),
    mais un socle avancé de A touche un socle de B -> engagées per-socle.

    engagement_zone = 10 subhex (2" × inches_to_subhex 5). Le contrôle ancre-à-ancre
    (hex distance == 1) refusait ce combat pourtant légal."""
    # A : ancre loin (50,50) + socle avancé (110,50) ; B : (116,50) collé au socle avancé.
    models_a = {"a#0": (50, 50), "a#1": (110, 50)}
    models_b = {"b#0": (116, 50)}
    edge = squads_min_edge_distance(models_a, ("round", 6), models_b, ("round", 6))
    assert edge <= 10  # engagées : le socle avancé est en contact


def test_squads_far_apart_are_not_engaged():
    edge = squads_min_edge_distance(
        {"a#0": (50, 50)}, ("round", 6), {"b#0": (50, 120)}, ("round", 6)
    )
    assert edge > 10


def test_squad_footprint_empty_raises():
    with pytest.raises(ValueError):
        squads_min_edge_distance({}, ("round", 6), {"b#0": (1, 1)}, ("round", 6))
