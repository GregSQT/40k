"""V11 §9.3 P2 — toute DÉCISION D'AGENT résolue laisse une ligne dans `step.log`.

TROU RÉPARÉ (2026-09-10) : la branche qui applique la déclaration de réserves 20.01
(`W40KEngine._dispatch_agent_decision_action`) construisait un résultat
`{"action": "agent_decision", ..., "declaredInReserves": ...}` mais n'appelait AUCUN
`append_action_log`. `grep -rn "decision" ai/step_logger.py` rendait 0 hit : le SEUL type de
décision journalisé était `rule_choice`, par un appel direct. Conséquence mesurable : impossible
de savoir si l'agent déclarait ses réserves ou déclinait systématiquement, alors que l'étape
20.01 précède désormais tout déploiement et pose une décision par unité déclarable.

CE QUE CE FICHIER VERROUILLE :
  - la ligne `DECISION [<type>] CHOICE_<i> [<libellé>]` atteint step.log par le chemin de
    PRODUCTION (`engine.step()` → flush des `action_logs`), et non par un appel direct au
    formateur ;
  - `CHOICE_0` (déclarer en réserves) et `CHOICE_1` (garder pour la mise en place) produisent
    deux lignes DISTINCTES, la seconde marquée `[DECLINED]` — c'est ce qui rend le taux de
    déclaration comptable ;
  - la ligne porte le type, l'index du candidat, l'unité, le joueur, le tour et l'épisode ;
  - `agent_decision` n'incrémente PAS le compteur de steps du StepLogger : le step gym consommé
    par `CHOICE_i` est déjà compté par la ligne d'effet quand le type en produit une.
"""
from __future__ import annotations

import re

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

SCENARIO = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent_x1" / "scenarios" / "training"
    / "reserves_20_fixture1.json"
)

#: `[hh:mm:ss] E<ep> T<turn> P<player> <PHASE> : Unit <id> DECISION [<type>] CHOICE_<i> [<label>]`
_LINE_RE = re.compile(
    r"^\[\d\d:\d\d:\d\d\] E(\d+) T(\d+) P(\d+) ([A-Z_]+) : "
    r"Unit (\S+) DECISION \[([A-Za-z0-9_]+)\] CHOICE_(\d+) \[([^\]]*)\]"
    r"(?P<declined> \[DECLINED\])? \[SUCCESS\]$"
)


@pytest.fixture(autouse=True)
def _pin_board(board_x5):
    pass


def _engine(tmp_path, seed: int = 0):
    from ai.step_logger import StepLogger
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent_x1", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent_x1", scenario_file=str(SCENARIO),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    # Le scheduler par-épisode peut rejouer le scénario en 'fixed' : la question 20.01 n'est
    # posée que dans un déploiement ACTIF.
    assert eng.training_config is not None
    sched = eng.training_config.get("deployment_mode_schedule")
    if isinstance(sched, dict):
        sched["enabled"] = False
    # buffer_size=1 : la ligne est sur le disque dès qu'elle est écrite, aucun flush à oublier.
    eng.step_logger = StepLogger(
        output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=1
    )
    eng.reset(seed=seed)
    return eng


def _drive_deployment(eng, *, declare_first: bool) -> str:
    """Déroule le déploiement. Rend l'id de l'escouade déclarée en réserves ('' si aucune).

    POLITIQUE : `CHOICE_0` (déclarer) pour la PREMIÈRE question quand `declare_first`, `CHOICE_1`
    (garder) pour toutes les autres — ce qui garantit au moins une ligne de chaque forme.
    """
    from engine.agent_decision import read_pending_agent_decision
    from engine.macro_intents import CHOICE_SLOTS

    gs = eng.game_state
    declared = ""
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask = eng.get_action_mask()  # c'est la construction du masque qui POSE la question
        pending = read_pending_agent_decision(gs)
        if pending is not None:
            assert str(pending["type"]) == "reserves_declaration", pending["type"]
            take_zero = bool(declare_first and not declared)
            if take_zero:
                declared = str(pending["unit_id"])
            eng.step(int(CHOICE_SLOTS.start + (0 if take_zero else 1)))
        else:
            deploy_actions = [a for a in range(4, 9) if mask[a]]
            assert deploy_actions, f"aucune action de déploiement au step {steps}"
            eng.step(int(deploy_actions[0]))
        steps += 1
    assert gs.get("phase") != "deployment", "déploiement non terminé"
    return declared


def _decision_lines(eng) -> List[Tuple[Dict[str, Any], str]]:
    eng.step_logger._flush_buffer()
    out: List[Tuple[Dict[str, Any], str]] = []
    for raw in Path(eng.step_logger.output_file).read_text(encoding="utf-8").splitlines():
        match = _LINE_RE.match(raw)
        if match is None:
            assert " DECISION [" not in raw, f"ligne DECISION au format inattendu : {raw!r}"
            continue
        out.append(
            (
                {
                    "episode": int(match.group(1)),
                    "turn": int(match.group(2)),
                    "player": int(match.group(3)),
                    "phase": match.group(4),
                    "unit_id": match.group(5),
                    "decision_type": match.group(6),
                    "option_index": int(match.group(7)),
                    "label": match.group(8),
                    "declined": match.group("declined") is not None,
                },
                raw,
            )
        )
    return out


