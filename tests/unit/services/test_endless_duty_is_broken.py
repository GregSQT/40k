"""Signet : le mode « Endless Duty » est exposé par l'API mais ne démarre pas.

Ce fichier n'est PAS une garantie de bon fonctionnement — c'est l'inverse. Il **affirme l'état
cassé constaté** le 2026-07-29, avec les valeurs exactes mesurées. Il est donc VERT aujourd'hui,
et il devient ROUGE le jour où quelqu'un répare (ou aggrave) un des trous : c'est le signal.

Forme retenue (« affirmer l'état cassé ») plutôt qu'un `xfail(strict=True)` : la suite complète
de l'utilisateur doit rester exploitable, donc pas de rouge durable ; et le message d'un
`XPASS(strict)` ne dit pas CE QUI a changé, alors qu'une assertion nommée le dit.

État complet, obstacles ordonnés et estimation d'effort :
    Documentation/Implémentation/A_faire/Endless_duty_etat_mesure.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ai.unit_registry import UnitRegistry
from services.endless_duty_runtime import ED_SCENARIO_DEFAULT, _apply_slot_picks_to_unit, _build_unit_from_registry

pytestmark = pytest.mark.anomaly

_DOC = "Documentation/Implémentation/A_faire/Endless_duty_etat_mesure.md"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Les 18 fiches de `frontend/src/roster/spaceMarine/units/endlessDuty/` (index.ts exclu).
_ED_UNIT_TYPES: List[str] = [
    "LeaderCaptain", "LeaderCaptainGravis", "LeaderCaptainTerminator", "LeaderLieutenant",
    "LeaderSergeant", "MeleeAggressor", "MeleeBladeguard", "MeleeIntercessor", "MeleeTerminator",
    "RangeEradicator", "RangeHellblaster", "RangeInceptor", "RangeInfernus", "RangeIntercessor",
    "RangeIntercessorGravis", "RangeSternguard", "RangeSuppressor", "RangeTerminator",
]


@pytest.fixture(scope="module")
def registry() -> UnitRegistry:
    return UnitRegistry()


def test_obstacle_5_ed_datasheets_miss_keys_the_engine_requires(registry: UnitRegistry) -> None:
    """Obstacle 5 — DONNÉE : les 18 fiches endlessDuty n'ont pas d'ILLUSTRATION_RATIO.

    `_build_unit_from_registry` l'exige : l'initialisation du mode meurt sur la première unité
    du slot « leader ».

    ⚠️ `FACTION_KEYWORDS` faisait partie de l'obstacle jusqu'au chantier 03 (2026-08-05). Il
    n'en fait plus partie, et ce n'est PAS la donnée qui a changé : le parseur pose désormais la
    clé sur TOUTE fiche, à `[]` quand la datasheet ne la déclare pas — même convention que
    `UNIT_KEYWORDS`. La clé existe donc, vide. La conséquence métier reste entière et elle est
    vérifiée ci-dessous : une fiche sans mot-clé de faction n'appartient à aucune faction, donc
    aucune capacité de faction (Waaagh!, Oath of Moment) ne la vise.
    """
    still_missing: Dict[str, List[str]] = {}
    for unit_type in _ED_UNIT_TYPES:
        keys = set(registry.get_unit_data(unit_type))
        absent = sorted({"ILLUSTRATION_RATIO"} - keys)
        if absent:
            still_missing[unit_type] = absent

    assert len(still_missing) == 18, (
        f"Les fiches endlessDuty ne sont plus toutes incomplètes ({len(still_missing)}/18 le "
        f"sont encore). Si la donnée a été complétée, l'obstacle 5 est levé : mettre à jour "
        f"{_DOC} et ce test."
    )
    assert all(
        absent == ["ILLUSTRATION_RATIO"] for absent in still_missing.values()
    ), f"La nature des clés manquantes a changé : {still_missing!r}. Mettre à jour {_DOC}."
    # La clé de faction est là, mais VIDE : ces fiches restent hors de toute capacité de faction.
    # Sans cette seconde moitié, compléter la donnée un jour passerait inaperçu ici.
    assert all(
        registry.get_unit_data(unit_type)["FACTION_KEYWORDS"] == []
        for unit_type in _ED_UNIT_TYPES
    ), f"Une fiche endlessDuty declare desormais une faction : mettre a jour {_DOC} et ce test."


def test_obstacle_5b_melee_terminator_also_misses_its_ranged_loadout(registry: UnitRegistry) -> None:
    """Obstacle 5 (variante) — MeleeTerminator n'a en plus ni RNG_WEAPON_CODES ni selectedRngWeaponIndex."""
    keys = set(registry.get_unit_data("MeleeTerminator"))
    assert not {"RNG_WEAPON_CODES", "selectedRngWeaponIndex"} & keys, (
        f"MeleeTerminator a désormais un armement à distance : obstacle 5 partiellement levé, "
        f"mettre à jour {_DOC}."
    )


