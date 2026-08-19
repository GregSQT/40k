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


def test_obstacle_5_ed_datasheets_have_illustration_ratio(registry: UnitRegistry) -> None:
    """Obstacle 5 — RÉSOLU : les 18 fiches endlessDuty ont désormais ILLUSTRATION_RATIO.

    `_build_unit_from_registry` l'exige : ce test vérifie que la clé est présente sur toutes les
    fiches, et que sa valeur est un nombre positif (délégué à la classe parente de chaque fiche).

    ⚠️ `FACTION_KEYWORDS` est présente sur toutes les fiches (parseur chantier 03, 2026-08-05),
    mais vide pour les fiches ED : une fiche sans mot-clé de faction n'appartient à aucune faction,
    donc aucune capacité de faction (Waaagh!, Oath of Moment) ne la vise.
    """
    missing: Dict[str, List[str]] = {}
    for unit_type in _ED_UNIT_TYPES:
        keys = set(registry.get_unit_data(unit_type))
        absent = sorted({"ILLUSTRATION_RATIO"} - keys)
        if absent:
            missing[unit_type] = absent

    assert len(missing) == 0, (
        f"{len(missing)} fiche(s) endlessDuty manquent encore ILLUSTRATION_RATIO : {sorted(missing)}"
    )
    # La valeur peut être un nombre direct ou une référence statique ('ClassName.FIELD') résolue
    # à l'exécution par _resolve_numeric_unit_field — les deux formes sont valides ici.
    for unit_type in _ED_UNIT_TYPES:
        ratio = registry.get_unit_data(unit_type)["ILLUSTRATION_RATIO"]
        assert ratio is not None, f"{unit_type}.ILLUSTRATION_RATIO est None"
    # La clé de faction est là, mais VIDE : ces fiches restent hors de toute capacité de faction.
    assert all(
        registry.get_unit_data(unit_type)["FACTION_KEYWORDS"] == []
        for unit_type in _ED_UNIT_TYPES
    ), "Une fiche endlessDuty declare desormais une faction — verifier si intentionnel."


def test_obstacle_5b_melee_terminator_has_empty_ranged_weapons(registry: UnitRegistry) -> None:
    """Obstacle 5 (variante) — MeleeTerminator est pur mêlée : RNG_WEAPONS présent mais vide.

    Le runtime lit `RNG_WEAPONS` (pas `RNG_WEAPON_CODES`) et gère correctement la liste vide
    (`selected_rng_weapon_index = None`). Ce test documente le choix de conception :
    MeleeTerminator n'a pas d'armement à distance, ce qui est intentionnel pour AssaultTerminator.
    """
    unit_data = registry.get_unit_data("MeleeTerminator")
    assert "RNG_WEAPONS" in unit_data, "RNG_WEAPONS absent du registre MeleeTerminator"
    assert unit_data["RNG_WEAPONS"] == [], (
        f"MeleeTerminator a désormais un armement à distance ({unit_data['RNG_WEAPONS']!r}) : "
        f"vérifier si intentionnel et mettre à jour {_DOC}."
    )


def test_obstacle_6_ed_unit_builder_emits_engine_required_fields(registry: UnitRegistry) -> None:
    """Obstacle 6 — RÉSOLU : `_build_unit_from_registry` émet tous les champs requis par le moteur.

    Vérifié sur `Termagant` (fiche tyranide avec ILLUSTRATION_RATIO) : MOVE 6" converti en 30
    subhex (×5), portée 18" convertie en 90 subhex, et présence de BASE_SHAPE/BASE_SIZE/
    MODEL_HEIGHT/orientation/level nécessaires à `build_units_cache`.
    """

    class _EngineStub:
        unit_registry = registry
        game_state: Dict[str, Any] = {"inches_to_subhex": 5}

    built = _build_unit_from_registry(_EngineStub(), "Termagant", player=2, unit_id=1, col=10, row=10)

    required_by_the_engine = ("BASE_SHAPE", "BASE_SIZE", "MODEL_HEIGHT", "orientation", "level")
    missing_keys = sorted(set(required_by_the_engine) - set(built))
    assert not missing_keys, (
        f"`_build_unit_from_registry` n'émet toujours pas : {missing_keys}"
    )
    assert built["MOVE"] == 30, (
        f"MOVE = {built['MOVE']!r} : attendu 30 subhex (6\" × inches_to_subhex=5)"
    )
    assert built.get("RNG_WEAPONS"), (
        f"RNG_WEAPONS absent ou vide dans la sortie de _build_unit_from_registry"
    )
    assert built["RNG_WEAPONS"][0]["RNG"] == 90, (
        f"Portée = {built['RNG_WEAPONS'][0]['RNG']!r} : attendu 90 subhex (18\" × inches_to_subhex=5)"
    )
    assert built["orientation"] == 0
    assert built["level"] == 0


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


def _make_engine_stub(registry: UnitRegistry, inches_to_subhex: int = 5) -> Any:
    class _EngineStub:
        unit_registry = registry
        game_state: Dict[str, Any] = {"inches_to_subhex": inches_to_subhex}
    return _EngineStub()


def test_obstacle_7_solved_value_and_requisition_cost_are_separate(registry: UnitRegistry) -> None:
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
    _apply_slot_picks_to_unit(unit, "leader", "Sergeant", starter_picks, _make_engine_stub(registry))
    assert unit["VALUE"] > 0, (
        f"VALUE écrasé par le coût de réquisition (obtenu {unit['VALUE']}) : "
        f"_apply_slot_picks_to_unit écrit à nouveau dans VALUE au lieu de REQUISITION_COST."
    )
    assert unit["REQUISITION_COST"] == 0, (
        f"REQUISITION_COST inattendu pour le loadout de départ du Sergent (obtenu {unit['REQUISITION_COST']}) : "
        f"le coût calculé devrait être 0 (base=0, picks à 0)."
    )


def test_apply_slot_picks_scales_rng_weapons_to_subhex(registry: UnitRegistry) -> None:
    """RNG_WEAPONS issus de `_apply_slot_picks_to_unit` doivent être en subhex, comme `_build_unit_from_registry`.

    Avant le fix, get_weapons() retournait des portées en pouces bruts (ex. bolt_rifle = 24"),
    écrasant le scaling fait par _build_unit_from_registry (× inches_to_subhex).
    La phase de tir comparait row["distance"] en subhex avec weapon_range en pouces → tir inopérant.
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
    _apply_slot_picks_to_unit(unit, "leader", "Sergeant", starter_picks, _make_engine_stub(registry, inches_to_subhex=5))
    rng_weapons = unit["RNG_WEAPONS"]
    assert rng_weapons, "Aucune RNG_WEAPONS après _apply_slot_picks_to_unit pour Sergeant/bolt_rifle"
    bolt_rifle_rng = rng_weapons[0]["RNG"]
    assert bolt_rifle_rng >= 5, (
        f"RNG_WEAPONS[0].RNG = {bolt_rifle_rng!r} : valeur inférieure à 5 subhex — "
        f"le scaling inches_to_subhex n'est pas appliqué (portée brute en pouces)."
    )
    # bolt_rifle = 24" × 5 = 120 subhex ; on vérifie le multiple exact
    assert bolt_rifle_rng % 5 == 0, (
        f"RNG_WEAPONS[0].RNG = {bolt_rifle_rng!r} : pas un multiple de inches_to_subhex=5 — "
        f"scaling non appliqué ou arme incorrecte."
    )
