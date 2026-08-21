"""Verrou : unit_entries_within_engagement_zone utilise le game_state pour résoudre la métrique.

Cinq tests, un par fichier appelant. Chaque test vérifie qu'un game_state dont
``inches_to_subhex`` diverge du board_config sur disque produit LE VERDICT DU GS —
non celui de la config globale.

Stratégie commune :
- spy sur ``engine.spatial_relations.engagement_distance_metric`` : retourne ``"hex"``
  si ``game_state`` est fourni (= gs du test), ``"euclidean"`` sinon.
- Un verdict ``"euclidean"`` est forcé à False via un patch de ``euclidean_edge_distance``
  qui retourne un écart hors seuil.
- Assertion : le call-site de chaque fichier passe bien ``game_state=gs``.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.spatial_relations import unit_entries_within_engagement_zone


# ─────────────────────────────────────────────────────────────────────────────
# Helpers communs
# ─────────────────────────────────────────────────────────────────────────────

def _gs_hex() -> Dict[str, Any]:
    """game_state minimal — inches_to_subhex=1 → géométrie HEX."""
    return {
        "inches_to_subhex": 1,
        "config": {"game_rules": {"engagement_zone": 2}},
    }


def _entry(col: int, row: int, player: int = 1) -> Dict[str, Any]:
    """Entrée units_cache minimale : socle rond base_size=1, sur le champ de bataille."""
    return {
        "col": col, "row": row, "player": player,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "occupied_hexes": {(col, row)},
    }


def _patch_divergence(monkeypatch: pytest.MonkeyPatch, gs_ref: Dict[str, Any]) -> None:
    """Monkeypatche engagement_distance_metric pour simuler une divergence config/game_state.

    - Si game_state IS gs_ref → "hex" (verdict du gs).
    - Si game_state is None  → "euclidean" (verdict config disque).
    + euclidean_edge_distance retourne un écart maximal → verdict euclidean = False.
    """
    def _edm(game_state=None) -> str:
        return "hex" if game_state is gs_ref else "euclidean"

    monkeypatch.setattr("engine.spatial_relations.engagement_distance_metric", _edm)
    # Forcer le chemin euclidean à « hors zone » quelle que soit la géométrie réelle.
    monkeypatch.setattr(
        "engine.spatial_relations.euclidean_edge_distance",
        lambda *_a, **_kw: 999.0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. engine/spatial_relations.py — call-site direct
# ─────────────────────────────────────────────────────────────────────────────

def test_verrou_game_state_spatial_relations(monkeypatch: pytest.MonkeyPatch) -> None:
    """La primitive utilise game_state pour la métrique : verdict hex ≠ verdict euclidean.

    Deux socles à distance hex 2 dans une zone d'engagement 2 :
    - avec game_state (GS hex) → metric="hex" → True (dans la zone).
    - sans game_state (config disk euclidean simulée) → metric="euclidean" →
      euclidean_edge_distance retourne 999 >> seuil → False.
    """
    gs = _gs_hex()
    _patch_divergence(monkeypatch, gs)

    e1 = _entry(0, 0, player=1)
    e2 = _entry(2, 0, player=2)  # hex-distance 2 depuis (0,0) → dans la zone (ez=2)

    # game_state fourni → métrique hex → True
    assert unit_entries_within_engagement_zone(e1, e2, 2, game_state=gs, memoise=False) is True
    # game_state absent → métrique euclidean (simulée hors zone) → False
    assert unit_entries_within_engagement_zone(e1, e2, 2, memoise=False) is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. engine/observation_builder.py — call-site ligne 1802
# ─────────────────────────────────────────────────────────────────────────────

def test_verrou_game_state_observation_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_squad_observation passe game_state à unit_entries_within_engagement_zone (ligne 1802).

    Setup minimal pour atteindre le bloc ENGAGEMENT :
    - deux escouades déployées (deployed_on_turn=0 ≠ None → on_battlefield)
    - méthodes lourdes d'encodage d'entités mockées (objectives, pending, deployment)
    - spy sur la primitive : si game_state= est supprimé ligne 1802, le spy reçoit None
      et l'assertion échoue.
    """
    from tests.unit.engine._config_helpers import build_game_rules
    from tests.unit.engine._state_builders import synthetic_state, synthetic_unit
    from engine.observation_builder import ObservationBuilder

    # FACTION_KEYWORDS et army_faction : army_has_oath_ability exige la déclaration explicite
    # (aucun défaut admis). TYRANIDS = faction neutre des tests sans capacité de commandement.
    unit_a = synthetic_unit("u1", 1, [{"col": 0, "row": 0, "OC": 1}],
                            FACTION_KEYWORDS=["TYRANIDS"], UNIT_KEYWORDS=[])
    unit_b = synthetic_unit("u2", 2, [{"col": 1, "row": 0, "OC": 1}],
                            FACTION_KEYWORDS=["TYRANIDS"], UNIT_KEYWORDS=[])
    gs = synthetic_state(
        [unit_a, unit_b],
        phase="shoot",
        game_rules=build_game_rules(),
        inches_to_subhex=1,
        # victory_points n'est pas posé par synthetic_state — ajouté via overrides ci-dessous
        **{"victory_points": {1: 0, 2: 0}},
    )
    gs["config"]["army_faction"] = {"1": "TYRANIDS", "2": "TYRANIDS"}
    # value_at_start est posé par build_units_cache (appelé dans synthetic_state). ✓
    # command_points est posé par turn_state_invariants(). ✓

    gs_received: list = []

    real_uewz = unit_entries_within_engagement_zone

    def _spy_uewz(
        first_entry: Any,
        second_entry: Any,
        engagement_zone: Any,
        metric: Any = None,
        vertical_zone_inches: Any = None,
        *,
        game_state: Any = None,
        memoise: bool = True,
    ) -> bool:
        gs_received.append(game_state)
        return real_uewz(
            first_entry, second_entry, engagement_zone,
            metric=metric, vertical_zone_inches=vertical_zone_inches,
            game_state=game_state, memoise=memoise,
        )

    monkeypatch.setattr("engine.spatial_relations.unit_entries_within_engagement_zone", _spy_uewz)

    # Mocker les méthodes lourdes pour ne pas exiger un game_state complet d'objectifs, etc.
    n = ObservationBuilder.SQUAD_N_OBJECTIVE_SLOTS
    monkeypatch.setattr(
        ObservationBuilder, "_squad_objective_control",
        lambda *_a, **_kw: ([0.0] * n, [0.0] * n),
    )
    monkeypatch.setattr(
        ObservationBuilder, "_squad_objective_geometry",
        lambda *_a, **_kw: ([0.0] * n, [0.0] * n, [0.0] * n),
    )
    monkeypatch.setattr(ObservationBuilder, "_encode_pending_decision", lambda *_a, **_kw: None)
    monkeypatch.setattr(ObservationBuilder, "_encode_deployment_candidates", lambda *_a, **_kw: None)

    builder = ObservationBuilder({"observation_params": {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}})

    # Appel réel — peut lever après le bloc ENGAGEMENT (entity encoding non mocké), ce qui
    # est acceptable : le spy est invoqué EN AMONT de ce qui pourrait lever.
    try:
        builder.build_squad_observation(gs, "u1")
    except Exception:
        pass  # échec APRÈS le bloc EZ (entity encoding) — le spy a déjà été appelé

    assert gs_received and any(g is gs for g in gs_received), (
        "build_squad_observation n'a pas propagé game_state à unit_entries_within_engagement_zone "
        "(ligne 1802 ou 1851). La métrique lirait la config disque au lieu du game_state courant."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. engine/phase_handlers/shared_utils.py — call-site _squads_are_engaged
# ─────────────────────────────────────────────────────────────────────────────

def test_verrou_game_state_shared_utils(monkeypatch: pytest.MonkeyPatch) -> None:
    """_squads_are_engaged passe game_state à unit_entries_within_engagement_zone.

    Le spy capte l'appel interne via engagement_distance_metric : si game_state=
    est omis, reçu sera [None] au lieu de [gs].
    """
    gs = _gs_hex()
    gs["units_cache"] = {
        "u1": _entry(0, 0, player=1),
        "u2": _entry(1, 0, player=2),
    }
    gs_received: list = []

    def _spy_edm(game_state=None) -> str:
        gs_received.append(game_state)
        return "hex"

    monkeypatch.setattr("engine.spatial_relations.engagement_distance_metric", _spy_edm)

    from engine.phase_handlers.shared_utils import _squads_are_engaged
    _squads_are_engaged(gs, "u1", "u2")

    assert gs_received and gs_received[-1] is gs, (
        "_squads_are_engaged n'a pas propagé game_state à engagement_distance_metric."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. engine/phase_handlers/charge_handlers.py — call-site _charge_anchor_within_1_of_target
# ─────────────────────────────────────────────────────────────────────────────

def test_verrou_game_state_charge_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    """_charge_anchor_within_1_of_target passe game_state à unit_entries_within_engagement_zone.

    Pour éviter le setup du BFS complet, on spy sur engagement_distance_metric et on
    laisse la primitive s'exécuter réellement.
    """
    from tests.unit.engine._config_helpers import build_game_rules
    from tests.unit.engine._state_builders import MODEL_HEIGHT, synthetic_state, synthetic_unit

    gs_received: list = []

    def _spy_edm(game_state=None) -> str:
        gs_received.append(game_state)
        return "hex"

    monkeypatch.setattr("engine.spatial_relations.engagement_distance_metric", _spy_edm)

    unit_a = synthetic_unit("u1", 1, [{"col": 0, "row": 0}])
    unit_b = synthetic_unit("u2", 2, [{"col": 1, "row": 0}])
    gs = synthetic_state(
        [unit_a, unit_b],
        phase="charge",
        game_rules=build_game_rules(),
    )

    from engine.phase_handlers.charge_handlers import _charge_anchor_within_1_of_target

    # anchor_col=0, anchor_row=0 : empreinte {(0,0)} ∩ cible {(1,0)} = ∅ → pas de retour
    # anticipé sur overlap, l'appel EZ est atteint.
    _charge_anchor_within_1_of_target(gs, unit_a, unit_b, anchor_col=0, anchor_row=0)

    assert gs_received and gs_received[-1] is gs, (
        "_charge_anchor_within_1_of_target n'a pas propagé game_state à engagement_distance_metric."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. engine/phase_handlers/shooting_handlers.py — call-site _friendly_engagement_blocks_ranged_shot
# ─────────────────────────────────────────────────────────────────────────────

def test_verrou_game_state_shooting_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    """_friendly_engagement_blocks_ranged_shot passe game_state à unit_entries_within_engagement_zone.

    Setup minimal : shooter player 1, friendly player 1, target player 2. Le friendly
    est adjacent à la cible → le check EZ est atteint.
    """
    gs = _gs_hex()
    target_entry = _entry(1, 0, player=2)
    friendly_entry = _entry(1, 0, player=1)  # même hex = adjacent à la cible
    gs["units_cache"] = {
        "shooter": _entry(5, 5, player=1),
        "friendly": friendly_entry,
    }

    gs_received: list = []

    def _spy_edm(game_state=None) -> str:
        gs_received.append(game_state)
        return "hex"

    monkeypatch.setattr("engine.spatial_relations.engagement_distance_metric", _spy_edm)

    from engine.phase_handlers.shooting_handlers import _friendly_engagement_blocks_ranged_shot

    result = _friendly_engagement_blocks_ranged_shot(
        game_state=gs,
        shooter_id_str="shooter",
        shooter_player_int=1,
        target_entry=target_entry,
        target_id_str="target",
        enemy_adjacent_to_shooter=False,  # force le check EZ
        units_cache=gs["units_cache"],
    )

    # Le friendly est au même hex que la cible → EZ True → bloque le tir.
    assert result is True
    assert gs_received and gs_received[-1] is gs, (
        "_friendly_engagement_blocks_ranged_shot n'a pas propagé game_state à engagement_distance_metric."
    )
