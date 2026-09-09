"""Verrous de la sonde `scripts/split_assigned_policy_probe.py`.

La sonde sert à trancher « les bits sont-ils exploités ». Ses deux façons de MENTIR sont :

- déclarer une contrefactuelle pure alors qu'autre chose a bougé — le TVD mesurerait ce autre
  chose, et le verdict serait faux dans le sens FAVORABLE ;
- rendre un TVD faux.

Les deux sont verrouillés ici. Le reste de la sonde (rollouts, chargement de modèle) n'est pas
testable sans moteur ni poids : il est couvert par ses propres contrôles à l'exécution (plancher
exactement nul, sonde non muette), qui font sortir la sonde en code 2 plutôt que de rendre un
rapport illisible.
"""
import numpy as np
import pytest

from scripts.split_assigned_policy_probe import SPLIT_BIT_IDX, _bits_only, _tvd


def _obs(bin_rows: np.ndarray, cont_rows: np.ndarray) -> dict:
    return {"enemies_bin": bin_rows, "enemies_cont": cont_rows}


def test_tvd_bornes():
    """0 pour deux distributions égales, 1 pour deux masses disjointes."""
    p = np.array([0.25, 0.25, 0.5])
    assert _tvd(p, p) == 0.0
    assert _tvd(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == pytest.approx(1.0)
    assert _tvd(np.array([0.5, 0.5]), np.array([1.0, 0.0])) == pytest.approx(0.5)


def test_contrefactuelle_pure_acceptee():
    """Deux observations ne différant QUE par les bits : c'est le cas que la sonde veut mesurer."""
    a_bin = np.zeros((4, 38), dtype=np.float32)
    b_bin = a_bin.copy()
    a_bin[1, SPLIT_BIT_IDX[0]] = 1.0
    b_bin[2, SPLIT_BIT_IDX[0]] = 1.0
    cont = np.ones((4, 21), dtype=np.float32)
    assert _bits_only(_obs(a_bin, cont), _obs(b_bin, cont.copy())) is True


def test_contrefactuelle_impure_refusee_sur_une_autre_colonne_du_meme_bloc():
    """Une colonne NON-bit qui bouge doit être refusée : sinon le TVD la mesurerait elle aussi."""
    a_bin = np.zeros((4, 38), dtype=np.float32)
    b_bin = a_bin.copy()
    a_bin[1, SPLIT_BIT_IDX[0]] = 1.0
    b_bin[2, SPLIT_BIT_IDX[0]] = 1.0
    b_bin[0, 3] = 1.0  # une colonne quelconque hors des dix bits
    cont = np.ones((4, 21), dtype=np.float32)
    assert _bits_only(_obs(a_bin, cont), _obs(b_bin, cont.copy())) is False


def test_contrefactuelle_impure_refusee_sur_une_autre_cle():
    """Une AUTRE clé d'observation qui bouge doit être refusée, pas seulement `enemies_bin`."""
    a_bin = np.zeros((4, 38), dtype=np.float32)
    b_bin = a_bin.copy()
    a_bin[1, SPLIT_BIT_IDX[0]] = 1.0
    b_bin[2, SPLIT_BIT_IDX[0]] = 1.0
    cont_a = np.ones((4, 21), dtype=np.float32)
    cont_b = cont_a.copy()
    cont_b[0, 0] = 42.0
    assert _bits_only(_obs(a_bin, cont_a), _obs(b_bin, cont_b)) is False


def test_les_dix_bits_sont_lus_du_registre():
    """Les colonnes viennent du registre, jamais d'un index recopié qui se périmerait."""
    from engine.observation_entities import (
        K_WEAPONS_RANGED,
        split_assigned_field,
        unit_bin_index,
    )

    assert SPLIT_BIT_IDX == tuple(
        unit_bin_index(split_assigned_field(i)) for i in range(K_WEAPONS_RANGED)
    )
