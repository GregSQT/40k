"""07.02 — ordre des phases par joueur.

Les phases doivent se succéder dans l'ordre COMMAND→MOVE→SHOOT→CHARGE→FIGHT au sein d'un tour,
mais la séquence est vérifiée PAR JOUEUR : P1 peut faire FIGHT dans son demi-tour avant que P2
ne fasse CHARGE dans le sien — c'est la règle 40K (chaque joueur joue ses 5 phases à son tour).
L'alternance du joueur ouvrant COMMAND n'est PAS vérifiée : en 40K la priorité est déterminée
par roll-off, aucune alternance stricte n'est imposée par les règles.

Mécanisme : `phase_seq_current_turn` (dict player→list) accumule les phases vues par joueur.
`_check_phase_seq` est appelé au changement de tour (et à EPISODE END pour le dernier tour).
"""
from __future__ import annotations

from pathlib import Path

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log

_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (5,5), HP_MAX=2 "
    "[MODELS: 1#0@(5,5,z0)]\n"
    "[10:00:00] Unit 2 (Intercessor) P2: Starting position (5,30), HP_MAX=2 "
    "[MODELS: 2#0@(5,30,z0)]\n"
)
_END = (
    "[12:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
    "Total=0, Duration=1.000s"
)


def _action(turn: int, player: int, phase: str, uid: str | None = None) -> str:
    return (
        f"[10:00:0{turn}] E1 T{turn} P{player} {phase} : "
        f"Unit {uid or str(player)}(5,5) WAITED [SUCCESS]"
    )


def _dead(turn: int, player_owner: int, phase: str, unit: int) -> str:
    """Ligne 'dead' : l'unité de player_owner meurt pendant la phase <phase> (souvent celle de l'adversaire)."""
    return (
        f"[10:00:0{turn}] E1 T{turn} P{player_owner} {phase} : "
        f"Unit {unit} DEAD model={unit}#0 reason=combat [SUCCESS]"
    )


def _run(tmp_path: Path, body: list[str]) -> dict:
    path = tmp_path / "step.log"
    path.write_text(
        entete_step_log(
            "\n".join(body) + "\n" + _END + "\n",
            units=_UNITS,
            inches_to_subhex=1,
            board="cols=44 rows=60",
            walls="none",
            metric_ranged="hex",
            rosters="scale=500pts AGENT_PLAYER=1 AGENT=a (a.json) OPPONENT=o (o.json)",
            objectives=None,
        ),
        encoding="utf-8",
    )
    return an.parse_step_log(str(path))


def test_ordre_correct_ne_declenche_pas_de_violation(tmp_path: Path) -> None:
    """VERROU : COMMAND→MOVE→SHOOT = séquence valide, 0 violation."""
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),
        _action(1, 1, "MOVE"),
        _action(1, 1, "SHOOT"),
    ])
    assert stats["phase_order_violations"] == 0, stats["phase_order_violations"]


def test_retour_en_arriere_declenche_une_violation(tmp_path: Path) -> None:
    """07.02 — MOVE après SHOOT dans le même tour = violation d'ordre."""
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),
        _action(1, 1, "SHOOT"),
        _action(1, 1, "MOVE"),   # antérieur à SHOOT → violation
    ])
    assert stats["phase_order_violations"] == 1, stats["phase_order_violations"]


def test_sequence_isolee_a_un_seul_tour_validee_a_episode_end(tmp_path: Path) -> None:
    """La séquence du DERNIER tour est validée à EPISODE END, pas seulement au changement de tour."""
    # Un seul tour → _check_phase_seq déclenché seulement à EPISODE END.
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),
        _action(1, 1, "FIGHT"),    # saute MOVE/SHOOT/CHARGE
        _action(1, 1, "MOVE"),     # retour en arrière → violation
    ])
    assert stats["phase_order_violations"] == 1, stats["phase_order_violations"]


def test_fight_p1_avant_charge_p2_meme_tour_pas_violation(tmp_path: Path) -> None:
    """07.02 — FIGHT(P1) avant CHARGE(P2) dans le même battle round = 0 violation.

    P1 saute CHARGE (aucune unité éligible) et passe à FIGHT. P2 fait ensuite COMMAND→CHARGE→FIGHT
    dans le même round. L'ancienne séquence partagée produisait [FIGHT, CHARGE] = faux positif.
    La séquence par joueur isole P1=[FIGHT] et P2=[COMMAND, CHARGE, FIGHT], toutes deux valides.
    """
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),
        _action(1, 1, "MOVE"),
        _action(1, 1, "SHOOT"),
        _action(1, 1, "FIGHT"),    # P1 saute CHARGE
        _action(1, 2, "COMMAND"),  # P2 ouvre son tour
        _action(1, 2, "CHARGE"),   # CHARGE après FIGHT(P1) dans le même T1 — doit rester 0 violation
        _action(1, 2, "FIGHT"),
    ])
    assert stats["phase_order_violations"] == 0, stats["phase_order_violations"]


