"""closest_target_penetration au TIR dans le chemin VIF (_manual_roll_intent).

Regle projet (config/unit_rules.json) : « When this unit makes a shooting attack at the
closest eligible unit, add 1 to the weapon's penetration. » Portee du code MORT
(_attack_sequence_rng, shooting_handlers) vers le chemin VIF partage gym/PvP.

Convention AP NEGATIF (cf. save_threshold) : +1 penetration => ap -= 1 => save degradee.

Ces tests passent par `_manual_roll_intent` (vrai `get_unit_by_id`, vrai
`_unit_has_rule_effect`, vraie mesure `ranged_edge_distance`) : ils verrouillent le CABLAGE
(regle presente ET cible = la plus proche), pas un helper isole. Le pool d eligibles est
monkeypatche (evite de monter LoS/portee) mais la determination « la plus proche » est
mesuree pour de vrai sur des `units_cache` positionnes.

Discrimination verrouillee : effet UNIQUEMENT si (regle presente) ET (cible = plus proche).
- cible = la plus proche + regle  -> AP+1 (contre-epreuve mutation : neutraliser `ap -= 1` => rouge)
- cible = PLUS LOINTAINE + regle   -> pas d effet (test « closest »)
- cible = la plus proche SANS regle -> pas d effet (contre-epreuve fonctionnelle)
"""
import random

from engine.phase_handlers import shooting_handlers
from tests.unit.engine._roll_helpers import roll_shoot_intent


def _neutralise_rng_and_cover(monkeypatch):
    """random.randint constant (les assertions portent sur ap/save_th, calcules AVANT les
    jets) + neutralisation du cover (hors sujet) + pool d eligibles force."""
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    # Metrique de distance forcee euclidienne (bases rondes) : test independant de game_config.
    monkeypatch.setattr(shooting_handlers, "_ranged_distance_metric", lambda: "euclidean")
    # Pool d eligibles = les deux escouades ennemies (evite LoS/portee reelles).
    monkeypatch.setattr(shooting_handlers, "shooting_build_valid_target_pool", lambda gs, sid: ["2", "3"])


def _uc_entry(col, row, *, value=10.0, player=1):
    """Entree units_cache minimale pour socle_from_cache_entry (base ronde) + targets_meta."""
    return {
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "col": col, "row": row,
        "occupied_hexes": set(), "VALUE": value, "player": player,
    }


def _game_state(unit_rules):
    """1 tireur (escouade '1' en (0,0)) ; cible '2' PROCHE en (0,3), cible '3' LOINTAINE en (0,10).
    Arme AP=-1 (=> save_th 4+ sur Sv3), pas de regle d arme speciale."""
    weapon = {"BS": 3, "STR": 4, "AP": -1, "DMG": 1, "NB": 1, "WEAPON_RULES": [], "display_name": "Gun"}
    attacker = {"id": "A1", "squad_id": "1", "T": 4, "player": 0, "RNG_WEAPONS": [weapon]}
    attacker_unit = {"id": "1", "UNIT_RULES": unit_rules}

    def _target_model(mid):
        return {"id": mid, "T": 4, "HP_CUR": 2, "HP_MAX": 2, "ARMOR_SAVE": 3,
                "INVUL_SAVE": 7, "role": None, "unitType": "Grunt", "player": 1}

    game_state = {
        "models_cache": {"A1": attacker, "T2": _target_model("T2"), "T3": _target_model("T3")},
        "squad_models": {"2": ["T2"], "3": ["T3"]},
        "squad_cache": {"2": {"model_count_at_start": 1}, "3": {"model_count_at_start": 1}},
        "units_cache": {
            "1": _uc_entry(0, 0, player=0),
            "2": _uc_entry(0, 3),
            "3": _uc_entry(0, 10),
        },
        "unit_by_id": {"1": attacker_unit, "2": {"id": "2", "UNIT_RULES": []}, "3": {"id": "3", "UNIT_RULES": []}},
        "objectives": [],
    }
    return game_state, weapon


def _intent(target_sid):
    return {"model_id": "A1", "target_unit_id": target_sid, "weapon_index": 0, "n_attacks_resolved": 1}


def test_ap_ameliore_sur_la_cible_la_plus_proche(monkeypatch):
    """Regle presente + cible = la plus proche ('2') -> AP -1 => -2, save_th 3-(-2)=5."""
    _neutralise_rng_and_cover(monkeypatch)
    gs, _ = _game_state([{"ruleId": "closest_target_penetration"}])

    result = roll_shoot_intent(gs, _intent("2"))

    assert result["ap"] == -2, "AP+1 penetration attendu sur la cible la plus proche"
    assert result["display_save_th"] == 5


def test_pas_d_effet_sur_une_cible_plus_lointaine(monkeypatch):
    """Regle presente mais cible = la PLUS LOINTAINE ('3') -> AP inchange (-1), save_th 4."""
    _neutralise_rng_and_cover(monkeypatch)
    gs, _ = _game_state([{"ruleId": "closest_target_penetration"}])

    result = roll_shoot_intent(gs, _intent("3"))

    assert result["ap"] == -1, "seule la cible la plus proche beneficie du bonus"
    assert result["display_save_th"] == 4


def test_pas_d_effet_sans_la_regle(monkeypatch):
    """Sans la regle, meme sur la cible la plus proche ('2') -> AP inchange (-1), save_th 4."""
    _neutralise_rng_and_cover(monkeypatch)
    gs, _ = _game_state([])

    result = roll_shoot_intent(gs, _intent("2"))

    assert result["ap"] == -1
    assert result["display_save_th"] == 4
