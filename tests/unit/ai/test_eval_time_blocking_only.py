"""`blocking_eval_seconds` ne doit contenir que du temps ou la boucle d'entrainement est ARRETEE.

Ce compteur est retranche des quatre chiffres `s/ep` de la barre et des durees d'episode par
slot (ai/training_callbacks.py, EpisodeTerminationCallback._on_step). Il etait alimente par la
duree wall de `_evaluate_against_bots` — or cette methode s'execute sur un thread worker en mode
async (`_async_eval_executor`), PENDANT que la boucle continue de produire des episodes, d'ou des
durees d'episode NEGATIVES (detail et mesure dans `_add_blocking_eval_seconds`).

Les tests verrouillent la separation : l'eval elle-meme n'accumule RIEN, seuls les appelants
situes sur le thread d'entrainement accumulent, et seulement ce qu'ils ont attendu.

Ils verrouillent aussi le PERIMETRE des alimenteurs. Le compteur n'a longtemps vecu que dans
`BotEvaluationCallback`, alors que les deux callbacks a SONDES de curriculum bloquent la meme
boucle : leur temps etait compte comme de l'entrainement, et `moy` cessait d'etre comparable
entre une etape a pool et une etape sans. Mesure du 2026-09-11 sur les trois etapes d'un meme
run, part du temps bloquant reellement retranchee : 87 % en P0 (sans pool) contre 53 % en P1 et
57 % en P2.

L'horloge est factice (meme convention que test_progress_wall_per_episode.py) : les durees
mesurees sont alors EXACTES, la ou des `sleep` reels imposeraient des seuils flous et
allongeraient la suite.
"""

from __future__ import annotations

import time
from concurrent.futures import Future
from typing import Any, Dict, Optional, cast

import pytest
from types import SimpleNamespace

import ai.bot_evaluation
import ai.vec_normalize_utils
from ai.train import (
    GATE_DISPLAY_STATE_KEY,
    bind_curriculum_probe_callbacks,
    setup_callbacks,
)
from ai.training_callbacks import (
    BotEvaluationCallback,
    EpisodeTerminationCallback,
    ExploiterProbeCallback,
    PoolEarlyStoppingCallback,
)


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
    callback.scenario_pool = "training"
    callback.model = cast(Any, object())
    # `_evaluate_against_bots` route les troncatures d'eval vers le tracker (V11 §0.61) ;
    # ce test-ci n'en a pas, et un `None` explicite vaut mieux qu'un AttributeError.
    callback.metrics_tracker = None
    callback._pending_eval_future = None
    callback._pending_eval_marker = None
    callback._pending_eval_snapshot_path = None
    callback.intermediate_n_workers = None
    callback.training_probe_every_n_evals = 0
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

    callback._pending_eval_future = cast(Any, _BlockingFuture())
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

    def _slow_eval(marker, **_):
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

    callback.model = cast(Any, _SlowModel())
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


class _SlowSavingModel:
    """Modele factice dont la sauvegarde COUTE du temps d'horloge.

    Zipper le modele fige la boucle autant que l'evaluation qui suit : les deux doivent tomber
    dans le meme chronometre. Un modele a sauvegarde instantanee laisserait passer une
    instrumentation posee sur la seule evaluation.
    """

    def __init__(self, clock: _FakeClock, save_seconds: float) -> None:
        self._clock = clock
        self._save_seconds = save_seconds

    def save(self, path: str) -> None:
        self._clock.advance(self._save_seconds)

    def get_env(self):
        return None


def _neutralise_les_dependances_de_sonde(monkeypatch, clock, eval_seconds, results):
    """Coupe tout ce qu'une sonde touche hors du chronometre, et fait couter l'evaluation."""

    def _slow_eval(**_kwargs):
        clock.advance(eval_seconds)
        return dict(results)

    monkeypatch.setattr(ai.bot_evaluation, "evaluate_against_checkpoints", _slow_eval)
    monkeypatch.setattr(ai.vec_normalize_utils, "save_vec_normalize", lambda env, path: False)


def test_la_sonde_de_pool_compte_son_temps_bloque(monkeypatch):
    """`PoolEarlyStoppingCallback._probe` est synchrone : elle arrete la boucle, donc elle cumule.

    C'est le defaut que ce test verrouille : le compteur vivait chez `BotEvaluationCallback`
    seul, cette sonde n'avait aucun moyen de l'alimenter, et ses minutes etaient lues comme du
    temps d'entrainement dans la colonne `moy`. La sauvegarde du modele (2 s) est comptee au
    meme titre que l'evaluation (40 s) : les deux figent les slots.
    """
    clock = _install_clock(monkeypatch)
    gate_state: Dict[str, Any] = {}
    callback = PoolEarlyStoppingCallback.__new__(PoolEarlyStoppingCallback)
    callback.gate_display_state = gate_state
    callback.pool_archives = [("/tmp/P0.zip", "P0")]
    callback.champion_label = "P0"
    callback.training_config_name = "x1_lineage"
    callback.rewards_config_name = "ArmageddonAgent_x1"
    callback.n_eval_episodes = 300
    callback._eval_n_workers = None
    callback._eval_pool = None
    callback.model = cast(Any, _SlowSavingModel(clock, 2.0))
    monkeypatch.setattr(callback, "_ensure_eval_pool", lambda: None)
    _neutralise_les_dependances_de_sonde(monkeypatch, clock, 40.0, {"P0": 0.55})

    assert callback._probe() == {"P0": pytest.approx(0.55)}
    assert gate_state["blocking_eval_seconds"] == pytest.approx(42.0), (
        "sauvegarde + evaluation : toute la sonde est du temps ou aucun episode ne progresse"
    )


