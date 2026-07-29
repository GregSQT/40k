"""[MELTA X] 24.25 au TIR dans le chemin VIF (resolution complete, gym auto).

PDF 24.25 : « Each time a model makes an attack with a [MELTA] weapon, if the target unit was
within half range of that weapon in the Select Targets step, until the attacking unit's attacks
have been resolved, add X to that weapon's D characteristic. »

Le bonus porte sur la CARACTERISTIQUE D : il s ajoute APRES le tirage du de de degats (D6+2),
pas en degats forfaitaires. Test BOUT-EN-BOUT via `build_manual_shoot_allocation` : verrouille
les trois points du cablage (mesure de demi-portee dans `_manual_roll_intent` -> `dmg_bonus`
propage dans le groupe d armes -> ajoute dans `_resolve_one_manual_wound`).

Positions extremes (cible collee vs tres loin) : le sens de l inegalite ne depend d aucune
conversion subhex.
"""
import random

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation
from tests._state_invariants import turn_state_invariants


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(shooting_handlers, "_ranged_distance_metric", lambda *args, **kwargs: "euclidean")


def _uc(col, row, *, player):
    return {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": col, "row": row,
            "occupied_hexes": set(), "VALUE": 10.0, "player": player}


def _game_state(weapon_rules, *, target_row):
    """Tireur '1' en (0,0), arme RNG 24 (demi-portee 12) DMG 1. Cible '2' HP 5, Sv 7 (aucune)."""
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
              "WEAPON_RULES": weapon_rules, "display_name": "Melta"}
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                "col": 0, "row": 0, "RNG_WEAPONS": [weapon]}
    target = {"id": "T1", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 5, "HP_MAX": 5,
              "ARMOR_SAVE": 7, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
              "points_per_hp": 5.0, "VALUE": 10.0, "col": 0, "row": target_row}
    return {**turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, "T1": target},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(0, target_row, player=1)},
        "units": [{"id": "1", "player": 0}, {"id": "2", "player": 1}],
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": []}, "2": {"id": "2", "UNIT_RULES": []}},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "pending_squad_shoot_intents": {
            "1": [{"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}]
        },
    }


def test_melta_dans_demi_portee_ajoute_x_aux_degats(monkeypatch):
    """MELTA:2 a demi-portee : DMG 1 -> 3 degats (5 PV - 3 = 2)."""
    _seq(monkeypatch, [4, 5, 1])  # touche 4, blessure 5, sauvegarde 1 (ratee)
    gs = _game_state(["MELTA:2"], target_row=1)

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 2


def test_melta_hors_demi_portee_pas_de_bonus(monkeypatch):
    """MELTA:2 hors demi-portee : DMG 1 -> 1 degat (discrimination de la demi-portee)."""
    _seq(monkeypatch, [4, 5, 1])
    gs = _game_state(["MELTA:2"], target_row=100)

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 4


def test_sans_melta_pas_de_bonus(monkeypatch):
    """Sans MELTA, cible collee : 1 degat (contre-epreuve fonctionnelle)."""
    _seq(monkeypatch, [4, 5, 1])
    gs = _game_state([], target_row=1)

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 4
