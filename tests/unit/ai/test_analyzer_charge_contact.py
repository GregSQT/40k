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
    assert calculate_hex_distance(*first["contact_cell"], *TARGET) == 1
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
