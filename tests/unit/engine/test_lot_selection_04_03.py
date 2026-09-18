"""04.03 RESOLVE ATTACKS — l'attaquant choisit l'ordre des lots, les dés sont jetés lot par lot.

PDF 04 Making attacks, 04.03 : « 1. Select Enemy Unit: Select one of the enemy units targeted
by one or more weapons. 2. Gather Attack Dice: Select one weapon targeting that unit that has
not yet been used to make attacks against it […] 4. Other Attacks: If there are any weapons
targeting the same unit that have not yet been used to make attacks, return to the Gather
Attack Dice step. Otherwise, if there are any weapons with unresolved attacks targeting a
different unit, return to the Select Enemy Unit step. »

Décision utilisateur du 2026-09-18 (option B) : la question n'est posée qu'à un attaquant
HUMAIN, et seulement s'il y a un vrai choix (≥ 2 unités désignées restantes, ou ≥ 2 profils sur
l'unité en cours) ; un attaquant programmatique prend l'ordre de déclaration. Les dés d'un lot
sont jetés au début de ce lot, jamais avant (aucune information anticipée).

Chaque test scripte les dés : `random.randint` lève si un dé est tiré là où la règle n'en
attend aucun.
"""
import random
from typing import Any, Dict, List

import pytest

from engine.constants import PENDING_SHOOT_ALLOCATION_KEY
from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import (
    SHOOT_CTX,
    build_manual_shoot_allocation,
    manual_allocation_waiting_payload,
    select_attack_lot,
)
from tests._state_invariants import turn_state_invariants
from tests.unit.engine._state_builders import units_cache_entry as _uc


def _kw(*names):
    return [{"keywordId": n} for n in names]


