"""Verrou : tout scenario ECRIT par un script declare `uses_codex_detachment`.

Ce champ est OBLIGATOIRE des qu'une armee ADEPTUS ASTARTES est en jeu — `game_state.
uses_codex_detachment` leve sinon, et il leve TARD : au premier jet de blessure d'un marine
contre la cible d'Oath, donc en plein episode, apres des minutes de generation et de run. Les
scenarios commites, eux, portent tous la cle ; ce sont les GENERATEURS qui l'avaient perdue, et
une regeneration l'effacait des fichiers commites sans qu'aucun test ne bouge.

Deux verrous complementaires :
  - un STATIQUE, qui couvre les trois sites d'ecriture a la fois (le payload rule-checker n'est
    pas extractible sans lancer la generation, qui ecrit sous `config/`) ;
  - un FONCTIONNEL, qui fait relire la valeur emise par le LECTEUR du moteur — un test de
    presence de cle laisserait passer une forme que le moteur refuse.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

from engine.game_state import uses_codex_detachment

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Les scripts qui ECRIVENT des scenarios. `primary_objectives` est le marqueur d'un payload de
#: scenario : il est present dans les trois, et absent de tout autre dict de ces fichiers.
SCENARIO_WRITERS = (
    "scripts/roster_matchup_stats.py",
    "scripts/build_holdout_benchmark.py",
    "scripts/smoke_t5_bare.py",
)


def _scenario_payload_literals(path: Path) -> list[ast.Dict]:
    """Les dict litteraux de `path` qui sont des payloads de scenario."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if "primary_objectives" in keys:
            found.append(node)
    return found


@pytest.mark.parametrize("relative", SCENARIO_WRITERS)
def test_every_generated_scenario_declares_codex_detachment(relative: str) -> None:
    payloads = _scenario_payload_literals(PROJECT_ROOT / relative)
    # VERT VACANT : un fichier dont on n'extrait AUCUN payload passerait le test sans rien
    # regarder. L'echantillon doit exister avant d'etre juge.
    assert payloads, f"aucun payload de scenario trouve dans {relative}"
    for payload in payloads:
        emitted = {
            k.value: v for k, v in zip(payload.keys, payload.values)
            if isinstance(k, ast.Constant)
        }
        assert "uses_codex_detachment" in emitted, (
            f"{relative}:{payload.lineno} ecrit un scenario sans `uses_codex_detachment` — "
            "il levera au premier jet de blessure d'un marine sous Oath of Moment"
        )
        # La VALEUR, pas seulement la cle : `True` nu, `{"1": True}` seul ou des cles entieres
        # passeraient une verification de presence et leveraient quand meme (TypeError/KeyError)
        # en plein episode — exactement la panne tardive que ce fichier existe pour empecher.
        # Le litteral est deja dans le noeud AST : c'est le LECTEUR du moteur qui le juge.
        value = ast.literal_eval(emitted["uses_codex_detachment"])
        for player in (1, 2):
            assert uses_codex_detachment({"config": {"uses_codex_detachment": value}}, player), (
                f"{relative}:{payload.lineno} : valeur illisible ou fausse pour le joueur "
                f"{player} ({value!r})"
            )


def _load(relative: str):
    path = PROJECT_ROOT / relative
    spec = importlib.util.spec_from_file_location(f"{path.stem}_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_emitted_value_is_the_one_the_engine_reads() -> None:
    """La valeur emise traverse le LECTEUR du moteur, pour les DEUX joueurs.

    `_build_scenario_template` est le seul des trois generateurs dont le payload s'obtient sans
    ecrire sous `config/` ; c'est donc lui qui porte la preuve de FORME, commune aux trois
    (meme litteral `{"1": True, "2": True}`).
    """
    template = _load("scripts/roster_matchup_stats.py")._build_scenario_template(
        "100pts", "44x60x5", "terrain-mc1.json"
    )
    for player in (1, 2):
        assert uses_codex_detachment({"config": template}, player) is True
