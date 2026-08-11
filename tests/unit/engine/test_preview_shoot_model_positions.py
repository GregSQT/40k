"""Aperçu de tir depuis des positions de figurines EXPLICITES (déploiement / move par-figurine).

DÉFAUT MESURÉ ICI (2026-08-11). Pendant un placement figurine par figurine, le plan vit dans le
client : le moteur ne reçoit rien avant la validation, donc l'escouade est HORS TABLE et son
`occupied_hexes_by_model` est peuplé de la sentinelle `(-1,-1)`. Le client demandait pourtant un
aperçu de tir « depuis une position » avec la position d'une figurine posée. Le placement par
ANCRE (`update_units_cache_position`) ne resynchronise les figurines QUE pour les escouades
mono-figurine : une escouade multi-figurine gardait donc toutes ses figurines à `(-1,-1)` pendant
que l'ancre, elle, passait sur le plateau. `_socle_from_entry` construit ses centres depuis ces
figurines → distances et LoS mesurées depuis le coin du plateau, sans la moindre erreur levée.

Le premier test verrouille le défaut par la MESURE : sans l'aperçu par-figurine, l'empreinte vue
par le moteur reste la sentinelle. Les suivants verrouillent le contrat de la correction.
"""

from typing import Any, Dict, List, Tuple

import pytest

from engine.phase_handlers.shared_utils import get_unit_from_cache
from engine.phase_handlers.shooting_handlers import (
    preview_shoot_valid_targets_from_model_positions,
    preview_shoot_valid_targets_from_position,
)
from tests.unit.engine._config_helpers import build_armageddon_engine


@pytest.fixture(scope="module")
def engine():
    return build_armageddon_engine(seed=12345)


