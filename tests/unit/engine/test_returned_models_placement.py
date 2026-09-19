"""Placement des figurines RENDUES (Grot Orderly / `return_destroyed_models`).

Défaut corrigé : toutes les figurines rendues étaient posées sur la case EXACTE du template
(`command_handlers._apply_return_destroyed_models`), donc superposées entre elles et à une
figurine vivante. Le move d'escouade étant rigide, la superposition d'origine se reportait sur
chaque destination et `execute_squad_move` refusait ensuite TOUS les mouvements de l'escouade :

    ValueError: execute_squad_move a échoué : squad=101 type=advance dest=(10,34) …
    Contrainte violée : collision intra-plan : deux figurines en (10,34) niveau 0 (dont 101#r0)

Règle appliquée — PDF `25 Rules appendix`, entrée REVIVED : « Models returned to a unit on the
battlefield must be set up […] in coherency with models in that unit that started that phase on
the battlefield. […] They can be engaged with one or more enemy units, but only if those enemy
units are already engaged with the unit those models are being returned to. »

Le placement est un CHOIX de joueur : l'agent choisit une intention (`toward_enemy`,
`toward_objective`, `away_from_enemy`) dès que deux intentions aboutissent à des positions
différentes ; sinon il n'y a rien à choisir.

⚠️ Le test porte sur les EMPREINTES, pas sur les ancres : à x5 un socle couvre plusieurs
subhexes, et le validateur de plan de move ne compare, lui, que les ancres — deux socles posés
sur des ancres distinctes mais aux empreintes recouvrantes passeraient donc inaperçus.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from engine.ability_calls import apply_ability_call, pending_ability_call_prompts
from engine.phase_handlers.command_handlers import (
    _GROT_ORDERLY_SKIPPED, _apply_return_destroyed_models, _bot_grot_orderly_policy,
    apply_returned_models_placement, apply_returned_models_placement_decision,
    apply_returned_models_profile_decision,
)
from engine.phase_handlers.deployment_handlers import (
    RETURNED_PLACEMENT_INTENTS, _model_footprint, plan_returned_models_placement,
    returned_models_legal_cells,
)
from engine.phase_handlers.shared_utils import (
    _build_enemy_adjacent_hexes_all_players, _recompute_squad_occupied_hexes,
)


# ---------------------------------------------------------------------------
# État minimal : une escouade ORK avec la règle, des figurines détruites, un ennemi
# ---------------------------------------------------------------------------

_SQUAD = "pain"
_ENEMY = "foe"


def _model(
    squad_id: str, col: int, row: int, base_size: int = 1,
    unit_type: str = "Boyz", value: int = 10, role: Optional[str] = None,
) -> Dict[str, Any]:
    """`role` : celui que `build_models_cache` écrit — None pour une figurine de base (bodyguard),
    "leader"/"support" pour un personnage attaché (`_is_character_role`)."""
    return {
        "squad_id": squad_id,
        "unitType": unit_type,
        "col": col,
        "row": row,
        "level": 0,
        "orientation": 0,
        "T": 5,
        "role": role,
        "HP_CUR": 3,
        "HP_MAX": 3,
        "INVUL_SAVE": 7,
        "ARMOR_SAVE": 5,
        "OC": 1,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "player": 1 if squad_id == _SQUAD else 2,
        "VALUE": value,
        "BASE_SHAPE": "round",
        "BASE_SIZE": base_size,
        "MODEL_HEIGHT": 2.0,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "UNIT_RULES": [],
    }


def _state(
    *, n_alive: int = 3, n_destroyed: int = 2, base_size: int = 1,
    enemy_at: Optional[Tuple[int, int]] = (18, 5),
    objectives: Optional[List[Dict[str, Any]]] = None,
    destroyed_profiles: Optional[List[Tuple[Any, ...]]] = None,
) -> Dict[str, Any]:
    """Escouade alignée en colonne autour de (6,5) — positions DISTINCTES, état jouable.

    `destroyed_profiles` : `(unitType, VALUE)` ou `(unitType, VALUE, role)` par figurine archivée."""
    units = [
        {
            # `unitType` et `displayName` : ce que porte toute unité de production, et ce que la
            # ligne `RETURNED` du journal exige (datasheet de repli, nom de la capacité).
            "id": _SQUAD, "player": 1, "col": 6, "row": 5, "unitType": "Boyz",
            "UNIT_KEYWORDS": ["INFANTRY"], "FACTION_KEYWORDS": ["TYRANIDS"],
            "UNIT_RULES": [{"ruleId": "return_destroyed_models", "displayName": "Grot Orderly"}],
        }
    ]
    models_cache: Dict[str, Any] = {}
    squad_models: Dict[str, List[str]] = {_SQUAD: []}
    # Espacement dérivé du socle : à base_size > 1 l'empreinte couvre les voisins, donc des
    # figurines posées sur des lignes adjacentes se recouvriraient DÈS le fixture.
    spacing = 1 if int(base_size) <= 1 else 2 * int(base_size)
    for i in range(n_alive):
        mid = f"{_SQUAD}#{i}"
        models_cache[mid] = _model(_SQUAD, 6, 4 + i * spacing, base_size)
        squad_models[_SQUAD].append(mid)
    units_cache: Dict[str, Any] = {
        _SQUAD: {
            "player": 1, "col": 6, "row": 5, "HP_CUR": 3 * n_alive, "OC_TOTAL": n_alive,
            "orientation": 0, "BASE_SHAPE": "round", "BASE_SIZE": base_size,
            "deployed_on_turn": 1, "MODEL_HEIGHT": 1.0,
        }
    }
    if enemy_at is not None:
        units.append({
            "id": _ENEMY, "player": 2, "col": enemy_at[0], "row": enemy_at[1],
            "UNIT_KEYWORDS": ["INFANTRY"], "FACTION_KEYWORDS": ["TYRANIDS"], "UNIT_RULES": [],
        })
        emid = f"{_ENEMY}#0"
        models_cache[emid] = _model(_ENEMY, enemy_at[0], enemy_at[1], base_size)
        squad_models[_ENEMY] = [emid]
        units_cache[_ENEMY] = {
            "player": 2, "col": enemy_at[0], "row": enemy_at[1], "HP_CUR": 3, "OC_TOTAL": 1,
            "orientation": 0, "BASE_SHAPE": "round", "BASE_SIZE": base_size,
            "deployed_on_turn": 1, "MODEL_HEIGHT": 1.0,
        }
    # Archive des figurines détruites : c'est ELLE que la restitution rend (REVIVED), plus un
    # clone d'une survivante. `destroyed_profiles` permet aux tests de composer une escouade
    # hétérogène (Boyz + personnage), le cas qui faisait ressusciter des personnages.
    profiles = destroyed_profiles or [("Boyz", 10)] * n_destroyed
    if len(profiles) != n_destroyed:
        raise AssertionError(
            f"fixture incoherente : {len(profiles)} profils detruits pour n_destroyed={n_destroyed}"
        )
    destroyed_models = {
        _SQUAD: [
            _model(_SQUAD, -1, -1, base_size, unit_type=str(prof[0]), value=int(prof[1]),
                   role=(str(prof[2]) if len(prof) > 2 else None))
            for prof in profiles
        ]
    }
    game_state: Dict[str, Any] = {
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "destroyed_models": destroyed_models,
        "units_cache": units_cache,
        "models_cache": models_cache,
        "squad_models": squad_models,
        "squad_cache": {
            _SQUAD: {
                "model_count": n_alive,
                "model_count_at_start": n_alive + n_destroyed,
                "is_coherent": True,
                "oc_total": n_alive,
                "centroid_col": 6,
                "centroid_row": 5,
            }
        },
        "current_player": 1,
        "turn": 1,
        "phase": "command",
        "action_logs": [],
        "action_log_seq": 0,
        "board_cols": 30,
        "board_rows": 30,
        # Résolution portée par l'ÉTAT, comme en production (`w40k_core` la pose au même rang que
        # `board_cols`/`board_rows`). Sans elle, `geometry_is_hex` retombe sur le config-loader
        # global : la géométrie du test devenait celle du plateau ambiant, donc dépendante de
        # l'ordre d'exécution — à x1 (hex), `explain_move_plan_rejection` exigeait un cache
        # d'adjacence que le fixture ne posait pas, et le rouge n'apparaissait que sous `-n 16`.
        "inches_to_subhex": 1,
        "wall_hexes": set(),
        "terrain_areas": [],
        "objectives": objectives or [],
        "waaagh_active": {1: False, 2: False},
        "waaagh_called": {1: False, 2: False},
        "oath_target": {1: None, 2: None},
        "pending_oath_selection": None,
        "suppressed_squads": {},
        "finest_hour_used": set(),
        "pending_agent_decision": None,
        "_restored_model_counter": 0,
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
                "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
                "bonus_malus_cap": 0,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
            "controlled_player": 1,
            "army_faction": {"1": "TYRANIDS", "2": "TYRANIDS"},
            "inches_to_subhex": 1,
        },
    }
    # Empreintes d'escouade, par la MÊME primitive que la construction du cache moteur : c'est
    # `occupied_hexes` que dilate `build_enemy_adjacent_hexes` juste en dessous.
    for squad_id in units_cache:
        _recompute_squad_occupied_hexes(game_state, squad_id)
    # Ce que fait `command_phase_start` avant toute étape de la phase (08.xx) : les tests
    # appellent les étapes directement, donc ils doivent poser le même pré-requis. En géométrie
    # hex, `move_enemy_ez_forbidden_cells` lit ce cache et n'a aucune raison de le reconstruire.
    _build_enemy_adjacent_hexes_all_players(game_state)
    return game_state


def _accept_grot_orderly(gs: Dict[str, Any], player: int = 1) -> bool:
    """08.04 : pose l'appel Grot Orderly à l'escouade éligible, puis l'ACCEPTE — ce que fait le
    siège qui répond `CHOICE_0`. Rend True si une décision d'agent (profil, placement) est posée
    derrière, False si les figurines sont rendues (ou qu'aucune case n'existe)."""
    assert _apply_return_destroyed_models(gs, player) is True, "aucun appel Grot Orderly posé"
    prompt = gs["pending_rule_choice_queue"].pop(0)
    assert prompt["rule_id"] == "return_destroyed_models" and prompt["unit_id"] == _SQUAD
    return bool(apply_ability_call(gs, prompt, True).get("waiting_for_player"))


def _footprints(gs: Dict[str, Any], squad_id: str) -> List[set]:
    models_cache = gs["models_cache"]
    return [
        _model_footprint(gs, models_cache[mid], int(models_cache[mid]["col"]), int(models_cache[mid]["row"]))
        for mid in gs["squad_models"][squad_id]
    ]


# ---------------------------------------------------------------------------
# L'invariant cassé : plus aucune superposition
# ---------------------------------------------------------------------------


def test_returned_models_are_not_stacked_on_the_template() -> None:
    """ROUGE avant le fix : toutes les figurines rendues portaient la position du template."""
    gs = _state(n_alive=3, n_destroyed=3, enemy_at=None)
    before = list(gs["squad_models"][_SQUAD])

    _accept_grot_orderly(gs)

    after = gs["squad_models"][_SQUAD]
    assert len(after) > len(before), "au moins une figurine doit être rendue"
    anchors = [
        (int(gs["models_cache"][mid]["col"]), int(gs["models_cache"][mid]["row"]))
        for mid in after
    ]
    assert len(set(anchors)) == len(anchors), f"ancres dupliquées : {anchors}"


def test_returned_models_footprints_do_not_overlap() -> None:
    """À x5 l'ancre ne suffit pas : ce sont les EMPREINTES qui doivent être disjointes.

    Le validateur de plan de move ne compare que les ancres — un chevauchement d'empreintes
    ne serait donc JAMAIS signalé, il se propagerait en silence à chaque mouvement.
    """
    gs = _state(n_alive=3, n_destroyed=3, base_size=3, enemy_at=None)

    _accept_grot_orderly(gs)

    seen: set = set()
    for footprint in _footprints(gs, _SQUAD):
        overlap = footprint & seen
        assert not overlap, f"empreintes qui se recouvrent sur {sorted(overlap)[:5]}"
        seen |= footprint


def test_returned_models_keep_squad_coherency() -> None:
    """03.03 : « in coherency with models in that unit that started that phase »."""
    from engine.phase_handlers.shared_utils import _positions_in_coherency

    gs = _state(n_alive=3, n_destroyed=3, enemy_at=None)
    _accept_grot_orderly(gs)

    models = [gs["models_cache"][mid] for mid in gs["squad_models"][_SQUAD]]
    assert _positions_in_coherency(models, gs), "l'escouade rendue doit rester cohérente"


# ---------------------------------------------------------------------------
# Le choix de l'agent
# ---------------------------------------------------------------------------


def test_decision_is_posted_when_intents_differ() -> None:
    """Deux intentions aboutissant à des positions différentes → l'agent tranche."""
    from engine.agent_decision import read_pending_agent_decision

    gs = _state(n_alive=3, n_destroyed=3)
    posted = _accept_grot_orderly(gs)

    assert posted is True, "une décision doit être posée quand les intentions divergent"
    decision = read_pending_agent_decision(gs)
    assert decision is not None
    assert str(decision["type"]) == "returned_models_placement"
    offered = [str(o["payload"]["intent"]) for o in decision["options"]]
    assert set(offered) <= set(RETURNED_PLACEMENT_INTENTS)
    assert len(offered) >= 2
    assert gs["_pending_returned_placement"]["squad_id"] == _SQUAD
    # Rien n'est posé tant que l'agent n'a pas répondu.
    assert len(gs["squad_models"][_SQUAD]) == 3


