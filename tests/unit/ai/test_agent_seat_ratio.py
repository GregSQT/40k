"""Verrou du ratio de siège : `agent_seat_p2_ratio` pilote vraiment la part d'épisodes en second.

POURQUOI CE FICHIER EXISTE. Le siège de l'agent était tiré par la PARITÉ d'un hachage, donc figé
à 50/50 sans aucun réglage possible, alors que l'agent joue nettement moins bien en second (run
x1_long du 2026-08-12 : 0.707 de win-rate en jouant premier contre 0.586 en jouant second, cf.
`ai.bot_evaluation.SEAT_KEYS`). Trois choses peuvent réellement casser ici :

  1. le tirage lui-même — un ratio déclaré mais non appliqué ne changerait rien, et c'est le motif
     d'échec récurrent de ce dépôt (« code testé mais jamais appelé ») ;
  2. la séparation entraînement / évaluation — si le biais fuitait jusqu'à `ai/bot_evaluation.py`,
     le win-rate publié cesserait d'être comparable d'un run à l'autre ;
  3. le contrat de config — la clé est OBLIGATOIRE quand le mode vaut `random`, sans défaut.
"""

from __future__ import annotations

import inspect
import json
import os

import pytest

from ai.env_wrappers import BotControlledEnv
from ai.train import build_training_opponents
from shared.data_validation import ConfigurationError

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
AGENT_CONFIG = os.path.join(
    PROJECT_ROOT, "config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json"
)

with open(AGENT_CONFIG, encoding="utf-8-sig") as _f:
    PROFILES = {k: v for k, v in json.load(_f).items() if isinstance(v, dict)}
PROFILE_NAMES = sorted(PROFILES)


def _silent(_message: str) -> None:
    return None


def _seat_config(**overrides) -> dict:
    config = {
        "bot_training": {
            "ratios": {"random": 0.5, "greedy": 0.5},
            "randomness": {"greedy": 0.05},
        },
        "agent_seat_mode": "random",
        "agent_seat_seed": 7,
        "agent_seat_p2_ratio": 0.65,
    }
    config.update(overrides)
    return config


class _SeatDraw(BotControlledEnv):
    """Expose le tirage de siège sans construire de moteur.

    `BotControlledEnv.__init__` exige un `gym.Wrapper` sur un vrai environnement ; or ce qu'on
    vérifie ici est une fonction PURE de (seed, rang, index d'épisode, ratio). On rejoue donc
    l'initialisation des seuls attributs qu'elle lit, en réutilisant la VRAIE validation du ratio
    (`_resolve_seat_p2_ratio`) et la VRAIE méthode de tirage — pas une réimplémentation, qui
    resterait verte si le wrapper changeait de formule.
    """

    def __init__(self, agent_seat_mode: str, agent_seat_p2_ratio, global_seed: int = 7, env_rank: int = 0):
        self.agent_seat_mode = agent_seat_mode
        self._global_seed = global_seed
        self._env_rank = env_rank
        self._episode_index = 0
        self._agent_seat_p2_ratio = self._resolve_seat_p2_ratio(agent_seat_p2_ratio)

    def p2_share(self, episodes: int) -> float:
        seats = []
        for index in range(episodes):
            self._episode_index = index
            seats.append(self._resolve_controlled_player_for_episode())
        return seats.count(2) / len(seats)


# --- 1. Le tirage applique vraiment le ratio ---------------------------------------------------


@pytest.mark.parametrize("ratio", [0.0, 0.25, 0.5, 0.65, 0.8, 1.0])
def test_the_drawn_share_of_second_seats_follows_the_declared_ratio(ratio: float) -> None:
    """La proportion OBTENUE suit la proportion DÉCLARÉE, à la tolérance d'échantillonnage près.

    C'est la seule assertion qui distingue un ratio câblé d'un ratio décoratif. 4000 épisodes :
    l'erreur-type d'une proportion vaut au pire 0.5/racine(4000) ≈ 0.008, donc 0.03 laisse près de
    quatre erreurs-types de marge et le test ne peut pas devenir instable sur un hachage fixe.
    """
    observed = _SeatDraw("random", ratio).p2_share(4000)
    assert abs(observed - ratio) < 0.03, f"ratio={ratio}, obtenu={observed}"


