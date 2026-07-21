"""V11 §10.5 — le holdout porte sur l'ADVERSAIRE, pas sur les rosters.

Les bots d'evaluation etaient un sous-ensemble STRICT des bots d'entrainement : le win-rate
mesurait l'exploitation apprise, pas la competence. `TacticalBot` est desormais reserve a
l'evaluation. Ces tests verrouillent l'invariant : aucun bot de holdout ne doit apparaitre
dans `bot_training.ratios`, dans AUCUNE phase d'AUCUN agent.
"""

import json
from pathlib import Path
from typing import List

import pytest

# Bots reserves a l'evaluation — jamais rencontres a l'entrainement.
HOLDOUT_BOTS = {"tactical"}

CONFIG_ROOT = Path(__file__).resolve().parents[3] / "config" / "agents"


def _training_config_files() -> List[Path]:
    """Configs ACTIVES uniquement : `<Agent>/<Agent>_training_config.json`.

    Le dossier contient aussi des sauvegardes (BEST_*, *_save_avant_*) qui ne sont
    chargees par aucun chemin d'entrainement.
    """
    files = sorted(
        agent_dir / f"{agent_dir.name}_training_config.json"
        for agent_dir in CONFIG_ROOT.iterdir()
        if agent_dir.is_dir() and (agent_dir / f"{agent_dir.name}_training_config.json").exists()
    )
    assert files, f"Aucune config d'entrainement active trouvee sous {CONFIG_ROOT}"
    return files


@pytest.mark.parametrize("config_path", _training_config_files(), ids=lambda p: p.parent.name)
def test_holdout_bots_never_used_in_training(config_path: Path) -> None:
    with config_path.open(encoding="utf-8-sig") as handle:
        config = json.load(handle)

    for phase_name, phase_cfg in config.items():
        if not isinstance(phase_cfg, dict) or "bot_training" not in phase_cfg:
            continue
        ratios = phase_cfg["bot_training"]["ratios"]
        leaked = HOLDOUT_BOTS.intersection(ratios.keys())
        assert not leaked, (
            f"{config_path.name}[{phase_name}] : bot(s) de holdout {sorted(leaked)} presents "
            "dans bot_training.ratios — le holdout d'evaluation serait invalide (V11 §10.5)."
        )


@pytest.mark.parametrize("config_path", _training_config_files(), ids=lambda p: p.parent.name)
def test_holdout_bots_present_in_evaluation(config_path: Path) -> None:
    with config_path.open(encoding="utf-8-sig") as handle:
        config = json.load(handle)

    for phase_name, phase_cfg in config.items():
        if not isinstance(phase_cfg, dict) or "callback_params" not in phase_cfg:
            continue
        callback_params = phase_cfg["callback_params"]
        if "bot_eval_weights" not in callback_params:
            continue
        weights = callback_params["bot_eval_weights"]
        missing = HOLDOUT_BOTS.difference(weights.keys())
        assert not missing, (
            f"{config_path.name}[{phase_name}] : bot(s) de holdout {sorted(missing)} absents "
            "de bot_eval_weights — le critere de succes §10.6 ne serait pas mesurable."
        )
        total = sum(float(w) for w in weights.values())
        assert abs(total - 1.0) < 1e-9, (
            f"{config_path.name}[{phase_name}] : bot_eval_weights somme a {total}, pas 1.0."
        )
        randomness = callback_params["bot_eval_randomness"]
        for bot_name in weights:
            assert bot_name in randomness, (
                f"{config_path.name}[{phase_name}] : '{bot_name}' pondere en evaluation mais "
                "absent de bot_eval_randomness."
            )


@pytest.mark.parametrize("config_path", _training_config_files(), ids=lambda p: p.parent.name)
def test_holdout_bots_carry_zero_selection_weight(config_path: Path) -> None:
    """Un holdout pondere dans `combined` serait optimise par la selection de modele.

    `combined` est un critere de gating (training_callbacks `_evaluate_model_gating`) et
    pilote le choix du BEST : le holdout doit y peser exactement 0.
    """
    with config_path.open(encoding="utf-8-sig") as handle:
        config = json.load(handle)

    for phase_name, phase_cfg in config.items():
        if not isinstance(phase_cfg, dict) or "callback_params" not in phase_cfg:
            continue
        weights = phase_cfg["callback_params"].get("bot_eval_weights")
        if weights is None:
            continue
        for bot_name in HOLDOUT_BOTS:
            assert float(weights[bot_name]) == 0.0, (
                f"{config_path.name}[{phase_name}] : le holdout '{bot_name}' pese "
                f"{weights[bot_name]} dans bot_eval_weights — il entrerait dans `combined`, "
                "donc dans le gating et la selection du BEST (V11 §10.5)."
            )


def test_holdout_bots_excluded_from_every_selection_signal() -> None:
    """Le poids nul ne suffit pas : worst_bot/gating/robuste iterent sur des NOMS de bots."""
    from ai.training_callbacks import ALL_BOT_NAMES, HOLDOUT_BOT_NAMES, SELECTION_BOT_NAMES

    assert HOLDOUT_BOTS == set(HOLDOUT_BOT_NAMES)
    # Mesure et affichage : le holdout est connu.
    assert HOLDOUT_BOT_NAMES.issubset(ALL_BOT_NAMES)
    # Selection : il en est absent.
    assert not HOLDOUT_BOT_NAMES.intersection(SELECTION_BOT_NAMES)
    assert SELECTION_BOT_NAMES == ALL_BOT_NAMES - HOLDOUT_BOT_NAMES

    # worst_bot_score de metrics_tracker doit lui aussi ignorer le holdout.
    import inspect

    from ai import metrics_tracker

    source = inspect.getsource(metrics_tracker.W40KMetricsTracker.log_bot_evaluations)
    all_bot_keys_line = next(
        line for line in source.splitlines() if line.strip().startswith("ALL_BOT_KEYS =")
    )
    for bot_name in HOLDOUT_BOTS:
        assert f"'{bot_name}'" not in all_bot_keys_line, (
            f"'{bot_name}' present dans ALL_BOT_KEYS : il entrerait dans worst_bot_score "
            "et donc dans 0_critical/b_worst_bot_score (V11 §10.5)."
        )