def test_reserves_declaration_writes_one_step_log_line_per_decision(tmp_path):
    """VERROU : retirer l'appel à `_record_agent_decision_action_log` rend ce test ROUGE."""
    eng = _engine(tmp_path)
    declared_id = _drive_deployment(eng, declare_first=True)
    assert declared_id, "aucune escouade déclarée : le scénario ne pose aucune question 20.01"

    lines = _decision_lines(eng)
    reserves = [row for row, _ in lines if row["decision_type"] == "reserves_declaration"]
    assert reserves, (
        "aucune ligne DECISION [reserves_declaration] dans step.log alors que le déploiement "
        "a répondu à au moins une question 20.01"
    )

    declaring = [row for row in reserves if row["option_index"] == 0]
    assert len(declaring) == 1, f"attendu 1 CHOICE_0, trouvé {len(declaring)} : {declaring}"
    assert declaring[0]["unit_id"] == declared_id
    assert declaring[0]["declined"] is False, "CHOICE_0 DÉCLARE : ce n'est pas le candidat qui passe"
    assert declaring[0]["phase"] == "DEPLOYMENT"
    assert declaring[0]["player"] in (1, 2)
    assert declaring[0]["turn"] >= 1
    assert declaring[0]["episode"] >= 1
    assert declaring[0]["label"], "le libellé du candidat joué doit être nommé"

    # Le second candidat est celui qui PASSE : sans ce marqueur, deux lignes de déclinaison et
    # deux lignes de déclaration se ressembleraient au caractère près hors de l'index.
    keeping = [row for row in reserves if row["option_index"] == 1]
    assert keeping, "aucune ligne CHOICE_1 : le déploiement n'a gardé aucune unité"
    assert all(row["declined"] for row in keeping), (
        "CHOICE_1 garde l'unité pour la mise en place : c'est le candidat `declines`"
    )


def test_declining_every_reserve_leaves_no_choice_zero_line(tmp_path):
    """VERT VACANT écarté : sans déclaration, il ne reste QUE des `CHOICE_1 [DECLINED]`.

    Si le relevé écrivait un index constant (ou omettait `declines`), le test précédent passerait
    quand même — c'est celui-ci qui prouve que la ligne SUIT le candidat réellement joué.
    """
    eng = _engine(tmp_path)
    assert _drive_deployment(eng, declare_first=False) == ""
    reserves = [
        row for row, _ in _decision_lines(eng)
        if row["decision_type"] == "reserves_declaration"
    ]
    assert reserves, "aucune question 20.01 posée : le scénario ne prouve rien"
    assert all(row["option_index"] == 1 and row["declined"] for row in reserves), (
        f"des CHOICE_0 apparaissent alors qu'aucune réserve n'a été déclarée : {reserves}"
    )


def test_agent_decision_does_not_double_count_a_gym_step(tmp_path):
    """`agent_decision` est non-incrémentant : une réponse 20.01 = un step moteur, un step logué.

    L'y compter doublerait `episode_step_count` face à `episode_steps` du moteur pour tout type
    dont l'effet produit déjà une ligne (charge, tir, move_after_shooting, rule_choice).
    """
    from engine.agent_decision import read_pending_agent_decision
    from engine.macro_intents import CHOICE_SLOTS
    from engine.w40k_core import W40KEngine

    assert "agent_decision" in W40KEngine._STEP_LOG_TYPE_MAP, (
        "sans cette entrée, la ligne n'atteint jamais step.log (liste blanche)"
    )
    assert "agent_decision" in W40KEngine._STEP_LOG_NON_INCREMENTING_TYPES

    eng = _engine(tmp_path)
    logger = eng.step_logger
    assert logger is not None
    eng.get_action_mask()
    assert read_pending_agent_decision(eng.game_state) is not None
    steps_before = int(eng.game_state["episode_steps"])
    logged_before = int(logger.episode_step_count)
    eng.step(int(CHOICE_SLOTS.start + 1))
    assert int(eng.game_state["episode_steps"]) == steps_before + 1
    assert int(logger.episode_step_count) == logged_before, (
        "la ligne de relevé ne doit pas incrémenter le compteur de steps du StepLogger"
    )


def test_game_log_message_and_step_log_line_say_the_same_thing(tmp_path):
    """Le Game Log PvP et `step.log` partagent le MÊME constructeur de libellé.

    Deux formateurs séparés auraient divergé au premier ajustement, et l'analyzer ne lit QUE
    `step.log` : la divergence serait passée inaperçue jusqu'à un verdict faux.
    """
    from engine.agent_decision import read_pending_agent_decision
    from engine.macro_intents import CHOICE_SLOTS

    eng = _engine(tmp_path)
    eng.get_action_mask()
    assert read_pending_agent_decision(eng.game_state) is not None
    eng.step(int(CHOICE_SLOTS.start + 0))

    entries = [
        entry for entry in eng.game_state["action_logs"]
        if entry.get("type") == "agent_decision"
    ]
    assert len(entries) == 1, f"attendu UNE entree action_log, trouve {len(entries)}"
    message = entries[0]["message"]
    assert message, "l'entree du Game Log PvP doit porter un libelle, pas une case vide"

    lines = [raw for _, raw in _decision_lines(eng)]
    assert len(lines) == 1
    assert lines[0].endswith(f"{message} [SUCCESS]"), (
        f"step.log dit {lines[0]!r}, le Game Log dit {message!r}"
    )
