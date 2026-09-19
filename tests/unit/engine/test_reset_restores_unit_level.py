"""Le reset d'épisode restaure le NIVEAU (étages) des unités — fuite inter-épisodes.

Les objets `unit` SURVIVENT d'un épisode à l'autre (`W40KEngine.reset` les réutilise et
restaure leurs champs un par un). Tout champ muté pendant l'épisode et non restauré fuit donc
sur le suivant. `col`/`row`, `deployed_on_turn`, `in_strategic_reserves` et
`reserves_repositioned` l'étaient déjà ; `level` ne l'était pas.

Conséquence, et c'est ce que ces deux tests verrouillent :

- unité MONO-FIGURINE : `build_units_cache`, appelé à la fin du reset, relit le niveau stocké et
  appelle `floor_height_at(-1, -1, 1)` — le reset LÈVE, donc l'épisode suivant n'existe pas ;
- escouade MULTI-FIGURINES : pas d'erreur, mais l'entrée de cache sort à `level = 1` avec toutes
  ses figurines au sol, ce qui rompt l'invariant « niveau de l'unité = niveau de l'ancre ».

Le niveau est écrit en jeu par la synchronisation d'ancre du mouvement
(`movement_handlers.py`, `unit["level"] = int(require_key(entry, "level"))`) : une escouade qui
finit sa partie dans une ruine porte `level >= 1` à l'instant du reset suivant.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest


@pytest.fixture(autouse=True)
def _pin_board(board_x5):
    """Les étages n'existent qu'hors x1 : à x1 une figurine occupe une seule case."""


def _unit_with_model_count(engine, count: int) -> Dict[str, Any]:
    squad_models = engine.game_state["squad_models"]
    for unit in engine.game_state["units"]:
        if len(squad_models.get(str(unit["id"]), [])) == count:
            return unit
    raise AssertionError(
        f"aucune unité à {count} figurine(s) dans ce scénario — le test ne peut pas "
        "mettre en scène le cas qu'il verrouille"
    )


def test_le_reset_efface_le_niveau_d_une_unite_mono_figurine(make_active_deployment_engine):
    """Sans la restauration, ce reset LÈVE « no floor at level 1 contains cell (-1, -1) »."""
    engine = make_active_deployment_engine(seed=0)
    unit = _unit_with_model_count(engine, 1)
    unit_id = str(unit["id"])
    # VERT VACANT : le champ doit exister et valoir 0 avant qu'on le salisse, sinon le test
    # ne prouverait pas que c'est bien le RESET qui le remet à zéro.
    assert int(unit["level"]) == 0
    unit["level"] = 1  # fin de partie dans une ruine

    engine.reset(seed=1)

    restored = next(u for u in engine.game_state["units"] if str(u["id"]) == unit_id)
    assert int(restored["level"]) == 0, (
        "le niveau du tour précédent a fui sur l'épisode suivant"
    )
    assert int(engine.game_state["units_cache"][unit_id]["level"]) == 0


def test_le_reset_realigne_le_niveau_d_une_escouade_sur_ses_figurines(
    make_active_deployment_engine,
):
    """Multi-figurines : pas de crash, mais l'ancre sortait à l'étage avec tout le monde au sol."""
    engine = make_active_deployment_engine(seed=0)
    unit = _unit_with_model_count(engine, 6)
    unit_id = str(unit["id"])
    unit["level"] = 2

    engine.reset(seed=1)

    entry = engine.game_state["units_cache"][unit_id]
    assert int(entry["level"]) == 0
    levels = entry["level_by_model"]
    assert levels, "l'escouade doit avoir des figurines pour que la comparaison prouve quelque chose"
    assert set(int(v) for v in levels.values()) == {0}
    assert int(entry["level"]) == int(next(iter(levels.values()))), (
        "invariant : le niveau de l'unité est celui de son ancre"
    )
