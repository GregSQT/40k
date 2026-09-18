"""05.04 / 06.02 — le défenseur ne répond que s'il a un vrai choix ; les blessures mortelles
suivent la cascade 06.02 sur toute l'unité.

PDF 05 Attack sequence, 05.04 « Select Model: Select one model in the current allocation group ;
this must be a model that has lost one or more wounds if possible. » — le choix existe entre
plusieurs figurines intactes, ET entre plusieurs figurines entamées ; une seule candidate est
allouée d'office (décision (a) du chantier « chaîne d'attaque 100 % », 2026-09-18).

PDF 06 Other concepts, 06.02 « Select Model: […] If a non-CHARACTER model in that unit has lost
one or more wounds, you must select that model. Otherwise, if that unit contains one or more
non-CHARACTER models, you must select one of those models. Otherwise […] CHARACTER ». Une
blessure mortelle de [DEVASTATING WOUNDS] (24.10, « the target unit suffers mortal wounds »)
est une blessure mortelle : elle va aux bodyguards même sous [PRECISION] — sauf clé
`game_rules.precision_mortal_wounds_to_character` (défaut `false`, en attente de confirmation
GW), qui la garde au groupe CHARACTER courant.
"""
import random
from typing import Any, Dict, List

from engine.constants import PENDING_SHOOT_ALLOCATION_KEY
from engine.phase_handlers import shooting_handlers
from engine.phase_handlers import shared_utils as su
from engine.phase_handlers.shared_utils import (
    SHOOT_CTX,
    apply_manual_shoot_allocation,
    build_manual_shoot_allocation,
)
from tests._state_invariants import turn_state_invariants
from tests.unit.engine._config_helpers import build_game_rules
from tests.unit.engine._state_builders import units_cache_entry as _uc


def _kw(*names):
    return [{"keywordId": n} for n in names]


