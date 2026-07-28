"""Chaîne d'affichage des règles d'armes : moteur → step.log → analyzer.

⚠️ **Le maillon que personne ne testait** (constat V11 §0.38, 2026-07-29). L'information d'une
règle d'arme traverse QUATRE maillons avant d'être exploitable :

    record moteur  →  `w40k_core._SHOT_RECORD_FIELD_MAP`  →  ligne step.log  →  regex analyzer

Chaque maillon avait ses tests ; **aucun ne traversait la jonction**. Résultat : les tokens
`Save [DEVASTATING WOUNDS]`, `[HEAVY]` et `[RAPID FIRE:X]` ont cessé d'être émis sans que rien
ne le signale, et les contrôles de conformité de `ai/analyzer_phases/shoot_handler.py` qui les
lisent sont muets — donc `ai/analyzer.py`, que CLAUDE.md désigne comme la stratégie de
validation du training, rend un verdict faux en silence. Le replay (`replayParser.ts`) lit
exactement les mêmes tokens et est aveugle pour la même raison.

Ce fichier verrouille la chaîne ENTIÈRE, avec du code de production à chaque maillon :
  - le record vient du vrai moteur (`build_manual_shoot_allocation`, dés scriptés) ;
  - le mapping est la vraie `_build_shot_details` et la vraie `_SHOT_RECORD_FIELD_MAP` ;
  - la ligne est écrite par le vrai `StepLogger.log_action` ;
  - le verdict est rendu par le vrai `ai.analyzer.parse_step_log`.

Rien n'est simulé sauf le décor (en-tête d'épisode, positions), qui n'est pas le sujet.
"""
from __future__ import annotations

import random

import pytest

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation


# Unité et arme RÉELLES du roster Space Marines : `TerminatorAssaultCannon` porte
# `Assault Cannon` (RNG 24, DEVASTATING_WOUNDS). L'analyzer résout l'arme depuis le registry
# via (nom affiché, type d'unité) : des noms inventés le feraient sortir silencieusement de
# ses contrôles, et le test ne prouverait rien.
UNIT_TYPE = "TerminatorAssaultCannon"
WEAPON_NAME = "Assault Cannon"
SHOOTER = (50, 50)
TARGET = (80, 50)  # 30 subhex = 6" — dans les 24" de l'arme
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))


def _uc(col, row, *, player):
    return {"BASE_SHAPE": "round", "BASE_SIZE": 6, "col": col, "row": row,
            "occupied_hexes": set(), "VALUE": 10.0, "player": player}


def _game_state(weapon_rules):
    """Tireur '1' vs cible '101', 1 attaque, en `gym_training_mode` (allocation auto)."""
    weapon = {"BS": 3, "STR": 6, "AP": 0, "DMG": 1, "NB": 1, "RNG": 120,
              "WEAPON_RULES": list(weapon_rules), "display_name": WEAPON_NAME}
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                "col": SHOOTER[0], "row": SHOOTER[1], "RNG_WEAPONS": [weapon]}
    target = {"id": "T1", "squad_id": "101", "player": 1, "T": 4, "HP_CUR": 2, "HP_MAX": 2,
              "ARMOR_SAVE": 2, "INVUL_SAVE": 7, "role": None, "unitType": "AssaultIntercessor",
              "points_per_hp": 5.0, "VALUE": 10.0, "col": TARGET[0], "row": TARGET[1]}
    return {
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, "T1": target},
        "squad_models": {"1": ["A1"], "101": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "101": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(*SHOOTER, player=0), "101": _uc(*TARGET, player=1)},
        "units": [{"id": "1", "player": 0, "unitType": UNIT_TYPE},
                  {"id": "101", "player": 1, "unitType": "AssaultIntercessor"}],
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": []},
                       "101": {"id": "101", "UNIT_RULES": []}},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "pending_squad_shoot_intents": {
            "1": [{"model_id": "A1", "target_unit_id": "101", "weapon_index": 0,
                   "n_attacks_resolved": 1}]
        },
    }


def _engine_shoot_log(monkeypatch, weapon_rules, rolls):
    """Fait jouer UN tir par le vrai moteur et rend (game_state, action_log de type 'shoot')."""
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})

    gs = _game_state(weapon_rules)
    build_manual_shoot_allocation(gs, "1")
    shoot_logs = [l for l in gs["action_logs"] if l.get("type") == "shoot"]
    assert shoot_logs, "le moteur n'a émis aucun log de tir"
    return gs, shoot_logs[0]


