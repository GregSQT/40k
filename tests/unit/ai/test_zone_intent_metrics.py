"""
Verrous des metriques zone-intent (`00_critical/n_intent_zone_steps`,
`00_critical/o_intent_control_dependency`, `combat/intent_*`).

Quatre defauts sont verrouilles ici :
  1. la fenetre etait remise a zero a CHAQUE fin d'episode, donc le diviseur valait toujours 1
     et la courbe n'etait pas moyennee du tout (un `max(1, ...)` masquait le diviseur mort) ;
  2. deux ecrivains alimentaient les compteurs (le moteur via `_metrics_tracker`, arme au seul
     n_envs==1, et le callback), donc `--step` comptait double ;
  3. rien ne distinguait "la tete zone-intent a appris" de "elle tire uniformement" — c'est le
     role de I(intent ; controle) ;
  4. I SEULE ne le distingue toujours pas : elle est bornee par H(controle), qui vaut 0 quand
     tous les objectifs sont neutres au moment des free steps — mesure faite sur le vrai
     moteur. Le diagnostic publie est donc I / H(controle), et il n'est PAS emis quand H = 0.
     Meme raison pour la ligne de reference de `intent_shaping_aligned_ratio` : le taux
     d'alignement obtenu par une politique aveugle n'est pas une constante (5/9 sur un plateau
     equilibre, INVADE etant paye sur deux etats sur trois), donc le ratio seul est illisible.
"""

from typing import Any, Dict, List, Tuple

import pytest

from ai.metrics_tracker import (
    INTENT_CARDINALITY,
    ZONE_CONTROL_CARDINALITY,
    ZONE_INTENT_WINDOW_EPISODES,
    W40KMetricsTracker,
)


class _RecordingWriter:
    """SummaryWriter minimal : conserve la derniere valeur de chaque tag et l'historique."""

    def __init__(self) -> None:
        self.history: List[Tuple[str, float, int]] = []

    def add_scalar(self, tag: str, value: Any, step: int) -> None:
        self.history.append((tag, float(value), int(step)))

    def latest(self, tag: str) -> float:
        values = [v for t, v, _ in self.history if t == tag]
        if not values:
            raise AssertionError(f"tag jamais emis: {tag}")
        return values[-1]

    def count(self, tag: str) -> int:
        return sum(1 for t, _, _ in self.history if t == tag)


def _tracker() -> Tuple[W40KMetricsTracker, _RecordingWriter]:
    """Tracker sans __init__ : seul l'etat zone-intent est necessaire ici."""
    t = W40KMetricsTracker.__new__(W40KMetricsTracker)
    writer = _RecordingWriter()
    t.writer = writer  # type: ignore[assignment]
    W40KMetricsTracker._reset_zone_intent_state(t)
    return t, writer


def _feed_episode(t: W40KMetricsTracker, steps: List[Tuple[int, float]], step_index: int) -> None:
    """Joue les free steps d'un episode puis clot cet episode."""
    for intent_value, zone_control in steps:
        t.log_zone_intent_step(intent_value, zone_control)
    t._log_zone_intent_metrics(step_index)


def test_window_averages_over_multiple_episodes() -> None:
    """
    VERROU 1 : la moyenne porte bien sur plusieurs episodes.

    Un episode a 10 free steps, les suivants 0. Sans fenetre (comportement d'origine) la courbe
    afficherait 10.0 puis 0.0 ; avec la fenetre glissante elle affiche 10/n.
    """
    t, writer = _tracker()

    _feed_episode(t, [(0, 0.0)] * 10, step_index=1)
    assert writer.latest("00_critical/n_intent_zone_steps") == 10.0

    _feed_episode(t, [], step_index=2)
    assert writer.latest("00_critical/n_intent_zone_steps") == 5.0

    for episode in range(3, 11):
        _feed_episode(t, [], step_index=episode)
    assert writer.latest("00_critical/n_intent_zone_steps") == 1.0


