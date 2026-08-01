"""Verrous du mecanisme de fermeture des environnements vectorises.

Ce que ces tests protegent, et pourquoi ca ne se voit pas a la lecture : un `SubprocVecEnv`
possede des PROCESSUS. Sans `close()`, personne ne leur demande de s'arreter — a la fin du run
ils sont tues par signal, n'executent aucun code de fin, et tout tampon non vide est perdu
(symptome constate : la queue de `perf_timing.log` de chaque worker, donc ses derniers episodes).
Aucun test ne cassait quand la fermeture disparaissait : le run se terminait normalement, seules
les DONNEES manquaient. D'ou ces verrous.
"""

from __future__ import annotations

import time

import pytest

import ai.train as train


class _FauxVecEnv:
    """Env minimal : compte ses fermetures, comme `SubprocVecEnv` en compte ses processus."""

    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


class _Wrapper:
    """Imite `VecNormalize` : expose l'env enveloppe via `.venv`, comme SB3."""

    def __init__(self, venv) -> None:
        self.venv = venv
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1
        self.venv.close()


@pytest.fixture(autouse=True)
def _registre_vide():
    """Le registre est un etat de module : le laisser sale contaminerait les tests suivants."""
    train._OPEN_VEC_ENVS.clear()
    yield
    train._OPEN_VEC_ENVS.clear()


def test_register_rend_l_env_inchange() -> None:
    env = _FauxVecEnv()
    assert train.register_vec_env(env) is env
    assert train._OPEN_VEC_ENVS == [env]


def test_fermeture_nominale_vide_le_registre() -> None:
    env = train.register_vec_env(_FauxVecEnv())
    train.close_training_env(env, "test")
    assert env.close_count == 1
    assert train._OPEN_VEC_ENVS == []


def test_balayage_ferme_ce_qui_reste() -> None:
    """Le filet de `main()` : ce qu'aucune fermeture nominale n'a atteint (exception, retour
    anticipe) doit tout de meme etre ferme."""
    a, b = train.register_vec_env(_FauxVecEnv()), train.register_vec_env(_FauxVecEnv())
    train.close_all_training_envs(log=lambda _m: None)
    assert (a.close_count, b.close_count) == (1, 1)
    assert train._OPEN_VEC_ENVS == []


def test_fermer_un_wrapper_desenregistre_l_env_enveloppe() -> None:
    """On ferme le plus souvent un `VecNormalize`, alors que c'est le `SubprocVecEnv` qu'il
    enveloppe qui est enregistre. Sans suivi de la chaine `.venv`, le balayage refermerait
    l'env deja ferme."""
    vec = train.register_vec_env(_FauxVecEnv())
    train.close_training_env(_Wrapper(vec), "test")
    assert vec.close_count == 1
    assert train._OPEN_VEC_ENVS == []
    train.close_all_training_envs(log=lambda _m: None)
    assert vec.close_count == 1


def test_fermeture_bloquee_rend_la_main_et_ne_reessaie_pas() -> None:
    """`SubprocVecEnv.close()` fait `recv()` puis `join()` SANS timeout : un worker bloque
    figerait la fin du run. La fermeture est bornee, et l'env sort du registre meme en cas
    d'expiration — sinon le balayage lancerait un SECOND `close()` concurrent du premier,
    toujours vivant, sur la meme connexion et les memes fils."""
    appels = []

    class _Bloquant:
        def close(self) -> None:
            appels.append(1)
            time.sleep(5)

    messages = []
    env = train.register_vec_env(_Bloquant())
    depart = time.perf_counter()
    train.close_training_env(env, "test", log=messages.append, timeout_s=0.3)
    duree = time.perf_counter() - depart

    assert duree < 3.0, "la fermeture n'est pas bornee dans le temps"
    assert train._OPEN_VEC_ENVS == []
    assert any("toujours en cours" in m for m in messages)
    train.close_all_training_envs(log=messages.append)
    assert len(appels) == 1, "un second close() a ete lance sur un env deja en fermeture"


def test_echec_de_fermeture_est_signale_et_non_leve() -> None:
    """Appelee depuis un `finally`, lever remplacerait l'exception d'entrainement en cours de
    propagation et masquerait la vraie cause. L'echec doit donc etre IMPRIME, pas leve."""
    class _Casse:
        def close(self) -> None:
            raise OSError("Broken pipe")

    messages = []
    train.close_training_env(train.register_vec_env(_Casse()), "test", log=messages.append)
    assert any("échouée" in m and "Broken pipe" in m for m in messages)


def test_env_absent_est_signale() -> None:
    messages = []
    train.close_training_env(None, "test", log=messages.append)
    assert any("aucun environnement" in m for m in messages)
