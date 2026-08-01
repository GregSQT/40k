"""Les durees de la barre d'entrainement doivent se comparer entre deux `n_envs`.

Le moteur les mesure PAR SLOT d'env : l'intervalle entre deux `done` d'un meme environnement,
attente de synchronisation comprise. Cette latence croit ~proportionnellement a `n_envs` alors
que le debit, lui, augmente — le passage de 8 a 48 envs le 2026-08-01 a fait passer la moyenne
par slot de 3,19 a 10,70 s et a fait conclure a un ralentissement, quand le nombre d'episodes
par seconde avait double.

Les QUATRE valeurs affichees sont donc en secondes de wall-clock PAR EPISODE PRODUIT, diviseur
annonce une fois en tete : `moy` = temps d'entrainement / episodes produits, `cur`/`min`/`max` =
durees par slot ramenees a cette meme echelle. Une seule unite par ligne — c'est le melange des
deux qui avait induit en erreur.

Le temps d'evaluation bot est retranche des quatre, sinon le slot qui enjambe une eval de 120 s
la porte dans sa propre duree (`max` mesure a 121,80 s contre 1,20 s de duree moteur).

`moy` est calcule DIRECTEMENT, pas comme `moyenne par slot / n_envs` : cette division n'est exacte
qu'une fois que chaque slot a termine un episode, et rend `n_envs/k` fois trop peu tant que seuls
`k` slots sont arrives. Son numerateur est le temps du CHUNK courant et son denominateur les
episodes de ce chunk — jamais le compteur d'affichage, qui cumule les chunks precedents en
rotation de scenarios. Ces deux pieges ont chacun leur test ci-dessous.

Ces tests pilotent une horloge factice pour que le temps ecoule et le nombre d'episodes soient
connus exactement, puis lisent la valeur RENDUE sur stdout — pas un attribut interne.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict

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


def _read_moy(line: str) -> float:
    match = re.search(r"moy ([0-9.]+)", line)
    assert match is not None, f"pas de colonne `moy` dans la ligne affichee : {line!r}"
    return float(match.group(1))


def _read_cur(line: str) -> float:
    match = re.search(r"s/ep \((\d+) env\): cur ([0-9.]+)", line)
    assert match is not None, f"pas d'en-tete `s/ep (N env): cur` dans la ligne : {line!r}"
    return float(match.group(2))


def _read_n_envs(line: str) -> int:
    match = re.search(r"s/ep \((\d+) env\)", line)
    assert match is not None, f"pas de diviseur en tete de ligne : {line!r}"
    return int(match.group(1))


def _read_min_max(line: str) -> tuple[float, float]:
    match = re.search(r"min/max: ([0-9.]+)/([0-9.]+)", line)
    assert match is not None, f"pas de colonne `min/max` dans la ligne affichee : {line!r}"
    return float(match.group(1)), float(match.group(2))


def test_moy_vaut_le_temps_ecoule_par_episode_produit(monkeypatch):
    """`moy` doit valoir temps d'entrainement / episodes produits, pas la duree d'un slot."""
    n_envs, steps_per_episode, episodes_per_slot = 48, 20, 5
    # Dernier tour deliberement plus lent : `cur` (dernier episode) et `moy` (moyenne du run)
    # sont deux grandeurs distinctes, un run uniforme ne le montrerait pas.
    # Valeurs choisies pour que `cur` (0.020) et `moy` (0.012) tombent PILE sur une valeur
    # rendue par `:.3f`. Avec 0.03 au dernier tour, `cur` valait 0.0125 : l'affichage arrondit a
    # 0.012 et l'assertion passait a 1.3e-18 de sa tolerance, donc rouge a la premiere derive
    # d'arrondi flottant, sur un affichage pourtant correct.
    seconds_by_round = [0.024, 0.024, 0.024, 0.024, 0.048]
    line = _drive(monkeypatch, n_envs, steps_per_episode, seconds_by_round, episodes_per_slot)

    elapsed = sum(seconds_by_round) * steps_per_episode
    produced = episodes_per_slot * n_envs
    assert _read_moy(line) == pytest.approx(elapsed / produced, abs=5e-4)
    assert _read_n_envs(line) == n_envs, "le diviseur doit etre annonce en tete de ligne"

    # `cur` est la duree du DERNIER episode, ramenee a la meme echelle que `moy` : la duree par
    # slot du dernier tour divisee par le nombre de slots.
    assert _read_cur(line) == pytest.approx(
        seconds_by_round[-1] * steps_per_episode / n_envs, abs=5e-4
    )
    assert _read_cur(line) > _read_moy(line), (
        "le dernier tour est 2x plus lent que les autres : `cur` doit depasser `moy`"
    )


def test_moy_est_invariant_quand_n_envs_change_a_debit_egal(monkeypatch):
    """Le verrou du defaut : 8 slots et 48 slots au meme debit doivent afficher le meme `moy`.

    Le pas de temps croit du meme facteur que le nombre de slots — c'est ce que fait la machine
    reelle, ou 6 fois plus d'envs se partagent les memes coeurs. Les deux configurations
    produisent donc le meme nombre d'episodes par seconde, et c'est le cas de figure exact du
    2026-08-01 : la duree PAR SLOT sextuple pendant que le debit ne bouge pas. Comme les quatre
    valeurs sont desormais ramenees a la seconde par episode, ce sextuplement ne doit plus
    transparaitre nulle part sur la ligne.
    """
    line_small = _drive(monkeypatch, n_envs=8, steps_per_episode=20,
                        step_seconds=0.01, episodes_per_slot=5)
    line_large = _drive(monkeypatch, n_envs=48, steps_per_episode=20,
                        step_seconds=0.06, episodes_per_slot=5)

    assert _read_n_envs(line_small) == 8 and _read_n_envs(line_large) == 48
    assert _read_cur(line_small) == pytest.approx(_read_cur(line_large), abs=5e-4), (
        "la duree par slot sextuple, mais ramenee par episode elle ne doit pas bouger"
    )
    assert _read_moy(line_small) == pytest.approx(_read_moy(line_large), abs=5e-4), (
        "meme debit, meme `moy` : la colonne doit etre comparable entre deux n_envs"
    )


def test_moy_est_juste_des_le_premier_affichage_slots_echelonnes(monkeypatch):
    """Le tout premier affichage, avec UN SEUL slot arrive sur 8, doit rendre le vrai rapport.

    C'est le cas que la moyenne-par-slot-divisee-par-n_envs ratait : la somme des durees ne
    couvre alors que le seul slot arrive, donc la diviser par 8 rendait un `moy` 8 fois trop
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
    assert _read_moy(printed[-1]) == pytest.approx(elapsed / 1, abs=5e-4), (
        "un seul episode produit en `elapsed` secondes : `moy` doit valoir `elapsed`, "
        "pas `elapsed / n_envs`"
    )


