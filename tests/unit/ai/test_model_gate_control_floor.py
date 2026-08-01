"""Le gate de selection porte un PLANCHER sur `vs_control`.

Pourquoi : la victoire se decide aux VP d'objectifs (`determine_winner_with_method` : les kills
ne tranchent qu'a egalite), et `ControlBot` est le seul adversaire du panel dont la doctrine est
de prendre et tenir les objectifs. Mesure a l'origine du plancher : sur deux runs successifs, le
win-rate contre chaque bot suivait exactement le rapport de ce bot aux objectifs, et le
`combined` MONTAIT (0.62 -> 0.65) pendant que `vs_control` BAISSAIT (0.33 -> 0.27). Une moyenne
ponderee peut donc progresser en perdant la competence decisive : il faut un seuil dur.

Le plancher s'AJOUTE aux trois criteres existants, il ne les remplace pas — sans `combined` ni
`worst_bot`, un modele effondre contre les trois autres bots resterait selectionnable.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ai.training_callbacks import BotEvaluationCallback

CONFIG_ROOT = Path(__file__).resolve().parents[3] / "config" / "agents"


def _gate(**thresholds: float) -> BotEvaluationCallback:
    """Callback reduit a son gate : aucun env, aucun modele, aucune eval reelle."""
    callback = BotEvaluationCallback.__new__(BotEvaluationCallback)
    callback.model_gating_enabled = True
    callback.model_gating_min_combined = thresholds["combined"]
    callback.model_gating_min_worst_bot = thresholds["worst_bot"]
    callback.model_gating_min_worst_scenario_combined = thresholds["worst_scenario"]
    callback.model_gating_min_vs_control = thresholds["vs_control"]
    callback.gating_pass_count = 0
    callback.gating_fail_count = 0
    callback.best_gating_criteria_mean = None
    callback.last_gate_pass = None
    callback.thresholds_ever_passed = False
    callback.use_episode_freq = True
    callback.gate_display_state = None
    callback.gating_history = []
    return callback


def _results(control: float, others: float = 0.90) -> Dict[str, Any]:
    """Une eval ou TOUT est bon sauf, eventuellement, `vs_control`."""
    return {
        "combined": 0.80,
        "control": control,
        "adaptive": others,
        "greedy": others,
        "defensive": others,
        "scenario_scores": {"s1": {"combined": 0.80}},
    }


# Les seuils des trois criteres historiques sont volontairement BAS dans ces doublures : c'est
# ce qui isole le plancher `vs_control` comme SEUL critere discriminant (un `worst_bot` a 0.40
# aurait recale le modele avant meme de regarder le plancher, et le test aurait ete vert pour
# la mauvaise raison).

def test_gate_fails_when_vs_control_is_below_the_floor(capsys: pytest.CaptureFixture) -> None:
    """Tous les autres criteres passent ; seul `vs_control` est sous le plancher -> REFUSE.

    Preuve que c'est bien LUI qui tranche : le MEME etat, plancher a 0.0, passe.
    """
    results = _results(control=0.20)

    strict = _gate(combined=0.60, worst_bot=0.10, worst_scenario=0.40, vs_control=0.30)
    assert strict._evaluate_model_gate(results, eval_marker=2000) is False

    without_floor = _gate(combined=0.60, worst_bot=0.10, worst_scenario=0.40, vs_control=0.0)
    assert without_floor._evaluate_model_gate(results, eval_marker=2000) is True
    capsys.readouterr()


def test_gate_passes_when_vs_control_reaches_the_floor(capsys: pytest.CaptureFixture) -> None:
    """Meme etat, `vs_control` juste AU seuil : le gate passe (comparaison >=)."""
    gate = _gate(combined=0.60, worst_bot=0.10, worst_scenario=0.40, vs_control=0.30)

    assert gate._evaluate_model_gate(_results(control=0.30), eval_marker=2000) is True
    capsys.readouterr()


def test_control_floor_does_not_replace_the_other_criteria(capsys: pytest.CaptureFixture) -> None:
    """Excellent contre control, effondre contre le reste -> REFUSE.

    C'est la raison d'etre du choix « plancher » plutot que « selection sur vs_control seul » :
    ici le plancher est LARGEMENT franchi (0.95 vs 0.30) et le modele est refuse quand meme.
    """
    gate = _gate(combined=0.60, worst_bot=0.10, worst_scenario=0.40, vs_control=0.30)
    results = _results(control=0.95, others=0.05)

    assert gate._evaluate_model_gate(results, eval_marker=2000) is False
    capsys.readouterr()


def test_floor_applies_even_when_full_gating_is_disabled(capsys: pytest.CaptureFixture) -> None:
    """`model_gating_enabled: false` (l'etat des 5 profils) ne desarme PAS le plancher.

    Sans cela le plancher serait purement decoratif : `_evaluate_model_gate` rendait True sans
    rien regarder, et les DEUX chemins de sauvegarde (best_combined et best_robust) sont gardes
    par ce `gate_pass`. Seul un seuil a 0.0 desarme le plancher.
    """
    gate = _gate(combined=0.60, worst_bot=0.10, worst_scenario=0.40, vs_control=0.30)
    gate.model_gating_enabled = False

    assert gate._evaluate_model_gate(_results(control=0.20), eval_marker=2000) is False
    assert gate._evaluate_model_gate(_results(control=0.40), eval_marker=2000) is True

    disarmed = _gate(combined=0.60, worst_bot=0.10, worst_scenario=0.40, vs_control=0.0)
    disarmed.model_gating_enabled = False
    assert disarmed._evaluate_model_gate(_results(control=0.0), eval_marker=2000) is True
    capsys.readouterr()


def test_missing_control_score_is_an_explicit_error(capsys: pytest.CaptureFixture) -> None:
    """`control` est un bot PONDERE : son absence est une config incoherente, pas un defaut."""
    from shared.data_validation import ConfigurationError

    gate = _gate(combined=0.60, worst_bot=0.40, worst_scenario=0.40, vs_control=0.30)
    results = _results(control=0.50)
    del results["control"]

    with pytest.raises(ConfigurationError, match="control"):
        gate._evaluate_model_gate(results, eval_marker=2000)
    capsys.readouterr()


def _active_training_configs() -> List[Path]:
    files = sorted(
        agent_dir / f"{agent_dir.name}_training_config.json"
        for agent_dir in CONFIG_ROOT.iterdir()
        if agent_dir.is_dir() and (agent_dir / f"{agent_dir.name}_training_config.json").exists()
    )
    assert files, f"Aucune config d'entrainement active sous {CONFIG_ROOT}"
    return files


def test_no_shared_fallback_for_the_control_floor() -> None:
    """`_training_common.json` ne doit PAS definir le plancher.

    Decision : ce seuil decide si un modele est sauve ou jete, il doit etre un choix EXPLICITE
    du profil qu'on lance — jamais une valeur heritee d'un fichier commun a tous les agents.
    `train.py` le lit donc directement dans `callback_params`, sans passer par
    `_resolve_callback_value`, et leve si la cle manque. Ce test verrouille la decision : le
    jour ou quelqu'un repose la cle dans le fichier commun, elle serait silencieusement heritee
    par tout profil qui l'oublie.
    """
    shared_path = CONFIG_ROOT / "_training_common.json"
    with shared_path.open(encoding="utf-8-sig") as handle:
        shared = json.load(handle)

    assert "model_gating_min_vs_control" not in shared, (
        "_training_common.json definit model_gating_min_vs_control : un profil qui oublie ce "
        "plancher en heriterait en silence. Le seuil appartient au profil de l'agent."
    )


@pytest.mark.parametrize("config_path", _active_training_configs(), ids=lambda p: p.parent.name)
def test_every_profile_declares_the_control_floor(config_path: Path) -> None:
    """La cle est OBLIGATOIRE dans CHAQUE profil : `train.py` la lit sans aucun repli."""
    with config_path.open(encoding="utf-8-sig") as handle:
        config = json.load(handle)

    profiles = [
        (name, cfg["callback_params"])
        for name, cfg in config.items()
        if isinstance(cfg, dict) and "callback_params" in cfg
    ]
    assert profiles, f"{config_path.name} : aucun profil avec callback_params"
    for name, params in profiles:
        assert "model_gating_min_vs_control" in params, (
            f"{config_path.name}[{name}] : plancher `vs_control` absent — `setup_callbacks` "
            "leve au lancement du run (aucun repli sur _training_common.json)."
        )
        value = float(params["model_gating_min_vs_control"])
        assert 0.0 <= value <= 1.0, f"{config_path.name}[{name}] : plancher hors [0,1] ({value})"
