"""HEAVY au TIR dans le chemin VIF (_manual_roll_intent).

Regle d arme PROJET (config/weapon_rules.json, source de verite du moteur) :
« Add 1 to Hit rolls if the bearer Remained Stationary this turn. » Portee du code MORT
(_attack_sequence_rng) vers le chemin VIF partage gym/PvP.

+1 au jet de touche = seuil BS ameliore de 1 (plancher 2). « Remained stationary » =
escouade absente de units_moved ET units_advanced.

ECART PDF ASSUME : la def projet est plus simple que le PDF 24.16 (pas de clause
« unengaged » / « set up this turn » / « moved <= 3\" ») — on suit la config, comme pour les
regles unit_rules.json. Cf. §9.2.1.

Discrimination verrouillee (contre-epreuve mutation : neutraliser `bs = max(2, bs-1)` => rouge) :
- HEAVY + stationnaire        -> BS ameliore (4 -> 3)
- HEAVY + a bouge (units_moved)    -> pas de bonus (4)
- HEAVY + a advance (units_advanced) -> pas de bonus (4)
- sans HEAVY + stationnaire    -> pas de bonus (4)
"""
import random

import pytest

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import _manual_roll_intent


def _neutralise(monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})


def _game_state(weapon_rules, *, moved=False, advanced=False):
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
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": []}, "2": {"id": "2", "UNIT_RULES": []}},
        "objectives": [],
        "units_moved": {"1"} if moved else set(),
        "units_advanced": {"1"} if advanced else set(),
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return gs, intent


def test_heavy_stationnaire_ameliore_le_seuil(monkeypatch):
    """HEAVY + stationnaire -> BS 4 ameliore a 3."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"])
    result = _manual_roll_intent(gs, intent, {})
    assert result["bs"] == 3


@pytest.mark.parametrize("moved,advanced", [(True, False), (False, True)])
def test_heavy_apres_mouvement_pas_de_bonus(monkeypatch, moved, advanced):
    """HEAVY mais a bouge OU advance -> pas de bonus (BS reste 4)."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"], moved=moved, advanced=advanced)
    result = _manual_roll_intent(gs, intent, {})
    assert result["bs"] == 4


def test_sans_heavy_pas_de_bonus(monkeypatch):
    """Sans HEAVY, meme stationnaire -> BS reste 4 (contre-epreuve fonctionnelle)."""
    _neutralise(monkeypatch)
    gs, intent = _game_state([])
    result = _manual_roll_intent(gs, intent, {})
    assert result["bs"] == 4
