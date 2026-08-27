"""`bot_eval_n_workers` doit etre LU, et l'etre depuis `callback_params`.

Bug d'origine, mesure a l'appui : les quatre cles `bot_eval_scenario_pool`,
`bot_eval_show_progress`, `bot_eval_use_subprocess` et `bot_eval_n_workers` vivaient au niveau
SUPERIEUR de chaque section de phase, alors que toute la chaine les lit dans `callback_params`
(`_resolve_callback_value` dans `ai/train.py`, `require_key(callback_params, ...)` dans
`ai/bot_evaluation.py`). Elles etaient donc invisibles, et `bot_eval_n_workers` retombait sur
un repli `min(n_envs, len(scenario_list) * len(active_bot_names))` = 24 workers — quelle que
soit la valeur ecrite dans la config. Passer la cle de 6 a 2 puis a 1 n'a jamais rien change.

Cout mesure : 24 workers = 47 Go de RSS (~1,9 Go chacun), soit la mort de la VM WSL au premier
marqueur d'evaluation. Deux cles ecrites, lues nulle part, aucun message.

Famille T1 (un repli qui contredit silencieusement la config) croisee avec le motif recurrent
du depot (« code teste mais jamais appele » — ici : config ecrite mais jamais lue).

Les deux moities de l'invariant sont verrouillees :
- PLACEMENT : aucune config n'ecrit ces cles hors de `callback_params` (elles y seraient mortes) ;
- CONTRAT : aucun site de lecture ne s'en remet a un defaut silencieux.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENTS_DIR = PROJECT_ROOT / "config" / "agents"

# Cles que `evaluate_against_bots` / `_resolve_callback_value` vont chercher dans
# `callback_params`. Les ecrire ailleurs revient a ne pas les ecrire.
CALLBACK_SCOPED_KEYS = (
    "bot_eval_scenario_pool",
    "bot_eval_show_progress",
    "bot_eval_use_subprocess",
    "bot_eval_n_workers",
    "bot_eval_task_timeout_seconds",
)


def _phase_sections() -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    """(nom de fichier, nom de phase, section) pour toutes les configs d'entrainement."""
    for path in sorted(AGENTS_DIR.glob("*/*_training_config.json")):
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        for phase, section in raw.items():
            if isinstance(section, dict) and "callback_params" in section:
                yield path.name, phase, section


def test_phase_sections_exist() -> None:
    """VERT VACANT : sans section a inspecter, les tests suivants passeraient a vide."""
    sections = list(_phase_sections())
    assert sections, f"aucune section de phase trouvee sous {AGENTS_DIR}"


@pytest.mark.parametrize("filename,phase,section", list(_phase_sections()))
def test_bot_eval_keys_live_in_callback_params(
    filename: str, phase: str, section: Dict[str, Any]
) -> None:
    """Les cles sont DANS callback_params et nulle part ailleurs. ROUGE avant le fix."""
    callback_params = section["callback_params"]
    for key in CALLBACK_SCOPED_KEYS:
        assert key not in section, (
            f"{filename}[{phase}].{key} est au niveau superieur de la section : personne ne "
            "l'y lit, la valeur est morte. Elle doit vivre dans callback_params."
        )
        assert key in callback_params, (
            f"{filename}[{phase}].callback_params.{key} manquant : "
            "la lecture est un require_key, le run leverait au premier marqueur d'evaluation."
        )


@pytest.mark.parametrize("filename,phase,section", list(_phase_sections()))
def test_bot_eval_n_workers_is_a_positive_int(
    filename: str, phase: str, section: Dict[str, Any]
) -> None:
    """Un `null` reintroduirait le repli a 24 workers via _training_common.json."""
    value = section["callback_params"]["bot_eval_n_workers"]
    assert isinstance(value, int) and not isinstance(value, bool) and value > 0, (
        f"{filename}[{phase}].callback_params.bot_eval_n_workers = {value!r} ; "
        "un entier > 0 est exige (le pic mesure est de ~1,9 Go par worker)."
    )


