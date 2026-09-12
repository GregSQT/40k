"""05.03 « Allocation Order » — validation de l ordre des groupes declare par le defenseur.

Le PDF 05 Attack sequence (05.03, etape 2) impose TROIS contraintes a l ordre declare :
  1. un groupe non-CHARACTER contenant une figurine blessee est en premier ;
  2. aucun groupe CHARACTER n est plus tot qu un groupe non-CHARACTER ;
  3. un groupe CHARACTER blesse est plus tot qu un groupe CHARACTER sain.

Deux consommateurs dans `shared_utils` :
  - `apply_manual_shoot_declare_order` (defenseur humain) : une boucle de validation par
    contrainte, chacune levant sa propre ValueError ;
  - `_auto_declared_order` (defenseur programmatique) : produit directement un ordre conforme.

Chaque ordre invalide de la section 05.03 viole EXACTEMENT UNE contrainte : retirer une boucle
de validation rougit le test correspondant et lui seul. La precondition « permutation des
groupes vivants » (groupe mort exclu, aucun doublon) a sa propre section.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from engine.phase_handlers import shared_utils as su
from engine.phase_handlers.shared_utils import SHOOT_CTX
from tests._state_invariants import turn_state_invariants
from tests.unit.engine._config_helpers import build_game_rules
from tests.unit.engine._state_builders import units_cache_entry as _uc

# Identifiants des groupes (creation : non-CHARACTER d abord, puis CHARACTER, cf.
# `_build_alloc_groups`).
NH = 0  # non-CHARACTER sain
NW = 1  # non-CHARACTER blesse
CW = 2  # CHARACTER blesse
CH = 3  # CHARACTER sain


def _model(hp_cur: int, hp_max: int) -> Dict[str, Any]:
    return {"HP_CUR": hp_cur, "HP_MAX": hp_max}


def _groups() -> List[Dict[str, Any]]:
    return [
        {"group_id": NH, "is_character": False, "model_ids": ["nh_a", "nh_b"]},
        {"group_id": NW, "is_character": False, "model_ids": ["nw_a", "nw_b"]},
        {"group_id": CW, "is_character": True, "model_ids": ["cw"]},
        {"group_id": CH, "is_character": True, "model_ids": ["ch"]},
    ]


def _gs() -> Dict[str, Any]:
    """Une allocation tir en attente de declaration d ordre : un lot, quatre groupes vivants."""
    return {
        "models_cache": {
            "nh_a": _model(2, 2), "nh_b": _model(2, 2),
            "nw_a": _model(2, 2), "nw_b": _model(1, 2),
            "cw": _model(3, 5),
            "ch": _model(5, 5),
        },
        SHOOT_CTX.alloc_key: {
            "current_batch_index": 0,
            "batches": [{"alloc_groups": _groups(), "declared_order": None, "current_group_index": None}],
        },
    }


def _declare(gs: Dict[str, Any], order: List[int]) -> Dict[str, Any]:
    return su.apply_manual_shoot_declare_order(gs, order, SHOOT_CTX)


# ── Defenseur humain : apply_manual_shoot_declare_order ───────────────────────


def test_ordre_conforme_accepte_et_enregistre(monkeypatch):
    """[NW, NH, CW, CH] respecte les trois contraintes : ordre enregistre, allocation relancee."""
    gs = _gs()
    stepped: List[Any] = []
    monkeypatch.setattr(su, "_manual_allocation_step", lambda g, ctx: stepped.append((g, ctx)) or {"ok": True})

    result = _declare(gs, [NW, NH, CW, CH])

    batch = gs[SHOOT_CTX.alloc_key]["batches"][0]
    assert batch["declared_order"] == [NW, NH, CW, CH]
    assert batch["current_group_index"] == 0
    assert len(stepped) == 1 and stepped[0][0] is gs and stepped[0][1] is SHOOT_CTX
    assert result == {"ok": True}


def test_character_avant_non_character_refuse():
    """Contrainte 2 seule violee : un CHARACTER (blesse) place avant un non-CHARACTER (sain)."""
    gs = _gs()
    with pytest.raises(ValueError, match="non-CHARACTER ne peut pas etre place apres un CHARACTER"):
        _declare(gs, [NW, CW, NH, CH])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] is None


def test_non_character_sain_avant_non_character_blesse_refuse():
    """Contrainte 1 seule violee : le groupe non-CHARACTER blesse n est pas en premier."""
    gs = _gs()
    with pytest.raises(ValueError, match="non-CHARACTER blesse doit preceder les groupes sains"):
        _declare(gs, [NH, NW, CW, CH])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] is None


def test_character_sain_avant_character_blesse_refuse():
    """Contrainte 3 seule violee : deux CHARACTER, le sain declare avant le blesse."""
    gs = _gs()
    with pytest.raises(ValueError, match="CHARACTER blesse doit preceder un CHARACTER sain"):
        _declare(gs, [NW, NH, CH, CW])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] is None


def test_double_declaration_refuse(monkeypatch):
    """Garde de re-declaration : un ordre deja enregistre pour le lot ne peut pas etre redeclare,
    et l ordre initial reste intact (l allocation n est pas relancee une seconde fois)."""
    gs = _gs()
    stepped: List[Any] = []
    monkeypatch.setattr(su, "_manual_allocation_step", lambda g, ctx: stepped.append((g, ctx)) or {"ok": True})
    _declare(gs, [NW, NH, CW, CH])

    with pytest.raises(ValueError, match="deja declare"):
        _declare(gs, [NW, NH, CW, CH])

    batch = gs[SHOOT_CTX.alloc_key]["batches"][0]
    assert batch["declared_order"] == [NW, NH, CW, CH]
    assert batch["current_group_index"] == 0
    assert len(stepped) == 1 and stepped[0][0] is gs and stepped[0][1] is SHOOT_CTX


def test_lot_epuise_refuse(monkeypatch):
    """Garde de lot courant : l index de lot pointe au-dela du dernier lot (allocation epuisee),
    aucune declaration n est possible et l allocation n est pas relancee."""
    gs = _gs()
    gs[SHOOT_CTX.alloc_key]["current_batch_index"] = 1
    stepped: List[Any] = []
    monkeypatch.setattr(su, "_manual_allocation_step", lambda g, ctx: stepped.append((g, ctx)) or {"ok": True})

    with pytest.raises(ValueError, match="aucun lot courant"):
        _declare(gs, [NW, NH, CW, CH])

    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] is None
    assert stepped == []


# ── Precondition : permutation des groupes vivants ────────────────────────────


def test_groupe_mort_exclu_de_la_permutation(monkeypatch):
    """Un groupe dont toutes les figurines sont mortes ne fait plus partie des groupes vivants :
    le declarer est refuse, l ordre sans lui est accepte."""
    gs = _gs()
    del gs["models_cache"]["ch"]
    monkeypatch.setattr(su, "_manual_allocation_step", lambda g, ctx: {"ok": True})

    with pytest.raises(ValueError, match="n est pas une permutation"):
        _declare(gs, [NW, NH, CW, CH])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] is None

    _declare(gs, [NW, NH, CW])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] == [NW, NH, CW]


def test_identifiant_duplique_refuse():
    """Un ID repete (et un autre absent) n est pas une permutation des groupes vivants."""
    gs = _gs()
    with pytest.raises(ValueError, match="n est pas une permutation"):
        _declare(gs, [NW, NW, CW, CH])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] is None


# ── Defenseur programmatique : _auto_declared_order ───────────────────────────


def test_ordre_auto_conforme_05_03():
    """L ordre automatique est [non-CHAR blesse, non-CHAR sain, CHAR blesse, CHAR sain]."""
    gs = _gs()
    # Groupes fournis dans le pire ordre : le resultat ne doit rien devoir a l ordre d entree.
    live_groups = list(reversed(_groups()))

    assert su._auto_declared_order(gs, live_groups) == [NW, NH, CW, CH]


def test_ordre_auto_passe_la_validation_humaine(monkeypatch):
    """Miroir IA/PvP : l ordre que rend l auto-decideur est un ordre qu un humain aurait le
    droit de declarer (meme contrat 05.03 des deux cotes)."""
    gs = _gs()
    monkeypatch.setattr(su, "_manual_allocation_step", lambda g, ctx: {"ok": True})

    auto_order = su._auto_declared_order(gs, _groups())
    _declare(gs, auto_order)

    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] == auto_order


# ── Bout en bout : l ordre declare est celui que suit l allocation (05.04) ─────
#
# Les tests ci-dessus remplacent `_manual_allocation_step` par un stub : ils verrouillent la
# VALIDATION de l ordre, pas son USAGE. Ici rien n est remplace : lot reel (pool trie, groupes
# construits par `_build_alloc_groups` sur le `models_cache`), defenseur HUMAIN (siege 1), et
# les blessures traversent `_resolve_one_manual_wound` → `destroy_model` / `update_model_hp`.
# 05.04, « Inflict Damage » : chaque blessure va au « current allocation group », le groupe
# suivant de l ordre declare ne devenant courant qu une fois le precedent detruit.


def _e2e_model(mid: str, hp_cur: int, hp_max: int, *, sv: int, role: Any, row: int) -> Dict[str, Any]:
    return {
        "id": mid, "squad_id": "2", "player": 1, "T": 4, "HP_CUR": hp_cur, "HP_MAX": hp_max,
        "ARMOR_SAVE": sv, "INVUL_SAVE": 7, "role": role, "unitType": "Grunt",
        "points_per_hp": 5.0, "VALUE": 10.0, "col": 9, "row": row,
        "RNG_WEAPONS": [], "CC_WEAPONS": [],
        # Exiges par `_recompute_squad_occupied_hexes` / `_recompute_squad_cache` a chaque mort.
        "level": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1, "OC": 1,
    }


def _e2e_gs() -> Dict[str, Any]:
    """Tir de '1' (siege 0) sur '2' (siege 1, HUMAIN) : un lot de 4 blessures deja jetees.

    Cible = 5 figurines, 4 groupes (05.03) dans l ordre de creation de `_build_alloc_groups`
    (non-CHARACTER par triplet (W, Sv, InSv) dans l ordre de decouverte, puis un groupe par
    CHARACTER) : NH=0 {nh_a, nh_b} 2/2 Sv7 · NW=1 {nw_a} 1/2 Sv6 · CW=2 {cw} 3/5 · CH=3 {ch} 5/5.
    Pool : 4 blessures a D1, `save_roll` 1 (un 1 echoue toujours, quel que soit le seuil).
    """
    targets = {
        "nh_a": _e2e_model("nh_a", 2, 2, sv=7, role=None, row=9),
        "nh_b": _e2e_model("nh_b", 2, 2, sv=7, role=None, row=10),
        "nw_a": _e2e_model("nw_a", 1, 2, sv=6, role=None, row=11),
        "cw": _e2e_model("cw", 3, 5, sv=7, role="leader", row=12),
        "ch": _e2e_model("ch", 5, 5, sv=7, role="support", row=13),
    }
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 4, "RNG": 24,
              "WEAPON_RULES": [], "code": "test_gun", "display_name": "Gun"}
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 0,
                "col": 0, "row": 0, "RNG_WEAPONS": [weapon], "CC_WEAPONS": []}
    pool = [
        {"save_roll": 1, "rec": {"strengthResult": "SUCCESS"}, "attacker_mid": "A1", "devastating": False}
        for _ in range(4)
    ]
    return {
        **turn_state_invariants(),
        "player_types": {"0": "human", "1": "human"},
        "phase": "shoot",
        "models_cache": {"A1": attacker, **targets},
        "squad_models": {"1": ["A1"], "2": list(targets)},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 5}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(9, 9, player=1, hp=13)},
        "units": [{"id": "1", "player": 0}, {"id": "2", "player": 1}],
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": [], "player": 0},
                       "2": {"id": "2", "UNIT_RULES": [], "player": 1}},
        "objectives": [],
        "_unit_move_version": 0,
        "board_cols": 44, "board_rows": 60, "wall_hexes": set(),
        "config": {"game_rules": build_game_rules(engagement_zone=1)},
        SHOOT_CTX.alloc_key: {
            "attacker_squad_id": "1",
            "weapon_groups": [{
                "attacker_squad_id": "1", "target_sid": "2", "weapon": weapon,
                "weapon_name": "Gun", "weapon_names": ["Gun"],
                "ap": 0, "dmg_raw": 1, "dmg_bonus": 0, "precision": False,
                "damage": 0, "kills": 0, "killed_model_ids": [],
            }],
            "batches": [{
                "target_sid": "2", "weapon_group_idx": 0, "defender_player": 1,
                "alloc_groups": None, "declared_order": None, "current_group_index": 0,
                "current_model_id": None, "pool": pool, "pool_index": 0,
                "pending_mortal_wounds": None,
            }],
            "current_batch_index": 0,
            "summary": {"attacks_made": 4, "hits": 4, "wounds": 4, "failed_saves": 0,
                        "damage_total": 0, "models_killed": 0, "events": [],
                        "targets_meta": {"2": {"player": 1, "col": 9, "row": 9, "hp_before": 13}}},
            "hazardous_weapon_count": 0,
        },
    }


def _hp(gs: Dict[str, Any], mid: str) -> Optional[int]:
    m = gs["models_cache"].get(mid)
    return None if m is None else int(m["HP_CUR"])


def test_ordre_declare_respecte_par_allocation():
    """[NW, NH, CW, CH] declare par le defenseur humain : les 3 premieres blessures tombent
    dans NW (figurine entamee forcee, tuee), PUIS dans NH (choix libre, puis figurine entamee
    forcee) ; CW et CH ne sont pas touches. L ordre de CREATION des groupes (NH avant NW)
    n a aucun effet : seul l ordre DECLARE compte."""
    gs = _e2e_gs()

    # 1. Le lot construit ses groupes sur le models_cache reel et rend la main pour l ordre.
    first = su._manual_allocation_step(gs, SHOOT_CTX)
    assert first["waiting_for_player"] is True
    assert first["action"] == SHOOT_CTX.declare_order_action
    batch = gs[SHOOT_CTX.alloc_key]["batches"][0]
    by_id = {g["group_id"]: g["model_ids"] for g in batch["alloc_groups"]}
    assert by_id == {NH: ["nh_a", "nh_b"], NW: ["nw_a"], CW: ["cw"], CH: ["ch"]}

    # 2. Ordre declare. Blessure 1 : NW courant, nw_a (1/2) forcee et tuee. Blessure 2 : NW
    #    detruit -> NH courant, deux figurines saines -> la main revient au defenseur.
    second = su.apply_manual_shoot_declare_order(gs, [NW, NH, CW, CH], SHOOT_CTX)
    assert "nw_a" not in gs["models_cache"], "la 1re blessure devait tuer nw_a (groupe NW)"
    assert (_hp(gs, "nh_a"), _hp(gs, "nh_b")) == (2, 2), "NH ne doit rien encaisser tant que NW vit"
    assert second["waiting_for_player"] is True
    assert second["action"] == SHOOT_CTX.manual_alloc_action
    assert second["allocation"]["current_group_id"] == NH
    assert [c["model_id"] for c in second["allocation"]["choices"]] == ["nh_a", "nh_b"]
    assert second["allocation"]["wounds_remaining"] == 3

    # 3. Blessure 2 : le defenseur choisit nh_a (2 -> 1). Blessure 3 : nh_a entamee, forcee,
    #    tuee. Blessure 4 : nh_b seule saine du groupe courant -> la main revient.
    third = su.apply_manual_shoot_allocation(gs, "nh_a", SHOOT_CTX)
    assert "nh_a" not in gs["models_cache"], "la 3e blessure devait finir nh_a (05.04, entamee)"
    assert _hp(gs, "nh_b") == 2
    assert third["waiting_for_player"] is True
    assert third["allocation"]["current_group_id"] == NH
    assert [c["model_id"] for c in third["allocation"]["choices"]] == ["nh_b"]
    assert third["allocation"]["wounds_remaining"] == 1

    # Les groupes CHARACTER, derniers de l ordre declare, sont intacts.
    assert (_hp(gs, "cw"), _hp(gs, "ch")) == (3, 5)
    assert batch["declared_order"] == [NW, NH, CW, CH]
    assert batch["current_group_index"] == 1  # NW (index 0) detruit, NH (index 1) courant
    assert gs[SHOOT_CTX.alloc_key]["summary"]["models_killed"] == 2
    assert gs[SHOOT_CTX.alloc_key]["summary"]["damage_total"] == 3
