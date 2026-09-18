"""PROJ.1.4.pile_in_engage — 12.03 WHILE MOVING « each model that is moved must end its move
closer to the closest pile-in target, and engaged with it if possible ».

Les contrôles pile-in existants ne jugeaient que le dépassement de 3" et le double pile-in ;
une figurine qui s'arrête hors engagement alors qu'une case engagée était libre et atteignable
passait inaperçue (mesure bot contre bot du 2026-09-18 : 100 figurines sur 762 hors engagement
après pile-in, moteur 5b2422dd5).

Géométrie x1 : S à (10,6), E à (10,10) — 4 cases ; budget 3 ; (10,8) est à 2 (engagée).
"""

from __future__ import annotations

from engine.combat_utils import calculate_hex_distance
from tests.unit.ai._melee_lot_fabrique import deployed, models_segment, parse, unit_header

START = (10, 6)
ENEMY = (10, 10)
HEADERS = unit_header("1", 1) + unit_header("101", 2)
SETUP = deployed("1", 1, [START]) + deployed("101", 2, [ENEMY])


def _piled_in(dest, targets: str = " [targets: 101]") -> str:
    return (
        f"[10:00:03] E1 T1 P1 FIGHT : Unit 1({START[0]},{START[1]}) PILED IN from ({START[0]},{START[1]})"
        f" to ({dest[0]},{dest[1]}){targets} [R:+0.0] {models_segment('1', [dest])} [SUCCESS]\n"
    )


def test_geometry_premise():
    assert calculate_hex_distance(*START, *ENEMY) == 4
    assert calculate_hex_distance(10, 7, *ENEMY) == 3 and calculate_hex_distance(10, 8, *ENEMY) == 2


def test_stopping_one_cell_short_of_engagement_is_an_error(tmp_path):
    """Arrivée à 3 cases (hors EZ 2) alors que (10,8) était libre et atteignable → 1 erreur."""
    stats = parse(tmp_path, HEADERS, SETUP + _piled_in((10, 7)))
    assert stats["fight_pile_in_no_engage"][1] == 1
    first = stats["first_error_lines"]["fight_pile_in_no_engage"][1]
    assert first is not None and first["model"] == "1#0" and calculate_hex_distance(*first["engaging_cell"], *ENEMY) <= 2
    assert stats["rule_usage"]["PROJ.1.4.pile_in_engage"][1] == 1
    assert stats["fight_move_invalid"]["pile_in"][1] == 0, "le budget 3\" est respecté"


def test_ending_engaged_is_no_error(tmp_path):
    stats = parse(tmp_path, HEADERS, SETUP + _piled_in((10, 8)))
    assert stats["fight_pile_in_no_engage"][1] == 0
    assert stats["rule_usage"]["PROJ.1.4.pile_in_engage"][1] == 1


def test_no_engaging_cell_reachable_is_no_error(tmp_path):
    """E à 6 cases : aucune case engagée à 3 pas → avancer de 3 sans engager est légal."""
    far_enemy = (10, 12)
    assert calculate_hex_distance(*START, *far_enemy) == 6
    body = deployed("1", 1, [START]) + deployed("101", 2, [far_enemy]) + _piled_in((10, 9))
    stats = parse(tmp_path, HEADERS, body)
    assert stats["fight_pile_in_no_engage"][1] == 0
    assert stats["rule_usage"]["PROJ.1.4.pile_in_engage"][1] == 1


def test_without_targets_token_the_closest_living_enemy_is_the_target(tmp_path):
    """Journal sans `[targets:]` (chemin PvP) : cibles = ennemis vivants, même verdict."""
    stats = parse(tmp_path, HEADERS, SETUP + _piled_in((10, 7), targets=""))
    assert stats["fight_pile_in_no_engage"][1] == 1
