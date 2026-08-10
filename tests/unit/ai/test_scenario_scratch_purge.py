"""`ai/scenario_scratch.py` — la purge n'efface jamais le répertoire d'un run VIVANT.

LE DÉFAUT CORRIGÉ (2026-08-10). `_purge_stale` effaçait tout répertoire de plus de 24 h, sans
regarder s'il servait encore. Le scénario n'étant écrit qu'UNE fois au démarrage (`ai/train.py`,
« if not os.path.exists »), la date du répertoire se fige au début du run : un entraînement de
47 h — la durée d'un retrain complet ici — voyait son propre scénario supprimé à la 24ᵉ heure par
n'importe quel run démarré après lui (éval, autre training, ou `pytest` depuis que les tests
matérialisent eux aussi). Le scénario Armageddon étant en `agent_roster_ref: training_random`, le
moteur RELIT ce fichier à chaque épisode : le run mourait en `FileNotFoundError` juste après.

Ces tests manipulent la date des répertoires plutôt que d'attendre 24 h — la situation est
CONSTRUITE, pas espérée.
"""

from __future__ import annotations

import os
import time

import pytest

from ai.scenario_scratch import (
    _OWNER_PID_FILE,
    _STALE_AFTER_SECONDS,
    _process_fingerprint,
    _purge_stale,
    make_scenario_scratch_dir,
)


def _vieillir(path: str, secondes: int) -> None:
    """Recule la date de dernière modification du répertoire."""
    passe = time.time() - secondes
    os.utime(path, (passe, passe))


@pytest.fixture
def scratch_root(tmp_path):
    return str(tmp_path)


def _repertoire(scratch_root: str, empreinte: str | None, nom: str) -> str:
    """Répertoire de travail portant `empreinte`, ou AUCUN fichier d'empreinte si `None`."""
    path = os.path.join(scratch_root, nom)
    os.makedirs(path)
    if empreinte is not None:
        with open(os.path.join(path, _OWNER_PID_FILE), "w", encoding="utf-8") as handle:
            handle.write(empreinte)
    return path


def _empreinte_de_mort() -> str:
    """Empreinte d'un processus assurément mort, ROBUSTE au recyclage de PID.

    On lance un vrai processus, on attend sa fin, puis on enregistre son PID AVEC une date de
    démarrage qui n'est pas la sienne. Si le noyau réattribue ce numéro entre-temps — la suite
    tourne en `pytest -n 8`, c'est un cas réel —, l'empreinte du nouveau venu ne correspondra pas
    davantage : le verdict « mort » ne dépend plus de la disponibilité du numéro.
    """
    import subprocess

    from ai.scenario_scratch import _boot_id

    proc = subprocess.Popen(["true"])
    proc.wait()
    # Boot courant (sinon le verdict viendrait du reboot, pas de la mort du processus) et date de
    # démarrage IMPOSSIBLE : aucun processus vivant ne peut porter `0`.
    return f"{_boot_id()} {proc.pid} 0"


def test_un_run_vivant_garde_son_repertoire_meme_tres_vieux(scratch_root):
    """LE VERROU. 47 h d'âge, propriétaire vivant → intact.

    C'est le cas exact qui tuait un retrain complet.
    """
    # Ce processus-ci est vivant, par construction : son empreinte est celle d'un run en cours.
    path = _repertoire(scratch_root, _process_fingerprint(os.getpid()), "run_vivant")
    _vieillir(path, 47 * 3600)

    _purge_stale(scratch_root)

    assert os.path.isdir(path), "le répertoire d'un run VIVANT a été effacé"


def test_un_run_mort_et_vieux_est_efface(scratch_root):
    """Contre-épreuve : sans elle, une purge qui n'efface plus RIEN passerait le test ci-dessus."""
    path = _repertoire(scratch_root, _empreinte_de_mort(), "run_mort_vieux")
    _vieillir(path, 47 * 3600)

    _purge_stale(scratch_root)

    assert not os.path.exists(path), "le répertoire d'un run mort et révolu n'est pas nettoyé"