def test_moy_ignore_les_episodes_des_chunks_precedents(monkeypatch):
    """En rotation de scenarios, `moy` ne doit pas diviser par le compteur CUMULE.

    Chaque chunk construit un callback neuf dont le chronometre repart de zero
    (`global_start_time` est reassigne a `time.time()` a chaque appel, ai/train.py:3032), alors
    que `global_episode_offset` cumule les chunks deja joues (ai/train.py:4381). Diviser un
    `elapsed` local au chunk par un compteur cumulatif effondre le taux : a l'offset 992, un
    vrai 0,031 s/ep s'affichait 0.000.

    Le meme chunk joue avec et sans offset doit rendre le MEME `moy` — le decalage d'affichage
    ne change pas la vitesse a laquelle la machine produit des episodes.
    """
    # 0.016 et non 0.01 : `moy` tombe alors sur 0.050, valeur exactement rendue par `:.3f`,
    # au lieu de 0.03125 arrondi a 0.031 (la moitie de la tolerance consommee par l'arrondi).
    n_envs, steps_per_episode, step_seconds, episodes_per_slot = 8, 25, 0.016, 1

    line_offset = _drive(monkeypatch, n_envs=n_envs, steps_per_episode=steps_per_episode,
                         step_seconds=step_seconds, episodes_per_slot=episodes_per_slot,
                         global_episode_offset=992)
    line_fresh = _drive(monkeypatch, n_envs=n_envs, steps_per_episode=steps_per_episode,
                        step_seconds=step_seconds, episodes_per_slot=episodes_per_slot,
                        global_episode_offset=0)

    elapsed = steps_per_episode * step_seconds
    expected = elapsed / (n_envs * episodes_per_slot)
    assert _read_moy(line_offset) == pytest.approx(expected, abs=5e-4), (
        "`moy` doit compter les episodes de CE chunk, pas ceux des chunks precedents"
    )
    assert _read_moy(line_offset) == pytest.approx(_read_moy(line_fresh), abs=5e-4), (
        "meme chunk, meme vitesse : l'offset d'affichage ne doit rien changer a `moy`"
    )