def test_la_sonde_exploiteur_compte_son_temps_bloque(monkeypatch):
    """Jumeau exact chez l'exploiteur : meme convention synchrone, meme dette si on l'oublie."""
    clock = _install_clock(monkeypatch)
    gate_state: Dict[str, Any] = {}
    callback = ExploiterProbeCallback.__new__(ExploiterProbeCallback)
    callback.gate_display_state = gate_state
    callback.target_archive_path = "/tmp/P3.zip"
    callback.training_config_name = "x1_lineage"
    callback.rewards_config_name = "ArmageddonAgent_x1"
    callback._eval_n_workers = None
    callback._eval_pool = None
    callback._episode_origin = 0
    callback.metrics_tracker = None
    callback.log_fn = lambda _message: None
    callback.model = cast(Any, _SlowSavingModel(clock, 3.0))
    monkeypatch.setattr(callback, "_ensure_eval_pool", lambda: None)
    _neutralise_les_dependances_de_sonde(monkeypatch, clock, 25.0, {"target": 0.62})

    assert callback._probe(100, "bon-marche") == pytest.approx(0.62)
    assert gate_state["blocking_eval_seconds"] == pytest.approx(28.0)


def test_une_sonde_non_liee_ne_fait_pas_tomber_le_run(monkeypatch):
    """Callback construit mais jamais lie au dict d'affichage : le cumul doit rester inerte.

    Les deux callbacks a sondes sont construits dans `_run_main`, AVANT que `setup_callbacks`
    ne cree `gate_display_state` ; la liaison est faite ensuite, dans la boucle
    `if extra_callbacks:`. Un chemin qui l'oublierait ne doit pas lever au milieu d'une sonde,
    a des heures de run du demarrage — d'ou le defaut de CLASSE a None, pose une fois dans
    `_BlockingEvalClockMixin` plutot que dans chaque `__init__`.
    """
    assert PoolEarlyStoppingCallback.gate_display_state is None
    assert ExploiterProbeCallback.gate_display_state is None
    callback = PoolEarlyStoppingCallback.__new__(PoolEarlyStoppingCallback)
    callback._add_blocking_eval_seconds(5.0)


def test_la_liaison_de_run_pose_le_dict_de_temps_bloque_sur_les_sondes():
    """Le câblage dont dépend la correction, et qu'aucun test ne couvrait.

    Les deux tests de sonde ci-dessus posent `gate_display_state` A LA MAIN : ils prouvent que
    le chronomètre cumule, pas que le run le branche. Or les sondes sont construites dans
    `_run_main`, avant que `setup_callbacks` ne crée le dict — sans cette liaison, le
    chronomètre écrirait dans un `None` et le défaut survivrait en silence, sa seule trace
    étant une colonne `moy` fausse des heures plus tard.

    `BotEvaluationCallback` ne doit PAS être touché ici : il reçoit le sien à la construction,
    et deux écrivains pour un même attribut est exactement ce qui les désynchronise.
    """
    gate_state: Dict[str, Any] = {"label": "Gate 🧱"}
    training_config = {GATE_DISPLAY_STATE_KEY: gate_state}
    pool = PoolEarlyStoppingCallback.__new__(PoolEarlyStoppingCallback)
    exploiteur = ExploiterProbeCallback.__new__(ExploiterProbeCallback)
    bot_eval = BotEvaluationCallback.__new__(BotEvaluationCallback)
    tracker = cast(Any, object())

    bind_curriculum_probe_callbacks([pool, exploiteur, bot_eval], tracker, training_config)

    assert pool.gate_display_state is gate_state
    assert exploiteur.gate_display_state is gate_state
    assert pool.metrics_tracker is tracker
    assert exploiteur.metrics_tracker is tracker
    assert "gate_display_state" not in bot_eval.__dict__, (
        "le callback d'eval bot recoit son dict a la construction : un second ecrivain le "
        "desynchroniserait"
    )


def test_un_profil_sans_barre_de_progression_lie_None_sans_lever():
    """`total_episodes` absent : `setup_callbacks` ne crée aucun dict, il n'y a rien à corriger.

    `.get` et non `require_key` : l'absence de barre est un état de run VALIDE (profils sans
    budget en épisodes), pas une panne. Le cumul devient alors inerte, cas déjà traité par
    `_add_blocking_eval_seconds`.
    """
    pool = PoolEarlyStoppingCallback.__new__(PoolEarlyStoppingCallback)
    bind_curriculum_probe_callbacks([pool], cast(Any, None), {})
    assert pool.gate_display_state is None
    pool._add_blocking_eval_seconds(4.0)


