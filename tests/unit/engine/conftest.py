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
