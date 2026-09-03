"""Verrou — l'enveloppe posee sur `logger.dump` est retiree, et ne capture que les updates PPO.

`MetricsCollectionCallback._on_training_start` enveloppe `logger.dump` pour lire les metriques PPO
avant que SB3 ne vide `name_to_value`. Trois defauts vivaient sur ce chemin.

1. AUCUN RETRAIT. SB3 appaire `on_training_start` et `on_training_end` autour de CHAQUE `learn()`
   (`sb3_contrib/ppo_mask/ppo_mask.py`, lignes 448 et 467), et la boucle budgetee en episodes de
   `train_with_scenario_rotation` enchaine un `learn()` par tranche de quatre updates. Sans
   `_on_training_end`, chaque tranche ajoutait une couche. Sur un run NEUF le defaut ne se voyait
   pas — SB3 reconstruit son logger a chaque `learn()`, l'enveloppe morte partait avec lui. Sur une
   REPRISE, `ai/train.py` pose le logger via `model.set_logger`, SB3 ne le reconstruit plus et les
   couches s'accumulaient. Mesure du run P1 du 2026-09-03 : 41 756 points sur
   `training_critical/clip_fraction` pour 575 updates PPO reels, contre 1 063 points pour 1 063
   updates sur un run neuf comparable. La fenetre de vingt valeurs de
   `W40KMetricsTracker._calculate_smoothed_metric` couvrait alors vingt copies du meme update : les
   quatre courbes de sante PPO de `00_critical` n'etaient plus lissees du tout.

2. CAPTURE A CHAQUE EPISODE. La garde etait `if ntv:`, or `_handle_episode_end` appelle
   `logger.dump` a chaque fin d'episode avec les seules cles `game_critical/*`. Chaque episode
   declenchait donc une capture complete, norme du gradient comprise, pour un dump ne portant aucun
   update. Mesure sur le run neuf du 2026-08-29, ou aucune couche ne s'empilait : 101 415 points
   sur `training_diagnostic/entropy_coef` pour 100 000 episodes et 1 063 updates.

3. ABSCISSE DECALEE. `_tracker.step_count` etait pose APRES `log_training_metrics`, qui ecrit
   chacun de ses scalaires a cette abscisse : chaque update partait au pas du dump precedent.

Les courbes de jeu (`d_win_rate`, `e_episode_reward_smooth`, `03_selfplay/*`) ne passent pas par ce
chemin et n'ont jamais ete touchees.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest


#: Un dump d'update PPO : ce que `patched_ppo.train()` enregistre avant de vider `name_to_value`.
_PPO_DUMP: Dict[str, Any] = {
    "train/clip_fraction": 0.074,
    "train/approx_kl": 0.0087,
    "train/explained_variance": 0.884,
    "train/entropy_loss": -1.34,
}

#: Un dump de fin d'episode : ce que `_handle_episode_end` enregistre. Aucune cle PPO.
_EPISODE_DUMP: Dict[str, Any] = {
    "game_critical/units_killed_vs_lost_ratio": 1.5,
    "game_critical/invalid_action_rate": 0.0,
}


class _FakeLogger:
    """Logger SB3 double : `dump` compte ses appels, `name_to_value` porte le dump courant."""

    def __init__(self) -> None:
        self.original_dump_calls = 0
        self.name_to_value: Dict[str, Any] = {}

    def dump(self, step: int = 0) -> None:
        self.original_dump_calls += 1


class _FakeModel:
    """Modele double SANS `policy` ni `ent_coef` : les deux branches optionnelles de la capture
    sont hors sujet ici, et les fournir imposerait un vrai reseau pour rien."""

    def __init__(self) -> None:
        self.logger = _FakeLogger()
        self.num_timesteps = 4_806_336


class _CountingTracker:
    """Tracker double : retient chaque capture avec l'abscisse en vigueur au moment de l'ecriture."""

    writer = None

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.steps_at_write: List[int] = []
        self.step_count = 0

    def log_training_metrics(self, model_stats: Dict[str, Any]) -> None:
        self.calls.append(dict(model_stats))
        self.steps_at_write.append(self.step_count)


def _callback(model: _FakeModel, tracker: _CountingTracker) -> Any:
    from ai.training_callbacks import MetricsCollectionCallback

    return MetricsCollectionCallback(tracker, model)


def _dump(model: _FakeModel, payload: Dict[str, Any]) -> None:
    """Un appel a `logger.dump`, precede du remplissage puis suivi du vidage que SB3 opere."""
    model.logger.name_to_value = dict(payload)
    model.logger.dump(step=model.num_timesteps)
    model.logger.name_to_value = {}


def _run_chunks(callback: Any, model: _FakeModel, n_chunks: int, updates: int = 4) -> None:
    """Rejoue la sequence de production : un `learn()` par tranche, `updates` updates dedans.

    C'est `on_training_start` PUIS `on_training_end` a chaque tranche, comme
    `sb3_contrib/ppo_mask/ppo_mask.py` les appelle. Omettre le `end` testerait une sequence que la
    production ne produit jamais.
    """
    for _ in range(n_chunks):
        callback._on_training_start()
        for _ in range(updates):
            _dump(model, _PPO_DUMP)
        callback._on_training_end()


def test_each_ppo_update_is_captured_exactly_once_across_chunks() -> None:
    """Dix tranches de quatre updates : quarante captures, pas un multiple du nombre de tranches."""
    model = _FakeModel()
    tracker = _CountingTracker()
    callback = _callback(model, tracker)

    _run_chunks(callback, model, n_chunks=10)

    assert len(tracker.calls) == 40, (
        f"{len(tracker.calls)} captures pour 40 updates : facteur de duplication "
        f"{len(tracker.calls) / 40:.1f}."
    )
    assert model.logger.original_dump_calls == 40


def test_the_wrapper_is_removed_at_the_end_of_each_chunk() -> None:
    """Apres `_on_training_end`, un `dump` ne capture plus rien.

    L'assertion porte sur l'EFFET et non sur l'identite de `logger.dump` : lire cet attribut
    fabrique une methode liee neuve a chaque acces, donc `is` y est toujours faux et un test
    ecrit ainsi passerait au vert sans rien verifier.

    C'est ce retrait qui rend l'empilement impossible sur un logger persistant, celui d'une
    reprise.
    """
    model = _FakeModel()
    tracker = _CountingTracker()
    callback = _callback(model, tracker)

    callback._on_training_start()
    _dump(model, _PPO_DUMP)
    assert len(tracker.calls) == 1, "l'enveloppe n'a pas ete posee"

    callback._on_training_end()
    _dump(model, _PPO_DUMP)
    assert len(tracker.calls) == 1, "l'enveloppe n'a pas ete retiree : la capture continue"
    assert model.logger.original_dump_calls == 2, "le dump d'origine doit rester joignable"


def test_a_rebuilt_logger_is_wrapped_again() -> None:
    """Le cas du run NEUF : SB3 reconstruit son logger a chaque `learn()`.

    Sans nouvelle enveloppe, plus aucune metrique PPO n'arriverait au tracker.
    """
    model = _FakeModel()
    tracker = _CountingTracker()
    callback = _callback(model, tracker)

    callback._on_training_start()
    callback._on_training_end()
    model.logger = _FakeLogger()  # SB3 a reconstruit le logger
    callback._on_training_start()
    _dump(model, _PPO_DUMP)

    assert len(tracker.calls) == 1
    assert model.logger.original_dump_calls == 1


def test_removal_targets_the_logger_that_was_wrapped() -> None:
    """Le retrait vise le logger enveloppe, jamais `self.model.logger` relu au moment du retrait.

    Si SB3 en a reconstruit un entre-temps, y ecrire le `dump` de l'ancien remplacerait un logger
    neuf et sain par la methode liee d'un logger mort.
    """
    model = _FakeModel()
    callback = _callback(model, _CountingTracker())

    callback._on_training_start()
    wrapped_logger = model.logger
    model.logger = _FakeLogger()

    callback._on_training_end()

    # Si le retrait avait vise `self.model.logger`, ce logger neuf porterait desormais la methode
    # liee de l'ANCIEN : dumper ici incrementerait le compteur de `wrapped_logger`.
    _dump(model, _PPO_DUMP)
    assert model.logger.original_dump_calls == 1, "le dump du logger neuf n'a pas ete appele"
    assert wrapped_logger.original_dump_calls == 0, (
        "le logger neuf porte le dump de l'ancien : le retrait a vise le mauvais logger"
    )


def test_end_of_episode_dumps_are_not_captured() -> None:
    """Un dump sans cle `train/` ne declenche aucune capture.

    `_handle_episode_end` appelle `logger.dump` a chaque fin d'episode. Le capturer recalculait la
    norme du gradient sur tous les parametres pour un dump ne portant aucun update, et publiait un
    point de plus sur `training_diagnostic/entropy_coef` et `gradient_norm` a chaque episode.
    """
    model = _FakeModel()
    tracker = _CountingTracker()
    callback = _callback(model, tracker)

    callback._on_training_start()
    for _ in range(50):  # cinquante episodes
        _dump(model, _EPISODE_DUMP)
    _dump(model, _PPO_DUMP)  # un seul vrai update
    callback._on_training_end()

    assert len(tracker.calls) == 1, (
        f"{len(tracker.calls)} captures pour un seul update PPO : les dumps de fin d'episode "
        "sont captures."
    )
    assert model.logger.original_dump_calls == 51, "les dumps d'episode doivent passer au logger"


def test_ppo_scalars_are_written_at_the_timestep_of_their_own_update() -> None:
    """L'abscisse en vigueur pendant l'ecriture est celle de l'update courant, pas du precedent.

    `log_training_metrics` ecrit chacun de ses scalaires a `tracker.step_count` : pose apres
    l'appel, l'update partait au pas du dump precedent et toutes les courbes
    `training_critical/*` etaient decalees d'un dump.
    """
    model = _FakeModel()
    tracker = _CountingTracker()
    callback = _callback(model, tracker)

    callback._on_training_start()
    for timestep in (8_160, 16_320, 24_480):
        model.num_timesteps = timestep
        _dump(model, _PPO_DUMP)
    callback._on_training_end()

    assert tracker.steps_at_write == [8_160, 16_320, 24_480], (
        f"abscisses {tracker.steps_at_write} : les scalaires sont decales."
    )


def test_unpaired_training_starts_do_not_stack() -> None:
    """Deux `_on_training_start` sans `end` entre eux : une seule enveloppe.

    La production n'y passe pas, SB3 appairant start et end. C'est la garde de dernier recours,
    verifiee pour qu'un futur appelant non appaire ne ramene pas le defaut d'origine.
    """
    model = _FakeModel()
    tracker = _CountingTracker()
    callback = _callback(model, tracker)

    callback._on_training_start()
    callback._on_training_start()
    callback._on_training_start()
    _dump(model, _PPO_DUMP)

    assert len(tracker.calls) == 1
    assert model.logger.original_dump_calls == 1


def test_capture_survives_a_missing_tracker() -> None:
    """Sans tracker, aucune enveloppe n'est posee et le `dump` d'origine passe normalement."""
    model = _FakeModel()
    tracker = _CountingTracker()
    callback = _callback(model, tracker)
    callback.metrics_tracker = None

    callback._on_training_start()
    _dump(model, _PPO_DUMP)

    assert tracker.calls == []
    assert model.logger.original_dump_calls == 1
    callback._on_training_end()  # ne doit pas lever