def test_no_decision_when_all_intents_agree() -> None:
    """Sans ennemi ni objectif, les trois intentions coïncident : aucun choix à poser."""
    from engine.agent_decision import read_pending_agent_decision

    gs = _state(n_alive=3, n_destroyed=3, enemy_at=None)
    posted = _accept_grot_orderly(gs)

    assert posted is False
    assert read_pending_agent_decision(gs) is None
    assert len(gs["squad_models"][_SQUAD]) > 3, "l'effet s'applique directement"


def test_chosen_intent_drives_the_positions() -> None:
    """L'intention choisie change réellement les positions retenues."""
    gs = _state(n_alive=3, n_destroyed=3)
    template = gs["models_cache"][f"{_SQUAD}#0"]

    toward = plan_returned_models_placement(gs, _SQUAD, template, 2, "toward_enemy")
    away = plan_returned_models_placement(gs, _SQUAD, template, 2, "away_from_enemy")

    assert toward and away
    from engine.combat_utils import calculate_hex_distance

    enemy_col = int(gs["units_cache"][_ENEMY]["col"])
    enemy_row = int(gs["units_cache"][_ENEMY]["row"])

    def _closest(cells):
        return min(calculate_hex_distance(c, r, enemy_col, enemy_row) for c, r in cells)

    assert _closest(toward) < _closest(away), (
        f"toward_enemy doit se rapprocher de ({enemy_col},{enemy_row}) : "
        f"toward={toward} away={away}"
    )


