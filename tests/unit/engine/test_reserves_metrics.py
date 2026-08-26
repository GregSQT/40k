"""Tests — métriques d'utilisation des réserves stratégiques dans episode_tactical_data.

Cinq mesures × DEUX CAMPS (`_agent` / `_opponent`), chantier « reserves metrics » (2026-08-08),
étendu par camp et par cause le 2026-08-11 :
  reserves_placed_*                  — unités mises en réserve (20.01)
  reserves_deployed_*                — arrivées depuis réserve (ingress move, 20.04)
  reserves_destroyed_turn3_*         — détruites fin du 3e round faute d'être arrivées (20.04)
  reserves_ingress_declined_*        — un slot d'arrivée était OUVERT, l'unité est restée
  reserves_ingress_no_destination_*  — le pool d'ingress était VIDE : aucune décision possible

POURQUOI LES DEUX DERNIERS. « Détruite en réserve » confondait une DÉCISION (refuser d'arriver)
et une impasse géométrique (bande de 6" du bord, > 8" de tout ennemi, zone adverse fermée avant
le 3e round). Une pénalité indexée sur la destruction seule punirait un choix qui n'a jamais été
proposé à l'agent.

POURQUOI PAR CAMP. Les trois premiers ne comptaient que le joueur contrôlé — `destroyed_turn3`
était même documenté « tous joueurs » alors que son site d'écriture filtrait. Le bot n'était donc
mesuré nulle part, et son code promet pourtant qu'il arrive dès qu'un slot s'ouvre
(`env_wrappers._select_bot_move_action` : pool d'ingress vide → WAIT, sinon il pose).

STRUCTURE DES TESTS

1. EXISTENCE — les douze clés sont toujours présentes dans tactical_data, même quand
   aucune réserve n'est utilisée (épisode fixed, sans déploiement actif).

2. VOLUME — sur un épisode avec réserves déclarées des deux côtés,
   reserves_placed_agent > 0.

3. COHÉRENCE — deployed <= placed des DEUX côtés, et une occasion déclinée suppose une
   occasion offerte.

3bis. CAUSE — un épisode où l'on refuse SYSTÉMATIQUEMENT toute arrivée : la réserve est
   détruite (20.04) et c'est `declined` qui l'explique. La situation est construite, pas
   attendue d'une graine — sur le fixture partagé, les deux camps arrivent d'eux-mêmes.

4. VERROU — on met le défaut (absence des clés), on vérifie que les tests deviennent
   ROUGES, puis on rétablit — prouvant que les tests ne sont pas vacants.

5. CONTRAT MOTEUR → TRACKER — le tactical_data d'un épisode réel traverse le vrai
   `log_tactical_metrics` sans lever, et les trois courbes `reserves/*` portent bien les
   compteurs du moteur. C'est ici, et nulle part ailleurs, que les deux jambes du contrat
   se rejoignent : les tests de `tests/unit/ai/` partent tous de fixtures écrites à la main.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARMAGEDDON_SCENARIOS = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
)

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

#: Les cinq mesures, déclinées par camp. Source unique des boucles de ce fichier : une mesure
#: ajoutée ici sans être alimentée par le moteur fait rougir le test d'existence.
_MESURES = (
    "reserves_placed",
    "reserves_deployed",
    "reserves_destroyed_turn3",
    "reserves_ingress_offers",
    "reserves_ingress_declined",
    "reserves_ingress_no_destination",
)
_CLES = tuple(f"{m}_{camp}" for m in _MESURES for camp in ("agent", "opponent"))


@pytest.mark.parametrize("seed", _SEEDS)
def test_reserves_metric_keys_always_present(seed: int) -> None:
    """Les dix clés existent dans tactical_data, même sur l'épisode reserves_fixture1."""
    td = _cached_play(seed)
    for cle in _CLES:
        assert cle in td, f"clé {cle} absente de tactical_data"


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
@pytest.mark.parametrize("camp", ["agent", "opponent"])
def test_reserves_coherence(seed: int, camp: str) -> None:
    """Invariants de cohérence, VÉRIFIÉS DES DEUX CÔTÉS.

    Le camp `opponent` n'est pas un doublon décoratif : c'est la jambe qui n'existait pas, et
    c'est elle qui permet de vérifier ce que le code du bot promet.
    """
    td = _cached_play(seed)
    placed = int(td[f"reserves_placed_{camp}"])
    deployed = int(td[f"reserves_deployed_{camp}"])
    destroyed = int(td[f"reserves_destroyed_turn3_{camp}"])

    assert deployed <= placed, (
        f"reserves_deployed_{camp} ({deployed}) > reserves_placed_{camp} ({placed}) — "
        "impossible de déployer plus que ce qui a été placé"
    )
    assert destroyed >= 0, f"reserves_destroyed_turn3_{camp} négatif : {destroyed}"
    # La somme deployed + destroyed peut être <= placed si des unités sont en réserve
    # ET encore en vie à la fin (partie terminée avant la fin du tour 3).
    assert deployed + destroyed <= placed, (
        f"deployed ({deployed}) + destroyed ({destroyed}) > placed ({placed}) — "
        "des unités comptées deux fois ou une unité déplacée hors réserve sans être comptée"
    )


