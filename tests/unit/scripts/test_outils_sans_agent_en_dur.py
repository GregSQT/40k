"""Aucun outil de `scripts/` ne porte l'agent `CoreAgent`, ni en dur ni en défaut argparse.

`config/agents/CoreAgent/` a été retiré le 2026-07-19 et le reste de la banque le 2026-09-10 :
depuis, `config_loader._resolve_agent_config_key` lève un `FileNotFoundError` sur cette clé. Un
défaut argparse qui la désigne ne rend pas l'outil utilisable sans argument — il déplace l'erreur
du parseur vers la première lecture, en la déguisant (T1). Trois traitements selon le fichier :

  - l'agent compose un chemin réellement lu (`config/agents/<agent>/...`) → l'argument devient
    OBLIGATOIRE, comme `--matchup-dir` de `roster_aggregate_rankings.py` le 2026-09-10 ;
  - l'argument n'était lu nulle part → il est retiré, pas repointé ;
  - l'outil lui-même n'avait plus d'objet → il est supprimé. C'est le cas de la chaîne
    `unit_matrix` (générateur, contrôle, synchronisation, et le JSON produit), dont la seule
    colonne propre était cet `agent_key` constant, et qu'aucun fichier de `frontend/src`
    n'importait ; sa garde utile, `check_roster_static_labels.py`, est autonome et reste.

Le balayage attrape aussi les outils écrits demain : c'est le point du contrôle par répertoire
plutôt que par liste nommée.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests._chargeur_script import charger_script

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

#: Outils dont l'agent compose un chemin lu : l'argument est obligatoire, sans valeur par défaut.
#: `(script, arguments minimaux hors agent, appel testé)` — l'appel doit sortir sur le PARSEUR,
#: donc avant tout accès disque.
OUTILS_A_AGENT_OBLIGATOIRE = (
    ("scripts/build_holdout_benchmark.py", "main"),
    ("scripts/rebalance_holdout_hard_scenarios.py", "main"),
    ("scripts/profile_env_step_360x312.py", "parse_args"),
)


def _sources() -> list[Path]:
    """Les fichiers Python de `scripts/`. Sans exclusion : aucun outil n'a de raison d'en avoir."""
    return sorted(SCRIPTS_DIR.glob("*.py"))


def test_le_balayage_ramasse_bien_les_outils() -> None:
    """VERT VACANT : un balayage vide, ou sur des fichiers vides, prouverait n'importe quoi."""
    sources = _sources()
    assert len(sources) >= 40, f"balayage anormalement court : {len(sources)} fichiers"
    assert all(p.stat().st_size > 0 for p in sources)


@pytest.mark.parametrize("source", _sources(), ids=lambda p: p.name)
def test_aucun_outil_ne_nomme_l_agent_supprime(source: Path) -> None:
    contenu = source.read_text(encoding="utf-8")
    assert "CoreAgent" not in contenu, (
        f"{source.relative_to(PROJECT_ROOT)} nomme `CoreAgent` : cet agent n'a plus de config "
        "depuis le 2026-07-19, `config_loader` lève dessus"
    )


@pytest.mark.parametrize(
    ("relatif", "appel"),
    OUTILS_A_AGENT_OBLIGATOIRE,
    ids=[Path(r).name for r, _ in OUTILS_A_AGENT_OBLIGATOIRE],
)
def test_l_agent_est_obligatoire(
    relatif: str, appel: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans l'argument d'agent, le parseur sort en code 2 — il ne retombe sur aucun défaut."""
    module = charger_script(relatif)
    monkeypatch.setattr(sys, "argv", [Path(relatif).name])
    with pytest.raises(SystemExit) as sortie:
        getattr(module, appel)()
    assert sortie.value.code == 2


def test_auto_boost_a_perdu_son_option_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--agent` n'était lu nulle part : les pools vivent sous `config/agents/_p2_rosters/`.

    Le parseur doit REFUSER l'option, pas l'accepter et l'ignorer — un argument accepté sans
    effet fait croire que l'outil travaille sur l'agent nommé.
    """
    module = charger_script("scripts/auto_boost_weak_rosters.py")
    monkeypatch.setattr(
        sys,
        "argv",
        ["auto_boost_weak_rosters.py", "--weak-ids-file", "ids.txt", "--agent", "ArmageddonAgent_x1"],
    )
    with pytest.raises(SystemExit) as sortie:
        module.main()
    assert sortie.value.code == 2
