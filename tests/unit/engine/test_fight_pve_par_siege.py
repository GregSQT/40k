"""Phase fight en PvE : la machine V11 est conduite PAR SIÈGE, jamais par mode.

Règles (Documentation/40k_rules) : 12.02 et 12.07 « Both players make pile-in / consolidation
moves with all of their eligible units **they choose to move** … The player whose turn it is
resolves all of their moves first, followed by their opponent » ; 12.04 « players alternate
selecting one friendly unit that is eligible to fight » ; 05.03/05.04 « **The opposing player**
resolves the following sequence ». Aucune de ces décisions ne dépend du mode de jeu.

Avant ce lot, `_is_fight_auto_execution_allowed` rendait True pour pve/pve_test/endless_duty et
`execute_action` routait TOUTE action du siège humain vers `_fight_v11_auto_step`, qui l'ignorait
et résolvait d'office une activation (pile-in imposé, cible par heuristique, pertes allouées par
la machine) — jusqu'à lever `RuntimeError … défenseur non-IA ?` quand le sélecteur 12.04 était
le bot et que le défenseur humain devait allouer. Le clic d'allocation du défenseur humain
(`squad_fight_manual_alloc`, attaquant bot) suivait le même chemin et n'atteignait jamais
`apply_manual_shoot_allocation`.

Contrat verrouillé ici, sur un MOTEUR RÉEL (`player_types {1: human, 2: ai}`, exceptions non
avalées — cf. mémoire « execute_ai_turn masque toute exception ») :
  - siège humain : `execute_semantic_action` conduit la machine manuelle du PvP ;
  - siège bot : `execute_ai_turn` = driver `_fight_v11_gym_settle` (pile-in/consolidation de SES
    unités, arrêt au groupe humain) puis politique (`_process_squad_action`) ;
  - le défenseur humain alloue les pertes du combat du bot, et la machine reste cohérente ;
  - `fight_eligible_units` (pool lu par le client) est rafraîchi par le chemin du bot ;
  - un clic humain sur une unité du bot est REFUSÉ (`programmatic_seat_turn`) ;
  - le bot termine la phase quand il vide la dernière étape (12.09), comme la machine manuelle
    le fait pour l'humain ;
  - New Foes to Face (12.08) : sélecteur = adversaire du PROPRIÉTAIRE du consolidant ; les New
    Foes de l'humain sont gelés par la consolidation engaging du bot, ceux du bot sont joués par
    la politique (`squad_fight` accepté en sous-phase consolidate).
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

import pytest

from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY
from engine.constants import PENDING_FIGHT_ALLOCATION_KEY
from engine.game_utils import require_unit_by_id
from engine.phase_handlers.charge_handlers import charge_phase_start
from engine.phase_handlers.fight_handlers import (
    _fight_v11_consolidation_resolve_new_foes,
    fight_phase_start,
    fight_v11_current_pool,
    fight_v11_enter_consolidate,
    fight_v11_enter_fight_step,
    fight_v11_expected_seat,
    fight_v11_start,
)
from engine.phase_handlers.shared_utils import get_enemy_slot_mapping
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    _fall_back_base_config as _base_config,
    _fall_back_make_engine as _make_engine,
    _fall_back_unit_cfg as _unit_cfg,
)


class _ScriptedController:
    """`pve_controller` minimal : rend les actions squad préparées, dans l'ordre. Le moteur les
    exécute par `_process_squad_action`, EXACTEMENT comme la politique."""

    def __init__(self, actions: List[Dict[str, Any]]) -> None:
        self.actions = list(actions)
        self.asked: List[Dict[str, Any]] = []

    def is_ready_for_decision(self) -> bool:
        return True

    def make_ai_decision(self, game_state: Dict[str, Any], engine: W40KEngine) -> Dict[str, Any]:
        if not self.actions:
            raise AssertionError("la politique est interrogée alors qu'aucune décision n'est prévue")
        action = self.actions.pop(0)
        self.asked.append(action)
        return action


def _engine(units: List[Dict[str, Any]], *, current_player: int = 1,
            actions: Optional[List[Dict[str, Any]]] = None) -> W40KEngine:
    eng = _make_engine(_base_config(units))
    gs = eng.game_state
    # Le helper boote en `gym_training_mode` ; l'état visé est une partie PvE servie par l'API.
    gs["gym_training_mode"] = False
    eng.gym_training_mode = False
    gs["player_types"] = {"1": "human", "2": "ai"}
    gs["current_mode_code"] = "pve"
    eng.current_mode_code = "pve"
    eng.is_pve_mode = True
    eng.pve_controller = _ScriptedController(actions or [])  # type: ignore[assignment]
    gs["current_player"] = current_player
    gs["phase"] = "fight"
    return eng


def _fight_step(eng: W40KEngine) -> Dict[str, Any]:
    gs = eng.game_state
    fight_v11_start(gs)
    fight_v11_enter_fight_step(gs)
    return gs


def _ai_turn(eng: W40KEngine):
    """`execute_ai_turn`, dont le `try/except` rend une exception moteur en `ai_decision_failed` :
    ici elle est une PANNE du test, jamais un résultat à interpréter."""
    ok, out = eng.execute_ai_turn()
    if not ok and out.get("error") == "ai_decision_failed":
        raise AssertionError(f"exception moteur avalée par execute_ai_turn : {out.get('message')}")
    return ok, out


# ---------------------------------------------------------------------------
# Reproduction du prompt : deux appels `fight` en PvE, sélecteur humain puis bot
# ---------------------------------------------------------------------------

def test_reproduction_deux_appels_fight_rendent_une_attente_au_lieu_de_lever(monkeypatch):
    """ROUGE avant le fix : 1er appel = combat résolu d'office sans choix humain, 2e appel =
    `RuntimeError _fight_v11_resolve_attacks: allocation combat non terminée en auto`."""
    eng = _engine([_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)])
    gs = _fight_step(eng)
    monkeypatch.setattr(random, "randint", random.Random(0).randint)

    for _ in range(2):
        ok, out = eng.execute_semantic_action({"action": "fight", "unitId": "1"})
        assert ok is True, out
        assert out["action"] == "wait" and out["waiting_for_player"] is True, out
    # Rien n'a été résolu à la place du joueur : aucune unité active, aucune sélection.
    assert gs["units_selected_to_fight"] == set()
    assert gs["active_fight_unit"] is None
    assert gs["fight_eligible_units"] == ["1"]


# ---------------------------------------------------------------------------
# Siège humain : activation puis combat par la machine manuelle ; le bot n'est pas conduit
# ---------------------------------------------------------------------------

def test_le_siege_humain_active_et_combat_le_siege_bot_est_refuse(monkeypatch):
    eng = _engine([_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)])
    gs = _fight_step(eng)
    monkeypatch.setattr(random, "randint", random.Random(0).randint)

    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True and out["active_fight_unit"] == "1" and out["valid_targets"] == ["2"], out
    assert "1" not in gs["units_selected_to_fight"], "activer n'est pas combattre"

    # Clic-cible : le défenseur est le bot → pertes allouées headless DANS la requête (05.04,
    # siège machine), l'unité est enregistrée, et la main passe au sélecteur bot.
    ok, out = eng.execute_semantic_action({"action": "fight", "unitId": "1", "targetId": "2"})
    assert ok is True, out
    assert "1" in gs["units_selected_to_fight"] and "1" in gs["units_fought"]
    assert PENDING_FIGHT_ALLOCATION_KEY not in gs
    assert gs["fight_selector"] == 2 and fight_v11_expected_seat(gs) == 2
    assert out["fight_eligible_units"] == ["2"]

    # Le pool exposé contient l'unité du bot : le clic humain dessus est REFUSÉ, inerte.
    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "2"})
    assert ok is False and out["error"] == "programmatic_seat_turn" and out["player"] == 2, out
    assert gs["active_fight_unit"] is None and "2" not in gs["units_selected_to_fight"]
    ok, out = eng.execute_semantic_action({"action": "skip_fight"})
    assert ok is False and out["error"] == "programmatic_seat_turn", out
    assert gs["fight_subphase"] == "fight"


# ---------------------------------------------------------------------------
# Siège bot : le driver résout SES pile-in seulement, puis rend la main à l'humain
# ---------------------------------------------------------------------------

def test_execute_ai_turn_pile_in_resout_les_unites_du_bot_et_s_arrete_au_groupe_humain():
    """ROUGE si `_fight_v11_gym_settle` draine les deux sièges : les unités humaines seraient
    marquées `pile_in_done` sans un seul clic du joueur."""
    # Tour du bot (joueur actif = 2) : son groupe pile-in passe en premier (12.02).
    eng = _engine(
        [_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20), _unit_cfg(3, 1, 30, 30), _unit_cfg(4, 2, 31, 30)],
        current_player=2,
    )
    gs = eng.game_state
    gs["phase"] = "charge"
    start = fight_phase_start(gs)
    assert gs["fight_subphase"] == "pile_in" and start["fight_eligible_units"] == ["2", "4"]

    ok, out = _ai_turn(eng)
    assert ok is False and out["error"] == "not_ai_player_turn", out
    assert out["reason"] == "no_eligible_ai_units_in_pool"
    assert gs["pile_in_done"] == {"2", "4"}, "seules les unités du bot ont pilé"
    assert gs["fight_subphase"] == "pile_in", "le groupe humain reste à jouer clic par clic"
    assert gs["fight_eligible_units"] == ["1", "3"], "pool client rafraîchi par le chemin du bot"
    assert fight_v11_expected_seat(gs) == 1

    # L'humain passe ses deux unités → étape FIGHT, sélecteur = joueur actif = bot.
    for uid in ("1", "3"):
        ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": uid})
        assert ok is True, out
        ok, out = eng.execute_semantic_action({"action": "skip", "unitId": uid})
        assert ok is True, out
    assert gs["fight_subphase"] == "fight" and gs["fight_selector"] == 2
    assert gs["fight_eligible_units"] == ["2", "4"]


# ---------------------------------------------------------------------------
# Combat du bot par la politique, pertes allouées par le défenseur HUMAIN, machine cohérente
# ---------------------------------------------------------------------------

def test_le_bot_combat_par_la_politique_et_le_defenseur_humain_alloue(monkeypatch):
    """ROUGE avant le fix : le clic `squad_fight_manual_alloc` de l'humain partait dans
    `_fight_v11_auto_step`, jamais dans `apply_manual_shoot_allocation`."""
    slot_of_1 = None
    eng = _engine([_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)], current_player=2)
    gs = _fight_step(eng)
    slot_of_1 = get_enemy_slot_mapping(gs, 2).index("1")
    eng.pve_controller.actions = [  # type: ignore[attr-defined]
        {"action": "squad_fight", "squad_id": "2", "target_slot": slot_of_1},
    ]
    # Touche 6, blesse 6, sauvegarde 1 : la blessure passe, une figurine humaine doit être choisie.
    rolls = iter([6, 6, 1])
    monkeypatch.setattr(random, "randint", lambda a, b: next(rolls, 1))

    ok, out = _ai_turn(eng)
    assert ok is True and out.get("waiting_for_weapon_select") is True, out
    assert "2" in gs["units_selected_to_fight"]
    pending_fw = gs[PENDING_FIGHT_WEAPON_KEY]
    weapon_slot = next(iter(pending_fw["slot_to_code"]))
    eng.pve_controller.actions = [{"action": "squad_fight_weapon", "weapon_slot": weapon_slot}]  # type: ignore[attr-defined]

    ok, out = _ai_turn(eng)
    assert ok is True, out
    assert out["action"] == "squad_fight_manual_alloc" and out["waiting_for_player"] is True, out
    assert PENDING_FIGHT_ALLOCATION_KEY in gs
    assert {c["model_id"] for c in out["allocation"]["choices"]} == {"1#0"}

    # Tant que l'humain n'a pas alloué, le bot ne joue pas (et n'interroge pas la politique).
    ok, out = _ai_turn(eng)
    assert ok is False and out["reason"] == "manual_allocation_pending", out

    hp_before = gs["models_cache"]["1#0"]["HP_CUR"]
    ok, out = eng.execute_semantic_action(
        {"action": "squad_fight_manual_alloc", "unitId": "1", "modelId": "1#0"}
    )
    assert ok is True, out
    assert gs["models_cache"]["1#0"]["HP_CUR"] == hp_before - 1, "l'allocation a été appliquée"
    assert PENDING_FIGHT_ALLOCATION_KEY not in gs
    # Machine cohérente après la reprise manuelle : le bot a combattu, la main est à l'humain.
    assert "2" in gs["units_selected_to_fight"] and "2" in gs["units_fought"]
    assert gs["fight_selector"] == 1 and fight_v11_expected_seat(gs) == 1
    assert out["action"] == "wait" and out["fight_eligible_units"] == ["1"], out
    assert gs["fight_eligible_units"] == ["1"]


# ---------------------------------------------------------------------------
# Cascade charge → fight par l'action du bot : le pool client est rafraîchi sans exception
# ---------------------------------------------------------------------------

def test_la_cascade_charge_vers_fight_par_le_bot_rafraichit_le_pool_client():
    """ROUGE avant le fix : `fight_v11_client_pool` était importé DANS le bloc
    `if current_phase == "fight":` d'`execute_ai_turn` et utilisé après l'action ; entré en phase
    charge, le nom était local non lié → `UnboundLocalError` avalée en `ai_decision_failed`."""
    eng = _engine(
        [_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20), _unit_cfg(3, 1, 30, 30), _unit_cfg(4, 2, 30, 34)],
        current_player=2,
        actions=[{"action": "squad_wait", "squad_id": "4"}],
    )
    gs = eng.game_state
    gs["phase"] = "charge"
    charge_phase_start(gs)
    assert gs["charge_activation_pool"] == ["4"], gs["charge_activation_pool"]

    ok, out = _ai_turn(eng)
    # Le `squad_wait` vide le pool charge → cascade vers fight dans la même requête.
    assert gs["phase"] == "fight", (gs["phase"], out)
    assert gs["fight_subphase"] is not None
    assert gs["pile_in_done"] == {"2"}, "pile-in du bot résolu par le driver, groupe humain suivant"
    # Pool lu par le client rafraîchi après la cascade : c'est à l'humain (unité 1).
    assert gs["fight_eligible_units"] == fight_v11_current_pool(gs) == ["1"]
    assert ok is True and out["action"] == "squad_wait" and out["activation_ended"] is True, out
    # Relance du client sur ce pool : rien à jouer pour le bot, aucune exception.
    ok, out = _ai_turn(eng)
    assert ok is False and out["reason"] == "no_eligible_ai_units_in_pool", out
    assert out["pool_checked"] == ["1"]


# ---------------------------------------------------------------------------
# Fin de phase par le bot quand il vide la dernière étape (12.09)
# ---------------------------------------------------------------------------

def test_le_bot_termine_la_phase_quand_il_vide_la_consolidation():
    eng = _engine([_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)], current_player=1)
    gs = _fight_step(eng)
    gs["units_selected_to_fight"] = {"1", "2"}
    gs["units_fought"] = {"1", "2"}
    fight_v11_enter_consolidate(gs)
    # L'humain (joueur actif, premier groupe 12.07) a déjà consolidé ; reste le groupe du bot.
    gs["consolidation_done"].add("1")
    assert fight_v11_current_pool(gs) == ["2"]

    ok, out = _ai_turn(eng)
    assert ok is True, out
    assert "2" in gs["consolidation_done"]
    assert gs["phase"] != "fight", "machine vidée par le bot → fin de phase par advance_phase"
    assert gs["fight_subphase"] is None


# ---------------------------------------------------------------------------
# New Foes to Face (12.08) : sélecteur, New Foes de l'humain armés par le bot, New Foes du bot
# joués par la politique
# ---------------------------------------------------------------------------

def test_le_selecteur_des_new_foes_est_l_adversaire_du_consolidant_pas_du_joueur_actif():
    """ROUGE avant le fix : `3 - current_player`, faux pour le groupe du joueur non actif."""
    # Tour du bot (actif = 2) ; c'est l'unité HUMAINE 1 qui consolide en engaging sur 2.
    eng = _engine([_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)], current_player=2)
    gs = _fight_step(eng)
    gs["units_selected_to_fight"] = {"1"}
    fight_v11_enter_consolidate(gs)
    armed = _fight_v11_consolidation_resolve_new_foes(gs, require_unit_by_id(gs, "1"), eng.config)
    assert armed is not None and armed["consolidation_new_foes"] == ["2"], armed
    assert gs["consolidation_new_foes_selector"] == 2
    assert fight_v11_expected_seat(gs) == 2
    assert fight_v11_current_pool(gs) == ["2"], "les New Foes SONT le pool actionnable"


def test_la_consolidation_engaging_du_bot_arme_les_new_foes_de_l_humain(monkeypatch):
    # Unité 1 (humain) jamais éligible au combat (ni engagée ni chargée) ; le bot 2 a combattu
    # et consolide : 1 est à 3" → mode engaging (12.08) → 1 devient un New Foe de l'humain.
    eng = _engine([_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 23, 20)], current_player=2)
    gs = _fight_step(eng)
    gs["units_selected_to_fight"] = {"2"}
    gs["units_fought"] = {"2"}
    fight_v11_enter_consolidate(gs)
    assert fight_v11_current_pool(gs) == ["2"]

    ok, out = _ai_turn(eng)
    assert ok is False and out["reason"] == "no_eligible_ai_units_in_pool", out
    assert "2" in gs["consolidation_done"]
    assert gs["consolidation_new_foes_pending"] == ["1"]
    assert gs["consolidation_new_foes_selector"] == 1 and fight_v11_expected_seat(gs) == 1
    assert gs["fight_eligible_units"] == ["1"]

    # L'humain fait combattre son New Foe (clic-cible, défenseur bot → headless), puis la
    # consolidation reprend et la phase se termine (plus rien à consolider).
    monkeypatch.setattr(random, "randint", random.Random(0).randint)
    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True and out["active_fight_unit"] == "1" and out["valid_targets"] == ["2"], out
    ok, out = eng.execute_semantic_action({"action": "fight", "unitId": "1", "targetId": "2"})
    assert ok is True, out
    assert "1" in gs["units_selected_to_fight"]
    assert "consolidation_new_foes_pending" not in gs
    # 1 « was eligible to fight this phase » : elle consolide à son tour (12.08), par l'humain.
    assert gs["fight_subphase"] == "consolidate" and out["fight_eligible_units"] == ["1"], out
    ok, out = eng.execute_semantic_action({"action": "end_consolidation"})
    assert ok is True, out
    assert gs["phase"] != "fight"


def test_les_new_foes_du_bot_sont_joues_par_la_politique(monkeypatch):
    # L'humain 1 (a combattu) consolide en engaging sur le bot 2, jamais sélectionné.
    eng = _engine([_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)], current_player=1)
    gs = _fight_step(eng)
    gs["units_selected_to_fight"] = {"1"}
    gs["units_fought"] = {"1"}
    fight_v11_enter_consolidate(gs)
    armed = _fight_v11_consolidation_resolve_new_foes(gs, require_unit_by_id(gs, "1"), eng.config)
    assert armed is not None and gs["consolidation_new_foes_selector"] == 2
    gs["consolidation_done"].add("1")

    slot_of_1 = get_enemy_slot_mapping(gs, 2).index("1")
    eng.pve_controller.actions = [  # type: ignore[attr-defined]
        {"action": "squad_fight", "squad_id": "2", "target_slot": slot_of_1},
    ]
    monkeypatch.setattr(random, "randint", lambda a, b: 1)  # tout rate : pas d'allocation

    ok, out = _ai_turn(eng)
    assert ok is True and out.get("waiting_for_weapon_select") is True, out
    assert gs["fight_subphase"] == "consolidate", "squad_fight accepté en consolidate (New Foe)"
    weapon_slot = next(iter(gs[PENDING_FIGHT_WEAPON_KEY]["slot_to_code"]))
    eng.pve_controller.actions = [{"action": "squad_fight_weapon", "weapon_slot": weapon_slot}]  # type: ignore[attr-defined]
    ok, out = _ai_turn(eng)
    assert ok is True, out
    assert "2" in gs["units_selected_to_fight"]
    assert "consolidation_new_foes_pending" not in gs, "liste épuisée → purgée par le driver"
    # 2 « was eligible to fight this phase » : le driver l'a consolidée dans la foulée (groupe
    # du bot), la machine est vidée → la phase se termine DANS LA MÊME REQUÊTE (12.09). Le client
    # ne relance le bot que sur un pool contenant une de ses unités et n'envoie jamais
    # `advance_phase` depuis sa boucle IA : un pool vide sans fin de phase figerait la partie.
    assert "2" in gs["consolidation_done"]
    assert gs["phase"] != "fight" and gs["fight_subphase"] is None, out


def test_squad_fight_en_consolidate_hors_new_foe_est_une_rupture():
    eng = _engine([_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)], current_player=1)
    gs = _fight_step(eng)
    gs["units_selected_to_fight"] = {"1"}
    fight_v11_enter_consolidate(gs)
    with pytest.raises(ValueError, match="hors du pool de selection"):
        eng._process_squad_action({"action": "squad_fight", "squad_id": "2", "target_slot": 0})
