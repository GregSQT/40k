"""Tests isolation de _deployment_slot_order pour les 7 stratégies (+0..+6).

Pas de moteur complet : la méthode est statique et ne dépend que de numpy.
Préférences vérifiées par mesure (scripts/_probe_slot_order.py) :
  progress : max (+0,+1,+5), min (+6)  — absent de +2,+3,+4
  nearest_enemy : min (+0,+1), max (+2,+3,+4,+6)  — absent de +5
  nearest_objective : toujours min
  los : toujours min
  center_distance : toujours min

`+6` (arrière-garde) trie par objectif PUIS par recul, et non par éloignement aux ennemis :
mené par l'éloignement, son tri était identique à celui de `+2` (« sûr ») dès que `los`,
`potential_los` et `nearest_ally` étaient constants — c'est-à-dire à chaque premier déploiement.
Voir `TestStrategiesStayDistinct`, qui verrouille la cause plutôt qu'un jeu de valeurs.
"""

import numpy as np
import pytest

from engine.action_decoder import ActionDecoder
from engine.macro_intents import DEPLOY_SLOT_BASE


def _cols(
    *,
    nearest_enemy,
    nearest_objective,
    nearest_ally,
    los,
    potential_los,
    cluster,
    progress,
    center_distance,
    cols,
    rows,
    center_col=5,
    center_row=5,
):
    def _a(seq):
        return np.array(seq, dtype=np.float32)

    return {
        "nearest_enemy": _a(nearest_enemy),
        "nearest_objective": _a(nearest_objective),
        "nearest_ally": _a(nearest_ally),
        "los": _a(los),
        "potential_los": _a(potential_los),
        "cluster": _a(cluster),
        "progress": _a(progress),
        "center_distance": _a(center_distance),
        "cols": _a(cols),
        "rows": _a(rows),
        "center_col": center_col,
        "center_row": center_row,
    }


def _neutral(n: int) -> dict:
    """Colonnes neutres (toutes à 0) pour n hexes."""
    z = [0.0] * n
    return dict(
        nearest_enemy=z, nearest_objective=z, nearest_ally=z,
        los=z, potential_los=z, cluster=z, progress=z,
        center_distance=z, cols=[5.0] * n, rows=[5.0] * n,
    )


def _order(columns, offset):
    return ActionDecoder._deployment_slot_order(columns, DEPLOY_SLOT_BASE + offset)


# ---------------------------------------------------------------------------
# +0 : front agressif — primary = progress max ; secondary = nearest_enemy min
# ---------------------------------------------------------------------------
class TestSlot0FrontAgressif:
    def test_progress_prime_max(self):
        kw = _neutral(3)
        kw["progress"] = [1.0, 5.0, 10.0]
        order = _order(_cols(**kw), 0)
        assert order[0] == 2  # progress max = 10

    def test_nearest_enemy_tiebreak_min(self):
        # progress égal, nearest_enemy min wins (closer = more aggressive)
        kw = _neutral(3)
        kw["progress"] = [7.0, 7.0, 7.0]
        kw["nearest_enemy"] = [1.0, 5.0, 9.0]
        order = _order(_cols(**kw), 0)
        assert order[0] == 0  # nearest_enemy min = 1


# ---------------------------------------------------------------------------
# +1 : pression objectif — primary = nearest_objective min
# ---------------------------------------------------------------------------
class TestSlot1ObjectivePressure:
    def test_objective_prime_min(self):
        kw = _neutral(3)
        kw["nearest_objective"] = [8.0, 5.0, 1.0]
        order = _order(_cols(**kw), 1)
        assert order[0] == 2  # nearest_objective min = 1

    def test_progress_tiebreak_max(self):
        # objective égal, progress max wins (4e critère ; los et potential_los sont 0 dans _neutral)
        kw = _neutral(3)
        kw["nearest_objective"] = [3.0, 3.0, 3.0]
        kw["progress"] = [1.0, 5.0, 10.0]
        order = _order(_cols(**kw), 1)
        assert order[0] == 2  # progress max = 10


# ---------------------------------------------------------------------------
# +2 : sûr/cohésion — primary = los min ; secondary = nearest_enemy max
# ---------------------------------------------------------------------------
class TestSlot2SafeCohesion:
    def test_los_prime_min(self):
        # min los = moins exposé = plus sûr
        kw = _neutral(3)
        kw["los"] = [0.0, 3.0, 7.0]
        order = _order(_cols(**kw), 2)
        assert order[0] == 0  # los min = 0

    def test_nearest_enemy_tiebreak_max(self):
        # los égal, nearest_enemy max wins (loin des ennemis = sûr)
        kw = _neutral(3)
        kw["los"] = [2.0, 2.0, 2.0]
        kw["nearest_enemy"] = [1.0, 5.0, 9.0]
        order = _order(_cols(**kw), 2)
        assert order[0] == 2  # nearest_enemy max = 9