def _play_always_declining_ingress(seed: int) -> Dict[str, Any]:
    """Joue un épisode en REFUSANT systématiquement toute arrivée de réserve.

    La situation est CONSTRUITE, pas espérée d'une graine : sur le fixture partagé, les deux
    camps arrivent d'eux-mêmes et aucune réserve n'est jamais détruite, si bien que le test de
    cause ne faisait que `skip` — un vert vacant déguisé.

    Reconnaître le moment : en phase de mouvement, seule une escouade EN RÉSERVES ouvre des
    slots de mise en place (`DEPLOY_SLOTS`). Une escouade posée n'a pas de candidat d'ingress,
    une escouade en réserves n'a pas de cellule de mouvement — les deux familles ne peuvent pas
    se confondre (`ActionDecoder.get_squad_action_mask_and_eligible_units`). `WAIT` est alors
    « rester en réserves ce tour-ci », un choix légal jusqu'à la fin du 3e round (20.03/20.04).
    """
    from engine.macro_intents import DEPLOY_SLOTS

    engine = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file=_FIXTURE_RESERVES,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    engine.reset(seed=seed)
    rng = np.random.default_rng(seed)
    deploy_slots = set(DEPLOY_SLOTS)
    info: Dict[str, Any] = {}
    for _ in range(5000):
        legal = np.flatnonzero(engine.get_action_mask())
        if legal.size == 0:
            action = SQUAD_ACTION_WAIT
        elif (
            engine.game_state.get("phase") == "move"
            and deploy_slots.intersection(legal.tolist())
            and SQUAD_ACTION_WAIT in legal
        ):
            action = SQUAD_ACTION_WAIT
        else:
            action = int(rng.choice(legal))
        _obs, _reward, terminated, truncated, info = engine.step(action)
        if terminated or truncated:
            break
    assert "tactical_data" in info, "épisode non terminé — pas de tactical_data"
    return info["tactical_data"]


def _penalty_calculator(enabled: Any = True, montant: Any = -25.0) -> Any:
    """RewardCalculator sans __init__ : seuls la config et le barème de réserves sont utiles."""
    from engine.reward_calculator import RewardCalculator

    calc = RewardCalculator.__new__(RewardCalculator)
    calc.config = {"controlled_agent": "TestAgent"}  # type: ignore[assignment]
    calc.rewards_config = {  # type: ignore[assignment]
        "TestAgent": {
            "reserves_shaping": {
                "enabled": enabled,
                "declined_arrival_lost_penalty": montant,
            }
        }
    }
    return calc


def test_the_wasted_reserve_penalty_only_charges_what_was_chosen() -> None:
    """Barème de la réserve gaspillée : proportionnel, négatif, débranchable, jamais gratuit.

    Le compte à zéro (aucune escouade détruite APRÈS refus) ne doit rien coûter : c'est le cas
    d'une réserve perdue faute de destination légale, et la facturer punirait un choix qui n'a
    pas existé.
    """
    calc = _penalty_calculator()
    assert calc.wasted_reserve_penalty(0) == 0.0
    assert calc.wasted_reserve_penalty(-1) == 0.0, "un compte négatif ne récompense pas"
    assert calc.wasted_reserve_penalty(1) == pytest.approx(-25.0)
    assert calc.wasted_reserve_penalty(3) == pytest.approx(-75.0), "coût PAR escouade"

    assert _penalty_calculator(enabled=False).wasted_reserve_penalty(3) == 0.0

    with pytest.raises(TypeError, match="doit etre un booleen"):
        _penalty_calculator(enabled="false").wasted_reserve_penalty(1)
    with pytest.raises(ValueError, match="doit etre negatif"):
        _penalty_calculator(montant=25.0).wasted_reserve_penalty(1)
    with pytest.raises(TypeError, match="doit etre un nombre"):
        _penalty_calculator(montant="-25").wasted_reserve_penalty(1)


def test_the_shipped_config_declares_the_reserves_penalty() -> None:
    """La config LIVRÉE porte le bloc, et son montant est un coût.

    Sa VALEUR est un choix de campagne, non verrouillée ici ; son SIGNE ne l'est pas : un
    montant positif récompenserait la perte d'une escouade restée hors table.
    """
    import json

    path = PROJECT_ROOT / "config/agents/ArmageddonAgent/ArmageddonAgent_rewards_config.json"
    shaping = json.loads(path.read_text(encoding="utf-8"))["ArmageddonAgent"]["reserves_shaping"]
    assert isinstance(shaping.get("enabled"), bool)
    montant = shaping.get("declined_arrival_lost_penalty")
    assert isinstance(montant, (int, float)) and not isinstance(montant, bool)
    assert montant <= 0.0, f"barème positif pour une réserve gaspillée : {montant}"


