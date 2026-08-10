"""Répertoire de travail des scénarios MATÉRIALISÉS (override de `wall_ref`). Module feuille.

Un scénario matérialisé est celui que l'épisode joue RÉELLEMENT, murs réécrits compris.
`W40KEngine.reset` journalise son chemin RELATIF à la racine du dépôt — c'est ce que le replay
repasse à `/api/config/board` pour dessiner le décor de cet épisode-là, information qu'aucune
autre ligne du journal ne porte. Journaliser le scénario d'ORIGINE à la place serait faux : ses
murs ne sont pas ceux joués.

DEUX contraintes, et elles ne sont satisfaites qu'ensemble :

1. **Sous `config/`.** `/api/config/board` refuse tout `scenario_file` hors de ce répertoire
   (`services/api_server.py`, « scenario_file must be under config/ »). Un scénario écrit dans
   `/tmp` faisait refuser l'épisode par le moteur ; l'écrire ailleurs sous le dépôt le faisait
   passer, mais le replay répondait alors 500 au chargement du décor. On écrit donc dans
   `config/local/`, déjà gitignoré et hors de l'énumération des agents.

2. **Survivre au processus.** Le replay est ouvert APRÈS le run. Un nettoyage `atexit` effaçait
   le fichier avant que quiconque puisse le lire. La purge se fait donc à la CRÉATION, sur les
   répertoires d'anciens runs, jamais sur celui du run en cours — ni sur celui d'un run ENCORE
   VIVANT, si vieux soit-il (cf. `_OWNER_PID_FILE` : le critère d'âge seul tuait les runs de
   plus de 24 h).

Deux appelants sans chemin d'import entre eux (`ai/bot_evaluation.py` pour l'éval,
`ai/train.py` pour l'entraînement) matérialisaient chacun dans `/tmp` : la contrainte vit ici
plutôt qu'en double.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time

# `config/local/` est gitignoré (.gitignore) et n'est enumeré par aucun chargeur de config.
_SCRATCH_SUBPATH = os.path.join("config", "local", "scenario_scratch")

# Les scénarios du run PRÉCÉDENT restent lisibles par le replay ; au-delà, ils ne servent plus
# personne. Purge à la création, pas à la sortie — un `atexit` détruirait le run qu'on vient de
# jouer.
_STALE_AFTER_SECONDS = 24 * 3600

# EMPREINTE du processus propriétaire (`<boot_id> <pid> <date de démarrage>`), déposée dans son
# répertoire de travail. Un répertoire dont le propriétaire VIT n'est jamais effacé, quel que
# soit son âge. Le nom du fichier est resté `OWNER_PID` — son contenu s'est enrichi le même jour,
# un PID nu ne distinguant pas un processus d'un homonyme réattribué par le noyau.
#
# POURQUOI CE FICHIER EXISTE. L'âge seul ne dit pas si un répertoire sert encore. Le scénario est
# écrit UNE fois au démarrage (`ai/train.py`, « if not os.path.exists ») : la date du répertoire
# se fige là et ne bouge plus de tout le run. Un entraînement de 47 h — la durée d'un retrain
# complet de ce dépôt — voyait donc son propre scénario effacé à la 24ᵉ heure par n'importe quel
# run démarré après lui : une éval, un autre training, ou simplement `pytest`. Le scénario
# Armageddon étant en `agent_roster_ref: training_random`, le moteur le RELIT à chaque épisode
# (`should_reload_scenario`) — le run mourait en `FileNotFoundError` à l'épisode suivant.
_OWNER_PID_FILE = "OWNER_PID"


def repo_root() -> str:
    """Racine du dépôt — MÊME dérivation que `engine.w40k_core.repo_relative_scenario_path`."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _boot_id() -> str:
    """Identifiant du démarrage courant du noyau, ou chaîne vide s'il n'est pas lisible.

    Il change à chaque reboot : une empreinte qui ne porte pas le même boot_id désigne un
    processus d'AVANT le redémarrage, donc mort à coup sûr. Sans lui, un PID réattribué après
    reboot ferait passer un répertoire mort pour vivant, et la purge s'arrêterait pour toujours.
    """
    try:
        with open("/proc/sys/kernel/random/boot_id", "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


#: `_process_start_time` rend cette valeur quand `/proc` répond que le processus N'EXISTE PAS.
#: Distincte de `None`, qui veut dire « on n'a pas pu savoir » : confondre les deux fait effacer
#: le répertoire d'un run VIVANT mais invisible (`/proc` en `hidepid`, autre utilisateur, autre
#: namespace PID) — l'inverse de ce que ce module garantit.
_PROCESS_ABSENT = "absent"


def _proc_is_readable() -> bool:
    """`/proc` répond-il pour CE processus ?

    Sonde de disponibilité du système de fichiers lui-même. Elle porte sur soi parce que c'est le
    seul PID dont on sait qu'il existe : un `/proc/<autre>/stat` absent est une INFORMATION (ce
    processus est mort), pas une panne.
    """
    try:
        with open(f"/proc/{os.getpid()}/stat", "r", encoding="utf-8"):
            return True
    except OSError:
        return False


def _process_start_time(pid: int):
    """Date de démarrage du processus (champ 22 de `/proc/<pid>/stat`).

    TROIS issues, et les confondre coûte un run :
      - une chaîne : la date, le processus existe et est lisible ;
      - `_PROCESS_ABSENT` : `/proc` fonctionne et ne connaît pas ce PID — le processus est mort ;
      - `None` : indéterminable (permission refusée, E/S, `/proc` absent) — on ne sait RIEN.

    C'est cette date qui distingue un PID d'un PROCESSUS. Le noyau réattribue les numéros — en
    quelques heures sur une machine chargée — et un run de 47 h vit assez longtemps pour croiser
    un homonyme. Deux processus de même PID ont des dates de démarrage différentes.

    `comm` (champ 2) peut contenir espaces et parenthèses : on découpe donc après la DERNIÈRE
    parenthèse fermante, pas sur le premier espace.
    """
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
            contenu = handle.read()
    except FileNotFoundError:
        # `/proc` lisible + ce PID absent = processus mort. `/proc` injoignable = on ne sait pas.
        return _PROCESS_ABSENT if _proc_is_readable() else None
    except OSError:
        # EACCES (`hidepid`, autre utilisateur), EIO… : le processus peut très bien vivre.
        return None
    fin_comm = contenu.rfind(")")
    if fin_comm == -1:
        return None
    champs = contenu[fin_comm + 2:].split()
    # `starttime` est le 22e champ du fichier, donc le 20e après `pid` et `comm`.
    return champs[19] if len(champs) >= 20 else None


def _process_fingerprint(pid: int):
    """Empreinte identifiant un PROCESSUS précis : `<boot_id> <pid> <date de démarrage>`.

    `None` si l'identité ne peut pas être établie — `/proc` muet, date illisible. Écrire une
    empreinte INCOMPLÈTE (`" 12345 "`) serait pire que ne rien écrire : relue, elle ne compte pas
    trois éléments, donc elle vaut « vivant » par fail-safe, et pour toujours. La purge devenait
    définitivement inerte sans que rien ne le signale.
    """
    boot = _boot_id()
    debut = _process_start_time(pid)
    if not boot or debut is None or debut == _PROCESS_ABSENT:
        return None
    return f"{boot} {pid} {debut}"


def _owner_is_alive(path: str) -> bool:
    """Le processus qui a créé ce répertoire tourne-t-il encore ?

    SENS DE L'ERREUR, délibéré : en cas de doute on répond OUI, donc on ne purge pas. Un
    répertoire gardé de trop coûte quelques kilo-octets ; un répertoire effacé sous un run vivant
    coûte le run — c'est précisément le défaut que ce fichier PID existe pour fermer.

    Une SEULE condition rend le verdict « mort » : le fichier d'empreinte est ABSENT (répertoire
    créé avant ce mécanisme, alors soumis au seul critère d'âge), ou l'empreinte enregistrée ne
    correspond plus au processus qui porte ce PID aujourd'hui. Tout le reste — fichier vide,
    tronqué, illisible, `/proc` indisponible, permission refusée — vaut VIVANT.
    """
    pid_path = os.path.join(path, _OWNER_PID_FILE)
    try:
        with open(pid_path, "r", encoding="utf-8") as handle:
            enregistree = handle.read().strip()
    except FileNotFoundError:
        return False
    except OSError:
        # Illisible n'est pas mort : une erreur d'E/S ne dit rien du processus propriétaire.
        return True
    if not enregistree:
        return True
    morceaux = enregistree.split()
    if len(morceaux) != 3:
        # Format inconnu (version antérieure, écriture interrompue) : on ne tranche pas.
        return True
    try:
        pid = int(morceaux[1])
    except ValueError:
        return True
    debut = _process_start_time(pid)
    if debut is None:
        # Indéterminable : permission refusée, E/S, `/proc` injoignable. On ne sait RIEN du
        # processus, et ne rien savoir n'est pas une preuve de mort.
        return True
    if debut is _PROCESS_ABSENT:
        # `/proc` fonctionne et ne connaît pas ce PID : le propriétaire est bien mort.
        return False
    # Le PID existe. Reste à savoir si c'est LE MÊME processus : un numéro réattribué, ou un
    # redémarrage de la machine, donnent une empreinte différente.
    return f"{_boot_id()} {pid} {debut}" == enregistree


def _purge_stale(scratch_root: str) -> None:
    """Efface les répertoires de travail des runs révolus. Silencieux sur un répertoire déjà
    disparu ou en cours d'écriture par un autre processus : ce n'est pas une erreur métier.

    DEUX conditions, et il faut les deux : le répertoire est vieux ET son propriétaire est mort.
    L'âge seul effaçait le répertoire d'un run encore en cours (cf. `_OWNER_PID_FILE`).
    """
    now = time.time()
    for name in os.listdir(scratch_root):
        path = os.path.join(scratch_root, name)
        if not os.path.isdir(path):
            continue
        try:
            if now - os.path.getmtime(path) <= _STALE_AFTER_SECONDS:
                continue
            if _owner_is_alive(path):
                continue
            shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def make_scenario_scratch_dir(prefix: str) -> str:
    """Crée un répertoire de travail sous `config/local/` et purge ceux des runs révolus.

    Le PID du processus courant y est déposé AVANT tout scénario : c'est ce qui protège ce
    répertoire de la purge d'un run démarré plus tard (cf. `_OWNER_PID_FILE`).
    """
    scratch_root = os.path.join(repo_root(), _SCRATCH_SUBPATH)
    os.makedirs(scratch_root, exist_ok=True)
    _purge_stale(scratch_root)
    path = tempfile.mkdtemp(prefix=prefix, dir=scratch_root)
    empreinte = _process_fingerprint(os.getpid())
    if empreinte is not None:
        with open(os.path.join(path, _OWNER_PID_FILE), "w", encoding="utf-8") as handle:
            handle.write(empreinte)
    # Empreinte indéterminable (`/proc` absent) : AUCUN fichier. Le répertoire retombe alors sur
    # le seul critère d'âge — le comportement d'avant ce mécanisme, imparfait mais actif. Écrire
    # une empreinte incomplète l'aurait rendu immortel et la purge inerte.
    return path
