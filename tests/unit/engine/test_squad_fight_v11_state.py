"""Le chemin gym avance la machine V11 de la phase de combat (12.01-12.09).

Rupture corrigée (V11 T6-d) : il existait DEUX résolutions du combat. Le PvP
(`_process_semantic_action` → `fight_handlers`) avançait la machine état par état ; le gym
(`_process_squad_action` → `squad_fight`) résolvait pile-in + fight + consolidation par escouade,
en une passe, sans jamais y toucher. Mesuré sur épisode réel : `fight_subphase` restait à
`'pile_in'` du début à la fin, `engaged_at_fight_step_start` n'était jamais posé,
`units_selected_to_fight` restait vide.

Conséquences réglementaires, toutes vérifiées ici :
- 12.02 exige que TOUS les pile-in des DEUX joueurs précèdent le premier combat ; le gym
  intercalait le pile-in d'une escouade entre deux combats ;
- 12.04 date son snapshot d'éligibilité (« was engaged at the start of this step ») du début de
  l'étape FIGHT — snapshot jamais pris, donc branche inapplicable ;
- 12.04 interdit à une escouade d'être sélectionnée deux fois dans la phase — rien ne
  l'enregistrait, donc rien ne l'interdisait ;
- 12.08 réserve la consolidation aux unités « eligible to fight this phase », dérivé du même set.

Le fix découpe `squad_fight` en UNE sélection de l'étape FIGHT, encadrée par les deux étapes
groupées résolues par `_fight_v11_gym_settle`.
"""
from __future__ import annotations

import json
import tempfile
from typing import Any, Dict
from pathlib import Path

import pytest

from tests.unit.engine._melee_scenario import MELEE_SCENARIO


@pytest.fixture()
def melee_scenario_file():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "melee.json"
        path.write_text(json.dumps(MELEE_SCENARIO))
        yield str(path)


def _engine_in_fight_phase(scenario_file: str, seed: int = 1):
    """Moteur gym amené en phase de combat par le vrai chemin d'entrée (12.01 + déroulement)."""
    from ai.unit_registry import UnitRegistry
    from engine.game_utils import get_unit_by_id

    from shared.data_validation import require_present
    from engine.phase_handlers import fight_handlers
    from engine.phase_handlers.fight_handlers import _fight_build_valid_target_pool
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent_x1", training_config_name="x1_debug", controlled_agent="ArmageddonAgent_x1",
        scenario_file=scenario_file, unit_registry=UnitRegistry(), quiet=True,
        gym_training_mode=True,
    )
    eng.reset(seed=seed)
    gs = eng.game_state
    gs["phase"] = "fight"
    # Le scénario mêlée est pré-engagé : on prend la main du joueur qui a une cible en ER, sinon
    # la phase se compléterait à vide et il n'y aurait pas d'étape FIGHT à observer.
    engaged = [
        sid for sid in gs["units_cache"]
        if _fight_build_valid_target_pool(gs, require_present(get_unit_by_id(gs, str(sid)), f"unit {sid}"))
    ]
    assert engaged, "le scénario mêlée doit être pré-engagé"
    gs["current_player"] = int(gs["units_cache"][str(engaged[0])]["player"])
    gs["units_fought"] = set()

    res = fight_handlers.fight_phase_start(gs)
    eng._fight_v11_gym_after_phase_start(res)
    return eng


def test_subphase_advances_past_pile_in(melee_scenario_file):
    """12.02 → 12.04 : le PILE IN groupé est résolu à l'entrée, la machine atteint l'étape FIGHT.

    Échoue sur l'ancien code : `fight_subphase` restait figé à `'pile_in'`.
    """
    eng = _engine_in_fight_phase(melee_scenario_file)
    assert eng.game_state["fight_subphase"] == "fight"


def test_pile_in_step_consumed_before_fight(melee_scenario_file):
    """12.02 : « Each unit cannot make more than one pile-in move during this step ».

    Le set `pile_in_done` matérialise la consommation de l'étape ; il restait vide, si bien que
    l'étape n'était jamais épuisée et ne pouvait jamais céder la place à l'étape FIGHT.
    """
    eng = _engine_in_fight_phase(melee_scenario_file)
    assert eng.game_state["pile_in_done"], "le pile-in groupé doit avoir été résolu et marqué"