def test_obstacle_6_ed_unit_builder_does_not_emit_what_the_engine_reads(registry: UnitRegistry) -> None:
    """Obstacle 6 — CODE : `_build_unit_from_registry` est un doublon dérivé de `_build_enhanced_unit`.

    Il n'émet ni socle (`BASE_SHAPE`/`BASE_SIZE`), ni `MODEL_HEIGHT`, ni `orientation`, ni
    `level`, et ne convertit ni `MOVE` ni les portées d'armes en subhex. `build_units_cache`
    lit `unit["BASE_SHAPE"]` sans valeur par défaut : la construction meurt là.

    Mesuré sur `Termagant` (fiche tyranide, qui a bien ILLUSTRATION_RATIO) : c'est le chemin qui
    survit à l'obstacle 5 et meurt ici. Datasheet : MOVE 6", portée 18" — le plateau actif est en
    subhex ×5, donc l'unité produite est 5× trop lente et 5× trop courte de portée.
    """

    class _EngineStub:
        unit_registry = registry
        game_state: Dict[str, Any] = {"inches_to_subhex": 5}

    built = _build_unit_from_registry(_EngineStub(), "Termagant", player=2, unit_id=1, col=10, row=10)

    required_by_the_engine = ("BASE_SHAPE", "BASE_SIZE", "MODEL_HEIGHT", "orientation", "level")
    assert not set(required_by_the_engine) & set(built), (
        f"`_build_unit_from_registry` émet désormais {sorted(set(required_by_the_engine) & set(built))} : "
        f"l'obstacle 6 est (partiellement) levé, mettre à jour {_DOC}."
    )
    assert built["MOVE"] == 6, (
        f"MOVE = {built['MOVE']!r} : la conversion subhex a peut-être été ajoutée (attendu 30 pour "
        f"inches_to_subhex=5). Obstacle 6 levé ? Mettre à jour {_DOC}."
    )
    assert built.get("RNG_WEAPONS"), (
        f"RNG_WEAPONS absent ou vide dans la sortie de _build_unit_from_registry : "
        f"la structure a changé — mettre à jour {_DOC}."
    )
    assert built["RNG_WEAPONS"][0]["RNG"] == 18, (
        f"Portée = {built['RNG_WEAPONS'][0]['RNG']!r} : la conversion subhex des armes a peut-être "
        f"été ajoutée (attendu 90 pour inches_to_subhex=5). Mettre à jour {_DOC}."
    )


def test_obstacle_2_ed_wall_ref_targets_wrong_board() -> None:
    """Obstacle 2 — DONNÉE : le wall_ref ne vit que sous `config/board/44x60x10/`, plateau non jouable."""
    scenario = json.loads((_PROJECT_ROOT / ED_SCENARIO_DEFAULT).read_text(encoding="utf-8"))

    assert scenario["wall_ref"] == "walls-11.json", (
        f"Le wall_ref du scénario ED a changé ({scenario['wall_ref']!r}) : obstacle 2 traité ? "
        f"Mettre à jour {_DOC}."
    )
    assert not (_PROJECT_ROOT / "config" / "board" / "44x60x5" / "walls" / "walls-11.json").exists(), (
        f"walls-11.json existe désormais pour le plateau actif : obstacle 2 levé, mettre à jour {_DOC}."
    )