def _weapon(rules=()) -> Dict[str, Any]:
    return {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": list(rules), "code": "gun", "display_name": "GUN"}


def _model(mid: str, *, hp_cur: int, hp_max: int = 3, role=None, col: int = 9) -> Dict[str, Any]:
    return {"id": mid, "squad_id": "2", "player": 1, "T": 4, "HP_CUR": hp_cur, "HP_MAX": hp_max,
            "ARMOR_SAVE": 7, "INVUL_SAVE": 7, "role": role, "unitType": "Grunt",
            "points_per_hp": 5.0, "VALUE": 10.0 if role is None else 50.0, "col": col, "row": 9,
            # Exiges par la cascade de `destroy_model` (recalcul des caches d escouade).
            "level": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1, "OC": 1,
            "RNG_WEAPONS": [], "CC_WEAPONS": [],
            "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": []}


def _game_state(weapon: Dict[str, Any], targets: List[Dict[str, Any]], *, precision_to_character: bool = False):
    shooter = {"id": "A0", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
               "HP_CUR": 2, "HP_MAX": 2, "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None,
               "unitType": "Shooter", "points_per_hp": 5.0, "VALUE": 10.0,
               "col": 0, "row": 0, "UNIT_KEYWORDS": _kw("INFANTRY"), "RNG_WEAPONS": [weapon],
               "UNIT_RULES": []}
    models = {"A0": shooter, **{m["id"]: m for m in targets}}
    units = [{"id": "1", "player": 0, "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": [],
              "designated_shoot_target_id": "2"},
             {"id": "2", "player": 1, "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": []}]
    return {
        **turn_state_invariants(),
        "gym_training_mode": False,
        # Attaquant programmatique (aucune question de lot) ; defenseur HUMAIN.
        "player_types": {"0": "ai", "1": "human"},
        "config": {"game_rules": build_game_rules(
            engagement_zone=1, precision_mortal_wounds_to_character=precision_to_character)},
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": models,
        "squad_models": {"1": ["A0"], "2": [m["id"] for m in targets]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": len(targets)}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(9, 9, player=1)},
        "units": units,
        "unit_by_id": {u["id"]: u for u in units},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "board_cols": 44, "board_rows": 60, "wall_hexes": set(), "_unit_move_version": 0,
        "pending_squad_shoot_intents": {"1": [
            {"model_id": "A0", "target_unit_id": "2", "weapon_index": 0,
             "n_attacks_resolved": 1, "target_squad_size_at_declaration": len(targets)},
        ]},
    }


def _dice(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "un dé a été jeté là où la règle n'en attend aucun"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    return seq


def _choices(payload):
    return [c["model_id"] for c in payload["allocation"]["choices"]]


# ------------------------------------------------------------------ 05.04 : le vrai choix

def test_deux_figurines_intactes_le_defenseur_choisit(monkeypatch):
    _dice(monkeypatch, [4, 4, 1])  # touche, blessure, sauvegarde ratée
    gs = _game_state(_weapon(), [_model("B0", hp_cur=3), _model("B1", hp_cur=3, col=10)])

    payload = build_manual_shoot_allocation(gs, "1")

    assert payload["waiting_for_player"] is True and payload["action"] == "squad_shoot_manual_alloc"
    assert _choices(payload) == ["B0", "B1"]
    assert "damage_type" not in payload["allocation"]


def test_deux_figurines_entamees_le_defenseur_choisit_laquelle(monkeypatch):
    """« must be a model that has lost one or more wounds if possible » : deux entamées, le
    choix entre elles appartient au défenseur — une version précédente imposait la première."""
    _dice(monkeypatch, [4, 4, 1])
    gs = _game_state(_weapon(), [_model("B0", hp_cur=2), _model("B1", hp_cur=1, col=10),
                                 _model("B2", hp_cur=3, col=11)])

    payload = build_manual_shoot_allocation(gs, "1")

    assert payload["waiting_for_player"] is True
    assert _choices(payload) == ["B0", "B1"], "les entamées seulement, et toutes les deux"
    result = apply_manual_shoot_allocation(gs, "B1", SHOOT_CTX)
    assert result["done"] is True
    assert "B1" not in gs["models_cache"] and gs["models_cache"]["B0"]["HP_CUR"] == 2


def test_une_seule_entamee_est_forcee_sans_question(monkeypatch):
    _dice(monkeypatch, [4, 4, 1])
    gs = _game_state(_weapon(), [_model("B0", hp_cur=2), _model("B1", hp_cur=3, col=10)])

    result = build_manual_shoot_allocation(gs, "1")

    assert result["done"] is True
    assert gs["models_cache"]["B0"]["HP_CUR"] == 1 and gs["models_cache"]["B1"]["HP_CUR"] == 3
    assert PENDING_SHOOT_ALLOCATION_KEY not in gs


def test_une_seule_figurine_est_allouee_sans_question(monkeypatch):
    _dice(monkeypatch, [4, 4, 1])
    gs = _game_state(_weapon(), [_model("B0", hp_cur=3)])

    result = build_manual_shoot_allocation(gs, "1")

    assert result["done"] is True and gs["models_cache"]["B0"]["HP_CUR"] == 2


def test_une_figurine_entamee_hors_choix_est_refusee(monkeypatch):
    _dice(monkeypatch, [4, 4, 1])
    gs = _game_state(_weapon(), [_model("B0", hp_cur=2), _model("B1", hp_cur=1, col=10),
                                 _model("B2", hp_cur=3, col=11)])
    build_manual_shoot_allocation(gs, "1")

    import pytest
    with pytest.raises(ValueError):
        apply_manual_shoot_allocation(gs, "B2", SHOOT_CTX)


# ------------------------------------------- 06.02 : blessure mortelle [DEVASTATING WOUNDS]

def _attached_unit():
    """Un CHARACTER (leader, 50 pts) et un bodyguard, tous deux intacts."""
    return [_model("C0", hp_cur=3, role="leader"), _model("B0", hp_cur=3, col=10)]


def test_devastating_sous_precision_va_au_bodyguard_par_defaut(monkeypatch):
    """[PRECISION] impose le groupe CHARACTER pour les dégâts normaux ; la blessure critique
    [DEVASTATING WOUNDS] est une blessure MORTELLE : cascade 06.02, non-CHARACTER d'abord."""
    monkeypatch.setattr(su, "_precision_group_is_visible", lambda gs, wg, cg: True)
    _dice(monkeypatch, [4, 6])  # touche, blessure critique -> mortelle, pas de sauvegarde
    gs = _game_state(_weapon(["PRECISION", "DEVASTATING_WOUNDS"]), _attached_unit())

    payload = build_manual_shoot_allocation(gs, "1")

    # Le lot a deux groupes (CHARACTER, bodyguard) : ordre à déclarer par le défenseur.
    assert payload["action"] == "squad_shoot_declare_order"
    order = [g["group_id"] for g in payload["order_request"]["groups"]]
    result = su.apply_manual_shoot_declare_order(gs, order, SHOOT_CTX)

    assert result["done"] is True
    assert gs["models_cache"]["B0"]["HP_CUR"] == 2, "la blessure mortelle va au bodyguard (06.02)"
    assert gs["models_cache"]["C0"]["HP_CUR"] == 3


def test_devastating_sous_precision_va_au_character_si_la_cle_le_dit(monkeypatch):
    monkeypatch.setattr(su, "_precision_group_is_visible", lambda gs, wg, cg: True)
    _dice(monkeypatch, [4, 6])
    gs = _game_state(_weapon(["PRECISION", "DEVASTATING_WOUNDS"]), _attached_unit(),
                     precision_to_character=True)

    payload = build_manual_shoot_allocation(gs, "1")
    order = [g["group_id"] for g in payload["order_request"]["groups"]]
    result = su.apply_manual_shoot_declare_order(gs, order, SHOOT_CTX)

    assert result["done"] is True
    assert gs["models_cache"]["C0"]["HP_CUR"] == 2, "clé à true : le CHARACTER courant encaisse"
    assert gs["models_cache"]["B0"]["HP_CUR"] == 3


def test_devastating_sans_precision_prend_la_figurine_entamee_de_toute_l_unite(monkeypatch):
    """06.02 première clause : une non-CHARACTER ENTAMÉE reçoit la blessure mortelle, même si
    elle n'est pas dans le groupe courant du lot."""
    _dice(monkeypatch, [4, 6])
    targets = [_model("B0", hp_cur=3), _model("B1", hp_cur=1, hp_max=1, col=10)]
    # B1 (W1) et B0 (W3) forment deux groupes 05.03 ; B0 sera entamée -> forcée par 06.02.
    targets[0]["HP_CUR"] = 2
    gs = _game_state(_weapon(["DEVASTATING_WOUNDS"]), targets)

    payload = build_manual_shoot_allocation(gs, "1")
    assert payload["action"] == "squad_shoot_declare_order"
    # Le défenseur déclare B1 (intacte, W1) en premier ; 05.03 l'impose d'ailleurs ? Non : un
    # groupe non-CHARACTER contenant une entamée doit être PREMIER — B0 est entamée, donc
    # l'ordre légal commence par son groupe ; on le suit, puis on vérifie la cascade.
    groups = payload["order_request"]["groups"]
    wounded_first = sorted(groups, key=lambda g: not g["has_wounded"])
    result = su.apply_manual_shoot_declare_order(gs, [g["group_id"] for g in wounded_first], SHOOT_CTX)

    assert result["done"] is True
    assert gs["models_cache"]["B0"]["HP_CUR"] == 1 and "B1" in gs["models_cache"]