def test_engaged_snapshot_posed_at_fight_step_start(melee_scenario_file):
    """12.04 : le snapshot d'engagement est pris au début de l'étape FIGHT, après les pile-in.

    Échoue sur l'ancien code : la clé était absente (jamais posée), rendant inapplicables la
    branche « was engaged at the start of this step » (12.04) et sa négation (overrun, 12.06).
    """
    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    snapshot = gs["engaged_at_fight_step_start"]
    assert isinstance(snapshot, dict)
    # Scénario pré-engagé : le snapshot doit constater au moins une unité engagée.
    assert any(snapshot.values()), f"snapshot sans aucune unité engagée: {snapshot}"


def _fight_action(game_state, squad_id: str) -> Dict[str, Any]:
    """Action `squad_fight` jouable pour `squad_id` : slot de la 1re cible 12.05, ou combat à vide.

    Reproduit le choix que le masque offre (V11 §9 P3-1), sans le deviner : le pool d'engagement
    et le mapping de slots sont ceux que `build_squad_action_mask` consulte.
    """
    from engine.game_utils import get_unit_by_id
    from engine.phase_handlers.fight_handlers import _fight_build_valid_target_pool
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    unit = get_unit_by_id(game_state, str(squad_id))
    if unit is None:
        raise KeyError(f"unit {squad_id} introuvable")
    targets = {str(t) for t in _fight_build_valid_target_pool(game_state, unit)}
    # Annotation EXPLICITE : `target_slot` est un entier, les deux autres clés des chaînes.
    # Sans elle, le dict est inféré `dict[str, str]` et l'ajout du slot ne type-checke pas.
    action: Dict[str, Any] = {"action": "squad_fight", "squad_id": str(squad_id)}
    if not targets:
        return action
    our_player = int(game_state["units_cache"][str(squad_id)]["player"])
    slot_map = get_enemy_slot_mapping(game_state, our_player)
    for slot_i, esid in enumerate(slot_map):
        if esid is not None and str(esid) in targets:
            action["target_slot"] = slot_i
            return action
    raise AssertionError(f"cible 12.05 {targets} sans slot ennemi mappé")


def test_squad_fight_registers_selection_and_cannot_fight_twice(melee_scenario_file):
    """12.04 : « has not already been selected to fight this phase ».

    Échoue sur l'ancien code : `units_selected_to_fight` restait vide, donc l'escouade restait
    dans le pool et pouvait être re-sélectionnée dans la même phase.
    """
    from engine.phase_handlers.fight_handlers import fight_v11_current_pool

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    pool = fight_v11_current_pool(gs)
    assert pool, "l'étape FIGHT doit proposer au moins une sélection"
    squad_id = str(pool[0])

    # V11 §9 P3-1 : la cible de mêlée est portée par l'action. On la choisit comme le pipeline
    # réel — via le pool 12.05 et le mapping de slots, la même source que le masque.
    ok, _result = eng._process_squad_action(_fight_action(gs, squad_id))
    assert ok is True
    assert squad_id in {str(x) for x in gs["units_selected_to_fight"]}
    assert squad_id not in [str(x) for x in fight_v11_current_pool(gs)]


def test_squad_fight_outside_selection_pool_is_rejected(melee_scenario_file):
    """Parité masque/commit : le commit n'accepte que ce que le pool 12.04 propose.

    Le masque gym dérive du même `fight_v11_current_pool` ; une escouade hors pool est une
    rupture masque/commit, qui doit lever plutôt que résoudre un combat que la règle interdit.
    """
    from engine.phase_handlers.fight_handlers import fight_v11_current_pool

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    pool = {str(x) for x in fight_v11_current_pool(gs)}
    outsiders = [str(sid) for sid in gs["units_cache"] if str(sid) not in pool]
    assert outsiders, "le scénario doit comporter une escouade non sélectionnable"

    with pytest.raises(ValueError, match="hors du pool de selection"):
        eng._process_squad_action({"action": "squad_fight", "squad_id": outsiders[0]})


