"""T6-c (V11_agent_rework.md) — journalisation des actions du pipeline squad.

Contexte : `_process_squad_action` (chemin VIF du gym) n'appelait AUCUN `log_action` — les 17
sites vivent dans `_process_semantic_action` (PvE/legacy). step.log se réduisait à ses en-têtes
(`Actions=0, Steps=0` sur 474/475 épisodes d'un run réel) et `ai/analyzer.py` n'avait aucune
matière, alors que CLAUDE.md fait de « --step + analyzer.py + replay » la SEULE stratégie de
validation du training.

Root cause : un CONTRAT MOTEUR violé. `end_activation(..., "ACTION", ...)` signifie « action déjà
journalisée par le handler » (generic_handlers ~L72-74), mais `execute_squad_move` et la branche
charge n'émettaient aucun `append_action_log`.

Verrouille :
- le drain ne journalise QUE les entrées postérieures au curseur (pas d'historique rejoué) ;
- no-op strict sans StepLogger / avec StepLogger désactivé (PvP, production) ;
- mapping type moteur -> action_type du formateur, dont la nuance move/advance/flee ;
- émission PAR JET pour shoot/combat (le moteur agrège dans shootDetails) ;
- les types sans formateur sont ignorés, pas crashés ;
- garde explicite : un action_log shoot/combat sans shootDetails = erreur (contrat rompu).
"""
from typing import Any, Dict, List

import pytest

from engine.w40k_core import W40KEngine


class _FakeStepLogger:
    """Capture les appels à log_action (mêmes kwargs que ai/step_logger.StepLogger)."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.calls: List[Dict[str, Any]] = []

    def log_action(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _engine_stub(action_logs: List[Dict[str, Any]], logger: Any) -> W40KEngine:
    """Instance minimale : on teste le drain seul, sans construire une partie complète."""
    eng = object.__new__(W40KEngine)
    eng.game_state = {"action_logs": action_logs, "phase": "move", "turn": 2}
    eng.step_logger = logger
    return eng


def _move_log(**overrides: Any) -> Dict[str, Any]:
    """Entrée d'action_log « move » COMPLÈTE : le formateur exige `move_type` et les 4 coordonnées.

    Une entrée partielle ferait lever `require_key` avant l'assertion du test, qui mesurerait
    alors la garde et non ce qu'il annonce.
    """
    return {"type": "move", "unitId": "1", "player": 1, "phase": "move", "turn": 2,
            "fromCol": 1, "fromRow": 1, "toCol": 2, "toRow": 2, "move_type": "normal",
            **overrides}


def _drain(engine: W40KEngine, cursor: int = 0, fight_state: Any = None) -> None:
    """La BORNE n'est plus un paramètre : c'est le curseur PERSISTANT de `game_state`.

    Le helper le pose donc dans l'état avant d'appeler le drain, exactement comme le fait un
    drainage précédent. Ce que la méthode reçoit, c'est le contexte de FORMATAGE (tour et
    sous-phase de combat capturés AVANT l'action, qui les mute).
    """
    engine.game_state[W40KEngine.STEP_LOG_DRAINED_KEY] = cursor
    engine._flush_squad_action_logs_to_step_logger(2, fight_state)


def test_no_step_logger_is_noop():
    """Sans StepLogger (cas PvP/production), le drain ne fait rien et ne lève pas."""
    eng = _engine_stub([{"type": "move", "unitId": "1"}], None)
    _drain(eng)  # ne doit pas lever


def test_disabled_step_logger_is_noop():
    logger = _FakeStepLogger(enabled=False)
    eng = _engine_stub([{"type": "move", "unitId": "1"}], logger)
    _drain(eng)
    assert logger.calls == []


def test_cursor_only_logs_new_entries():
    """Le curseur isole l'action courante : les entrées antérieures ne sont pas rejouées."""
    logger = _FakeStepLogger()
    logs = [
        _move_log(unitId="old", turn=1),
        _move_log(unitId="new", fromCol=3, fromRow=3, toCol=4, toRow=4),
    ]
    eng = _engine_stub(logs, logger)
    _drain(eng, cursor=1)
    assert [c["unit_id"] for c in logger.calls] == ["new"]


