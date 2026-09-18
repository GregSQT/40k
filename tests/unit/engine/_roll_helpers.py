"""Helpers de jets manuels partagés par les tests d'armes (tir et mêlée).

``_manual_roll_intent`` / ``_manual_roll_fight_intent`` renvoient ``None`` quand l'intent doit
être IGNORÉ (attaquant absent, cible hors du cache, index d'arme invalide…). Les tests d'armes
attendent tous un intent résolu : ces wrappers transforment ce ``None`` en échec explicite au
lieu d'un ``TypeError`` opaque au premier indexage, et donnent au type checker le
non-``None`` que les tests supposent.

Depuis le chantier « chaîne d'attaque 100 % » (04.03, option B), les deux rollers ne jettent
plus aucun dé : ils PRÉPARENT l'intent (profil + ``roll_spec``) et les jets ont lieu au début du
lot, par ``roll_prepared_intent``. Ces wrappers enchaînent les deux avec la politique de relance
par défaut (échecs seulement), et rendent le dict fusionné — la forme que les tests d'armes
lisaient quand le roller jetait lui-même (``shot_records``, ``pending_wounds``, ``counts``,
``pending_mortal_wounds``).
"""

from __future__ import annotations

from typing import Any, Dict

from engine.phase_handlers.fight_handlers import _manual_roll_fight_intent
from engine.phase_handlers.shared_utils import _manual_roll_intent, roll_prepared_intent

DEFAULT_POLICY: Dict[str, bool] = {"hit": False, "wound": False}


def roll_prepared(game_state: Dict[str, Any], prepared: Dict[str, Any], policy: Dict[str, bool] | None = None) -> Dict[str, Any]:
    """Jette un intent préparé et rend le dict fusionné (profil + jets)."""
    rolled = roll_prepared_intent(game_state, prepared, DEFAULT_POLICY if policy is None else policy)
    return {**prepared, **rolled}


def roll_shoot_intent(
    game_state: Dict[str, Any],
    intent: Dict[str, Any],
    targets_meta: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Jets de tir d'un intent — échoue si le moteur l'ignore."""
    result = _manual_roll_intent(game_state, intent, {} if targets_meta is None else targets_meta)
    assert result is not None, f"_manual_roll_intent a ignoré l'intent: {intent!r}"
    return roll_prepared(game_state, result)


def roll_fight_intent(
    game_state: Dict[str, Any],
    intent: Dict[str, Any],
    targets_meta: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Jets de mêlée d'un intent — échoue si le moteur l'ignore."""
    result = _manual_roll_fight_intent(
        game_state, intent, {} if targets_meta is None else targets_meta
    )
    assert result is not None, f"_manual_roll_fight_intent a ignoré l'intent: {intent!r}"
    return roll_prepared(game_state, result)
