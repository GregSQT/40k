"""Helpers de config partagés pour les tests moteur.

But : éviter que chaque fixture réinvente un sous-ensemble de ``game_rules`` qui
diverge du contrat moteur réel. Les fixtures partent désormais des vraies règles
(config/game_config.json) et n'overrident que les valeurs sensibles au test.
Conséquence : l'ajout d'une nouvelle règle requise (ex: detection_range) ne casse
plus les tests — la clé est présente automatiquement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "game_config.json"


def _real_game_rules() -> Dict[str, Any]:
    return json.loads(_CONFIG_PATH.read_text())["game_rules"]


def build_game_rules(**overrides: Any) -> Dict[str, Any]:
    """``game_rules`` réels (toutes les clés requises par le moteur) + overrides de test.

    Les overrides servent à neutraliser les valeurs sensibles aux tests
    (ex: cover_ratio=0.0, engagement_zone=1).
    """
    rules = _real_game_rules()
    rules.update(overrides)
    return rules


def _real_move_rules() -> Dict[str, Any]:
    return json.loads(_CONFIG_PATH.read_text())["move"]


def build_move_rules(**overrides: Any) -> Dict[str, Any]:
    """``move`` réels (toggles de traversée, Règles 03.01) + overrides de test."""
    rules = _real_move_rules()
    rules.update(overrides)
    return rules
