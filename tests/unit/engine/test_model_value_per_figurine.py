"""Tests de non-regression — VALUE par figurine (§0.12 de index_v11.md).

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

from tests.unit.engine._config_helpers import NEUTRAL_TEST_ARMY_FACTION, NEUTRAL_TEST_FACTION
from engine.phase_handlers.shared_utils import build_units_cache
from shared.data_validation import ConfigurationError
from engine.reward_calculator import RewardCalculator
from tests._state_invariants import turn_state_invariants, unit_invariants


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _unit(uid: int, value: int, hp_max: int, models: List[Dict[str, Any]] | None) -> Dict[str, Any]:
    """Unite minimale acceptee par build_units_cache. `models=None` => mono-figurine."""
    u: Dict[str, Any] = {**unit_invariants(),
        "id": uid,
        "player": 1,
        "col": 5,
        "row": 5,
        "HP_CUR": hp_max,
        "HP_MAX": hp_max,
        "VALUE": value,
        # L'autre moitie de la declaration `army_faction` de la config : la garde anti-coquille
        # refuse une faction que personne ne porte (cf. NEUTRAL_TEST_FACTION).
        "FACTION_KEYWORDS": [NEUTRAL_TEST_FACTION],
        # Jumeau de `FACTION_KEYWORDS` ci-dessus, et la clé est OBLIGATOIRE : l'observation lit
        # les mots-clés de catégorie de chaque entité (`kw_infantry`… dans `UNIT_BIN_FIELDS`) et
        # refuse une unité qui n'en déclare aucune liste. Vide : ces unités minimales n'exercent
        # aucune règle de catégorie, et une liste vide dit « aucun mot-clé déclaré » — c'est la
        # convention déjà portée par la config d'entrée de `test_state_manager.py`.
        "UNIT_KEYWORDS": [],
        "OC": 1,
        # Ld : caracteristique de datasheet OBLIGATOIRE, exactement comme `UNIT_KEYWORDS`
        # ci-dessus. L'observation la lit pour chaque entite (`leadership` dans
        # `UNIT_CONT_FIELDS`, seuil de 01.06/08.03) via `unit_effective_leadership`, qui refuse
        # une figurine sans Ld : une escouade qui n'en declare aucun ne peut pas faire de jet de
        # commandement, et l'inventer serait un seuil faux servi en silence.
        "LD": 6,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        # Hauteur modele (pouces) : borne haute de l'intervalle vertical de l'engagement 3D
        # (§03.04). EXIGEE par build_units_cache depuis que toute la phase de combat passe
        # `vertical_zone_inches` — une unite reelle la porte toujours (game_state.py).
        "MODEL_HEIGHT": 2.5,
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
    gs: Dict[str, Any] = {**turn_state_invariants(),
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


_SHAPING = {"hp_damage_weight": 1.0, "model_kill_bonus_factor": 1.0, "squad_kill_bonus_factor": 0.0,
            "reward_on_expectation": False}


def _combat(events: List[Dict[str, Any]], squad_value: int, mcs: int) -> Dict[str, Any]:
    return {
        "events": events,
        "squads_wiped": [],
        "expected_damage_by_target": {},
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
# D — observation : la VALUE d'une escouade ennemie somme la VALUE PAR FIGURINE
# ─────────────────────────────────────────────────────────────────────────────
# 4e rupture, non recensee par l'enonce d'origine de §0.12 et introduite EN
# REGRESSION par les etapes A/B : observation_builder extrapolait le
# points_per_hp de la figurine d'index 0 a toute l'escouade. Uniforme avant A/B,
# donc exact ; faux des que l'escouade est heterogene en points.
# L'invariant teste ici est le plus fort disponible : le resultat ne doit pas
# dependre de l'ORDRE des figurines dans l'escouade.
#
# Refonte V11 (V11_audit_observation.md §9.1) : la feature calculee `value_over_ttk`
# a ete SUPPRIMEE de l'observation au profit de la donnee brute — la VALUE vivante
# de l'escouade ennemie (bloc D). L'invariant, lui, est inchange et porte desormais
# sur cette dimension : c'est toujours une somme PAR FIGURINE.

class TestObservationEnemySquadValue:

    def _obs_enemy_slot0(self, enemy_models: List[Dict[str, Any]]) -> float:
        from engine.observation_builder import ObservationBuilder

        ally = _unit(1, value=20, hp_max=2, models=None)
        ally["player"] = 1
        ally["col"], ally["row"] = 10, 10
        ally["RNG_WEAPONS"] = [{"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24, "WEAPON_RULES": [], "code": "test_weapon"}]
        ally["selectedRngWeaponIndex"] = 0

        enemy = _unit(2, value=75, hp_max=1, models=enemy_models)
        enemy["player"] = 2

        gs: Dict[str, Any] = {**turn_state_invariants(),
            "config": {
                "game_rules": {**_GAME_RULES, "max_base_size_hex": 35},
                "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
                # Config LITTERALE : elle porte sa declaration elle-meme (cf.
                # NEUTRAL_TEST_ARMY_FACTION).
                "army_faction": dict(NEUTRAL_TEST_ARMY_FACTION),
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
            # Distance parcourue ce tour (V11 §9.2.5) : partie du contrat d etat, au meme titre
            # que `units_moved`. Vide = personne n a bouge.
            "moved_distance_by_model": {},
        }
        build_units_cache(gs)
        builder = ObservationBuilder({
            "observation_params": {
                "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
            }
        })
        gs["victory_points"] = {1: 0, 2: 0}
        from engine.observation_entities import unit_cont_index

        cont = builder.build_squad_observation(gs, "1")["enemies_cont"][0]
        return float(cont[unit_cont_index("value_alive")])

    def _boyz(self, nob_index: int) -> List[Dict[str, Any]]:
        """9 Boyz a 7 pts + 1 Nob a 12, le Nob place a `nob_index`."""
        models = [{"col": 20 + i, "row": 20, "VALUE": 7} for i in range(10)]
        models[nob_index]["VALUE"] = 12
        return models

    def test_invariant_a_lordre_des_figurines(self):
        """Le Nob en tete ou en queue : meme VALUE d'escouade (rouge avant le fix)."""
        nob_premier = self._obs_enemy_slot0(self._boyz(nob_index=0))
        nob_dernier = self._obs_enemy_slot0(self._boyz(nob_index=9))
        assert nob_premier > 0.0
        assert nob_premier == pytest.approx(nob_dernier)

    def test_escouade_chere_vaut_plus_quune_escouade_bon_marche(self):
        """Le signal reste monotone en points (garde-fou de sens)."""
        gretchins = [{"col": 20 + i, "row": 20, "VALUE": 5} for i in range(10)]
        assert self._obs_enemy_slot0(self._boyz(nob_index=0)) > self._obs_enemy_slot0(gretchins)