def test_window_is_sliding_and_bounded() -> None:
    """
    VERROU 1 (suite) : la fenetre GLISSE — elle oublie les episodes trop anciens — et emet un
    point a CHAQUE episode, comme les autres courbes 00_critical.
    """
    t, writer = _tracker()

    for episode in range(ZONE_INTENT_WINDOW_EPISODES):
        _feed_episode(t, [(0, 0.0)] * 4, step_index=episode)
    assert writer.latest("00_critical/n_intent_zone_steps") == 4.0
    assert writer.count("00_critical/n_intent_zone_steps") == ZONE_INTENT_WINDOW_EPISODES

    # Les episodes muets chassent progressivement les anciens : a fenetre pleine de zeros, 0.0.
    for episode in range(ZONE_INTENT_WINDOW_EPISODES):
        _feed_episode(t, [], step_index=ZONE_INTENT_WINDOW_EPISODES + episode)
    assert writer.latest("00_critical/n_intent_zone_steps") == 0.0
    assert writer.count("00_critical/n_intent_zone_steps") == 2 * ZONE_INTENT_WINDOW_EPISODES


def test_free_steps_are_counted_across_interleaved_envs() -> None:
    """
    Le tracker est unique et recoit n_envs episodes entrelaces : la mesure est le RATIO
    steps/episodes sur la fenetre, pas une attribution par episode.
    """
    t, writer = _tracker()

    # 8 envs qui produisent 3 free steps chacun, puis 8 fins d'episode.
    for _ in range(8 * 3):
        t.log_zone_intent_step(1, 1.0)
    for episode in range(8):
        t._log_zone_intent_metrics(episode)

    assert writer.latest("00_critical/n_intent_zone_steps") == 3.0


def test_dependency_is_not_emitted_when_the_board_offers_no_contrast() -> None:
    """
    Le piege que la MI brute ne voit pas : tous les objectifs neutres => H(controle) = 0, donc
    I = 0 MECANIQUEMENT, quelle que soit la politique. Publier ce 0 en 00_critical se lirait
    "la tete zone-intent n'a rien appris" alors qu'il n'y avait rien a apprendre.

    Ce n'est pas un cas theorique : c'est ce que le vrai moteur produit en jeu aleatoire, les
    free steps etant joues en command phase avant tout mouvement du tour.
    """
    t, writer = _tracker()

    _feed_episode(t, [(0, 0.0)] * 10 + [(1, 0.0)] * 10 + [(2, 0.0)] * 10, step_index=1)

    assert writer.latest("combat/intent_control_entropy_bits") == pytest.approx(0.0)
    assert writer.latest("combat/intent_mutual_info_bits") == pytest.approx(0.0)
    assert writer.count("00_critical/o_intent_control_dependency") == 0, (
        "un plateau sans contraste ne doit pas etre impute a la politique"
    )
    # Les ratios marginaux, eux, restent mesurables : ils ne dependent pas du controle.
    assert writer.latest("combat/intent_invade_ratio") == pytest.approx(1 / 3)


def test_dependency_saturates_regardless_of_control_entropy() -> None:
    """
    La normalisation fait son travail : un intent entierement determine par l'etat donne U = 1.0
    meme quand le plateau est TRES desequilibre — ou I brute, elle, reste faible.

    Ici H(controle) ~ 0,47 bit (9 free steps sur 10 voient un objectif tenu) : la MI brute
    plafonne a 0,47 sur 1,585 possible, et se lirait comme un conditionnement faible.
    """
    t, writer = _tracker()

    _feed_episode(t, [(1, 1.0)] * 90 + [(0, -1.0)] * 10, step_index=1)

    entropy = writer.latest("combat/intent_control_entropy_bits")
    assert entropy == pytest.approx(0.4690, abs=1e-3)
    assert writer.latest("combat/intent_mutual_info_bits") == pytest.approx(entropy)
    assert writer.latest("00_critical/o_intent_control_dependency") == pytest.approx(1.0)


def test_dependency_is_zero_when_intent_ignores_a_contrasted_board() -> None:
    """Symetrique : le plateau OFFRE du contraste et la politique l'ignore => U = 0."""
    t, writer = _tracker()

    steps: List[Tuple[int, float]] = []
    for zone_control in (-1.0, 1.0):
        for intent_value in (0, 1, 2):
            steps.extend([(intent_value, zone_control)] * 7)
    _feed_episode(t, steps, step_index=1)

    assert writer.latest("combat/intent_control_entropy_bits") == pytest.approx(1.0)
    assert writer.latest("00_critical/o_intent_control_dependency") == pytest.approx(0.0, abs=1e-12)


