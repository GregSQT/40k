"""Verrous T1 — le step logging ne peut plus échouer en silence.

Deux portes de silence existaient, toutes deux capables de rendre un run vert avec un
`step.log` réduit à l'en-tête écrit par le constructeur (394 octets, mesuré le 2026-09-07) :

1. cinq `except Exception` autour du chemin d'écriture (`log_action`, `_flush_buffer`,
   `log_episode_start`, `log_phase_transition`, `log_episode_end`) imprimaient `str(e)` sans
   trace et rendaient la main. La cause première de l'incident n'a jamais pu être identifiée
   parce que l'exception avait été détruite ;
2. rien ne contrôlait, à la fin d'un run `--step`, qu'un seul épisode avait atteint le
   fichier — journal jamais atteint, `enabled` faux, environnement recréé après la connexion
   du logger (cf. le commentaire V11 T6 de `ai/train.py`).

Cycle rouge→vert :
  - remettre `try:` / `except Exception as e: print(...)` autour du bloc `with open(...)` de
    `log_episode_start` fait passer `test_log_episode_start_leve_si_lecriture_echoue` au rouge ;
  - remplacer la sonde `episodes_written` de `assert_step_log_written` par `episode_number`
    fait passer `test_controle_fin_de_run_leve_quand_rien_na_ete_ecrit` au rouge (c'est le
    piège : `engine/w40k_core.py` écrase `episode_number` à chaque reset).

Le troisième verrou tient l'EXCLUSION : les écritures dans `debug.log` sous `if
self.debug_mode` sont de l'instrumentation, leur `pass` est justifié et doit le rester.
"""
from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ai.step_logger import StepLogger, assert_step_log_written
from tests._state_invariants import unit_invariants


def _units() -> List[Dict[str, Any]]:
    return [
        {
            **unit_invariants(),
            "id": 1,
            "col": 2,
            "row": 3,
            "player": 1,
            "HP_MAX": 2,
            "unitType": "Intercessor",
            "BASE_SHAPE": "round",
            "BASE_SIZE": 1,
        }
    ]


def _episode_start(logger: StepLogger) -> None:
    logger.log_episode_start(
        units_data=_units(),
        run_rules={"metric.engagement": "hex"},
        board_config={
            "cols": 15, "rows": 13, "hex_radius": 1.0,
            "margin": 0.0, "inches_to_subhex": 2.0,
        },
        primary_objective_config={"mode": "control"},
    )


def _move_details() -> Dict[str, Any]:
    return {
        "current_turn": 1,
        "start_pos": (2, 3),
        "end_pos": (4, 5),
        "unit_with_coords": "1(4,5)",
    }


# ── 1. le chemin d'écriture lève ──────────────────────────────────────────────

def test_log_episode_start_leve_si_lecriture_echoue(tmp_path: Path) -> None:
    """Journalisation DEMANDÉE qui échoue = erreur, pas un avertissement imprimé."""
    logger = StepLogger(output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=50)
    # Le constructeur a déjà écrit l'en-tête : c'est APRÈS coup que la destination devient
    # inatteignable, exactement la forme de l'incident (fichier créé, épisodes absents).
    logger.output_file = str(tmp_path / "repertoire-inexistant" / "step.log")

    with pytest.raises(FileNotFoundError):
        _episode_start(logger)

    assert logger.episodes_written == 0


def test_flush_buffer_leve_si_lecriture_echoue(tmp_path: Path) -> None:
    """Jumeau de `log_episode_start` sur l'autre écrivain du fichier."""
    logger = StepLogger(output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=50)
    logger.log_buffer.append("ligne\n")
    logger.output_file = str(tmp_path / "repertoire-inexistant" / "step.log")

    with pytest.raises(FileNotFoundError):
        logger._flush_buffer()

    # Le tampon n'est PAS vide (le vidage n'a pas eu lieu) : sans ce nettoyage, `__del__`
    # retenterait le flush au ramassage et pytest remonterait l'echec en warning `unraisable`.
    logger.log_buffer = []


# ── 2. le garde-fou de fin de run ─────────────────────────────────────────────

