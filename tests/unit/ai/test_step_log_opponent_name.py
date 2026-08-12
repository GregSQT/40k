"""Le journal nomme l'adversaire qu'il CONNAÎT, ou ne le nomme pas.

`current_bot_name` porte le commentaire « Set externally for bot-evaluation logging » depuis sa
création, et **aucun code ne l'assignait**. Le moteur retombait donc sur une étiquette en dur,
« SelfPlay », écrite sur 100 % des lignes d'en-tête : le journal du 2026-08-11 annonçait
`Opponent: SelfplayBot` sur ses 600 épisodes alors qu'ils opposaient l'agent aux six bots
pondérés (control, value_trade, adaptive, greedy, defensive, tactical).

Ce n'est pas une coquette : cette constante a fait conclure — à tort, et par moi — que l'agent
n'affrontait qu'un instantané figé de lui-même, et un arbitrage entier a été rendu sur cette
lecture. Même famille que `[Strategy: <label>]`, supprimé le même jour : un champ que rien ne
produit, plus une valeur par défaut, égale une information inventée que tout lecteur croit vraie.

DEUX MOITIÉS, et il faut les deux :
  - le repli est supprimé (`w40k_core`) → sans nom connu, AUCUNE ligne `Opponent:` ;
  - le nom réel est posé là où il existe (`bot_evaluation._eval_worker_task`, seul endroit qui tient
    à la fois le journal et la tâche) → en évaluation, la ligne dit le vrai bot.
Supprimer sans brancher aurait rendu le journal muet sur l'adversaire — une perte, pas un gain.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai.step_logger import StepLogger
from engine.w40k_core import W40KEngine
from tests._state_invariants import unit_invariants


def _episode_header(tmp_path: Path, *, current_bot_name=None, bot_name=None) -> str:
    """Écrit un en-tête d'épisode par le VRAI StepLogger et rend le contenu du journal."""
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=10)
    if current_bot_name is not None:
        logger.current_bot_name = current_bot_name
    logger.log_episode_start(
        run_rules={"engagement_zone_subhex": 10, "metric.engagement": "hex",
                   "metric.ranged": "euclidean", "move.thru_ez": True,
                   "move.thru_enemy": False, "move.thru_friendly": True},
        units_data=[{**unit_invariants(), "id": 1, "col": 2, "row": 3, "player": 1,
                     "HP_MAX": 2, "unitType": "Intercessor", "BASE_SHAPE": "round",
                     "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5}],
        scenario_info="demo-scenario",
        bot_name=bot_name,
        walls=[],
        objectives=[{"id": 1, "hexes": [(4, 4)]}],
        primary_objective_config={"mode": "control"},
        roster_info={"agent_roster_id": "A1", "opponent_roster_id": "B2",
                     "agent_roster_ref": "sm", "opponent_roster_ref": "ork",
                     "scale": 2000, "agent_player": 1},
        board_config={"cols": 15, "rows": 13, "hex_radius": 1.0,
                      "margin": 0.0, "inches_to_subhex": 2.0},
    )
    return output_file.read_text()


def test_no_opponent_line_when_the_adversary_is_unknown(tmp_path: Path) -> None:
    """Sans nom connu, le journal se TAIT — il n'invente pas un adversaire.

    C'est la moitié qui manquait : la branche par défaut écrivait « SelfPlay » quoi qu'il arrive.
    """
    content = _episode_header(tmp_path)

    assert "Opponent:" not in content, content
    assert "SelfPlay" not in content and "Selfplay" not in content, content
    # L'en-tête reste complet par ailleurs : on retire une invention, pas une information.
    assert "Scenario: demo-scenario" in content
    assert "Unit 1 (Intercessor)" in content


def test_the_real_bot_name_reaches_the_log(tmp_path: Path) -> None:
    """`current_bot_name` posé par l'évaluation → la ligne dit le VRAI bot."""
    content = _episode_header(tmp_path, current_bot_name="control")

    assert "Opponent: ControlBot" in content, content


@pytest.mark.parametrize(
    "bot_key,display",
    [
        ("value_trade", "ValueTradeBot"),
        ("alpha", "AlphaStrikeBot"),
    ],
)
def test_the_displayed_name_comes_from_the_registry_not_from_capitalize(
    tmp_path: Path, bot_key: str, display: str
) -> None:
    """VERROU : `capitalize() + "Bot"` rend ce test ROUGE sur les trois clés.

    L'en-tête fabriquait le nom lui-même, et la recette ne tombait juste que sur les clés d'un
    seul mot — `control` étant précisément celle que le test d'origine couvrait. Les autres
    s'affichaient `Value_tradeBot`, ou `AlphaBot` pour un bot dont le nom est `AlphaStrikeBot` :
    le journal nommait des adversaires qui n'existent pas. Deux failles de la recette, deux cas :
    le séparateur `_` qu'elle ne repasse pas en majuscule, et le nom de classe qui n'est pas la
    clé habillée (`alpha` → `AlphaStrikeBot`).
    """
    content = _episode_header(tmp_path, current_bot_name=bot_key)

    assert f"Opponent: {display}" in content, content
    assert f"{bot_key.capitalize()}Bot" not in content, content


def test_an_unknown_bot_key_raises_rather_than_inventing_a_label(tmp_path: Path) -> None:
    """Une clé hors registre est un bot ajouté à moitié, pas une étiquette à improviser."""
    with pytest.raises(KeyError, match="inconnu du registre"):
        _episode_header(tmp_path, current_bot_name="pas_un_bot")


def test_the_eval_task_sets_the_name_on_the_logger() -> None:
    """Le maillon qui manquait, vérifié sur le CODE DE PRODUCTION et non sur une reconstitution.

    `_eval_worker_task` est le seul endroit qui tient à la fois le journal (attaché en mode sérial)
    et la tâche (qui porte `bot_name`). Si cette affectation disparaît, les deux tests ci-dessus
    restent verts et le journal redevient muet : ce test-ci est le seul à l'attraper.
    """
    import inspect

    from ai import bot_evaluation

    src = inspect.getsource(bot_evaluation._eval_worker_task)
    assert 'step_logger = config_params["step_logger"]' in src
    assert "env.engine.step_logger = step_logger" in src
    assert 'step_logger.current_bot_name = task["bot_name"]' in src


def _engine_with_logger(logger) -> W40KEngine:
    """Instance nue : `_logged_opponent_name` ne lit que `step_logger` (même patron que
    `tests/unit/engine/test_step_log_state_and_advance_drain.py`)."""
    eng = W40KEngine.__new__(W40KEngine)
    eng.step_logger = logger
    return eng


class _LoggerWithoutAttribute:
    """Journal qui n'a jamais reçu de nom : l'attribut n'existe même pas."""


def test_the_engine_invents_no_opponent_when_none_was_given() -> None:
    """VRAI CHEMIN, et non un grep du source. Sans nom fourni → None, jamais une étiquette.

    ⚠️ Ce test REMPLACE une contre-épreuve par `assert 'bot_name = "SelfPlay"' not in src`, qui
    a été MESURÉE inopérante le 2026-08-11 : réintroduire le défaut sous la forme
    `getattr(...) or "SelfPlay"` laissait les quatre tests verts. Un test qui interroge la FORME
    du code n'attrape que la forme qu'il connaît ; celui-ci exerce le comportement.
    """
    assert _engine_with_logger(_LoggerWithoutAttribute())._logged_opponent_name() is None

    logger = _LoggerWithoutAttribute()
    logger.current_bot_name = None  # type: ignore[attr-defined]
    assert _engine_with_logger(logger)._logged_opponent_name() is None


def test_the_engine_forwards_the_name_it_was_given() -> None:
    """Contre-épreuve du test précédent : quand le nom EXISTE, il ressort tel quel.

    Sans ce second test, supprimer purement la lecture (`return None` en dur) resterait vert et
    le journal redeviendrait muet sur l'adversaire — la moitié qu'on cherche justement à brancher.
    """
    logger = _LoggerWithoutAttribute()
    logger.current_bot_name = "control"  # type: ignore[attr-defined]
    assert _engine_with_logger(logger)._logged_opponent_name() == "control"
