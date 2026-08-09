"""Les zones de déploiement survivent au restore d'un snapshot, y compris d'un snapshot ANCIEN.

CE QUE CE FICHIER VERROUILLE (défaut mesuré le 2026-08-05). Les zones de déploiement ont vécu
dans ``game_state["deployment_state"]["deployment_pools"]`` jusqu'à ce que le reset les publie à
la racine (``game_state["deployment_pools"]``), pour que la clause d'ingress 20.04 et l'ancre de
grille d'une unité hors table puissent les lire hors phase de déploiement.

Les états PvP sont persistés sur disque par les saves (``game_saves.SaveStore``) : un état capturé
AVANT ce déplacement ne porte pas la clé racine. Or ``build_game_state``
reconstruit l'état à partir des **seules** clés déclarées statiques (prises de l'engine vivant)
plus la copie mutable du snapshot. Tant que ``deployment_pools`` n'était pas déclarée statique,
elle disparaissait donc du state reconstruit, et le premier clic de déploiement levait
``Required key 'deployment_pools'`` (500 côté API, ``[DEPLOY] deployment_pools manquant`` côté UI).

La déclarer statique règle la reprise SANS code de migration : la valeur vient de l'engine vivant.
"""

from __future__ import annotations

import os

import pytest

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
#: Scénario à déploiement ACTIF : c'est le seul mode où la phase `deployment` existe, donc le
#: seul où un snapshot de cette phase peut être capturé.
SCENARIO = os.path.join(
    PROJECT_ROOT, "config/agents/ArmageddonAgent/scenarios/holdout_regular/scenario_bot-01.json"
)


@pytest.fixture(scope="module")
def engine():
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file=SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    eng.reset(seed=0)
    return eng


def test_the_engine_really_publishes_the_zones(engine):
    """VERT VACANT : sans zones à la racine, les deux tests suivants ne prouveraient rien."""
    pools = engine.game_state.get("deployment_pools")
    assert isinstance(pools, dict) and pools, (
        "aucune zone de déploiement à la racine du game_state — le reset ne les publie pas"
    )


def test_zones_are_not_copied_into_the_snapshot(engine):
    """Zone = donnée de scénario : elle est ré-attachée depuis l'engine, jamais recopiée.

    C'est la moitié « coût » : ~33 000 tuples immuables seraient deepcopiés à CHAQUE capture de
    phase. C'est aussi ce qui PROUVE que la clé est traitée comme statique — sans quoi le test
    suivant passerait pour la mauvaise raison (la valeur viendrait de la copie, pas du vivant).
    """
    from services.game_snapshots import GameSnapshotStore

    store = GameSnapshotStore()
    assert store.maybe_capture(engine), "aucun snapshot capturé — l'état n'est pas en début de phase"
    gs = engine.game_state
    snap = store._get(int(gs["turn"]), int(gs["current_player"]), str(gs["phase"]))
    assert "deployment_pools" not in snap["game_state"], (
        "les zones de déploiement sont recopiées dans le snapshot : elles ne sont pas déclarées "
        "statiques, donc un snapshot ANCIEN (sans la clé) les perdra au restore"
    )


def test_an_old_snapshot_without_the_root_key_still_restores_the_zones(engine):
    """Le cas de MIGRATION, CONSTRUIT et non espéré : un pickle d'avant le déplacement.

    On retire la clé racine de la partie capturée pour reproduire exactement ce que contient un
    snapshot pris quand les zones vivaient encore dans ``deployment_state``. Le state reconstruit
    doit malgré tout porter les zones, prises de l'engine vivant.
    """
    from services.game_snapshots import GameSnapshotStore

    store = GameSnapshotStore()
    gs = engine.game_state
    live_pools = gs["deployment_pools"]
    assert store.maybe_capture(engine), "aucun snapshot capturé"
    key = (int(gs["turn"]), int(gs["current_player"]), str(gs["phase"]))
    snap = store._get(*key)
    # Snapshot « ancien » : aucune clé racine, les zones ne vivaient que sous `deployment_state`.
    snap["game_state"].pop("deployment_pools", None)

    rebuilt = store.build_game_state(engine, *key)
    assert "deployment_pools" in rebuilt, (
        "les zones ont disparu du state reconstruit : la reprise d'une partie persistée avant le "
        "déplacement de la clé lèvera au premier déploiement"
    )
    assert rebuilt["deployment_pools"] == live_pools, (
        "les zones reconstruites ne sont pas celles de l'engine vivant"
    )
