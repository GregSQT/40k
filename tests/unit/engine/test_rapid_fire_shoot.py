"""RAPID_FIRE au TIR dans le chemin VIF (_manual_roll_intent).

Regle d arme PROJET (config/weapon_rules.json ; PDF 24.30) : « Increase this weapon's
Attacks by X when target unit is within half range. » Portee du code MORT vers le vif.

X vient du parametre de la regle ('RAPID_FIRE:X'), extrait par weapon_rule_parameter.
Demi-portee = RNG/2 (RNG deja en subhexes). Distance escouade->escouade via le selecteur
`ranged` (meme convention que le gate de portee du moteur et que closest_target_penetration).

Positions EXTREMES (cible quasi-collee vs tres loin) pour un test robuste, independant des
conversions subhex : le sens de l inegalite ne fait aucun doute.

Discrimination (contre-epreuve mutation : neutraliser `n_attacks += _rf_x` => rouge) :
- RAPID_FIRE:2 + cible dans la demi-portee -> 1 + 2 = 3 attaques
- RAPID_FIRE:2 + cible hors demi-portee    -> 1 attaque
- sans RAPID_FIRE + cible proche           -> 1 attaque
"""
import random

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import _manual_roll_intent


def _neutralise(monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(shooting_handlers, "_ranged_distance_metric", lambda: "euclidean")


def _uc(col, row, *, value=10.0, player=1):
    return {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": col, "row": row,
            "occupied_hexes": set(), "VALUE": value, "player": player}


def _game_state(weapon_rules, *, target_row):
    """Tireur escouade '1' en (0,0), RNG=24 subhex (demi-portee 12). Cible '2' en (0,target_row)."""
    weapon = {"BS": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
              "WEAPON_RULES": weapon_rules, "display_name": "Gun"}
    attacker = {"id": "A1", "squad_id": "1", "T": 4, "player": 0, "RNG_WEAPONS": [weapon]}
    target_model = {"id": "T1", "T": 4, "HP_CUR": 2, "HP_MAX": 2, "ARMOR_SAVE": 3,
                    "INVUL_SAVE": 7, "role": None, "unitType": "Grunt", "player": 1}
    gs = {
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(0, target_row)},
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": []}, "2": {"id": "2", "UNIT_RULES": []}},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return gs, intent


def test_rapid_fire_dans_demi_portee_ajoute_x(monkeypatch):
    """RAPID_FIRE:2, cible quasi-collee (dans la demi-portee) -> 1 + 2 = 3 attaques."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["RAPID_FIRE:2"], target_row=1)
    result = _manual_roll_intent(gs, intent, {})
    assert result["counts"]["attacks"] == 3


def test_rapid_fire_hors_demi_portee_pas_de_bonus(monkeypatch):
    """RAPID_FIRE:2, cible tres loin (hors demi-portee) -> 1 attaque."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["RAPID_FIRE:2"], target_row=100)
    result = _manual_roll_intent(gs, intent, {})
    assert result["counts"]["attacks"] == 1


def test_sans_rapid_fire_pas_de_bonus(monkeypatch):
    """Sans RAPID_FIRE, cible proche -> 1 attaque (contre-epreuve fonctionnelle)."""
    _neutralise(monkeypatch)
    gs, intent = _game_state([], target_row=1)
    result = _manual_roll_intent(gs, intent, {})
    assert result["counts"]["attacks"] == 1