def _callback_params_get_calls() -> list:
    """Les `callback_params.get(<literal>, ...)` de `ai/bot_evaluation.py`."""
    source = (PROJECT_ROOT / "ai" / "bot_evaluation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            continue
        if not isinstance(func.value, ast.Name) or func.value.id != "callback_params":
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            found.append((node.args[0].value, node.lineno))
    return found


def test_no_silent_default_on_guarded_callback_params_reads() -> None:
    """Aucune des cles gardees n'est lue par `.get()`. ROUGE avant le fix (T1)."""
    offenders = [
        (key, lineno) for key, lineno in _callback_params_get_calls()
        if key in CALLBACK_SCOPED_KEYS
    ]
    assert not offenders, (
        "ai/bot_evaluation.py lit ces cles avec callback_params.get() : un defaut silencieux "
        f"y contredirait la config sans le dire — {offenders}. Utiliser require_key."
    )


def test_validator_rejects_each_bad_value() -> None:
    """La fabrique leve sur cle absente, mauvais type ou valeur <= 0. ROUGE avant le fix."""
    from ai.bot_evaluation import validate_bot_eval_worker_params

    valid = {
        "bot_eval_use_subprocess": True,
        "bot_eval_task_timeout_seconds": 3600,
        "bot_eval_n_workers": 4,
    }
    assert validate_bot_eval_worker_params(dict(valid)) == {
        "use_subprocess": True, "task_timeout_seconds": 3600, "n_workers": 4, "n_workers_gate": None,
    }
    # Avec bot_eval_n_workers_gate present, il est retourne.
    assert validate_bot_eval_worker_params({**valid, "bot_eval_n_workers_gate": 2}) == {
        "use_subprocess": True, "task_timeout_seconds": 3600, "n_workers": 4, "n_workers_gate": 2,
    }
    from shared.data_validation import ConfigurationError  # ce que leve require_key

    for key in valid:  # absence des cles obligatoires
        broken = {k: v for k, v in valid.items() if k != key}
        with pytest.raises(ConfigurationError):
            validate_bot_eval_worker_params(broken)
    for key, bad in (
        ("bot_eval_use_subprocess", "true"),         # chaine, pas booleen
        ("bot_eval_task_timeout_seconds", 0),        # pas de timeout instantane
        ("bot_eval_n_workers", 0),                   # 0 worker = aucune tache executee
        ("bot_eval_n_workers", None),                # le `null` qui reintroduisait le repli a 24
        ("bot_eval_n_workers", True),                # bool est un int en Python : doit etre refuse
        ("bot_eval_n_workers_gate", 0),              # 0 worker gate = invalide
        ("bot_eval_n_workers_gate", True),           # bool refuse
        ("bot_eval_n_workers_gate", -1),             # negatif refuse
    ):
        with pytest.raises((ValueError, TypeError)):
            validate_bot_eval_worker_params({**valid, key: bad})


def test_startup_validates_worker_params() -> None:
    """`ai/train.py` appelle la fabrique au demarrage. ROUGE avant le fix.

    Sans cet appel, une config incomplete n'arrete le run qu'au premier marqueur
    d'evaluation — le defaut meme que ce correctif invoque pour deplacer les controles.
    """
    tree = ast.parse((PROJECT_ROOT / "ai" / "train.py").read_text(encoding="utf-8"))
    called = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "validate_bot_eval_worker_params"
        for node in ast.walk(tree)
    )
    assert called, (
        "ai/train.py n'appelle pas validate_bot_eval_worker_params : les 3 cles ne seraient "
        "verifiees qu'au premier marqueur d'evaluation."
    )


def test_guarded_keys_are_read_with_require_key() -> None:
    """Contrepartie du test precedent : supprimer la lecture n'est pas une facon de le faire passer."""
    source = (PROJECT_ROOT / "ai" / "bot_evaluation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    required = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "require_key":
            continue
        if len(node.args) == 2 and isinstance(node.args[0], ast.Name) \
                and node.args[0].id == "callback_params" \
                and isinstance(node.args[1], ast.Constant):
            required.add(node.args[1].value)
    for key in ("bot_eval_use_subprocess", "bot_eval_n_workers", "bot_eval_task_timeout_seconds"):
        assert key in required, (
            f"ai/bot_evaluation.py ne lit plus {key} via require_key(callback_params, ...)"
        )
