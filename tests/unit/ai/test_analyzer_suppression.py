"""`suppression_without_hit` (ai/analyzer_suppression.py) — Primitive F, grammaire 12.

Journal FABRIQUÉ (fabrique `entete_step_log`) : le WarTrakk 1 tire sur 101 et 102, puis la
ligne `SUPPRESSES` dit qui est supprimé. Un journal correct → 0 ; supprimée sans touche → 1 ;
malus `[SUPPRESSED]` sans suppression en vigueur → 1 ; suppression en vigueur sans malus → 1 ;
expiration à la phase de commandement du suppresseur ; grammaire 11 → abstention.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

_UNITS = (
    "[10:00:00] Unit 1 (WarTrakk) P1: Starting position (-1,-1), HP_MAX=7 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)
S, T1, T2 = "(50,50)", "(80,80)", "(80,50)"
_SETUP = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S}"
    f" [R:+0.0] [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T1} DEPLOYED from (-1,-1) to {T1}"
    f" [R:+0.0] [MODELS: 101#0@(80,80,z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102{T2} DEPLOYED from (-1,-1) to {T2}"
    f" [R:+0.0] [MODELS: 102#0@(80,50,z0)] [SUCCESS]\n"
)


def _shot(sec: int, target: str, pos: str, hit: bool, turn: int = 1) -> str:
    rolls = "Hit 5(4+) - Wound 5(4+) - → " + target + "#0 - Save 2(3+) - Dmg:1HP" if hit else "Hit 1(4+)"
    alloc = f" [ALLOC_MODEL: {target}#0]" if hit else ""
    return (
        f"[10:00:{sec:02d}] E1 T{turn} P1 SHOOT : Unit 1{S} SHOT [DESIGNATED:101] Unit {target}{pos}"
        f" with [Big Shoota] - {rolls} [R:+0.0] [MODELS: 1#0@(50,50,z0)]"
        f" [SHOOTER_MODELS: 1#0]{alloc} [SUCCESS]\n"
    )


def _suppresses(sec: int, target: str, pos: str, turn: int = 1) -> str:
    return (
        f"[10:00:{sec:02d}] E1 T{turn} P1 SHOOT : Unit 1{S} SUPPRESSES Unit {target}{pos}"
        f" [SUPPRESSED→{target}] [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n"
    )


def _enemy_shot(sec: int, shooter: str, pos: str, suppressed_token: bool, turn: int = 1) -> str:
    tag = " [SUPPRESSED]" if suppressed_token else ""
    return (
        f"[10:00:{sec:02d}] E1 T{turn} P2 SHOOT : Unit {shooter}{pos} SHOT{tag} [DESIGNATED:1] Unit 1{S}"
        f" with [Bolt Pistol] - Hit 5(4+) - Wound 5(4+) - → 1#0 - Save 2(3+) - Dmg:1HP [R:+0.0]"
        f" [MODELS: {shooter}#0@{pos[:-1]},z0)] [SHOOTER_MODELS: {shooter}#0] [ALLOC_MODEL: 1#0] [SUCCESS]\n"
    )


def _command(sec: int, player: int, turn: int) -> str:
    return f"[10:00:{sec:02d}] E1 T{turn} P{player} COMMAND : Unit 1{S} WAIT [R:+0.0] [SUCCESS]\n"


def _stats(tmp_path, body: str) -> dict:
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(_SETUP + body, units=_UNITS, ez_vertical_inches=None))
    return an.parse_step_log(str(log))


def test_journal_correct_zero_erreur(tmp_path):
    """101 touchée, 102 ratée, 101 supprimée ; 101 tire ensuite AVEC le malus, 102 sans."""
    body = (
        _shot(2, "101", T1, hit=True) + _shot(3, "102", T2, hit=False) + _suppresses(4, "101", T1)
        + _enemy_shot(5, "101", T1, suppressed_token=True) + _enemy_shot(6, "102", T2, suppressed_token=False)
    )
    stats = _stats(tmp_path, body)
    assert stats["suppression_without_hit"] == {1: 0, 2: 0}, stats["first_error_lines"]["suppression_without_hit"]


def test_supprimee_sans_touche_est_une_erreur(tmp_path):
    """102 RATÉE puis supprimée → 1 erreur chez le suppresseur (P1)."""
    body = _shot(2, "101", T1, hit=True) + _shot(3, "102", T2, hit=False) + _suppresses(4, "102", T2)
    stats = _stats(tmp_path, body)
    assert stats["suppression_without_hit"] == {1: 1, 2: 0}
    assert "sans l'avoir TOUCHÉE" in stats["first_error_lines"]["suppression_without_hit"][1]["detail"]


def test_malus_sans_suppression_en_vigueur_est_une_erreur(tmp_path):
    """102 n'est pas supprimée mais tire avec [SUPPRESSED] → 1 erreur chez P2."""
    body = _shot(2, "101", T1, hit=True) + _suppresses(3, "101", T1) + _enemy_shot(4, "102", T2, suppressed_token=True)
    stats = _stats(tmp_path, body)
    assert stats["suppression_without_hit"] == {1: 0, 2: 1}
    assert "sans suppression en vigueur" in stats["first_error_lines"]["suppression_without_hit"][2]["detail"]


def test_suppression_en_vigueur_sans_malus_est_une_erreur(tmp_path):
    """101 supprimée tire SANS [SUPPRESSED] → 1 erreur chez P2 (le -1 contrôlé au tir)."""
    body = _shot(2, "101", T1, hit=True) + _suppresses(3, "101", T1) + _enemy_shot(4, "101", T1, suppressed_token=False)
    stats = _stats(tmp_path, body)
    assert stats["suppression_without_hit"] == {1: 0, 2: 1}
    assert "SANS le malus" in stats["first_error_lines"]["suppression_without_hit"][2]["detail"]


def test_la_suppression_expire_a_la_phase_de_commandement_du_suppresseur(tmp_path):
    """Après la phase de commandement de P1 (tour 2), 101 tire sans malus : correct. Et une
    touche du tour 1 ne justifie plus une suppression au tour 2."""
    body = (
        _shot(2, "101", T1, hit=True) + _suppresses(3, "101", T1)
        + _command(4, 1, 2)
        + _enemy_shot(5, "101", T1, suppressed_token=False, turn=2)
        + _suppresses(6, "101", T1, turn=2)  # touche du tour 1 périmée → erreur
    )
    stats = _stats(tmp_path, body)
    assert stats["suppression_without_hit"] == {1: 1, 2: 0}