def test_the_two_extreme_ratios_are_exact_not_approximate() -> None:
    """0.0 et 1.0 ne laissent AUCUN épisode à l'autre siège : le seuil est strict des deux côtés.

    Un seuil mal écrit (`<=` au lieu de `<`) ne se verrait pas sur les ratios intermédiaires, mais
    ferait fuiter des épisodes p2 à ratio 0.0 — c'est-à-dire un profil qui déclare un siège fixe et
    n'en obtient pas un.
    """
    assert _SeatDraw("random", 0.0).p2_share(2000) == 0.0
    assert _SeatDraw("random", 1.0).p2_share(2000) == 1.0


def test_a_fixed_seat_mode_ignores_the_draw_entirely() -> None:
    assert _SeatDraw("p1", None).p2_share(50) == 0.0
    assert _SeatDraw("p2", None).p2_share(50) == 1.0


def test_the_ratio_defaults_to_a_fair_draw_when_unspecified() -> None:
    """`None` vaut 0.5 : c'est le contrat historique de `random`, pas un repli anti-erreur.

    Ce chemin est celui des appelants qui n'ont aucune raison de biaiser — l'évaluation et les
    scripts de mesure. S'il dérivait, leur tirage cesserait d'être équitable sans qu'aucune config
    ne le déclare.
    """
    assert abs(_SeatDraw("random", None).p2_share(4000) - 0.5) < 0.03


def test_the_draw_varies_with_the_env_rank() -> None:
    """Deux environnements vectorisés ne rejouent pas la même séquence de sièges.

    Sans cela, `n_envs` copies tireraient le même siège au même index d'épisode : la ventilation
    globale resterait juste en moyenne, mais tous les environnements basculeraient ensemble, ce qui
    corrèle les gradients d'un batch au siège joué.
    """
    rank_0 = [_SeatDraw("random", 0.5, env_rank=0)._resolve_controlled_player_for_episode()]
    draws_by_rank = []
    for rank in range(8):
        draw = _SeatDraw("random", 0.5, env_rank=rank)
        draws_by_rank.append(draw._resolve_controlled_player_for_episode())
    assert len(set(draws_by_rank)) == 2, f"tous les rangs tirent le même siège : {draws_by_rank}"
    assert rank_0[0] == draws_by_rank[0], "le rang 0 doit rester déterministe"


# --- 2. La validation du ratio ------------------------------------------------------------------


@pytest.mark.parametrize("bad_ratio", [-0.01, 1.01, 2.0, -1.0])
def test_a_ratio_outside_the_unit_interval_is_refused(bad_ratio: float) -> None:
    with pytest.raises(ValueError, match="agent_seat_p2_ratio"):
        _SeatDraw("random", bad_ratio)


@pytest.mark.parametrize("bad_ratio", [True, False, "0.5", None.__class__])
def test_a_non_numeric_ratio_is_refused(bad_ratio) -> None:
    with pytest.raises(TypeError, match="agent_seat_p2_ratio"):
        _SeatDraw("random", bad_ratio)


def test_a_ratio_on_a_fixed_seat_mode_is_refused_not_ignored() -> None:
    """Déclarer un ratio avec `agent_seat_mode: "p1"` est une contradiction, pas une préférence.

    L'accepter en l'ignorant ferait mentir la config : elle annoncerait une ventilation que le run
    ne produirait jamais.
    """
    with pytest.raises(ValueError, match="random"):
        _SeatDraw("p1", 0.65)


def test_the_wrapper_accepts_the_ratio_as_a_keyword_argument() -> None:
    """La signature porte bien le paramètre, au bon nom, avec `None` pour défaut.

    Le tirage est vérifié plus haut sur un objet qui court-circuite `__init__` ; ce test est ce qui
    relie ce court-circuit au vrai constructeur, seul chemin qu'empruntent train.py et
    training_utils.py.
    """
    signature = inspect.signature(BotControlledEnv.__init__)
    parameter = signature.parameters["agent_seat_p2_ratio"]
    assert parameter.default is None
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY or parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


# --- 3. Le contrat de config --------------------------------------------------------------------


def test_build_training_opponents_carries_the_declared_ratio() -> None:
    opponents = build_training_opponents(_seat_config(), True, 10, _silent)
    assert opponents["agent_seat_p2_ratio"] == 0.65


def test_build_training_opponents_refuses_a_random_seat_without_a_ratio() -> None:
    """La clé est OBLIGATOIRE, sans défaut : un profil qui l'oublie doit échouer au démarrage.

    Retomber silencieusement sur 50/50 est exactement le silence qui avait laissé deux profils
    diverger sur `deployment_mode_schedule` sans que rien ne le signale.
    """
    config = _seat_config()
    del config["agent_seat_p2_ratio"]
    with pytest.raises(ConfigurationError, match="agent_seat_p2_ratio"):
        build_training_opponents(config, True, 10, _silent)


