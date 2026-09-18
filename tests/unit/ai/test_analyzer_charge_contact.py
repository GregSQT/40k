"""PROJ.1.3.contact — 11.04 WHILE MOVING « Each model that can end its move within 1" of one or
more charge targets must do so ».

Le contrôle de charge existant (`PROJ.1.3.budget`) ne juge que le budget ; une figurine qui
finit à 2" d'une cible alors qu'une case à ≤ 1" était libre et atteignable dans le jet passait
inaperçue (mesure bot contre bot du 2026-09-18 : 118 figurines au contact sur 516 après
charge, moteur 5b2422dd5).

Géométrie x1 : S à (10,4), cible à (10,10) — 6 cases ; jet 11 ; (10,9) est à 1 (contact).
"""

from __future__ import annotations

from engine.combat_utils import calculate_hex_distance
from tests.unit.ai._melee_lot_fabrique import deployed, models_segment, parse, unit_header

START = (10, 4)
TARGET = (10, 10)
HEADERS = unit_header("1", 1) + unit_header("101", 2)
SETUP = deployed("1", 1, [START]) + deployed("101", 2, [TARGET])


def _charged(dest, roll: int = 11, extra: str = "") -> str:
    return (
        f"[10:00:02] E1 T1 P1 CHARGE : Unit 1({START[0]},{START[1]}) CHARGED{extra} Unit 101({TARGET[0]},{TARGET[1]})"
        f" from ({START[0]},{START[1]}) to ({dest[0]},{dest[1]}) [Roll: {roll}]"
        f" [Dist: 6.0\" | Nearest: 6.0\"] [R:+0.0] {models_segment('1', [dest])} [SUCCESS]\n"
    )


def test_geometry_premise():
    assert calculate_hex_distance(*START, *TARGET) == 6
    assert calculate_hex_distance(10, 8, *TARGET) == 2 and calculate_hex_distance(10, 9, *TARGET) == 1


def test_stopping_at_two_inches_with_a_contact_cell_reachable_is_an_error(tmp_path):
    stats = parse(tmp_path, HEADERS, SETUP + _charged((10, 8)))
    assert stats["charge_no_contact"][1] == 1
    first = stats["first_error_lines"]["charge_no_contact"][1]
    assert first is not None and first["model"] == "1#0"
    contact_col, contact_row = first["contact_cell"]
    assert calculate_hex_distance(contact_col, contact_row, *TARGET) == 1
    assert stats["rule_usage"]["PROJ.1.3.contact"][1] == 1
    assert stats["charge_invalid"][1]["distance_over_roll"] == 0, "le budget est respecté"


def test_ending_in_contact_is_no_error(tmp_path):
    stats = parse(tmp_path, HEADERS, SETUP + _charged((10, 9)))
    assert stats["charge_no_contact"][1] == 0
    assert stats["rule_usage"]["PROJ.1.3.contact"][1] == 1


def test_roll_too_short_for_contact_is_no_error(tmp_path):
    """Jet 4 : (10,8) est le plus loin atteignable, le contact (10,9) demande 5 pas → légal."""
    stats = parse(tmp_path, HEADERS, SETUP + _charged((10, 8), roll=4))
    assert stats["charge_no_contact"][1] == 0
    assert stats["rule_usage"]["PROJ.1.3.contact"][1] == 1


def test_flying_charge_is_out_of_scope(tmp_path):
    """21.03 : mesure à vol d'oiseau, le chemin BFS n'a pas de sens → ni erreur ni occasion."""
    stats = parse(tmp_path, HEADERS, SETUP + _charged((10, 8), extra=" [FLY]"))
    assert stats["charge_no_contact"][1] == 0
    assert stats["rule_usage"]["PROJ.1.3.contact"][1] == 0


NON_TARGET = (10, 11)


def _charged_with_bystander(dest, roll: int = 11) -> str:
    """Même charge, mais une unité ennemie NON-cible 102 est déployée en NON_TARGET."""
    return deployed("102", 2, [NON_TARGET]) + _charged(dest, roll=roll)


def test_geometry_premise_bystander():
    """Toute case à 1 de la cible est à ≤ 2 (zone d'engagement x1) de la non-cible adjacente ;
    la case d'arrivée (10,8) est à 2 de la cible (engagée) et à 3 de la non-cible (hors ER)."""
    from engine.combat_utils import get_hex_neighbors

    assert calculate_hex_distance(*NON_TARGET, *TARGET) == 1
    for c, r in get_hex_neighbors(*TARGET):
        assert calculate_hex_distance(c, r, *NON_TARGET) <= 2, (c, r)
    assert calculate_hex_distance(10, 8, *NON_TARGET) == 3


def test_contact_cells_inside_a_non_target_engagement_zone_are_not_reachable(tmp_path):
    """11.04 AFTER MOVING « cannot be engaged with … enemy units that are not charge targets » :
    les seules cases à ≤ 1" de la cible sont dans l'ER de la non-cible 102 — le moteur les
    refuse (`_hex_legal_for_charge`), la charge finit légalement à 2" (engagée). ROUGE avant :
    le contrôle comptait `charge_no_contact` sur cette charge légale."""
    stats = parse(tmp_path, HEADERS + unit_header("102", 2), SETUP + _charged_with_bystander((10, 8)))
    assert stats["charge_no_contact"][1] == 0, stats["first_error_lines"]["charge_no_contact"][1]
    assert stats["rule_usage"]["PROJ.1.3.contact"][1] == 1, "occasion jugée, verdict conforme"


def test_a_far_bystander_does_not_excuse_stopping_short(tmp_path):
    """Non-cible hors de portée : le contrôle juge comme sans elle (contact atteignable)."""
    far = deployed("102", 2, [(30, 40)])
    stats = parse(tmp_path, HEADERS + unit_header("102", 2), SETUP + far + _charged((10, 8)))
    assert stats["charge_no_contact"][1] == 1
