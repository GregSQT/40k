"""Rampes pilotees PAR EPISODE — source unique de la conversion budget global -> budget par env.

POURQUOI CE MODULE EXISTE (V11 §0.57, 2026-08-02).
Un entrainement vectorise ouvre `n_envs` environnements, chacun dans son PROCESSUS. Le compteur
d'episodes que voit un environnement (`W40KEngine.episode_number`, `game_state["episode_number"]`,
`BotControlledEnv._episode_index`) ne compte QUE ses propres episodes : aucun d'eux n'observe le
compteur global, et chacun ne joue que `total_episodes / n_envs` episodes.

Rapporter ce compteur LOCAL a un budget GLOBAL fait donc avancer une rampe `n_envs` fois trop
lentement. Mesure du defaut sur le run `x1_long` (n_envs=48, total_episodes=200000) :
`s_deploy_active_share` valait 0.3040 a 78 477 episodes — soit `active_ratio_start` — la ou la
rampe 0.3 -> 0.8 attendait 0.496. Elle est restee figee a sa valeur de depart sur TOUT le run.

Le denominateur correct est `episodes_per_env`. Cette formule vivait en QUATRE exemplaires
manuscrits (deux moteur, un wrapper, un callback) ; deux d'entre eux etaient faux, et c'est
exactement ce qu'une formule recopiee produit. Tout consommateur passe desormais par ici.

`n_envs` doit etre celui du RUN, pas celui declare par le profil : `--step` / `--replay` forcent un
environnement unique alors que le JSON en annonce 48 (`ai/train.py::_resolve_n_envs_for_step_logging`).
C'est `ai/train.py` qui resout la valeur une fois pour toutes et la propage.
"""

from __future__ import annotations

from typing import Any

from shared.data_validation import require_positive_int


def episodes_per_env(total_episodes: Any, n_envs: Any) -> int:
    """Nombre d'episodes qu'UN environnement joue quand le run en vise `total_episodes` au total."""
    total = require_positive_int(total_episodes, "total_episodes")
    envs = require_positive_int(n_envs, "n_envs")
    return (total + envs - 1) // envs


def ramp_progress(episode_index: int, total_episodes: Any, n_envs: Any) -> float:
    """Progression [0.0, 1.0] d'une rampe par-episode, dans l'echelle du compteur LOCAL.

    `episode_index` est un index a base 0 dans les episodes de CET environnement. Le premier
    episode rend 0.0 (valeur de depart de la rampe), le dernier rend 1.0.
    """
    denominator = max(1, episodes_per_env(total_episodes, n_envs) - 1)
    return min(1.0, max(0.0, float(max(0, episode_index)) / float(denominator)))