def test_aligned_baseline_is_what_a_blind_policy_would_score() -> None:
    """
    `intent_shaping_aligned_ratio` n'est lisible qu'en regard de sa reference. Une politique qui
    choisit son intent SANS regarder le plateau doit obtenir ratio == baseline : c'est ce qui
    rend l'ecart entre les deux courbes interpretable.
    """
    t, writer = _tracker()

    # Intents et controles independants par construction (produit croise complet).
    steps: List[Tuple[int, float]] = []
    for zone_control in (-1.0, 0.0, 1.0):
        for intent_value in (0, 1, 2):
            steps.extend([(intent_value, zone_control)] * 5)
    _feed_episode(t, steps, step_index=1)

    ratio = writer.latest("combat/intent_shaping_aligned_ratio")
    baseline = writer.latest("combat/intent_shaping_aligned_baseline")
    assert ratio == pytest.approx(baseline), "sous independance, ratio et reference coincident"

    # Politique parfaitement alignee, MEMES marginales de controle : le ratio sature, la
    # reference reste ou elle etait — c'est l'ECART entre les deux courbes qui porte le signal.
    t2, writer2 = _tracker()
    _feed_episode(t2, [(1, 1.0)] * 15 + [(0, 0.0)] * 15 + [(0, -1.0)] * 15, step_index=1)
    assert writer2.latest("combat/intent_shaping_aligned_ratio") == pytest.approx(1.0)
    # 5/9 : INVADE est paye sur DEUX etats de controle sur trois, donc meme un tirage aveugle
    # marque tres souvent. Un seuil absolu ("> 0.5 = bon") serait trompeur — d'ou la reference.
    assert writer2.latest("combat/intent_shaping_aligned_baseline") == pytest.approx(5 / 9)
    assert (
        writer2.latest("combat/intent_shaping_aligned_ratio")
        > writer2.latest("combat/intent_shaping_aligned_baseline")
    )


def test_mutual_info_is_zero_when_intent_ignores_board_state() -> None:
    """
    VERROU 3 : intents tires independamment du controle -> I = 0 bit, avec un echantillon
    REELLEMENT peuple (une table vide donnerait 0 elle aussi : ce serait un vert vacant).
    """
    t, writer = _tracker()

    steps: List[Tuple[int, float]] = []
    for zone_control in (-1.0, 0.0, 1.0):
        for intent_value in (0, 1, 2):
            steps.extend([(intent_value, zone_control)] * 7)
    _feed_episode(t, steps, step_index=1)

    table = t._intent_contingency_window[-1]
    assert sum(table) == 63, "echantillon vide : le test ne mesurerait rien"
    assert all(cell > 0 for cell in table), "les 9 cellules doivent etre peuplees"

    assert writer.latest("combat/intent_mutual_info_bits") == pytest.approx(0.0, abs=1e-12)
    assert writer.latest("combat/intent_invade_ratio") == pytest.approx(1 / 3)
    assert writer.latest("combat/intent_defend_ratio") == pytest.approx(1 / 3)
    assert writer.latest("combat/intent_attack_ratio") == pytest.approx(1 / 3)


def test_mutual_info_is_maximal_when_intent_is_determined_by_control() -> None:
    """
    VERROU 3 (suite) : un intent entierement determine par l'etat de l'objectif sature la MI a
    log2(3) bits, et les ratios marginaux restent a 1/3 — c'est precisement le cas que les
    seules courbes `intent_*_ratio` ne savaient pas distinguer du tir uniforme.

    log2(3) n'est atteignable QUE parce que les trois etats de controle sont equiprobables ici
    (H(controle) = log2(3)) : c'est le seul cas ou la MI brute peut etre lue contre un maximum
    connu. Voir `test_dependency_saturates_regardless_of_control_entropy` pour le cas general.
    """
    t, writer = _tracker()

    steps = [(0, -1.0)] * 7 + [(1, 1.0)] * 7 + [(2, 0.0)] * 7
    _feed_episode(t, steps, step_index=1)

    import math

    assert writer.latest("combat/intent_control_entropy_bits") == pytest.approx(math.log2(3))
    assert writer.latest("combat/intent_mutual_info_bits") == pytest.approx(math.log2(3))
    assert writer.latest("00_critical/o_intent_control_dependency") == pytest.approx(1.0)
    assert writer.latest("combat/intent_invade_ratio") == pytest.approx(1 / 3)
    assert writer.latest("combat/intent_defend_ratio") == pytest.approx(1 / 3)
    assert writer.latest("combat/intent_attack_ratio") == pytest.approx(1 / 3)