def test_controle_fin_de_run_leve_quand_rien_na_ete_ecrit(tmp_path: Path) -> None:
    """`--step` demandé + zéro épisode écrit = erreur, chemin et épisodes joués cités."""
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)

    with pytest.raises(RuntimeError) as excinfo:
        assert_step_log_written(logger, 300)

    message = str(excinfo.value)
    assert str(output_file) in message
    assert "300" in message


def test_controle_fin_de_run_sans_total_publie(tmp_path: Path) -> None:
    """Un mode qui ne publie aucun total d'épisodes lève quand même, et le dit."""
    logger = StepLogger(output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=50)

    with pytest.raises(RuntimeError, match=r"aucun total d'episodes"):
        assert_step_log_written(logger, None)


def test_controle_fin_de_run_passe_apres_un_episode_ecrit(tmp_path: Path) -> None:
    """Anti-vert-vacant : le compteur bouge REELLEMENT quand l'épisode atteint le fichier."""
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)
    _episode_start(logger)

    assert logger.episodes_written == 1
    assert "=== EPISODE 1 START ===" in output_file.read_text(encoding="utf-8")
    assert_step_log_written(logger, 1)


def test_le_compteur_ignore_lecrasement_de_episode_number(tmp_path: Path) -> None:
    """Le piège : `engine/w40k_core.py` réécrit `episode_number` à chaque reset.

    Une sonde bâtie dessus compterait les resets du moteur, donc ne serait jamais nulle sur
    un run qui a joué — le contrôle serait vert alors que le journal est vide.
    """
    logger = StepLogger(output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=50)
    logger.episode_number = 299  # ce que fait w40k_core.py:2234 à chaque reset

    assert logger.episodes_written == 0
    with pytest.raises(RuntimeError):
        assert_step_log_written(logger, 300)


# ── 3. l'exclusion : debug.log reste avalé ────────────────────────────────────

def test_les_ecritures_debug_log_restent_avalees(tmp_path: Path, monkeypatch) -> None:
    """Instrumentation `if self.debug_mode` : son échec n'a aucune conséquence métier.

    Verrou de NON-RÉGRESSION sur l'exclusion — si un `pass` de `debug.log` est un jour
    converti en levée, ce test tombe.
    """
    logger = StepLogger(
        output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=50, debug_mode=True
    )
    vrai_open = builtins.open

    def open_qui_refuse_debug_log(file, *args, **kwargs):
        if str(file) == "debug.log":
            raise OSError("debug.log indisponible")
        return vrai_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_qui_refuse_debug_log)

    # step_increment=True et action_type="move" : les trois écritures debug.log du chemin
    # (appel, STEP_TIMING, après-écriture) sont traversées dans le même appel.
    logger.log_action(
        unit_id=1,
        action_type="move",
        phase="move",
        player=1,
        success=True,
        step_increment=True,
        action_details=_move_details(),
    )

    assert len(logger.log_buffer) == 1
    assert "MOVED" in logger.log_buffer[0]


def test_main_appelle_le_controle_de_fin_de_run(tmp_path: Path, monkeypatch) -> None:
    """Le contrôle est-il sur le VRAI chemin ? `main()` est le point d'entrée de `p ai/train.py`.

    `_run_main` est remplacé par un stub qui pose exactement ce qu'un run `--step` réussi pose
    (drapeau armé, logger global, total d'épisodes publié) et rend 0 : sans l'appel dans le
    wrapper, `main()` rendrait 0 en silence, comme le run du 2026-09-07.
    """
    import ai.train as train

    logger = StepLogger(output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=50)

    def _stub_run_main() -> int:
        train.step_logger = logger
        train._step_log_required = True
        train._run_episodes_played = 300
        return 0

    monkeypatch.setattr(train, "_run_main", _stub_run_main)
    monkeypatch.setattr(train, "step_logger", None, raising=False)

    with pytest.raises(RuntimeError, match=r"aucun episode n'a ete ecrit"):
        train.main()


def test_main_ne_controle_pas_un_run_en_echec(tmp_path: Path, monkeypatch) -> None:
    """Un `return 1` (arguments refusés, modèle absent) a déjà son diagnostic : ne pas l'écraser."""
    import ai.train as train

    def _stub_run_main() -> int:
        train.step_logger = StepLogger(
            output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=50
        )
        train._step_log_required = True
        return 1

    monkeypatch.setattr(train, "_run_main", _stub_run_main)

    assert train.main() == 1
