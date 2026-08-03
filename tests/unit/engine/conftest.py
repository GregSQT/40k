"""Fixtures locales aux tests moteur.

``_fight_v11_force_hex_engagement`` : les tests ``fight_v11`` valident la LOGIQUE de la phase
fight (machine à états, snapshots d'engagement, éligibilité, alternance de sélection) sur des
setups ``engagement_zone=1`` pensés en **adjacence hex**. Depuis la bascule EZ euclidienne
(Étape 7.6, ``distance_metric["engagement"]="euclidean"``), la métrique par défaut est
euclidienne (disque 1,5×) → ces setups produiraient des snapshots d'engagement différents et
casseraient les tests pour une raison orthogonale à ce qu'ils vérifient. La métrique EZ
euclidienne est couverte séparément (``test_spatial_relations`` + masque move). On épingle donc
hex pour ces modules afin d'isoler la logique fight.
"""

import pytest


@pytest.fixture(autouse=True)
def _fight_v11_force_hex_engagement(request, monkeypatch):
    if "fight_v11" in request.module.__name__:
        monkeypatch.setattr(
            "engine.spatial_relations.engagement_distance_metric",
            lambda *args, **kwargs: "hex",
        )


#: Scénario `deployment_type: active` réel. Le harnais habituel construit le moteur depuis une
#: config en mémoire, qui démarre TOUJOURS en placement fixe (`deployment_type` ne vient que
#: d'un fichier de scénario) : un test qui veut voir une phase de déploiement doit passer par un
#: fichier, sinon il observe un état qui ne se produit jamais et affiche « tout va bien » — le
#: VERT VACANT déjà payé en V11 §0.56.
ACTIVE_DEPLOYMENT_SCENARIO = (
    "config/agents/ArmageddonAgent/scenarios/holdout_regular/scenario_bot-01.json"
)


@pytest.fixture
def make_active_deployment_engine():
    """Fabrique un `W40KEngine` déjà `reset` sur un scénario à déploiement actif.

    Partagée parce que la même construction (7 arguments, même scénario, même profil
    `x1_debug`) était recopiée dans chaque fichier qui en avait besoin : un argument ajouté à
    `W40KEngine.__init__` casserait les copies une par une, et celle écrite en ligne dans un
    test n'aurait même pas de nom à greper.
    """
    def _make(seed: int, **overrides):
        from ai.unit_registry import UnitRegistry
        from engine.w40k_core import W40KEngine

        kwargs = {
            "rewards_config": "ArmageddonAgent",
            "training_config_name": "x1_debug",
            "controlled_agent": "ArmageddonAgent",
            "scenario_file": ACTIVE_DEPLOYMENT_SCENARIO,
            "unit_registry": UnitRegistry(),
            "quiet": True,
            "gym_training_mode": True,
        }
        kwargs.update(overrides)
        engine = W40KEngine(**kwargs)
        engine.reset(seed=seed)
        return engine

    return _make