def test_decision_applies_the_chosen_intent() -> None:
    """Le handler pose les figurines à l'endroit dicté par l'intention jouée."""
    from engine.agent_decision import read_pending_agent_decision

    gs = _state(n_alive=3, n_destroyed=3)
    assert _accept_grot_orderly(gs) is True
    template = gs["models_cache"][f"{_SQUAD}#0"]
    expected = plan_returned_models_placement(
        gs, _SQUAD, template, gs["_pending_returned_placement"]["to_restore"], "away_from_enemy"
    )

    apply_returned_models_placement_decision(gs, 1, "away_from_enemy")

    assert read_pending_agent_decision(gs) is None
    assert "_pending_returned_placement" not in gs
    placed = [
        (int(gs["models_cache"][mid]["col"]), int(gs["models_cache"][mid]["row"]))
        for mid in gs["squad_models"][_SQUAD] if "#r" in mid
    ]
    assert placed == expected


def test_unknown_intent_raises() -> None:
    """Une intention hors contrat est une rupture, pas un cas à absorber."""
    gs = _state(n_alive=3, n_destroyed=3)
    template = gs["models_cache"][f"{_SQUAD}#0"]

    with pytest.raises(ValueError, match="intention"):
        plan_returned_models_placement(gs, _SQUAD, template, 1, "sideways")


# ---------------------------------------------------------------------------
# Contraintes de la règle
# ---------------------------------------------------------------------------


def test_no_legal_cell_returns_nothing_and_keeps_the_once_per_battle() -> None:
    """Aucune case légale → rien n'est rendu, et l'effet reste disponible.

    La règle impose un placement conforme ; elle n'ouvre aucune pose de repli, et consommer le
    « once per battle » sans rien rendre volerait la capacité.
    """
    gs = _state(n_alive=3, n_destroyed=3)
    # Plateau entièrement muré autour de l'escouade : plus aucune ancre n'est posable.
    gs["wall_hexes"] = {
        (c, r) for c in range(gs["board_cols"]) for r in range(gs["board_rows"])
    }

    posted = _accept_grot_orderly(gs)

    assert posted is False
    assert len(gs["squad_models"][_SQUAD]) == 3, "aucune figurine ne doit être rendue"
    assert _SQUAD not in gs.get("return_destroyed_models_used", set())


def test_legal_cells_exclude_enemy_footprints() -> None:
    """Une case dont l'empreinte recouvre un ennemi n'est jamais légale."""
    gs = _state(n_alive=3, n_destroyed=3, enemy_at=(8, 5))
    template = gs["models_cache"][f"{_SQUAD}#0"]
    enemy = gs["models_cache"][f"{_ENEMY}#0"]
    enemy_cells = _model_footprint(gs, enemy, int(enemy["col"]), int(enemy["row"]))

    cells = returned_models_legal_cells(gs, _SQUAD, template)

    for col, row in cells:
        assert not (_model_footprint(gs, template, col, row) & enemy_cells), (
            f"({col},{row}) recouvre l'empreinte ennemie"
        )


def test_legal_cells_exclude_own_models() -> None:
    """Une case occupée par une figurine de l'escouade n'est jamais légale."""
    gs = _state(n_alive=3, n_destroyed=3)
    template = gs["models_cache"][f"{_SQUAD}#0"]
    own = {
        (int(gs["models_cache"][mid]["col"]), int(gs["models_cache"][mid]["row"]))
        for mid in gs["squad_models"][_SQUAD]
    }

    cells = returned_models_legal_cells(gs, _SQUAD, template)

    assert own.isdisjoint(set(cells))


def test_restored_models_are_full_health_and_distinct_ids() -> None:
    """Chaque figurine rendue a son propre identifiant et repart à pleins PV (REVIVED)."""
    gs = _state(n_alive=3, n_destroyed=3, enemy_at=None)
    _accept_grot_orderly(gs)

    restored = [mid for mid in gs["squad_models"][_SQUAD] if "#r" in mid]
    assert restored
    assert len(set(restored)) == len(restored)
    for mid in restored:
        model = gs["models_cache"][mid]
        assert model["HP_CUR"] == model["HP_MAX"]
        assert model["id"] == mid, "l'identifiant du template ne doit pas être recopié"


def test_the_returned_line_declares_each_restored_model_datasheet() -> None:
    """La ligne `RETURNED` porte la DATASHEET de chaque socle rendu — grammaire 10.

    ROUGE avant le fix : `return_destroyed_models` n'était dans aucune entrée de
    `_STEP_LOG_TYPE_MAP` (type sans formateur, écarté en silence) et l'action_log ne portait ni
    message, ni position, ni datasheet. Les ids `#r` n'apparaissaient dans step.log qu'au détour
    du `[MODELS:]` d'une ligne suivante, sans datasheet — et `living_datasheets` (analyzer)
    s'abstenait de tout verdict 19.04 pour l'escouade (mesuré le 2026-09-11 : 6 ids `#r`,
    0 déclaré). 19.04 : « Should those models later be revived, those abilities will once more
    apply » — le socle rendu est exactement celui dont la datasheet compte.

    Deux profils archivés distincts (Boyz, PainBoy) : la datasheet vient de la figurine rendue,
    pas de l'escouade.
    """
    from ai.step_logger import StepLogger
    from engine.w40k_core import W40KEngine

    gs = _state(
        n_alive=3, n_destroyed=2, enemy_at=None,
        destroyed_profiles=[("Boyz", 10), ("PainBoy", 60)],
    )
    # Deux profils distincts posent une décision `returned_models_profile` en amont : on appelle
    # l'ÉCRIVAIN directement, avec les deux figurines de l'archive et deux cases légales.
    apply_returned_models_placement(gs, _SQUAD, [(6, 7), (6, 8)], [0, 1], d3=2, destroyed=2)
    logs = [e for e in gs["action_logs"] if e["type"] == "return_destroyed_models"]
    assert len(logs) == 1, logs
    entry = logs[0]
    restored = [mid for mid in gs["squad_models"][_SQUAD] if "#r" in mid]
    assert entry["restored"] == len(restored) and restored, entry
    assert set(entry["restoredModelTypes"]) == set(restored), entry
    for mid in restored:
        assert entry["restoredModelTypes"][mid] == gs["models_cache"][mid]["unitType"]
    assert {"Boyz", "PainBoy"} >= set(entry["restoredModelTypes"].values())
    assert entry["abilityDisplayName"].upper() == "GROT ORDERLY"
    assert entry["unitId"] == _SQUAD and entry["phase"] == "command"
    assert "RETURNED" in entry["message"] and "[GROT ORDERLY]" in entry["message"]

    # CHEMIN DE PRODUCTION du journal : traduction des clés puis formateur.
    assert "return_destroyed_models" in W40KEngine._STEP_LOG_TYPE_MAP
    assert "return_destroyed_models" in W40KEngine._STEP_LOG_NON_INCREMENTING_TYPES, (
        "une restitution n'est pas un step d'agent"
    )
    eng = W40KEngine.__new__(W40KEngine)
    eng.game_state = gs
    details = eng._build_step_log_details(entry, pre_action_turn=1)
    logger = StepLogger(output_file="/dev/null", enabled=False, buffer_size=1)
    msg = logger._format_replay_style_message(_SQUAD, "returned_models", details)
    assert msg.startswith(f"Unit {_SQUAD}({entry['col']},{entry['row']}) RETURNED {len(restored)} models [GROT ORDERLY] (D3="), msg
    assert "[MODEL_TYPES: " in msg, msg
    for mid in restored:
        assert f"{mid}={gs['models_cache'][mid]['unitType']}" in msg, msg
    # Le segment [MODELS:] (positions des socles vivants, socles rendus compris) suit la ligne.
    assert details["models_segment"], "la ligne RETURNED doit porter [MODELS:]"
    for mid in restored:
        assert f"{mid}@(" in details["models_segment"], details["models_segment"]


def test_a_squad_without_named_ability_cannot_return_models() -> None:
    """Le nom de la capacité est exigé (T1) : une restitution par une escouade qui ne porte pas
    `return_destroyed_models` est une incohérence d'état, pas une ligne sans tag."""
    gs = _state(n_alive=3, n_destroyed=2, enemy_at=None)
    for unit in gs["units"]:
        if unit["id"] == _SQUAD:
            unit["UNIT_RULES"] = []
    with pytest.raises(ValueError, match="sans capacite"):
        apply_returned_models_placement(gs, _SQUAD, [(6, 7)], [0], d3=1, destroyed=2)