# ─────────────────────────────────────────────────────────────────────────────
# S11 — `reward_on_expectation` : la récompense lit l'espérance, pas les événements
# ─────────────────────────────────────────────────────────────────────────────


def _combat_s11(*, expected: float, alive: int, hp_max: int, events: List[Dict[str, Any]],
                player: int = 2, hp_before: int | None = None) -> Dict[str, Any]:
    return {
        "events": events,
        "squads_wiped": [],
        "expected_damage_by_target": {"9": expected},
        "targets_meta": {"9": {
            "value": 75, "model_count_at_start": 10, "player": player,
            "alive_count": alive, "hp_max": hp_max,
            "hp_before": alive * hp_max if hp_before is None else hp_before,
            "points_per_hp_mean": 5.0, "model_value_mean": 10.0,
        }},
    }


class TestS11RewardOnExpectation:
    _ON = {**_SHAPING, "reward_on_expectation": True}

    def test_l_esperance_remplace_le_jet(self):
        """E[dmg] 1,5 sur des figurines à 1 PV (3 vivantes) : 5 × 1,5 + 10 × min(1,5, 3) = 22,5,
        quels que soient les événements réels (ici un jet à 2 dégâts et un kill)."""
        calc = _calculator()
        ev = _event(model_value=10.0, points_per_hp=5.0, damage=2, destroyed=True)
        combat = _combat_s11(expected=1.5, alive=3, hp_max=1, events=[ev])
        assert calc._squad_combat_shaping(combat, lambda p: p == 2, self._ON) == pytest.approx(22.5)
        # Même choix, jet nul : même récompense.
        combat_miss = _combat_s11(expected=1.5, alive=3, hp_max=1, events=[])
        assert calc._squad_combat_shaping(combat_miss, lambda p: p == 2, self._ON) == pytest.approx(22.5)

    def test_le_drapeau_a_faux_garde_l_ancienne_formule(self):
        calc = _calculator()
        ev = _event(model_value=10.0, points_per_hp=5.0, damage=2, destroyed=True)
        combat = _combat_s11(expected=1.5, alive=3, hp_max=1, events=[ev])
        assert calc._squad_combat_shaping(combat, lambda p: p == 2, _SHAPING) == pytest.approx(5.0 * 2 + 10.0)

    def test_les_figurines_tuees_esperees_sont_plafonnees_par_les_vivantes(self):
        """E[dmg] 10 sur 3 figurines à 1 PV (3 PV restants) : dégâts = min(10, 3) = 3, kills =
        min(10, 3) = 3 -> 5 × 3 + 10 × 3 = 45. Le jet ne retire jamais plus que les PV restants ;
        20 attaques sur un Grot ne paient pas 2,5 PV."""
        calc = _calculator()
        combat = _combat_s11(expected=10.0, alive=3, hp_max=1, events=[])
        assert calc._squad_combat_shaping(combat, lambda p: p == 2, self._ON) == pytest.approx(45.0)

    def test_les_degats_esperes_sont_plafonnes_par_les_pv_restants(self):
        """Escouade déjà blessée : 5 vivantes à 2 PV mais 6 PV restants ; E[dmg] 8 -> dégâts 6."""
        calc = _calculator()
        combat = _combat_s11(expected=8.0, alive=5, hp_max=2, events=[], hp_before=6)
        # dégâts 5 × 6 = 30 ; kills min(8/2, 5) = 4 -> 10 × 4 = 40.
        assert calc._squad_combat_shaping(combat, lambda p: p == 2, self._ON) == pytest.approx(70.0)

    def test_hp_max_divise_les_kills_esperes(self):
        """E[dmg] 3 sur des figurines à 2 PV : kills = 1,5 -> 5 × 3 + 10 × 1,5 = 30."""
        calc = _calculator()
        combat = _combat_s11(expected=3.0, alive=5, hp_max=2, events=[])
        assert calc._squad_combat_shaping(combat, lambda p: p == 2, self._ON) == pytest.approx(30.0)

    def test_victime_du_mauvais_joueur_ignoree(self):
        calc = _calculator()
        combat = _combat_s11(expected=3.0, alive=5, hp_max=2, events=[], player=1)
        assert calc._squad_combat_shaping(combat, lambda p: p == 2, self._ON) == 0.0

    def test_le_bonus_de_wipe_reste_sur_le_resultat_reel(self):
        calc = _calculator()
        shaping = {**self._ON, "squad_kill_bonus_factor": 2.0}
        combat = _combat_s11(expected=0.0, alive=1, hp_max=1, events=[])
        combat["squads_wiped"] = ["9"]
        assert calc._squad_combat_shaping(combat, lambda p: p == 2, shaping) == pytest.approx(150.0)

    def test_drapeau_absent_ou_non_booleen_leve(self):
        calc = _calculator()
        combat = _combat_s11(expected=1.0, alive=1, hp_max=1, events=[])
        with pytest.raises(Exception):
            calc._squad_combat_shaping(combat, lambda p: p == 2, {k: v for k, v in _SHAPING.items() if k != "reward_on_expectation"})
        with pytest.raises(ValueError, match="booleen"):
            calc._squad_combat_shaping(combat, lambda p: p == 2, {**_SHAPING, "reward_on_expectation": 1})
