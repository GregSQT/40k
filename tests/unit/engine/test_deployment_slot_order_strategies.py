"""Tests isolation de _deployment_slot_order pour les 7 stratégies (+0..+6).

Pas de moteur complet : la méthode est statique et ne dépend que de numpy.
Préférences vérifiées par mesure (scripts/_probe_slot_order.py) :
  progress : max (+0,+1,+5)  — absent de +2,+3,+4,+6
  nearest_enemy : min (+0,+1), max (+2,+3,+4,+6)  — absent de +5
  nearest_objective : toujours min
  los : toujours min
  center_distance : toujours min
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
# +6 : safe_rear — primary = nearest_enemy max (loin des ennemis)
# ---------------------------------------------------------------------------
class TestSlot6SafeRear:
    def test_nearest_enemy_prime_max(self):
        # hex 0 le plus loin des ennemis
        kw = _neutral(3)
        kw["nearest_enemy"] = [10.0, 3.0, 1.0]
        order = _order(_cols(**kw), 6)
        assert order[0] == 0  # nearest_enemy max = 10

    def test_objective_tiebreak_min(self):
        # nearest_enemy égal, nearest_objective min wins
        kw = _neutral(3)
        kw["nearest_enemy"] = [5.0, 5.0, 5.0]
        kw["nearest_objective"] = [8.0, 1.0, 4.0]
        order = _order(_cols(**kw), 6)
        assert order[0] == 1  # nearest_objective min = 1


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