def test_squad_fight_rejected_when_machine_not_at_fight_step(melee_scenario_file):
    """`squad_fight` est une sélection de l'étape FIGHT : hors de cette étape, elle n'existe pas.

    Verrouille la rupture d'origine : l'ancien code résolvait un combat complet en sous-phase
    `'pile_in'`, c'est-à-dire avant que le snapshot 12.04 n'existe. Plutôt que de deviner un
    état, le moteur doit dire que la machine n'a pas été déroulée.
    """
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent_x1", training_config_name="x1_debug", controlled_agent="ArmageddonAgent_x1",
        scenario_file=melee_scenario_file, unit_registry=UnitRegistry(), quiet=True,
        gym_training_mode=True,
    )
    eng.reset(seed=1)
    gs = eng.game_state
    # Phase forcée sans démarrer la machine : `fight_subphase` reste None.
    gs["phase"] = "fight"
    squad_id = str(next(iter(gs["units_cache"])))

    with pytest.raises(RuntimeError, match="n a pas ete deroulee jusqu a l etape FIGHT"):
        eng._process_squad_action({"action": "squad_fight", "squad_id": squad_id})


def test_pool_vide_masque_sans_slot_fight(melee_scenario_file):
    """Invariant masque↔commit (face 1) : squad hors pool 12.04 → aucun slot fight dans build_squad_action_mask.

    La rupture cible `build_squad_action_mask` (shared_utils) : si la garde
    `squad_id in fight_v11_current_pool` est absente, un squad déjà sélectionné obtient des slots
    fight que le commit refuserait (ValueError « rupture masque/commit »). Le test passe le squad
    directement à `build_squad_action_mask` pour exercer cette garde, indépendamment du filtre amont
    `eligible_units` de `get_squad_action_mask_and_eligible_units`.
    """
    from engine.phase_handlers.fight_handlers import fight_v11_current_pool
    from engine.phase_handlers.shared_utils import (
        SQUAD_ACTION_FIGHT_NO_TARGET,
        SQUAD_ACTION_FIGHT_SLOT_BASE,
        SQUAD_ACTION_FIGHT_SLOT_COUNT,
        build_squad_action_mask,
        get_enemy_slot_mapping,
    )

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state

    pool = fight_v11_current_pool(gs)
    assert pool, "précondition : pool 12.04 non vide au départ"
    squad_id = str(pool[0])

    # Marquer l'unité comme déjà sélectionnée → elle quitte le pool 12.04.
    gs["units_selected_to_fight"].add(squad_id)
    assert squad_id not in [str(x) for x in fight_v11_current_pool(gs)], (
        "précondition : squad_id doit être hors pool après marquage"
    )

    # Appel direct à build_squad_action_mask : c'est là que vit la garde `squad_id in pool`.
    our_player = int(gs["units_cache"][squad_id]["player"])
    enemy_slot_ids = get_enemy_slot_mapping(gs, our_player)
    mask = build_squad_action_mask(gs, squad_id, enemy_slot_ids)

    fight_slots = list(range(SQUAD_ACTION_FIGHT_SLOT_BASE, SQUAD_ACTION_FIGHT_SLOT_BASE + SQUAD_ACTION_FIGHT_SLOT_COUNT))
    fight_slots.append(SQUAD_ACTION_FIGHT_NO_TARGET)
    opened = [i for i in fight_slots if mask[i]]
    assert not opened, (
        f"squad {squad_id!r} hors pool 12.04 mais {len(opened)} slot(s) fight ouvert(s) : {opened} "
        f"(rupture masque/commit — l'agent commettrait une action que le moteur refuserait)"
    )


def test_commit_rupture_pool_vide_apres_masque(melee_scenario_file):
    """Invariant masque↔commit (face 2) : slot fight ouvert au masque, pool vidé avant commit → ValueError.

    Simule la désynchronisation temporelle masque/commit : l'escouade est dans le pool lors du
    calcul du masque (slot ouvert), mais sélectionnée à la mêlée avant que l'action ne soit
    traitée. Le moteur doit lever, pas absorber.
    """
    from engine.phase_handlers.fight_handlers import fight_v11_current_pool

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state

    pool = fight_v11_current_pool(gs)
    assert pool, "précondition : pool 12.04 non vide"
    squad_id = str(pool[0])

    # Construire l'action que le masque propose pour squad_id (pool non vide à ce stade).
    action = _fight_action(gs, squad_id)

    # Vider le pool APRÈS la construction du masque : l'escouade est maintenant sélectionnée.
    gs["units_selected_to_fight"].add(squad_id)
    assert squad_id not in [str(x) for x in fight_v11_current_pool(gs)], (
        "précondition : squad_id doit être hors pool après marquage"
    )

    # Le commit doit détecter la rupture et lever, jamais absorber silencieusement.
    with pytest.raises(ValueError, match="rupture masque/commit"):
        eng._process_squad_action(action)


