"""21.03 — les action_logs du gym doivent porter `is_fly_move` (move ET charge).

Ce que les tests existants verrouillaient DEJA : le formateur (`step_logger`) et le mapping
(`_build_step_log_details`) — cf. tests/unit/ai/test_analyzer_scale_vehicle_fly.py. Ce qu'ils ne
verrouillaient PAS, et c'est precisement ce qui manquait : l'EMISSION par le moteur, sur le chemin
que le gym execute reellement.

`movement_commit_move_plan_handler` / `movement_destination_selection_handler` posaient bien le
drapeau, mais ce sont les chemins PvP : ils n'emettent aucun `move_type`, cle exigee par
`_drain_action_logs_to_step_log`, donc ils ne peuvent pas alimenter step.log. Le seul emetteur du
gym est la branche `squad_normal_move / squad_advance / squad_fall_back` de `_process_squad_action`
— elle ignorait `is_fly_move`. Mesure sur un run de 600 episodes : zero `[FLY]` dans 24 Mo de
step.log, et 1014 fausses erreurs « au-delà du budget » chez l'analyzer, qui pathfindait les
escouades volantes au SOL.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test Bolter"}


def _unit_cfg(uid: int, player: int, col: int, row: int,
              keywords: List[Dict[str, str]]) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestFlyer" if keywords else "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": list(keywords), "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


def _engine(keywords: List[Dict[str, str]]) -> W40KEngine:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [], "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                       "max_base_size_hex": 35, "max_turns": 5},
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "controlled_player": 1,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [_unit_cfg(1, 1, 20, 20, keywords), _unit_cfg(2, 2, 50, 50, [])],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(config), gym_training_mode=True)
    eng.reset()
    eng.game_state["phase"] = "move"
    return eng


def _declare_flight(eng: W40KEngine, squad_id: str = "1") -> None:
    """Joue la DÉCLARATION 21.03 par le chemin de production (`L6`), si elle est due.

    Depuis `L6` le vol n'est plus une politique moteur : l'escouade volante doit répondre
    `CHOICE_0` avant de bouger. On joue donc la MÊME séquence que la production —
    `arm_fly_declaration_decision` (ce que fait le masque), puis le décodage de `CHOICE_0` et son
    application par le moteur — plutôt qu'une écriture directe dans `units_took_to_skies`, qui
    court-circuiterait exactement ce que ce fichier prétend observer : le chemin réel.
    Une escouade sans FLY n'est jamais interrogée : rien à jouer.

    (Le masque lui-même est verrouillé par `test_fly_declaration_decision.py` ; ici les fixtures
    posent la phase à la main et n'ont donc pas de pool d'activation à offrir au masque.)
    """
    from engine.macro_intents import CHOICE_BASE
    from engine.phase_handlers.movement_handlers import arm_fly_declaration_decision

    if arm_fly_declaration_decision(eng.game_state, squad_id) is None:
        return
    semantic = eng.action_decoder.convert_squad_action(CHOICE_BASE, eng.game_state)
    ok, _ = eng._process_squad_action(semantic)
    assert ok, "la déclaration de vol a échoué"


def _move_log(eng: W40KEngine, dest_col: int, dest_row: int) -> Dict[str, Any]:
    """Joue un move squad par le chemin de PRODUCTION et rend son action_log."""
    _declare_flight(eng)
    before = len(eng.game_state.get("action_logs", []))
    ok, _ = eng._process_squad_action(
        {"action": "squad_normal_move", "squad_id": "1", "destCol": dest_col, "destRow": dest_row}
    )
    assert ok, "le move squad a échoué : le test n'observe rien"
    moves = [
        entry for entry in eng.game_state["action_logs"][before:]
        if entry.get("type") == "move"
    ]
    assert len(moves) == 1, f"attendu 1 action_log de move, obtenu {len(moves)}"
    return moves[0]


@pytest.mark.parametrize(
    "keywords, expected",
    [
        ([{"keywordId": "FLY"}], True),
        ([], False),
    ],
)
def test_gym_move_carries_the_fly_flag(keywords: List[Dict[str, str]], expected: bool) -> None:
    """L'escouade volante qui DÉCLARE le vol (21.03, `CHOICE_0` de `L6`) -> le log le porte."""
    eng = _engine(keywords)
    entry = _move_log(eng, 24, 20)
    assert entry["is_fly_move"] is expected, entry


