"""Le writer partage par les DEUX barres d'avancement (entrainement et evaluation bot).

Elles se relaient sur la meme ligne de terminal : l'eval prend la main pendant que la boucle
d'entrainement est figee, puis la rend. Deux proprietes seulement, mais elles se paient cher
quand elles manquent — une queue de ligne qui traine rend une barre illisible, une exception
d'affichage arrete un run de 47 h.
"""

from __future__ import annotations

import sys
from typing import Any, Dict

import pytest

from shared.progress_writer import SHARED_LINE_LEN_KEY, ProgressWriter
from tests.unit.shared._stubs import RecordingStdout as _RecordingStdout


def test_progress_writer_erases_the_tail_of_the_previous_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L'effacement se calcule sur la ligne PRECEDENTE, et la longueur publiee est la nouvelle.

    C'est ce que l'AUTRE barre relit dans `line_length_state` pour reprendre la main proprement :
    une longueur publiee alors que l'ecriture a echoue lui ferait effacer une ligne qui n'a
    jamais ete affichee.
    """
    out = _RecordingStdout()
    monkeypatch.setattr(sys, "stdout", out)
    state: Dict[str, Any] = {}
    writer = ProgressWriter(state)

    writer.write("XXXXXXXX")
    writer.write("YY")

    assert out.writes == ["\rXXXXXXXX", "\rYY      "], "6 espaces effacent la queue de la 1re ligne"
    assert state[SHARED_LINE_LEN_KEY] == 2


def test_progress_writer_erases_the_line_left_by_the_other_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La poignee de main joue dans LES DEUX SENS, et c'est tout son interet.

    Un writer qui n'aurait ecrit que des lignes courtes ne sait pas, de lui-meme, que l'autre
    barre vient d'en afficher une longue : sans la relecture de l'etat partage, la reprise laisse
    sa queue a l'ecran. C'est le cas au retour d'une eval vers l'entrainement comme a l'entree
    d'une eval — les deux barres partagent le meme code, donc la meme correction.
    """
    out = _RecordingStdout()
    monkeypatch.setattr(sys, "stdout", out)
    state: Dict[str, Any] = {SHARED_LINE_LEN_KEY: 10}
    writer = ProgressWriter(state)

    writer.write("ABC")

    assert out.writes == ["\rABC       "], "7 espaces effacent la queue de la ligne de l'autre barre"
    assert state[SHARED_LINE_LEN_KEY] == 3, "la longueur publiee est celle qui est a l'ecran"


def test_progress_writer_survives_broken_stdout_and_stops_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une sortie cassee ne doit rien emporter, et ne doit pas tracer a chaque affichage.

    Sortie redirigee dans `head`, terminal ferme, session detachee : `sys.stdout.write` leve.
    Sans isolation ICI, cette exception d'affichage remonte au coeur de l'appelant — depuis le
    callback SB3 elle arrete l'entrainement lui-meme ; depuis le callback d'un episode d'eval
    elle sort de la collecte parallele avant `must_abort_pool` (pool jamais force-termine),
    depuis l'abandon en bloc elle tronque le denominateur du score, depuis la ligne finale elle
    perd des resultats DEJA agreges.

    L'ecriture est aussi le seul endroit ou avaler l'echec reste compatible avec T1 : les
    callbacks appelants, eux, valident le resultat du worker (`require_key`), et un `try/except`
    pose autour d'eux masquerait un contrat rompu.
    """
    out = _RecordingStdout(broken=True)
    monkeypatch.setattr(sys, "stdout", out)
    state: Dict[str, Any] = {}
    writer = ProgressWriter(state)

    writer.write("50% barre")
    writer.write("60% barre")
    writer.write("100% barre")

    assert len(out.writes) == 1, "affichage desactive au 1er echec, pas retente a chaque appel"
    assert state == {}, "aucune longueur publiee : rien n'a ete affiche"


def test_progress_writer_lock_is_per_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le verrou d'echec appartient a UNE barre, pas au processus.

    Les deux barres partagent le dict d'etat, pas leur sante : une eval dont l'affichage a casse
    ne doit pas eteindre celle du run suivant, ni la barre d'entrainement qui reprend la main.
    Un drapeau global (module ou classe) rendrait ce test rouge.
    """
    broken = _RecordingStdout(broken=True)
    monkeypatch.setattr(sys, "stdout", broken)
    state: Dict[str, Any] = {}
    ProgressWriter(state).write("eval sur une sortie cassee")

    healthy = _RecordingStdout()
    monkeypatch.setattr(sys, "stdout", healthy)
    ProgressWriter(state).write("barre suivante")

    assert healthy.writes == ["\rbarre suivante"], "un writer neuf affiche malgre l'echec du precedent"


def test_progress_writer_without_shared_state_still_erases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`line_length_state` est optionnel (run sans gate affichee) : pas de crash, pas de queue."""
    out = _RecordingStdout()
    monkeypatch.setattr(sys, "stdout", out)
    writer = ProgressWriter()

    writer.write("XXXXXXXX")
    writer.write("YY")

    assert out.writes == ["\rXXXXXXXX", "\rYY      "]


def test_progress_writer_survives_none_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    """sys.stdout = None ne doit pas se propager hors du writer.

    AttributeError (None n'a pas d'attribut write) n'etait pas attrape par
    except (OSError, ValueError). Sans ce test rouge, la regression se manifeste
    en production : depuis on_result() dans bot_evaluation.py, l'exception sort de
    la boucle de collecte avant must_abort_pool, et le ProcessPoolExecutor pend.
    """
    monkeypatch.setattr(sys, "stdout", None)
    writer = ProgressWriter()
    writer.write("test")
    assert writer._broken, "l'echec doit marquer le writer comme casse"
