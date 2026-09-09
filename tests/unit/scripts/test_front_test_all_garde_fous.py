"""Les garde-fous de `scripts/front_test_all.sh` — l'orchestrateur des trois couches front.

CE QUE CE FICHIER VERROUILLE, et le défaut qui l'a fait écrire (mesuré le 2026-09-09).

`npx vite` n'est qu'un LANCEUR : le `node .../vite --port 5198` qu'il crée ne meurt pas avec lui.
Le `trap cleanup` du script tuait le PID de `npx`, pas ce petit-fils. Chaque exécution laissait donc
un serveur vivant — constaté : un Vite d'un worktree DEPUIS LONGTEMPS SUPPRIMÉ écoutait encore.

Le run suivant voyait « Port 5198 is already in use », son propre Vite mourait, et le script
continuait quand même : Playwright pilotait alors le serveur de l'AUTRE run, avec son ancienne
configuration de proxy. Les tests ne mesuraient plus l'arbre de travail, ils mesuraient un
fantôme — et rendaient « terrain-list: HTTP 500 » alors que l'API, elle, répond 200.

C'est le pire mode de panne d'un harnais : il ne s'arrête pas, il ment. D'où deux invariants, l'un
qui empêche de laisser l'orphelin (`setsid` + kill de groupe), l'autre qui refuse de démarrer si
quelqu'un occupe déjà la place.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
SCRIPT = RACINE / "scripts" / "front_test_all.sh"


@pytest.fixture(scope="module")
def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_le_script_est_syntaxiquement_valide() -> None:
    """Un `bash -n` : le reste du fichier lit le script, celui-ci vérifie qu'il s'exécuterait."""
    resultat = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert resultat.returncode == 0, resultat.stderr


def test_vite_est_lance_dans_son_propre_groupe(source: str) -> None:
    """`setsid` : sans lui, `cleanup` ne peut pas tuer le `node vite` que `npx` a engendré."""
    assert "setsid npx vite" in source, (
        "Vite n'est plus lancé par `setsid` : son processus enfant survivra au script et "
        "squattera le port pour tous les runs suivants."
    )


def test_le_nettoyage_tue_le_groupe_et_pas_seulement_le_pid(source: str) -> None:
    assert 'kill -- "-$pid"' in source, (
        "`cleanup` ne tue plus le GROUPE de processus : le petit-fils `node vite` survivra."
    )


@pytest.mark.parametrize("appelant", ["spawn_backend", "FRONT_C"])
def test_chaque_serveur_verifie_que_sa_place_est_libre(source: str, appelant: str) -> None:
    """Les DEUX serveurs sont gardés : un backend fantôme fausse autant qu'un frontend fantôme."""
    assert source.count("port_libre_ou_echoue") >= 3, (
        "la garde de port doit être définie ET appelée pour le backend ET pour Vite ; "
        f"occurrences trouvées : {source.count('port_libre_ou_echoue')}"
    )


def test_l_interpreteur_manquant_est_dit_tout_de_suite(source: str) -> None:
    """Diagnostic immédiat plutôt que 30 s d'attente d'un serveur qui n'a jamais démarré.

    Le cas se produit dans un worktree, qui n'a pas de `.venv` : le message d'origine était un
    `No such file or directory` noyé, suivi d'un timeout qui accusait le réseau.
    """
    assert 'if [ ! -x "$VENV" ]' in source, "l'absence d'interpréteur n'est plus détectée"
    assert "worktree" in source, "le message doit dire OÙ ce script se lance"


def _port_libre() -> int:
    """Un port réellement libre, pour ne pas dépendre d'un numéro écrit en dur."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(shutil.which("curl") is None, reason="la garde interroge le port avec curl")
def test_la_garde_refuse_un_port_occupe_et_laisse_passer_un_port_libre(tmp_path) -> None:
    """La garde EXERCÉE, pas seulement lue : un vrai serveur, un vrai refus.

    La fonction est extraite du script plutôt que sourcée en entier — sourcer le script
    exécuterait les trois couches, ce que ce test n'a aucune raison de faire.
    """
    lignes = SCRIPT.read_text(encoding="utf-8").splitlines()
    debut = next(i for i, l in enumerate(lignes) if l.startswith("port_libre_ou_echoue()"))
    fin = next(i for i in range(debut, len(lignes)) if lignes[i] == "}")
    garde = "\n".join(lignes[debut:fin + 1])

    occupe = _port_libre()
    serveur = subprocess.Popen(
        ["python3", "-m", "http.server", str(occupe)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=tmp_path,
    )
    try:
        # Le serveur doit écouter avant qu'on l'interroge : on attend qu'il accepte une connexion.
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", occupe), timeout=0.1):
                    break
            except OSError:
                # `create_connection` échoue INSTANTANÉMENT sur un port fermé : sans cette pause,
                # les cent essais s'épuisent en quelques millisecondes et le témoin n'a pas encore
                # eu le temps d'ouvrir sa socket.
                time.sleep(0.05)
        else:
            pytest.fail("le serveur témoin n'a jamais écouté : le test ne prouverait rien")

        essai = tmp_path / "essai.sh"
        essai.write_text(textwrap.dedent(f"""\
            {garde}
            port_libre_ou_echoue {occupe} "temoin" && echo LIBRE || echo REFUSE
            port_libre_ou_echoue {_port_libre()} "temoin" && echo LIBRE || echo REFUSE
            """), encoding="utf-8")
        sortie = subprocess.run(["bash", str(essai)], capture_output=True, text=True).stdout
    finally:
        serveur.terminate()
        serveur.wait(timeout=10)

    assert sortie.split() == ["REFUSE", "LIBRE"], (
        f"la garde n'a pas distingué le port occupé du port libre : {sortie!r}"
    )
