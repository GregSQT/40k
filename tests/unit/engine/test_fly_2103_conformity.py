#!/usr/bin/env python3
"""Conformité « Take to the skies » (Règles 21.03, PDF `21 Flying and surging`).

Texte de référence (21.03 FLYING MODELS) :

    « Each time a FLYING unit is selected to make a normal, advance, fall-back or charge move,
      before moving any models in that unit, the active player can declare that it will take to
      the skies. If it does, while resolving that move:
        - Subtract 2" from the maximum distance.
        - Each time a FLYING model moves:
            - Ignore all vertical distance for the purposes of how far it has moved.
            - It can move through all types of model (including enemy models and
              MONSTER/VEHICLE models).
            - It can move horizontally and vertically through all categories of terrain feature. »

Trois défauts sont verrouillés ici :

1. **Casse du keyword** — la reconnaissance du keyword FLY doit être insensible à la casse : le
   corpus de rosters écrit `"fly"` (16 fichiers) ET `"FLY"` (6 fichiers), dont cinq types du
   roster d'entraînement d'ArmageddonAgent.
2. **Traversée gratuite en entraînement** — la traversée (murs/figurines/vertical) est la
   CONTREPARTIE d'une déclaration qui coûte 2". Sans déclaration : aucune traversée.
3. **Vol de charge inaccessible à l'IA** — 21.03 nomme explicitement le *charge move*.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pytest

from engine.phase_handlers.movement_handlers import _unit_has_keyword


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARMAGEDDON_ROSTERS = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "rosters" / "500pts"
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Casse du keyword — sur le VRAI roster, chargé par le VRAI chargeur
# ─────────────────────────────────────────────────────────────────────────────


def _armageddon_unit_types() -> List[str]:
    """Tous les `unit_type` cités par les rosters d'ArmageddonAgent (training + holdout)."""
    types: Set[str] = set()
    roster_files = sorted(ARMAGEDDON_ROSTERS.rglob("*.json"))
    assert roster_files, f"aucun roster ArmageddonAgent sous {ARMAGEDDON_ROSTERS}"
    for path in roster_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for entry in payload["composition"]:
            types.add(str(entry["unit_type"]))
            for model in entry.get("models", []):
                # Une figurine s'écrit soit `{"unit_type": ...}`, soit directement son type.
                types.add(str(model["unit_type"]) if isinstance(model, dict) else str(model))
    return sorted(types)


@pytest.fixture(scope="module")
def registry():
    from ai.unit_registry import UnitRegistry

    return UnitRegistry()


def test_armageddon_roster_flying_units_are_recognised_as_flying(registry):
    """Les unités FLY du roster d'ArmageddonAgent, chargées par `UnitRegistry` (le vrai chargeur,
    pas une fixture écrite à la main), DOIVENT être reconnues volantes par le moteur.

    Le chargeur rend la casse telle qu'écrite dans le `.ts` — ici `"FLY"`. Une comparaison stricte
    perdait le keyword en silence : l'agent s'entraînait avec des réacteurs dorsaux qui ne volaient
    pas. On ne code PAS la liste en dur : elle est dérivée du roster réel.
    """
    flying = []
    for unit_type in _armageddon_unit_types():
        data = registry.get_unit_data(unit_type)
        assert data is not None, f"{unit_type} introuvable dans UnitRegistry"
        keywords = data["UNIT_KEYWORDS"]
        raw_has_fly = any(
            str(kw["keywordId"]).strip().lower() == "fly" for kw in keywords
        )
        engine_has_fly = _unit_has_keyword({"id": unit_type, "UNIT_KEYWORDS": keywords}, "fly")
        assert engine_has_fly == raw_has_fly, (
            f"{unit_type}: la donnée porte fly={raw_has_fly} "
            f"(keywords={keywords}) mais le moteur lit {engine_has_fly} — "
            "la reconnaissance du keyword dépend de la casse"
        )
        if raw_has_fly:
            flying.append(unit_type)

    # Sonde : prouve que le test a réellement VU des unités volantes (un roster sans FLY
    # rendrait l'assertion ci-dessus vide de sens).
    assert len(flying) >= 5, (
        f"sonde : seulement {len(flying)} type(s) FLY trouvé(s) dans les rosters "
        f"d'ArmageddonAgent ({flying}) — attendu >= 5"
    )


@pytest.mark.parametrize("written_case", ["fly", "FLY", "Fly", " FLY "])
def test_fly_keyword_recognition_is_case_insensitive(written_case):
    """Le corpus de rosters est mixte ; la LECTURE normalise, comme partout ailleurs dans le
    moteur (`game_state.py`, `shared_utils.compute_hideable`, `attack_sequence`, le front)."""
    unit = {"id": "u", "UNIT_KEYWORDS": [{"keywordId": written_case}]}
    assert _unit_has_keyword(unit, "fly") is True


def test_absent_fly_keyword_is_not_invented():
    """La normalisation ne doit pas rendre le prédicat permissif : sans keyword, pas de vol."""
    assert _unit_has_keyword({"id": "u", "UNIT_KEYWORDS": []}, "fly") is False
    assert (
        _unit_has_keyword({"id": "u", "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}]}, "fly")
        is False
    )
