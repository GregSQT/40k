"""Filet de regression — declaration d'attaque au TIR (primitives PvP manuel).

Verrouille le comportement AVANT la migration `index -> identite(code) + quantite`
(cf. refactor declare_attack_weapon_qty). Ces tests DOIVENT rester verts pendant
toute la migration : ils sont la garde anti-regression sur les chemins conserves.

Couvert ici (passe sur le code actuel) :
  - plomberie identite : chaque arme d'armory porte son `code` (get_weapons)
  - groupage combi (`_weapon_group_key`) : Frag/Krak = meme arme physique
  - declaration par-figurine (`declare_attack_model`) : 1 intent (fig, arme selectionnee, cible)
  - declaration par-arme homogene (`declare_attack_weapon`) : 1 intent par fig porteuse

Les tests specifiques a `declare_attack_weapon_qty` (identite par code + count +
exclusivite de groupe + erreur si count > eligibles) seront ajoutes AVEC son
implementation (etape 2 de la migration).
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
    squad_declare_shoot_model,
    squad_declare_shoot_weapon,
    squad_declare_shoot_weapon_qty,
    squad_shoot_weapon_qty_max,
    squad_shoot_weapons_for_target,
    squad_shoot_eligible_models,
    squad_shoot_toggle_model_weapon,
    squad_shoot_models_status,
    squad_undeclare_shoot_weapon_qty,
    squad_union_weapons,
    _weapon_group_key,
)

# Armes reelles de l'armory (teste aussi la propagation du champ `code` par le parser).
STORM = get_weapons("SpaceMarine", ["storm_bolter"])[0]
FRAG = get_weapons("SpaceMarine", ["cyclone_missile_launcher_frag"])[0]
KRAK = get_weapons("SpaceMarine", ["cyclone_missile_launcher_krak"])[0]


def _unit(
    uid: int, player: int, models: List[Dict[str, Any]], rng_weapons: List[Dict[str, Any]]
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
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "RNG_WEAPONS": rng_weapons,
        "CC_WEAPONS": [],
        "selectedRngWeaponIndex": 0,
        "selectedCcWeaponIndex": 0,
        "models": models,
    }


def _make_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {**_GAME_RULES, "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 40,
        "board_rows": 30,
        "current_player": 1,
        "phase": "shoot",
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
    """Ouvre l'activation tir de l'escouade (pending initialise) sans effets de bord."""
    gs["pending_squad_shoot_intents"][squad_id] = []


def _m(col: int, row: int, weapons: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"col": col, "row": row, "RNG_WEAPONS": weapons, "selectedRngWeaponIndex": 0}


# ─────────────────────────────────────────────────────────────────────────────
# Plomberie identite (code) + groupage combi
# ─────────────────────────────────────────────────────────────────────────────
class TestWeaponIdentity:
    def test_armory_weapons_carry_code(self):
        assert STORM["code"] == "storm_bolter"
        assert FRAG["code"] == "cyclone_missile_launcher_frag"
        assert KRAK["code"] == "cyclone_missile_launcher_krak"

    def test_group_key_groups_combi_profiles(self):
        weapons = [FRAG, KRAK]
        # Frag et Krak partagent COMBI_WEAPON -> meme arme physique.
        assert _weapon_group_key(weapons, 0) == _weapon_group_key(weapons, 1)

    def test_group_key_distinguishes_solo_weapon(self):
        assert _weapon_group_key([STORM], 0) != _weapon_group_key([FRAG, KRAK], 0)


# ─────────────────────────────────────────────────────────────────────────────
# Declaration par-figurine (conservee telle quelle par la migration)
# ─────────────────────────────────────────────────────────────────────────────
class TestDeclareModel:
    def _squad(self):
        atk = _unit(1, 1, [_m(5, 5, [STORM]), _m(5, 6, [STORM]), _m(6, 5, [STORM])], [STORM])
        tgt = _unit(2, 2, [_m(5, 15, [STORM])], [STORM])
        return _make_gs([atk, tgt])

    def test_creates_single_intent_for_that_fig(self):
        gs = self._squad()
        _activate(gs, "1")
        intent = squad_declare_shoot_model(gs, "1", "1#0", "2")
        assert intent["model_id"] == "1#0"
        assert intent["weapon_index"] == 0
        assert intent["target_unit_id"] == "2"
        assert gs["pending_squad_shoot_intents"]["1"] == [intent]

    def test_redeclare_same_fig_same_weapon_replaces_target(self):
        atk = _unit(1, 1, [_m(5, 5, [STORM])], [STORM])
        tgt_a = _unit(2, 2, [_m(5, 15, [STORM])], [STORM])
        tgt_b = _unit(3, 2, [_m(6, 15, [STORM])], [STORM])
        gs = _make_gs([atk, tgt_a, tgt_b])
        _activate(gs, "1")
        squad_declare_shoot_model(gs, "1", "1#0", "2")
        squad_declare_shoot_model(gs, "1", "1#0", "3")
        intents = gs["pending_squad_shoot_intents"]["1"]
        assert len(intents) == 1
        assert intents[0]["target_unit_id"] == "3"


# ─────────────────────────────────────────────────────────────────────────────
# Declaration par-arme homogene (invariant que la migration doit preserver)
# ─────────────────────────────────────────────────────────────────────────────
class TestDeclareWeaponHomogeneous:
    def test_one_intent_per_carrier_fig(self):
        atk = _unit(1, 1, [_m(5, 5, [STORM]), _m(5, 6, [STORM]), _m(6, 5, [STORM])], [STORM])
        tgt = _unit(2, 2, [_m(5, 15, [STORM])], [STORM])
        gs = _make_gs([atk, tgt])
        _activate(gs, "1")
        created = squad_declare_shoot_weapon(gs, "1", 0, "2")
        assert len(created) == 3
        assert {i["model_id"] for i in created} == {"1#0", "1#1", "1#2"}
        assert all(i["weapon_index"] == 0 and i["target_unit_id"] == "2" for i in created)


# ─────────────────────────────────────────────────────────────────────────────
# Declaration par-arme QUANTIFIEE + identite code (nouvelle primitive)
# ─────────────────────────────────────────────────────────────────────────────
FRAG_CODE = "cyclone_missile_launcher_frag"
KRAK_CODE = "cyclone_missile_launcher_krak"
CYCLONE_MODELS = {"1#2", "1#3"}  # figs portant l'arme physique cyclone (frag/krak)


class TestDeclareWeaponQty:
    def _gs(self, targets=1):
        # 2 storm bolter + 2 cyclone (frag/krak) ; cible(s) a portee sans engagement.
        atk = _unit(
            1, 1,
            [_m(5, 5, [STORM]), _m(5, 6, [STORM]), _m(6, 5, [FRAG, KRAK]), _m(6, 6, [FRAG, KRAK])],
            [STORM],
        )
        units = [atk, _unit(2, 2, [_m(5, 15, [STORM]), _m(6, 15, [STORM])], [STORM])]
        if targets == 2:
            units.append(_unit(3, 2, [_m(20, 15, [STORM])], [STORM]))
        gs = _make_gs(units)
        _activate(gs, "1")
        return gs

    def test_selects_only_carriers_of_code(self):
        gs = self._gs()
        created = squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 1, "2")
        assert len(created) == 1
        assert created[0]["model_id"] in CYCLONE_MODELS  # jamais une fig storm bolter
        assert created[0]["weapon_index"] == 0  # index LOCAL de Frag chez le cyclone
        assert created[0]["target_unit_id"] == "2"

    def test_count_two_selects_both_carriers(self):
        gs = self._gs()
        created = squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 2, "2")
        assert {i["model_id"] for i in created} == CYCLONE_MODELS

    def test_group_exclusivity_frag_consumes_krak(self):
        gs = self._gs()
        squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 2, "2")  # les 2 cyclones en Frag
        # Plus aucune arme physique cyclone libre -> Krak impossible.
        with pytest.raises(ValueError):
            squad_declare_shoot_weapon_qty(gs, "1", KRAK_CODE, 1, "2")

    def test_count_exceeds_eligibles_raises_without_mutation(self):
        gs = self._gs()
        with pytest.raises(ValueError):
            squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 3, "2")  # seulement 2 cyclones
        assert gs["pending_squad_shoot_intents"]["1"] == []  # aucun effet de bord

    def test_set_semantics_edit_count_replaces(self):
        gs = self._gs()
        squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 1, "2")
        squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 2, "2")  # edition de la meme ligne
        frag = [i for i in gs["pending_squad_shoot_intents"]["1"]]
        assert len(frag) == 2  # remplace, ne cumule pas (2 et non 3)

    def test_split_same_profile_two_targets(self):
        gs = self._gs(targets=2)
        squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 1, "2")
        squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 1, "3")
        intents = gs["pending_squad_shoot_intents"]["1"]
        assert len(intents) == 2
        assert {i["target_unit_id"] for i in intents} == {"2", "3"}
        assert {i["model_id"] for i in intents} == CYCLONE_MODELS  # 1 cyclone par cible


# ─────────────────────────────────────────────────────────────────────────────
# Union des armes par-figurine (source du menu, point 5)
# ─────────────────────────────────────────────────────────────────────────────
class TestSquadUnionWeapons:
    def test_union_exposes_per_model_profiles_distinct(self):
        atk = _unit(
            1, 1,
            [_m(5, 5, [STORM]), _m(5, 6, [STORM]), _m(6, 5, [FRAG, KRAK])],
            [STORM],
        )
        gs = _make_gs([atk])
        union = squad_union_weapons(gs, "1")
        codes = [w["code"] for w in union]
        # Storm apparait une seule fois (distinct) + les 2 profils du Cyclone.
        assert codes == ["storm_bolter", FRAG_CODE, KRAK_CODE]
        assert all("shot" in w for w in union)  # flag attendu par weapon_availability_check
        assert all("carrier_type" in w and "carrier_name" in w for w in union)  # type porteur (distinction homonymes)

    def test_union_raises_on_weapon_without_code(self):
        atk = _unit(1, 1, [_m(5, 5, [{"display_name": "X", "RNG": 24, "NB": 1,
                                       "ATK": 3, "STR": 4, "AP": 0, "DMG": 1}])], [STORM])
        gs = _make_gs([atk])
        with pytest.raises(ValueError):
            squad_union_weapons(gs, "1")


# ─────────────────────────────────────────────────────────────────────────────
# Borne du champ count + annulation d'une ligne (support UI point 5)
# ─────────────────────────────────────────────────────────────────────────────
class TestQtyMaxAndUnassign:
    def _gs(self):
        atk = _unit(
            1, 1,
            [_m(5, 5, [STORM]), _m(5, 6, [STORM]), _m(6, 5, [FRAG, KRAK]), _m(6, 6, [FRAG, KRAK])],
            [STORM],
        )
        gs = _make_gs([atk, _unit(2, 2, [_m(5, 15, [STORM]), _m(6, 15, [STORM])], [STORM])])
        _activate(gs, "1")
        return gs

    def test_qty_max_counts_eligible_carriers(self):
        gs = self._gs()
        assert squad_shoot_weapon_qty_max(gs, "1", FRAG_CODE, "2") == 2  # 2 cyclones
        assert squad_shoot_weapon_qty_max(gs, "1", "storm_bolter", "2") == 2  # 2 storm

    def test_qty_max_accounts_group_exclusivity(self):
        gs = self._gs()
        squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 1, "2")  # 1 cyclone en Frag
        # Krak : 1 cyclone reste libre (l'autre consomme par Frag).
        assert squad_shoot_weapon_qty_max(gs, "1", KRAK_CODE, "2") == 1

    def test_qty_max_counts_own_line_as_free(self):
        gs = self._gs()
        squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 2, "2")  # les 2 cyclones
        # Editer la MEME ligne (Frag, cible 2) : ses figs comptent comme libres -> max 2.
        assert squad_shoot_weapon_qty_max(gs, "1", FRAG_CODE, "2") == 2

    def test_unassign_removes_only_that_line(self):
        gs = self._gs()
        squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 1, "2")
        squad_declare_shoot_weapon_qty(gs, "1", "storm_bolter", 2, "2")
        removed = squad_undeclare_shoot_weapon_qty(gs, "1", FRAG_CODE, "2")
        assert removed == 1
        codes_restants = {
            gs["models_cache"][i["model_id"]]["RNG_WEAPONS"][i["weapon_index"]]["code"]
            for i in gs["pending_squad_shoot_intents"]["1"]
        }
        assert codes_restants == {"storm_bolter"}  # la ligne Frag retiree, storm conservee


# ─────────────────────────────────────────────────────────────────────────────
# Menu cible-d'abord : armes eligibles pour une cible avec (m, x)
# ─────────────────────────────────────────────────────────────────────────────
class TestWeaponsForTarget:
    def _gs(self):
        atk = _unit(
            1, 1,
            [_m(5, 5, [STORM]), _m(5, 6, [STORM]), _m(6, 5, [FRAG, KRAK]), _m(6, 6, [FRAG, KRAK])],
            [STORM],
        )
        gs = _make_gs([atk, _unit(2, 2, [_m(5, 15, [STORM]), _m(6, 15, [STORM])], [STORM])])
        _activate(gs, "1")
        return gs

    def test_lists_eligible_weapons_with_max_and_zero_current(self):
        gs = self._gs()
        entries = squad_shoot_weapons_for_target(gs, "1", "2")
        by_code = {e["code"]: e for e in entries}
        assert by_code["storm_bolter"]["m"] == 2 and by_code["storm_bolter"]["x"] == 0
        assert by_code[FRAG_CODE]["m"] == 2 and by_code[FRAG_CODE]["x"] == 0
        # Frag et Krak apparaissent tous deux (m mesure la capacite de l'arme physique).
        assert by_code[KRAK_CODE]["m"] == 2
        assert "weapon" in by_code["storm_bolter"]  # dict d'arme pour l'affichage

    def test_current_count_reflects_declaration(self):
        gs = self._gs()
        squad_declare_shoot_weapon_qty(gs, "1", FRAG_CODE, 1, "2")
        by_code = {e["code"]: e for e in squad_shoot_weapons_for_target(gs, "1", "2")}
        assert by_code[FRAG_CODE]["x"] == 1  # 1 attribue
        assert by_code[FRAG_CODE]["m"] == 2  # ligne propre comptee libre
        assert by_code[KRAK_CODE]["m"] == 1  # 1 cyclone consomme par Frag


# ─────────────────────────────────────────────────────────────────────────────
# Voile vert (figs éligibles) + clic sur fig précise (toggle)
# ─────────────────────────────────────────────────────────────────────────────
class TestEligibleModelsAndToggle:
    def _gs(self):
        atk = _unit(
            1, 1,
            [_m(5, 5, [STORM]), _m(5, 6, [STORM]), _m(6, 5, [FRAG, KRAK]), _m(6, 6, [FRAG, KRAK])],
            [STORM],
        )
        gs = _make_gs([atk, _unit(2, 2, [_m(5, 15, [STORM]), _m(6, 15, [STORM])], [STORM])])
        _activate(gs, "1")
        return gs

    def test_eligible_models_lists_carriers_unassigned(self):
        gs = self._gs()
        models = squad_shoot_eligible_models(gs, "1", "storm_bolter", "2")
        assert {m["model_id"] for m in models} == {"1#0", "1#1"}  # les 2 storm terminators
        assert all(m["assigned"] is False for m in models)  # rien attribué encore

    def test_toggle_adds_then_removes_specific_fig(self):
        gs = self._gs()
        r1 = squad_shoot_toggle_model_weapon(gs, "1", "1#0", "storm_bolter", "2")
        assert r1 == "added"
        intents = gs["pending_squad_shoot_intents"]["1"]
        assert [i["model_id"] for i in intents] == ["1#0"]
        # marquée assigned dans le voile vert
        models = {m["model_id"]: m["assigned"] for m in squad_shoot_eligible_models(gs, "1", "storm_bolter", "2")}
        assert models["1#0"] is True and models["1#1"] is False
        # re-clic → retire
        r2 = squad_shoot_toggle_model_weapon(gs, "1", "1#0", "storm_bolter", "2")
        assert r2 == "removed"
        assert gs["pending_squad_shoot_intents"]["1"] == []

    def test_toggle_ineligible_fig_raises(self):
        gs = self._gs()
        # 1#0 ne porte pas le Cyclone → inéligible pour FRAG.
        with pytest.raises(ValueError):
            squad_shoot_toggle_model_weapon(gs, "1", "1#0", FRAG_CODE, "2")

    def test_toggle_respects_group_exclusivity(self):
        gs = self._gs()
        squad_shoot_toggle_model_weapon(gs, "1", "1#2", FRAG_CODE, "2")  # cyclone en Frag
        # même fig en Krak → arme physique déjà engagée → inéligible.
        with pytest.raises(ValueError):
            squad_shoot_toggle_model_weapon(gs, "1", "1#2", KRAK_CODE, "2")


class TestModelsStatus:
    def _gs(self):
        atk = _unit(
            1, 1,
            [_m(5, 5, [STORM]), _m(5, 6, [STORM]), _m(6, 5, [FRAG, KRAK]), _m(6, 6, [FRAG, KRAK])],
            [STORM],
        )
        gs = _make_gs([atk, _unit(2, 2, [_m(5, 15, [STORM])], [STORM])])
        _activate(gs, "1")
        return gs

    def test_all_green_and_weapon_codes(self):
        gs = self._gs()
        status = {s["model_id"]: s for s in squad_shoot_models_status(gs, "1", "2")}
        assert all(status[m]["can_shoot"] for m in status)  # toutes à portée/LoS
        assert status["1#0"]["weapon_codes"] == ["storm_bolter"]
        assert set(status["1#2"]["weapon_codes"]) == {FRAG_CODE, KRAK_CODE}

    def test_fig_becomes_grey_when_exhausted(self):
        gs = self._gs()
        # 1#0 tire son unique arme (storm) → épuisée → grise.
        squad_shoot_toggle_model_weapon(gs, "1", "1#0", "storm_bolter", "2")
        st = {s["model_id"]: s for s in squad_shoot_models_status(gs, "1", "2")}
        assert st["1#0"]["can_shoot"] is False and st["1#0"]["exhausted"] is True  # épuisée → gris
        assert st["1#1"]["can_shoot"] is True and st["1#1"]["exhausted"] is False  # l'autre storm reste vert
        # Le cyclone : Frag attribué mais Krak partage le groupe → épuisé aussi.
        squad_shoot_toggle_model_weapon(gs, "1", "1#2", FRAG_CODE, "2")
        st2 = {s["model_id"]: s for s in squad_shoot_models_status(gs, "1", "2")}
        assert st2["1#2"]["exhausted"] is True  # Frag/Krak = 1 arme physique → épuisée

    def test_can_shoot_false_but_not_exhausted_when_out_of_range(self):
        # Cible hors portée d'une fig non épuisée → can_shoot False MAIS exhausted False (= "rien").
        atk = _unit(1, 1, [_m(5, 5, [STORM])], [STORM])
        far = _unit(2, 2, [_m(5, 90, [STORM])], [STORM])  # hors portée storm (24)
        gs = _make_gs([atk, far])
        _activate(gs, "1")
        s = squad_shoot_models_status(gs, "1", "2")[0]
        assert s["can_shoot"] is False and s["exhausted"] is False