def test_aligned_ratio_follows_shaping_definition() -> None:
    """
    `intent_shaping_aligned_ratio` donne le SENS que la MI ignore : DEFEND sur objectif tenu,
    INVADE sur objectif adverse ou neutre sont payes ; le reste ne l'est pas.
    """
    t, writer = _tracker()

    _feed_episode(t, [(1, 1.0), (0, -1.0), (0, 0.0)], step_index=1)
    assert writer.latest("combat/intent_shaping_aligned_ratio") == pytest.approx(1.0)

    t, writer = _tracker()
    # Politique systematiquement INVERSE du shaping : dependance saturee (elle conditionne
    # parfaitement) mais alignement nul. C'est le cas qui interdit de lire
    # `o_intent_control_dependency` comme une mesure de qualite — elle mesure le
    # conditionnement, pas son sens.
    _feed_episode(t, [(0, 1.0), (1, -1.0), (2, 0.0)], step_index=1)
    assert writer.latest("combat/intent_shaping_aligned_ratio") == pytest.approx(0.0)
    assert writer.latest("00_critical/o_intent_control_dependency") == pytest.approx(1.0)
    assert (
        writer.latest("combat/intent_shaping_aligned_ratio")
        < writer.latest("combat/intent_shaping_aligned_baseline")
    )


def test_empty_window_emits_nothing_rather_than_zeros() -> None:
    """
    Sans aucun free step, emettre 0.0 se lirait comme "uniforme, MI nulle" — soit le diagnostic
    recherche. On n'emet donc ni MI ni ratios (n_intent_zone_steps reste emis : 0 y est une
    information exacte).
    """
    t, writer = _tracker()

    for episode in range(5):
        _feed_episode(t, [], step_index=episode)

    assert writer.latest("00_critical/n_intent_zone_steps") == 0.0
    assert writer.count("combat/intent_mutual_info_bits") == 0
    assert writer.count("combat/intent_control_entropy_bits") == 0
    assert writer.count("00_critical/o_intent_control_dependency") == 0
    assert writer.count("combat/intent_invade_ratio") == 0
    assert writer.count("combat/intent_shaping_aligned_ratio") == 0
    assert writer.count("combat/intent_shaping_aligned_baseline") == 0


def test_invalid_step_arguments_raise() -> None:
    """Aucun rabattage silencieux : une valeur hors domaine est un defaut de cablage."""
    t, _ = _tracker()

    with pytest.raises(ValueError, match="intent_value"):
        t.log_zone_intent_step(3, 0.0)
    with pytest.raises(ValueError, match="zone_control"):
        t.log_zone_intent_step(0, 2.0)


def test_contingency_table_shape_matches_cardinalities() -> None:
    t, _ = _tracker()
    _feed_episode(t, [(0, 0.0)], step_index=1)
    assert len(t._intent_contingency_window[-1]) == ZONE_CONTROL_CARDINALITY * INTENT_CARDINALITY


def test_engine_publishes_zone_control_and_does_not_count_itself() -> None:
    """
    VERROU 2 : le moteur PUBLIE `zone_control` dans l'info et ne compte plus lui-meme. Sans ce
    verrou, reposer un `_metrics_tracker` sur l'env reintroduirait le double comptage a
    n_envs==1 sans qu'aucun test ne bronche.
    """
    import inspect

    from engine import w40k_core

    source = inspect.getsource(w40k_core)
    assert "log_zone_intent_step" not in source, (
        "le moteur ne doit pas compter les free steps : ecrivain unique = training_callbacks"
    )
    assert "_metrics_tracker" not in source, (
        "attribut mort : plus aucun lecteur cote moteur"
    )
    assert '"zone_control": zone_control' in source


def test_callback_forwards_both_keys_without_defaults() -> None:
    """
    Le callback doit exiger les deux cles (require_key) : un `.get()` silencieux rendrait la
    metrique muette si le cablage moteur se cassait.
    """
    import inspect

    from ai import training_callbacks

    source = inspect.getsource(training_callbacks)
    call_index = source.index("log_zone_intent_step(")
    call_site = source[call_index : call_index + 300]
    assert "require_key(info, 'intent_value')" in call_site
    assert "require_key(info, 'zone_control')" in call_site