# ---------------------------------------------------------------------------
# +3 : flanc gauche — primary = los min ; secondary = cols min (leftmost)
# ---------------------------------------------------------------------------
class TestSlot3LeftFlank:
    def test_los_prime_min(self):
        kw = _neutral(3)
        kw["los"] = [0.0, 3.0, 7.0]
        order = _order(_cols(**kw), 3)
        assert order[0] == 0

    def test_cols_tiebreak_leftmost(self):
        # los égal, leftmost column wins
        kw = _neutral(3)
        kw["los"] = [1.0, 1.0, 1.0]
        kw["cols"] = [8.0, 5.0, 1.0]
        order = _order(_cols(**kw), 3)
        assert order[0] == 2  # cols min = 1 (leftmost)


# ---------------------------------------------------------------------------
# +4 : flanc droit — primary = los min ; secondary = cols max (rightmost)
# ---------------------------------------------------------------------------
class TestSlot4RightFlank:
    def test_los_prime_min(self):
        kw = _neutral(3)
        kw["los"] = [0.0, 3.0, 7.0]
        order = _order(_cols(**kw), 4)
        assert order[0] == 0

    def test_cols_tiebreak_rightmost(self):
        kw = _neutral(3)
        kw["los"] = [1.0, 1.0, 1.0]
        kw["cols"] = [9.0, 5.0, 1.0]
        order = _order(_cols(**kw), 4)
        assert order[0] == 0  # cols max = 9 (rightmost)


# ---------------------------------------------------------------------------
# +5 : centre_hub — primary = center_distance min
# ---------------------------------------------------------------------------
class TestSlot5CentreHub:
    def test_center_distance_prime_min(self):
        # hex 1 au centre (distance minimale)
        kw = _neutral(3)
        kw["center_distance"] = [4.0, 0.0, 6.0]
        order = _order(_cols(**kw), 5)
        assert order[0] == 1  # center_distance min = 0

    def test_objective_tiebreak_min(self):
        # center_distance égal, nearest_objective min wins
        kw = _neutral(3)
        kw["center_distance"] = [2.0, 2.0, 2.0]
        kw["nearest_objective"] = [5.0, 3.0, 1.0]
        order = _order(_cols(**kw), 5)
        assert order[0] == 2  # nearest_objective min = 1


# ---------------------------------------------------------------------------
# +6 : safe_rear — primary = nearest_objective min ; puis progress min (recul)
# ---------------------------------------------------------------------------
class TestSlot6SafeRear:
    def test_objective_prime_min(self):
        # hex 1 le plus proche d'un objectif, même s'il n'est ni le plus reculé ni le plus loin
        # des ennemis : une arrière-garde TIENT quelque chose.
        kw = _neutral(3)
        kw["nearest_objective"] = [8.0, 1.0, 4.0]
        kw["nearest_enemy"] = [10.0, 3.0, 5.0]
        kw["progress"] = [-9.0, 2.0, -4.0]
        order = _order(_cols(**kw), 6)
        assert order[0] == 1  # nearest_objective min = 1

    def test_progress_tiebreak_min(self):
        # objectif égal : le plus RECULÉ gagne — c'est ce qui sépare ce slot de « pression sur
        # objectif » (+1), qui trie le même objectif par progression maximale.
        kw = _neutral(3)
        kw["nearest_objective"] = [5.0, 5.0, 5.0]
        kw["progress"] = [2.0, -7.0, 1.0]
        order = _order(_cols(**kw), 6)
        assert order[0] == 1  # progress min = -7

    def test_nearest_enemy_breaks_ties_after_objective_and_progress(self):
        # objectif ET recul égaux : l'éloignement aux ennemis départage, comme avant.
        kw = _neutral(3)
        kw["nearest_objective"] = [5.0, 5.0, 5.0]
        kw["progress"] = [-3.0, -3.0, -3.0]
        kw["nearest_enemy"] = [4.0, 9.0, 1.0]
        order = _order(_cols(**kw), 6)
        assert order[0] == 1  # nearest_enemy max = 9

    def test_does_not_shadow_objective_pressure(self):
        """+1 et +6 partagent l'objectif comme premier critère, jamais le même hexe.

        Les deux visent l'objectif ; ce qui les sépare est le SENS de la progression — avancer
        pour la pression (+1), reculer pour l'arrière-garde (+6). Sans ce second critère opposé,
        le correctif de la collision +2/+6 en aurait simplement créé une autre.
        """
        kw = _neutral(4)
        kw["nearest_objective"] = [2.0, 2.0, 9.0, 9.0]
        kw["progress"] = [6.0, -6.0, 1.0, -1.0]
        assert int(_order(_cols(**kw), 1)[0]) == 0  # objectif proche ET avancé
        assert int(_order(_cols(**kw), 6)[0]) == 1  # objectif proche ET reculé


