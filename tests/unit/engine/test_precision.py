"""[PRECISION] 24.28 — l'attaquant impose un groupe CHARACTER comme groupe d'allocation courant.

PDF 24.28 : « While resolving attacks made with one or more [PRECISION] weapons, at the start of
the Allocation Order step (05.03), if the target unit contains one or more CHARACTER models
visible to one or more of the attacking models, the active player can select one allocation
group that contains one of those visible CHARACTER models. If they do, until those attacks are
resolved, or until that CHARACTER group is destroyed, that CHARACTER group is the current
allocation group. »

Sans PRECISION, 05.03 impose l'inverse : « No CHARACTER group can be earlier in the allocation
order than a non-CHARACTER group » — le character est donc intouchable tant que l'escouade vit.
C'est exactement la discrimination testée ici.

Concernées dans les rosters de training : `urty_syringe` (PainBoy), `eadbanger` (WeirdBoy).
Test BOUT-EN-BOUT en mêlée via `build_manual_fight_allocation` (gym auto).
"""
import random

from engine.phase_handlers.fight_handlers import build_manual_fight_allocation
from tests._state_invariants import turn_state_invariants


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)


def _game_state(weapon_rules):
    """Attaquant '1' vs escouade '2' = 1 grunt + 1 leader (2 groupes d'allocation 05.03)."""
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
              "WEAPON_RULES": list(weapon_rules), "display_name": "Syringe"}
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "ATTACK_LEFT": 1,
                "col": 0, "row": 0, "CC_WEAPONS": [weapon]}
    grunt = {"id": "T1", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 2, "HP_MAX": 2,
             "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
             "points_per_hp": 5.0, "VALUE": 10.0, "col": 1, "row": 0}
    leader = {"id": "T2", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 4, "HP_MAX": 4,
              "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": "leader", "unitType": "Boss",
              "points_per_hp": 20.0, "VALUE": 80.0, "col": 1, "row": 1}
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0,
              "n_attacks_resolved": 1, "target_squad_size_at_declaration": 2}
    return {**turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "fight",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, "T1": grunt, "T2": leader},
        "squad_models": {"1": ["A1"], "2": ["T1", "T2"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 2}},
        "units_cache": {"1": {"VALUE": 10.0, "player": 0, "col": 0, "row": 0},
                        "2": {"VALUE": 90.0, "player": 1, "col": 1, "row": 0}},
        "units": [{"id": "1", "player": 0}, {"id": "2", "player": 1}],
        "unit_by_id": {"1": {"id": "1", "player": 0, "UNIT_RULES": [], "UNIT_KEYWORDS": []},
                       "2": {"id": "2", "player": 1, "UNIT_RULES": [], "UNIT_KEYWORDS": []}},
        "objectives": [],
        "pending_squad_fight_intents": {"1": [intent]},
        "pending_squad_shoot_intents": {},
    }


def test_precision_frappe_le_character(monkeypatch):
    """24.28 : la blessure va sur le leader, alors que 05.03 le protégerait."""
    _seq(monkeypatch, [4, 5, 1])  # touche, blessure, sauvegarde ratée
    gs = _game_state(["PRECISION"])

    build_manual_fight_allocation(gs, "1")

    assert gs["models_cache"]["T2"]["HP_CUR"] == 3, "le CHARACTER doit encaisser la blessure"
    assert gs["models_cache"]["T1"]["HP_CUR"] == 2, "le grunt ne doit rien encaisser"


def test_sans_precision_le_character_est_protege(monkeypatch):
    """Contre-épreuve 05.03 : sans PRECISION, la blessure va sur le groupe non-CHARACTER."""
    _seq(monkeypatch, [4, 5, 1])
    gs = _game_state([])

    build_manual_fight_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 1, "le grunt doit encaisser"
    assert gs["models_cache"]["T2"]["HP_CUR"] == 4, "le CHARACTER reste intact"


def test_precision_sans_character_dans_la_cible(monkeypatch):
    """24.28 sans CHARACTER visible : aucun override, l'allocation reste normale."""
    _seq(monkeypatch, [4, 5, 1])
    gs = _game_state(["PRECISION"])
    gs["models_cache"]["T2"]["role"] = None  # plus aucun CHARACTER dans la cible

    build_manual_fight_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] + gs["models_cache"]["T2"]["HP_CUR"] == 5


def test_precision_choisit_le_character_le_plus_cher(monkeypatch):
    """Arbitrage du « can select » : parmi plusieurs groupes CHARACTER, le plus coûteux."""
    _seq(monkeypatch, [4, 5, 1])
    gs = _game_state(["PRECISION"])
    gs["models_cache"]["T3"] = {
        "id": "T3", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 6, "HP_MAX": 6,
        "ARMOR_SAVE": 2, "INVUL_SAVE": 7, "role": "support", "unitType": "Warlord",
        "points_per_hp": 30.0, "VALUE": 180.0, "col": 2, "row": 1,
    }
    gs["squad_models"]["2"].append("T3")

    build_manual_fight_allocation(gs, "1")

    assert gs["models_cache"]["T3"]["HP_CUR"] == 5, "le CHARACTER le plus cher est visé"
    assert gs["models_cache"]["T2"]["HP_CUR"] == 4