def _weapon(code: str, *, strength: int = 4, rules=()) -> Dict[str, Any]:
    return {"ATK": 3, "STR": strength, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": list(rules), "code": code, "display_name": code.upper()}


def _target_model(mid: str, squad: str, *, hp: int = 3, col: int = 9) -> Dict[str, Any]:
    return {"id": mid, "squad_id": squad, "player": 1, "T": 4, "HP_CUR": hp, "HP_MAX": hp,
            "ARMOR_SAVE": 7, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
            "points_per_hp": 5.0, "VALUE": 10.0, "col": col, "row": 9,
            "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": []}


def _game_state(weapons: List[Dict[str, Any]], intents: List[Dict[str, Any]],
                *, attacker_human: bool = True, target_models: int = 1) -> Dict[str, Any]:
    """Un tireur (escouade 1, joueur 0) portant `weapons` ; cibles 2 et 3 (joueur 1, humain)."""
    shooter = {"id": "A0", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
               "HP_CUR": 2, "HP_MAX": 2, "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None,
               "unitType": "Shooter", "points_per_hp": 5.0, "VALUE": 10.0,
               "col": 0, "row": 0, "UNIT_KEYWORDS": _kw("INFANTRY"), "RNG_WEAPONS": list(weapons),
               "UNIT_RULES": []}
    models = {"A0": shooter}
    squad_models = {"1": ["A0"], "2": [], "3": []}
    for sid, base_col in (("2", 9), ("3", 20)):
        for i in range(target_models):
            mid = f"T{sid}_{i}"
            models[mid] = _target_model(mid, sid, col=base_col + i)
            squad_models[sid].append(mid)
    units = [{"id": "1", "player": 0, "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": []},
             {"id": "2", "player": 1, "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": []},
             {"id": "3", "player": 1, "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": []}]
    return {
        **turn_state_invariants(),
        "gym_training_mode": False,
        "player_types": {"0": "human" if attacker_human else "ai", "1": "human"},
        "config": {"game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                                  "precision_mortal_wounds_to_character": False}},
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": models,
        "squad_models": squad_models,
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": target_models},
                        "3": {"model_count_at_start": target_models}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(9, 9, player=1), "3": _uc(20, 9, player=1)},
        "units": units,
        "unit_by_id": {u["id"]: u for u in units},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        # Exiges par la cascade de `destroy_model` quand une escouade entiere disparait.
        "board_cols": 44, "board_rows": 60, "wall_hexes": set(), "_unit_move_version": 0,
        "pending_squad_shoot_intents": {"1": intents},
    }


def _intent(weapon_index: int, target: str) -> Dict[str, Any]:
    return {"model_id": "A0", "target_unit_id": target, "weapon_index": weapon_index,
            "n_attacks_resolved": 1, "target_squad_size_at_declaration": 1}


def _dice(monkeypatch, rolls):
    """Dés scriptés ; un dé tiré au-delà de la liste est une erreur (aucun jet anticipé)."""
    seq = list(rolls)

    def fake(a, b):
        assert seq, "un dé a été jeté là où la règle n'en attend aucun"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    return seq


def _lots(payload):
    return [(lot["lot_id"], lot["target_unit_id"], lot["weapon_name"]) for lot in payload["lot_request"]["lots"]]


# --------------------------------------------------------------------- deux cibles, deux armes

def test_deux_cibles_l_attaquant_humain_choisit_sans_qu_aucun_de_ne_soit_jete(monkeypatch):
    seq = _dice(monkeypatch, [])
    gs = _game_state([_weapon("gun_a"), _weapon("gun_b", strength=5)],
                     [_intent(0, "2"), _intent(1, "3")])

    payload = build_manual_shoot_allocation(gs, "1")

    assert payload["waiting_for_player"] is True
    assert payload["action"] == "squad_shoot_select_lot"
    assert payload["lot_request"]["locked_target_unit_id"] is None
    assert payload["lot_request"]["policy_only"] is False
    assert _lots(payload) == [(0, "2", "GUN_A"), (1, "3", "GUN_B")]
    assert seq == [], "aucun dé n'a été consommé"
    alloc = gs[PENDING_SHOOT_ALLOCATION_KEY]
    assert all(not b["rolled"] and b["pool"] == [] for b in alloc["batches"])
    # Le garde-fou re-signale la même attente sans muter.
    assert manual_allocation_waiting_payload(gs, SHOOT_CTX)["lot_request"]["lots"] == payload["lot_request"]["lots"]


def test_le_lot_choisi_est_jete_en_premier_puis_le_dernier_lot_va_seul(monkeypatch):
    """Lot 1 (gun_b → 3) choisi : ses dés partent d'abord ; le lot 0, seul restant, s'enchaîne
    sans question (candidat unique) ; la cible mono-figurine encaisse sans question (05.04)."""
    # gun_b : touche 6, blessure 6, save 1 ; puis gun_a : touche 2 (raté).
    _dice(monkeypatch, [6, 6, 1, 2])
    gs = _game_state([_weapon("gun_a"), _weapon("gun_b", strength=5)],
                     [_intent(0, "2"), _intent(1, "3")])
    build_manual_shoot_allocation(gs, "1")

    result = select_attack_lot(gs, SHOOT_CTX, 1)

    assert result["done"] is True
    assert result["shoot_result"]["lot_order"] == ["GUN_B", "GUN_A"]
    assert gs["models_cache"]["T3_0"]["HP_CUR"] == 2, "gun_b a blessé la cible 3 avec les premiers dés"
    assert gs["models_cache"]["T2_0"]["HP_CUR"] == 3, "gun_a a raté (dernier dé)"
    assert PENDING_SHOOT_ALLOCATION_KEY not in gs


def test_un_lot_non_candidat_est_refuse_sans_mutation(monkeypatch):
    seq = _dice(monkeypatch, [])
    gs = _game_state([_weapon("gun_a"), _weapon("gun_b", strength=5)],
                     [_intent(0, "2"), _intent(1, "3")])
    build_manual_shoot_allocation(gs, "1")

    with pytest.raises(ValueError) as exc:
        select_attack_lot(gs, SHOOT_CTX, 7)

    assert "7" in str(exc.value) and "candidats" in str(exc.value)
    assert seq == []
    assert gs[PENDING_SHOOT_ALLOCATION_KEY]["lot_choice"] is None


# ---------------------------------------------------------- une cible, deux profils (04.03 §2)

def test_meme_cible_deux_profils_le_choix_porte_sur_le_profil(monkeypatch):
    _dice(monkeypatch, [])
    gs = _game_state([_weapon("gun_a"), _weapon("gun_b", strength=5)],
                     [_intent(0, "2"), _intent(1, "2")])

    payload = build_manual_shoot_allocation(gs, "1")

    assert payload["action"] == "squad_shoot_select_lot"
    assert _lots(payload) == [(0, "2", "GUN_A"), (1, "2", "GUN_B")]


# ------------------------------------------------- cible verrouillée tant qu'il lui reste un lot

def test_toutes_les_armes_d_une_cible_avant_la_suivante(monkeypatch):
    """A→2, B→3, C→2 : après A (cible 2), le seul candidat est C (cible 2 verrouillée) ; B
    ne vient qu'ensuite. Aucune question n'est posée pour C ni pour B (candidat unique)."""
    # A : 2,  C : 2,  B : 2 — trois touches ratées, un dé par lot.
    seq = _dice(monkeypatch, [2, 2, 2])
    gs = _game_state([_weapon("gun_a"), _weapon("gun_b", strength=5), _weapon("gun_c", strength=6)],
                     [_intent(0, "2"), _intent(1, "3"), _intent(2, "2")])
    payload = build_manual_shoot_allocation(gs, "1")
    # Identites de lot = ordre de construction (cibles par premiere apparition, puis profils).
    assert _lots(payload) == [(0, "2", "GUN_A"), (1, "2", "GUN_C"), (2, "3", "GUN_B")]

    result = select_attack_lot(gs, SHOOT_CTX, 0)

    assert result["done"] is True and seq == []
    assert result["shoot_result"]["lot_order"] == ["GUN_A", "GUN_C", "GUN_B"]


def test_cible_verrouillee_apres_un_lot_choisi_parmi_plusieurs(monkeypatch):
    """A→2, B→3, C→2 : l'attaquant choisit B (cible 3). Il ne reste que des lots sur 2 :
    A et C sont proposés (deux profils), puis le dernier va seul."""
    seq = _dice(monkeypatch, [2, 2, 2])
    gs = _game_state([_weapon("gun_a"), _weapon("gun_b", strength=5), _weapon("gun_c", strength=6)],
                     [_intent(0, "2"), _intent(1, "3"), _intent(2, "2")])
    build_manual_shoot_allocation(gs, "1")

    second = select_attack_lot(gs, SHOOT_CTX, 2)  # lot 2 = GUN_B -> cible 3

    assert second["action"] == "squad_shoot_select_lot"
    assert second["lot_request"]["locked_target_unit_id"] is None
    assert _lots(second) == [(0, "2", "GUN_A"), (1, "2", "GUN_C")]
    result = select_attack_lot(gs, SHOOT_CTX, 1)
    assert result["done"] is True and seq == []
    assert result["shoot_result"]["lot_order"] == ["GUN_B", "GUN_C", "GUN_A"]


# ------------------------------------------------------------- attaquant programmatique

def test_attaquant_programmatique_ordre_de_declaration_sans_question(monkeypatch):
    seq = _dice(monkeypatch, [2, 2])
    gs = _game_state([_weapon("gun_a"), _weapon("gun_b", strength=5)],
                     [_intent(1, "3"), _intent(0, "2")], attacker_human=False)

    result = build_manual_shoot_allocation(gs, "1")

    assert result["done"] is True and seq == []
    assert result["shoot_result"]["lot_order"] == ["GUN_B", "GUN_A"]


# ------------------------------------------------------- politique de relance, par lot

def test_question_de_relance_posee_seulement_quand_elle_a_un_sens(monkeypatch):
    """[TWIN-LINKED] + [DEVASTATING WOUNDS] sur un lot unique : lot imposé, mais la politique
    de relance est demandée (policy_only). Réponse « tous les non-critiques » : la blessure 5
    est relancée, le 6 obtenu est critique → blessure mortelle sans sauvegarde."""
    seq = _dice(monkeypatch, [4, 5, 6])
    gs = _game_state([_weapon("gun_a", rules=("TWIN_LINKED", "DEVASTATING_WOUNDS"))],
                     [_intent(0, "2")])

    payload = build_manual_shoot_allocation(gs, "1")

    assert payload["action"] == "squad_shoot_select_lot"
    assert payload["lot_request"]["policy_only"] is True
    assert payload["lot_request"]["lots"][0]["reroll_choices"] == {"hit": False, "wound": True}
    assert seq == [4, 5, 6], "rien n'est jeté avant la réponse"

    result = select_attack_lot(gs, SHOOT_CTX, 0, hit_non_crit=False, wound_non_crit=True)

    assert result["done"] is True and seq == []
    assert gs["models_cache"]["T2_0"]["HP_CUR"] == 2
    rec = result["shoot_result"]["events"][0]
    assert rec["damage"] == 1


def test_sans_regle_sur_critique_aucune_question_de_relance(monkeypatch):
    """[TWIN-LINKED] seul : « échecs seulement » domine, le lot unique part sans question."""
    seq = _dice(monkeypatch, [4, 5, 3])  # touche, blessure 5 (réussie, non relancée), save 3
    gs = _game_state([_weapon("gun_a", rules=("TWIN_LINKED",))], [_intent(0, "2")])

    result = build_manual_shoot_allocation(gs, "1")

    assert result["done"] is True and seq == []


# ------------------------------------------------------------- cible détruite entre deux lots

def test_un_lot_sur_une_cible_deja_detruite_ne_jette_aucun_de(monkeypatch):
    """A→2 tue la cible 2 (1 PV) ; le lot C→2 n'est pas joué (04.03 : plus d'unité à attaquer),
    aucun dé consommé pour lui, et B→3 s'enchaîne."""
    seq = _dice(monkeypatch, [6, 6, 1, 2])  # A : touche, blessure, save ratée -> mort ; B : raté
    gs = _game_state([_weapon("gun_a"), _weapon("gun_b", strength=5), _weapon("gun_c", strength=6)],
                     [_intent(0, "2"), _intent(1, "3"), _intent(2, "2")])
    gs["models_cache"]["T2_0"]["HP_CUR"] = 1
    build_manual_shoot_allocation(gs, "1")

    result = select_attack_lot(gs, SHOOT_CTX, 0)

    assert result["done"] is True and seq == []
    assert "T2_0" not in gs["models_cache"]
    assert result["shoot_result"]["lot_order"] == ["GUN_A", "GUN_B"]
    assert result["shoot_result"]["attacks_made"] == 2
