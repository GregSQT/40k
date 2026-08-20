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

import os

import pytest

from tests.unit.engine._config_helpers import build_armageddon_engine


@pytest.fixture(autouse=True, scope="module")
def _board_path_module_isolation():
    """Isole W40K_BOARD_PATH par module : chaque module termine avec l'état d'env
    qu'il avait à son entrée, évitant les fuites cross-module sur les fixtures module-scoped."""
    previous = os.environ.get("W40K_BOARD_PATH")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("W40K_BOARD_PATH", None)
        else:
            os.environ["W40K_BOARD_PATH"] = previous


@pytest.fixture(autouse=True)
def _fight_v11_force_hex_engagement(request, monkeypatch):
    if "fight_v11" in request.module.__name__:
        monkeypatch.setattr(
            "engine.spatial_relations.engagement_distance_metric",
            lambda *args, **kwargs: "hex",
        )


@pytest.fixture
def make_active_deployment_engine():
    """Fabrique un `W40KEngine` déjà `reset` sur un scénario à déploiement actif.

    Partagée parce que la même construction (7 arguments, même scénario, même profil
    `x1_debug`) était recopiée dans chaque fichier qui en avait besoin : un argument ajouté à
    `W40KEngine.__init__` casserait les copies une par une, et celle écrite en ligne dans un
    test n'aurait même pas de nom à greper.
    """
    return build_armageddon_engine


@pytest.fixture
def board_x5():
    """ÉPINGLE le plateau `44x60x5` le temps du test (le cache du loader est indexé par l'override).

    Même raison de vivre ici que `make_active_deployment_engine` juste au-dessus : ce pin était
    recopié à l'identique dans plusieurs fichiers (`test_board_downscale.py`,
    `test_socle_normalized_at_x1.py`, et une variante paramétrée dans `test_move_mask_is_executable.py`),
    et une copie qui oublie la restauration `finally` fuit le plateau sur les tests suivants du même
    processus — un défaut qui ne se voit pas dans le fichier coupable.

    À utiliser dès qu'un test observe quelque chose qui n'existe QUE hors x1 : à x1, `_scale_socle`
    rend `("round", 1)` pour toute figurine (1 fig = 1 case, c'est la définition de la résolution),
    donc les empreintes multi-hex et les paires non-rondes disparaissent. Épingler évite qu'un
    changement de `config/config.json` rende ces tests silencieusement creux.
    """
    import os

    previous = os.environ.get("W40K_BOARD_PATH")
    os.environ["W40K_BOARD_PATH"] = "board/44x60x5"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("W40K_BOARD_PATH", None)
        else:
            os.environ["W40K_BOARD_PATH"] = previous
