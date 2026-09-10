"""Une méthode de victoire que le barème ne connaît pas n'est plus rangée dans « nul ».

Le barème de `stats['win_methods']` énumère trois méthodes par siège et une seule pour le nul
(`draw`). Le repli qui suivait comptait `draw` dès que le vainqueur valait -1, SANS regarder la
méthode lue : une fin d'épisode déclarée nulle par une autre voie — le moteur pose déjà
`step_limit` sur sa troncature — devenait un nul ordinaire dans le rapport, indiscernable des
vrais. Le lecteur ne pouvait pas voir que le moteur avait pris de l'avance sur l'analyzer.

Un désaccord entre ce que le moteur déclare et ce que l'analyzer sait compter se signale
désormais comme ce qu'il est : une ligne de journal que l'analyzer ne sait pas lire.
"""
from __future__ import annotations

from pathlib import Path

import ai.analyzer as an

from tests.unit.ai._fabriques import entete_step_log


def _episode(winner: int, method: str) -> str:
    return entete_step_log(
        f"[10:00:09] EPISODE END: Winner={winner}, Method={method}, Actions=0, Steps=0, "
        f"Total=0, Duration=1.000s\n",
        rosters="scale=500pts AGENT_PLAYER=1 AGENT=a (a.json) OPPONENT=o (o.json)",
        walls="none",
        ez_vertical_inches=None,
        objectives=None,
    )


def _run(tmp_path: Path, body: str) -> dict:
    path = tmp_path / "step.log"
    path.write_text(body, encoding="utf-8")
    return an.parse_step_log(str(path))


def test_un_nul_de_methode_connue_reste_compte(tmp_path: Path) -> None:
    """Contre-épreuve : sans elle, les zéros du test suivant ne prouveraient qu'un journal muet."""
    stats = _run(tmp_path, _episode(-1, "draw"))
    assert stats["win_methods"][-1]["draw"] == 1, stats["win_methods"]
    assert not stats["parse_errors"], stats["parse_errors"]


def test_un_nul_de_methode_hors_bareme_nest_pas_compte_comme_draw(tmp_path: Path) -> None:
    stats = _run(tmp_path, _episode(-1, "step_limit"))
    assert stats["win_methods"][-1]["draw"] == 0, (
        "une méthode hors barème est comptée comme un nul ordinaire : le rapport affiche un "
        "nul là où le moteur a déclaré autre chose"
    )


def test_un_nul_de_methode_hors_bareme_est_signale(tmp_path: Path) -> None:
    stats = _run(tmp_path, _episode(-1, "step_limit"))
    erreurs = [e for e in stats["parse_errors"] if "Method=step_limit" in e["error"]]
    assert len(erreurs) == 1, stats["parse_errors"]
    assert "EPISODE END" in erreurs[0]["line"]
