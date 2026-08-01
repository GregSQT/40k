"""La colonne de duree de la barre d'entrainement doit se comparer entre deux `n_envs`.

`cur` et `max` sont des durees PAR SLOT : l'intervalle entre deux `done` d'un meme
environnement. Leur moyenne croit ~proportionnellement a `n_envs` alors que le debit, lui,
augmente — le passage de 8 a 48 envs le 2026-08-01 a fait passer cette moyenne de 3,19 a
10,70 s et a fait conclure a un ralentissement, quand le nombre d'episodes par seconde avait
double. La barre affiche desormais `mur` = temps d'ENTRAINEMENT / episodes produits.

Le temps d'evaluation bot est retranche des QUATRE valeurs affichees : du numerateur de `mur`, et
des durees par slot `cur`/`min`/`max`, sinon le slot qui enjambe une eval de 120 s la porte dans
sa propre duree (`max` mesure a 121,80 s contre 1,20 s de duree moteur reelle).

Ce rapport est calcule DIRECTEMENT, pas comme `moyenne par slot / n_envs` : cette division n'est
exacte qu'une fois que chaque slot a termine un episode, et rend `n_envs/k` fois trop peu tant
que seuls `k` slots sont arrives. Le temps ecoule est celui du CHUNK courant, divise par les
episodes de ce chunk — jamais par le compteur d'affichage, qui cumule les chunks precedents en
rotation de scenarios. Les deux pieges ont chacun leur test ci-dessous.

Ces tests pilotent une horloge factice pour que le temps ecoule et le nombre d'episodes soient
connus exactement, puis lisent la valeur RENDUE sur stdout — pas un attribut interne.
"""

from __future__ import annotations

import re
import time

import pytest

from ai.training_callbacks import EpisodeTerminationCallback


class _FakeClock:
    """Horloge monotone pilotee par le test, partagee par perf_counter et time."""

    def __init__(self, start: float) -> None:
        self.now = float(start)

    def advance(self, delta: float) -> None:
        self.now += delta

    def read(self) -> float:
        return self.now


def _install(monkeypatch, n_envs: int, steps_per_episode: int, episodes_per_slot: int,
             global_episode_offset: int = 0, gate_display_state=None):
    """Pose l'horloge factice, le callback et la capture de stdout. Rend (clock, cb, printed).

    `global_episode_offset` simule la rotation de scenarios : le callback du chunk courant
    affiche un compteur qui CUMULE les chunks precedents, alors que son chronometre, lui, part
    du debut de ce chunk.
    """
    clock = _FakeClock(1000.0)
    monkeypatch.setattr(time, "perf_counter", clock.read)
    monkeypatch.setattr(time, "time", clock.read)

    chunk_episodes = episodes_per_slot * n_envs
    callback = EpisodeTerminationCallback(
        max_episodes=chunk_episodes,
        expected_timesteps=chunk_episodes * steps_per_episode,
        total_episodes=global_episode_offset + chunk_episodes,
        disable_early_stopping=True,
        gate_display_state=gate_display_state,
    )
    callback.global_episode_offset = global_episode_offset
    # `_on_training_start` fixe start_time sur l'horloge factice, AVANT le premier pas.
    callback._on_training_start()

    printed: list[str] = []
    monkeypatch.setattr(
        "builtins.print",
        lambda *a, **k: printed.append(a[0] if a else ""),
    )
    return clock, callback, printed


def _drive(monkeypatch, n_envs: int, steps_per_episode: int, step_seconds,
           episodes_per_slot: int, global_episode_offset: int = 0) -> str:
    """Joue `episodes_per_slot` episodes sur chaque slot et rend la derniere ligne affichee.

    Tous les slots terminent en meme temps : le temps ecoule est donc exactement
    `somme(step_seconds) * steps_per_episode`, pour `episodes_per_slot * n_envs` episodes.

    `step_seconds` accepte un flottant (tous les episodes de meme duree) ou une sequence d'une
    valeur par tour d'episode, pour construire des durees d'episode DIFFERENTES.
    """
    clock, callback, printed = _install(monkeypatch, n_envs, steps_per_episode,
                                        episodes_per_slot, global_episode_offset)

    if isinstance(step_seconds, (int, float)):
        seconds_by_round = [float(step_seconds)] * episodes_per_slot
    else:
        seconds_by_round = [float(value) for value in step_seconds]
        if len(seconds_by_round) != episodes_per_slot:
            raise ValueError("step_seconds doit compter une valeur par tour d'episode")

    not_done = [False] * n_envs
    all_done = [True] * n_envs
    for round_index in range(episodes_per_slot):
        for step_index in range(steps_per_episode):
            clock.advance(seconds_by_round[round_index])
            callback.locals = {
                "dones": all_done if step_index == steps_per_episode - 1 else not_done
            }
            callback._on_step()

    assert printed, "aucune ligne de progression affichee : le test ne regarde rien"
    return printed[-1]


def _read_mur(line: str) -> float:
    match = re.search(r"mur ([0-9.]+) \((\d+) env\)", line)
    assert match is not None, f"pas de colonne `mur` dans la ligne affichee : {line!r}"
    return float(match.group(1))