def test_moy_retranche_le_temps_d_evaluation_bot(monkeypatch):
    """Une eval bot bloque la boucle : son temps ne doit pas etre impute aux episodes.

    L'evaluation periodique pese lourd (13 min mesurees contre 21 s d'entrainement sur un run de
    6 episodes). L'inclure ferait de `moy` un chiffre plusieurs fois trop lent, et surtout
    incomparable entre deux runs de cadences d'eval differentes — or c'est exactement ce que la
    colonne existe pour permettre. L'EMA retranchait deja ce temps ; `moy` doit faire pareil.

    Le test arme `gate_display_state` (le canal reel : `_run_bot_eval` y cumule `total_eval_time`)
    et fait avancer l'horloge d'une pause d'eval au milieu du run.
    """
    n_envs, steps_per_episode, step_seconds = 4, 10, 0.02
    eval_seconds = 30.0
    gate_state: Dict[str, Any] = {"label": "Gate 🧱"}
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
    assert _read_moy(printed[-1]) == pytest.approx(training_elapsed / produced, abs=5e-4), (
        "les 30 s d'evaluation ne doivent pas etre comptees comme du temps d'entrainement"
    )

    # Les durees PAR SLOT non plus : le slot qui enjambe l'eval l'absorberait sinon dans sa
    # propre duree, et `max` afficherait 30 s de plus que la realite moteur — la colonne
    # `min/max` sert justement a reperer une dispersion d'origine moteur.
    episode_seconds = steps_per_episode * step_seconds / n_envs
    minimum, maximum = _read_min_max(printed[-1])
    assert maximum == pytest.approx(episode_seconds, abs=5e-4), (
        f"le slot qui enjambe l'evaluation ne doit pas se voir imputer ses {eval_seconds:.0f} s "
        "d'attente"
    )
    assert _read_cur(printed[-1]) == pytest.approx(episode_seconds, abs=5e-4)
    # Le minimum sort du PREMIER tour, ampute d'un pas parce que son chrono demarre au premier
    # `_on_step` — meme artefact que dans le test min/max ci-dessous, sans rapport avec l'eval.
    assert minimum == pytest.approx((steps_per_episode - 1) * step_seconds / n_envs, abs=5e-4)


