"""`blocking_eval_seconds` ne doit contenir que du temps ou la boucle d'entrainement est ARRETEE.

Ce compteur est retranche des quatre chiffres `s/ep` de la barre et des durees d'episode par
slot (ai/training_callbacks.py, EpisodeTerminationCallback._on_step). Il etait alimente par la
duree wall de `_evaluate_against_bots` — or cette methode s'execute sur un thread worker en mode
async (`_async_eval_executor`), PENDANT que la boucle continue de produire des episodes, d'ou des
durees d'episode NEGATIVES (detail et mesure dans `_add_blocking_eval_seconds`).

Les tests verrouillent la separation : l'eval elle-meme n'accumule RIEN, seuls les appelants
situes sur le thread d'entrainement accumulent, et seulement ce qu'ils ont attendu.

L'horloge est factice (meme convention que test_progress_wall_per_episode.py) : les durees
mesurees sont alors EXACTES, la ou des `sleep` reels imposeraient des seuils flous et
allongeraient la suite.
"""

from __future__ import annotations

import time
from concurrent.futures import Future
from typing import Any, Dict, Optional

import pytest

import ai.bot_evaluation
from ai.training_callbacks import BotEvaluationCallback


class _FakeClock:
    """Horloge monotone pilotee par le test, substituee a `time.perf_counter`."""

    def __init__(self) -> None:
        self.now = 1000.0

    def advance(self, delta: float) -> None:
        self.now += delta

    def read(self) -> float:
        return self.now


def _bare_callback(gate_state: Optional[Dict[str, Any]]) -> BotEvaluationCallback:
    """Instance minimale : `__init__` exige un modele SB3 et une config complete.

    Seuls les attributs lus par les methodes sous test sont poses. Aucun defaut cache : si
    l'une d'elles se met a lire autre chose, le test tombe en AttributeError plutot que de
    passer sur une valeur inventee.
    """
    callback = BotEvaluationCallback.__new__(BotEvaluationCallback)
    callback.gate_display_state = gate_state
    callback.async_eval_enabled = True
    callback.show_eval_progress = False
    callback.eval_deterministic = True
    callback.eval_count = 1
    callback.n_eval_episodes = 2
    callback.training_config_name = "x1"
    callback.rewards_config_name = "CoreAgent"
    callback.scenario_pool = None
    callback.model = object()
    callback._pending_eval_future = None
    callback._pending_eval_marker = None
    callback._pending_eval_snapshot_path = None
    return callback


