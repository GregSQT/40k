"""Un journal sous `MIN_SUPPORTED_LOG_GRAMMAR` est REFUSÉ à l'ouverture.

C'est le verrou unique qui remplace la dizaine de gardes `state.log_grammar >= N` retirées le
2026-09-19. Elles suspendaient chacune un contrôle sur les journaux antérieurs ; puisque ces
journaux ne sont plus lus (décision utilisateur), le lecteur ne sait plus s'abstenir et
compterait des fautes INVENTÉES — mesuré avant le chantier : une ligne de dégâts sans `[FNP:]`
contre une escouade porteuse d'un Feel No Pain comptait 1 faute en grammaire 7 comme en 17,
sans un mot.

POURQUOI UNE CONSTANTE DISTINCTE DE `LOG_GRAMMAR_VERSION`, et c'est l'objet du dernier test :
adosser le refus au numéro courant du producteur rendrait illisible, au prochain incrément, le
step.log d'un run de la veille ou d'un run EN COURS — un journal qui n'a pourtant rien de
défectueux. La borne ne bouge que par décision explicite.
"""
from __future__ import annotations

import pathlib

import pytest

from ai.step_logger import LOG_GRAMMAR_VERSION, MIN_SUPPORTED_LOG_GRAMMAR
from tests.unit.ai._fabriques import entete_step_log

_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (20,20), HP_MAX=2 base=round/1"
    " [MODELS: 1#0@(20,20,z0)] [MODEL_TYPES: 1#0=Intercessor]\n"
)
_END = ("[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n")


def _journal(tmp_path, log_grammar):
    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        _END, units=_UNITS, ez_vertical_inches=None, log_grammar=log_grammar,
        rosters="scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=ork (ref)",
    ))
    return str(log)


def test_un_journal_sous_la_version_minimale_est_refuse(tmp_path):
    import ai.analyzer as an

    with pytest.raises(ValueError, match=r"grammaire \d+, la plus ancienne lisible"):
        an.parse_step_log(_journal(tmp_path, MIN_SUPPORTED_LOG_GRAMMAR - 1))


def test_l_entete_sans_ligne_de_version_est_refusee(tmp_path):
    """Son absence vaut la grammaire 1, qui ne veut plus dire « vieux journal » mais
    « journal qu'on ne sait plus lire ».

    La ligne est retirée du texte produit : la fabrique la déclare maintenant d'office, et
    c'est bien l'entête AMPUTÉE qu'il faut présenter au lecteur.
    """
    import ai.analyzer as an

    log = tmp_path / "ampute.log"
    entier = pathlib.Path(_journal(tmp_path, MIN_SUPPORTED_LOG_GRAMMAR)).read_text(encoding="utf-8")
    ampute = entier.replace(f"[10:00:00] Log grammar: {MIN_SUPPORTED_LOG_GRAMMAR}\n", "")
    assert ampute != entier, "prémisse : la ligne de version devait être présente"
    log.write_text(ampute, encoding="utf-8")

    with pytest.raises(ValueError, match=r"grammaire 1, la plus ancienne lisible"):
        an.parse_step_log(str(log))


def test_le_message_nomme_la_version_lue_et_la_version_attendue(tmp_path):
    """Un refus qui ne dit pas ce qu'il attend laisse chercher : les deux nombres y sont."""
    import ai.analyzer as an

    with pytest.raises(ValueError) as exc:
        an.parse_step_log(_journal(tmp_path, 3))
    message = str(exc.value)
    assert "grammaire 3" in message, message
    assert str(MIN_SUPPORTED_LOG_GRAMMAR) in message, message


def test_la_version_minimale_est_acceptee(tmp_path):
    """VERT VACANT écarté : sans ce test, un refus qui prendrait TOUT passerait pour correct."""
    import ai.analyzer as an

    stats = an.parse_step_log(_journal(tmp_path, MIN_SUPPORTED_LOG_GRAMMAR))
    assert stats["total_episodes"] == 1, stats["total_episodes"]


def test_une_version_plus_recente_que_connue_reste_acceptee(tmp_path):
    """Un journal plus récent porte au moins ce que promettent les versions antérieures."""
    import ai.analyzer as an

    stats = an.parse_step_log(_journal(tmp_path, LOG_GRAMMAR_VERSION + 5))
    assert stats["total_episodes"] == 1, stats["total_episodes"]


def test_la_borne_ne_suit_pas_le_numero_courant_du_producteur():
    """Le refus est adossé à une constante DISTINCTE, jamais à `LOG_GRAMMAR_VERSION`.

    Les deux valent 17 aujourd'hui, et c'est un accident de calendrier : ce qui est verrouillé
    ici, c'est qu'elles soient deux objets séparés. Les confondre ferait basculer tous les
    journaux de la veille dans le refus au prochain incrément du producteur, pendant qu'un run
    en cours écrit encore l'ancienne version.
    """
    import ai.step_logger as sl

    assert "MIN_SUPPORTED_LOG_GRAMMAR" in sl.__all__
    assert MIN_SUPPORTED_LOG_GRAMMAR <= LOG_GRAMMAR_VERSION, (
        "la borne ne peut pas exiger une version que le producteur n'écrit pas encore"
    )
