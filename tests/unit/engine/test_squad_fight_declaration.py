"""Filet de regression — declaration d'attaque au COMBAT (primitives PvP manuel).

Jumeau de test_squad_shoot_declaration.py, adapte a la melee : armes CC reelles et
eligibilite par ENGAGEMENT (pas de portee/LoS). Verrouille les wrappers squad_fight_*
(fight_handlers.py) qui delèguent au moteur generique via FIGHT_DECLARE_CTX.

Difference cle vs tir :
  - source d'armes : CC_WEAPONS (close_combat_weapon / power_fist), selectedCcWeaponIndex ;
  - validite = la figurine attaquante est engagee avec la cible (empreinte synthetique
    dans la zone d'engagement), au lieu de portee + ligne de vue.
  - pas de regle Pistol (10.06) : la melee n'a pas d'exclusion de groupe entre profils.

NB : le moteur generique nomme le drapeau de disponibilite `can_shoot` quelle que soit
la phase ; en melee il se lit "peut frapper" (engagee + arme physique libre).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

# game_rules reels : evite de dupliquer/deriver des seuils (cf. feedback_inches_to_subhex).
_GAME_RULES = json.loads((Path(__file__).parents[3] / "config" / "game_config.json").read_text())["game_rules"]

from engine.weapons import get_weapons
import pytest

from engine.phase_handlers.shared_utils import (
    build_units_cache,
    init_pending_intents,
)
from engine.phase_handlers.fight_handlers import (
    squad_declare_fight_model,
    squad_declare_fight_weapon,
    squad_declare_fight_weapon_qty,
    squad_fight_weapon_qty_max,
    squad_fight_weapons_for_target,
    squad_fight_eligible_models,
    squad_fight_toggle_model_weapon,
    squad_fight_models_status,
    squad_undeclare_fight_weapon_qty,
    squad_union_cc_weapons,
)

# Armes de melee reelles de l'armory (teste aussi la propagation du champ `code`).
CCW = get_weapons("SpaceMarine", ["close_combat_weapon"])[0]
PF = get_weapons("SpaceMarine", ["power_fist"])[0]
FORCE = get_weapons("SpaceMarine", ["force_weapon"])[0]

CCW_CODE = "close_combat_weapon"
PF_CODE = "power_fist"
PF_MODELS = {"1#2", "1#3"}  # figs portant le power_fist


def _unit(
    uid: int, player: int, models: List[Dict[str, Any]], cc_weapons: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Escouade multi-figurine minimale acceptee par build_units_cache."""
    return {
        "id": uid,
        "player": player,
        "col": models[0]["col"],
        "row": models[0]["row"],
        "HP_CUR": 3,
        "HP_MAX": 3,
        "VALUE": 100,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "RNG_WEAPONS": [],
        "CC_WEAPONS": cc_weapons,
        "selectedRngWeaponIndex": 0,
        "selectedCcWeaponIndex": 0,
        "models": models,
    }


