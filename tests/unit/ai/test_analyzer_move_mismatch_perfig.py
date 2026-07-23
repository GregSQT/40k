"""Contrôle 2.2 (cohérence position/log) en per-figurine.

Régression verrouillée (2026-07-23). Le contrôle comparait l'ancre d'escouade mémorisée à
l'ancre « from » loggée, à l'égalité EXACTE. Or le moteur peut ré-émettre une ancre d'escouade
décalée de ±1 subhex entre une consolidation (`to (166,98)`) et l'advance suivant
(`from (166,97)`) sans qu'aucun socle n'ait bougé → faux « position/log incohérent » (2 sur
un run réel, zéro vrai problème).

Correctif : `move_start_is_inconsistent` juge la cohérence sur l'EMPREINTE des figurines de
départ connues (dernier segment [MODELS:]). L'ancre « from » doit tomber dans cette empreinte —
le bruit de recalcul d'ancre est absorbé, une vraie téléportation reste détectée.
"""
from __future__ import annotations

from ai.analyzer_perfig import move_start_status, squad_footprint

BASE = ("round", 6)  # socle réel des logs (SM / Orks) → empreinte de 19 subhexes
MODELS = {"105#0": (166, 98)}


def test_exact_anchor_is_exact() -> None:
    """Départ = ancre mémorisée : statut 'exact'."""
    assert move_start_status(MODELS, BASE, (166, 98), 166, 98) == "exact"


def test_anchor_rounding_noise_is_absorbed_not_mismatch() -> None:
    """Ancre « from » à ±1 subhex de la figurine connue (≠ ancre mémorisée mais dans
    l'empreinte) : statut 'absorbed' — tracé pour info, jamais compté comme incohérence."""
    assert (166, 97) in squad_footprint(MODELS, BASE)
    assert move_start_status(MODELS, BASE, (166, 98), 166, 97) == "absorbed"


def test_real_teleport_is_still_flagged() -> None:
    """Départ hors de l'empreinte des socles connus (téléportation / log manquant) : 'mismatch'."""
    assert (220, 20) not in squad_footprint(MODELS, BASE)
    assert move_start_status(MODELS, BASE, (166, 98), 220, 20) == "mismatch"


def test_falls_back_to_exact_anchor_without_models() -> None:
    """Sans données per-figurine (log sans [MODELS:]) : repli sur l'égalité d'ancre exacte."""
    assert move_start_status(None, BASE, (166, 98), 166, 97) == "mismatch"
    assert move_start_status(None, BASE, (166, 98), 166, 98) == "exact"
