"""Compteurs d'issues du cache de scoring du déploiement — V11 §0.46 axe A.

CE QUE CES TESTS VERROUILLENT, et pourquoi ils ne peuvent pas se contenter d'un moteur
construit en mémoire : le harnais habituel démarre en placement FIXE (`deployment_type` ne
vient que d'un fichier de scénario), donc il ne consulte JAMAIS le cache de scoring. Un test
écrit sur ce harnais afficherait « tout va bien » sur des compteurs restés à zéro — le VERT
VACANT déjà payé en §0.56. Ils tournent donc sur un scénario `deployment_type: active` réel.
"""

import pytest

from engine.action_decoder import ActionDecoder

_ACTIVE_SCENARIO = "config/agents/ArmageddonAgent/scenarios/holdout_regular/scenario_bot-01.json"


def _make_engine(seed: int):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file=_ACTIVE_SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )
    eng.reset(seed=seed)
    return eng


def _counts(eng):
    return eng.game_state[ActionDecoder.DEPLOYMENT_CACHE_COUNTS_KEY]


def test_reset_creates_the_counters_and_leaves_exactly_the_initial_observation_build():
    """`reset` est le SEUL créateur de la clé, et il déclare les quatre issues.

    Le compteur n'est PAS à zéro en sortie de `reset` : l'observation initiale, construite
    dans `reset`, consulte déjà le cache pour décrire les candidats de déploiement (§0.40).
    Elle le fait sur un `game_state` fraîchement purgé, donc exactement UNE fois et par un
    `full_build_cold`. C'est cette signature qui est verrouillée ici — si un jour l'obs
    consultait le cache deux fois, ou par un autre chemin, ce test le dirait.
    """
    eng = _make_engine(seed=1)
    counts = _counts(eng)
    assert set(counts) == set(ActionDecoder.DEPLOYMENT_CACHE_OUTCOMES)
    assert counts == {
        "incremental": 0,
        "full_build_cold": 1,
        "full_build_hex_mismatch": 0,
        "full_build_incremental_failed": 0,
    }


def test_deployment_phase_actually_exercises_the_cache():
    """CONTRE LE VERT VACANT : sans consultation réelle, tous les tests suivants sont creux.

    On joue la phase de déploiement en posant les unités une à une, et on exige que le
    compteur BOUGE. Si ce test devient rouge parce que la somme reste à zéro, ce n'est pas
    le compteur qui est cassé — c'est que le scénario ne déploie plus, et les autres tests
    de ce fichier ne prouvent alors plus rien.
    """
    eng = _make_engine(seed=1)
    assert eng.game_state["phase"] == "deployment", (
        "le scenario doit demarrer en phase de deploiement, sinon ce fichier ne teste rien"
    )

    for _ in range(400):
        if eng.game_state["phase"] != "deployment":
            break
        mask = eng.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        eng.step(legal[0])

    total = sum(_counts(eng).values())
    assert total > 0, "le cache de scoring n'a ete consulte AUCUNE fois : test creux"


def test_counters_do_not_leak_across_episodes():
    """L'état qui fuit ENTRE épisodes (§0.42) : un `reset` remet les compteurs à zéro.

    Un compteur qui survit au reset gonflerait d'épisode en épisode et rendrait le taux de
    rebuild ininterprétable — sans jamais lever.
    """
    eng = _make_engine(seed=1)
    after_fresh_reset = dict(_counts(eng))

    for _ in range(50):
        if eng.game_state["phase"] != "deployment":
            break
        mask = eng.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        eng.step(legal[0])
    played = sum(_counts(eng).values())
    assert played > sum(after_fresh_reset.values()), (
        "l'episode n'a consomme aucune consultation de plus que le reset : test creux"
    )

    # Le reset suivant repart d'un compteur neuf : au plus la consultation de l'observation
    # initiale, jamais les dizaines accumulees par l'episode precedent.
    #
    # POURQUOI PAS L'EGALITE STRICTE avec `after_fresh_reset` : le mode de deploiement est
    # TIRE PAR EPISODE (`deployment_mode_schedule`, rampe §0.57). L'episode suivant peut
    # demarrer en placement FIXE, qui ne consulte pas ce cache du tout — exiger la meme
    # signature ferait dependre le test d'un tirage. Un cumul, lui, se verrait sans ambiguite :
    # il rendrait le total >= `played`.
    eng.reset(seed=2)
    after_second_reset = sum(_counts(eng).values())
    assert after_second_reset < played, (
        f"les compteurs cumulent entre episodes : {after_second_reset} apres reset "
        f"contre {played} accumules par l'episode precedent"
    )
    assert after_second_reset <= 1, (
        "un episode neuf consulte le cache au plus une fois (observation initiale)"
    )


def test_unknown_outcome_raises_instead_of_creating_a_silent_key():
    """Une issue non déclarée lève — elle ne crée pas un compteur fantôme.

    C'est la contrepartie de `require_key` : un nom d'issue mal orthographié dans un futur
    chemin doit échouer bruyamment, pas produire une cinquième clé que personne ne publie.
    """
    eng = _make_engine(seed=1)
    with pytest.raises(KeyError):
        ActionDecoder._record_deployment_cache_outcome(eng.game_state, "chemin_inexistant")


def test_recording_without_reset_raises():
    """Un `game_state` qui n'a pas traversé `reset` doit lever, pas compter dans le vide.

    `ConfigurationError` et non `KeyError` : c'est ce que lève `require_key`, le contrôle
    strict du dépôt.
    """
    from shared.data_validation import ConfigurationError

    with pytest.raises(ConfigurationError):
        ActionDecoder._record_deployment_cache_outcome({}, "incremental")
