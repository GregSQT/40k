"""[HEAVY] 24.16 au TIR dans le chemin VIF (_manual_roll_intent).

PDF 24.16 (source de verite, arbitrage utilisateur 2026-07-26) : « add 1 to the hit roll if ALL
of the following apply to the attacking unit : that unit is UNENGAGED ; that unit was not set up
on the battlefield this turn ; no model in that unit has moved more than 3" this turn. »

+1 au jet de touche = seuil BS ameliore de 1 (plancher 2 : un 1 non modifie rate toujours, 05.01).

Etat des trois clauses dans ce moteur :
- unengaged            : TESTE (meme predicat que le gate de tir 10.06).
- pas pose ce tour     : TESTE sur `deployed_on_turn` (0 = pre-bataille, N = arrivee de
                         reserve au tour N). Aucune arrivee en cours de bataille n existe encore
                         (reserves 20 non modelisees), mais la clause est cablee.
- aucune fig > 3"      : borne CONSERVATRICE « aucune figurine n a bouge » (units_moved /
                         units_advanced) — la distance parcourue par figurine n est pas
                         conservee par le moteur. Plus stricte que le PDF, jamais laxiste.

Discrimination verrouillee (contre-epreuve mutation : neutraliser `bs = max(2, bs-1)` => rouge) :
- HEAVY + stationnaire + unengaged   -> BS ameliore (4 -> 3)
- HEAVY + a bouge (units_moved)      -> pas de bonus (4)
- HEAVY + a advance (units_advanced) -> pas de bonus (4)
- HEAVY + stationnaire mais ENGAGE   -> pas de bonus (4)
- HEAVY + POSEE CE TOUR (arrivee de reserve) -> pas de bonus (4)
- sans HEAVY + stationnaire          -> pas de bonus (4)
"""
import random

import pytest

from engine.phase_handlers import shooting_handlers
from tests.unit.engine._roll_helpers import roll_shoot_intent


def _neutralise(monkeypatch, *, engaged=False):
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    # Clause 1 de 24.16 : « that unit is unengaged » — meme predicat que le gate de tir.
    monkeypatch.setattr(
        shooting_handlers, "_is_adjacent_to_enemy_within_cc_range", lambda gs, u: engaged
    )


def _game_state(weapon_rules, *, moved=False, advanced=False, deployed_on_turn=0):
    """1 tireur (escouade '1', BS4) + 1 cible. moved/advanced marquent l escouade."""
    weapon = {"BS": 4, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "WEAPON_RULES": weapon_rules, "display_name": "Gun"}
    attacker = {"id": "A1", "squad_id": "1", "T": 4, "player": 0, "RNG_WEAPONS": [weapon]}
    target_model = {"id": "T1", "T": 4, "HP_CUR": 2, "HP_MAX": 2, "ARMOR_SAVE": 3,
                    "INVUL_SAVE": 7, "role": None, "unitType": "Grunt", "player": 1}
    gs = {
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        "units_cache": {"2": {"col": 9, "row": 9, "VALUE": 10.0, "player": 1}},
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": [], "deployed_on_turn": deployed_on_turn},
                       "2": {"id": "2", "UNIT_RULES": [], "deployed_on_turn": 0}},
        "objectives": [], "turn": 2,
        "units_moved": {"1"} if moved else set(),
        "units_advanced": {"1"} if advanced else set(),
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return gs, intent


def test_heavy_stationnaire_ameliore_le_seuil(monkeypatch):
    """HEAVY + stationnaire -> BS 4 ameliore a 3."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"])
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 3


@pytest.mark.parametrize("moved,advanced", [(True, False), (False, True)])
def test_heavy_apres_mouvement_pas_de_bonus(monkeypatch, moved, advanced):
    """HEAVY mais a bouge OU advance -> pas de bonus (BS reste 4)."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"], moved=moved, advanced=advanced)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4


def test_heavy_engage_pas_de_bonus(monkeypatch):
    """24.16 clause 1 : stationnaire mais ENGAGE -> aucun bonus (BS reste 4)."""
    _neutralise(monkeypatch, engaged=True)
    gs, intent = _game_state(["HEAVY"])
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4


def test_heavy_pose_ce_tour_pas_de_bonus(monkeypatch):
    """24.16 clause 2 : unite arrivee de reserve CE TOUR -> aucun bonus (BS reste 4)."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"], deployed_on_turn=2)  # turn == 2 dans la fixture
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4


def test_heavy_pose_un_tour_avant_bonus_conserve(monkeypatch):
    """Discrimination : arrivee au tour PRECEDENT -> le bonus s applique."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"], deployed_on_turn=1)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 3


def test_le_log_de_tir_affiche_le_token_heavy(monkeypatch):
    """Le combat log doit montrer `Hit:X+ [HEAVY]` quand le bonus est APPLIQUE — le frontend
    y accroche le tooltip de la regle (meme mecanique que [COVER] / [HAZARD]).

    Discrimination : arme HEAVY mais unite ayant bouge -> aucun token (le bonus n a pas eu lieu).
    """
    from engine.phase_handlers.shared_utils import _emit_squad_shoot_log, SHOOT_CTX

    def _log_message(*, moved):
        _neutralise(monkeypatch)
        gs, intent = _game_state(["HEAVY"], moved=moved)
        r = roll_shoot_intent(gs, intent)
        gs.update({"units": [{"id": "1", "unitType": "Shooter"}, {"id": "2", "unitType": "Grunt"}],
                   "action_logs": [], "action_log_seq": 0, "turn": 2})
        gs["units_cache"]["1"] = {"col": 0, "row": 0}
        group = {
            "weapon_name": "Gun", "target_sid": "2", "attacker_squad_id": "1",
            "target_col": 9, "target_row": 9, "attacks": 1, "damage": 0, "kills": 0,
            "bs": r["bs"], "display_wth": r["display_wth"], "display_save_th": r["display_save_th"],
            "heavy_applied": r["heavy_applied"], "shooter_mids": ["A1"], "shots": [],
            "player": 0,
        }
        _emit_squad_shoot_log(gs, group, SHOOT_CTX)
        return gs["action_logs"][-1]["message"]

    stationnaire = _log_message(moved=False)
    apres_mouvement = _log_message(moved=True)

    assert "Hit:3+ [HEAVY]" in stationnaire, stationnaire
    assert "[HEAVY]" not in apres_mouvement, apres_mouvement


def test_sans_heavy_pas_de_bonus(monkeypatch):
    """Sans HEAVY, meme stationnaire -> BS reste 4 (contre-epreuve fonctionnelle)."""
    _neutralise(monkeypatch)
    gs, intent = _game_state([])
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4