def test_selection_worst_bot_excludes_holdout_even_when_it_is_the_minimum() -> None:
    """Lock comportemental : le holdout ne pilote JAMAIS worst_bot, meme s'il est le pire.

    C'est le trou §0.16(a) : `combined` protege le holdout par poids nul, mais worst_bot
    est un `min` sur des NOMS de bots — le poids n'y intervient pas.
    """
    from ai.training_callbacks import selection_worst_bot

    scores = {"greedy": 0.80, "control": 0.55, "tactical": 0.05}
    name, score = selection_worst_bot(scores)
    assert name == "control" and score == 0.55, (
        "tactical (0.05) est le minimum mais il est HOLDOUT : worst_bot doit rester sur control."
    )


def test_selection_worst_bot_raises_when_only_holdout_remains() -> None:
    from ai.training_callbacks import selection_worst_bot

    with pytest.raises(ValueError, match="holdout"):
        selection_worst_bot({"tactical": 0.0})


def test_both_worst_bot_sites_delegate_to_selection_worst_bot() -> None:
    """Lock structurel : les DEUX sites de calcul du worst_bot passent par le helper.

    Le lock comportemental ci-dessus ne vaut que si personne ne re-inline un `min` brut.
    §0.16(a) nomme exactement ces deux sites (bot_evaluation par-scenario + train.py eval-only) ;
    le test `test_holdout_bots_excluded_from_every_selection_signal` les avait manques.
    """
    import inspect

    from ai import bot_evaluation, train

    eval_src = inspect.getsource(bot_evaluation.evaluate_against_bots)
    assert "selection_worst_bot(" in eval_src, (
        "bot_evaluation.evaluate_against_bots ne delegue plus a selection_worst_bot : "
        "worst_bot_score par-scenario risque de re-inclure le holdout (V11 §10.5)."
    )
    # Le site eval-only de train.py n'est pas isole dans une fonction : on inspecte le module.
    train_src = inspect.getsource(train)
    assert "worst_bot_name, worst_bot_score = selection_worst_bot(" in train_src, (
        "le chemin --eval de train.py ne delegue plus a selection_worst_bot (V11 §10.5)."
    )


def test_evaluation_randomness_has_no_silent_default() -> None:
    """La config `bot_eval_randomness` doit etre LUE, pas contournee par un defaut 0.15.

    `randomness_config` ne recopiait que greedy/defensive/control : aggressive_smart,
    adaptive et tactical retombaient silencieusement sur 0.15.
    """
    from ai.bot_evaluation import _create_eval_env

    with pytest.raises(KeyError, match="tactical"):
        _create_eval_env(
            bot_name="tactical",
            bot_type="tactical",
            randomness_config={"greedy": 0.05},
            scenario_file="unused.json",
            training_config_name="default",
            rewards_config_name="default",
            controlled_agent="agent",
            base_agent_key="agent",
            debug_mode=False,
            agent_seat_mode="p1",
            agent_seat_seed=None,
        )


def test_tactical_bot_is_instantiable_by_the_evaluation_factory() -> None:
    # Le poids en config ne sert a rien si la factory ne sait pas construire le bot.
    from ai.evaluation_bots import TacticalBot

    bot = TacticalBot(randomness=0.05)
    assert bot.select_action([]) is not None


# --- V11 §0.16(a) : le ranking ne doit PAS s'afficher quand l'eval est non fiable ---

_RANKING_SCORES = {
    "holdout_regular_bot-01": {"combined": 0.77, "worst_bot_score": 0.0},
    "holdout_regular_bot-02": {"combined": 0.46, "worst_bot_score": 0.0},
}


def test_scenario_ranking_shown_when_no_episode_failed() -> None:
    from ai.bot_evaluation import _render_scenario_ranking

    lines = _render_scenario_ranking(_RANKING_SCORES, total_failed_episodes=0)
    assert lines[0] == "🏁 Scenario ranking (combined):"
    # Tri decroissant par `combined` : le meilleur scenario en premier.
    assert "holdout_regular_bot-01" in lines[1]
    assert "holdout_regular_bot-02" in lines[2]
    assert not any("SUPPRIME" in l for l in lines)


def test_scenario_ranking_suppressed_when_episodes_failed() -> None:
    """Un classement calcule sur un denominateur tronque ne doit pas paraitre fiable.

    C'est la reserve ouverte de §0.16(a) : le bloc s'imprimait AVANT le raise eval-only
    sur `total_failed_episodes > 0`, presentant des `combined` partiels comme un resultat.
    """
    from ai.bot_evaluation import _render_scenario_ranking

    lines = _render_scenario_ranking(_RANKING_SCORES, total_failed_episodes=3)
    joined = "\n".join(lines)
    assert "SUPPRIME" in joined and "NON FIABLE" in joined
    assert "3 episode(s) echoue(s)" in joined
    # Aucun chiffre de classement ne doit fuiter.
    assert "🏁" not in joined
    assert "combined=" not in joined


def test_scenario_ranking_empty_when_no_scores() -> None:
    from ai.bot_evaluation import _render_scenario_ranking

    assert _render_scenario_ranking({}, total_failed_episodes=0) == []
    assert _render_scenario_ranking({}, total_failed_episodes=5) == []