@pytest.mark.parametrize("bad_ratio", [-0.1, 1.5])
def test_build_training_opponents_refuses_an_out_of_range_ratio(bad_ratio: float) -> None:
    with pytest.raises(ValueError, match="agent_seat_p2_ratio"):
        build_training_opponents(_seat_config(agent_seat_p2_ratio=bad_ratio), True, 10, _silent)


@pytest.mark.parametrize("bad_ratio", [True, "0.65"])
def test_build_training_opponents_refuses_a_non_numeric_ratio(bad_ratio) -> None:
    with pytest.raises(TypeError, match="agent_seat_p2_ratio"):
        build_training_opponents(_seat_config(agent_seat_p2_ratio=bad_ratio), True, 10, _silent)


@pytest.mark.parametrize("fixed_mode", ["p1", "p2"])
def test_a_cli_override_to_a_fixed_seat_leaves_the_profile_ratio_without_object(fixed_mode: str) -> None:
    """`--param agent_seat_mode p2` doit rester utilisable sur un profil qui déclare un ratio.

    L'override CLI réécrit `agent_seat_mode` dans la config SANS pouvoir en retirer
    `agent_seat_p2_ratio` (`_apply_param_overrides`), et ce chemin est documenté
    (Documentation/Reference/training/entrainement.md). Le ratio y devient sans objet — pas une
    contradiction : `agent_seat_seed` a exactement le même statut, déclaré par les six profils et
    lu par le seul mode `random`. Il ne doit donc pas être transmis au wrapper, qui refuse un ratio
    sur un siège figé.
    """
    opponents = build_training_opponents(_seat_config(agent_seat_mode=fixed_mode), True, 10, _silent)
    assert opponents["agent_seat_mode"] == fixed_mode
    assert opponents["agent_seat_p2_ratio"] is None


@pytest.mark.parametrize("profile_name", PROFILE_NAMES)
def test_every_profile_declares_a_usable_seat_ratio(profile_name: str) -> None:
    """Les six profils portent la clé, dans les bornes, cohérente avec leur `agent_seat_mode`.

    Même règle que `deployment_mode_schedule` : un profil qui diverge en silence entraîne un agent
    sur une distribution de sièges différente de celle des autres, et son win-rate cesse d'être
    comparable au leur.
    """
    profile = PROFILES[profile_name]
    seat_mode = profile["agent_seat_mode"]
    if seat_mode != "random":
        assert "agent_seat_p2_ratio" not in profile, (
            f"{profile_name} déclare un ratio avec agent_seat_mode={seat_mode!r}"
        )
        return
    assert "agent_seat_p2_ratio" in profile, f"{profile_name} n'a pas de agent_seat_p2_ratio"
    ratio = profile["agent_seat_p2_ratio"]
    assert isinstance(ratio, (int, float)) and not isinstance(ratio, bool), profile_name
    assert 0.0 <= float(ratio) <= 1.0, profile_name


def test_the_profiles_do_not_silently_diverge_on_the_seat_ratio() -> None:
    """Tous les profils partagent la MÊME valeur, `x1` faisant référence.

    Le ratio décrit un RÉGIME d'entraînement, pas une longueur de run : le laisser varier d'un
    profil à l'autre rendrait un run de mise au point non représentatif du run de mesure qu'il est
    censé préparer.
    """
    reference = PROFILES["x1"]["agent_seat_p2_ratio"]
    diverging = {
        name: profile["agent_seat_p2_ratio"]
        for name, profile in PROFILES.items()
        if profile.get("agent_seat_mode") == "random"
        and profile.get("agent_seat_p2_ratio") != reference
    }
    assert not diverging, f"profils divergents (référence x1={reference}) : {diverging}"


def test_the_evaluation_never_reads_the_training_seat_ratio() -> None:
    """Le biais ne doit PAS fuiter jusqu'à l'évaluation, dont le tirage reste équitable.

    C'est ce qui garde le win-rate publié comparable entre runs : un `combined` mesuré sur une
    ventilation de sièges biaisée ne le serait plus. Même séparation que
    `deployment_mode_schedule.training_only`.
    """
    with open(os.path.join(PROJECT_ROOT, "ai/bot_evaluation.py"), encoding="utf-8") as f:
        source = f.read()
    assert "agent_seat_p2_ratio" not in source, (
        "ai/bot_evaluation.py référence le ratio d'entraînement : l'évaluation doit garder un "
        "tirage équitable, sinon le win-rate publié cesse d'être comparable d'un run à l'autre."
    )
