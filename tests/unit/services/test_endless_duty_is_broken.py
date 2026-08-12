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
from services.endless_duty_runtime import ED_SCENARIO_DEFAULT, _build_unit_from_registry

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


def test_obstacles_1_to_4_ed_scenario_uses_a_removed_format() -> None:
    """Obstacles 1 à 4 — DONNÉE/CONCEPTION : le scénario ED est resté au format d'avant V11.

    1. il vit dans `config/` et ne déclare pas `board_ref` → `_resolve_board_dir` refuse ;
    2. son `wall_ref` ne vit que sous `config/board/44x60x10/`, plateau non jouable ;
    3. il porte la clé `objectives`, retirée du format (les objectifs viennent des zones de
       terrain marquées `"objective": true` via `terrain_ref`) ;
    4. il ne déclare aucune unité du joueur 2 → `engine.reset()` construit une observation qui
       exige `value_at_start[2]`.
    """
    scenario = json.loads((_PROJECT_ROOT / ED_SCENARIO_DEFAULT).read_text(encoding="utf-8"))

    assert "board_ref" not in scenario, f"Obstacle 1 levé (board_ref ajouté) : mettre à jour {_DOC}."
    assert scenario["wall_ref"] == "walls-11.json", (
        f"Le wall_ref du scénario ED a changé ({scenario['wall_ref']!r}) : obstacle 2 traité ? "
        f"Mettre à jour {_DOC}."
    )
    assert not (_PROJECT_ROOT / "config" / "board" / "44x60x5" / "walls" / "walls-11.json").exists(), (
        f"walls-11.json existe désormais pour le plateau actif : obstacle 2 levé, mettre à jour {_DOC}."
    )
    assert "objectives" in scenario, f"Obstacle 3 traité (clé `objectives` retirée) : mettre à jour {_DOC}."
    assert "terrain_ref" not in scenario, f"Obstacle 3 traité (terrain_ref ajouté) : mettre à jour {_DOC}."
    assert not [u for u in scenario["units"] if int(u["player"]) == 2], (
        f"Le scénario ED déclare désormais des unités du joueur 2 : obstacle 4 levé, mettre à jour {_DOC}."
    )


def test_obstacle_7_ed_leader_has_no_combat_value() -> None:
    """Obstacle 7 — CONCEPTION : `VALUE` porte deux sens incompatibles.

    Le moteur lit `VALUE` comme la valeur de COMBAT (référence d'usure `value_at_start`, V11 §9.8).
    Endless Duty l'écrase avec le COÛT en points de réquisition (`_apply_slot_picks_to_unit`), et
    le catalogue donne `base = 0` au Sergent de départ, tous ses picks initiaux à 0. Résultat :
    `value_at_start[1] = 0` et `build_squad_observation` refuse — le tour IA est impossible.

    C'est un arbitrage produit, pas une réparation : cf. le document de chantier.
    """
    catalog = json.loads(
        (_PROJECT_ROOT / "config" / "endless_duty" / "leader_evolution.json").read_text(encoding="utf-8")
    )["catalog"]["Sergeant"]
    starter_costs = [
        row["cost"]
        for row in catalog["rows"]
        if (row["slot"], row["pick"]) in {
            ("melee", "close_combat_weapon"), ("ranged", "bolt_rifle"), ("secondary", "bolt_pistol"),
        }
    ]
    assert catalog["base"] == 0 and starter_costs == [0, 0, 0], (
        f"Le coût de départ du Sergent n'est plus nul (base={catalog['base']}, picks={starter_costs}) : "
        f"obstacle 7 traité ? Mettre à jour {_DOC}."
    )