class _Bridge:
    """Emprunte à `W40KEngine` le VRAI mapping record → action_details, sans construire le
    moteur complet (qui exigerait un scénario et une partie entière). Les trois membres
    empruntés sont le code de production tel quel — c'est `_SHOT_RECORD_FIELD_MAP` qui est
    le maillon suspect, il doit être exercé, pas réécrit."""

    def __init__(self, game_state):
        from engine.w40k_core import W40KEngine

        self.game_state = game_state
        self._SHOT_RECORD_FIELD_MAP = W40KEngine._SHOT_RECORD_FIELD_MAP
        self._build_shot_details = W40KEngine._build_shot_details.__get__(self)
        self._models_segment_for_unit = W40KEngine._models_segment_for_unit.__get__(self)


def _step_log_line(tmp_path, gs, raw_log):
    """Écrit la ligne step.log du 1er jet avec le VRAI StepLogger et la relit."""
    from ai.step_logger import StepLogger

    shots = raw_log["shootDetails"]
    assert shots, "le log de tir ne porte aucun jet"
    details = _Bridge(gs)._build_shot_details(raw_log, shots[0], 1, None)

    out = tmp_path / "engine_line.log"
    logger = StepLogger(output_file=str(out), enabled=True, buffer_size=1)
    logger.episode_number = 1
    logger.log_action(
        unit_id=raw_log["shooterId"], action_type="shoot", phase="shoot",
        player=1, success=True, step_increment=True, action_details=details,
    )
    logger._flush_buffer()
    lines = [l for l in out.read_text().splitlines() if " SHOOT : " in l]
    assert lines, (
        "le StepLogger n'a produit AUCUNE ligne de tir — `log_action` avale ses exceptions, "
        "un champ requis manque probablement dans le mapping"
    )
    return lines[-1]


def _analyzer_stats(tmp_path, engine_line):
    """Injecte la ligne PRODUITE PAR LE MOTEUR dans un step.log valide et lance l'analyzer."""
    import ai.analyzer as an

    body = engine_line.split(" : ", 1)[1]
    log = tmp_path / "step.log"
    log.write_text(
        "=== STEP-BY-STEP ACTION LOG ===\n"
        "================================================================================\n\n"
        "[10:00:00] === EPISODE 1 START ===\n"
        "[10:00:00] Scenario: scenario_bot-01\n"
        "[10:00:00] Opponent: SelfplayBot\n"
        "[10:00:00] Walls: \n"
        f"[10:00:00] Objectives: rect b NW:{OBJECTIVES}\n"
        "[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1\n"
        f"[10:00:00] Unit 1 ({UNIT_TYPE}) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
        "[10:00:00] === ACTIONS START ===\n"
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) DEPLOYED from (-1,-1) to ({SHOOTER[0]},{SHOOTER[1]}) [R:+0.0] [SUCCESS]\n"
        f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({TARGET[0]},{TARGET[1]}) DEPLOYED from (-1,-1) to ({TARGET[0]},{TARGET[1]}) [R:+0.0] [SUCCESS]\n"
        f"[10:00:02] E1 T1 P1 SHOOT : {body}\n"
    )
    return an.parse_step_log(str(log))


# ─────────────────────────────────────────────────────────────────────────────
# [DEVASTATING WOUNDS] 24.10 — la chaîne complète
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def devastating_line(monkeypatch, tmp_path):
    """Un tir dont la blessure est CRITIQUE (6) sur une arme DEVASTATING : la sauvegarde ne
    doit pas être faite, et la ligne doit le dire."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["DEVASTATING_WOUNDS"], [4, 6, 6])
    assert gs["models_cache"]["T1"]["HP_CUR"] == 1, "prémisse : le dégât a bien été infligé"
    return _step_log_line(tmp_path, gs, raw_log)


def test_la_ligne_step_log_annonce_la_sauvegarde_sautee(devastating_line):
    """Maillon 1-3 : le token que l'analyzer ET le replay cherchent doit être présent."""
    assert "[DEVASTATING WOUNDS]" in devastating_line, devastating_line


def test_la_ligne_ne_montre_pas_de_jet_de_sauvegarde(devastating_line):
    """24.10 : « no saving throw can be made ». Afficher `Save 6(2+)` sur une blessure
    mortelle est ce que l'analyzer lui-même classe en `devastating_wounds_incorrect`."""
    import re

    assert re.search(r"Save\s+\d+\(", devastating_line) is None, devastating_line


def test_l_analyzer_compte_le_tir_comme_conforme(devastating_line, tmp_path):
    """Maillon 4 : le verdict de conformité de l'analyzer sur la ligne réelle du moteur."""
    stats = _analyzer_stats(tmp_path, devastating_line)

    assert stats["devastating_wounds_incorrect"][1] == 0, stats["devastating_wounds_incorrect"]
    assert stats["devastating_wounds_correct"][1] == 1, (
        "l'analyzer doit compter ce tir en DEVASTATING conforme ; 0 signifie que la chaîne "
        "moteur → step.log → analyzer est rompue"
    )
