"""La ligne `[HAZARDOUS]` (24.15) n'atteignait JAMAIS step.log.

Symptôme visible pendant un entraînement : `⚠️ Step logging error: 'Hazardous action missing
required unit_with_coords'`. Mais l'avertissement défile dans une barre de progression, et
`log_action` avale l'exception : la ligne est perdue sans que rien ne s'arrête.

Mesuré sur un run de 12 épisodes : **zéro** ligne `HAZARD` dans le journal, alors que le type
figure bien dans `_STEP_LOG_TYPE_MAP`. Deux verrous se cumulaient, tous deux côté PRODUCTEUR :

1. le payload moteur ne portait ni `col`/`row` ni `toCol`/`toRow`, donc
   `_build_step_log_details` ne construisait pas `unit_with_coords` — que le formateur exige ;
2. il ne portait pas non plus le nombre de blessures mortelles en champ structuré (seulement
   dans le texte de `result`, « 3 MW »), que le formateur exige aussi.

Les deux données étaient DÉJÀ calculées à l'émission, pour le message. Elles n'étaient
simplement pas exposées.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from ai.step_logger import StepLogger
from engine.w40k_core import W40KEngine


def _details(raw_log: Dict[str, Any]) -> Dict[str, Any]:
    eng = W40KEngine.__new__(W40KEngine)
    eng.game_state = {}
    return eng._build_step_log_details(raw_log, pre_action_turn=1)


def _payload(**over: Any) -> Dict[str, Any]:
    """Le payload que `hazardous_test` construit réellement (champs utiles au formateur)."""
    base = {
        "type": "hazard",
        "message": "Unit 3 BigMek(12,7) [HAZARD] roll (shoot): 1 rolls - 1 fail(s) - 3 mortal wound(s)",
        "turn": 2,
        "phase": "shoot",
        "unitId": 3,
        "player": 1,
        "col": 12,
        "row": 7,
        "hazardousMortalWounds": 3,
        "result": "3 MW",
        "hazardDetails": [],
    }
    base.update(over)
    return base


def test_la_ligne_hasardeuse_est_formatable(tmp_path) -> None:
    """VERROU : c'est exactement l'appel que faisait le drainage, et qui levait."""
    logger = StepLogger(output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=1)
    msg = logger._format_replay_style_message("3", "hazardous", _details(_payload()))
    assert msg == "Unit 3(12,7) SUFFERS 3 Mortal Wounds [HAZARDOUS]", msg


def test_sans_coordonnees_la_ligne_est_perdue(tmp_path) -> None:
    """Le premier des deux verrous, remis : le formateur lève, donc `log_action` avale."""
    logger = StepLogger(output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=1)
    sans_pos = _payload()
    del sans_pos["col"]
    del sans_pos["row"]
    with pytest.raises(KeyError, match="unit_with_coords"):
        logger._format_replay_style_message("3", "hazardous", _details(sans_pos))


def test_sans_blessures_mortelles_la_ligne_est_perdue(tmp_path) -> None:
    """Le second verrou. Corriger les coordonnées seules n'aurait rien débloqué."""
    logger = StepLogger(output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=1)
    sans_mw = _payload()
    del sans_mw["hazardousMortalWounds"]
    with pytest.raises(Exception):
        logger._format_replay_style_message("3", "hazardous", _details(sans_mw))


def test_le_payload_du_moteur_porte_bien_les_deux_champs() -> None:
    """VERROU CÔTÉ PRODUCTEUR : le formateur peut être juste, si le moteur ne fournit rien la
    ligne reste perdue. On vérifie la source, pas seulement le lecteur."""
    import inspect

    from engine.phase_handlers import shared_utils

    src = inspect.getsource(shared_utils)
    i = src.index('"type": "hazard"')
    payload = src[i:]
    assert '"col": col' in payload, "le payload hasardeux ne porte plus la position"
    assert '"hazardousMortalWounds"' in payload, (
        "le payload hasardeux ne porte plus le nombre de blessures mortelles"
    )
    assert '"hazardContext": context_label' in payload, (
        "le payload hasardeux ne porte plus hazardContext — "
        "l'analyzer ne peut plus distinguer Desperate Escape de HAZARDOUS"
    )


def test_desperate_escape_utilise_tag_distinct() -> None:
    """VERROU : un jet de Desperate Escape (09.07) doit produire [DESPERATE ESCAPE]
    dans step.log, jamais [HAZARDOUS] — pour que l'analyzer n'exige pas d'arme HAZARDOUS."""
    logger = StepLogger(output_file="/dev/null", enabled=True, buffer_size=1)
    payload = _payload(hazardContext="Desperate Escape")
    msg = logger._format_replay_style_message("3", "hazardous", _details(payload))
    assert "[DESPERATE ESCAPE]" in msg, msg
    assert "[HAZARDOUS]" not in msg, msg


def test_hazardous_weapon_utilise_tag_hazardous() -> None:
    """VERROU jumeau : un jet d'arme HAZARDOUS (24.15) doit garder [HAZARDOUS]."""
    logger = StepLogger(output_file="/dev/null", enabled=True, buffer_size=1)
    payload = _payload(hazardContext="Hazardous")
    msg = logger._format_replay_style_message("3", "hazardous", _details(payload))
    assert "[HAZARDOUS]" in msg, msg
    assert "[DESPERATE ESCAPE]" not in msg, msg


def test_sans_hazard_context_tag_hazardous_par_defaut() -> None:
    """Rétro-compatibilité : un payload sans hazardContext produit [HAZARDOUS] (défaut)."""
    logger = StepLogger(output_file="/dev/null", enabled=True, buffer_size=1)
    msg = logger._format_replay_style_message("3", "hazardous", _details(_payload()))
    assert "[HAZARDOUS]" in msg, msg
