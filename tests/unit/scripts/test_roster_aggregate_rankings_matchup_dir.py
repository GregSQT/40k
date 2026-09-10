"""`--matchup-dir` est une donnée obligatoire, pas un défaut vers un dossier disparu.

Le défaut historique pointait `config/agents/CoreAgent/rosters/150pts/matchups`, un dossier
supprimé avec le reste de `config/agents/CoreAgent/` le 2026-09-10. Un défaut qui ne désigne
aucun dossier existant ne rend pas l'outil utilisable sans argument : il déplace l'erreur du
parseur vers la première lecture, en la déguisant. Le script dérive de toute façon l'agent et
l'échelle du chemin donné (`agent_key_and_scale_from_matchup_dir`), donc aucune valeur par
défaut n'est légitime ici.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "scripts" / "roster_aggregate_rankings.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("roster_aggregate_rankings", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_refuse_de_tourner_sans_matchup_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    monkeypatch.setattr(sys, "argv", ["roster_aggregate_rankings.py"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2


def test_aucun_chemin_dagent_en_dur_dans_le_script() -> None:
    """VERT VACANT : le fichier doit être lu et non vide pour que l'absence prouve quelque chose."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "argparse" in source, "le script lu n'est pas celui attendu"
    assert "CoreAgent" not in source
