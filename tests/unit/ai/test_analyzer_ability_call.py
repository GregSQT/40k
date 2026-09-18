"""Relevé des appels de capacité (« ABILITY CALL <Nom> [USED|DECLINED] », engine/ability_calls.py).

La ligne DECLINED existe pour que l'analyzer distingue « refusé » de « jamais proposé » ; ce
verrou prouve que la ligne est CLASSÉE (branche dédiée, avant les verbes de jeu) et comptée par
capacité, verdict et joueur — et qu'un nom libre n'est pas lu comme une action de jeu.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

_UNITS = (
    "[10:00:00] Unit 1 (Boyz) P1: Starting position (-1,-1), HP_MAX=1 base=round/6\n"
    "[10:00:00] Unit 101 (Intercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)
_SETUP = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50)"
    " [R:+0.0] [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(80,80) DEPLOYED from (-1,-1) to (80,80)"
    " [R:+0.0] [MODELS: 101#0@(80,80,z0)] [SUCCESS]\n"
)


def _stats(tmp_path, body: str) -> dict:
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(_SETUP + body, units=_UNITS, ez_vertical_inches=None))
    return an.parse_step_log(str(log))


def test_ability_call_lines_are_counted_by_ability_verdict_and_player(tmp_path):
    body = (
        "[10:00:02] E1 T2 P1 COMMAND : Unit 1(50,50) ABILITY CALL Grot Orderly [DECLINED]"
        " [R:+0.0] [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n"
        "[10:00:03] E1 T3 P1 COMMAND : Unit 1(50,50) ABILITY CALL Grot Orderly [USED]"
        " [R:+0.0] [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n"
        "[10:00:04] E1 T3 P2 FIGHT : Unit 101(80,80) ABILITY CALL Finest Hour [USED]"
        " [R:+0.0] [MODELS: 101#0@(80,80,z0)] [SUCCESS]\n"
    )
    stats = _stats(tmp_path, body)
    counts = stats["ability_call_counts"]
    assert counts[("Grot Orderly", "DECLINED")] == {1: 1, 2: 0}
    assert counts[("Grot Orderly", "USED")] == {1: 1, 2: 0}
    assert counts[("Finest Hour", "USED")] == {1: 0, 2: 1}
    # La ligne n'est pas lue comme une action de jeu : aucune erreur inventée.
    assert stats["shoot_over_rng_nb"] == {1: 0, 2: 0}


def test_no_ability_call_line_means_no_count(tmp_path):
    stats = _stats(tmp_path, "")
    assert dict(stats["ability_call_counts"]) == {}
