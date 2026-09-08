"""Tout ce que le cache spatial du move dépose dans l'état doit rester SAUVEGARDABLE.

`_move_spatial_cache` vit dans `game_state` et n'est PAS une clé statique de
`services/game_snapshots.py` : à chaque capture de phase, tout son contenu est deepcopié puis
picklé dans la save. Deux conséquences que ce fichier verrouille :

  1. le dépickle des saves passe par `services.game_saves._safe_loads`, qui REFUSE toute classe
     hors liste blanche — une classe déposée par le move rend donc IRRÉCUPÉRABLE toute partie
     sauvegardée après une phase de mouvement ;
  2. ce qui y entre est recopié en profondeur à chaque frontière de phase, donc une structure
     lourde y coûte du temps et de la taille de save à chaque point.

Cas réel du 2026-09-08 : la mémoïsation de la carte d'obstacles du BFS y avait déposé un
`BlockedBitmap`, qui porte la `HexIndexTable` du plateau (66 000 tuples de voisins à 220x300).
Reproduit avant correction — `UnpicklingError: classe interdite au dépickle d'une save :
engine.combat_utils.BlockedBitmap`, capture 287 ms et pickle 4,26 Mo, contre 158 ms et 2,47 Mo
après. Les deux tests de save existants restaient VERTS : `tests/integration/pvp/
test_save_restricted_unpickle.py` capture juste après `start_party`, avant toute activation
d'unité, et le flux PvP x5 chemine en métrique euclidienne, sans BFS géodésique.

Le moteur est donc piloté ici en mode gym (chemin hex), le seul qui remplit ce cache.
"""

from __future__ import annotations

import os
import pickle
import random
from typing import Any, Dict

import pytest

SCENARIO = "config/board/44x60x5/scenario/scenario_pvp_test.json"
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
STEPS = 40


def _engine_with_populated_move_cache():
    """Vrai moteur, joué jusqu'à ce que le cache spatial du move porte ses entrées de transit."""
    from ai.training_utils import setup_imports
    from ai.unit_registry import UnitRegistry
    from services.api_server import get_agents_from_scenario

    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()
    sf = os.path.join(PROJECT_ROOT, SCENARIO)
    if not os.path.exists(sf):
        raise FileNotFoundError(sf)
    env = W40KEngine(
        rewards_config="default",
        training_config_name="x1",
        controlled_agent=sorted(get_agents_from_scenario(sf, ur))[0],
        scenario_file=sf,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    env.reset(seed=42)
    rng = random.Random(42)
    for _ in range(STEPS):
        cache = env.game_state.get("_move_spatial_cache") or {}
        if cache.get("transit_bm"):
            return env
        mask = env.get_action_mask()
        valid = [i for i in range(len(mask)) if mask[i]]
        if not valid:
            break
        _, _, terminated, truncated, _ = env.step(rng.choice(valid))
        if terminated or truncated:
            env.reset(seed=42)
    cache = env.game_state.get("_move_spatial_cache") or {}
    if cache.get("transit_bm"):
        return env
    pytest.fail(
        f"cache de transit vide après {STEPS} steps : aucun BFS de move n'a tourné, "
        f"ces tests ne verrouilleraient rien"
    )


@pytest.fixture(scope="module")
def engine():
    return _engine_with_populated_move_cache()


def _cache(engine) -> Dict[str, Any]:
    return engine.game_state["_move_spatial_cache"]


def test_move_cache_holds_no_class_that_the_save_reader_would_refuse(engine):
    """Une save capturée APRÈS un BFS de move doit se relire par le dépickle restreint."""
    from services.game_saves import _safe_loads
    from services.game_snapshots import capture_live_state

    assert _cache(engine)["transit_bm"], "cache de transit vide : vert vacant"

    blob = pickle.dumps(capture_live_state(engine))

    # Lève `UnpicklingError` si une classe hors liste blanche traîne dans l'état capturé.
    restored = _safe_loads(blob)
    assert restored["game_state"]["units"], "état relu sans unités : le test ne prouve rien"


def test_move_cache_stores_only_plain_bytes_for_the_blocked_map(engine):
    """La carte d'obstacles est mémoïsée en `bytes` nus, jamais en objet portant la table.

    C'est la forme qui rend le test précédent vrai, et elle se vérifie directement : un objet
    riche y ferait passer la table de plateau entière dans chaque capture de phase.
    """
    from engine.combat_utils import HexIndexTable

    board = engine.game_state["board_cols"] * engine.game_state["board_rows"]
    for key, entry in _cache(engine)["transit_bm"].items():
        transit, data = entry
        assert type(data) is bytes, (
            f"{key} : la carte est un {type(data).__name__}, pas des `bytes` nus — "
            f"tout ce qui n'est pas un type de base casse le dépickle des saves"
        )
        assert len(data) == board, f"{key} : carte de {len(data)} octets pour {board} cases"
        assert not isinstance(transit, HexIndexTable)


def test_blocked_map_deep_copies_without_duplicating_the_board_table(engine):
    """`deepcopy` de l'entrée mémoïsée ne recopie pas d'octets : `bytes` est atomique.

    Le cache est deepcopié à CHAQUE capture de phase ; sans cette propriété, chaque point de
    save paierait une copie complète de la carte.
    """
    import copy

    for _key, (_transit, data) in _cache(engine)["transit_bm"].items():
        assert copy.deepcopy(data) is data, (
            "la carte n'est plus atomique pour deepcopy — chaque capture de phase la recopie"
        )
