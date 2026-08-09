"""Tests — métriques d'utilisation des réserves stratégiques dans episode_tactical_data.

Trois compteurs ajoutés par le chantier « reserves metrics » (2026-08-08) :
  reserves_placed_agent     — unités mises en réserve par l'agent (joueur 1)
  reserves_deployed_agent   — arrivées depuis réserve (agent)
  reserves_destroyed_turn3  — détruites par 20.04 fin de tour 3 (tous joueurs)

STRUCTURE DES TESTS

1. EXISTENCE — les trois clés sont toujours présentes dans tactical_data, même quand
   aucune réserve n'est utilisée (épisode fixed, sans déploiement actif).

2. VOLUME — sur un épisode avec réserves déclarées des deux côtés,
   reserves_placed_agent > 0.

3. COHÉRENCE — reserves_deployed_agent <= reserves_placed_agent
   (on ne peut pas déployer plus qu'on n'a placé).

4. VERROU — on met le défaut (absence des clés), on vérifie que les tests deviennent
   ROUGES, puis on rétablit — prouvant que les tests ne sont pas vacants.

5. CONTRAT MOTEUR → TRACKER — le tactical_data d'un épisode réel traverse le vrai
   `log_tactical_metrics` sans lever, et les trois courbes `reserves/*` portent bien les
   compteurs du moteur. C'est ici, et nulle part ailleurs, que les deux jambes du contrat
   se rejoignent : les tests de `tests/unit/ai/` partent tous de fixtures écrites à la main.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARMAGEDDON_SCENARIOS = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
)

sys.path.insert(0, str(PROJECT_ROOT))

from ai.metrics_tracker import W40KMetricsTracker  # noqa: E402
from ai.unit_registry import UnitRegistry  # noqa: E402
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT  # noqa: E402
from engine.w40k_core import W40KEngine  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Harnais commun
# ──────────────────────────────────────────────────────────────────────────────

_FIXTURE_RESERVES = str(ARMAGEDDON_SCENARIOS / "reserves_full_episode_fixture1.json")

_SEEDS = (0, 1, 2)


def _play(scenario_file: str, seed: int) -> Dict[str, Any]:
    """Joue un épisode complet en actions légales tirées au sort ; rend tactical_data."""
    engine = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file=scenario_file,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    engine.reset(seed=seed)
    rng = np.random.default_rng(seed)
    info: Dict[str, Any] = {}
    for _ in range(5000):
        legal = np.flatnonzero(engine.get_action_mask())
        action = int(rng.choice(legal)) if legal.size else SQUAD_ACTION_WAIT
        _obs, _reward, terminated, truncated, info = engine.step(action)
        if terminated or truncated:
            break
    assert "tactical_data" in info, "épisode non terminé — pas de tactical_data"
    return info["tactical_data"]


# Épisodes mémoïsés par graine. Chaque `_play` rejoue une partie entière (9 à 50 s selon la
# graine) et les tests ci-dessous relisent tous le MÊME épisode par graine.
#
# PORTÉE RÉELLE DU GAIN, mesurée — le cache est module-scope, donc PAR PROCESSUS. En série il
# ramène le fichier de 9 rejouages à 3 (40 s CPU). Sous `-n 8 --dist worksteal`, la commande de
# vérification du dépôt, xdist distribue les items un par un : 8 des 9 tests rejouent leur
# épisode dans leur propre worker (185 s CPU pour 30 s d'horloge). Ne pas lire ce cache comme
# une garantie de coût — ce fichier reste le plus lourd de `tests/unit/engine/`.
#
# Contrat de partage, identique à `test_episode_charge_counters._cached_play` : les appelants
# traitent le dict rendu en LECTURE SEULE — un test qui le mute contaminerait les suivants.
# Ceux d'ici ne font que lire. À la différence du jumeau, ce cache ne retient PAS les moteurs
# (mesuré : 8 Ko par entrée, aucun `W40KEngine` atteignable).
_EPISODES: Dict[int, Dict[str, Any]] = {}


def _cached_play(seed: int) -> Dict[str, Any]:
    """`_play` mémoïsé sur la graine, pour le fixture à réserves."""
    if seed not in _EPISODES:
        _EPISODES[seed] = _play(_FIXTURE_RESERVES, seed)
    return _EPISODES[seed]


def _seed_with_reserves() -> int | None:
    """Première graine où l'agent place au moins une unité en réserve, `None` si aucune.

    La positivité par graine n'est pas garantie : deux tests la cherchent, et une seule
    écriture du prédicat les suit le jour où le fixture change.
    """
    return next(
        (s for s in _SEEDS if int(_cached_play(s)["reserves_placed_agent"]) > 0), None
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. Existence des clés — toujours présentes
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", _SEEDS)
def test_reserves_metric_keys_always_present(seed: int) -> None:
    """Les trois clés existent dans tactical_data, même sur l'épisode reserves_fixture1."""
    td = _cached_play(seed)
    assert "reserves_placed_agent" in td, "clé reserves_placed_agent absente de tactical_data"
    assert "reserves_deployed_agent" in td, "clé reserves_deployed_agent absente de tactical_data"
    assert "reserves_destroyed_turn3" in td, "clé reserves_destroyed_turn3 absente de tactical_data"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Volume — des réserves sont effectivement utilisées
