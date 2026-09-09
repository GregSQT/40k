"""Tests unitaires — ObservationBuilder : validation de la config d'observation.

Les blocs qui verrouillaient `_calculate_wound_target`, `_calculate_expected_damage` et
`_calculate_favorite_target` ont été retirés avec le pipeline mono-figurine 359-d : ces
méthodes n'existent plus. La table de blessure vive est celle des handlers
(`shooting_handlers._calculate_wound_target`), déjà couverte par ses propres tests.
"""

from __future__ import annotations

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from tests.unit.engine._config_helpers import build_game_rules


def _make_builder(obs_params: dict | None = None) -> ObservationBuilder:
    """Instance minimale. Les VRAIES `game_rules`, jamais un dict bricolé.

    `obs_params` sert aux contre-épreuves ci-dessous : il permet de poser un
    `observation_params` VOLONTAIREMENT périmé et de vérifier qu'il ne change rien.
    """
    config: dict = {"game_rules": build_game_rules()}
    if obs_params is not None:
        config["observation_params"] = obs_params
    return ObservationBuilder(config)


def _declared_scalars(builder: ObservationBuilder) -> int:
    """Somme des scalaires DÉCLARÉS par les formes — la taille réellement produite."""
    return sum(int(np.prod(shape)) for shape in builder.squad_obs_shapes().values())


# ─────────────────────────────────────────────────────────────────────────────
# ObservationBuilder __init__ validation
# ─────────────────────────────────────────────────────────────────────────────

class TestObsBuilderInit:
    def test_obs_size_is_derived_from_the_schema_not_the_config(self):
        """La taille de l'observation vient du schéma d'entités, pas de la config.

        Remplace `obs_init_missing` et `obs_init_no_size`, qui vérifiaient que le builder EXIGEAIT
        un `observation_params.obs_size`. C'était une seconde source de vérité pour un fait que le
        schéma détermine seul : `w40k_core` confrontait ensuite la valeur recopiée à
        `SQUAD_OBS_SIZE_TARGET`, qui la déterminait déjà — une boucle fermée, incapable de rien
        établir, dont la seule issue possible était de retarder sur sa source. La clé n'est plus
        lue, et ce test le prouve avec une valeur DÉLIBÉRÉMENT périmée : la taille produite ne
        bouge pas d'un scalaire.

        Le désaccord modèle/environnement, lui, reste attrapé par SB3 au chargement du `.zip`
        (`check_for_correct_spaces`), qui compare le Dict ENTIER — donc aussi une DISPOSITION
        changée à taille égale, ce que le total scalaire ne voyait pas.
        """
        perime = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET - 70}
        assert _declared_scalars(_make_builder(obs_params=perime)) == (
            ObservationBuilder.SQUAD_OBS_SIZE_TARGET
        ), "un obs_size périmé en config a déplacé la taille produite — la clé est encore lue"

    def test_config_without_observation_params_initializes(self):
        """obs_init_ok : plus aucun paramètre d'observation n'est exigé.

        La contre-épreuve du test précédent : sans la clé du tout, le builder se construit et
        produit exactement la même taille. C'est ce que voit la production depuis que la config
        d'agent ne porte plus `observation_params`.
        """
        assert _declared_scalars(_make_builder()) == ObservationBuilder.SQUAD_OBS_SIZE_TARGET
