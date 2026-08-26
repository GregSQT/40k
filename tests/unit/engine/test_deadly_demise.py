"""§24.08 DEADLY DEMISE — mécanisme générique dans destroy_model.

PDF 24.08 : « When a model with this ability is destroyed, before removing it from play (and
before making any Emergency Disembark rolls), roll one D6: on a 6, each unit within 6" of it
suffers a number of mortal wounds as detailed in the ability's entry. »

Ce test couvre le MECANISME uniquement (chantier en cours). La valeur `deadly_demise` sur les
datasheets sera câblée par le chantier 06 (actuellement absente de tous les rosters).

Discrimination verrouillee :
- deadly_demise présente + D6=6 → action_log contient une entrée deadly_demise par unité dans 6"
- deadly_demise présente + D6=1 → action_log contient une entrée deadly_demise (d6Roll=1) mais
  deadlyDemiseWounds=0 et pas d'allocation
- deadly_demise absente → aucune entrée deadly_demise dans action_log
"""
import random
import pytest

from engine.phase_handlers.shared_utils import destroy_model


# ── game_state minimal pour destroy_model ────────────────────────────────────

def _gs(*, with_deadly_demise: bool = True, target_col: int = 2, target_row: int = 2):
    """Une figurine (mid='SRC#0') dans escouade 'SRC' à (0,0) + une escouade cible 'TGT' à
    (target_col, target_row).  inches_to_subhex=5 => 6" = 30 subhex.
    """
    ish = 5
    src_model = {
        "col": 0, "row": 0, "level": 0, "player": 1, "squad_id": "SRC",
        "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
    }
    src_uc: dict = {
        "col": 0, "row": 0, "player": 1, "HP_CUR": 1,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        "occupied_hexes": {(0, 0)},
        "occupied_hexes_by_model": {"SRC#0": (0, 0)},
        "floor_height_by_model": {"SRC#0": 0.0},
        "level_by_model": {"SRC#0": 0},
        "MODEL_HEIGHT": 2.0,
    }
    if with_deadly_demise:
        src_uc["deadly_demise"] = 1

    tgt_uc = {
        "col": target_col, "row": target_row, "player": 2, "HP_CUR": 2,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        "occupied_hexes": {(target_col, target_row)},
        "occupied_hexes_by_model": {"TGT#0": (target_col, target_row)},
        "floor_height_by_model": {"TGT#0": 0.0},
        "level_by_model": {"TGT#0": 0},
        "MODEL_HEIGHT": 2.0,
    }

    return {
        "models_cache": {"SRC#0": src_model},
        "squad_models": {"SRC": ["SRC#0"], "TGT": ["TGT#0"]},
        "units_cache": {"SRC": src_uc, "TGT": tgt_uc},
        "action_logs": [],
        "action_log_seq": 0,
        "board_cols": 44, "board_rows": 44,
        "wall_hexes": set(),
        "_unit_move_version": 0,
        "terrain_areas": [],
        "inches_to_subhex": ish,
        "config": {
            "game_rules": {
                "engagement_zone": 2,
                "max_base_size_hex": 12,
                "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
                "plunging_fire_height": 3,
            },
            "move": {
                "can_move_through_enemy_engagement_zone": True,
                "can_move_through_enemy_model": False,
                "can_move_through_friendly_model": True,
            },
        },
        "phase": "fight",
        "turn": 1,
    }


def _dd_logs(gs):
    return [e for e in gs["action_logs"] if e.get("type") == "deadly_demise"]


# ── tests ────────────────────────────────────────────────────────────────────

def test_dd_d6_6_emet_entree_dans_action_log(monkeypatch):
    """D6=6 et cible a <=6" -> une entree deadly_demise dans action_log, wounds > 0."""
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink: None)
    gs = _gs(with_deadly_demise=True, target_col=5, target_row=0)   # TGT a 5 subhex < 30
    destroy_model(gs, "SRC#0", reason="combat")
    logs = _dd_logs(gs)
    assert len(logs) >= 1, f"attendu >=1 entree deadly_demise, obtenu {logs}"
    hit = next(e for e in logs if e["unitId"] == "TGT")
    assert hit["d6Roll"] == 6
    assert hit["deadlyDemiseWounds"] == 1   # deadly_demise = 1 dans le gs