# ---------------------------------------------------------------------------
# Le vrai symptôme : l'escouade peut encore bouger
# ---------------------------------------------------------------------------


def test_squad_can_still_move_after_restoration() -> None:
    """Le mouvement rigide de l'escouade reste exécutable — c'est le crash d'origine.

    ROUGE avant le fix : `explain_move_plan_rejection` renvoyait
    « collision intra-plan : deux figurines en (…) niveau 0 ».
    """
    from engine.phase_handlers.shared_utils import explain_move_plan_rejection

    gs = _state(n_alive=3, n_destroyed=3, enemy_at=None)
    _accept_grot_orderly(gs)

    plan = [
        (mid, int(gs["models_cache"][mid]["col"]) + 1, int(gs["models_cache"][mid]["row"]), 0)
        for mid in gs["squad_models"][_SQUAD]
    ]
    reason = explain_move_plan_rejection(
        plan, gs, {"budget_per_model": None, "require_coherency": False}
    )

    assert reason is None or "collision intra-plan" not in reason, (
        f"le plan doit rester exécutable, refus obtenu : {reason}"
    )


def _state_with_a_survivor_on_the_floor() -> Dict[str, Any]:
    """Jumeau MULTI-NIVEAU : `pain#1` est à l'ÉTAGE (plancher 3×3 autour de (6,5)), ses deux
    sœurs au sol — le gate de P1 (2026-09-17) : un socle rendu posé SOUS une survivante à l'étage.

    L'état est aussi porté en phase de MOVE (budget, caches) pour mesurer le masque de move rigide
    juste après la restitution : c'est là que la partie plantait.
    """
    gs = _state(n_alive=3, n_destroyed=1, enemy_at=None)
    floor_hexes = [[6 + dc, 5 + dr] for dc in (-1, 0, 1) for dr in (-1, 0, 1)]
    gs["terrain_areas"] = [{"floors": [{
        "level": 1, "height_inches": 3.0, "hexes": floor_hexes,
        "polygon_vertices": [[4, 3], [9, 3], [9, 8], [4, 8]],
    }]}]
    gs["models_cache"][f"{_SQUAD}#1"]["level"] = 1
    _recompute_squad_occupied_hexes(gs, _SQUAD)
    # Ce que porte toute unité et tout état de production, et que le masque de move lit
    # (`battle_shocked`, `_unit_move_version`, …) : les invariants partagés des fixtures.
    from tests._state_invariants import turn_state_invariants, unit_invariants

    unit = gs["unit_by_id"][_SQUAD]
    for key, value in unit_invariants().items():
        unit.setdefault(key, value)
    unit["MOVE"] = 6
    unit["BASE_SHAPE"] = "round"
    unit["BASE_SIZE"] = 1
    unit["HP_CUR"] = 9
    unit["level"] = 0
    # Forme de production des mots-clés (objets `keywordId`), lue par le move (13.06) ; la
    # restitution ne les lit pas, d'où la forme abrégée du fixture de base.
    unit["UNIT_KEYWORDS"] = [{"keywordId": "infantry"}]
    for key, value in turn_state_invariants().items():
        gs.setdefault(key, value)
    gs["units_took_to_skies"] = set()
    gs["gym_training_mode"] = True
    # Toggles de traversée RÉELS (03.01), lus par le pool de move.
    from tests.unit.engine._config_helpers import build_move_rules

    gs["config"]["move"] = build_move_rules()
    return gs


def test_returned_model_may_be_set_up_under_a_survivor_on_the_floor() -> None:
    """REVIVED n'interdit pas la case SOUS une survivante à l'étage (13.06 : deux figurines à la
    même position horizontale sur deux étages sont légales) — la règle de placement n'est PAS
    durcie pour contourner le plan rigide, c'est le plan qui s'adapte."""
    gs = _state_with_a_survivor_on_the_floor()
    template = gs["destroyed_models"][_SQUAD][0]

    assert (6, 5) in returned_models_legal_cells(gs, _SQUAD, template)


def test_squad_can_still_move_after_restoration_under_a_survivor_on_the_floor() -> None:
    """Le crash du gate de P1 : « collision intra-plan : deux figurines en (…) niveau 0 (dont
    1#r0) ». Après restitution sous la survivante à l'étage, le masque de move rigide doit être
    non vide et CHAQUE cellule offerte exécutable — la survivante garde son étage, le socle rendu
    reste au sol, elles restent superposées sans se heurter.

    ROUGE avant le fix : `build_rigid_plan` aplatissait toutes deux au niveau 0 et le masque,
    supposant la collision intra-plan invariante par translation, offrait ces destinations.
    """
    from engine.phase_handlers.shared_utils import (
        build_rigid_plan, build_squad_move_cell_map, explain_move_plan_rejection,
        infer_squad_move_type, resolve_squad_move_constraints,
    )

    gs = _state_with_a_survivor_on_the_floor()
    apply_returned_models_placement(gs, _SQUAD, [(6, 5)], [0], d3=1, destroyed=1)
    returned = [m for m in gs["squad_models"][_SQUAD] if "#r" in m]
    assert returned == [f"{_SQUAD}#r0"]
    r0 = gs["models_cache"][f"{_SQUAD}#r0"]
    assert (int(r0["col"]), int(r0["row"]), int(r0["level"])) == (6, 5, 0)

    gs["phase"] = "move"
    _build_enemy_adjacent_hexes_all_players(gs)
    cell_map = build_squad_move_cell_map(gs, _SQUAD, None)
    assert cell_map, "masque vide : l'escouade est clouée au sol après la restitution"
    kept_on_floor = 0
    for (cell, cost) in cell_map.values():
        plan = build_rigid_plan(cell[0], cell[1], _SQUAD, gs)
        assert plan is not None
        by_mid = {entry[0]: entry for entry in plan}
        assert by_mid[f"{_SQUAD}#1"][3] == 1, (cell, plan)
        assert by_mid[f"{_SQUAD}#r0"][3] == 0, (cell, plan)
        kept_on_floor += 1
        move_type = infer_squad_move_type(gs, _SQUAD, cost)
        constraints = resolve_squad_move_constraints(_SQUAD, gs, move_type, None)
        reason = explain_move_plan_rejection(plan, gs, constraints)
        assert reason is None, (cell, reason)
    assert kept_on_floor > 0


# ---------------------------------------------------------------------------
# Correctifs de revue : réserves, bords de plateau, ordre de 08.04
# ---------------------------------------------------------------------------


def test_reserves_do_not_block_placement() -> None:
    """Une unité ennemie en RÉSERVES est à la sentinelle (-1,-1) : elle ne ferme aucune case.

    Comptée comme ennemi bloquant, elle interdirait tout le coin du plateau et la restitution
    échouerait en silence, sans même consommer le « once per battle ».
    """
    gs = _state(n_alive=3, n_destroyed=3, enemy_at=None)
    gs["units"].append({
        "id": "res", "player": 2, "col": -1, "row": -1,
        "UNIT_KEYWORDS": ["INFANTRY"], "FACTION_KEYWORDS": ["TYRANIDS"], "UNIT_RULES": [],
    })
    gs["unit_by_id"]["res"] = gs["units"][-1]
    gs["models_cache"]["res#0"] = _model("res", -1, -1)
    gs["squad_models"]["res"] = ["res#0"]
    gs["units_cache"]["res"] = {
        "player": 2, "col": -1, "row": -1, "HP_CUR": 3, "OC_TOTAL": 1,
        "orientation": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 1.0,
    }
    template = gs["models_cache"][f"{_SQUAD}#0"]

    cells = returned_models_legal_cells(gs, _SQUAD, template)

    assert cells, "une unité hors table ne doit fermer aucune case"


