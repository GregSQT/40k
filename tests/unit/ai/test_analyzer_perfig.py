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
    resolve_weapon_value,
    squads_min_edge_distance,
)


# --------------------------------------------------------------------------- #
# T2 — parsing du segment [MODELS:]                                            #
# --------------------------------------------------------------------------- #
def test_parse_models_groups_by_unit_id_prefix():
    seg = "Unit 1(85,164) SHOT [MODELS: 1#2@(85,164) 1#3@(91,171) 101#0@(2,146)] [SUCCESS]"
    parsed = parse_models_segment(seg)
    assert parsed == {
        "1": {"1#2": (85, 164), "1#3": (91, 171)},
        "101": {"101#0": (2, 146)},
    }


def test_parse_models_absent_returns_none():
    assert parse_models_segment("Unit 1(1,1) MOVED from (0,0) to (1,1) [SUCCESS]") is None


def test_parse_models_dead_socles_absent_from_list():
    # 1#0 / 1#1 morts : la liste commence à 1#2 (règle « socles morts disparaissent »).
    seg = "[MODELS: 1#2@(85,164) 1#5@(79,168)]"
    parsed = parse_models_segment(seg)
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