def test_cursor_beyond_length_raises():
    """action_logs ne rétrécit jamais sous un drainage actif : erreur explicite, pas de silence.

    Le seul vidage du chemin journalisé (`reset`) purge le curseur dans la même fonction, et le
    vidage de l'API PvP n'atteint pas ce code (aucun StepLogger côté serveur). Repartir de 0
    rédrainerait des entrées déjà écrites — donc des lignes en double dans step.log, comptées
    double par l'analyzer.
    """
    logger = _FakeStepLogger()
    eng = _engine_stub([_move_log()], logger)
    with pytest.raises(ValueError, match="cannot exceed current length"):
        _drain(eng, cursor=5)
    assert logger.calls == [], "des lignes ont été réécrites avant le refus"


@pytest.mark.parametrize("move_type,expected", [
    ("normal", "move"),
    ("advance", "advance"),
    ("fall_back", "flee"),
])
def test_move_type_maps_to_formatter_action_type(move_type, expected):
    """La nuance normal/advance/fall_back vit dans move_type (le moteur émet toujours "move")."""
    logger = _FakeStepLogger()
    eng = _engine_stub([_move_log(move_type=move_type)], logger)
    _drain(eng)
    assert len(logger.calls) == 1
    assert logger.calls[0]["action_type"] == expected
    details = logger.calls[0]["action_details"]
    assert details["start_pos"] == (1, 1)
    assert details["end_pos"] == (2, 2)
    assert details["current_turn"] == 2  # seul champ EXIGÉ par log_action


def test_type_without_formatter_is_skipped_not_crashed():
    """death/roll_info n'ont pas de formateur (_STEP_LOG_TYPE_MAP) : ignorés volontairement.
    NB: pile_in/consolidation, eux, SONT journalisés (phase fight) — cf.
    test_pile_in_is_logged_as_fight. battle_shock EST dans _STEP_LOG_TYPE_MAP (chantier L25)."""
    logger = _FakeStepLogger()
    logs = [{"type": "death", "unitId": "2"}, {"type": "roll_info"}]
    eng = _engine_stub(logs, logger)
    _drain(eng)
    assert logger.calls == []


def test_pile_in_is_logged_as_fight():
    """pile_in/consolidation sont des déplacements de la phase fight : journalisés (formateur present
    dans _STEP_LOG_TYPE_MAP), avec la phase portee par le raw_log."""
    logger = _FakeStepLogger()
    logs = [
        {"type": "pile_in", "unitId": "1", "phase": "fight", "player": 1},
        {"type": "consolidation", "unitId": "2", "phase": "fight", "player": 2},
    ]
    eng = _engine_stub(logs, logger)
    _drain(eng)
    assert [c["action_type"] for c in logger.calls] == ["pile_in", "consolidation"]
    assert all(c["phase"] == "fight" for c in logger.calls)


def test_shoot_emits_one_log_action_per_shot():
    """Le moteur agrège les jets dans shootDetails ; le formateur travaille PAR ATTAQUE."""
    logger = _FakeStepLogger()
    logs = [{
        "type": "shoot", "shooterId": "7", "targetId": "9", "player": 1, "phase": "shoot",
        "turn": 2, "weaponName": "Bolt Rifle", "shooterCol": 5, "shooterRow": 6,
        "targetCol": 10, "targetRow": 11,
        "shootDetails": [
            {"shotNumber": 1, "attackRoll": 2, "hitResult": "MISS", "hitTarget": 3},
            {"shotNumber": 2, "attackRoll": 5, "hitResult": "HIT", "hitTarget": 3,
             "strengthRoll": 4, "strengthResult": "SUCCESS", "woundTarget": 4,
             "saveRoll": 2, "saveTarget": 3, "saveSuccess": False, "damageDealt": 1},
        ],
    }]
    eng = _engine_stub(logs, logger)
    _drain(eng)

    assert len(logger.calls) == 2  # une ligne PAR JET
    assert all(c["action_type"] == "shoot" for c in logger.calls)
    assert all(c["unit_id"] == "7" for c in logger.calls)

    miss, hit = (c["action_details"] for c in logger.calls)
    # Les 11 champs doivent EXISTER même sur un MISS (le formateur teste `not in details`).
    for key in ("target_id", "hit_roll", "wound_roll", "save_roll", "damage_dealt",
                "hit_result", "wound_result", "save_result", "hit_target",
                "wound_target", "save_target"):
        assert key in miss, f"champ {key} absent sur un MISS -> le formateur lèverait"
        assert key in hit
    assert miss["hit_result"] == "MISS"
    assert miss["wound_roll"] is None  # None est correct : jamais rendu sur un MISS
    assert hit["hit_roll"] == 5 and hit["wound_roll"] == 4 and hit["save_roll"] == 2
    assert hit["save_result"] == "FAIL"  # saveSuccess=False -> le formateur affiche les dégâts
    assert hit["damage_dealt"] == 1
    assert hit["target_coords"] == (10, 11)
    assert hit["weapon_name"] == "Bolt Rifle"


