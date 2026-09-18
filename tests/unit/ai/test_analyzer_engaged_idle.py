"""PROJ.1.4.engagees_inactives — une figurine engagée qui ne frappe pas est relevée.

04.01 « You must select one melee weapon that model has », 04.02 « Each target must be engaged
with the model that has that weapon », 24.11 : chaque figurine engagée sélectionne une arme et
frappe. Jusqu'au 2026-09-18 aucun contrôle ne le regardait : l'analyzer du 16/09 rendait 0 erreur
sur 10 121 combats alors que 43 % des figurines engagées frappaient (mesure bot contre bot).

Verdict par ACTIVATION, rendu en fin de lecture (`flush_engaged_idle`) : figurines engagées au
premier FOUGHT (tout ennemi, socles d'avant la ligne) moins l'union des `[SHOOTER_MODELS:]`.
"""

from __future__ import annotations

from engine.combat_utils import calculate_hex_distance
from tests.unit.ai._melee_lot_fabrique import deployed, fought, parse, unit_header

SQUAD = [(10, 10), (10, 11), (10, 12)]
ENEMY = [(11, 11)]
HEADERS = unit_header("1", 1) + unit_header("101", 2)
SETUP = deployed("1", 1, SQUAD) + deployed("101", 2, ENEMY)


def test_geometry_premise_all_three_models_are_engaged():
    assert all(calculate_hex_distance(c, r, *ENEMY[0]) <= 2 for c, r in SQUAD)


def test_one_shooter_out_of_three_engaged_is_two_idle_models(tmp_path):
    """Trois figurines engagées, une seule dans `[SHOOTER_MODELS:]` → 2 figurines relevées."""
    body = SETUP + fought("1", SQUAD[0], "101", ENEMY[0], SQUAD, ["1#0"], ENEMY)
    stats = parse(tmp_path, HEADERS, body)
    assert stats["fight_engaged_idle"][1] == 2
    assert stats["fight_engaged_idle"][2] == 0
    first = stats["first_error_lines"]["fight_engaged_idle"][1]
    assert first is not None and first["idle_models"] == ["1#1", "1#2"], first
    assert stats["rule_usage"]["PROJ.1.4.engagees_inactives"][1] == 1


def test_shooters_accumulate_across_the_lines_of_one_activation(tmp_path):
    """Deux lignes de la même activation (deux armes) : l'union des tireurs compte."""
    body = (
        SETUP
        + fought("1", SQUAD[0], "101", ENEMY[0], SQUAD, ["1#0", "1#1"], ENEMY)
        + fought("1", SQUAD[0], "101", ENEMY[0], SQUAD, ["1#2"], ENEMY)
    )
    stats = parse(tmp_path, HEADERS, body)
    assert stats["fight_engaged_idle"][1] == 0
    assert stats["rule_usage"]["PROJ.1.4.engagees_inactives"][1] == 1, "une activation, une occasion"


def test_all_engaged_models_striking_is_no_error(tmp_path):
    body = SETUP + fought("1", SQUAD[0], "101", ENEMY[0], SQUAD, ["1#0", "1#1", "1#2"], ENEMY)
    stats = parse(tmp_path, HEADERS, body)
    assert stats["fight_engaged_idle"][1] == 0
    assert stats["rule_usage"]["PROJ.1.4.engagees_inactives"][1] == 1


def test_a_model_out_of_engagement_is_not_expected_to_strike(tmp_path):
    """La troisième figurine à 4 cases n'est pas engagée : deux tireurs sur deux engagées → 0."""
    squad = [(10, 10), (10, 11), (10, 15)]
    assert calculate_hex_distance(10, 15, *ENEMY[0]) > 2
    body = deployed("1", 1, squad) + deployed("101", 2, ENEMY) + fought(
        "1", squad[0], "101", ENEMY[0], squad, ["1#0", "1#1"], ENEMY
    )
    stats = parse(tmp_path, HEADERS, body)
    assert stats["fight_engaged_idle"][1] == 0


def test_a_line_without_shooter_segment_is_not_judged(tmp_path):
    """Journal antérieur au segment `[SHOOTER_MODELS:]` : non jugeable, ni erreur ni occasion."""
    line = fought("1", SQUAD[0], "101", ENEMY[0], SQUAD, ["1#0"], ENEMY).replace(
        " [SHOOTER_MODELS: 1#0]", ""
    )
    stats = parse(tmp_path, HEADERS, SETUP + line)
    assert stats["fight_engaged_idle"][1] == 0
    assert stats["rule_usage"]["PROJ.1.4.engagees_inactives"][1] == 0
