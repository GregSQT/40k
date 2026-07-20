"""Tests de non-regression — VALUE par figurine (§0.12 de V11_agent_rework.md).

Trois invariants :
  A/B — `points_per_hp` est calcule PAR FIGURINE (`VALUE_i / HP_MAX_i`) et la cle
        `VALUE` est portee par `models_cache`.
  C   — le reward de kill lit la VALUE de la figurine detruite, plus la moyenne
        d'escouade (`value / model_count_at_start`).

Piege verrouille ici (cf. §0.12) : l'invariant n'est PAS « meme profil => identique »
mais « VALUE UNIFORME sur toutes les figurines => identique a l'ancienne formule ».
Une escouade homogene en profil peut etre heterogene en points (Boyz : 9 x 7 + Nob 12).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from engine.phase_handlers.shared_utils import build_units_cache
from shared.data_validation import ConfigurationError
from engine.reward_calculator import RewardCalculator


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _unit(uid: int, value: int, hp_max: int, models: List[Dict[str, Any]] | None) -> Dict[str, Any]:
    """Unite minimale acceptee par build_units_cache. `models=None` => mono-figurine."""
    u: Dict[str, Any] = {
        "id": uid,
        "player": 1,
        "col": 5,
        "row": 5,
        "HP_CUR": hp_max,
        "HP_MAX": hp_max,
        "VALUE": value,
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
        "CC_WEAPONS": [],
        "selectedRngWeaponIndex": 0,
        "selectedCcWeaponIndex": 0,
    }
    if models is not None:
        u["models"] = models
        # Invariant moteur : l'ancre de l'unite doit egaler la position de models[0].
        u["col"] = models[0]["col"]
        u["row"] = models[0]["row"]
    return u


_GAME_RULES = json.loads(
    (Path(__file__).parents[3] / "config" / "game_config.json").read_text()
)["game_rules"]


def _models_cache(unit: Dict[str, Any]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {**_GAME_RULES, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 40,
        "board_rows": 40,
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": [unit],
        "unit_by_id": {str(unit["id"]): unit},
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    return gs["models_cache"]


def _calculator() -> RewardCalculator:
    return RewardCalculator(config={"quiet": True}, rewards_config={}, unit_registry=None, state_manager=None)


_SHAPING = {"hp_damage_weight": 1.0, "model_kill_bonus_factor": 1.0, "squad_kill_bonus_factor": 0.0}


def _combat(events: List[Dict[str, Any]], squad_value: int, mcs: int) -> Dict[str, Any]:
    return {
        "events": events,
        "squads_wiped": [],
        "targets_meta": {"9": {"value": squad_value, "model_count_at_start": mcs, "player": 2}},
    }


def _event(*, model_value: float, points_per_hp: float, damage: int, destroyed: bool) -> Dict[str, Any]:
    return {
        "target_squad_id": "9",
        "target_player": 2,
        "points_per_hp": points_per_hp,
        "damage": damage,
        "destroyed": destroyed,
        "model_value": model_value,
    }


# ─────────────────────────────────────────────────────────────────────────────
# A/B — models_cache : VALUE et points_per_hp par figurine
# ─────────────────────────────────────────────────────────────────────────────

class TestModelsCacheValuePerFigurine:
    def test_mono_figurine_identique_a_lancienne_formule(self):
        """Mono-fig : VALUE fig = VALUE unite, points_per_hp = VALUE / HP_MAX (inchange)."""
        mc = _models_cache(_unit(1, value=75, hp_max=5, models=None))
        assert len(mc) == 1
        entry = mc["1#0"]
        assert entry["VALUE"] == 75
        assert entry["points_per_hp"] == pytest.approx(75.0 / 5.0)

    def test_value_uniforme_identique_a_lancienne_formule(self):
        """VALUE uniforme (Gretchin 10 x 5) : per-fig == VALUE_escouade / total_hp_pool."""
        models = [{"col": c, "row": 5, "VALUE": 5} for c in range(10)]
        mc = _models_cache(_unit(1, value=50, hp_max=1, models=models))
        ancienne = 50.0 / (10 * 1.0)  # VALUE escouade / somme(HP_MAX_i)
        assert len(mc) == 10
        for mid, entry in mc.items():
            assert entry["VALUE"] == 5
            assert entry["points_per_hp"] == pytest.approx(ancienne), mid

    def test_value_heterogene_differencie_les_figurines(self):
        """Boyz : 9 x 7 + Nob 12 — meme profil, VALUE differentes (piege §0.12)."""
        models = [{"col": c, "row": 5, "VALUE": 7} for c in range(9)]
        models.append({"col": 9, "row": 5, "VALUE": 12})
        mc = _models_cache(_unit(1, value=75, hp_max=1, models=models))
        assert mc["1#0"]["points_per_hp"] == pytest.approx(7.0)
        assert mc["1#9"]["points_per_hp"] == pytest.approx(12.0)
        # L'ancienne formule aurait donne 7.5 partout — elle ne doit plus apparaitre.
        assert all(e["points_per_hp"] != pytest.approx(75.0 / 10.0) for e in mc.values())

    def test_hp_max_par_figurine_divise_bien_par_son_propre_hp(self):
        """HP_MAX heterogene : points_per_hp_i = VALUE_i / HP_MAX_i, pas / somme."""
        models = [
            {"col": 0, "row": 5, "VALUE": 20, "HP_MAX": 2},
            {"col": 1, "row": 5, "VALUE": 30, "HP_MAX": 3},
        ]
        mc = _models_cache(_unit(1, value=50, hp_max=2, models=models))
        assert mc["1#0"]["points_per_hp"] == pytest.approx(10.0)
        assert mc["1#1"]["points_per_hp"] == pytest.approx(10.0)

    def test_value_absente_leve(self):
        """Pas de valeur par defaut masquant la donnee absente (CLAUDE.md)."""
        models = [{"col": 0, "row": 5}]
        with pytest.raises(ConfigurationError, match="VALUE"):
            _models_cache(_unit(1, value=50, hp_max=1, models=models))

    def test_hp_max_invalide_leve_toujours(self):
        """La validation HP_MAX <= 0 survit au deplacement dans la boucle unique."""
        models = [{"col": 0, "row": 5, "VALUE": 5, "HP_MAX": 0}]
        with pytest.raises(ValueError, match="invalid HP_MAX"):
            _models_cache(_unit(1, value=50, hp_max=1, models=models))


# ─────────────────────────────────────────────────────────────────────────────
# C — reward de kill : VALUE de la figurine detruite
# ─────────────────────────────────────────────────────────────────────────────

class TestSquadCombatShapingModelValue:
    def _shape(self, events: List[Dict[str, Any]], squad_value: int, mcs: int) -> float:
        calc = _calculator()
        return calc._squad_combat_shaping(_combat(events, squad_value, mcs), lambda p: p == 2, _SHAPING)

    def test_mono_figurine_bit_identique(self):
        """mcs == 1 : model_value == VALUE unite => resultat inchange."""
        ev = _event(model_value=75.0, points_per_hp=15.0, damage=5, destroyed=True)
        # Ancienne formule : value / mcs = 75 / 1 = 75. Identique.
        assert self._shape([ev], squad_value=75, mcs=1) == pytest.approx(15.0 * 5 + 75.0)

    def test_value_uniforme_identique_a_lancienne_formule(self):
        """Gretchin 10 x 5 : model_value 5 == 50 / 10 => resultat inchange."""
        ev = _event(model_value=5.0, points_per_hp=5.0, damage=1, destroyed=True)
        ancienne = 5.0 * 1 + (50.0 / 10)
        assert self._shape([ev], squad_value=50, mcs=10) == pytest.approx(ancienne)

    def test_figurine_chere_rapporte_strictement_plus(self):
        """Boyz 9 x 7 + Nob 12 : tuer le Nob > tuer un Boy (signal de ciblage)."""
        # hp_damage_weight = 0 : le seul terme restant est le bonus de kill, donc le
        # test rougit si le kill relit la moyenne d'escouade (mutation-teste).
        calc = _calculator()
        shaping = {**_SHAPING, "hp_damage_weight": 0.0}
        boy = _event(model_value=7.0, points_per_hp=7.0, damage=1, destroyed=True)
        nob = _event(model_value=12.0, points_per_hp=12.0, damage=1, destroyed=True)
        r_boy = calc._squad_combat_shaping(_combat([boy], 75, 10), lambda p: p == 2, shaping)
        r_nob = calc._squad_combat_shaping(_combat([nob], 75, 10), lambda p: p == 2, shaping)
        assert r_nob > r_boy
        # L'ancienne formule rendait les deux egaux (moyenne 7.5) — non-regression.
        assert r_boy != pytest.approx(r_nob)

    def test_bonus_de_wipe_reste_sur_la_valeur_descouade(self):
        """Ne PAS convertir le wipe par figurine : c'est l'escouade entiere (§0.12)."""
        calc = _calculator()
        combat = _combat([], squad_value=75, mcs=10)
        combat["squads_wiped"] = ["9"]
        shaping = {**_SHAPING, "squad_kill_bonus_factor": 2.0}
        assert calc._squad_combat_shaping(combat, lambda p: p == 2, shaping) == pytest.approx(150.0)

    def test_event_sans_model_value_leve(self):
        """Un event destroyed sans la cle leve — pas de retour silencieux a la moyenne."""
        ev = _event(model_value=7.0, points_per_hp=7.0, damage=1, destroyed=True)
        del ev["model_value"]
        with pytest.raises(ConfigurationError, match="model_value"):
            self._shape([ev], squad_value=75, mcs=10)

    def test_victime_du_mauvais_joueur_ignoree(self):
        """Garde is_victim inchangee par le portage."""
        ev = _event(model_value=12.0, points_per_hp=12.0, damage=1, destroyed=True)
        calc = _calculator()
        assert calc._squad_combat_shaping(_combat([ev], 75, 10), lambda p: p == 1, _SHAPING) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# D — observation : value_over_ttk somme la VALUE PAR FIGURINE
# ─────────────────────────────────────────────────────────────────────────────
# 4e rupture, non recensee par l'enonce d'origine de §0.12 et introduite EN
# REGRESSION par les etapes A/B : observation_builder extrapolait le
# points_per_hp de la figurine d'index 0 a toute l'escouade. Uniforme avant A/B,
# donc exact ; faux des que l'escouade est heterogene en points.
# L'invariant teste ici est le plus fort disponible : le resultat ne doit pas
# dependre de l'ORDRE des figurines dans l'escouade.

class TestObservationValueOverTtk:
    _SLOT_VALUE_OVER_TTK = 63 + 7  # base du slot ennemi 0 + offset value_over_ttk

    def _obs_enemy_slot0(self, enemy_models: List[Dict[str, Any]]) -> float:
        from engine.observation_builder import ObservationBuilder

        ally = _unit(1, value=20, hp_max=2, models=None)
        ally["player"] = 1
        ally["col"], ally["row"] = 10, 10
        ally["RNG_WEAPONS"] = [{"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24, "WEAPON_RULES": []}]
        ally["selectedRngWeaponIndex"] = 0

        enemy = _unit(2, value=75, hp_max=1, models=enemy_models)
        enemy["player"] = 2

        gs: Dict[str, Any] = {
            "config": {
                "game_rules": {**_GAME_RULES, "max_base_size_hex": 35},
                "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
            },
            "board_cols": 40,
            "board_rows": 40,
            "wall_hexes": set(),
            "terrain_areas": [],
            "objectives": [],
            "units": [ally, enemy],
            "unit_by_id": {"1": ally, "2": enemy},
            "current_player": 1,
            "phase": "shoot",
            "inches_to_subhex": 1,
        }
        build_units_cache(gs)
        builder = ObservationBuilder({
            "observation_params": {
                "perception_radius": 25, "max_nearby_units": 6,
                "max_valid_targets": 5, "obs_size": 357,
            }
        })
        return float(builder.build_squad_observation(gs, "1")[self._SLOT_VALUE_OVER_TTK])

    def _boyz(self, nob_index: int) -> List[Dict[str, Any]]:
        """9 Boyz a 7 pts + 1 Nob a 12, le Nob place a `nob_index`."""
        models = [{"col": 20 + i, "row": 20, "VALUE": 7} for i in range(10)]
        models[nob_index]["VALUE"] = 12
        return models

    def test_invariant_a_lordre_des_figurines(self):
        """Le Nob en tete ou en queue : meme value_over_ttk (rouge avant le fix)."""
        nob_premier = self._obs_enemy_slot0(self._boyz(nob_index=0))
        nob_dernier = self._obs_enemy_slot0(self._boyz(nob_index=9))
        assert nob_premier > 0.0
        assert nob_premier == pytest.approx(nob_dernier)

    def test_escouade_chere_vaut_plus_quune_escouade_bon_marche(self):
        """Le signal reste monotone en points (garde-fou de sens)."""
        gretchins = [{"col": 20 + i, "row": 20, "VALUE": 5} for i in range(10)]
        assert self._obs_enemy_slot0(self._boyz(nob_index=0)) > self._obs_enemy_slot0(gretchins)