def test_dd_d6_1_emet_entree_sans_allocation(monkeypatch):
    """D6=1 -> entree deadly_demise emise MAIS wounds=0 et pas d'allocation."""
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    import engine.phase_handlers.shared_utils as su
    allocated_calls = []
    monkeypatch.setattr(su, "allocate_mortal_wounds",
                        lambda gs, uid, n, auto, sink: allocated_calls.append((uid, n)))
    gs = _gs(with_deadly_demise=True, target_col=5, target_row=0)
    destroy_model(gs, "SRC#0", reason="combat")
    logs = _dd_logs(gs)
    assert any(e["d6Roll"] == 1 for e in logs), "l'event doit etre emis meme sur echec"
    assert not any(e["deadlyDemiseWounds"] > 0 for e in logs)
    assert not allocated_calls, "aucune allocation sur d6 < 6"


def _gs_multi(*, n_targets: int = 3):
    """game_state avec n_targets unités cibles à courte portée (5 subhex chacune)."""
    ish = 5
    src_model = {
        "col": 0, "row": 0, "level": 0, "player": 1, "squad_id": "SRC",
        "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
    }
    src_uc: dict = {
        "col": 0, "row": 0, "player": 1, "HP_CUR": 1,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        "occupied_hexes": {(0, 0)},
        "occupied_hexes_by_model": {"SRC#0": (0, 0)},
        "floor_height_by_model": {"SRC#0": 0.0},
        "level_by_model": {"SRC#0": 0},
        "MODEL_HEIGHT": 2.0,
        "deadly_demise": 1,
    }
    units_cache: dict = {"SRC": src_uc}
    squad_models: dict = {"SRC": ["SRC#0"]}
    for i in range(n_targets):
        uid = f"TGT{i}"
        col = i + 1
        units_cache[uid] = {
            "col": col, "row": 0, "player": 2, "HP_CUR": 2,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            "occupied_hexes": {(col, 0)},
            "occupied_hexes_by_model": {f"{uid}#0": (col, 0)},
            "floor_height_by_model": {f"{uid}#0": 0.0},
            "level_by_model": {f"{uid}#0": 0},
            "MODEL_HEIGHT": 2.0,
        }
        squad_models[uid] = [f"{uid}#0"]
    return {
        "models_cache": {"SRC#0": src_model},
        "squad_models": squad_models,
        "units_cache": units_cache,
        "action_logs": [],
        "action_log_seq": 0,
        "board_cols": 44, "board_rows": 44,
        "wall_hexes": set(),
        "_unit_move_version": 0,
        "terrain_areas": [],
        "inches_to_subhex": ish,
        "config": {
            "game_rules": {
                "engagement_zone": 2,
                "max_base_size_hex": 12,
                "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
                "plunging_fire_height": 3,
            },
            "move": {
                "can_move_through_enemy_engagement_zone": True,
                "can_move_through_enemy_model": False,
                "can_move_through_friendly_model": True,
            },
        },
        "phase": "fight",
        "turn": 1,
    }


def test_dd_d6_1_un_seul_log_meme_avec_plusieurs_cibles(monkeypatch):
    """D6=1 avec 3 unites en portee -> exactement 1 log 'no effect', 0 jet de de par cible."""
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda *a: None)
    gs = _gs_multi(n_targets=3)
    destroy_model(gs, "SRC#0", reason="combat")
    logs = _dd_logs(gs)
    assert len(logs) == 1, (
        f"d6<6 doit produire exactement 1 log 'no effect', obtenu {len(logs)}: {logs}"
    )
    assert logs[0]["d6Roll"] == 1
    assert logs[0]["deadlyDemiseWounds"] == 0


def test_dd_absent_aucune_entree(monkeypatch):
    """Sans la cle deadly_demise en units_cache, aucune entree deadly_demise emise."""
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink: None)
    gs = _gs(with_deadly_demise=False, target_col=5, target_row=0)
    destroy_model(gs, "SRC#0", reason="combat")
    assert not _dd_logs(gs), "aucune entree deadly_demise sans la cle"


def test_dd_cible_hors_portee_pas_d_entree(monkeypatch):
    """Cible a > 6" (> 30 subhex) -> aucune entree deadly_demise pour cette cible."""
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink: None)
    # TGT a (40, 0) = 40 subhex, donc 40/5 = 8" > 6"
    gs = _gs(with_deadly_demise=True, target_col=40, target_row=0)
    destroy_model(gs, "SRC#0", reason="combat")
    tgt_logs = [e for e in _dd_logs(gs) if e.get("unitId") == "TGT"]
    assert not tgt_logs, "la cible hors portee ne doit pas recevoir de MW"