def _make_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {**_GAME_RULES, "engagement_zone": 2, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 40,
        "board_rows": 40,
        "current_player": 1,
        "phase": "fight",
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    init_pending_intents(gs)
    return gs


def _activate(gs: Dict[str, Any], squad_id: str) -> None:
    """Ouvre l'activation combat de l'escouade (pending initialise) sans effets de bord."""
    gs["pending_squad_fight_intents"][squad_id] = []


def _m(col: int, row: int, weapons: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"col": col, "row": row, "CC_WEAPONS": weapons, "selectedCcWeaponIndex": 0}


# Escouade de reference : 2 figs close_combat + 2 figs power_fist(+close_combat),
# toutes engagees avec la cible "2" (5,7)/(6,7). Cf. geometrie ez=2 verifiee.
def _atk_squad() -> Dict[str, Any]:
    return _unit(
        1, 1,
        [_m(5, 5, [CCW]), _m(5, 6, [CCW]), _m(6, 5, [PF, CCW]), _m(6, 6, [PF, CCW])],
        [CCW],
    )


def _target2() -> Dict[str, Any]:
    return _unit(2, 2, [_m(5, 7, [CCW]), _m(6, 7, [CCW])], [CCW])


# ─────────────────────────────────────────────────────────────────────────────
# Plomberie identite (code)
# ─────────────────────────────────────────────────────────────────────────────
class TestWeaponIdentity:
    def test_armory_weapons_carry_code(self):
        assert CCW["code"] == CCW_CODE
        assert PF["code"] == PF_CODE
        assert FORCE["code"] == "force_weapon"


# ─────────────────────────────────────────────────────────────────────────────
# Declaration par-figurine (engagement)
# ─────────────────────────────────────────────────────────────────────────────
class TestDeclareModel:
    def test_creates_single_intent_for_that_fig(self):
        gs = _make_gs([_atk_squad(), _target2()])
        _activate(gs, "1")
        intent = squad_declare_fight_model(gs, "1", "1#0", "2")
        assert intent["model_id"] == "1#0"
        assert intent["weapon_index"] == 0
        assert intent["target_unit_id"] == "2"
        assert gs["pending_squad_fight_intents"]["1"] == [intent]

    def test_declare_non_engaged_fig_raises(self):
        # Fig unique loin de la cible → non engagee → declaration refusee.
        atk = _unit(1, 1, [_m(5, 5, [CCW])], [CCW])
        far = _unit(2, 2, [_m(5, 25, [CCW])], [CCW])
        gs = _make_gs([atk, far])
        _activate(gs, "1")
        with pytest.raises(ValueError):
            squad_declare_fight_model(gs, "1", "1#0", "2")


# ─────────────────────────────────────────────────────────────────────────────
# Declaration par-arme homogene (index escouade) — chemin conserve jusqu'a l'etape 6
# ─────────────────────────────────────────────────────────────────────────────
class TestDeclareWeaponHomogeneous:
    def test_one_intent_per_engaged_carrier_fig(self):
        # Escouade uniforme [CCW] : index 0 = close_combat pour toutes les figs.
        atk = _unit(
            1, 1,
            [_m(5, 5, [CCW]), _m(5, 6, [CCW]), _m(6, 5, [CCW]), _m(6, 6, [CCW])],
            [CCW],
        )
        gs = _make_gs([atk, _target2()])
        _activate(gs, "1")
        created = squad_declare_fight_weapon(gs, "1", 0, "2")
        assert {i["model_id"] for i in created} == {"1#0", "1#1", "1#2", "1#3"}
        assert all(i["weapon_index"] == 0 and i["target_unit_id"] == "2" for i in created)


# ─────────────────────────────────────────────────────────────────────────────
# Declaration par-arme QUANTIFIEE + identite code (nouvelle primitive melee)
# ─────────────────────────────────────────────────────────────────────────────
class TestDeclareWeaponQty:
    def _gs(self, split_target=False):
        units = [_atk_squad(), _target2()]
        if split_target:
            # Seconde cible engagee du cote oppose (7,5)/(7,6) — geometrie ez=2 verifiee.
            units.append(_unit(4, 2, [_m(7, 5, [CCW]), _m(7, 6, [CCW])], [CCW]))
        gs = _make_gs(units)
        _activate(gs, "1")
        return gs

    def test_selects_only_carriers_of_code(self):
        gs = self._gs()
        created = squad_declare_fight_weapon_qty(gs, "1", PF_CODE, 1, "2")
        assert len(created) == 1
        assert created[0]["model_id"] in PF_MODELS  # jamais une fig close_combat seule
        assert created[0]["target_unit_id"] == "2"

    def test_count_two_selects_both_carriers(self):
        gs = self._gs()
        created = squad_declare_fight_weapon_qty(gs, "1", PF_CODE, 2, "2")
        assert {i["model_id"] for i in created} == PF_MODELS

    def test_count_exceeds_eligibles_raises_without_mutation(self):
        gs = self._gs()
        with pytest.raises(ValueError):
            squad_declare_fight_weapon_qty(gs, "1", PF_CODE, 3, "2")  # seulement 2 power_fist
        assert gs["pending_squad_fight_intents"]["1"] == []  # aucun effet de bord

    def test_set_semantics_edit_count_replaces(self):
        gs = self._gs()
        squad_declare_fight_weapon_qty(gs, "1", PF_CODE, 1, "2")
        squad_declare_fight_weapon_qty(gs, "1", PF_CODE, 2, "2")  # edition de la meme ligne
        assert len(gs["pending_squad_fight_intents"]["1"]) == 2  # remplace, ne cumule pas

    def test_split_same_profile_two_targets(self):
        gs = self._gs(split_target=True)
        squad_declare_fight_weapon_qty(gs, "1", PF_CODE, 1, "2")
        squad_declare_fight_weapon_qty(gs, "1", PF_CODE, 1, "4")
        intents = gs["pending_squad_fight_intents"]["1"]
        assert len(intents) == 2
        assert {i["target_unit_id"] for i in intents} == {"2", "4"}
        assert {i["model_id"] for i in intents} == PF_MODELS  # 1 power_fist par cible

    def test_non_engaged_target_cannot_be_declared(self):
        # Cible hors engagement → aucun candidat → erreur.
        atk = _unit(1, 1, [_m(5, 5, [PF, CCW])], [CCW])
        far = _unit(2, 2, [_m(5, 25, [CCW])], [CCW])
        gs = _make_gs([atk, far])
        _activate(gs, "1")
        with pytest.raises(ValueError):
            squad_declare_fight_weapon_qty(gs, "1", PF_CODE, 1, "2")


# ─────────────────────────────────────────────────────────────────────────────
# Union des armes CC par-figurine (source du menu)
# ─────────────────────────────────────────────────────────────────────────────
class TestSquadUnionWeapons:
    def test_union_exposes_per_model_profiles_distinct(self):
        gs = _make_gs([_atk_squad()])
        union = squad_union_cc_weapons(gs, "1")
        codes = [w["code"] for w in union]
        # close_combat une seule fois (distinct) puis power_fist (1re occurrence 1#2).
        assert codes == [CCW_CODE, PF_CODE]
        assert all("carrier_type" in w and "carrier_name" in w for w in union)

    def test_union_raises_on_weapon_without_code(self):
        atk = _unit(1, 1, [_m(5, 5, [{"display_name": "X", "ATK": 3, "STR": 4, "AP": 0, "DMG": 1}])], [CCW])
        gs = _make_gs([atk])
        with pytest.raises(ValueError):
            squad_union_cc_weapons(gs, "1")


# ─────────────────────────────────────────────────────────────────────────────
# Borne du champ count + annulation d'une ligne
# ─────────────────────────────────────────────────────────────────────────────
class TestQtyMaxAndUnassign:
    def _gs(self):
        gs = _make_gs([_atk_squad(), _target2()])
        _activate(gs, "1")
        return gs

    def test_qty_max_counts_engaged_carriers(self):
        gs = self._gs()
        assert squad_fight_weapon_qty_max(gs, "1", PF_CODE, "2") == 2  # 2 power_fist
        assert squad_fight_weapon_qty_max(gs, "1", CCW_CODE, "2") == 4  # 4 close_combat engagees

    def test_qty_max_counts_own_line_as_free(self):
        gs = self._gs()
        squad_declare_fight_weapon_qty(gs, "1", PF_CODE, 2, "2")  # les 2 power_fist
        # Editer la MEME ligne : ses figs comptent comme libres → max 2.
        assert squad_fight_weapon_qty_max(gs, "1", PF_CODE, "2") == 2

    def test_qty_max_zero_for_non_engaged_target(self):
        atk = _unit(1, 1, [_m(5, 5, [PF, CCW])], [CCW])
        far = _unit(2, 2, [_m(5, 25, [CCW])], [CCW])
        gs = _make_gs([atk, far])
        _activate(gs, "1")
        assert squad_fight_weapon_qty_max(gs, "1", PF_CODE, "2") == 0

    def test_unassign_removes_only_that_line(self):
        gs = self._gs()
        squad_declare_fight_weapon_qty(gs, "1", PF_CODE, 1, "2")
        squad_declare_fight_weapon_qty(gs, "1", CCW_CODE, 2, "2")
        removed = squad_undeclare_fight_weapon_qty(gs, "1", PF_CODE, "2")
        assert removed == 1
        codes_restants = {
            gs["models_cache"][i["model_id"]]["CC_WEAPONS"][i["weapon_index"]]["code"]
            for i in gs["pending_squad_fight_intents"]["1"]
        }
        assert codes_restants == {CCW_CODE}  # la ligne power_fist retiree, close_combat conservee


# ─────────────────────────────────────────────────────────────────────────────
# Menu cible-d'abord : armes eligibles pour une cible avec (m, x)
# ─────────────────────────────────────────────────────────────────────────────
class TestWeaponsForTarget:
    def _gs(self):
        gs = _make_gs([_atk_squad(), _target2()])
        _activate(gs, "1")
        return gs

    def test_lists_eligible_weapons_with_max_and_zero_current(self):
        gs = self._gs()
        by_code = {e["code"]: e for e in squad_fight_weapons_for_target(gs, "1", "2")}
        assert by_code[CCW_CODE]["m"] == 4 and by_code[CCW_CODE]["x"] == 0
        assert by_code[PF_CODE]["m"] == 2 and by_code[PF_CODE]["x"] == 0
        assert "weapon" in by_code[CCW_CODE]

    def test_current_count_reflects_declaration(self):
        gs = self._gs()
        squad_declare_fight_weapon_qty(gs, "1", PF_CODE, 1, "2")
        by_code = {e["code"]: e for e in squad_fight_weapons_for_target(gs, "1", "2")}
        assert by_code[PF_CODE]["x"] == 1
        assert by_code[PF_CODE]["m"] == 2  # ligne propre comptee libre

    def test_empty_for_non_engaged_target(self):
        atk = _unit(1, 1, [_m(5, 5, [CCW])], [CCW])
        far = _unit(2, 2, [_m(5, 25, [CCW])], [CCW])
        gs = _make_gs([atk, far])
        _activate(gs, "1")
        assert squad_fight_weapons_for_target(gs, "1", "2") == []


# ─────────────────────────────────────────────────────────────────────────────
# Voile vert (figs éligibles) + clic sur fig précise (toggle)
# ─────────────────────────────────────────────────────────────────────────────
class TestEligibleModelsAndToggle:
    def _gs(self):
        gs = _make_gs([_atk_squad(), _target2()])
        _activate(gs, "1")
        return gs

    def test_eligible_models_lists_carriers_unassigned(self):
        gs = self._gs()
        models = squad_fight_eligible_models(gs, "1", PF_CODE, "2")
        assert {m["model_id"] for m in models} == PF_MODELS
        assert all(m["assigned"] is False for m in models)

    def test_toggle_adds_then_removes_specific_fig(self):
        gs = self._gs()
        r1 = squad_fight_toggle_model_weapon(gs, "1", "1#2", PF_CODE, "2")
        assert r1 == "added"
        assert [i["model_id"] for i in gs["pending_squad_fight_intents"]["1"]] == ["1#2"]
        models = {m["model_id"]: m["assigned"] for m in squad_fight_eligible_models(gs, "1", PF_CODE, "2")}
        assert models["1#2"] is True and models["1#3"] is False
        r2 = squad_fight_toggle_model_weapon(gs, "1", "1#2", PF_CODE, "2")
        assert r2 == "removed"
        assert gs["pending_squad_fight_intents"]["1"] == []

    def test_toggle_ineligible_fig_raises(self):
        gs = self._gs()
        # 1#0 ne porte pas le power_fist → ineligible.
        with pytest.raises(ValueError):
            squad_fight_toggle_model_weapon(gs, "1", "1#0", PF_CODE, "2")


class TestModelsStatus:
    def test_all_can_fight_and_weapon_codes(self):
        gs = _make_gs([_atk_squad(), _target2()])
        _activate(gs, "1")
        status = {s["model_id"]: s for s in squad_fight_models_status(gs, "1", "2")}
        assert all(status[m]["can_shoot"] for m in status)  # toutes engagees (can_shoot = peut frapper)
        assert status["1#0"]["weapon_codes"] == [CCW_CODE]
        assert set(status["1#2"]["weapon_codes"]) == {PF_CODE, CCW_CODE}

    def test_fig_becomes_grey_when_exhausted(self):
        gs = _make_gs([_atk_squad(), _target2()])
        _activate(gs, "1")
        # 1#0 frappe son unique arme (close_combat) → epuisee → grise.
        squad_fight_toggle_model_weapon(gs, "1", "1#0", CCW_CODE, "2")
        st = {s["model_id"]: s for s in squad_fight_models_status(gs, "1", "2")}
        assert st["1#0"]["can_shoot"] is False and st["1#0"]["exhausted"] is True
        assert st["1#1"]["can_shoot"] is True and st["1#1"]["exhausted"] is False

    def test_can_fight_false_but_not_exhausted_when_not_engaged(self):
        # Cible hors engagement d'une fig non epuisee → can_shoot False MAIS exhausted False.
        atk = _unit(1, 1, [_m(5, 5, [CCW])], [CCW])
        far = _unit(2, 2, [_m(5, 25, [CCW])], [CCW])
        gs = _make_gs([atk, far])
        _activate(gs, "1")
        s = squad_fight_models_status(gs, "1", "2")[0]
        assert s["can_shoot"] is False and s["exhausted"] is False