# ---------------------------------------------------------------------------
# Deux stratégies ne peuvent pas désigner le même hexe
# ---------------------------------------------------------------------------
class TestStrategiesStayDistinct:
    """« Sûr » (+2) et « arrière-garde » (+6) ne désignent pas le même hexe.

    LE CAS RÉEL, et non un jeu de données choisi pour tomber juste : au premier déploiement,
    aucun ennemi ni allié n'est encore posé, donc `los`, `potential_los` et `nearest_ally` sont
    CONSTANTS sur toute la zone (`_deployment_score_columns` met `nearest_ally` à zéro partout
    quand aucun allié n'est déployé). Les deux tuples de tri ne différaient alors que par des
    clés constantes, donc ils coïncidaient : mesuré sur le scénario `reserves_20_fixture1`,
    les slots 6 et 10 posaient tous deux (216, 296) au déploiement et (219, 299) à l'ingress,
    aux trois graines et sur les deux terrains.

    L'agent disposait de sept actions dont deux rigoureusement redondantes, sans que rien ne
    lève — masque valide et plan exécutable des deux côtés.
    """

    def test_safe_and_safe_rear_differ_when_los_and_ally_are_constant(self):
        kw = _neutral(6)
        # Ce qui est CONSTANT dans un premier déploiement — c'est là toute la cause.
        kw["los"] = [0.0] * 6
        kw["potential_los"] = [0.0] * 6
        kw["nearest_ally"] = [0.0] * 6
        # Ce qui varie : un fond de zone loin des ennemis, et un hexe sur objectif un peu moins
        # reculé. « Sûr » doit prendre le premier, « arrière-garde » le second.
        kw["nearest_enemy"] = [10.0, 9.0, 4.0, 3.0, 2.0, 1.0]
        kw["nearest_objective"] = [7.0, 0.0, 5.0, 6.0, 8.0, 9.0]
        kw["progress"] = [-9.0, -7.0, -3.0, -1.0, 2.0, 5.0]
        kw["cols"] = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        kw["rows"] = [9.0, 7.0, 3.0, 1.0, 2.0, 5.0]

        safe = int(_order(_cols(**kw), 2)[0])
        safe_rear = int(_order(_cols(**kw), 6)[0])
        assert safe != safe_rear, (
            f"« sûr » et « arrière-garde » désignent le même hexe (index {safe}) : deux des sept "
            f"actions de pose sont redondantes"
        )

    def test_the_two_tuples_are_not_equal_modulo_constant_keys(self):
        """La cause STRUCTURELLE, indépendamment des données : les deux tris ne coïncident pas.

        Le test ci-dessus prouve la séparation sur un jeu de valeurs ; celui-ci prouve qu'elle
        ne tient pas à ce jeu. On annule TOUTES les clés que le premier déploiement rend
        constantes, et on compare les ordres complets sur des valeurs aléatoires : deux tris qui
        ne diffèrent que par des clés neutralisées rendent la même permutation.
        """
        rng = np.random.default_rng(20260909)
        for _ in range(20):
            n = 12
            kw = _neutral(n)
            kw["los"] = [0.0] * n
            kw["potential_los"] = [0.0] * n
            kw["nearest_ally"] = [0.0] * n
            kw["nearest_enemy"] = rng.integers(0, 20, n).astype(float).tolist()
            kw["nearest_objective"] = rng.integers(0, 20, n).astype(float).tolist()
            kw["progress"] = rng.integers(-20, 20, n).astype(float).tolist()
            kw["cluster"] = rng.integers(0, 4, n).astype(float).tolist()
            kw["center_distance"] = rng.integers(0, 12, n).astype(float).tolist()
            kw["cols"] = rng.integers(0, 12, n).astype(float).tolist()
            kw["rows"] = rng.integers(0, 12, n).astype(float).tolist()
            safe = _order(_cols(**kw), 2).tolist()
            safe_rear = _order(_cols(**kw), 6).tolist()
            assert safe != safe_rear, (
                "« sûr » et « arrière-garde » produisent l'ORDRE ENTIER identique : leurs tuples "
                "de tri ne diffèrent que par des clés que le premier déploiement met à zéro"
            )


# ---------------------------------------------------------------------------
# Slot invalide : ValueError attendu
# ---------------------------------------------------------------------------
class TestInvalidSlot:
    def test_raises_on_slot_7(self):
        kw = _neutral(1)
        with pytest.raises(ValueError, match="Invalid deployment action"):
            ActionDecoder._deployment_slot_order(_cols(**kw), DEPLOY_SLOT_BASE + 7)

    def test_raises_below_base(self):
        kw = _neutral(1)
        with pytest.raises(ValueError, match="Invalid deployment action"):
            ActionDecoder._deployment_slot_order(_cols(**kw), DEPLOY_SLOT_BASE - 1)


# ---------------------------------------------------------------------------
# Propriété commune : toutes les stratégies retournent une permutation valide
# ---------------------------------------------------------------------------
class TestReturnShape:
    @pytest.mark.parametrize("offset", range(7))
    def test_returns_valid_permutation(self, offset):
        n = 5
        kw = _neutral(n)
        kw["progress"] = list(range(n))
        kw["nearest_enemy"] = list(range(n))
        kw["nearest_objective"] = list(range(n))
        kw["center_distance"] = list(range(n))
        order = _order(_cols(**kw), offset)
        assert len(order) == n
        assert set(order.tolist()) == set(range(n))
