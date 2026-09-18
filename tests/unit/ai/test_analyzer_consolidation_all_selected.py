"""PROJ.1.4.conso_toutes_selectionnees — 12.08 AFTER MOVING, Engaging : « Your unit must be
engaged with all of the selected enemy units ».

Le contrôle « Conso au-delà de 3" » ne juge que le budget. Depuis A3 (2026-09-18) la ligne
`CONSOLIDATED … [ENGAGING] [targets: a,b]` porte la sélection réelle : chaque cible sélectionnée
doit être engagée à l'arrivée.

Géométrie x1 : S à (10,10), E1 à (10,13) et E2 à (10,7) (3 cases de part et d'autre) ; l'arrivée
(10,11) engage E1 (distance 2) mais pas E2 (distance 4).
"""

from __future__ import annotations

from engine.combat_utils import calculate_hex_distance
from tests.unit.ai._melee_lot_fabrique import deployed, models_segment, parse, unit_header

START = (10, 10)
E1 = (10, 13)
E2 = (10, 7)
HEADERS = unit_header("1", 1) + unit_header("101", 2) + unit_header("102", 2)
SETUP = deployed("1", 1, [START]) + deployed("101", 2, [E1]) + deployed("102", 2, [E2])


def _consolidated(dest, tokens: str) -> str:
    return (
        f"[10:00:04] E1 T1 P1 FIGHT : Unit 1({START[0]},{START[1]}) CONSOLIDATED from ({START[0]},{START[1]})"
        f" to ({dest[0]},{dest[1]}){tokens} [R:+0.0] {models_segment('1', [dest])} [SUCCESS]\n"
    )


def test_geometry_premise():
    assert calculate_hex_distance(10, 11, *E1) == 2 and calculate_hex_distance(10, 11, *E2) == 4


def test_a_selected_target_left_unengaged_is_an_error(tmp_path):
    stats = parse(tmp_path, HEADERS, SETUP + _consolidated((10, 11), " [ENGAGING] [targets: 101,102]"))
    assert stats["fight_consolidation_not_all_selected"][1] == 1
    first = stats["first_error_lines"]["fight_consolidation_not_all_selected"][1]
    assert first is not None and first["not_engaged"] == ["102"], first
    assert stats["rule_usage"]["PROJ.1.4.conso_toutes_selectionnees"][1] == 1


def test_every_selected_target_engaged_is_no_error(tmp_path):
    stats = parse(tmp_path, HEADERS, SETUP + _consolidated((10, 11), " [ENGAGING] [targets: 101]"))
    assert stats["fight_consolidation_not_all_selected"][1] == 0
    assert stats["rule_usage"]["PROJ.1.4.conso_toutes_selectionnees"][1] == 1


def test_ongoing_and_lines_without_targets_are_not_judged(tmp_path):
    body = (
        SETUP
        + _consolidated((10, 11), " [ONGOING] [targets: 101,102]")
        + _consolidated((10, 11), " [ENGAGING]")
    )
    stats = parse(tmp_path, HEADERS, body)
    assert stats["fight_consolidation_not_all_selected"][1] == 0
    assert stats["rule_usage"]["PROJ.1.4.conso_toutes_selectionnees"][1] == 0
