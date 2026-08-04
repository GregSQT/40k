"""`max_base_size_hex` — régime d'erreur de la CLÉ, jumeau de `get_engagement_zone`.

DÉFAUT CORRIGÉ (2026-08-04, mesuré). `shared_utils.get_max_base_size_hex` lisait la clé par
TROIS replis en cascade (`game_state.get("config") or {}` → `config.get("game_rules") or {}` →
`game_rules.get("max_base_size_hex", 35)`), alors que son jumeau strict, à dix lignes de là dans
le MÊME fichier (`get_engagement_zone` → `spatial_relations.get_engagement_zone`), exige les
trois niveaux par `require_key`. Deux lecteurs de la même section `game_rules`, dans le même
fichier, avec des régimes d'erreur opposés : exactement l'asymétrie supprimée le même jour entre
`move` et `objective_control_check` (cf. `test_objective_control_checkpoint_1402.py`), cette fois
au niveau de la CLÉ et non de la SECTION.

Le `35` littéral ne couvrait AUCUN cas métier : la clé existe dans `config/game_config.json` et,
mesuré sur 791 appels d'une partie réelle (`ArmageddonAgent`, `x1_debug`, deux graines), elle a
été lue depuis la config à chaque fois — zéro repli, valeur toujours 35. Le défaut ne pouvait
donc que masquer un état de jeu malformé ou une clé retirée du JSON. Il était d'autant plus
trompeur que ce seuil est un DIAMÈTRE HEX non scalé par `inches_to_subhex` (absent de la liste
de conversion de `w40k_core`) : un littéral en dur n'a pas le même sens d'un plateau à l'autre.

Ce fichier verrouille les deux moitiés : la config de production porte la clé, ET les deux
appelants de production propagent l'exigence au lieu de se replier localement.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from shared.data_validation import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO = (
    PROJECT_ROOT
    / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "scenario_training_armageddon.json"
)


@pytest.fixture(scope="module")
def gym_engine():
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    engine = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", training_n_envs=1,
        scenario_file=str(SCENARIO), unit_registry=UnitRegistry(),
        quiet=True, gym_training_mode=True,
    )
    engine.reset(seed=0)
    return engine


def _state_without(game_state, *, drop: str):
    """Copie de l'état où l'on retire `drop` (clé de game_rules, ou "game_rules", ou "config").

    Copie SUPERFICIELLE des seuls dictionnaires réécrits : `game_state` porte les caches du
    moteur (units_cache, squad_models…) qu'un deepcopy dupliquerait pour rien.
    """
    state = dict(game_state)
    if drop == "config":
        del state["config"]
        return state
    config = dict(state["config"])
    state["config"] = config
    if drop == "game_rules":
        del config["game_rules"]
        return state
    game_rules = dict(config["game_rules"])
    del game_rules[drop]
    config["game_rules"] = game_rules
    return state


def test_la_config_de_production_porte_la_cle(gym_engine) -> None:
    """La clé vit dans `config/game_config.json`, plus dans le code Python.

    Sans défaut littéral, son retrait du JSON n'éteint plus une borne en silence : il fait
    tomber le moteur au premier calcul d'horizon d'engagement.
    """
    game_rules = gym_engine.game_state["config"]["game_rules"]
    assert "max_base_size_hex" in game_rules, (
        "`max_base_size_hex` absente des `game_rules` du moteur d'ENTRAÎNEMENT : la prune "
        "conservatrice des ennemis (move + observation) ne peut plus se borner"
    )
    assert int(game_rules["max_base_size_hex"]) > 0


def test_le_getter_exige_les_trois_niveaux(gym_engine) -> None:
    """Aucun défaut caché : config, section et clé sont EXIGÉES, comme `get_engagement_zone`.

    Avec l'ancienne cascade `.get(..., 35)`, les trois cas rendaient 35 en silence.
    """
    from engine.phase_handlers.shared_utils import get_max_base_size_hex

    for drop in ("config", "game_rules", "max_base_size_hex"):
        with pytest.raises(ConfigurationError):
            get_max_base_size_hex(_state_without(gym_engine.game_state, drop=drop))


def test_la_valeur_vient_de_la_config_et_non_dune_constante(gym_engine) -> None:
    """VERT VACANT : exiger la clé ne prouve pas qu'on la LIT.

    La config réelle vaut 35 — exactement l'ancien défaut littéral. Un getter resté constant
    passerait donc les assertions ci-dessus. On surcharge la valeur et on exige qu'elle ressorte.
    """
    from engine.phase_handlers.shared_utils import get_max_base_size_hex

    state = copy.copy(gym_engine.game_state)
    state["config"] = dict(state["config"])
    state["config"]["game_rules"] = {**state["config"]["game_rules"], "max_base_size_hex": 7}
    assert get_max_base_size_hex(state) == 7


def test_les_deux_appelants_de_production_propagent_lexigence(gym_engine) -> None:
    """Motif « code testé mais jamais appelé » : le verrou doit tenir sur le VRAI chemin.

    Les deux seuls appelants — la prune du move et celle de l'observation — sont exercés sur
    l'état réel du moteur, privé de la seule clé `max_base_size_hex`. Chacun doit remonter
    l'erreur au lieu de se replier localement sur une borne de secours.
    """
    from engine.observation_builder import ObservationBuilder  # noqa: F401
    from engine.phase_handlers.movement_handlers import (
        _enemy_items_within_move_engagement_horizon,
    )
    from engine.phase_handlers.shared_utils import get_engagement_zone

    game_state = gym_engine.game_state
    broken = _state_without(game_state, drop="max_base_size_hex")
    units_cache = broken["units_cache"]

    unit = next(u for u in broken["units"] if str(u["id"]) in units_cache)
    entry = units_cache[str(unit["id"])]
    mover_player = int(entry["player"])
    # L'unité de référence doit avoir au moins un adverse dans le cache, sinon la boucle
    # d'entrées tournerait à vide et le verrou ne pèserait plus rien le jour où le getter
    # descendrait dans cette boucle.
    assert any(int(e["player"]) != mover_player for e in units_cache.values())

    # La section `game_rules` reste lisible : seule la clé manque, donc l'erreur ne peut venir
    # que du getter visé (et non du jumeau `get_engagement_zone`, qui doit passer).
    assert get_engagement_zone(broken) > 0

    with pytest.raises(ConfigurationError):
        _enemy_items_within_move_engagement_horizon(
            broken, unit, str(unit["id"]), mover_player,
            int(entry["col"]), int(entry["row"]), 6, units_cache,
        )

    # `enemy_of_player` désigne le camp à EXCLURE (`if int(entry["player"]) == enemy_of_player:
    # continue`), donc la production y passe le camp de l'unité de référence elle-même
    # (`observation_builder.py:1634`, `enemy_of_player=active_player`). Passer l'adverse
    # inverserait le filtre et ne reproduirait pas le chemin verrouillé.
    builder = gym_engine.obs_builder
    with pytest.raises(ConfigurationError):
        builder._engagement_relevant_entries(
            broken, entry, get_engagement_zone(broken), enemy_of_player=mover_player,
        )