def test_a_declined_and_destroyed_reserve_is_actually_charged() -> None:
    """La pénalité ATTEINT la récompense de l'épisode, elle ne reste pas en attente.

    Le compte est posé par `fight_handlers` à la destruction (20.04) et facturé au step suivant,
    par le même chemin que le shaping zone-intent. S'il n'était jamais poppé — cas vécu sur
    `_pending_zone_shaping` — rien ne rougirait côté compteurs : ils sont, eux, corrects.

    Le seuil est un MAJORANT (`<=`) : `penalties` porte aussi les coûts d'action ordinaires, tous
    négatifs. Ce qui est vérifié, c'est qu'il y a au moins de quoi payer les escouades gaspillées.
    """
    td = _play_always_declining_ingress(seed=0)

    wasted = int(td["reserves_destroyed_turn3_agent"])
    assert wasted > 0, "aucune réserve gaspillée : le test ne mesure rien"
    assert int(td["reserves_ingress_declined_agent"]) > 0, "gaspillage sans refus enregistré"

    penalties = float(td["reward_breakdown"]["penalties"])
    assert penalties <= -25.0 * wasted, (
        f"penalties={penalties} pour {wasted} escouade(s) gaspillée(s) à -25.0 l'unité — "
        "la pénalité n'a pas été facturée"
    )


@pytest.mark.parametrize("camp", ["agent", "opponent"])
def test_declining_every_arrival_destroys_the_reserve_and_names_the_cause(camp: str) -> None:
    """Refuser toutes ses arrivées : la réserve MEURT (20.04) et la cause est « déclinée ».

    C'est le verrou de la nouvelle mesure, et il porte sur les DEUX camps — ce que rien ne
    faisait avant, puisque les compteurs filtraient sur le joueur contrôlé. L'environnement nu
    (sans wrapper de bot) fait jouer les deux sièges par le même masque : la politique de refus
    s'applique donc symétriquement, et les deux jambes du compteur doivent monter. Remettre le
    filtre `player == controlled` sur l'un des trois sites d'écriture rend ce test rouge côté
    `opponent`.

    Chaîne complète vérifiée sur un seul épisode : des réserves placées, aucune arrivée, des
    occasions offertes, autant de refus, et la destruction de fin de 3e round qui s'ensuit.
    """
    td = _play_always_declining_ingress(seed=0)

    assert int(td[f"reserves_placed_{camp}"]) > 0, f"aucune réserve côté {camp} : rien à mesurer"
    assert int(td[f"reserves_deployed_{camp}"]) == 0, (
        f"le camp {camp} est arrivé alors que la politique décline toujours — le test ne mesure "
        "pas ce qu'il croit"
    )
    assert int(td[f"reserves_ingress_offers_{camp}"]) > 0, (
        "aucune occasion offerte : la destruction ne prouverait rien sur la DÉCISION"
    )
    assert int(td[f"reserves_ingress_declined_{camp}"]) > 0, (
        "des occasions offertes, aucune déclinée, alors que la politique refuse tout"
    )
    assert int(td[f"reserves_destroyed_turn3_{camp}"]) > 0, (
        "réserve jamais arrivée et pourtant non détruite à la fin du 3e round (20.04)"
    )


@pytest.mark.parametrize("seed", _SEEDS)
def test_ingress_opportunities_are_recorded_at_all(seed: int) -> None:
    """Le point de mesure des occasions d'ingress est ATTEINT sur un fixture à réserves.

    Garde « vert vacant », et elle porte sur `offers` — pas sur `declined`. Un `declined` à zéro
    est un résultat NORMAL (mesuré : sur la graine 1, les deux camps arrivent dès leur première
    occasion), donc l'exiger positif ferait rougir le test sur une partie bien jouée. C'est
    l'absence d'OFFRE qui, elle, ne peut pas s'expliquer : une unité en réserve entre dans le
    pool d'activation du mouvement à chaque round ≥ 2, et le masque construit alors ses
    candidats d'ingress.
    """
    td = _cached_play(seed)
    offers = sum(int(td[f"reserves_ingress_offers_{camp}"]) for camp in ("agent", "opponent"))
    declined = sum(int(td[f"reserves_ingress_declined_{camp}"]) for camp in ("agent", "opponent"))
    no_dest = sum(
        int(td[f"reserves_ingress_no_destination_{camp}"]) for camp in ("agent", "opponent")
    )
    assert offers + no_dest > 0, (
        "aucune occasion d'ingress enregistrée sur un fixture à réserves des deux côtés — "
        "le hook de `ingress_slot_candidates` n'est pas atteint (code jamais appelé)"
    )
    assert declined <= offers, (
        f"declined ({declined}) > offers ({offers}) — une arrivée déclinée sans occasion offerte"
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
    """Les douze courbes `reserves/*` portent les compteurs du MOTEUR, pas des valeurs saisies.

    Sans ce contrôle, le contrat avait deux jambes qui ne se rejoignaient nulle part : les
    tests ci-dessus vérifient les compteurs sans jamais toucher le tracker, et
    `tests/unit/ai/test_metrics_single_writer.py` vérifie l'appariement tag ↔ clé sur des
    valeurs écrites à la main. Si le moteur cessait d'alimenter `_reserves_placed`, la
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

    for cle in _CLES:
        tag = "reserves/" + cle[len("reserves_"):]
        assert written[tag] == float(tactical[cle]), tag
