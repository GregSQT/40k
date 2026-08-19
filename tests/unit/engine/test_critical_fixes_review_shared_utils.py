"""Verroux pour 2 corrections critiques confirmées et 1 amélioration défensive — /code-review shared_utils.py.

Fix 1 (9175) — sort DEVASTATING_WOUNDS : amélioration défensive uniquement. `pw["save_roll"]`
vaut None pour les blessures DEVASTATING (critical_wound + profile.devastating), mais le sort
`(bool(devastating), save_roll)` ne crashe PAS en pratique — `(True, None) < (True, None)`
retourne False sans TypeError car Python compare l'égalité de l'élément précédent d'abord.
Changé par `pw.get("save_roll") or 0` (clé plus claire, aucun changement comportemental).
Tests : vérification de l'invariant d'ordonnancement (DEVASTATING en dernier, 24.10).

Fix 2 (6268) — `_advance_blocks_weapon` : `require_key(game_state, "units_advanced")` crashait
si la clé était absente (game_state construit sans `reset()`). Corrigé par
`game_state.get("units_advanced", set())`, aligné sur tous les autres appelants.
VERROU ROUGE : test avec game_state sans `units_advanced`.

Fix 3 (6122-6125) — `_attacker_model_can_reach_squad` : `_compute_unit_occupied_hexes` et `Socle`
utilisaient `base_unit` (entrée squad de units_cache) pour BASE_SHAPE/BASE_SIZE au lieu de `tm`
(figurine individuelle de models_cache). Corrigé par `tm["BASE_SHAPE"]` / `tm["BASE_SIZE"]`.
VERROU ROUGE : test avec base_unit sans BASE_SHAPE/BASE_SIZE (KeyError si bug réintroduit).
"""
from __future__ import annotations

import random
from typing import Any, Dict

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fix 1 — sort DEVASTATING_WOUNDS (ligne 9175)
# ─────────────────────────────────────────────────────────────────────────────