def test_placement_never_hangs_off_the_board() -> None:
    """L'EMPREINTE doit tenir sur le plateau, pas seulement l'ancre (défaut visible à x5)."""
    gs = _state(n_alive=2, n_destroyed=3, base_size=3, enemy_at=None)
    # Escouade collée au bord : les ancres proches du bord restent valides, pas les empreintes.
    for i, mid in enumerate(gs["squad_models"][_SQUAD]):
        gs["models_cache"][mid]["col"] = 2
        gs["models_cache"][mid]["row"] = 2 + i * 6
    template = gs["models_cache"][f"{_SQUAD}#0"]

    for col, row in returned_models_legal_cells(gs, _SQUAD, template):
        for cc, rr in _model_footprint(gs, template, col, row):
            assert 0 <= cc < gs["board_cols"] and 0 <= rr < gs["board_rows"], (
                f"empreinte hors plateau depuis ({col},{row}) : ({cc},{rr})"
            )


def test_expired_waaagh_decision_does_not_break_the_command_phase() -> None:
    """08.04 : l'extinction précède la restitution, sinon une décision périmée fait LEVER.

    ROUGE si la décision de placement est posée avant `expire_faction_abilities_for_player` :
    `set_pending_agent_decision` refuse une décision déjà en attente.
    """
    from engine.phase_handlers.command_handlers import command_step_command_abilities

    gs = _state(n_alive=3, n_destroyed=3)
    # Décision restée en attente d'un tour précédent (siège sans décideur, partie rechargée).
    gs["pending_agent_decision"] = {
        "type": "waaagh_call",
        "player": 1,
        "unit_id": "player_1",
        "options": [
            {"label": "Call", "effect_ids": (), "declines": False, "payload": {"call": True}}
        ],
    }

    command_step_command_abilities(gs)  # ne doit pas lever

    assert gs.get("pending_agent_decision") is None, "la décision périmée doit avoir été purgée"
    prompts = pending_ability_call_prompts(gs, squad_id=_SQUAD, effect_id="return_destroyed_models")
    assert len(prompts) == 1, "08.04 pose l'APPEL Grot Orderly, pas encore le placement"
    gs["pending_rule_choice_queue"].pop(0)
    apply_ability_call(gs, prompts[0], True)  # ne doit pas lever non plus
    pending = gs.get("pending_agent_decision")
    assert pending is not None and str(pending["type"]) == "returned_models_placement", (
        "l'appel accepté ouvre le placement sans heurter la décision périmée"
    )


# ---------------------------------------------------------------------------
# Correctifs de revue : boucle re-décision et template mort
# ---------------------------------------------------------------------------


def test_squad_added_to_phase_skip_when_cells_empty_at_apply_time() -> None:
    """Board changé entre pose et résolution de placement_decision : cells vide → skip temporaire.

    Le « once per battle » ne doit PAS être consommé (cohérent avec le chemin profile_decision
    et mono-profil). L'escouade entre dans _grot_orderly_skipped_this_phase pour ne pas être
    reposée en boucle dans la même phase de commandement.

    ROUGE avant le fix : return_destroyed_models_used.add() était appelé inconditionnellement
    (ligne 505 de l'original), consommant la capacité sans avoir rendu de figurine.

    Stratégie : plateau 1×1 ; le template occupe (0,0) — aucune case libre, plan retourne [].
    """
    gs = _state(n_alive=3, n_destroyed=3)
    assert _accept_grot_orderly(gs) is True  # décision posée

    # Réduire le plateau à (0,0) pour que plan_returned_models_placement ne trouve aucune case.
    gs["board_cols"] = 1
    gs["board_rows"] = 1
    # Déplacer toutes les figurines sur la seule case disponible pour bloquer le BFS.
    for mid in gs["squad_models"][_SQUAD]:
        gs["models_cache"][mid]["col"] = 0
        gs["models_cache"][mid]["row"] = 0

    before_count = len(gs["squad_models"][_SQUAD])
    apply_returned_models_placement_decision(gs, 1, "away_from_enemy")

    # Aucune figurine ajoutée (aucune case légale).
    assert len(gs["squad_models"][_SQUAD]) == before_count
    # Skip temporaire posé — pas le once-per-battle.
    assert _SQUAD in gs.get("_grot_orderly_skipped_this_phase", set()), (
        "squad doit être dans _grot_orderly_skipped_this_phase pour bloquer le re-sweep"
    )
    assert _SQUAD not in gs.get("return_destroyed_models_used", set()), (
        "le 'once per battle' ne doit pas être consommé quand aucune case n'est légale"
    )


def test_returned_model_carries_the_destroyed_profile() -> None:
    """La figurine rendue porte le profil de la figurine DÉTRUITE, jamais celui d'une survivante.

    `25 Rules appendix`, REVIVED : « the specified number of destroyed models are added to the
    unit […] with all wargear and enhancements they started the battle with ».

    ROUGE avant le fix : la restitution clonait la première figurine vivante de l'escouade
    (`copy.copy(template)`), donc un Boy détruit revenait en PainBoy à 90 points dès que le
    PainBoy était la première survivante — la valeur de l'armée AUGMENTAIT en cours de partie.
    """
    gs = _state(n_alive=3, n_destroyed=1, enemy_at=None,
                destroyed_profiles=[("Boyz", 8)])
    # La seule survivante est un personnage bien plus cher : c'est elle que l'ancien code clonait.
    for mid in gs["squad_models"][_SQUAD]:
        gs["models_cache"][mid]["unitType"] = "PainBoy"
        gs["models_cache"][mid]["VALUE"] = 90

    apply_returned_models_placement(gs, _SQUAD, [(6, 7)], [0], d3=1, destroyed=1)

    restored = [mid for mid in gs["squad_models"][_SQUAD] if "#r" in mid]
    assert restored, "au moins une figurine doit être créée"
    for mid in restored:
        model = gs["models_cache"][mid]
        assert model["unitType"] == "Boyz", (
            f"la figurine rendue doit reprendre le profil detruit (Boyz), obtenu : "
            f"{model['unitType']}"
        )
        assert model["VALUE"] == 8, (
            f"la figurine rendue doit valoir ce que valait la detruite (8), obtenu : "
            f"{model['VALUE']}"
        )


def test_returned_models_never_raise_the_army_value() -> None:
    """La VALUE survivante ne peut pas dépasser la VALUE de départ après une restitution.

    C'est l'invariant que `w40k_core` vérifie en fin d'épisode (« surviving VALUE exceeds start
    VALUE »). Il tient par CONSTRUCTION dès que les figurines rendues sont de vraies figurines
    détruites : leur valeur a déjà été retranchée quand elles sont mortes.

    ROUGE avant le fix : trois Boyz à 8 détruits revenaient en trois PainBoy à 90, soit +246.
    """
    gs = _state(n_alive=1, n_destroyed=3, enemy_at=None,
                destroyed_profiles=[("Boyz", 8), ("Boyz", 8), ("Boyz", 8)])
    for mid in gs["squad_models"][_SQUAD]:
        gs["models_cache"][mid]["unitType"] = "PainBoy"
        gs["models_cache"][mid]["VALUE"] = 90

    start_value = (
        sum(float(m["VALUE"]) for m in gs["models_cache"].values() if int(m["player"]) == 1)
        + sum(float(m["VALUE"]) for m in gs["destroyed_models"][_SQUAD])
    )

    apply_returned_models_placement(
        gs, _SQUAD, [(6, 7), (6, 8), (6, 9)], [0, 1, 2], d3=3, destroyed=3
    )

    surviving = sum(
        float(m["VALUE"]) for m in gs["models_cache"].values() if int(m["player"]) == 1
    )
    assert surviving <= start_value, (
        f"VALUE survivante {surviving} > VALUE de depart {start_value} : la restitution a cree "
        f"de la valeur qui n'existait pas au debut de la partie"
    )


