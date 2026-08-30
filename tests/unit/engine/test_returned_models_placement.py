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

from engine.phase_handlers.command_handlers import (
    _apply_return_destroyed_models, apply_returned_models_placement_decision,
)
from engine.phase_handlers.deployment_handlers import (
    RETURNED_PLACEMENT_INTENTS, _model_footprint, plan_returned_models_placement,
    returned_models_legal_cells,
)


# ---------------------------------------------------------------------------
# État minimal : une escouade ORK avec la règle, des figurines détruites, un ennemi
# ---------------------------------------------------------------------------

_SQUAD = "pain"
_ENEMY = "foe"


def _model(squad_id: str, col: int, row: int, base_size: int = 1) -> Dict[str, Any]:
    return {
        "squad_id": squad_id,
        "col": col,
        "row": row,
        "level": 0,
        "orientation": 0,
        "T": 5,
        "role": "bodyguard",
        "HP_CUR": 3,
        "HP_MAX": 3,
        "INVUL_SAVE": 7,
        "ARMOR_SAVE": 5,
        "OC": 1,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "player": 1 if squad_id == _SQUAD else 2,
        "VALUE": 10,
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
) -> Dict[str, Any]:
    """Escouade alignée en colonne autour de (6,5) — positions DISTINCTES, état jouable."""
    units = [
        {
            "id": _SQUAD, "player": 1, "col": 6, "row": 5,
            "UNIT_KEYWORDS": ["INFANTRY"], "FACTION_KEYWORDS": ["TYRANIDS"],
            "UNIT_RULES": [{"ruleId": "return_destroyed_models"}],
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
    return {
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
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

    _apply_return_destroyed_models(gs, 1)

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

    _apply_return_destroyed_models(gs, 1)

    seen: set = set()
    for footprint in _footprints(gs, _SQUAD):
        overlap = footprint & seen
        assert not overlap, f"empreintes qui se recouvrent sur {sorted(overlap)[:5]}"
        seen |= footprint


def test_returned_models_keep_squad_coherency() -> None:
    """03.03 : « in coherency with models in that unit that started that phase »."""
    from engine.phase_handlers.shared_utils import _positions_in_coherency

    gs = _state(n_alive=3, n_destroyed=3, enemy_at=None)
    _apply_return_destroyed_models(gs, 1)

    models = [gs["models_cache"][mid] for mid in gs["squad_models"][_SQUAD]]
    assert _positions_in_coherency(models, gs), "l'escouade rendue doit rester cohérente"


# ---------------------------------------------------------------------------
# Le choix de l'agent
# ---------------------------------------------------------------------------


def test_decision_is_posted_when_intents_differ() -> None:
    """Deux intentions aboutissant à des positions différentes → l'agent tranche."""
    from engine.agent_decision import read_pending_agent_decision

    gs = _state(n_alive=3, n_destroyed=3)
    posted = _apply_return_destroyed_models(gs, 1)

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
    posted = _apply_return_destroyed_models(gs, 1)

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
    assert _apply_return_destroyed_models(gs, 1) is True
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

    posted = _apply_return_destroyed_models(gs, 1)

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
    _apply_return_destroyed_models(gs, 1)

    restored = [mid for mid in gs["squad_models"][_SQUAD] if "#r" in mid]
    assert restored
    assert len(set(restored)) == len(restored)
    for mid in restored:
        model = gs["models_cache"][mid]
        assert model["HP_CUR"] == model["HP_MAX"]
        assert model["id"] == mid, "l'identifiant du template ne doit pas être recopié"


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
    _apply_return_destroyed_models(gs, 1)

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

    pending = gs.get("pending_agent_decision")
    assert pending is not None
    assert str(pending["type"]) == "returned_models_placement", (
        "la décision périmée doit avoir été purgée et remplacée par celle du placement"
    )
