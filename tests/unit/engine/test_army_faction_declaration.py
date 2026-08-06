"""Verrou de DONNÉES : la Faction d'Armée (08.04) est déclarée partout où une partie se joue.

`engine.game_state.army_faction` lève quand la déclaration manque, et elle lève TARD : à la
première phase de commandement, donc en plein épisode ou en pleine partie PvP. Les trois
familles de fichiers qui décrivent une armée doivent donc la porter :

  - les SCÉNARIOS à `units` (PvP/PvE, fixtures de test) — un dict par joueur ;
  - les ROSTERS compacts (`config/agents/**`), que les scénarios d'entraînement tirent au sort
    à chaque épisode — un scalaire, parce qu'un fichier décrit UNE liste ;
  - les FICHIERS D'ARMÉE (`config/armies/*.json`), chargés par `change_roster` en déploiement.

Un scénario à `agent_roster_ref` n'en déclare volontairement PAS : sa faction vient du roster
effectivement tiré, et une déclaration de scénario décrirait l'armée d'un autre épisode.

Ce fichier est le jumeau de `tests/unit/scripts/test_scenario_generators_declare_codex_detachment.py`
— même nature de champ, même mode de panne, mêmes emplacements.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _check_declaration(declaration, players, label: str) -> None:
    """La forme QUE LE MOTEUR EXIGE : dict par joueur, clés `str`, valeurs non vides."""
    assert isinstance(declaration, dict), (
        f"{label} : `army_faction` doit etre un dict par joueur, recu {type(declaration).__name__}"
    )
    for player in players:
        assert str(player) in declaration, (
            f"{label} : `army_faction` n'a pas d'entree pour le joueur {player} ({declaration!r})"
        )
        value = declaration[str(player)]
        assert isinstance(value, str) and value.strip(), (
            f"{label} : `army_faction[{player}]` doit etre un mot-cle non vide, recu {value!r}"
        )


def _scenario_files() -> list[Path]:
    """Scénarios versionnés qui posent leurs unités eux-mêmes (hors rosters tirés au sort)."""
    found: list[Path] = []
    for pattern in ("config/*.json", "config/board/*/scenario/*.json",
                    "config/agents/*/scenarios/**/*.json", "frontend/public/config/scenario.json"):
        for path in PROJECT_ROOT.glob(pattern):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(data, dict) and isinstance(data.get("units"), list) and data["units"]:
                found.append(path)
    return sorted(found)


def _roster_files() -> list[Path]:
    found = [
        path for path in PROJECT_ROOT.glob("config/agents/**/*.json")
        if isinstance(json.loads(path.read_text(encoding="utf-8-sig")), dict)
        and "composition" in json.loads(path.read_text(encoding="utf-8-sig"))
    ]
    return sorted(found)


def test_les_scenarios_a_unites_declarent_la_faction_de_chaque_camp() -> None:
    scenarios = _scenario_files()
    # VERT VACANT : une énumération qui ne rend rien afficherait « tout va bien ».
    assert scenarios, "aucun scenario a `units` trouve — l'enumeration ne regarde rien"
    for path in scenarios:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        players = sorted(
            {unit["player"] for unit in data["units"] if unit.get("player") is not None}
        )
        assert players, f"{path} : aucune unite avec un `player`"
        _check_declaration(data.get("army_faction"), players, str(path.relative_to(PROJECT_ROOT)))


def test_les_rosters_compacts_declarent_leur_faction() -> None:
    rosters = _roster_files()
    assert rosters, "aucun roster compact trouve — l'enumeration ne regarde rien"
    for path in rosters:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        value = data.get("army_faction")
        assert isinstance(value, str) and value.strip(), (
            f"{path.relative_to(PROJECT_ROOT)} : `army_faction` scalaire non vide attendu, "
            f"recu {value!r} — un fichier de roster decrit UNE liste"
        )


def test_les_fichiers_d_armee_declarent_leur_faction() -> None:
    armies = sorted((PROJECT_ROOT / "config" / "armies").glob("*.json"))
    assert armies, "aucun fichier d'armee trouve — l'enumeration ne regarde rien"
    for path in armies:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        value = data.get("army_faction")
        assert isinstance(value, str) and value.strip(), (
            f"{path.name} : `army_faction` scalaire non vide attendu, recu {value!r}"
        )


@pytest.mark.parametrize("relative", ("shared/rule_checker_scenarios.py", "scripts/smoke_t5_bare.py"))
def test_les_generateurs_de_scenarios_a_unites_declarent_la_faction(relative: str) -> None:
    """Les deux générateurs qui écrivent des scénarios à `units`.

    Les deux autres (`roster_matchup_stats`, `build_holdout_benchmark`) écrivent des scénarios à
    rosters : leur faction vient du roster tiré, et c'est le test des rosters qui la couvre.
    """
    source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
    assert '"army_faction"' in source, (
        f"{relative} ecrit des scenarios a `units` sans declarer `army_faction` — 08.04 levera "
        "a la premiere phase de commandement"
    )