def test_returned_models_leave_the_archive() -> None:
    """Une figurine rendue n'est plus détruite : elle sort de l'archive.

    Sans ce retrait, une seconde restitution (une autre unité, une autre partie du balayage)
    pourrait rendre DEUX FOIS la même figurine — et là, la VALUE dépasserait bel et bien.
    """
    gs = _state(n_alive=2, n_destroyed=2, enemy_at=None,
                destroyed_profiles=[("Boyz", 8), ("BoyzNobKombi", 12)])

    apply_returned_models_placement(gs, _SQUAD, [(6, 7)], [1], d3=1, destroyed=2)

    remaining = gs["destroyed_models"][_SQUAD]
    assert len(remaining) == 1, f"une seule figurine doit rester detruite, obtenu {len(remaining)}"
    assert remaining[0]["unitType"] == "Boyz", (
        f"c'est le Nob (index 1) qui a ete rendu ; il doit rester le Boy, obtenu "
        f"{remaining[0]['unitType']}"
    )


# ---------------------------------------------------------------------------
# QUELLES figurines reviennent : décision `returned_models_profile`
# ---------------------------------------------------------------------------

def test_no_profile_decision_when_all_destroyed_share_one_profile() -> None:
    """Un seul profil détruit = rien à choisir : aucune décision de profil n'est posée.

    Même principe que le placement — une seule option réelle est une décision, pas un choix.
    """
    gs = _state(n_alive=3, n_destroyed=2, enemy_at=None,
                destroyed_profiles=[("Boyz", 8), ("Boyz", 8)])

    _accept_grot_orderly(gs)

    pending = gs.get("pending_agent_decision")
    assert pending is None or pending["type"] != "returned_models_profile", (
        "aucune decision de profil ne doit etre posee quand un seul profil est detruit"
    )


def test_profile_decision_is_posted_when_profiles_differ() -> None:
    """Plusieurs profils détruits → l'agent choisit lequel revient, avec valeur et effectif.

    La règle fixe le NOMBRE (D3) mais pas l'identité : un Nob à 85 points et trois Boyz à 8
    ne se valent ni en points ni en contrôle d'objectif, donc le moteur n'a pas à trancher.
    """
    gs = _state(n_alive=3, n_destroyed=3, enemy_at=None,
                destroyed_profiles=[("Boyz", 8), ("Boyz", 8), ("Nob", 85)])

    posed = _accept_grot_orderly(gs)

    assert posed is True, "le balayage doit rendre la main sur une decision posee"
    pending = gs["pending_agent_decision"]
    assert pending["type"] == "returned_models_profile"
    offered = {
        opt["payload"]["profile"]: (opt["payload"]["value"], opt["payload"]["count"])
        for opt in pending["options"]
    }
    assert offered == {"Boyz": (8, 2), "Nob": (85, 1)}, (
        f"chaque profil detruit doit etre offert avec sa valeur et son effectif, obtenu {offered}"
    )


