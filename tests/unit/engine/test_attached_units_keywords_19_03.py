"""Règle 19.03 (Keywords in attached units) — l'unité attachée porte l'UNION des keywords.

PDF 19 : « an attached unit has the keywords of all its component units ». Vérifié BOUT-EN-BOUT
via le vrai chemin de chargement (`load_units_from_scenario` → `_fold_attached_characters` →
`_build_enhanced_unit`), pas sur la fonction d'union isolée.

Enjeu concret : [ANTI-X Y+] 24.03 teste les keywords de l'unité CIBLE. Sans l'union, une escouade
menée par un CHARACTER n'exposait que les keywords du bodyguard, et une arme [ANTI-CHARACTER]
(ou tout gate keyword : couvert 13.08, étages 13.06) ratait la cible.

Contre-épreuve : le test de non-régression vérifie qu'une escouade SANS character garde
exactement ses propres keywords (l'union n'invente rien).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _scenario(units: list) -> dict:
    return {
        "board_ref": "25x21",
        "primary_objectives": ["objectives_control"],
        "wall_ref": "walls-none.json",
        "units": units,
    }


def _load(scenario: dict):
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


_BODYGUARD = {"id": 101, "unit_type": "Intercessor", "player": 2, "col": 12, "row": 10}
_LEADER = {"id": 102, "unit_type": "CaptainPowerWeaponBolter", "player": 2,
           "attached_squad": 101, "col": 20, "row": 4}


def _keywords(engine, unit_id: str) -> set:
    unit = engine.game_state["unit_by_id"][unit_id]
    return {str(kw["keywordId"]).strip().lower() for kw in unit["UNIT_KEYWORDS"]}


def _registry_keywords(unit_type: str) -> set:
    from ai.unit_registry import UnitRegistry
    data = UnitRegistry().get_unit_data(unit_type)
    return {str(kw["keywordId"]).strip().lower() for kw in data["UNIT_KEYWORDS"]}


def test_attached_unit_has_union_of_keywords():
    """19.03 : l'escouade attachée porte SES keywords ET ceux du leader replié."""
    engine = _load(_scenario([dict(_BODYGUARD), dict(_LEADER)]))

    union = _keywords(engine, "101")
    bodyguard_kw = _registry_keywords("Intercessor")
    leader_kw = _registry_keywords("CaptainPowerWeaponBolter")

    assert bodyguard_kw <= union, "les keywords du bodyguard doivent être conservés"
    assert leader_kw <= union, "19.03 : les keywords du leader doivent être ajoutés"
    assert union == bodyguard_kw | leader_kw, "l'union ne doit rien inventer d'autre"
    # Discrimination : le leader apporte au moins un keyword absent du bodyguard, sinon ce test
    # passerait même sans union (garde-fou contre une fixture qui perdrait son pouvoir).
    assert leader_kw - bodyguard_kw, "fixture invalide : le leader n'apporte aucun keyword nouveau"


def test_unit_without_character_keeps_its_own_keywords():
    """Non-régression : sans attachement, les keywords sont exactement ceux de l'unité."""
    engine = _load(_scenario([dict(_BODYGUARD)]))

    assert _keywords(engine, "101") == _registry_keywords("Intercessor")