def test_gym_move_log_reaches_the_step_log_formatter_with_the_marker() -> None:
    """Chaine complete : action_log moteur -> `_build_step_log_details` -> `[FLY]` dans la ligne.

    Verrouille le maillon manquant BOUT A BOUT : sans l'emission, le mapping et le formateur
    restent corrects mais ne voient jamais rien. `move_type` est exige par le drainage, il fait
    donc partie du contrat teste ici.
    """
    from ai.step_logger import StepLogger

    eng = _engine([{"keywordId": "FLY"}])
    entry = _move_log(eng, 24, 20)
    assert entry["move_type"] == "normal"

    details = eng._build_step_log_details(entry, entry["turn"])
    assert details["is_fly_move"] is True

    formatter = StepLogger.__new__(StepLogger)
    formatter.debug_mode = False  # seul attribut lu par la branche « move » du formateur
    message = formatter._format_replay_style_message(entry["unitId"], "move", details)
    assert "MOVED [FLY] from" in message, message


# ─────────────────────────────────────────────────────────────────────────────
# JUMEAU : la CHARGE. 21.03 couvre « a normal, advance, fall-back or CHARGE move ».
# ─────────────────────────────────────────────────────────────────────────────

def _charge_engine(keywords: List[Dict[str, str]]) -> W40KEngine:
    eng = _engine(keywords)
    # Cible a 6 cases : declarable (< 12") et atteignable avec un jet de 12, meme ampute des 2"
    # que 21.03 fait payer au vol.
    eng.game_state["unit_by_id"]["2"]["col"] = 26
    eng.game_state["unit_by_id"]["2"]["row"] = 20
    from engine.phase_handlers.shared_utils import build_units_cache
    build_units_cache(eng.game_state)
    eng.game_state["phase"] = "charge"
    return eng


@pytest.mark.parametrize("keywords, expected", [([{"keywordId": "FLY"}], True), ([], False)])
def test_gym_charge_carries_the_fly_flag(keywords: List[Dict[str, str]], expected: bool) -> None:
    """Sans ce drapeau, la ligne `CHARGED` de step.log ne porte pas `[FLY]` : l'analyzer juge la
    charge avec un budget 2" trop large ET des murs qui ne s'appliquent pas — exactement la
    classe de faux positifs que le correctif du move supprime, laissee ouverte sur son jumeau.
    """
    eng = _charge_engine(keywords)
    _declare_flight(eng)
    before = len(eng.game_state.get("action_logs", []))
    # Étape 1 : déclaration de charge — le moteur arme la décision de placement (L10) et revient
    # en waiting_for_agent_decision ; aucun action_log n'est encore écrit.
    with patch("engine.phase_handlers.shared_utils.roll_charge_distance", return_value=12):
        ok1, result1 = eng._process_squad_action(
            {"action": "squad_charge", "squad_id": "1", "target_slot": 0}
        )
    assert ok1 and result1.get("decision_type") == "charge_placement", result1
    # Étape 2 : résolution du placement (CHOICE_0 = premier plan) — `_finish_charge_after_placement`
    # commit le move et écrit l'action_log portant `is_fly_move`.
    ok, result = eng._process_squad_action({"action": "agent_decision", "option_index": 0})
    assert ok and result["charge_succeeded"] is True, result
    charges = [e for e in eng.game_state["action_logs"][before:] if e.get("type") == "charge"]
    assert len(charges) == 1, charges
    assert charges[0]["is_fly_move"] is expected, charges[0]


def test_gym_charge_log_reaches_the_step_log_formatter_with_the_marker() -> None:
    """Chaine complete pour la CHARGE : action_log -> `_build_step_log_details` -> `[FLY]` dans la ligne.

    Jumeau de `test_gym_move_log_reaches_the_step_log_formatter_with_the_marker`. Verrouille que
    `_build_step_log_details` propage `is_fly_move` pour le type 'charge' ET que la branche
    charge du formateur l'inclut dans la sortie. Sans ce test, une regression sur l'un ou l'autre
    maillon laisserait passer `test_gym_charge_carries_the_fly_flag` (qui ne couvre que
    l'action_log) tout en supprimant `[FLY]` de step.log.
    """
    from ai.step_logger import StepLogger

    eng = _charge_engine([{"keywordId": "FLY"}])
    _declare_flight(eng)
    before = len(eng.game_state.get("action_logs", []))
    with patch("engine.phase_handlers.shared_utils.roll_charge_distance", return_value=12):
        ok1, result1 = eng._process_squad_action(
            {"action": "squad_charge", "squad_id": "1", "target_slot": 0}
        )
    assert ok1 and result1.get("decision_type") == "charge_placement", result1
    ok2, result2 = eng._process_squad_action({"action": "agent_decision", "option_index": 0})
    assert ok2 and result2["charge_succeeded"] is True, result2

    charges = [e for e in eng.game_state["action_logs"][before:] if e.get("type") == "charge"]
    assert len(charges) == 1, charges
    entry = charges[0]
    assert entry["is_fly_move"] is True

    details = eng._build_step_log_details(entry, entry["turn"])
    assert details["is_fly_move"] is True

    formatter = StepLogger.__new__(StepLogger)
    formatter.debug_mode = False
    message = formatter._format_replay_style_message(entry["unitId"], "charge", details)
    assert "CHARGED [FLY]" in message, message