class TestDevastatingWoundsSortOrder:
    """Vérifie que les blessures DEVASTATING sont résolues APRÈS les blessures normales (24.10).

    Invariant : les entrées devastating=True doivent toujours être en fin de pool trié
    (elles correspondent à des blessures mortelles infligées « after resolving any normal damage »).
    Pas de verrou rouge ici (l'amélioration est défensive), mais les tests vérifient l'ordre réel.
    """

    def _pool_order(self, entries):
        """Retourne le pool trié en appliquant la même clé que ligne 9175."""
        return sorted(entries, key=lambda pw: (bool(pw.get("devastating")), pw.get("save_roll") or 0))

    def test_devastating_apres_normaux(self):
        """Un hit DEVASTATING vient APRÈS un hit normal dans le pool trié."""
        pool = [
            {"save_roll": None, "devastating": True},   # devastating → dernier
            {"save_roll": 3,    "devastating": False},  # normal → premier
        ]
        result = self._pool_order(pool)
        assert result[0]["devastating"] is False
        assert result[1]["devastating"] is True

    def test_ordre_save_dans_normaux(self):
        """Les hits normaux sont triés save_roll croissant (résolution par le plus bas en premier)."""
        pool = [
            {"save_roll": 5,    "devastating": False},
            {"save_roll": 2,    "devastating": False},
            {"save_roll": None, "devastating": True},
        ]
        result = self._pool_order(pool)
        assert result[0]["save_roll"] == 2
        assert result[1]["save_roll"] == 5
        assert result[2]["devastating"] is True

    def test_sort_production_devastating_apres_normaux(self, monkeypatch):
        """Vérifie le tri RÉEL ligne 9175 (pas _pool_order) : blessures DEVASTATING après normales.

        Mode human-defender : le batch est conservé dans game_state pendant le choix du modèle,
        ce qui permet d'inspecter pool trié AVANT résolution. Sans ce mode, l'auto-résolution
        gym vide le batch avant que le test puisse l'observer.

        Rolls [4, 6, 4, 4, 2] :
          attack 1 : hit=4, wound_crit=6 → DEVASTATING (save_roll=None)
          attack 2 : hit=4, wound=4 (normal, STR4 vs T4 → 4+), save=2 → fail (AP-1 → 3+ effectif)
        Pool résultant avant tri : [{devastating=True,save_roll=None},{devastating=False,save_roll=2}]
        Pool après tri ligne 9175 : [{devastating=False,save_roll=2},{devastating=True,save_roll=None}]
        """
        from engine.phase_handlers import shooting_handlers
        from engine.phase_handlers.shared_utils import build_manual_shoot_allocation
        from tests._state_invariants import turn_state_invariants

        SHOOTER = (50, 50)
        TARGET = (80, 50)
        weapon = {"ATK": 3, "STR": 4, "AP": -1, "DMG": 1, "NB": 2, "RNG": 120,
                  "WEAPON_RULES": ["DEVASTATING_WOUNDS"], "display_name": "DW Gun"}
        attacker = {"id": "1#0", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                    "col": SHOOTER[0], "row": SHOOTER[1], "RNG_WEAPONS": [weapon]}
        target_m = {"id": "101#0", "squad_id": "101", "player": 1, "T": 4,
                    "HP_CUR": 9, "HP_MAX": 9, "ARMOR_SAVE": 2, "INVUL_SAVE": 7,
                    "role": None, "unitType": "AssaultIntercessor", "points_per_hp": 5.0,
                    "VALUE": 10.0, "col": TARGET[0], "row": TARGET[1]}
        uc_entry = {"BASE_SHAPE": "round", "BASE_SIZE": 6, "occupied_hexes": set(), "VALUE": 10.0}
        gs: Dict[str, Any] = {
            **turn_state_invariants(),
            # pas de gym_training_mode → defender player 1 est "human"
            "player_types": {"0": "ai", "1": "human"},
            "turn": 1, "phase": "shoot",
            "action_logs": [], "action_log_seq": 0,
            "models_cache": {"1#0": attacker, "101#0": target_m},
            "squad_models": {"1": ["1#0"], "101": ["101#0"]},
            "squad_cache": {"1": {"model_count_at_start": 1}, "101": {"model_count_at_start": 1}},
            "units_cache": {
                "1": {**uc_entry, "col": SHOOTER[0], "row": SHOOTER[1], "player": 0,
                      "occupied_hexes_by_model": {"1#0": SHOOTER},
                      "floor_height_by_model": {"1#0": 0.0}},
                "101": {**uc_entry, "col": TARGET[0], "row": TARGET[1], "player": 1,
                        "occupied_hexes_by_model": {"101#0": TARGET},
                        "floor_height_by_model": {"101#0": 0.0}},
            },
            "units": [{"id": "1", "player": 0, "unitType": "SternguardVeteranBoltRifle"},
                      {"id": "101", "player": 1, "unitType": "AssaultIntercessor"}],
            "unit_by_id": {"1": {"id": "1", "UNIT_RULES": [], "deployed_on_turn": 0},
                           "101": {"id": "101", "UNIT_RULES": [], "deployed_on_turn": 0}},
            "objectives": [],
            "inches_to_subhex": 5,
            "moved_distance_by_model": {"1#0": 0.0},
            "pending_squad_shoot_intents": {
                "1": [{"model_id": "1#0", "target_unit_id": "101", "weapon_index": 0,
                       "n_attacks_resolved": 2, "target_squad_size_at_declaration": 1}]
            },
        }
        seq = [4, 6, 4, 4, 2]

        def fake_randint(a: int, b: int) -> int:
            assert seq, "sequence RNG épuisée — rolls prévus : [4, 6, 4, 4, 2]"
            return seq.pop(0)

        monkeypatch.setattr(random, "randint", fake_randint)
        monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
        monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
        monkeypatch.setattr(shooting_handlers, "_is_adjacent_to_enemy_within_cc_range", lambda gs, u: False)

        build_manual_shoot_allocation(gs, "1")

        alloc = gs.get("pending_shoot_allocation")
        assert alloc, "allocation non créée — mode human-defender devrait laisser la structure"
        assert alloc["batches"], "batches vides — au moins un batch attendu"
        pool = alloc["batches"][0]["pool"]
        # Invariant 24.10 : blessures mortelles (devastating=True) APRÈS blessures normales
        devastating_indices = [i for i, pw in enumerate(pool) if pw.get("devastating")]
        normal_indices = [i for i, pw in enumerate(pool) if not pw.get("devastating")]
        assert normal_indices and devastating_indices, (
            f"le pool devrait contenir 1 normal + 1 devastating : {pool}"
        )
        assert max(normal_indices) < min(devastating_indices), (
            f"les blessures DEVASTATING doivent être en fin de pool (24.10) : {pool}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Fix 2 — _advance_blocks_weapon sans clé units_advanced (ligne 6268)
# ─────────────────────────────────────────────────────────────────────────────

class TestAdvanceBlocksWeaponKeyMissing:
    def _gs_without_units_advanced(self) -> Dict[str, Any]:
        """game_state sans clé `units_advanced` — état impossible en production (reset manquant)."""
        gs: Dict[str, Any] = {
            "config": {"game_rules": {}},
            "inches_to_subhex": 5,
            "models_cache": {},
            "squad_models": {"1": []},
            "units_cache": {},
            "units": [],
            "unit_by_id": {},
            "objectives": [],
            # units_advanced intentionnellement absent
        }
        return gs

    def test_absence_de_units_advanced_renvoie_false(self):
        """ROUGE avant fix : require_key() levait KeyError si units_advanced manque."""
        from engine.phase_handlers.shared_utils import _advance_blocks_weapon

        gs = self._gs_without_units_advanced()
        weapon: Dict[str, Any] = {"WEAPON_RULES": [], "display_name": "Gun"}
        result = _advance_blocks_weapon(gs, "1", weapon)
        assert result is False

    def test_absence_de_units_advanced_avec_squad_non_advanced(self):
        """Idem squad "99" — aucune avance → False sans crash."""
        from engine.phase_handlers.shared_utils import _advance_blocks_weapon

        gs = self._gs_without_units_advanced()
        weapon: Dict[str, Any] = {"WEAPON_RULES": [], "display_name": "Gun"}
        assert _advance_blocks_weapon(gs, "99", weapon) is False

    def test_units_advanced_present_bloque_arme_non_assault(self, monkeypatch):
        """Régression : si units_advanced EST présent et contient "1", une arme non-ASSAULT est bloquée."""
        from engine.phase_handlers import shooting_handlers
        from engine.phase_handlers.shared_utils import _advance_blocks_weapon

        monkeypatch.setattr(
            shooting_handlers, "_can_unit_shoot_after_advance_with_weapon",
            lambda unit, weapon: False
        )
        monkeypatch.setattr(
            shooting_handlers, "_get_unit_by_id",
            lambda gs, sid: {"id": sid, "UNIT_RULES": []}
        )

        gs: Dict[str, Any] = {
            "config": {"game_rules": {}},
            "units_advanced": {"1"},
        }
        weapon: Dict[str, Any] = {"WEAPON_RULES": [], "display_name": "Plain Gun"}
        assert _advance_blocks_weapon(gs, "1", weapon) is True


# ─────────────────────────────────────────────────────────────────────────────
# Fix 3 — _attacker_model_can_reach_squad utilise tm pas base_unit (6122-6125)
# ─────────────────────────────────────────────────────────────────────────────

class TestAttackerModelCanReachSquadUsesModelBase:
    def _setup(self, monkeypatch):
        """État minimal pour _attacker_model_can_reach_squad avec base_unit sans BASE_SHAPE."""
        from engine.phase_handlers import shooting_handlers

        monkeypatch.setattr(
            shooting_handlers, "_compute_visibility_with_obscuring",
            lambda *a, **kw: (1, 1, None),
        )
        monkeypatch.setattr(
            shooting_handlers, "_ranged_distance_metric",
            lambda gs: "euclidean",
        )

        tm = {
            "id": "101#0", "squad_id": "101", "player": 1,
            "col": 5, "row": 0, "level": 0,
            "BASE_SHAPE": "round", "BASE_SIZE": 6,
            "orientation": 0,
        }
        attacker = {
            "id": "1#0", "squad_id": "1", "player": 0,
            "col": 0, "row": 0, "level": 0,
            "BASE_SHAPE": "round", "BASE_SIZE": 6,
            "orientation": 0,
        }
        # base_unit intentionnellement sans BASE_SHAPE/BASE_SIZE :
        # si le code accède base_unit["BASE_SHAPE"] (bug pre-fix) → KeyError.
        # Après fix, seul tm["BASE_SHAPE"] est accédé.
        base_unit_no_shape: Dict[str, Any] = {"player": 1, "occupied_hexes": {(5, 0)}}

        gs: Dict[str, Any] = {
            "config": {"game_rules": {"detection_range": 200, "metric": "euclidean"}},
            "inches_to_subhex": 5,
            "models_cache": {"1#0": attacker, "101#0": tm},
            "squad_models": {"1": ["1#0"], "101": ["101#0"]},
            "units_cache": {
                "1": {"player": 0, "occupied_hexes": {(0, 0)},
                      "BASE_SHAPE": "round", "BASE_SIZE": 6},
                "101": base_unit_no_shape,
            },
            "units": [{"id": "1", "player": 0}, {"id": "101", "player": 1}],
        }
        return gs, attacker, tm

    def test_base_shape_lue_depuis_tm_pas_base_unit(self, monkeypatch):
        """ROUGE avant fix : base_unit["BASE_SHAPE"] → KeyError car base_unit n'a pas ce champ.

        Verrou : si on rétablit `base_unit["BASE_SHAPE"]` à la place de `tm["BASE_SHAPE"]`,
        ce test lève KeyError sur le base_unit sans BASE_SHAPE."""
        from engine.phase_handlers.shared_utils import _attacker_model_can_reach_squad

        gs, attacker, _tm = self._setup(monkeypatch)
        result = _attacker_model_can_reach_squad(gs, attacker, 0, 0, "101", 50)
        assert result is True

    def test_modele_hors_portee_renvoie_false(self, monkeypatch):
        """Régression : un modèle trop loin reste non atteignable même après le fix.

        BASE_SIZE=6 = diamètre 6 hexes → rayon 3 hexes. Cible à (5,0) : footprints
        se chevauchent (5 < 3+3), edge=0. On met la cible à (100,0) : edge = 94 >> 5."""
        from engine.phase_handlers.shared_utils import _attacker_model_can_reach_squad

        gs, attacker, _tm = self._setup(monkeypatch)
        # déplace la cible loin
        gs["models_cache"]["101#0"]["col"] = 100
        gs["units_cache"]["101"]["occupied_hexes"] = {(100, 0)}
        result = _attacker_model_can_reach_squad(gs, attacker, 0, 0, "101", 5)
        assert result is False

    def test_model_height_lu_depuis_base_unit_pas_tm_quand_cible_elevee(self, monkeypatch):
        """Couvre la branche 3D LoS (line 6150) : MODEL_HEIGHT lu depuis base_unit, pas tm.

        Verrou : si on remplace `require_key(base_unit, 'MODEL_HEIGHT')` par
        `require_key(tm, 'MODEL_HEIGHT')` (ligne 6155), ce test lève KeyError car
        tm (models_cache) ne porte pas MODEL_HEIGHT — c'est un attribut squad (units_cache).

        Configuration : cible à level=1 (étage), tireur au sol (level=0). La branche
        `if shooter_level >= 1 or target_level >= 1` devient True, exécutant ligne 6155.
        """
        from engine.phase_handlers import shooting_handlers
        from engine.phase_handlers.shared_utils import _attacker_model_can_reach_squad

        monkeypatch.setattr(
            shooting_handlers, "_compute_visibility_with_obscuring",
            lambda *a, **kw: (1, 1, None),
        )
        monkeypatch.setattr(
            shooting_handlers, "_ranged_distance_metric",
            lambda gs: "euclidean",
        )
        monkeypatch.setattr(
            shooting_handlers, "_fig_z_and_occluder",
            lambda gs, level, hexes, mh: (mh, None),
        )

        # tm n'a pas MODEL_HEIGHT : les models_cache ne le portent jamais (c'est squad-level).
        # Si le code lit tm["MODEL_HEIGHT"] (bug), KeyError. S'il lit base_unit (correct), OK.
        tm = {
            "id": "101#0", "squad_id": "101", "player": 1,
            "col": 5, "row": 0, "level": 1,          # ← à l'étage : active la branche 3D
            "BASE_SHAPE": "round", "BASE_SIZE": 6,
            "orientation": 0,
            # PAS de MODEL_HEIGHT ici — c'est un attribut squad, pas par-figurine
        }
        attacker = {
            "id": "1#0", "squad_id": "1", "player": 0,
            "col": 0, "row": 0, "level": 0,
            "BASE_SHAPE": "round", "BASE_SIZE": 6,
            "orientation": 0,
        }
        base_unit_no_shape: Dict[str, Any] = {
            "player": 1,
            "occupied_hexes": {(5, 0)},
            "MODEL_HEIGHT": 3.0,  # lu par require_key(base_unit, "MODEL_HEIGHT") ligne 6155
            # PAS de BASE_SHAPE/BASE_SIZE → verrou fix 3 (utilise tm, pas base_unit)
        }
        gs: Dict[str, Any] = {
            "config": {"game_rules": {"detection_range": 200, "metric": "euclidean"}},
            "inches_to_subhex": 5,
            "models_cache": {"1#0": attacker, "101#0": tm},
            "squad_models": {"1": ["1#0"], "101": ["101#0"]},
            "units_cache": {
                "1": {"player": 0, "occupied_hexes": {(0, 0)},
                      "BASE_SHAPE": "round", "BASE_SIZE": 6,
                      "MODEL_HEIGHT": 2.0},   # lu ligne 6153 (shooter au sol, cible élevée)
                "101": base_unit_no_shape,
            },
            "units": [{"id": "1", "player": 0}, {"id": "101", "player": 1}],
        }
        result = _attacker_model_can_reach_squad(gs, attacker, 0, 0, "101", 50)
        assert result is True