def test_combat_a_vide_ne_pose_pas_pending_fight_weapon_select(melee_scenario_file):
    """Invariant §0.69 : un combat à vide (cibles toutes mortes, 12.04/12.06) ne pose jamais
    `pending_fight_weapon_select` dans game_state — la sélection d'arme n'existe que quand
    une cible est résolue.

    Le scénario : une escouade est dans le pool 12.04 (snapshot engaged_at_fight_step_start=True),
    mais toutes les cibles adjacentes sont retirées AVANT le commit. Le moteur doit résoudre
    le combat sans armer l'état intermédiaire §0.69.
    """
    from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY
    from engine.game_utils import get_unit_by_id
    from engine.phase_handlers.fight_handlers import (
        _fight_build_valid_target_pool,
        fight_v11_current_pool,
    )
    from engine.phase_handlers.shared_utils import remove_from_units_cache

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state

    pool = fight_v11_current_pool(gs)
    assert pool, "précondition : pool 12.04 non vide"

    # Trouver une escouade qui a au moins une cible adjacente.
    squad_id = None
    targets_to_remove = []
    for sid in pool:
        unit = get_unit_by_id(gs, str(sid))
        if unit is None:
            continue
        tgts = list(_fight_build_valid_target_pool(gs, unit))
        if tgts:
            squad_id = str(sid)
            targets_to_remove = tgts
            break

    assert squad_id is not None, "précondition : au moins une escouade avec cible"
    assert targets_to_remove, "précondition : cibles adjacentes présentes"

    # Retirer toutes les cibles adjacentes → pool 12.05 vide pour squad_id.
    for tid in targets_to_remove:
        remove_from_units_cache(gs, str(tid))

    # L'escouade doit rester dans le pool 12.04 grâce au snapshot engaged_at_fight_step_start.
    assert squad_id in [str(x) for x in fight_v11_current_pool(gs)], (
        f"squad {squad_id!r} a quitté le pool après suppression des cibles — "
        "le snapshot engaged_at_fight_step_start n'a pas maintenu l'éligibilité 12.04"
    )

    # Vérifier que _fight_build_valid_target_pool est bien vide (pool 12.05 vide).
    unit = get_unit_by_id(gs, squad_id)
    assert unit is not None
    assert not _fight_build_valid_target_pool(gs, unit), (
        "précondition : le pool 12.05 doit être vide après retrait des cibles"
    )

    action = {"action": "squad_fight", "squad_id": squad_id}  # pas de target_slot

    ok, result = eng._process_squad_action(action)

    assert ok is True
    assert PENDING_FIGHT_WEAPON_KEY not in gs, (
        f"combat à vide : pending_fight_weapon_select ne doit pas être posé (résultat={result!r})"
    )
    assert result.get("waiting_for_weapon_select") is not True, (
        "combat à vide : waiting_for_weapon_select ne doit pas être True"
    )


# ---------------------------------------------------------------------------------------------
# 12.08 AFTER — Engaging consolidation → « New Foes to Face » sur le chemin gym.
# « If one or more enemy units engaged with your unit have not been selected to fight this
# phase, your opponent must select each of those units, one at a time; when each is selected,
# it becomes eligible to fight and is selected to fight (12.04). »
# ---------------------------------------------------------------------------------------------

# Position de l'ennemi E (unité 4, P2) pour le scénario : à ≤ 3" (consolidation_trigger_range)
# de l'unité 1 (P1) SANS être engagé avec elle, et atteignable par une consolidation engaging
# (`squad_consolidate_plan` rend un plan qui finit engagé). Mesuré sur le scénario mêlée :
# rows 212-220 = déjà engagé (mode ongoing), 222-225 = engaging mais plan None (hors d'atteinte).
_NEW_FOE_COL, _NEW_FOE_ROW = 59, 221