def test_save_success_true_maps_to_save():
    logger = _FakeStepLogger()
    logs = [{"type": "shoot", "shooterId": "1", "targetId": "2", "player": 1, "phase": "shoot",
             "turn": 2, "shootDetails": [{"attackRoll": 6, "hitResult": "HIT", "hitTarget": 3,
                                          "strengthRoll": 6, "strengthResult": "SUCCESS",
                                          "woundTarget": 4, "saveRoll": 6, "saveTarget": 3,
                                          "saveSuccess": True, "damageDealt": 0}]}]
    eng = _engine_stub(logs, logger)
    _drain(eng)
    assert logger.calls[0]["action_details"]["save_result"] == "SAVE"


def test_combat_receives_pre_action_fight_state():
    """Le formateur "combat" exige fight_subphase + les 3 pools (contrat replay), et l'action
    les MUTE -> ils sont capturés AVANT le dispatch, pas relus au drain."""
    logger = _FakeStepLogger()
    fight_state = {
        "fight_subphase": "charging",
        "charging_activation_pool": ["1"],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": ["9"],
    }
    logs = [{"type": "combat", "shooterId": "1", "targetId": "9", "player": 1, "phase": "fight",
             "turn": 2, "shootDetails": [{"attackRoll": 4, "hitResult": "HIT", "hitTarget": 3,
                                          "strengthRoll": 5, "strengthResult": "SUCCESS",
                                          "woundTarget": 4, "saveRoll": 1, "saveTarget": 4,
                                          "saveSuccess": False, "damageDealt": 2}]}]
    eng = _engine_stub(logs, logger)
    _drain(eng, fight_state=fight_state)
    details = logger.calls[0]["action_details"]
    assert details["fight_subphase"] == "charging"
    assert details["charging_activation_pool"] == ["1"]
    assert details["non_active_alternating_activation_pool"] == ["9"]


def test_shoot_without_shoot_details_raises():
    """Contrat _emit_squad_shoot_log rompu = erreur explicite, jamais un silence."""
    logger = _FakeStepLogger()
    logs = [{"type": "shoot", "shooterId": "1", "targetId": "2", "player": 1, "turn": 2}]
    eng = _engine_stub(logs, logger)
    with pytest.raises(TypeError, match="shootDetails"):
        _drain(eng)


def test_hazard_maps_to_hazardous_formatter():
    """Seul type dont le nom moteur diffère de celui du formateur."""
    logger = _FakeStepLogger()
    logs = [{"type": "hazard", "unitId": "1", "player": 1, "phase": "move", "turn": 2,
             "col": 3, "row": 4}]
    eng = _engine_stub(logs, logger)
    _drain(eng)
    assert logger.calls[0]["action_type"] == "hazardous"


def test_deploy_unit_is_mapped():
    """Le déploiement n'était PAS journalisé (deployment_handlers : zéro append_action_log) :
    l'analyzer gardait les unités en (-1,-1) -> 49 fausses collisions (contrôle 2.2)."""
    logger = _FakeStepLogger()
    logs = [{"type": "deploy_unit", "unitId": "5", "player": 2, "phase": "deployment", "turn": 1,
             "fromCol": -1, "fromRow": -1, "toCol": 12, "toRow": 34}]
    eng = _engine_stub(logs, logger)
    _drain(eng)
    assert logger.calls[0]["action_type"] == "deploy_unit"
    details = logger.calls[0]["action_details"]
    # Le formateur deploy_unit EXIGE start_pos ET end_pos.
    assert details["start_pos"] == (-1, -1)
    assert details["end_pos"] == (12, 34)


# ─────────────────────────────────────────────────────────────────────────────
# Instantané 14.02 : contrôle d'objectif + points de victoire journalisés
#
# Le replay affichait un contrôle RECALCULÉ dans le navigateur (par ancre d'escouade, sans
# battle-shock 01.07), donc des points de victoire différents de ceux attribués. Il lit
# désormais l'état du moteur ; ces tests verrouillent la production de cet état.
# ─────────────────────────────────────────────────────────────────────────────


