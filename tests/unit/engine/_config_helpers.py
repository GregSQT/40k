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


#: Réglages PAR ÉPISODE qu'un test observant la phase de déploiement doit ÉPINGLER au lieu de
#: les subir. Injectés dans le ``training_config`` de l'INSTANCE — jamais dans le fichier de
#: config, qui porte une décision utilisateur (la rampe 0.0 → 0.8 est délibérée).
_ACTIVE_DEPLOYMENT_PINS: Dict[str, Dict[str, Any]] = {
    # Déploiement ACTIF à tous les épisodes. Le tirage du moteur est
    # ``random.random() < p_active`` ; ``random.random()`` vit dans [0.0, 1.0), donc p_active
    # = 1.0 rend « active » CERTAIN — déterminisme par construction, pas par chance.
    # ``start == end`` rend le tirage indépendant de la progression, donc de ``total_episodes``.
    # ``training_only: false`` l'affranchit du split de chemin ``/scenarios/training/``.
    "deployment_mode_schedule": {
        "enabled": True,
        "training_only": False,
        "active_ratio_start": 1.0,
        "active_ratio_end": 1.0,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
    },
    # Épinglé À L'ARRÊT. Activé, ``W40KEngine._should_force_random_deployment_action`` REMPLACE
    # l'action de déploiement choisie par une action valide tirée au hasard : un test qui pilote
    # le déploiement (clustering forcé, slot précis…) verrait ses choix silencieusement écrasés
    # et continuerait de passer en ne testant plus ce qu'il annonce.
    "deployment_random_mix": {
        "enabled": False,
        "training_only": False,
        "force_random_ratio_start": 0.0,
        "force_random_ratio_end": 0.0,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
        "apply_to": "agent_only",
    },
}


def pin_active_deployment(engine: Any) -> Any:
    """Force une phase de déploiement ACTIVE et reproductible. À appeler AVANT ``reset()``.

    POURQUOI CE HELPER EXISTE. Quatre fichiers observaient la phase de déploiement en la tenant
    pour acquise. Ils ne l'obtenaient en fait que parce que le profil ``x1_debug`` ne portait
    AUCUN bloc ``deployment_mode_schedule`` : ``_configure_deployment_mode_for_episode`` rendait
    ``None`` et le mode retombait sur le JSON du scénario (``active``). Le jour où les cinq
    profils ont reçu ce bloc avec ``active_ratio_start: 0.0``, le premier épisode est passé en
    placement figé et les quatre fichiers sont tombés d'un coup. **Un test ne doit pas dépendre
    de l'ABSENCE d'une configuration : il doit déclarer l'état de jeu qu'il exige.**

    CE QUE CE HELPER NE FAIT PAS. Il ne change ni le scénario, ni la géométrie, ni les graines,
    ni aucune règle de jeu : le déploiement passe par le VRAI chemin moteur (le scheduler tire
    « active », le moteur ouvre la phase et construit ses pools). Seul le tirage du MODE est
    forcé à la valeur que ces tests supposaient déjà. C'est ce qui permet de corriger sans
    toucher aux scénarios — et donc sans altérer les propriétés géométriques testées.

    Même technique que ``test_deployment_mode_schedule.py``, qui pilote ce mécanisme depuis le
    test. Retourne le moteur, pour s'enchaîner sur la construction.
    """
    if engine.training_config is None:
        raise ValueError(
            "pin_active_deployment: `engine.training_config` est None — ce helper s'applique "
            "aux moteurs construits sur un profil d'entraînement."
        )
    # Copie défensive AVANT écriture : `training_config` peut être l'objet même que sert le
    # cache de configuration. Le muter en place contaminerait les autres tests du process.
    engine.training_config = dict(engine.training_config)
    engine.training_config.update(_ACTIVE_DEPLOYMENT_PINS)
    return engine


def assert_deployment_phase(engine: Any) -> None:
    """Garde-fou commun : le moteur DOIT être en phase de déploiement après ``reset()``.

    C'est cette assertion qui a signalé la régression de la rampe. Elle reste en place dans
    chaque fichier : sans elle, un test de déploiement qui ne déploie plus passerait au vert.
    """
    phase = engine.game_state["phase"]
    if phase != "deployment":
        raise AssertionError(
            f"phase {phase!r} au lieu de 'deployment' malgré `pin_active_deployment`. "
            f"Le mécanisme de sélection du mode de déploiement a changé : réaligner "
            f"`_ACTIVE_DEPLOYMENT_PINS` sur le contrat du moteur, ne pas contourner l'assertion."
        )