def _engine_at_new_foes(scenario_file: str):
    """Moteur gym arrêté par `_fight_v11_gym_settle` sur les New Foes de l'unité 1.

    Construit l'état « U a été sélectionnée et a détruit sa cible » sans jets : la cible (unité 2)
    est retirée, l'unité 1 enregistrée « selected to fight », l'ennemi E (unité 4, jamais éligible
    12.04 : ni engagé au début de l'étape, ni chargeur) posé à ≤ 3" hors engagement. Puis le
    settle — la fonction de production appelée après chaque `squad_fight` — déroule : fin de
    l'étape FIGHT (plus aucune unité éligible), CONSOLIDATE, conso engaging de 1 vers 4.
    """
    from engine.phase_handlers.fight_handlers import _fight_v11_register_selection
    from engine.phase_handlers.shared_utils import destroy_model, place_model_at_effective_level

    eng = _engine_in_fight_phase(scenario_file)
    gs = eng.game_state
    assert gs["current_player"] == 1 and gs["fight_subphase"] == "fight"
    destroy_model(gs, "2#0", "combat")
    _fight_v11_register_selection(gs, "1")
    place_model_at_effective_level(
        gs, "4#0", _NEW_FOE_COL, _NEW_FOE_ROW, int(gs["models_cache"]["4#0"]["level"])
    )
    assert "4" not in {str(x) for x in gs["units_selected_to_fight"]}
    eng._fight_v11_gym_settle()
    return eng


def test_engaging_consolidation_hands_new_foes_to_opponent(melee_scenario_file):
    """12.08 AFTER : la conso engaging de 1 finit engagée avec 4, jamais sélectionnée → le settle
    s'arrête, et le pool (source du masque et du siège qui agit) ne contient QUE ce New Foe.

    Échoue sur l'ancien code : le settle drainait toute la consolidation sans rien poser — pool
    vide, 4 jamais sélectionnée, phase terminée sans son combat.
    """
    from engine.phase_handlers.fight_handlers import (
        fight_v11_current_pool,
        fight_v11_fight_selection_pool,
    )

    eng = _engine_at_new_foes(melee_scenario_file)
    gs = eng.game_state
    assert gs["fight_subphase"] == "consolidate"
    assert "1" in gs["consolidation_done"], "U a consolidé (I1)"
    assert gs["consolidation_new_foes_pending"] == ["4"]
    assert gs["consolidation_new_foes_for_unit"] == "1"
    # Sélecteur = adversaire du propriétaire de U (P1) → P2.
    assert gs["consolidation_new_foes_selector"] == 2
    assert [str(x) for x in fight_v11_current_pool(gs)] == ["4"]
    assert [str(x) for x in fight_v11_fight_selection_pool(gs)] == ["4"]
    assert "4" not in gs["consolidation_done"], "E n'a pas encore combattu : pas de conso (I5)"


def test_new_foe_mask_opens_fight_slot_in_consolidate(melee_scenario_file):
    """Parité masque/commit (face masque) : en sous-phase consolidate, le New Foe obtient un slot
    FIGHT vers l'unité qui l'a engagé. L'ancienne garde `fight_subphase == "fight"` le masquait
    entièrement : masque vide → `advance_phase` → combat perdu.
    """
    from engine.phase_handlers.shared_utils import (
        SQUAD_ACTION_FIGHT_SLOT_BASE,
        SQUAD_ACTION_FIGHT_SLOT_COUNT,
        build_squad_action_mask,
        get_enemy_slot_mapping,
    )

    eng = _engine_at_new_foes(melee_scenario_file)
    gs = eng.game_state
    enemy_slot_ids = get_enemy_slot_mapping(gs, 2)
    mask = build_squad_action_mask(gs, "4", enemy_slot_ids)
    opened = [
        str(enemy_slot_ids[i])
        for i in range(SQUAD_ACTION_FIGHT_SLOT_COUNT)
        if mask[SQUAD_ACTION_FIGHT_SLOT_BASE + i]
    ]
    assert opened == ["1"], f"slots FIGHT ouverts pour le New Foe : {opened}"


