"""Règle 19.01 (Forming attached units) — légalité d'attachement + unicité.

`_fold_attached_characters` (engine/game_state.py) refuse désormais un attachement illégal
AVANT d'injecter le character dans son bodyguard. Deux verrous, tous bout-en-bout via le vrai
chemin de chargement de scénario (`load_units_from_scenario` → fold) :

- **Éligibilité 19.01/24.22/24.34** : la cible `attached_squad` doit être un bodyguard éligible —
  un de ses keywords de nom d'unité ∈ `CAN_LEAD` du character (insensible à la casse). Un Captain
  Terminator (`CAN_LEAD = ["terminator squad"]`) posé sur une Intercessor Squad (`INTERCESSOR
  SQUAD`) est illégal.
- **Unicité 19.01** : au plus un leader ET un support par bodyguard. Deux leaders sur la même
  escouade → erreur explicite.

Contre-épreuve (neutraliser la validation dans `_fold_attached_characters` fait rougir les deux
tests d'erreur) : vérifiée manuellement, cf. §9.2.1.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _scenario(units: list) -> dict:
    return {
        "board_ref": "44x60x5",
        "primary_objectives": ["objectives_control"],
        "wall_ref": "walls-none.json",
        # Faction d'Armée DÉCLARÉE des deux camps, comme tout scénario de production : 08.04 la
        # demande à chaque phase de commandement et refuse de la déduire des unités présentes.
        # ADEPTUS ASTARTES est la faction RÉELLE des datasheets de ce fichier (Intercessor,
        # Captain*, vérifiée au registre) — la garde anti-coquille d'`army_faction` rejetterait
        # toute autre valeur.
        "army_faction": {"1": "ADEPTUS ASTARTES", "2": "ADEPTUS ASTARTES"},
        # Corollaire OBLIGATOIRE d'une armée ADEPTUS ASTARTES : la clause du +1 Wound d'Oath
        # en dépend, et l'observation la lit à chaque construction.
        "uses_codex_detachment": {"1": True, "2": True},
        "units": units,
    }


def _load(scenario: dict):
    """Charge le scénario par le vrai chemin moteur (le fold s'exécute pendant reset)."""
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "attached.json"
        path.write_text(json.dumps(scenario))
        eng = W40KEngine(
            rewards_config="ArmageddonAgent", training_config_name="x1_debug",
            controlled_agent="ArmageddonAgent", scenario_file=str(path),
            unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
        )
        eng.reset(seed=0)
        return eng


# Bodyguard éligible : Intercessor a le keyword "INTERCESSOR SQUAD".
_BODYGUARD = {"id": 101, "unit_type": "Intercessor", "player": 2, "col": 12, "row": 10}


def test_legal_attachment_loads():
    """Leader dont CAN_LEAD couvre 'intercessor squad' → chargement OK, character folded."""
    scen = _scenario([
        dict(_BODYGUARD),
        # CaptainPowerWeaponBolter : CAN_LEAD = ["assault intercessor squad", "intercessor squad"].
        {"id": 102, "unit_type": "CaptainPowerWeaponBolter", "player": 2,
         "attached_squad": 101, "col": 20, "row": 4},
    ])
    eng = _load(scen)
    # Le character n'existe plus comme unité séparée : il est une figurine du bodyguard.
    assert "102" not in eng.game_state["units_cache"], "le character aurait dû être folded dans 101"
    assert "101" in eng.game_state["units_cache"], "le bodyguard doit exister"


def test_illegal_attachment_rejected():
    """Captain Terminator (CAN_LEAD 'terminator squad') sur Intercessor Squad → erreur 19.01."""
    scen = _scenario([
        dict(_BODYGUARD),
        {"id": 102, "unit_type": "CaptainTerminatorRelicWeaponBolter", "player": 2,
         "attached_squad": 101, "col": 20, "row": 4},
    ])
    with pytest.raises(ValueError, match="illegal attachment"):
        _load(scen)


def test_two_leaders_on_same_bodyguard_rejected():
    """19.01 : au plus un leader par bodyguard → deux leaders sur 101 → erreur explicite."""
    scen = _scenario([
        dict(_BODYGUARD),
        {"id": 102, "unit_type": "CaptainPowerWeaponBolter", "player": 2,
         "attached_squad": 101, "col": 20, "row": 4},
        {"id": 103, "unit_type": "CaptainRelicShield", "player": 2,
         "attached_squad": 101, "col": 22, "row": 6},
    ])
    with pytest.raises(ValueError, match="already has a leader"):
        _load(scen)
