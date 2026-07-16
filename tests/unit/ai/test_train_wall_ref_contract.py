"""T6 (V11_agent_rework.md) — contrat wall_ref du sampler de scénarios.

Contexte : la migration T4 a rendu la banque de scénarios TERRAIN-ONLY (le script
`migrate_scenario_bank_v11.py` supprime la clé legacy `wall_ref` ; les murs viennent
désormais du `terrain_ref`, de façon additive côté moteur — game_state.py). Le sampler
`_apply_wall_ref_weighting` de train.py, lui, exigeait encore un `wall_ref` par scénario
via `require_key` → `ConfigurationError: Required key 'wall_ref' is missing` au lancement
de `train.py --scenario bot` (rupture T6, reliquat de T4).

Verrouille :
- `_load_scenario_wall_ref` : None quand la clé est ABSENTE (contrat T4 légitime, pas une
  valeur par défaut masquant une erreur) ; valeur stricte quand elle est présente ;
  erreur explicite quand elle est présente mais invalide (non-régression).
- `_apply_wall_ref_weighting` : fonctionne de bout en bout sur un scénario terrain-only et
  n'injecte AUCUN wall_ref (le poids "default" = « garde les murs du scénario »).
- `_materialize_scenario_with_refs` : le paramètre `objectives_ref` est purgé (hygiène T6) —
  les objectifs ont pour source unique les terrains (14.01/14.02) et le moteur REJETTE la
  clé legacy `objectives_ref`. Aucun scénario matérialisé ne doit la porter.
"""
import json
import sys
import types
from pathlib import Path

import pytest

if "ai.multi_agent_trainer" not in sys.modules:
    _stub = types.ModuleType("ai.multi_agent_trainer")
    setattr(_stub, "MultiAgentTrainer", object)
    sys.modules["ai.multi_agent_trainer"] = _stub

import ai.train as train

# Scénario au contrat T4 réel (cf. config/agents/CoreAgent/scenarios/training/*.json) :
# board_ref + terrain_ref, AUCUN wall_ref.
TERRAIN_ONLY_SCENARIO = {
    "deployment_type": "active",
    "scale": "150pts",
    "agent_roster_ref": "training_random",
    "opponent_roster_ref": "training_random",
    "primary_objectives": ["objectives_control"],
    "board_ref": "44x60x5",
    "terrain_ref": "terrain-train-01.json",
}


def _write(tmp_path: Path, name: str, data: dict) -> str:
    # Le chemin doit contenir 'agents' (contrainte de _materialize_scenario_with_refs).
    target = tmp_path / "agents" / "CoreAgent" / "scenarios" / "training"
    target.mkdir(parents=True, exist_ok=True)
    path = target / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_load_scenario_wall_ref_absent_returns_none(tmp_path):
    """Contrat T4 terrain-only : absence de wall_ref => None (échouait avant le fix T6)."""
    path = _write(tmp_path, "scenario_training_bot-01.json", TERRAIN_ONLY_SCENARIO)
    assert train._load_scenario_wall_ref(path) is None


def test_load_scenario_wall_ref_present_returned_stripped(tmp_path):
    """Une clé présente reste lue strictement (non-régression du chemin legacy supporté)."""
    data = dict(TERRAIN_ONLY_SCENARIO, wall_ref="  walls-33.json  ")
    path = _write(tmp_path, "scenario_with_walls.json", data)
    assert train._load_scenario_wall_ref(path) == "walls-33.json"


@pytest.mark.parametrize("bad", ["", "   ", 42, None, []])
def test_load_scenario_wall_ref_present_but_invalid_raises(tmp_path, bad):
    """Présente-mais-invalide reste une erreur explicite : le fix ne dilue pas la validation."""
    data = dict(TERRAIN_ONLY_SCENARIO, wall_ref=bad)
    path = _write(tmp_path, "scenario_bad_walls.json", data)
    with pytest.raises(ValueError, match="wall_ref must be a non-empty string"):
        train._load_scenario_wall_ref(path)


def test_apply_wall_ref_weighting_terrain_only_scenario(tmp_path):
    """Repro de la rupture T6 : le sampler doit traverser un scénario sans wall_ref."""
    path = _write(tmp_path, "scenario_training_bot-01.json", TERRAIN_ONLY_SCENARIO)
    training_config = {"scenario_sampling": {"train_wall_ref_weights": {"default": 1.0}}}

    weighted = train._apply_wall_ref_weighting(
        scenario_list=[path], training_config=training_config
    )

    assert len(weighted) > 0
    # Poids "default" => aucun override : le scénario d'origine est réutilisé tel quel.
    assert set(weighted) == {path}
    # Et il reste terrain-only : aucun wall_ref n'a été injecté.
    assert "wall_ref" not in json.loads(Path(path).read_text(encoding="utf-8"))


def test_materialize_scenario_with_refs_has_no_objectives_ref_param(tmp_path):
    """Hygiène T6 : le paramètre objectives_ref est purgé (clé rejetée par le moteur)."""
    path = _write(tmp_path, "scenario_training_bot-01.json", TERRAIN_ONLY_SCENARIO)

    with pytest.raises(TypeError):
        # Paramètre volontairement inexistant : c'est l'objet du test (l'appel doit lever).
        train._materialize_scenario_with_refs(scenario_path=path, objectives_ref="objectives-51.json")  # type: ignore[call-arg]


def test_materialize_scenario_with_refs_wall_override_emits_no_legacy_key(tmp_path):
    """Un override de murs produit wall_ref et JAMAIS de clé objectifs legacy."""
    path = _write(tmp_path, "scenario_training_bot-01.json", TERRAIN_ONLY_SCENARIO)

    out = train._materialize_scenario_with_refs(scenario_path=path, wall_ref="walls-33.json")
    produced = json.loads(Path(out).read_text(encoding="utf-8"))

    assert produced["wall_ref"] == "walls-33.json"
    assert produced["terrain_ref"] == "terrain-train-01.json"  # terrain préservé
    for legacy in ("objectives", "objectives_ref", "objective_hexes"):
        assert legacy not in produced


def test_materialize_scenario_with_refs_none_is_passthrough(tmp_path):
    """Sans override, le chemin d'origine est retourné tel quel (aucune copie temporaire)."""
    path = _write(tmp_path, "scenario_training_bot-01.json", TERRAIN_ONLY_SCENARIO)
    assert train._materialize_scenario_with_refs(scenario_path=path, wall_ref=None) == path
