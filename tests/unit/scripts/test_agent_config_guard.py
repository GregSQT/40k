"""Guard : un commit documentaire ne doit pas modifier silencieusement un champ
pilotant l'entraînement dans config/agents/**/*.json.

DOC_KEYS liste les seules clés dont le contenu est autorisé à différer entre le
working tree et HEAD (notes, justifications, valeurs textuelles sans effet sur
l'entraînement). Toute autre divergence fait échouer le test.

Rejouable à tout moment : si le working tree est propre vs HEAD, le test est vert
sans contenu (il n'y a rien à vérifier). Il n'est utile qu'avant un commit
présenté comme documentaire, ou dans un hook pre-commit.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DOC_KEYS: frozenset[str] = frozenset({"justification", "total_episodes_normal"})


def _strip_doc_keys(obj: Any) -> Any:
    """Élimine récursivement les clés de DOC_KEYS de tout arbre JSON."""
    if isinstance(obj, dict):
        return {k: _strip_doc_keys(v) for k, v in obj.items() if k not in DOC_KEYS}
    if isinstance(obj, list):
        return [_strip_doc_keys(item) for item in obj]
    return obj


def _changed_agent_configs(root: Path = PROJECT_ROOT) -> list[Path]:
    """Fichiers .json sous config/agents/ modifiés dans le working tree vs HEAD."""
    result = subprocess.run(
        [
            "git", "diff", "HEAD", "--name-only",
            "--diff-filter=M", "--", "config/agents/",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    paths = []
    for line in result.stdout.splitlines():
        p = root / line.strip()
        if p.suffix == ".json" and p.is_file():
            paths.append(p)
    return paths


def _head_json(path: Path, root: Path = PROJECT_ROOT) -> Any | None:
    """Retourne l'arbre JSON de la version HEAD du fichier, ou None si absent."""
    rel = path.relative_to(root)
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel.as_posix()}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def _check_training_fields(root: Path = PROJECT_ROOT) -> list[str]:
    """Retourne les chemins relatifs des configs dont les champs d'entraînement diffèrent de HEAD."""
    failures: list[str] = []
    for path in _changed_agent_configs(root):
        head_obj = _head_json(path, root)
        if head_obj is None:
            continue
        if _strip_doc_keys(head_obj) != _strip_doc_keys(json.loads(path.read_text(encoding="utf-8"))):
            failures.append(str(path.relative_to(root)))
    return failures


# --- helpers pour les tests de mutation ---


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def agent_config_repo(tmp_path: Path) -> Path:
    """Dépôt git minimal avec une config d'agent commitée."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@t.t", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)

    cfg_dir = repo / "config" / "agents"
    cfg_dir.mkdir(parents=True)
    cfg = cfg_dir / "agent_training_config.json"
    cfg.write_text(
        json.dumps({
            "seed": 12345,
            "total_episodes": 10000,
            "total_episodes_normal": "note doc initiale",
            "nested": {"justification": "raison initiale", "learning_rate": 0.002},
        }),
        encoding="utf-8",
    )
    _git("add", "config/agents/agent_training_config.json", cwd=repo)
    _git("commit", "-qm", "init", cwd=repo)
    return repo


# --- tests unitaires des helpers ---


def test_strip_doc_keys_removes_exact_keys() -> None:
    obj = {
        "total_episodes": 10000,
        "total_episodes_normal": "note documentaire",
        "justification": "raison du choix",
        "nested": {
            "justification": "dans un sous-objet",
            "learning_rate": 0.002,
        },
        "arr": [{"justification": "dans une liste", "x": 1}],
    }
    result = _strip_doc_keys(obj)
    assert result == {
        "total_episodes": 10000,
        "nested": {"learning_rate": 0.002},
        "arr": [{"x": 1}],
    }


def test_strip_doc_keys_preserves_non_doc_fields() -> None:
    obj = {"seed": 42, "n_envs": 48, "model_params": {"policy": "MultiInputPolicy"}}
    assert _strip_doc_keys(obj) == obj


def test_strip_doc_keys_on_scalar_is_identity() -> None:
    assert _strip_doc_keys(42) == 42
    assert _strip_doc_keys("texte") == "texte"


# --- tests de mutation sur dépôt fixture ---


def test_guard_passes_when_only_doc_key_changed(agent_config_repo: Path) -> None:
    """Modifier seulement total_episodes_normal ou justification → vert."""
    cfg = agent_config_repo / "config" / "agents" / "agent_training_config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["total_episodes_normal"] = "note documentaire mise à jour"
    data["nested"]["justification"] = "nouvelle raison"
    cfg.write_text(json.dumps(data), encoding="utf-8")

    assert _check_training_fields(agent_config_repo) == []


def test_guard_fails_when_training_field_changed(agent_config_repo: Path) -> None:
    """Modifier un champ d'entraînement (seed) → rouge, même si une doc-key bouge aussi."""
    cfg = agent_config_repo / "config" / "agents" / "agent_training_config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["seed"] = 99999  # champ d'entraînement
    data["total_episodes_normal"] = "note mise à jour en même temps"  # doc-key
    cfg.write_text(json.dumps(data), encoding="utf-8")

    failures = _check_training_fields(agent_config_repo)
    assert failures == ["config/agents/agent_training_config.json"]


def test_guard_fails_when_nested_training_field_changed(agent_config_repo: Path) -> None:
    """Modifier learning_rate imbriqué → rouge."""
    cfg = agent_config_repo / "config" / "agents" / "agent_training_config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["nested"]["learning_rate"] = 0.001
    cfg.write_text(json.dumps(data), encoding="utf-8")

    failures = _check_training_fields(agent_config_repo)
    assert failures == ["config/agents/agent_training_config.json"]


# --- garde principal ---


def test_no_training_field_changed_vs_head() -> None:
    """Les champs d'entraînement de config/agents/ ne diffèrent pas de HEAD."""
    failures = _check_training_fields(PROJECT_ROOT)
    assert not failures, (
        "Champs hors DOC_KEYS modifiés dans config/agents/ par rapport à HEAD "
        f"({', '.join(sorted(DOC_KEYS))}) :\n"
        + "\n".join(f"  {f}" for f in sorted(failures))
    )