def test_un_run_mort_mais_recent_est_garde(scratch_root):
    """Le replay ouvre le scénario APRÈS le run : un run tout juste fini reste lisible."""
    path = _repertoire(scratch_root, _empreinte_de_mort(), "run_mort_recent")
    _vieillir(path, _STALE_AFTER_SECONDS // 2)

    _purge_stale(scratch_root)

    assert os.path.isdir(path), "le répertoire d'un run récent doit rester lisible par le replay"


def test_un_repertoire_sans_pid_reste_soumis_a_l_age(scratch_root):
    """Répertoire créé AVANT ce mécanisme : le critère d'âge seul s'applique, comme avant.

    Sans ce cas, les répertoires antérieurs s'accumuleraient pour toujours.
    """
    path = _repertoire(scratch_root, None, "run_sans_empreinte")
    _vieillir(path, 47 * 3600)

    _purge_stale(scratch_root)

    assert not os.path.exists(path), "un répertoire sans PID et révolu doit être nettoyé"


def test_l_empreinte_est_deposee_a_la_creation():
    """VERT VACANT : les tests ci-dessus ne valent que si la vraie fabrique pose l'empreinte.

    Et elle doit être celle de CE processus : une empreinte déposée mais fausse protégerait le
    répertoire d'un run vivant aussi mal qu'une empreinte absente.
    """
    import shutil

    path = make_scenario_scratch_dir("test_pid_")
    try:
        pid_path = os.path.join(path, _OWNER_PID_FILE)
        assert os.path.isfile(pid_path), f"aucun {_OWNER_PID_FILE} déposé dans {path}"
        with open(pid_path, encoding="utf-8") as handle:
            assert handle.read().strip() == _process_fingerprint(os.getpid())
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_un_proprietaire_invisible_vaut_vivant(scratch_root, monkeypatch):
    """`/proc/<pid>/stat` en PERMISSION REFUSÉE : le processus vit peut-être, on ne purge pas.

    Cas réels : `/proc` monté en `hidepid=1/2`, run appartenant à un autre utilisateur, autre
    namespace PID. Une lecture refusée ne dit RIEN du processus — la confondre avec « absent »
    effaçait le répertoire d'un run vivant, exactement le défaut que ce module ferme.
    """
    import ai.scenario_scratch as module

    path = _repertoire(scratch_root, _process_fingerprint(os.getpid()), "run_invisible")
    _vieillir(path, 47 * 3600)

    vrai_open = open
    cible = f"/proc/{os.getpid()}/stat"

    def open_refuse(fichier, *args, **kwargs):
        # On refuse la lecture de CE pid seulement : la sonde `_proc_is_readable` porte sur le
        # même chemin, donc le test couvre aussi le cas où elle serait mal aiguillée.
        if str(fichier) == cible:
            raise PermissionError(13, "Permission denied", str(fichier))
        return vrai_open(fichier, *args, **kwargs)

    monkeypatch.setattr(module, "open", open_refuse, raising=False)
    _purge_stale(scratch_root)

    assert os.path.isdir(path), "un propriétaire ILLISIBLE a été pris pour un propriétaire mort"


def test_aucune_empreinte_ecrite_si_l_identite_est_indeterminable(scratch_root, monkeypatch):
    """`/proc` muet : pas de fichier plutôt qu'une empreinte incomplète.

    Une empreinte `" 12345 "` se relit en un seul élément, donc « format inconnu », donc
    « vivant » — pour toujours. La purge devenait définitivement inerte, en silence. Sans
    empreinte, le répertoire retombe sur le critère d'âge : imparfait, mais actif.
    """
    import shutil

    import ai.scenario_scratch as module

    monkeypatch.setattr(module, "_boot_id", lambda: "")
    path = module.make_scenario_scratch_dir("test_sans_proc_")
    try:
        assert not os.path.exists(os.path.join(path, _OWNER_PID_FILE)), (
            "une empreinte a été écrite alors que l'identité du processus est indéterminable"
        )
        # Et le répertoire reste purgeable, ce qui est tout l'enjeu.
        _vieillir(path, 47 * 3600)
        _purge_stale(os.path.dirname(path))
        assert not os.path.exists(path), "répertoire sans empreinte devenu immortel : purge inerte"
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_une_empreinte_illisible_vaut_vivant(scratch_root):
    """FAIL-SAFE : tout ce qui n'est pas une preuve de mort vaut VIVANT.

    Fichier vide (disque plein à la création), format inconnu (version antérieure, écriture
    interrompue), PID non numérique : aucun ne dit que le processus est mort. Les traiter comme
    tels rouvrirait exactement le défaut que ce mécanisme ferme — c'était le cas de la première
    version, dont le code contredisait sa propre docstring.
    """
    for nom, contenu in (
        ("vide", ""),
        ("tronque", "137c690e-dcfb"),
        ("pid_non_numerique", "bootid abc 123"),
        ("format_inconnu", "42"),
    ):
        path = _repertoire(scratch_root, contenu, f"run_{nom}")
        _vieillir(path, 47 * 3600)

    _purge_stale(scratch_root)

    survivants = sorted(os.listdir(scratch_root))
    assert len(survivants) == 4, (
        f"une empreinte illisible a été prise pour une preuve de mort : reste {survivants}"
    )