class _ConfigJamaisLue:
    """Loader de configuration qui REFUSE d'être lu.

    Mesure du 2026-09-11 : `setup_callbacks` ne touche aucun attribut du loader sur ce chemin —
    tout ce qu'il lui faut vient du profil d'entraînement. Un stub permissif masquerait le jour
    où ce n'est plus vrai ; celui-ci nomme l'attribut demandé, ce qui dit quoi fournir.
    """

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(
            f"setup_callbacks a lu config.{name} : le profil minimal de ce test ne suffit plus"
        )


def _profil_minimal_de_run(total_episodes: int = 20) -> Dict[str, Any]:
    """Le plus petit profil d'entraînement que `setup_callbacks` accepte, valeurs indifférentes.

    Aucune de ces clés ne décrit le sujet du fichier : ce sont les champs OBLIGATOIRES que la
    fonction exige avant de construire quoi que ce soit (chaque absence lève en nommant la clé,
    jamais un défaut silencieux — c'est la règle du dépôt). Seuls comptent ici `total_episodes`,
    qui déclenche la barre de progression donc la création du dict, et `_turn_step_limit`, dont
    elle dérive son budget de pas.
    """
    return {
        "total_episodes": total_episodes,
        "_turn_step_limit": 5,
        "callback_params": {
            "checkpoint_save_freq": 1000,
            "checkpoint_name_prefix": "factice",
            "bot_eval_use_episodes": False,
            "eval_deterministic": True,
            "bot_eval_use_subprocess": False,
            "bot_eval_task_timeout_seconds": 60,
            "bot_eval_n_workers": 1,
            "model_gating_min_vs_control": 0.0,
            "robust_penalty_bot": 0.0,
            "robust_penalty_hard": 0.0,
            "early_stopping_patience": 1,
            "save_best_min_episodes": 1,
        },
    }


def _seul(callbacks: Any, classe: type) -> Any:
    """Rend l'unique callback de ce type, et échoue s'il y en a zéro ou plusieurs."""
    trouves = [callback for callback in callbacks if isinstance(callback, classe)]
    assert len(trouves) == 1, (
        f"attendu UN {classe.__name__} parmi {[c.__class__.__name__ for c in callbacks]}"
    )
    return trouves[0]


def test_le_dict_de_temps_bloque_est_une_source_unique_pour_tout_le_run(tmp_path):
    """Le dict que la BARRE lit est celui que la liaison distribue aux sondes — le MÊME objet.

    Les quatre tests ci-dessus tiennent chacun un maillon, mais posent tous leur
    `gate_display_state` A LA MAIN : aucun ne prouve que le run n'en a qu'UN. Or la correction
    ne tient que par cette identité — `setup_callbacks` crée le dict, le dépose dans le profil
    du run, le passe à la barre et à l'éval bot, et `bind_curriculum_probe_callbacks` le relit
    là pour les sondes. Déposer une COPIE au lieu de la référence laisserait les quatre autres
    tests verts pendant que les sondes cumuleraient dans un dict que personne ne lit : seule
    trace, une colonne `moy` fausse des heures plus tard.

    C'est le seul test du fichier qui appelle la vraie construction des callbacks. Elle est
    inoffensive, mesuré le 2026-09-11 : ni thread, ni processus fils, ni fichier créé, et pas
    une lecture du loader de configuration (cf. `_ConfigJamaisLue`).

    Ce test ne couvre PAS le cas d'une sonde construite hors du chemin qui passe par la
    liaison : aucun test ne le peut, seul le site de construction unique (`_run_main`) le tient.
    """
    training_config = _profil_minimal_de_run()

    callbacks = setup_callbacks(
        config=_ConfigJamaisLue(),
        model_path=str(tmp_path / "modele.zip"),
        training_config=training_config,
        training_config_name="x1_factice",
        agent="AgentFactice",
        rewards_config_name="AgentFactice",
    )

    gate_state = training_config[GATE_DISPLAY_STATE_KEY]
    barre = _seul(callbacks, EpisodeTerminationCallback)
    eval_bot = _seul(callbacks, BotEvaluationCallback)
    assert barre.gate_display_state is gate_state, (
        "la barre retranche un AUTRE dict que celui depose dans le profil du run"
    )
    assert eval_bot.gate_display_state is gate_state, (
        "l'eval bot cumulerait dans un dict que la barre ne lit pas"
    )

    sonde = PoolEarlyStoppingCallback.__new__(PoolEarlyStoppingCallback)
    bind_curriculum_probe_callbacks([sonde], cast(Any, None), training_config)
    assert sonde.gate_display_state is gate_state

    # L'identité rendue OBSERVABLE : ce que la sonde cumule, la barre le lit. C'est la chaîne
    # complète du sujet — sonde synchrone -> compteur partagé -> temps retranché de `moy`.
    sonde._add_blocking_eval_seconds(40.0)
    assert barre.gate_display_state["blocking_eval_seconds"] == pytest.approx(40.0), (
        "les 40 s bloquées par la sonde doivent être visibles par la barre qui les retranche"
    )