def _read_cur(line: str) -> float:
    match = re.search(r"s/ep: cur ([0-9.]+)", line)
    assert match is not None, f"pas de colonne `cur` dans la ligne affichee : {line!r}"
    return float(match.group(1))


def _read_min_max(line: str) -> tuple[float, float]:
    match = re.search(r"min/max: ([0-9.]+)/([0-9.]+)", line)
    assert match is not None, f"pas de colonne `min/max` dans la ligne affichee : {line!r}"
    return float(match.group(1)), float(match.group(2))


def test_mur_vaut_le_temps_ecoule_par_episode_produit(monkeypatch):
    """`mur` doit valoir temps d'entrainement / episodes produits, pas la duree d'un slot."""
    n_envs, steps_per_episode, step_seconds, episodes_per_slot = 48, 20, 0.01, 5
    line = _drive(monkeypatch, n_envs, steps_per_episode, step_seconds, episodes_per_slot)

    elapsed = episodes_per_slot * steps_per_episode * step_seconds
    produced = episodes_per_slot * n_envs
    assert _read_mur(line) == pytest.approx(elapsed / produced, abs=5e-4)

    # Et la duree PAR SLOT, elle, vaut n_envs fois plus : c'est bien deux grandeurs distinctes
    # qui sont mesurees, pas la meme affichee deux fois.
    assert _read_cur(line) == pytest.approx(steps_per_episode * step_seconds, abs=5e-3)


def test_mur_est_invariant_quand_n_envs_change_a_debit_egal(monkeypatch):
    """Le verrou du defaut : 8 slots et 48 slots au meme debit doivent afficher le meme `mur`.

    Le pas de temps croit du meme facteur que le nombre de slots — c'est ce que fait la machine
    reelle, ou 6 fois plus d'envs se partagent les memes coeurs. Les deux configurations
    produisent donc le meme nombre d'episodes par seconde, et c'est le cas de figure exact du
    2026-08-01 : la duree PAR SLOT sextuple pendant que le debit ne bouge pas.
    """
    line_small = _drive(monkeypatch, n_envs=8, steps_per_episode=20,
                        step_seconds=0.01, episodes_per_slot=5)
    line_large = _drive(monkeypatch, n_envs=48, steps_per_episode=20,
                        step_seconds=0.06, episodes_per_slot=5)

    assert _read_cur(line_large) == pytest.approx(_read_cur(line_small) * 6.0, rel=0.02), (
        "la duree par slot devrait sextupler entre ces deux runs"
    )
    assert _read_mur(line_small) == pytest.approx(_read_mur(line_large), abs=5e-4), (
        "meme debit, meme `mur` : la colonne doit etre comparable entre deux n_envs"
    )


def test_mur_est_juste_des_le_premier_affichage_slots_echelonnes(monkeypatch):
    """Le tout premier affichage, avec UN SEUL slot arrive sur 8, doit rendre le vrai rapport.

    C'est le cas que la moyenne-par-slot-divisee-par-n_envs ratait : la somme des durees ne
    couvre alors que le seul slot arrive, donc la diviser par 8 rendait un `mur` 8 fois trop
    petit. Un rapport temps / episodes produits est juste des le premier episode.
    Le pilotage ci-dessous est deliberement DESYNCHRONISE — c'est la situation reelle, les
    slots ne terminent pas ensemble.
    """
    n_envs, steps_per_episode, step_seconds = 8, 20, 0.05
    clock, callback, printed = _install(monkeypatch, n_envs, steps_per_episode,
                                        episodes_per_slot=1)

    only_first_done = [True] + [False] * (n_envs - 1)
    not_done = [False] * n_envs
    for step_index in range(steps_per_episode):
        clock.advance(step_seconds)
        callback.locals = {
            "dones": only_first_done if step_index == steps_per_episode - 1 else not_done
        }
        callback._on_step()

    assert printed, "aucune ligne affichee : le premier episode n'a pas declenche l'affichage"
    elapsed = steps_per_episode * step_seconds
    assert _read_mur(printed[-1]) == pytest.approx(elapsed / 1, abs=5e-4), (
        "un seul episode produit en `elapsed` secondes : `mur` doit valoir `elapsed`, "
        "pas `elapsed / n_envs`"
    )