class _FakeSnapshotLogger:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.snapshots: List[Dict[str, Any]] = []

    def log_objective_control_snapshot(
        self, turn, objectives, controllers, victory_points, command_points, **kwargs
    ) -> None:
        self.snapshots.append(
            {
                "turn": turn,
                "objectives": objectives,
                "controllers": dict(controllers),
                "victory_points": dict(victory_points),
                "command_points": dict(command_points),
            }
        )


def _snapshot_engine(
    logger: Any,
    controllers: Dict[str, Any],
    vp: Dict[int, int],
    cp: Dict[int, int] | None = None,
) -> W40KEngine:
    eng = object.__new__(W40KEngine)
    eng.game_state = {
        "objectives": [{"id": 1, "name": "Alpha", "hexes": [[5, 5]]}],
        "objective_controllers": controllers,
        "victory_points": vp,
        # 08.02 : les CP entrent dans l'instantané ET dans sa clé de déduplication.
        "command_points": dict(cp) if cp is not None else {1: 0, 2: 0},
        "turn": 2,
        "units_cache": {},
        "units": [],
    }
    eng.step_logger = logger
    return eng


def test_objective_snapshot_noop_without_logger():
    eng = _snapshot_engine(None, {"1": 1}, {1: 0, 2: 0})
    eng._log_objective_control_snapshot_if_changed()  # ne doit pas lever


def test_objective_snapshot_noop_when_logger_disabled():
    logger = _FakeSnapshotLogger(enabled=False)
    eng = _snapshot_engine(logger, {"1": 1}, {1: 0, 2: 0})
    eng._log_objective_control_snapshot_if_changed()
    assert logger.snapshots == []


def test_objective_snapshot_noop_without_objectives():
    """Scénario sans objectif : rien à journaliser, et surtout pas une ligne vide."""
    logger = _FakeSnapshotLogger()
    eng = _snapshot_engine(logger, {}, {1: 0, 2: 0})
    eng.game_state["objectives"] = []
    eng._log_objective_control_snapshot_if_changed()
    assert logger.snapshots == []


def test_objective_snapshot_emitted_once_then_deduplicated():
    logger = _FakeSnapshotLogger()
    eng = _snapshot_engine(logger, {"1": 1}, {1: 3, 2: 0})
    eng._log_objective_control_snapshot_if_changed()
    eng._log_objective_control_snapshot_if_changed()
    assert len(logger.snapshots) == 1
    assert logger.snapshots[0]["controllers"] == {"1": 1}
    assert logger.snapshots[0]["victory_points"] == {1: 3, 2: 0}
    assert logger.snapshots[0]["turn"] == 2


def test_objective_snapshot_reemitted_when_controller_changes():
    logger = _FakeSnapshotLogger()
    eng = _snapshot_engine(logger, {"1": 1}, {1: 3, 2: 0})
    eng._log_objective_control_snapshot_if_changed()
    eng.game_state["objective_controllers"]["1"] = 2
    eng._log_objective_control_snapshot_if_changed()
    assert [s["controllers"] for s in logger.snapshots] == [{"1": 1}, {"1": 2}]


def test_objective_snapshot_reemitted_when_victory_points_change():
    """Les VP bougent DANS les handlers (apply_primary_objective_scoring), pas à la frontière de
    phase : un déclencheur limité au contrôle les manquerait."""
    logger = _FakeSnapshotLogger()
    eng = _snapshot_engine(logger, {"1": 1}, {1: 3, 2: 0})
    eng._log_objective_control_snapshot_if_changed()
    eng.game_state["victory_points"][1] = 8
    eng._log_objective_control_snapshot_if_changed()
    assert [s["victory_points"][1] for s in logger.snapshots] == [3, 8]


def test_objective_snapshot_reemitted_when_command_points_change():
    """08.02 : un gain de CP sans changement de contrôle ni de VP DOIT réémettre.

    Les CP montent à chaque phase de commandement alors que le contrôle et les VP peuvent ne pas
    bouger. Hors de la clé de déduplication, le replay afficherait un stock figé toute la partie.
    """
    logger = _FakeSnapshotLogger()
    eng = _snapshot_engine(logger, {"1": 1}, {1: 3, 2: 0}, {1: 2, 2: 2})
    eng._log_objective_control_snapshot_if_changed()
    eng.game_state["command_points"][1] = 3
    eng._log_objective_control_snapshot_if_changed()
    assert [s["command_points"][1] for s in logger.snapshots] == [2, 3]