def test_new_foe_fights_then_consolidation_resumes(melee_scenario_file):
    """Le New Foe est « selected to fight » par le commit `squad_fight` en sous-phase consolidate,
    combat (normal fight, in-place), puis la consolidation reprend : liste purgée, E consolide à
    son tour (I5), la sous-phase se draine (I2 : E combat une seule fois).
    """
    from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY
    from engine.phase_handlers.fight_handlers import fight_v11_current_pool

    eng = _engine_at_new_foes(melee_scenario_file)
    gs = eng.game_state
    ok, result = eng._process_squad_action(_fight_action(gs, "4"))
    assert ok is True
    assert "4" in {str(x) for x in gs["units_selected_to_fight"]}
    if result.get("waiting_for_weapon_select"):
        slot = min(gs[PENDING_FIGHT_WEAPON_KEY]["slot_to_code"])
        ok, result = eng._process_squad_action(
            {"action": "squad_fight_weapon", "squad_id": "4", "weapon_slot": slot}
        )
        assert ok is True
    assert result["action"] == "squad_fight" and result["squad_id"] == "4"
    assert "fight_result" in result, "le combat du New Foe est résolu (reward porté)"
    # Reprise de la consolidation par le settle : liste épuisée → purgée ; E consolide (12.08
    # « was eligible to fight this phase ») ; plus rien à faire → pool vide (→ advance_phase).
    assert "consolidation_new_foes_pending" not in gs
    assert "consolidation_new_foes_selector" not in gs
    assert "consolidation_new_foes_for_unit" not in gs
    assert gs["fight_subphase"] == "consolidate"
    assert "4" in gs["consolidation_done"]
    assert fight_v11_current_pool(gs) == []


def test_squad_fight_in_consolidate_restricted_to_new_foes(melee_scenario_file):
    """Parité masque/commit (face commit) : en consolidate, `squad_fight` n'accepte QUE les New
    Foes — pas l'alternance 12.04 entière (§8.C). L'unité 3 (P1, jamais sélectionnée) est refusée.
    """
    eng = _engine_at_new_foes(melee_scenario_file)
    with pytest.raises(ValueError, match="hors du pool de selection"):
        eng._process_squad_action({"action": "squad_fight", "squad_id": "3"})


def test_gym_consolidation_log_carries_pre_move_mode(melee_scenario_file):
    """L17 : le mode 12.08 loggué est celui constaté AVANT le move. Relu après, une conso engaging
    réussie (engagée par construction) était logguée `ongoing` — faux tag dans step.log.
    """
    eng = _engine_at_new_foes(melee_scenario_file)
    entries = [
        e for e in eng.game_state["action_logs"]
        if e.get("type") == "consolidation" and str(e.get("unitId")) == "1"
    ]
    assert len(entries) == 1, entries
    assert entries[0]["consolidationMode"] == "engaging"


def test_auto_step_resolves_new_foes_before_consolidation(melee_scenario_file):
    """Siège auto (PvE : `_is_fight_auto_execution_allowed`) : un New Foe gelé par le settle du
    bot doit combattre AVANT toute reprise de la consolidation — même priorité que le flux
    manuel. L'ancien auto-step ignorait la liste et sautait droit à `fight_v11_grouped_next`.
    """
    from engine.phase_handlers.fight_handlers import _fight_v11_auto_step

    eng = _engine_at_new_foes(melee_scenario_file)
    gs = eng.game_state
    ok, result = _fight_v11_auto_step(gs, eng.config)
    assert ok is True
    assert result["action"] == "combat" and result["unitId"] == "4"
    assert result["fight_type"] == "normal", "New Foe engagé : normal fight in-place, pas d'overrun"
    assert "4" in {str(x) for x in gs["units_selected_to_fight"]}
    assert "4" not in gs["consolidation_done"], "le combat précède la conso, il ne la remplace pas"
    # Appel suivant : liste épuisée → purge → la consolidation reprend (E, désormais éligible).
    ok, result = _fight_v11_auto_step(gs, eng.config)
    assert ok is True
    assert "consolidation_new_foes_pending" not in gs
    assert result["action"] == "consolidation" and result["unitId"] == "4"