def test_agent_profile_choice_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le profil choisi par l'agent est celui qui revient, pas un ordre imposé par le moteur.

    ROUGE si le moteur retombe sur un tri interne (plus cher / moins cher d'abord) : on demande
    ici le profil le MOINS cher alors qu'un Nob est disponible.

    D3 est FIXÉ à 2 : le scénario doit tenir dans les deux Boyz détruits, sinon le complément
    (légitime) ramènerait le Warboss et le test dépendrait du dé plutôt que du choix testé.
    """
    import engine.combat_utils as combat_utils

    _real_dice = combat_utils.resolve_dice_value
    monkeypatch.setattr(
        combat_utils, "resolve_dice_value",
        lambda spec, context="": 2 if context == "grot_orderly_return"
        else _real_dice(spec, context),
    )

    gs = _state(n_alive=3, n_destroyed=3, enemy_at=None,
                destroyed_profiles=[("Boyz", 8), ("Boyz", 8), ("Nob", 85)])
    _accept_grot_orderly(gs)
    assert gs["pending_agent_decision"]["type"] == "returned_models_profile"

    apply_returned_models_profile_decision(gs, 1, "Boyz")

    # Le placement peut rester à trancher : on résout jusqu'à la pose effective.
    pending = gs.get("pending_agent_decision")
    if pending is not None and pending["type"] == "returned_models_placement":
        apply_returned_models_placement_decision(gs, 1, "away_from_enemy")

    restored = [
        gs["models_cache"][mid] for mid in gs["squad_models"][_SQUAD] if "#r" in mid
    ]
    assert restored, "au moins une figurine doit etre rendue"
    assert all(m["unitType"] == "Boyz" for m in restored), (
        f"le profil choisi (Boyz) doit etre rendu, obtenu "
        f"{[m['unitType'] for m in restored]}"
    )


# ---------------------------------------------------------------------------
# F1 + F2 : figurines archivées à un étage différent des survivants
# ---------------------------------------------------------------------------


def _state_multi_level(
    *, alive_level: int = 0, archived_level: int = 1,
) -> Dict[str, Any]:
    """Survivants à `alive_level`, figurines archivées mortes à `archived_level`."""
    gs = _state(n_alive=2, n_destroyed=2, enemy_at=None)
    # Positionner les survivants au niveau demandé.
    for mid in gs["squad_models"][_SQUAD]:
        gs["models_cache"][mid]["level"] = alive_level
    # Les figurines archivées sont mortes à un autre niveau.
    for archived in gs["destroyed_models"][_SQUAD]:
        archived["level"] = archived_level
    return gs


def test_legal_cells_found_when_survivors_changed_floor() -> None:
    """F2 — `returned_models_legal_cells` retourne des cases même si les survivants ont changé
    d'étage par rapport au niveau où les figurines archivées sont mortes.

    ROUGE avant le fix : `level` lu sur le template archivé (niveau 1), `present` filtré sur
    ce niveau alors que les survivants sont au niveau 0 → `present` vide → liste vide.
    """
    gs = _state_multi_level(alive_level=0, archived_level=1)
    template = gs["destroyed_models"][_SQUAD][0]

    cells = returned_models_legal_cells(gs, _SQUAD, template)

    assert cells, (
        "des cases légales doivent exister autour des survivants (niveau 0) "
        "même si le template est archivé au niveau 1"
    )


def test_revived_model_level_matches_current_squad() -> None:
    """F1 — le modèle rendu hérite du niveau COURANT du squad, pas du niveau archivé.

    ROUGE avant le fix : `new_model["level"]` conservait la valeur de l'archive (niveau 1)
    alors que les cases validées sont au niveau 0 → crash dans `_recompute_squad_occupied_hexes`.
    """
    gs = _state_multi_level(alive_level=0, archived_level=1)
    # Fournir des cases au niveau 0 (là où les survivants se trouvent).
    cells = [(8, 5), (8, 6)]

    apply_returned_models_placement(gs, _SQUAD, cells, [0, 1], d3=2, destroyed=2)

    restored = [gs["models_cache"][mid] for mid in gs["squad_models"][_SQUAD] if "#r" in mid]
    assert restored, "au moins une figurine doit être rendue"
    for m in restored:
        assert int(m["level"]) == 0, (
            f"la figurine rendue doit être au niveau 0 (niveau actuel du squad), "
            f"obtenu level={m['level']}"
        )


def test_profile_choice_no_cells_does_not_consume_once_per_battle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F5 — après un choix de profil, si aucune case n'est légale, le « once per battle »
    n'est PAS consommé.

    ROUGE avant le fix : `apply_returned_models_profile_choice` ajoutait l'escouade dans
    `return_destroyed_models_used` même quand `_arm_returned_placement` retournait None.
    """
    import engine.combat_utils as combat_utils

    _real_dice = combat_utils.resolve_dice_value
    monkeypatch.setattr(
        combat_utils, "resolve_dice_value",
        lambda spec, context="": 1 if context == "grot_orderly_return"
        else _real_dice(spec, context),
    )

    gs = _state(n_alive=3, n_destroyed=3, enemy_at=None,
                destroyed_profiles=[("Boyz", 8), ("Boyz", 8), ("Nob", 85)])
    # Poser la décision de profil.
    _accept_grot_orderly(gs)
    assert gs.get("pending_agent_decision", {}).get("type") == "returned_models_profile"

    # Murer le plateau : aucune case légale disponible pour le placement.
    gs["wall_hexes"] = {
        (c, r) for c in range(gs["board_cols"]) for r in range(gs["board_rows"])
    }

    apply_returned_models_profile_decision(gs, 1, "Boyz")

    assert _SQUAD not in gs.get("return_destroyed_models_used", set()), (
        "le 'once per battle' ne doit pas être consommé quand aucune case n'est légale"
    )
    assert len(gs["squad_models"][_SQUAD]) == 3, "aucune figurine ne doit avoir été rendue"


def test_mono_profile_no_cells_added_to_phase_skip_set() -> None:
    """Finding A — chemin mono-profil sans case : l'escouade entre dans le set temporaire.

    Sans ce skip, un re-sweep dans la même phase de commandement (déclenché par la résolution
    d'une autre décision d'escouade) relancerait le D3 une deuxième fois pour cette escouade.

    ROUGE avant le fix : `_apply_return_destroyed_models` ne modifiait pas
    `_grot_orderly_skipped_this_phase` pour le chemin mono-profil (path `if _mono_result is None`
    absent), laissant l'escouade sans protection contre le re-sweep.
    """
    gs = _state(n_alive=3, n_destroyed=2, enemy_at=None,
                destroyed_profiles=[("Boyz", 8), ("Boyz", 8)])
    gs["wall_hexes"] = {
        (c, r) for c in range(gs["board_cols"]) for r in range(gs["board_rows"])
    }

    _accept_grot_orderly(gs)

    assert _SQUAD in gs.get("_grot_orderly_skipped_this_phase", set()), (
        "l'escouade doit être dans _grot_orderly_skipped_this_phase pour ne pas être "
        "re-traitée dans le même tour de commandement"
    )
    assert _SQUAD not in gs.get("return_destroyed_models_used", set()), (
        "le 'once per battle' ne doit pas être consommé"
    )


# ---------------------------------------------------------------------------
# Candidats DISCERNABLES (Grot Orderly : quel profil, puis où)
# ---------------------------------------------------------------------------


def test_profile_candidates_carry_distinct_traits() -> None:
    """Deux profils détruits -> deux lignes continues DIFFÉRENTES.

    ROUGE avant le câblage de `decision_options_cont` : les candidats de
    `returned_models_profile` ne portaient ni effet accordable ni `declines`, donc des lignes
    d'observation strictement identiques. `value` et `count` vivaient dans le `payload`, que
    l'observation ne lit pas — l'agent choisissait entre un Nob et deux Boyz à pile ou face.
    """
    from engine.observation_entities import decision_option_cont_index

    gs = _state(n_alive=3, n_destroyed=3, enemy_at=None,
                destroyed_profiles=[("Boyz", 8), ("Boyz", 8), ("Nob", 85)])
    _accept_grot_orderly(gs)

    decision = gs["pending_agent_decision"]
    assert str(decision["type"]) == "returned_models_profile"
    cont = decision.get("options_cont")
    assert cont is not None, "les profils proposés doivent porter des traits continus"
    assert len(cont) == len(decision["options"])
    assert cont[0] != cont[1], f"deux profils indiscernables : {cont}"

    value_i = decision_option_cont_index("profile_value_norm")
    by_profile = {
        str(opt["payload"]["profile"]): row for opt, row in zip(decision["options"], cont)
    }
    # Rapportée au profil le plus cher PROPOSÉ : le Warboss vaut 1.0, un Boy 8/85.
    assert by_profile["Nob"][value_i] == pytest.approx(1.0)
    assert by_profile["Boyz"][value_i] == pytest.approx(8.0 / 85.0)
    # Toutes les colonnes des autres familles de décision restent muettes.
    count_i = decision_option_cont_index("profile_count_norm")
    for row in cont:
        others = [v for i, v in enumerate(row) if i not in (value_i, count_i)]
        assert others == [0.0] * len(others), f"colonnes étrangères remplies : {row}"


def test_placement_candidates_carry_distinct_traits() -> None:
    """Deux intentions de pose -> deux lignes continues DIFFÉRENTES.

    ROUGE avant le câblage : l'étiquette « toward_enemy » n'est écrite dans AUCUN scalaire
    d'observation, et les intentions sortaient toutes à `present=1`. Ce sont les distances du
    plan — objectif et ennemi le plus proche — qui disent ce que l'intention vaut sur CE plateau.
    """
    from engine.observation_entities import decision_option_cont_index

    # Un objectif RÉEL sur la table : sans lui `obj_dist_norm` vaut la borne partout, et deux
    # intentions peuvent coïncider sur la seule colonne restante. Une partie a toujours des
    # objectifs (14.01), donc c'est le fixture sans objectif qui serait le cas exotique — et
    # c'est exactement ce qu'un test « deux lignes diffèrent » aurait laissé passer.
    gs = _state(
        n_alive=3, n_destroyed=3,
        objectives=[{"id": "obj1", "hexes": [[6, 12], [7, 12], [6, 13], [7, 13]]}],
    )
    _accept_grot_orderly(gs)

    decision = gs["pending_agent_decision"]
    assert str(decision["type"]) == "returned_models_placement"
    cont = decision.get("options_cont")
    assert cont is not None, "les intentions proposées doivent porter des traits continus"
    assert len(cont) == len(decision["options"]) >= 2
    assert len({tuple(row) for row in cont}) == len(cont), (
        f"chaque intention proposée doit avoir sa propre ligne, obtenu {cont}"
    )

    enemy_i = decision_option_cont_index("dist_enemy_norm")
    by_intent = {
        str(opt["payload"]["intent"]): row for opt, row in zip(decision["options"], cont)
    }
    # L'ennemi du fixture est en (18,5), l'escouade autour de (6,5) : « vers l'ennemi » doit
    # poser plus près que « loin de l'ennemi ». C'est le SENS de la colonne qui est verrouillé
    # ici, pas seulement le fait que deux lignes diffèrent.
    assert {"toward_enemy", "away_from_enemy"} <= set(by_intent), (
        f"le fixture doit offrir les deux intentions opposées, obtenu {sorted(by_intent)}"
    )
    assert by_intent["toward_enemy"][enemy_i] < by_intent["away_from_enemy"][enemy_i], (
        f"« vers l'ennemi » doit réduire dist_enemy_norm, obtenu {by_intent}"
    )


def test_placement_traits_ignore_an_enemy_in_reserves() -> None:
    """Une escouade ennemie en RÉSERVES ne change aucune distance de plan.

    ROUGE avec l'énumération naïve de `models_cache` : une unité en réserves stratégiques (20.01)
    est vivante dans le cache mais posée sur la sentinelle (-1,-1). Elle devient alors l'ennemi
    « le plus proche » de TOUS les plans, et l'ordre des intentions s'inverse — « s'éloigner de
    l'ennemi » se décrit comme le plan le plus proche de lui. Mesuré : {0.1667, 0.2, 0.2333}
    devenait {0.15, 0.1667, 0.1167}.
    """
    from engine.observation_entities import decision_option_cont_index

    objectives = [{"id": "obj1", "hexes": [[6, 12], [7, 12], [6, 13], [7, 13]]}]

    reference = _state(n_alive=3, n_destroyed=3, objectives=objectives)
    _accept_grot_orderly(reference)
    ref_cont = reference["pending_agent_decision"]["options_cont"]

    with_reserve = _state(n_alive=3, n_destroyed=3, objectives=objectives)
    # Escouade ennemie EN RÉSERVES : la sentinelle (-1,-1) est le prédicat moteur de « hors
    # table » (`entry_is_on_battlefield`), jumelle de `deployed_on_turn is None`.
    with_reserve["units_cache"]["RESERVE"] = {
        "player": 2, "col": -1, "row": -1, "HP_CUR": 3, "OC_TOTAL": 1,
        "orientation": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1,
        "deployed_on_turn": None, "MODEL_HEIGHT": 1.0,
    }
    with_reserve["models_cache"]["RESERVE#0"] = dict(
        with_reserve["models_cache"][f"{_SQUAD}#0"], player=2, col=-1, row=-1
    )
    with_reserve["squad_models"]["RESERVE"] = ["RESERVE#0"]
    _accept_grot_orderly(with_reserve)
    res_cont = with_reserve["pending_agent_decision"]["options_cont"]

    enemy_i = decision_option_cont_index("dist_enemy_norm")
    assert [row[enemy_i] for row in res_cont] == [row[enemy_i] for row in ref_cont], (
        "une unité hors table ne doit peser sur aucune distance : "
        f"{[r[enemy_i] for r in res_cont]} contre {[r[enemy_i] for r in ref_cont]}"
    )


# ---------------------------------------------------------------------------
# Grot Orderly en appel de capacité : « you can return up to D3 destroyed BODYGUARD models »
# ---------------------------------------------------------------------------


def test_a_dead_warboss_is_never_offered_nor_returned() -> None:
    """Datasheet Painboy : seuls les BODYGUARD models reviennent. Un Warboss attaché (rôle
    `leader`) mort reste dans l'archive : il n'est ni offert comme profil, ni rendu en
    complément du D3.

    ROUGE avant le filtre `_returned_bodyguard_indices` : le Warboss était un profil offert
    (« Boyz » ou « Warboss »), et revenait sur la table.
    """
    gs = _state(n_alive=3, n_destroyed=2, enemy_at=None,
                destroyed_profiles=[("Warboss", 85, "leader"), ("Boyz", 8)])

    posed = _accept_grot_orderly(gs)

    assert posed is False, "un seul profil de bodyguard : aucun choix de profil à poser"
    assert gs["pending_agent_decision"] is None
    returned = [mid for mid in gs["squad_models"][_SQUAD] if "#r" in mid]
    assert len(returned) == 1, f"un seul bodyguard mort → une seule figurine rendue : {returned}"
    assert gs["models_cache"][returned[0]]["unitType"] == "Boyz"
    remaining = [m["unitType"] for m in gs["destroyed_models"][_SQUAD]]
    assert remaining == ["Warboss"], f"le Warboss doit rester dans l'archive : {remaining}"


def test_only_a_dead_character_means_no_call() -> None:
    """Sous l'effectif de départ mais sans aucun bodyguard mort : rien à rendre, aucun appel."""
    gs = _state(n_alive=3, n_destroyed=1, enemy_at=None,
                destroyed_profiles=[("Warboss", 85, "leader")])

    assert _apply_return_destroyed_models(gs, 1) is False
    assert gs.get("pending_rule_choice_queue", []) == []


def test_declining_the_call_consumes_nothing_and_is_reproposed_next_phase() -> None:
    """« You can » : le refus ne dépense pas le once-per-battle et ne touche pas l'archive ;
    l'escouade n'est plus proposée CETTE phase, et l'est à nouveau quand 08.01 vide le set."""
    gs = _state(n_alive=3, n_destroyed=2, enemy_at=None)
    assert _apply_return_destroyed_models(gs, 1) is True
    prompt = gs["pending_rule_choice_queue"].pop(0)

    payload = apply_ability_call(gs, prompt, False)

    assert payload == {}, "refus : aucune décision posée derrière"
    assert _SQUAD not in gs.get("return_destroyed_models_used", set())
    assert len(gs["destroyed_models"][_SQUAD]) == 2
    assert gs["squad_models"][_SQUAD] == ["pain#0", "pain#1", "pain#2"]
    assert _SQUAD in gs[_GROT_ORDERLY_SKIPPED]
    assert _apply_return_destroyed_models(gs, 1) is False, "pas reproposé dans la même phase"
    gs.pop(_GROT_ORDERLY_SKIPPED)  # ce que fait `command_step_start_of_phase` (08.01)
    assert _apply_return_destroyed_models(gs, 1) is True, "reproposé à la phase suivante"


def test_accepting_the_call_spends_the_once_per_battle() -> None:
    """Acceptation, placement forcé (tous les plans se valent, aucun ennemi) : les figurines
    reviennent, le once-per-battle est dépensé, plus aucun appel ne se pose."""
    gs = _state(n_alive=3, n_destroyed=2, enemy_at=None)

    assert _accept_grot_orderly(gs) is False
    assert _SQUAD in gs["return_destroyed_models_used"]
    assert len(gs["squad_models"][_SQUAD]) > 3
    assert _apply_return_destroyed_models(gs, 1) is False
    assert gs["pending_rule_choice_queue"] == []


def test_bot_policy_is_declared_on_dead_bodyguards_and_round() -> None:
    """Siège bot : accepte dès deux bodyguard morts, ou dès le round 4 ; jamais un tirage."""
    one_dead = _state(n_alive=3, n_destroyed=1, enemy_at=None)
    assert _bot_grot_orderly_policy(one_dead, _SQUAD) is False
    one_dead["turn"] = 4
    assert _bot_grot_orderly_policy(one_dead, _SQUAD) is True

    two_dead = _state(n_alive=3, n_destroyed=2, enemy_at=None)
    assert _bot_grot_orderly_policy(two_dead, _SQUAD) is True

    # Un Warboss mort n'est pas un bodyguard : il ne compte pas.
    character_and_boy = _state(n_alive=3, n_destroyed=2, enemy_at=None,
                               destroyed_profiles=[("Warboss", 85, "leader"), ("Boyz", 8)])
    assert _bot_grot_orderly_policy(character_and_boy, _SQUAD) is False


def test_la_restitution_ne_consomme_aucun_step_gym(tmp_path) -> None:
    """La ligne `RETURNED` passe par le VRAI drainage et n'incrémente pas `Steps=`.

    ROUGE avant le fix : `_flush_squad_action_logs_to_step_logger` comparait le type MAPPÉ
    (`returned_models`) au set `_STEP_LOG_NON_INCREMENTING_TYPES`, clé par type BRUT. Comme
    `return_destroyed_models` est le seul type non-incrémentant dont le nom mappé diffère de la
    clé, chaque restitution comptait un step — `Steps=` de la ligne `EPISODE END` gonflait d'un
    Grot Orderly par phase de commandement, à l'inverse de ce que le set déclare.

    Le test ne recopie PAS l'expression du moteur : il draine et lit le compteur du StepLogger.
    """
    from ai.step_logger import StepLogger
    from engine.w40k_core import W40KEngine

    gs = _state(n_alive=3, n_destroyed=2, enemy_at=None)
    apply_returned_models_placement(gs, _SQUAD, [(6, 7), (6, 8)], [0, 1], d3=2, destroyed=2)

    eng = W40KEngine.__new__(W40KEngine)
    eng.game_state = gs
    log = tmp_path / "step.log"
    logger = StepLogger(output_file=str(log), enabled=True, buffer_size=50)
    logger.episode_number = 1
    eng.step_logger = logger

    eng._flush_squad_action_logs_to_step_logger(pre_action_turn=1)
    logger._flush_buffer()

    lignes = [l for l in log.read_text(encoding="utf-8").splitlines() if " RETURNED " in l]
    assert len(lignes) == 1, log.read_text(encoding="utf-8")
    assert logger.episode_step_count == 0, (
        f"la restitution a consommé {logger.episode_step_count} step(s) gym : {lignes[0]}"
    )
    assert logger.step_count == 0