def test_obstacle_4_ed_scenario_declares_no_player_2_units() -> None:
    """Obstacle 4 — DONNÉE : le scénario ED ne déclare aucune unité du joueur 2.

    `engine.reset()` construit une observation qui exige `value_at_start[2]`.
    """
    scenario = json.loads((_PROJECT_ROOT / ED_SCENARIO_DEFAULT).read_text(encoding="utf-8"))

    assert not [u for u in scenario["units"] if int(u["player"]) == 2], (
        f"Le scénario ED déclare désormais des unités du joueur 2 : obstacle 4 levé, mettre à jour {_DOC}."
    )


def test_obstacles_1_and_3_ed_scenario_now_uses_v11_format() -> None:
    """Obstacles 1 et 3 — SOLDÉS : le scénario ED déclare board_ref et terrain_ref.

    1. board_ref "44x60x5" ajouté → `_resolve_board_dir` résout le plateau actif ;
    3. terrain_ref "terrain-endless-duty.json" ajouté, clé `objectives` supprimée → objectif
       fixe unique issu de la zone `"objective": true` du fichier terrain.
    """
    scenario = json.loads((_PROJECT_ROOT / ED_SCENARIO_DEFAULT).read_text(encoding="utf-8"))

    assert scenario.get("board_ref") == "44x60x5", (
        f"Obstacle 1 a régressé : board_ref absent ou incorrect ({scenario.get('board_ref')!r})."
    )
    assert "terrain_ref" in scenario, "Obstacle 3 a régressé : terrain_ref absent du scénario ED."
    assert "objectives" not in scenario, (
        "Obstacle 3 a régressé : clé `objectives` toujours présente dans le scénario ED."
    )
    terrain_path = (
        _PROJECT_ROOT / "config" / "board" / "44x60x5" / "terrain" / scenario["terrain_ref"]
    )
    assert terrain_path.exists(), (
        f"terrain_ref pointe vers un fichier absent : {terrain_path}"
    )
    terrain = json.loads(terrain_path.read_text(encoding="utf-8"))
    objective_zones = [area for area in terrain.get("terrain", []) if area.get("objective")]
    assert len(objective_zones) == 1, (
        f"Le terrain ED doit contenir exactement 1 zone objective, trouvé {len(objective_zones)}."
    )


def test_obstacle_7_solved_value_and_requisition_cost_are_separate() -> None:
    """Obstacle 7 — RÉSOLU : VALUE (combat) et REQUISITION_COST (réquisition) sont distincts.

    Avant le fix, `_apply_slot_picks_to_unit` écrasait VALUE avec le coût de réquisition (0 pour
    le Sergent de départ), rendant value_at_start[1] = 0 et bloquant le tour IA.

    Après le fix : VALUE reste la valeur de combat (> 0), REQUISITION_COST reçoit le coût calculé.
    """
    starter_picks = {"melee": "close_combat_weapon", "ranged": "bolt_rifle", "secondary": "bolt_pistol"}
    unit: Dict[str, Any] = {
        "VALUE": 18,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "selectedRngWeaponIndex": None,
        "selectedCcWeaponIndex": None,
        "SHOOT_LEFT": 0,
        "ATTACK_LEFT": 0,
    }
    _apply_slot_picks_to_unit(unit, "leader", "Sergeant", starter_picks)
    assert unit["VALUE"] > 0, (
        f"VALUE écrasé par le coût de réquisition (obtenu {unit['VALUE']}) : "
        f"_apply_slot_picks_to_unit écrit à nouveau dans VALUE au lieu de REQUISITION_COST."
    )
    assert unit["REQUISITION_COST"] == 0, (
        f"REQUISITION_COST inattendu pour le loadout de départ du Sergent (obtenu {unit['REQUISITION_COST']}) : "
        f"le coût calculé devrait être 0 (base=0, picks à 0)."
    )