def test_retour_en_arriere_par_joueur_detecte_violation(tmp_path: Path) -> None:
    """07.02 — MOVE après SHOOT CHEZ LE MÊME JOUEUR = violation même avec l'autre joueur entrelacé."""
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),
        _action(1, 1, "SHOOT"),
        _action(1, 2, "COMMAND"),   # entrelacement P2 — ne doit pas masquer la violation P1
        _action(1, 1, "MOVE"),      # retour en arrière chez P1 → violation
    ])
    assert stats["phase_order_violations"] == 1, stats["phase_order_violations"]


def test_p2_defense_avant_command_ignoree_violation_dans_propre_tour_detectee(tmp_path: Path) -> None:
    """07.02 — P2 fight en défenseur avant son COMMAND : ignoré. FIGHT→CHARGE dans son propre tour : violation.

    Scénario réel : P2 fight comme défenseur pendant le FIGHT de P1 (sans COMMAND P2 ouvert),
    puis P2 ouvre son tour (COMMAND) et enchaîne FIGHT→CHARGE (ordre invalide dans son propre tour).
    Les phases de défense pré-COMMAND ne polluent pas la séquence active de P2.
    """
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),
        _action(1, 1, "FIGHT"),    # P1 combat
        _action(1, 2, "FIGHT"),    # P2 défenseur pré-COMMAND : ignoré de la séquence P2
        _action(1, 2, "COMMAND"),  # P2 ouvre son propre tour → séquence P2 démarre ici
        _action(1, 2, "FIGHT"),    # P2 combat dans son propre tour
        _action(1, 2, "CHARGE"),   # CHARGE après FIGHT dans le propre tour P2 → violation
    ])
    assert stats["phase_order_violations"] == 1, stats["phase_order_violations"]


def test_p2_defense_pre_command_seule_aucune_violation(tmp_path: Path) -> None:
    """07.02 — P2 fight en défenseur avant son COMMAND, puis joue normalement : 0 violation."""
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),
        _action(1, 1, "FIGHT"),    # P1 combat
        _action(1, 2, "FIGHT"),    # P2 défenseur pré-COMMAND : ignoré
        _action(1, 2, "COMMAND"),  # P2 ouvre son tour
        _action(1, 2, "MOVE"),
        _action(1, 2, "CHARGE"),
        _action(1, 2, "FIGHT"),
    ])
    assert stats["phase_order_violations"] == 0, stats["phase_order_violations"]


def test_meme_joueur_ouvre_command_plusieurs_tours_consecutifs_aucune_violation(tmp_path: Path) -> None:
    """VERROU : P1 ouvre COMMAND à chaque tour (env d'entraînement) → 0 violation.

    En 40K la priorité de tour est déterminée par roll-off ; aucune alternance n'est imposée.
    """
    stats = _run(tmp_path, [
        _action(1, 1, "COMMAND"),
        _action(1, 1, "MOVE"),
        _action(2, 1, "COMMAND"),
        _action(2, 1, "MOVE"),
        _action(3, 1, "COMMAND"),
        _action(3, 1, "MOVE"),
    ])
    assert stats["phase_order_violations"] == 0, stats["phase_order_violations"]


def test_mort_en_phase_adverse_ne_pollue_pas_la_sequence_du_joueur(tmp_path: Path) -> None:
    """07.02 — §2.9 : l'event DEAD d'une unité P1 loggé pendant la SHOOT de P2 ne doit pas

    injecter SHOOT dans la séquence active de P1 après que P1 a déjà joué CHARGE.

    Scénario réel (E231 T2 P1) : P1 joue COMMAND→MOVE→CHARGE (SHOOT auto-sauté, 0 tireurs).
    P2 tire et tue une unité P1 → step.log produit une ligne
    « E1 T1 P1 SHOOT : Unit 1 DEAD model=1#0 reason=combat [SUCCESS] ».
    Sans le filtre, l'analyzer ajoute SHOOT à la séquence P1 → [COMMAND,MOVE,CHARGE,SHOOT,FIGHT]
    → violation §2.9. Avec le filtre, la ligne DEAD est ignorée → 0 violation.
    """
    stats = _run(tmp_path, [
        # P1 joue son tour sans phase de tir (aucun tireur éligible → SHOOT auto-sauté)
        _action(1, 1, "COMMAND"),
        _action(1, 1, "MOVE"),
        _action(1, 1, "CHARGE"),
        # P2 tire et tue l'unité 1 de P1 — player_owner=1 (propriétaire), phase=SHOOT (phase courante)
        _dead(1, 1, "SHOOT", 1),
        # P1 combat en mêlée
        _action(1, 1, "FIGHT"),
    ])
    assert stats["phase_order_violations"] == 0, stats["phase_order_violations"]