def _multi_model_unit(game_state: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Première escouade MULTI-figurine du scénario, avec des armes de tir."""
    squad_models = game_state["squad_models"]
    for unit in game_state["units"]:
        unit_id = str(unit["id"])
        model_ids = squad_models.get(unit_id, [])
        if len(model_ids) > 1 and unit.get("RNG_WEAPONS"):
            return unit_id, [str(m) for m in model_ids]
    pytest.skip("aucune escouade multi-figurine avec arme de tir dans le scénario")


def _send_off_table(game_state: Dict[str, Any], unit_id: str, model_ids: List[str]) -> None:
    """Remet l'escouade dans l'état d'un placement NON validé : tout à la sentinelle."""
    from engine.phase_handlers.shared_utils import set_unit_coordinates

    for model_id in model_ids:
        model = game_state["models_cache"][model_id]
        model["col"] = -1
        model["row"] = -1
    entry = get_unit_from_cache(unit_id, game_state)
    assert entry is not None
    entry["col"] = -1
    entry["row"] = -1
    entry["occupied_hexes"] = []
    entry["occupied_hexes_by_model"] = {mid: (-1, -1) for mid in model_ids}
    unit = next(u for u in game_state["units"] if str(u["id"]) == unit_id)
    set_unit_coordinates(unit, -1, -1)
    unit["deployed_on_turn"] = None


def _model_centers_seen_by_engine(preview_state: Dict[str, Any], unit_id: str):
    entry = get_unit_from_cache(unit_id, preview_state)
    assert entry is not None
    return sorted(entry["occupied_hexes_by_model"].values())


def test_anchor_preview_leaves_multi_model_squad_at_the_sentinel(engine, monkeypatch):
    """LE DÉFAUT : placer par l'ANCRE laisse les figurines hors table, sans lever.

    On intercepte l'état de la copie de travail au moment où le pipeline mesure : c'est lui qui
    décide des distances et de la LoS. Si les figurines y sont encore à `(-1,-1)`, tout ce que
    l'aperçu rend est mesuré depuis le coin du plateau.
    """
    game_state = engine.game_state
    unit_id, model_ids = _multi_model_unit(game_state)
    _send_off_table(game_state, unit_id, model_ids)

    seen: Dict[str, Any] = {}
    from engine.phase_handlers import shooting_handlers

    original = shooting_handlers.build_unit_los_cache

    def _spy(gs, uid, **kwargs):
        if str(uid) == unit_id and "centers" not in seen:
            seen["centers"] = _model_centers_seen_by_engine(gs, unit_id)
        return original(gs, uid, **kwargs)

    monkeypatch.setattr(shooting_handlers, "build_unit_los_cache", _spy)
    preview_shoot_valid_targets_from_position(
        game_state, unit_id, 20, 20, include_los_cells=False
    )

    assert "centers" in seen, "le pipeline n'a pas été atteint — le test ne prouve rien"
    assert seen["centers"] == [(-1, -1)] * len(model_ids), (
        "le placement par ancre est censé laisser les figurines à la sentinelle ; si ce n'est "
        "plus le cas, ce test ne décrit plus le défaut qu'il documente"
    )


def test_model_positions_preview_puts_every_figure_on_the_board(engine, monkeypatch):
    """LA CORRECTION : chaque figurine est posée là où le plan la place."""
    game_state = engine.game_state
    unit_id, model_ids = _multi_model_unit(game_state)
    _send_off_table(game_state, unit_id, model_ids)

    positions = {mid: (20 + index, 20) for index, mid in enumerate(model_ids)}

    seen: Dict[str, Any] = {}
    from engine.phase_handlers import shooting_handlers

    original = shooting_handlers.build_unit_los_cache

    def _spy(gs, uid, **kwargs):
        if str(uid) == unit_id and "centers" not in seen:
            seen["centers"] = _model_centers_seen_by_engine(gs, unit_id)
        return original(gs, uid, **kwargs)

    monkeypatch.setattr(shooting_handlers, "build_unit_los_cache", _spy)
    preview_shoot_valid_targets_from_model_positions(
        game_state, unit_id, positions, include_los_cells=False
    )

    assert "centers" in seen, "le pipeline n'a pas été atteint — le test ne prouve rien"
    assert seen["centers"] == sorted(positions.values())
    assert all(col >= 0 and row >= 0 for col, row in seen["centers"])


def test_preview_does_not_mutate_the_real_state(engine):
    """Lecture pure : l'aperçu travaille sur une copie, l'escouade réelle ne bouge pas."""
    game_state = engine.game_state
    unit_id, model_ids = _multi_model_unit(game_state)
    _send_off_table(game_state, unit_id, model_ids)

    before = _model_centers_seen_by_engine(game_state, unit_id)
    preview_shoot_valid_targets_from_model_positions(
        game_state, unit_id, {mid: (20 + i, 20) for i, mid in enumerate(model_ids)},
        include_los_cells=False,
    )
    assert _model_centers_seen_by_engine(game_state, unit_id) == before


def test_unknown_model_id_raises_instead_of_being_ignored(engine):
    """Une figurine inconnue est une incohérence de plan, pas une figurine à sauter."""
    game_state = engine.game_state
    unit_id, model_ids = _multi_model_unit(game_state)
    with pytest.raises(KeyError):
        preview_shoot_valid_targets_from_model_positions(
            game_state, unit_id, {"figurine_qui_n_existe_pas": (20, 20)},
            include_los_cells=False,
        )


def test_off_board_position_raises(engine):
    """La sentinelle en ENTRÉE n'a pas de sens ici : c'est le plan qui donne les positions."""
    game_state = engine.game_state
    unit_id, model_ids = _multi_model_unit(game_state)
    with pytest.raises(ValueError, match="HORS TABLE"):
        preview_shoot_valid_targets_from_model_positions(
            game_state, unit_id, {model_ids[0]: (-1, -1)}, include_los_cells=False,
        )


def test_empty_plan_raises(engine):
    game_state = engine.game_state
    unit_id, _model_ids = _multi_model_unit(game_state)
    with pytest.raises(ValueError, match="aucune figurine"):
        preview_shoot_valid_targets_from_model_positions(
            game_state, unit_id, {}, include_los_cells=False,
        )