def test_dd_mutation_verrou(monkeypatch):
    """Verrou mutation : si _apply_deadly_demise n'est pas appele, aucun log deadly_demise.

    Prouve que le bloc `if _deadly_demise_val is not None: _apply_deadly_demise(...)` dans
    destroy_model est effectivement atteint quand la cle est presente.
    """
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink: None)

    # Cas controle : sans deadly_demise -> 0 log (baseline de la mutation)
    gs_no = _gs(with_deadly_demise=False, target_col=5, target_row=0)
    destroy_model(gs_no, "SRC#0", reason="combat")
    assert not _dd_logs(gs_no), "baseline : sans la cle, 0 log"

    # Cas actif : avec deadly_demise -> >= 1 log (echoue si le bloc est retire)
    gs_yes = _gs(with_deadly_demise=True, target_col=5, target_row=0)
    destroy_model(gs_yes, "SRC#0", reason="combat")
    assert _dd_logs(gs_yes), "avec la cle, le log doit apparaitre — echoue si le bloc est mute"


# ── câblage roster → build_units_cache ───────────────────────────────────────

from typing import Any, Dict


def _unit(*, unit_id: str, col: int, row: int, with_dd_rule: bool, dd_value: Any = "D3") -> Dict[str, Any]:
    """Unité minimale compatible avec build_units_cache."""
    unit_rules: list[Dict[str, Any]] = [{"ruleId": "leader", "displayName": "Leader"}]
    if with_dd_rule:
        unit_rules.append({
            "ruleId": "deadly_demise",
            "displayName": "Deadly Demise D3",
            "rule_args": {"value": dd_value},
        })
    return {
        "id": unit_id,
        "col": col, "row": row, "level": 0,
        "HP_CUR": 4, "HP_MAX": 4, "VALUE": 65, "OC": 1,
        "T": 5, "ARMOR_SAVE": 5, "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SHAPE": "round", "BASE_SIZE": 20,
        "MODEL_HEIGHT": 2.5, "MOVE": 6,
        "UNIT_RULES": unit_rules,
        "player": 1,
        "orientation": 0,
    }


def _build_gs(*units):
    from engine.phase_handlers.shared_utils import build_units_cache
    gs = {
        "units": list(units),
        "unit_by_id": {str(u["id"]): u for u in units},
        "config": {
            "game_rules": {
                "engagement_zone": 2,
                "max_base_size_hex": 12,
                "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
                "plunging_fire_height": 3,
            },
        },
        "board_cols": 44, "board_rows": 44,
        "wall_hexes": set(),
        "terrain_areas": [],
        "inches_to_subhex": 5,
        "_unit_move_version": 0,
    }
    build_units_cache(gs)
    return gs


def test_build_units_cache_pose_deadly_demise_depuis_unit_rules():
    """build_units_cache doit écrire units_cache[id]['deadly_demise'] = 'D3' si la règle est déclarée."""
    gs = _build_gs(_unit(unit_id="W", col=0, row=0, with_dd_rule=True, dd_value="D3"))
    assert gs["units_cache"]["W"].get("deadly_demise") == "D3", (
        "La clé 'deadly_demise' doit valoir 'D3' quand UNIT_RULES la déclare"
    )


def test_build_units_cache_pas_de_cle_sans_regle():
    """Sans deadly_demise dans UNIT_RULES, la clé ne doit pas exister dans units_cache."""
    gs = _build_gs(_unit(unit_id="U", col=0, row=0, with_dd_rule=False))
    assert "deadly_demise" not in gs["units_cache"]["U"], (
        "La clé 'deadly_demise' ne doit PAS être présente si la règle est absente"
    )


def test_build_units_cache_mutation_verrou():
    """Verrou mutation : retire la règle → clé absente ; la remet → clé présente.

    Prouve que build_units_cache LIT effectivement UNIT_RULES et n'ignore pas la branche.
    """
    # Défaut injecté : without rule → clé absente (baseline)
    gs_no = _build_gs(_unit(unit_id="X", col=0, row=0, with_dd_rule=False))
    assert "deadly_demise" not in gs_no["units_cache"]["X"], "baseline : sans règle, clé absente"

    # Fix rétabli : with rule → clé présente (échoue si la branche est retirée)
    gs_yes = _build_gs(_unit(unit_id="X", col=0, row=0, with_dd_rule=True, dd_value=1))
    assert gs_yes["units_cache"]["X"].get("deadly_demise") == 1, "avec règle, clé doit valoir 1"
