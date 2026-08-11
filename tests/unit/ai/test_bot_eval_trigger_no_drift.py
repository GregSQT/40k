"""Le déclencheur d'évaluation par ÉPISODES ne doit pas accumuler de dépassement.

`setup_callbacks` (ai/train.py) promet `total_episodes // bot_eval_freq` évaluations : c'est sur
ce compte qu'il refuse au démarrage une fenêtre `robust_window` inatteignable. Le déclencheur doit
donc la tenir.

Il ne la tenait pas. L'entraînement vectorisé fait sauter le compteur d'épisodes — plusieurs
`dones` au même pas —, donc une éval se déclenche à `k*eval_freq + depassement`. Le repère était
remis au compteur COURANT, ce qui reportait ce dépassement d'une éval à la suivante : le décalage
se cumulait et la DERNIÈRE éval tombait au-delà de `total_episodes`, où le run est déjà arrêté.

Une éval de moins que promis, TOUJOURS la dernière. Sans conséquence sur un run calibré large
(19 points au lieu de 20), fatale sur un run calibré au ras de sa fenêtre : x1_long ramené à
50 000 épisodes avec `bot_eval_freq` 10 000 promettait 5 points pour une fenêtre de 5, et n'en
produisait que 4 — donc AUCUN best model robuste, en silence, puisque la garde du démarrage, elle,
en comptait 5. (Sa fenêtre est passée à 3 le même jour, pour une raison distincte : 5 points pour
une fenêtre de 5 ne laissent qu'une position, donc aucune sélection réelle. Les deux corrections
sont indépendantes — celle-ci rend au run le point de mesure qu'il perdait, quelle que soit sa
fenêtre.)

Le test CONSTRUIT la suite de compteurs qu'il observe (sauts irréguliers imposés), il ne l'espère
d'aucun tirage.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, cast

from ai.training_callbacks import BotEvaluationCallback


def _callback(eval_freq: int, initial_marker: int = 0) -> BotEvaluationCallback:
    """Instance réduite aux attributs que `_on_step` lit réellement.

    Aucun défaut caché : si le déclencheur se met à lire autre chose, le test tombe en
    AttributeError plutôt que de passer sur une valeur inventée.
    """
    callback = BotEvaluationCallback.__new__(BotEvaluationCallback)
    callback.use_episode_freq = True
    callback.eval_freq = eval_freq
    callback.last_eval_episode = initial_marker
    callback.eval_count = 0
    callback.num_timesteps = 0
    callback.async_eval_enabled = False
    callback.early_stopping_patience = 0
    callback.should_stop_early = False
    callback.metrics_tracker = cast(Any, SimpleNamespace(episode_count=0))
    return callback


def _run(callback: BotEvaluationCallback, episode_counts: List[int]) -> List[int]:
    """Rejoue une suite de compteurs d'épisodes et rend les marqueurs des évals déclenchées."""
    markers: List[int] = []
    callback._evaluate_against_bots = lambda marker: markers.append(int(marker))  # type: ignore[method-assign]
    callback._apply_eval_results = lambda results, marker: None  # type: ignore[method-assign]
    callback._blocking_eval_timer = _NullTimer  # type: ignore[method-assign]
    for count in episode_counts:
        callback.metrics_tracker.episode_count = count
        callback._on_step()
    return markers


class _NullTimer:
    """Substitut du chronomètre de blocage : il n'y a pas d'éval réelle à mesurer ici."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> bool:
        return False


def test_les_evals_promises_ont_toutes_lieu_malgre_les_sauts_du_compteur():
    """x1_long : 50 000 épisodes, `bot_eval_freq` 10 000 → les CINQ évals de la fenêtre robuste.

    Le compteur saute de 7 épisodes par pas : chaque seuil est franchi avec un dépassement, et
    c'est ce dépassement que l'ancienne remise à zéro du repère cumulait. Le run s'arrête au
    premier pas où le compteur atteint 50 000 (`EpisodeTerminationCallback`), donc la suite
    rejouée s'arrête là aussi — une 5ᵉ éval qui n'arriverait qu'après n'aurait jamais lieu.
    """
    callback = _callback(eval_freq=10_000)
    counts = list(range(7, 50_007, 7))
    assert counts[-1] >= 50_000 > counts[-2], "la suite s'arrete au 1er pas qui atteint 50 000"

    markers = _run(callback, counts)

    assert len(markers) == 5, f"5 evals promises par 50000 // 10000, obtenues : {markers}"
    # Chaque éval tombe dans le pas qui suit son seuil, sans jamais le dépasser d'un cran.
    for index, marker in enumerate(markers, start=1):
        seuil = index * 10_000
        assert seuil <= marker < seuil + 7, f"eval {index} a {marker}, seuil {seuil}"


def test_une_reprise_de_run_garde_sa_cadence_depuis_son_repere():
    """`initial_episode_marker` : la cadence part du repère repris, pas de zéro."""
    callback = _callback(eval_freq=1000, initial_marker=2500)

    markers = _run(callback, list(range(2500, 6001, 3)))

    assert markers == [3502, 4501, 5500], markers


def test_un_compteur_qui_saute_plusieurs_seuils_ne_declenche_qu_une_eval():
    """Un saut de 3 périodes ne rattrape pas les évals manquées — mais ne décale pas la suite.

    Rejouer les seuils sautés évaluerait trois fois le MÊME modèle. Le repère, lui, avance des
    trois périodes : la prochaine éval reste sur la grille.
    """
    callback = _callback(eval_freq=1000)

    markers = _run(callback, [999, 3200, 3999, 4001, 5001])

    assert markers == [3200, 4001, 5001], markers
