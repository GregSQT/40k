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
trompeur pour la raison exposée dans la docstring de `get_max_base_size_hex` (seuil non scalé
par `inches_to_subhex`), qui reste la version canonique de cette explication.

Ce fichier verrouille les deux moitiés : la config de production porte la clé, ET l'appelant de
production propage l'exigence au lieu de se replier localement.

APPELANT UNIQUE DEPUIS `a0bb97eb` (« acceleration move preview »). La prune du move lisait elle
aussi la clé, pour PLAFONNER l'empreinte adverse (`min(span, max_base_size_hex)`) ; ce plafond a
été retiré sciemment — il rétrécissait un horizon dont la docstring promet qu'il ne peut se
tromper que par le HAUT, et élaguait donc des ennemis pertinents. La fenêtre d'observation reste
le seul lecteur (`observation_builder._engagement_relevant_entries`), et c'est elle que le test
d'appelant exerce. Cette section est le verrou de cette exclusivité : si un second lecteur
réapparaît, il doit être ajouté ici.
"""
from __future__ import annotations

import pytest

from shared.data_validation import ConfigurationError

from tests.unit.engine._config_helpers import TRAINING_SCENARIO, build_armageddon_engine


@pytest.fixture(scope="module")
def gym_engine():
    """Portée module : les 4 tests lisent le même état sans jamais le muter (tous copient)."""
    return build_armageddon_engine(
        seed=0, scenario_file=TRAINING_SCENARIO, training_n_envs=1,
    )


def _copied_layers(game_state):
    """Copie SUPERFICIELLE des trois dicts que ce fichier réécrit : état, config, game_rules.

    Superficielle et non `deepcopy` : `game_state` porte les caches du moteur (units_cache,
    squad_models…) qu'une copie profonde dupliquerait pour rien. Rend les trois niveaux pour
    que retirer une clé et en surcharger une passent par le MÊME chemin de copie.
    """
    state = dict(game_state)
    config = state["config"] = dict(state["config"])
    game_rules = config["game_rules"] = dict(config["game_rules"])
    return state, config, game_rules


def _state_without(game_state, *, drop: str):
    """État privé de `drop` : "config", "game_rules", ou une clé de `game_rules`."""
    state, config, game_rules = _copied_layers(game_state)
    target = {"config": state, "game_rules": config}.get(drop, game_rules)
    del target[drop]
    return state


def _state_with_rules(game_state, **overrides):
    """État dont les `game_rules` portent `overrides`."""
    state, _config, game_rules = _copied_layers(game_state)
    game_rules.update(overrides)
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

    state = _state_with_rules(gym_engine.game_state, max_base_size_hex=7)
    assert get_max_base_size_hex(state) == 7


def test_lappelant_de_production_propage_lexigence(gym_engine) -> None:
    """Motif « code testé mais jamais appelé » : le verrou doit tenir sur le VRAI chemin.

    Le seul appelant — la fenêtre d'observation — est exercé sur l'état réel du moteur, privé de
    la seule clé `max_base_size_hex` : il doit remonter l'erreur au lieu de se replier localement
    sur une borne de secours. La prune du move, elle, ne lit plus la clé (cf. l'en-tête) et le
    même état la traverse donc SANS erreur — c'est ce que cette exclusivité veut dire.
    """
    from engine.phase_handlers.movement_handlers import (
        _enemy_items_within_move_engagement_horizon,
    )
    from engine.phase_handlers.shared_utils import get_engagement_zone
    from engine.spatial_relations import enemy_entries_on_battlefield

    game_state = gym_engine.game_state
    broken = _state_without(game_state, drop="max_base_size_hex")
    units_cache = broken["units_cache"]

    # Unité DÉPLOYÉE : le scénario en laisse une en réserve (col/row à -1), depuis laquelle la
    # boucle d'ennemis de la prune ne mesurerait aucune distance réelle.
    unit = next(
        u for u in broken["units"]
        if str(u["id"]) in units_cache and int(units_cache[str(u["id"])]["col"]) >= 0
    )
    entry = units_cache[str(unit["id"])]
    mover_player = int(entry["player"])
    # L'unité de référence doit avoir au moins un adverse POSÉ, sinon la boucle d'entrées
    # tournerait à vide et le verrou ne pèserait plus rien le jour où le getter descendrait
    # dans cette boucle. Même énumération que la prune elle-même : lire le cache brut
    # compterait les unités en réserve, que `entries_on_battlefield` écarte.
    assert any(enemy_entries_on_battlefield(
        units_cache, mover_player, exclude_id=str(unit["id"]),
    ))

    # La section `game_rules` reste lisible : seule la clé manque, donc l'erreur ne peut venir
    # que du getter visé (et non du jumeau `get_engagement_zone`, qui doit passer).
    assert get_engagement_zone(broken) > 0

    # La prune du move traverse ses ennemis sans jamais lire la clé. Elle rend une liste (vide
    # ou non selon l'écart des camps au déploiement) : ce qui est verrouillé ici, c'est
    # l'ABSENCE d'erreur là où l'observation, elle, doit lever.
    assert isinstance(
        _enemy_items_within_move_engagement_horizon(
            broken, unit, str(unit["id"]), mover_player,
            int(entry["col"]), int(entry["row"]), 6, units_cache,
        ),
        list,
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
