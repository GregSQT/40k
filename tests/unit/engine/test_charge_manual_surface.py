"""Surface PvP manuelle de la charge — verrous de la décision, pas seulement de l'appel.

Pourquoi ce fichier existe. Les six fonctions ci-dessous sont ATTEINTES par
``tests/integration/pvp/test_charge.py`` (mesuré : 1 à 6 appels chacune), mais ce chemin ne
joue que le scénario nominal — une escouade mono-figurine qui charge une cible unique et
réussit. Les branches de REFUS n'étaient exécutées par aucun test du dépôt (couverture ligne
mesurée avant ce fichier : 62 % à 89 %, tous les trous du côté « non »). Or ce sont elles qui
portent les règles : « end closer » (11.04 WHILE MOVING), « aucun ennemi non déclaré »
(11.04 AFTER MOVING), la cohérence d'unité (03.03), la couverture du plan par toutes les
figurines vivantes. Une correction fausse sur ces branches passait au vert.

Chaque test CONSTRUIT sa situation (positions posées explicitement) et vérifie ses propres
prémisses avant d'observer le refus : sans cela un refus pour la mauvaise raison compterait
comme un verrou.

Règles citées : Documentation/40k_rules/11 Charge phase, /03 Moving.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

from engine.phase_handlers import charge_handlers as ch
from engine.phase_handlers.shared_utils import build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants


# ─────────────────────────────────────────────────────────────────────────────
# Harnais : plateau nu (ni mur ni terrain), échelle 1 sous-hex = 1", bases 1 hex.
# Toute la géométrie est donc lisible directement dans les coordonnées du test.
# ─────────────────────────────────────────────────────────────────────────────

def _unit(uid: str, player: int, models: Sequence[Tuple[int, int]]) -> Dict[str, Any]:
    col, row = models[0]
    return {**unit_invariants(),
        "id": uid, "player": player, "col": col, "row": row,
        "HP_CUR": len(models), "HP_MAX": len(models), "VALUE": 100, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round", "MOVE": 6, "UNIT_RULES": [],
        "models": [{"col": c, "row": r, "VALUE": 10} for c, r in models],
    }


def _make_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {
                # Déjà en sous-hex (w40k_core pré-scale à l'init) ; ici inches_to_subhex=1.
                "engagement_zone": 1,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
                "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
            },
            "charge": {"charge_max_distance": 12},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 60, "board_rows": 60,
        "current_player": 1,
        "phase": "charge",
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(), "units_fled": set(),
        "units_cannot_charge": set(), "units_advanced": set(),
        "units_took_to_skies_charge": set(),
        "_unit_move_version": 0,
        "inches_to_subhex": 1,
        "charge_roll_values": {},
        "charge_target_selections": {},
        "charge_activation_pool": [],
        "action_logs": [],
        "action_log_seq": 0,
        "current_turn": 1,
    }
    build_units_cache(gs)
    return gs


def _footprint_distance(gs: Dict[str, Any], a: str, b: str) -> int:
    from engine.hex_utils import min_distance_between_sets

    return min_distance_between_sets(
        gs["units_cache"][a]["occupied_hexes"], gs["units_cache"][b]["occupied_hexes"]
    )


def _activated(gs: Dict[str, Any], unit_id: str, roll: int) -> None:
    """Met l'unité dans l'état « activée, jet fait » du flux PvP (roll-first, 11.02)."""
    gs["charge_activation_pool"] = [unit_id]
    gs["active_charge_unit"] = unit_id
    gs["charge_roll_values"][unit_id] = roll


# ─────────────────────────────────────────────────────────────────────────────
# charge_build_valid_targets — quelles cibles sont DÉCLARABLES (11.02 / 11.04 BEFORE)
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildValidTargets:
    def test_an_enemy_already_engaged_is_not_declarable(self):
        """11.02 : une unité déjà en zone d'engagement d'un ennemi ne peut pas le charger.

        Le filtre est PAR ENNEMI (charge_handlers.py:2903) : un ennemi au contact est écarté
        sans écarter l'ennemi lointain, qui reste une cible légale.
        """
        gs = _make_gs([
            _unit("1", 1, [(10, 10)]),
            _unit("close", 2, [(11, 10)]),   # adjacent → dans la zone d'engagement (1)
            _unit("far", 2, [(15, 10)]),     # à 4 hexes → chargeable avec un jet de 6
        ])
        zone = int(gs["config"]["game_rules"]["engagement_zone"])
        assert _footprint_distance(gs, "1", "close") <= zone, "prémisse : 'close' doit être engagée"
        assert _footprint_distance(gs, "1", "far") > zone, "prémisse : 'far' ne doit pas l'être"

        ids = {t["id"] for t in ch.charge_build_valid_targets(gs, "1", max_distance=6)}

        assert "close" not in ids, "un ennemi déjà engagé est proposé comme cible de charge (11.02)"
        assert "far" in ids, "l'ennemi lointain a disparu : le filtre écarte trop"

    def test_the_target_cache_follows_the_move_version(self):
        """Le mémo est indexé sur ``_unit_move_version`` : une figurine qui bouge le périme.

        Sans cette indexation, une charge déclarée après un déplacement lirait des cibles
        calculées depuis l'ancienne position — un pool périmé, donc des cibles inatteignables.
        """
        gs = _make_gs([
            _unit("1", 1, [(10, 10)]),
            _unit("2", 2, [(20, 10)]),   # hors d'atteinte d'un jet de 6 (10 hexes)
        ])
        assert not ch.charge_build_valid_targets(gs, "1", max_distance=6), (
            "prémisse : la cible doit être hors de portée au départ"
        )

        from engine.phase_handlers.shared_utils import update_model_position

        update_model_position(gs, "1#0", 16, 10)
        gs["_unit_move_version"] += 1

        ids = {t["id"] for t in ch.charge_build_valid_targets(gs, "1", max_distance=6)}
        assert ids == {"2"}, "le mémo a resservi un pool calculé avant le déplacement"


# ─────────────────────────────────────────────────────────────────────────────
# _charge_model_pos_is_closer — la légalité d'UNE position de figurine (11.04)
# ─────────────────────────────────────────────────────────────────────────────

class TestModelPositionLegality:
    def _duel(self):
        """Chargeur 1 figurine en (10,10), cible unique en (16,10)."""
        gs = _make_gs([_unit("1", 1, [(10, 10)]), _unit("2", 2, [(16, 10)])])
        return gs, gs["unit_by_id"]["1"]

    def test_a_destination_that_does_not_close_the_gap_is_refused(self):
        """11.04 WHILE MOVING : « Each model must end its move closer to one or more targets ».

        Une destination à distance ÉGALE au départ ne rapproche pas : elle est illégale même si
        elle est dans le budget et libre.
        """
        gs, unit = self._duel()
        # (10,11) est à la même distance de (16,10) que (10,10) : latéral pur.
        from engine.hex_utils import min_distance_between_sets

        start = min_distance_between_sets({(10, 10)}, {(16, 10)})
        side = min_distance_between_sets({(10, 11)}, {(16, 10)})
        assert side >= start, "prémisse : la case latérale ne doit pas rapprocher"

        assert ch._charge_model_pos_is_closer(gs, unit, "1#0", 10, 11, ["2"], 6, {}) is False
        # Contrôle positif : la même figurine, même budget, vers l'avant → légale.
        assert ch._charge_model_pos_is_closer(gs, unit, "1#0", 14, 10, ["2"], 6, {}) is True

    def test_a_destination_engaging_an_undeclared_enemy_is_refused(self):
        """11.04 AFTER MOVING : « Your unit cannot be engaged with enemy units that are not
        charge targets ». La position rapproche bien de la cible, mais met la figurine au
        contact d'un ennemi NON déclaré : elle est refusée pour cette seule raison.
        """
        gs = _make_gs([
            _unit("1", 1, [(10, 10)]),
            _unit("2", 2, [(16, 10)]),
            _unit("bystander", 2, [(14, 11)]),
        ])
        unit = gs["unit_by_id"]["1"]
        zone = int(gs["config"]["game_rules"]["engagement_zone"])
        from engine.hex_utils import min_distance_between_sets

        assert min_distance_between_sets({(14, 10)}, {(14, 11)}) <= zone, (
            "prémisse : la destination doit engager le non-cible"
        )
        assert min_distance_between_sets({(14, 10)}, {(16, 10)}) < min_distance_between_sets(
            {(10, 10)}, {(16, 10)}
        ), "prémisse : la destination doit rapprocher de la cible déclarée"

        assert ch._charge_model_pos_is_closer(gs, unit, "1#0", 14, 10, ["2"], 6, {}) is False
        # La même destination redevient légale si l'ennemi gênant est DÉCLARÉ.
        assert ch._charge_model_pos_is_closer(
            gs, unit, "1#0", 14, 10, ["2", "bystander"], 6, {}
        ) is True

    def test_a_teammate_already_placed_blocks_the_destination(self):
        """03 « Ending a move » : deux figurines ne peuvent pas se chevaucher. La coéquipière
        déjà posée dans le plan provisoire occupe la case → destination refusée.
        """
        gs = _make_gs([_unit("1", 1, [(10, 10), (10, 11)]), _unit("2", 2, [(16, 10)])])
        unit = gs["unit_by_id"]["1"]
        # Sans coéquipière posée là, la case est légale : c'est le contrôle qui rend le refus
        # attribuable à la collision et à rien d'autre.
        assert ch._charge_model_pos_is_closer(gs, unit, "1#0", 14, 10, ["2"], 6, {"1#1": (10, 11, 0)}) is True

        assert ch._charge_model_pos_is_closer(
            gs, unit, "1#0", 14, 10, ["2"], 6, {"1#1": (14, 10, 0)}
        ) is False

    def test_a_teammate_on_another_level_does_not_block(self):
        """03.04 : l'occupation est par NIVEAU. Une coéquipière à l'étage ne bloque pas une
        fin de charge au sol sur la même colonne — sinon l'étage durcirait le sol sous lui.
        """
        gs = _make_gs([_unit("1", 1, [(10, 10), (10, 11)]), _unit("2", 2, [(16, 10)])])
        unit = gs["unit_by_id"]["1"]

        assert ch._charge_model_pos_is_closer(
            gs, unit, "1#0", 14, 10, ["2"], 6, {"1#1": (14, 10, 1)}
        ) is True, "une coéquipière au niveau 1 bloque une destination au niveau 0"

    def test_a_destination_beyond_the_roll_is_refused(self):
        """11.02 : le mouvement de charge est borné par le jet. Le budget est la seule
        différence entre les deux appels ci-dessous.
        """
        gs, unit = self._duel()
        assert ch._charge_model_pos_is_closer(gs, unit, "1#0", 14, 10, ["2"], 4, {}) is True
        assert ch._charge_model_pos_is_closer(gs, unit, "1#0", 14, 10, ["2"], 3, {}) is False

    def test_an_absent_declared_target_makes_every_position_illegal(self):
        """Aucune cible déclarée présente sur la table → aucune position n'est « plus proche »
        de quoi que ce soit. Refus explicite, pas de position acceptée par défaut.
        """
        gs, unit = self._duel()
        assert ch._charge_model_pos_is_closer(gs, unit, "1#0", 14, 10, ["fantome"], 6, {}) is False


# ─────────────────────────────────────────────────────────────────────────────
# charge_preview_move_plan — le Check du plan manuel (11.04 AFTER + 03.03)
# ─────────────────────────────────────────────────────────────────────────────

class TestPreviewMovePlan:
    def test_a_plan_breaking_unit_coherency_cannot_be_validated(self):
        """03.03 : « models must be within 2" horizontally of at least one other model ».

        Les deux figurines sont individuellement légales (11.04) mais s'écartent de plus de
        2" l'une de l'autre : le plan reste refusé, et le refus vient de la cohérence — les
        autres critères sont vérifiés verts dans le même souffle.
        """
        gs = _make_gs([_unit("1", 1, [(10, 10), (10, 11)]), _unit("2", 2, [(16, 10)])])
        gs["charge_roll_values"]["1"] = 8
        # 1#1 finit à 3 hexes de 1#0 : chaque figurine s'est rapprochée de la cible (11.04),
        # mais l'écart intra-escouade dépasse les 2" de la 1re puce de 03.03.
        plan = [("1#0", 15, 10, 0), ("1#1", 14, 13, 0)]

        out = ch.charge_preview_move_plan(gs, "1", plan, ["2"])

        assert all(out["per_model"].values()), (
            f"prémisse : chaque figurine doit être légale isolément, obtenu {out['per_model']}"
        )
        assert out["engaged_all"] is True, "prémisse : la cible doit être engagée"
        assert out["coherency_ok"] is False, "un plan étalé à 5\" passe la cohérence (03.03)"
        assert out["can_validate"] is False

    def test_a_declared_target_engaged_by_nobody_is_reported(self):
        """11.04 AFTER MOVING : « Your unit must be engaged with all of the charge targets ».

        Deux cibles déclarées, une seule engagée par le plan → l'autre est nommée dans
        ``missing_targets`` et la validation est refusée.
        """
        gs = _make_gs([
            _unit("1", 1, [(10, 10), (10, 11)]),
            _unit("2", 2, [(16, 10)]),
            _unit("3", 2, [(16, 30)]),
        ])
        gs["charge_roll_values"]["1"] = 8
        plan = [("1#0", 15, 10, 0), ("1#1", 15, 11, 0)]

        out = ch.charge_preview_move_plan(gs, "1", plan, ["2", "3"])

        assert out["missing_targets"] == ["3"], (
            f"la cible non engagée n'est pas signalée : {out['missing_targets']}"
        )
        assert out["engaged_all"] is False
        assert out["can_validate"] is False

    def test_a_plan_without_a_stored_roll_validates_nothing(self):
        """Sans jet enregistré, il n'y a pas de budget : le Check ne peut RIEN valider. Aucune
        valeur de repli n'est inventée (un budget par défaut autoriserait des plans illégaux).
        """
        gs = _make_gs([_unit("1", 1, [(10, 10)]), _unit("2", 2, [(16, 10)])])
        assert "1" not in gs["charge_roll_values"], "prémisse : aucun jet enregistré"

        out = ch.charge_preview_move_plan(gs, "1", [("1#0", 14, 10, 0)], ["2"])

        assert out["can_validate"] is False
        assert out["per_model"] == {}


# ─────────────────────────────────────────────────────────────────────────────
# charge_target_selection_handler — déclaration des cibles (11.04 BEFORE MOVING)
# ─────────────────────────────────────────────────────────────────────────────

class TestTargetSelectionHandler:
    def test_a_declaration_without_any_target_is_refused(self):
        gs = _make_gs([_unit("1", 1, [(10, 10)]), _unit("2", 2, [(16, 10)])])
        _activated(gs, "1", 6)

        ok, res = ch.charge_target_selection_handler(gs, "1", {"action": "charge"})

        assert ok is False
        assert res["error"] == "missing_target"

    def test_the_declared_target_list_is_stored_verbatim(self):
        """11.04 BEFORE MOVING autorise « one or more enemy units » : la liste déclarée doit
        être conservée telle quelle, pas réduite à sa première entrée.
        """
        gs = _make_gs([
            _unit("1", 1, [(10, 10)]),
            _unit("2", 2, [(15, 10)]),
            _unit("3", 2, [(15, 11)]),
        ])
        _activated(gs, "1", 8)

        ok, _ = ch.charge_target_selection_handler(
            gs, "1", {"action": "charge", "targetIds": ["2", "3"]}
        )

        assert ok is True
        assert gs["charge_target_selections"]["1"] == ["2", "3"]

    def test_a_roll_too_low_fails_the_charge_and_clears_the_state(self):
        """11.02 FAILED CHARGES : « the unit would not move ». Le jet est consommé, les cibles
        déclarées effacées, l'unité sort du pool — sinon elle rechargerait avec un jet fantôme.
        """
        gs = _make_gs([_unit("1", 1, [(10, 10)]), _unit("2", 2, [(16, 10)])])
        _activated(gs, "1", 2)
        before = (gs["models_cache"]["1#0"]["col"], gs["models_cache"]["1#0"]["row"])

        ok, res = ch.charge_target_selection_handler(
            gs, "1", {"action": "charge", "targetId": "2"}
        )

        assert ok is True
        assert res["charge_failed"] is True
        assert res["charge_failed_reason"] == "roll_too_low"
        assert "1" not in gs["charge_roll_values"], "le jet raté n'a pas été consommé"
        assert "1" not in gs["charge_target_selections"], "les cibles déclarées survivent à l'échec"
        assert "1" not in gs["charge_activation_pool"]
        assert (gs["models_cache"]["1#0"]["col"], gs["models_cache"]["1#0"]["row"]) == before, (
            "la figurine a bougé malgré la charge ratée (11.02)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# charge_commit_move_plan_handler — le commit ne valide QUE des plans complets
# ─────────────────────────────────────────────────────────────────────────────

class TestCommitMovePlanHandler:
    def _ready(self):
        """Unité de 2 figurines, cible déclarée, jet enregistré : prête à committer."""
        gs = _make_gs([_unit("1", 1, [(10, 10), (10, 11)]), _unit("2", 2, [(16, 10)])])
        _activated(gs, "1", 8)
        gs["charge_target_selections"]["1"] = ["2"]
        return gs

    def test_a_missing_plan_raises(self):
        gs = self._ready()
        with pytest.raises(KeyError):
            ch.charge_commit_move_plan_handler(gs, "1", {"action": "commit_charge_plan"})

    def test_an_empty_plan_is_refused(self):
        gs = self._ready()
        ok, res = ch.charge_commit_move_plan_handler(gs, "1", {"plan": []})
        assert ok is False
        assert res["error"] == "empty_charge_plan"

    def test_a_malformed_plan_entry_raises(self):
        """Une entrée doit être ``[model_id, col, row, level]``. Une entrée tronquée — y compris
        un 3-uplet SANS étage — est une erreur de contrat du front, pas une position à deviner.
        """
        gs = self._ready()
        with pytest.raises(ValueError):
            ch.charge_commit_move_plan_handler(gs, "1", {"plan": [["1#0", 14]]})

    def test_a_plan_entry_without_level_is_refused(self):
        """Décision : un plan MUET est refusé, jamais complété.

        Le 3-uplet ``[mid, col, row]`` était accepté et l'étage inventé (0 au commit de charge,
        niveau de VUE au pile-in/consolidation) : une escouade à cheval sur deux étages devenait
        invalidable. Les deux formes muettes — 3-uplet et étage ``None`` — lèvent.
        """
        gs = self._ready()
        with pytest.raises(ValueError, match="étage"):
            ch.charge_commit_move_plan_handler(
                gs, "1", {"plan": [["1#0", 15, 10], ["1#1", 15, 11]]}
            )
        with pytest.raises(ValueError, match="étage"):
            ch.charge_commit_move_plan_handler(
                gs, "1", {"plan": [["1#0", 15, 10, None], ["1#1", 15, 11, 0]]}
            )

    def test_a_model_absent_from_the_plan_stays_legitimate(self):
        """L'autre moitié de la décision : une figurine ABSENTE du plan n'est PAS une erreur de
        forme. Le refus porte sur l'entrée muette, pas sur la couverture — la couverture est
        vérifiée plus loin et rend ``plan_models_mismatch``, pas une exception."""
        gs = self._ready()
        ok, res = ch.charge_commit_move_plan_handler(gs, "1", {"plan": [["1#0", 15, 10, 0]]})
        assert ok is False
        assert res["error"] == "plan_models_mismatch", res

    def test_a_commit_without_declared_target_is_refused(self):
        gs = self._ready()
        del gs["charge_target_selections"]["1"]
        ok, res = ch.charge_commit_move_plan_handler(
            gs, "1", {"plan": [["1#0", 15, 10, 0], ["1#1", 15, 11, 0]]}
        )
        assert ok is False
        assert res["error"] == "target_not_selected"

    def test_a_commit_without_roll_is_refused(self):
        gs = self._ready()
        del gs["charge_roll_values"]["1"]
        ok, res = ch.charge_commit_move_plan_handler(
            gs, "1", {"plan": [["1#0", 15, 10, 0], ["1#1", 15, 11, 0]]}
        )
        assert ok is False
        assert res["error"] == "charge_roll_missing"

    def test_a_plan_missing_a_living_model_is_refused(self):
        """11.04 : le mouvement de charge déplace L'UNITÉ. Un plan qui oublie une figurine
        vivante laisserait cette figurine derrière sans que rien ne le signale.
        """
        gs = self._ready()
        ok, res = ch.charge_commit_move_plan_handler(gs, "1", {"plan": [["1#0", 15, 10, 0]]})

        assert ok is False
        assert res["error"] == "plan_models_mismatch"
        assert res["expected"] == ["1#0", "1#1"]
        assert res["got"] == ["1#0"]
        assert (gs["models_cache"]["1#0"]["col"], gs["models_cache"]["1#0"]["row"]) == (10, 10), (
            "un plan refusé a quand même déplacé une figurine"
        )

    def test_a_charge_after_advance_names_the_waaagh_in_the_log(self):
        """VERROU LOG : une charge après Advance permise par le Waaagh! le NOMME (08.04).

        C'est le chemin PvP — `commit_charge_plan`, le seul que le frontend emprunte — et il
        n'écrivait aucun marqueur de capacité : seul le jumeau `charge_destination_selection_handler`
        (chemin IA) en posait un. Le joueur voyait une charge après avance sans savoir ce qui
        l'avait autorisée, et `step.log` non plus (`ability_display_name` absent des détails).

        Token en MAJUSCULES comme `[OATH OF MOMENT]` : c'est cette forme que le frontend
        normalise pour retrouver la description de la règle (`config/unit_rules.json`).
        """
        from engine.game_state import call_waaagh, initial_faction_ability_state

        gs = self._ready()
        # L'unité est ORKS dans une armée ORKS déclarée : sans les DEUX, la capacité n'existe pas.
        gs["unit_by_id"]["1"]["FACTION_KEYWORDS"] = [{"keywordId": "ORKS"}]
        gs["config"]["army_faction"] = {"1": "ORKS", "2": "TYRANIDS"}
        gs.update(initial_faction_ability_state())
        call_waaagh(gs, 1)
        gs["units_advanced"].add("1")

        ok, res = ch.charge_commit_move_plan_handler(
            gs, "1", {"plan": [["1#0", 15, 10, 0], ["1#1", 15, 11, 0]]}
        )

        assert ok is True, f"plan légal refusé : {res}"
        entry = next(e for e in reversed(gs["action_logs"]) if e["type"] == "charge")
        assert "CHARGED [WAAAGH!]" in entry["message"], entry["message"]
        assert entry["ability_display_name"] == "Waaagh!", (
            "step_logger réécrit la ligne et ne lit le token que dans ce champ"
        )

    def test_an_unexplainable_charge_after_advance_leaves_the_state_untouched(self):
        """VERROU ORDRE : le prédicat d'éligibilité est lu AVANT toute mutation.

        `_charge_enabling_ability` LÈVE quand une unité a avancé sans qu'aucune capacité ne
        rende la charge légale (ni `charge_after_advance`, ni Waaagh! actif) — c'est le garde-fou
        qui empêche l'éligibilité et le log de diverger. Lu APRÈS `commit_move`, sa levée
        laissait les figurines posées à destination et `units_charged` marqué, sans ligne de log,
        sans impact de charge et sans fin d'activation : une partie dans un état impossible à
        rejouer. Le test observe donc l'ÉTAT après la levée, pas seulement la levée.
        """
        gs = self._ready()
        gs["units_advanced"].add("1")  # aucune règle, aucun Waaagh! : rien ne justifie la charge

        with pytest.raises(ValueError, match="without any enabling rule"):
            ch.charge_commit_move_plan_handler(
                gs, "1", {"plan": [["1#0", 15, 10, 0], ["1#1", 15, 11, 0]]}
            )

        assert (gs["models_cache"]["1#0"]["col"], gs["models_cache"]["1#0"]["row"]) == (10, 10), (
            "figurine déplacée alors que le commit a levé"
        )
        assert "1" not in gs["units_charged"], "unité marquée comme ayant chargé sans log de charge"

    def test_a_complete_and_legal_plan_commits(self):
        """Contrôle positif : sans lui, les six refus ci-dessus seraient satisfaits par une
        fonction qui refuse TOUT.
        """
        gs = self._ready()
        ok, res = ch.charge_commit_move_plan_handler(
            gs, "1", {"plan": [["1#0", 15, 10, 0], ["1#1", 15, 11, 0]]}
        )

        assert ok is True, f"plan légal refusé : {res}"
        assert res["charge_succeeded"] is True
        assert "1" in gs["units_charged"]
        assert (gs["models_cache"]["1#0"]["col"], gs["models_cache"]["1#0"]["row"]) == (15, 10)


# ─────────────────────────────────────────────────────────────────────────────
# charge_autoplace_plan — les entrées manquantes lèvent, elles ne se devinent pas
# ─────────────────────────────────────────────────────────────────────────────

class TestAutoplacePlan:
    def _ready(self):
        gs = _make_gs([_unit("1", 1, [(10, 10), (10, 11)]), _unit("2", 2, [(16, 10)])])
        _activated(gs, "1", 8)
        gs["charge_target_selections"]["1"] = ["2"]
        return gs

    def test_an_unknown_mode_raises(self):
        gs = self._ready()
        with pytest.raises(ValueError, match="mode invalide"):
            ch.charge_autoplace_plan(gs, "1", mode="agressif")

    def test_an_empty_target_override_raises(self):
        gs = self._ready()
        with pytest.raises(ValueError, match="target_ids_override vide"):
            ch.charge_autoplace_plan(gs, "1", target_ids_override=[])

    def test_autoplace_without_declared_target_raises(self):
        gs = self._ready()
        del gs["charge_target_selections"]["1"]
        # « pour » ancre le message sur l'absence de DÉCLARATION : sans lui le motif
        # attraperait aussi « aucune cible déclarée présente », qui est une autre panne.
        with pytest.raises(ValueError, match="aucune cible déclarée pour"):
            ch.charge_autoplace_plan(gs, "1")

    def test_autoplace_without_roll_raises(self):
        gs = self._ready()
        del gs["charge_roll_values"]["1"]
        with pytest.raises(ValueError, match="jet de charge absent"):
            ch.charge_autoplace_plan(gs, "1")

    def test_a_target_absent_from_the_table_raises(self):
        """Une cible déclarée qui a quitté la table (détruite) n'est pas silencieusement
        ignorée : l'auto-placement n'a plus de contrainte à satisfaire et le dit.
        """
        gs = self._ready()
        gs["charge_target_selections"]["1"] = ["disparue"]
        with pytest.raises(ValueError, match="aucune cible déclarée présente"):
            ch.charge_autoplace_plan(gs, "1")

    def test_the_produced_plan_covers_every_living_model_and_engages_the_target(self):
        """Contrôle positif : le plan sort complet et validable — c'est ce qui rend les cinq
        levées ci-dessus attribuables aux entrées manquantes et non à un autoplace en panne.
        """
        gs = self._ready()
        out = ch.charge_autoplace_plan(gs, "1", mode="offensive")

        plan = out["plan"]
        assert {str(e[0]) for e in plan} == {"1#0", "1#1"}
        check = ch.charge_preview_move_plan(gs, "1", plan, ["2"])
        assert check["engaged_all"] is True, f"autoplace n'engage pas la cible : {check}"


class TestAutoplaceFallbacks:
    """Les deux replis DOCUMENTÉS de l'autoplace — aucun n'était exécuté par un test (mesuré)."""

    def _gs(self, models, target, roll):
        gs = _make_gs([_unit("1", 1, models), _unit("2", 2, [target])])
        _activated(gs, "1", roll)
        gs["charge_target_selections"]["1"] = ["2"]
        return gs

    def test_a_model_without_a_slot_still_advances_towards_the_target(self):
        """Repli « traînards » : une figurine que l'ILP ne place sur aucun slot d'engagement n'est
        pas laissée au départ — elle est rapprochée au maximum (11.04 WHILE MOVING : CHAQUE
        figurine doit finir plus proche). La laisser sur place rendrait le plan invalide au Check
        pour une raison que le joueur n'a pas causée.
        """
        starts = [(10, 10), (2, 30), (3, 31)]
        gs = self._gs(starts, (16, 10), 6)
        from engine.hex_utils import min_distance_between_sets

        before = {f"1#{i}": min_distance_between_sets({p}, {(16, 10)}) for i, p in enumerate(starts)}

        plan = ch.charge_autoplace_plan(gs, "1", mode="offensive")["plan"]

        placed = {str(e[0]): (int(e[1]), int(e[2])) for e in plan}
        assert set(placed) == {"1#0", "1#1", "1#2"}
        stragglers = ["1#1", "1#2"]
        for mid in stragglers:
            assert placed[mid] != starts[int(mid[-1])], (
                f"{mid} est restée au départ au lieu d'être rapprochée (repli traînards)"
            )
            after = min_distance_between_sets({placed[mid]}, {(16, 10)})
            assert after < before[mid], (
                f"{mid} n'a pas fini plus proche de la cible : {before[mid]} → {after}"
            )

    def test_an_impossible_full_coverage_does_not_abort_the_plan(self):
        """Couverture dure infaisable : deux cibles déclarées, une seule atteignable.

        La contrainte (4) de l'ILP — chaque cible reçoit ≥ 1 figurine qui l'engage — ne peut pas
        être satisfaite. L'autoplace NE RENONCE PAS : il rend un plan complet et légal, engage la
        cible atteignable, et laisse le Check nommer l'autre. Renoncer priverait le joueur d'une
        charge partielle que 11.04 WHILE MOVING lui accorde.

        Portée du verrou, mesurée : ce test tient si l'autoplace abandonne (plan vide), pas s'il
        se contente de retirer la contrainte (4). Dans cette configuration le repli « traînards »
        atteint l'engagement à lui seul — l'effet propre du second passage ILP n'est pas
        observable ici et n'est donc pas revendiqué.
        """
        gs = _make_gs([
            _unit("1", 1, [(10, 10), (10, 11)]),
            _unit("2", 2, [(16, 10)]),    # atteignable avec un jet de 6
            _unit("3", 2, [(45, 45)]),    # hors de portée : rend la couverture dure infaisable
        ])
        _activated(gs, "1", 6)
        gs["charge_target_selections"]["1"] = ["2", "3"]

        plan = ch.charge_autoplace_plan(gs, "1", mode="offensive")["plan"]

        assert {str(e[0]) for e in plan} == {"1#0", "1#1"}, "plan incomplet malgré le repli"
        check = ch.charge_preview_move_plan(gs, "1", [tuple(e) for e in plan], ["2", "3"])
        assert all(check["per_model"].values()), (
            f"le repli a produit une position illégale : {check['per_model']}"
        )
        assert check["missing_targets"] == ["3"], (
            f"la cible atteignable doit être engagée et elle seule manquer : {check['missing_targets']}"
        )