# ──────────────────────────────────────────────────────────────────────────────

def test_reserves_placed_agent_is_positive_on_reserves_fixture() -> None:
    """Sur le fixture à réserves des DEUX côtés, l'agent place au moins une unité en réserve.

    VERROU : si la clé reste toujours à 0, ce test devient rouge — c'est le test
    « vert vacant » guard qui prouve que le compteur est réellement incrémenté.
    """
    assert _seed_with_reserves() is not None, (
        "reserves_placed_agent == 0 sur toutes les graines — "
        "le compteur n'est jamais incrémenté (vert vacant)"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 3. Cohérence — deployed <= placed, destroyed >= 0
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", _SEEDS)
def test_reserves_coherence(seed: int) -> None:
    """Invariants de cohérence entre les trois compteurs."""
    td = _cached_play(seed)
    placed = int(td["reserves_placed_agent"])
    deployed = int(td["reserves_deployed_agent"])
    destroyed = int(td["reserves_destroyed_turn3"])

    assert deployed <= placed, (
        f"reserves_deployed_agent ({deployed}) > reserves_placed_agent ({placed}) — "
        "impossible de déployer plus que ce qui a été placé"
    )
    assert destroyed >= 0, f"reserves_destroyed_turn3 négatif : {destroyed}"
    # La somme deployed + destroyed peut être <= placed si des unités sont en réserve
    # ET encore en vie à la fin (partie terminée avant la fin du tour 3).
    assert deployed + destroyed <= placed, (
        f"deployed ({deployed}) + destroyed ({destroyed}) > placed ({placed}) — "
        "des unités comptées deux fois ou une unité déplacée hors réserve sans être comptée"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 5. Contrat moteur → tracker — les deux jambes se rejoignent
# ──────────────────────────────────────────────────────────────────────────────

def _recorded_scalars(tactical: Dict[str, Any], tmp_path: Any) -> Dict[str, float]:
    """Passe `tactical` au VRAI `log_tactical_metrics` et rend les scalaires écrits."""
    tracker = W40KMetricsTracker(
        "ArmageddonAgent", log_dir=str(tmp_path), show_banner=False,
        perf_window=1, perf_window_fast=1,
    )
    written: Dict[str, float] = {}

    class _Writer:
        def add_scalar(self, key: str, value: float, step: int, /) -> None:
            written[key] = value

        def add_custom_scalars(self, layout: Dict[str, Any], /) -> None:
            pass

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    # `__init__` a ouvert un vrai SummaryWriter (fichier d'événements + thread d'écriture) dont
    # ce test n'a que faire : on le ferme AVANT de le remplacer par la doublure, sinon chaque
    # appel laisse derrière lui un descripteur et un thread vivants.
    tracker.writer.close()
    tracker.writer = _Writer()
    tracker.episode_count = 1
    tracker.log_tactical_metrics(tactical)
    return written


def test_the_engine_feeds_every_key_the_tracker_reads(tmp_path: Any) -> None:
    """Le tactical_data d'un épisode RÉEL traverse `log_tactical_metrics` sans lever.

    C'est le contrat moteur → tracker, EXÉCUTÉ au lieu d'être décrit (le régime de lecture
    stricte est expliqué là où il vit, `W40KMetricsTracker.log_tactical_metrics`). Rien ne
    garantissait que le moteur fournisse toutes les clés exigées, et une clé manquante ne se
    découvrait qu'en cours d'entraînement. Les fixtures de `tests/unit/ai/` sont écrites à la
    main et ne prouvent rien de ce côté-là — elles vérifient ce que le tracker FAIT de ses
    clés, pas que le moteur les LUI donne.

    Ce contrôle remplace toute liste de clés exigées maintenue à la main : la source de vérité
    est le code du tracker lui-même, et il ne peut pas dériver de lui-même. Aucun COMPTE de
    clés n'est écrit ici non plus — un nombre recopié serait exactement la liste manuelle que
    ce test existe pour supprimer.

    DEUX clés ne sont lues que derrière une garde MÉTIER, et sortiraient donc de la couverture
    sans que rien ne le signale si l'épisode changeait de forme :
      - `hits`, sous `if shots_fired > 0` ;
      - `victory_points_controlled_episode`, sous `if samples and opp_samples`.
    Les assertions ci-dessous exigent que ces deux gardes soient OUVERTES sur l'épisode observé.
    Elles ne testent pas le moteur : elles refusent que ce contrôle rétrécisse en silence. Si
    l'une devient rouge, c'est l'épisode de référence qu'il faut choisir autrement — pas
    l'assertion qu'il faut retirer.
    """
    tactical = _cached_play(_SEEDS[0])

    assert int(tactical["shots_fired"]) > 0, (
        "aucun tir sur cet épisode : `hits` n'est plus lu, la couverture a fondu sans rougir"
    )
    assert tactical["controlled_objective_samples"] and tactical["opponent_objective_samples"], (
        "aucun échantillon d'objectif : `victory_points_controlled_episode` n'est plus lu"
    )

    _recorded_scalars(tactical, tmp_path)


def test_the_reserves_curves_carry_the_engine_counters(tmp_path: Any) -> None:
    """Les trois courbes `reserves/*` portent les compteurs du MOTEUR, pas des valeurs saisies.

    Sans ce contrôle, le contrat avait deux jambes qui ne se rejoignaient nulle part : les
    tests ci-dessus vérifient les compteurs sans jamais toucher le tracker, et
    `tests/unit/ai/test_metrics_single_writer.py` vérifie l'appariement tag ↔ clé sur des
    valeurs écrites à la main. Si le moteur cessait d'alimenter `_reserves_placed_agent`, la
    courbe passait à 0 constant sans qu'aucun des deux ne rougisse.

    CE QU'IL NE DISCRIMINE PAS : sur ce fixture, `placed == deployed` et `destroyed == 0`, donc
    ni un échange de ces deux tags ni la valeur du troisième ne se voient ici. C'est
    `test_metrics_single_writer.py::test_each_reserves_curve_carries_its_own_tactical_key`, dont
    la fixture porte trois valeurs distinctes, qui les attrape. La garde `placed > 0` ci-dessous
    est ce qui empêche les trois égalités de dégénérer en 0 == 0.
    """
    seed = _seed_with_reserves()
    assert seed is not None, (
        "aucune graine ne place de réserve — les trois égalités compareraient 0 à 0"
    )
    tactical = _cached_play(seed)

    written = _recorded_scalars(tactical, tmp_path)

    assert written["reserves/placed_agent"] == float(tactical["reserves_placed_agent"])
    assert written["reserves/deployed_agent"] == float(tactical["reserves_deployed_agent"])
    assert written["reserves/destroyed_turn3"] == float(tactical["reserves_destroyed_turn3"])