def _install_clock(monkeypatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(time, "perf_counter", clock.read)
    return clock


def test_l_eval_ne_compte_pas_sa_propre_duree(monkeypatch):
    """`_evaluate_against_bots` tourne sur le worker : sa duree n'arrete aucun episode.

    La fausse eval consomme 30 s d'horloge — l'ancienne accumulation les aurait laissees ici.
    """
    clock = _install_clock(monkeypatch)
    gate_state: Dict[str, Any] = {}
    callback = _bare_callback(gate_state)

    def _slow_eval(**_kwargs):
        clock.advance(30.0)
        return {"win_rate": 0.5}

    monkeypatch.setattr(ai.bot_evaluation, "evaluate_against_bots", _slow_eval)

    results = callback._evaluate_against_bots(42)

    assert results == {"win_rate": 0.5}
    assert gate_state.get("blocking_eval_seconds", 0.0) == 0.0, (
        "une eval qui tourne a cote de la boucle ne doit rien ajouter au temps bloque"
    )


def test_la_recolte_non_bloquante_n_ajoute_rien(monkeypatch):
    """Future deja resolu : `result()` rend la main immediatement, rien a imputer.

    C'est le cas NOMINAL du mode async — celui qui produisait les durees negatives — et il
    survient a CHAQUE `_on_step`, donc il ne doit meme pas ouvrir de chronometre.
    """
    _install_clock(monkeypatch)
    gate_state: Dict[str, Any] = {}
    callback = _bare_callback(gate_state)

    future: Future = Future()
    future.set_result({"win_rate": 0.5})
    callback._pending_eval_future = future
    callback._pending_eval_marker = 42

    applied: list = []
    monkeypatch.setattr(callback, "_apply_eval_results", lambda r, m: applied.append((r, m)))
    monkeypatch.setattr(callback, "_cleanup_pending_snapshot", lambda: None)

    callback._consume_async_eval_if_ready(force_wait=False)

    assert applied == [({"win_rate": 0.5}, 42)], "le resultat doit avoir ete consomme"
    assert "blocking_eval_seconds" not in gate_state, (
        "aucune attente : la recolte non bloquante ne doit rien cumuler du tout"
    )


def test_l_attente_explicite_du_future_est_comptee(monkeypatch):
    """`force_wait=True` (early stopping, fin de run) : la boucle attend REELLEMENT.

    Ce temps-la doit etre retranche, sinon on impute a un episode l'attente de la fin d'eval.
    Le faux future avance l'horloge DANS `result()` : c'est exactement ce que le chronometre
    doit encadrer.
    """
    clock = _install_clock(monkeypatch)
    gate_state: Dict[str, Any] = {}
    callback = _bare_callback(gate_state)

    class _BlockingFuture:
        def done(self) -> bool:
            return False

        def result(self):
            clock.advance(12.0)
            return {"win_rate": 0.5}

    callback._pending_eval_future = _BlockingFuture()
    callback._pending_eval_marker = 42
    monkeypatch.setattr(callback, "_apply_eval_results", lambda r, m: None)
    monkeypatch.setattr(callback, "_cleanup_pending_snapshot", lambda: None)

    callback._consume_async_eval_if_ready(force_wait=True)

    assert gate_state["blocking_eval_seconds"] == pytest.approx(12.0), (
        "l'attente reelle du thread d'entrainement doit etre comptee comme temps bloque"
    )


def test_le_chemin_synchrone_compte_toute_la_duree_de_l_eval(monkeypatch):
    """`async_eval_enabled=False` : l'eval s'execute DANS `_on_step`, elle fige la boucle.

    Le defaut d'origine (`max` a 121,80 s pour 1,20 s de duree moteur) reviendrait pour ces
    runs si le call-site synchrone n'accumulait pas. Le test passe par `_on_step`, donc par le
    VRAI chemin de production, pas par un appel direct au cumul.
    """
    clock = _install_clock(monkeypatch)
    gate_state: Dict[str, Any] = {}
    callback = _bare_callback(gate_state)
    callback.async_eval_enabled = False
    callback.use_episode_freq = False
    callback.num_timesteps = 10
    callback.eval_freq = 10
    callback.eval_count = 0
    callback.should_stop_early = False

    def _slow_eval(marker):
        clock.advance(120.0)
        return {"win_rate": 0.5, "marker": marker}

    monkeypatch.setattr(callback, "_evaluate_against_bots", _slow_eval)
    applied: list = []
    monkeypatch.setattr(callback, "_apply_eval_results", lambda r, m: applied.append((r, m)))

    assert callback._on_step() is True
    assert applied and applied[0][1] == 10, "l'eval synchrone doit bien avoir eu lieu"
    assert gate_state["blocking_eval_seconds"] == pytest.approx(120.0), (
        "une eval synchrone arrete la boucle : toute sa duree est du temps bloque"
    )


def test_la_sauvegarde_de_modele_est_comptee(monkeypatch):
    """Zipper le modele fige la boucle, et les TROIS sauvegardes passent par la meme methode.

    L'instrumentation vit dans `_save_model_with_vecnormalize` et non aux call-sites : le
    snapshot d'eval, `best_model` et `best_robust` sont ainsi couverts par construction. Poser
    le chronometre sur le seul snapshot laissait les deux autres gonfler les durees affichees.
    """
    clock = _install_clock(monkeypatch)
    gate_state: Dict[str, Any] = {}
    callback = _bare_callback(gate_state)

    monkeypatch.setattr(callback, "_ensure_zip_path", lambda p: p)

    class _SlowModel:
        policy = type("_P", (), {})()

        def save(self, path):
            clock.advance(3.0)

        def get_env(self):
            return None

    callback.model = _SlowModel()
    monkeypatch.setattr("os.path.exists", lambda p: True)
    monkeypatch.setattr("ai.vec_normalize_utils.save_vec_normalize", lambda env, path: False)

    assert callback._save_model_with_vecnormalize("/tmp/x.zip") == "/tmp/x.zip"
    assert gate_state["blocking_eval_seconds"] == pytest.approx(3.0)


def test_une_duree_negative_est_refusee():
    """Invariant explicite plutot que silence : ce compteur ne peut que croitre.

    Il est soustrait du temps ecoule cote affichage ; un cumul qui reculerait gonflerait les
    durees d'episode au lieu de les corriger. Aucun appelant ne peut produire cela aujourd'hui
    (`perf_counter` est monotone) — la garde verrouille l'invariant pour le prochain appelant.
    """
    callback = _bare_callback({})
    with pytest.raises(ValueError, match="must be >= 0"):
        callback._add_blocking_eval_seconds(-1.0)


def test_sans_gate_display_state_le_cumul_est_sans_effet():
    """`gate_display_state` est optionnel (runs sans affichage de gate) : pas de crash."""
    callback = _bare_callback(None)
    callback._add_blocking_eval_seconds(1.0)