def test_mur_ignore_les_episodes_des_chunks_precedents(monkeypatch):
    """En rotation de scenarios, `mur` ne doit pas diviser par le compteur CUMULE.

    Chaque chunk construit un callback neuf dont le chronometre repart de zero
    (`global_start_time` est reassigne a `time.time()` a chaque appel, ai/train.py:3032), alors
    que `global_episode_offset` cumule les chunks deja joues (ai/train.py:4381). Diviser un
    `elapsed` local au chunk par un compteur cumulatif effondre le taux : a l'offset 992, un
    vrai 0,031 s/ep s'affichait 0.000.

    Le meme chunk joue avec et sans offset doit rendre le MEME `mur` — le decalage d'affichage
    ne change pas la vitesse a laquelle la machine produit des episodes.
    """
    n_envs, steps_per_episode, step_seconds = 8, 25, 0.01
    common = dict(n_envs=n_envs, steps_per_episode=steps_per_episode,
                  step_seconds=step_seconds, episodes_per_slot=1)

    line_offset = _drive(monkeypatch, global_episode_offset=992, **common)
    line_fresh = _drive(monkeypatch, global_episode_offset=0, **common)

    elapsed = steps_per_episode * step_seconds
    expected = elapsed / (n_envs * common["episodes_per_slot"])
    assert _read_mur(line_offset) == pytest.approx(expected, abs=5e-4), (
        "`mur` doit compter les episodes de CE chunk, pas ceux des chunks precedents"
    )
    assert _read_mur(line_offset) == pytest.approx(_read_mur(line_fresh), abs=5e-4), (
        "meme chunk, meme vitesse : l'offset d'affichage ne doit rien changer a `mur`"
    )


def test_mur_retranche_le_temps_d_evaluation_bot(monkeypatch):
    """Une eval bot bloque la boucle : son temps ne doit pas etre impute aux episodes.

    L'evaluation periodique pese lourd (13 min mesurees contre 21 s d'entrainement sur un run de
    6 episodes). L'inclure ferait de `mur` un chiffre plusieurs fois trop lent, et surtout
    incomparable entre deux runs de cadences d'eval differentes — or c'est exactement ce que la
    colonne existe pour permettre. L'EMA retranchait deja ce temps ; `mur` doit faire pareil.

    Le test arme `gate_display_state` (le canal reel : `_run_bot_eval` y cumule `total_eval_time`)
    et fait avancer l'horloge d'une pause d'eval au milieu du run.
    """
    n_envs, steps_per_episode, step_seconds = 4, 10, 0.02
    eval_seconds = 30.0
    gate_state = {"label": "Gate 🧱"}
    clock, callback, printed = _install(monkeypatch, n_envs, steps_per_episode,
                                        episodes_per_slot=2, gate_display_state=gate_state)

    not_done = [False] * n_envs
    all_done = [True] * n_envs
    for round_index in range(2):
        for step_index in range(steps_per_episode):
            clock.advance(step_seconds)
            callback.locals = {
                "dones": all_done if step_index == steps_per_episode - 1 else not_done
            }
            callback._on_step()
        if round_index == 0:
            # Une eval bot s'intercale : l'horloge avance, aucun episode d'entrainement produit.
            clock.advance(eval_seconds)
            gate_state["total_eval_time"] = eval_seconds

    training_elapsed = 2 * steps_per_episode * step_seconds
    produced = 2 * n_envs
    assert _read_mur(printed[-1]) == pytest.approx(training_elapsed / produced, abs=5e-4), (
        "les 30 s d'evaluation ne doivent pas etre comptees comme du temps d'entrainement"
    )

    # Les durees PAR SLOT non plus : le slot qui enjambe l'eval l'absorberait sinon dans sa
    # propre duree, et `max` afficherait 30 s de plus que la realite moteur — la colonne
    # `min/max` sert justement a reperer une dispersion d'origine moteur.
    episode_seconds = steps_per_episode * step_seconds
    minimum, maximum = _read_min_max(printed[-1])
    assert maximum == pytest.approx(episode_seconds, abs=5e-3), (
        f"le slot qui enjambe l'evaluation ne doit pas se voir imputer ses {eval_seconds:.0f} s "
        "d'attente"
    )
    assert _read_cur(printed[-1]) == pytest.approx(episode_seconds, abs=5e-3)
    # Le minimum sort du PREMIER tour, ampute d'un pas parce que son chrono demarre au premier
    # `_on_step` — meme artefact que dans le test min/max ci-dessous, sans rapport avec l'eval.
    assert minimum == pytest.approx((steps_per_episode - 1) * step_seconds, abs=5e-3)


def test_min_et_max_encadrent_des_durees_reellement_differentes(monkeypatch):
    """`min` doit suivre le PLUS COURT episode, pas rester colle a `max` ni a son initialisation.

    Les trois tours d'episodes ont des durees deliberement distinctes : un `min` cable sur le
    maximum, ou laisse a son initialisation, ne peut pas rendre 0.10. La dispersion min/max est
    justement ce que la colonne sert a montrer.

    Le tour intermediaire est place EN PREMIER a dessein : le chrono du premier episode demarre
    au premier `_on_step`, il compte donc un pas de moins que les suivants. Ni le minimum ni le
    maximum ne doivent sortir de ce tour tronque, sinon le test verrouillerait cet artefact de
    demarrage au lieu de la statistique.
    """
    steps_per_episode = 10
    line = _drive(monkeypatch, n_envs=4, steps_per_episode=steps_per_episode,
                  step_seconds=[0.02, 0.01, 0.04], episodes_per_slot=3)

    minimum, maximum = _read_min_max(line)
    assert minimum == pytest.approx(0.01 * steps_per_episode, abs=5e-3)
    assert maximum == pytest.approx(0.04 * steps_per_episode, abs=5e-3)
    assert minimum < maximum, "min et max ne doivent pas etre le meme compteur"