def test_la_ligne_reste_lisible_par_les_parseurs_des_bancs(monkeypatch):
    """Le format de la ligne est un CONTRAT avec `scripts/ab_bench.py`, pas un detail d'affichage.

    `read_steady_rate` lit `episodes`, `n_envs` et `moy` sur DEUX rafraichissements de barre et en
    tire le regime etabli : c'est la grandeur du VERDICT des trois bancs qui lancent des
    entrainements, et de leur balayage. `read_loop_elapsed` lit le `[MM:SS<` dont ils derivent la
    part hors boucle. Un renommage de colonne casse donc les campagnes, et les casse par
    `SystemExit` — que le `except RunFailed` du balayage ne rattrape pas, tuant la nuit entiere
    apres le premier run.

    Ce test relie les deux cotes : il fait produire de VRAIES lignes par le callback et les donne
    a manger aux parseurs. Sans lui, renommer une colonne laisse ce fichier vert pendant que les
    bancs tombent — c'est ce qui s'est produit au passage de `mur` a `moy`.

    Le run est volontairement DEUX FOIS PLUS LENT sur sa seconde moitie : le regime etabli (1,5
    s/ep) differe alors du `moy` cumule affiche (1,0 s/ep), donc un parseur qui lirait la mauvaise
    colonne, ou le test qui verifierait la mauvaise grandeur, ne pourrait pas passer par hasard.
    """
    import os
    import sys

    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from ab_bench import read_loop_elapsed, read_steady_rate  # noqa: E402

    # n_envs=8 : les episodes tombent par vagues de 8, donc les rafraichissements (tous les 10
    # episodes affiches) ont lieu a 40 et 80. Deux points, le minimum qu'exige `read_steady_rate`.
    n_envs, steps_per_episode, episodes_per_slot = 8, 20, 10
    slow_seconds, fast_seconds = 0.6, 0.2
    seconds_by_round = [fast_seconds] * 5 + [slow_seconds] * 5
    clock, callback, printed = _install(monkeypatch, n_envs, steps_per_episode, episodes_per_slot)

    not_done = [False] * n_envs
    all_done = [True] * n_envs
    for round_seconds in seconds_by_round:
        for step_index in range(steps_per_episode):
            clock.advance(round_seconds)
            callback.locals = {
                "dones": all_done if step_index == steps_per_episode - 1 else not_done
            }
            callback._on_step()

    output = "\n".join(printed)
    rate, n_envs_read, window = read_steady_rate(output)

    assert n_envs_read == n_envs, "le banc doit retrouver le n_envs annonce en tete de ligne"
    assert window == (40, 80), f"fenetre de mesure inattendue : {window}"
    steady = slow_seconds * steps_per_episode / n_envs
    assert rate == pytest.approx(steady, abs=5e-4), (
        "le banc doit mesurer le regime de la SECONDE moitie, pas la moyenne cumulee"
    )
    assert rate != pytest.approx(_read_moy(printed[-1]), abs=5e-4), (
        "regime etabli et `moy` cumule doivent differer ici, sinon le test passerait par hasard"
    )

    elapsed = sum(seconds_by_round) * steps_per_episode
    assert read_loop_elapsed(output) == pytest.approx(elapsed, abs=1.0), (
        "le banc doit retrouver le `[MM:SS<` du dernier rafraichissement (resolution : la seconde)"
    )


def test_min_et_max_encadrent_des_durees_reellement_differentes(monkeypatch):
    """`min` doit suivre le PLUS COURT episode, pas rester colle a `max` ni a son initialisation.

    Les trois tours d'episodes ont des durees deliberement distinctes : un `min` cable sur le
    maximum, ou laisse a son initialisation, ne peut pas rendre le tour le plus court. La
    dispersion min/max est justement ce que la colonne sert a montrer.

    Le tour intermediaire est place EN PREMIER a dessein : le chrono du premier episode demarre
    au premier `_on_step`, il compte donc un pas de moins que les suivants. Ni le minimum ni le
    maximum ne doivent sortir de ce tour tronque, sinon le test verrouillerait cet artefact de
    demarrage au lieu de la statistique.
    """
    n_envs, steps_per_episode = 4, 10
    line = _drive(monkeypatch, n_envs=n_envs, steps_per_episode=steps_per_episode,
                  step_seconds=[0.02, 0.01, 0.04], episodes_per_slot=3)

    # Comme `cur` et `moy`, les bornes sont affichees en secondes par episode produit.
    minimum, maximum = _read_min_max(line)
    assert minimum == pytest.approx(0.01 * steps_per_episode / n_envs, abs=5e-4)
    assert maximum == pytest.approx(0.04 * steps_per_episode / n_envs, abs=5e-4)
    assert minimum < maximum, "min et max ne doivent pas etre le meme compteur"
