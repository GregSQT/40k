"""Ligne `SUFFERS N Mortal Wounds` d'une CAPACITÉ (06.02) — formateur du StepLogger.

Hold Still and Say Aargh et Exhortation de Rage empruntent la ligne générique des blessures
mortelles, mais avec leur propre tag : l'analyzer ne déclenche le contrôle d'armurerie de 24.15
que sur `[HAZARDOUS]`, et compter ces blessures-là y ferait remonter des « unité sans arme
HAZARDOUS » sur des unités qui n'en portent aucune.

Format attendu :
  SUFFERS 7 Mortal Wounds [HOLD STILL AND SAY AARGH] MW:3,4 [FROM:12] [ALLOC_MODEL: ...]
  SUFFERS 2 Mortal Wounds [EXHORTATION DE RAGE] Trigger:5 MW:2 [FROM:7] [ALLOC_MODEL: ...]

`MW:` est un segment SÉPARÉ de `Roll:` : celui-ci porte des jets de hasard comparés à un seuil,
celui-là les D6 qui donnent une quantité. Les confondre ferait sommer les uns par le contrôle
de validité appliqué aux autres. `Trigger:` est le troisième sens — le D6 de DÉCLENCHEMENT
d'Exhortation of Rage (4+) — et a donc son propre segment.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ai.step_logger import StepLogger
from shared.data_validation import HAZARD_CONTEXT_EXHORTATION, HAZARD_CONTEXT_HOLD_STILL


def _logger(output_file: Path) -> StepLogger:
    return StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)


def _details(
    *,
    mortal_wounds: int = 7,
    hazard_context: str = HAZARD_CONTEXT_HOLD_STILL,
    mw_dice: Optional[List[int]] = None,
    source_id: Optional[str] = "12",
    trigger: Optional[int] = None,
) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "current_turn": 1,
        "reward": 0.0,
        "unit_with_coords": "10(2,3)",
        "hazardous_mortal_wounds": mortal_wounds,
        "hazard_context": hazard_context,
    }
    if mw_dice is not None:
        d["mortal_wound_dice"] = mw_dice
    if trigger is not None:
        d["ability_trigger_roll"] = trigger
    if source_id is not None:
        d["mortal_wound_source_id"] = source_id
    if mortal_wounds > 0:
        d["target_model_id"] = "model-1"
    return d


def _emit(tmp_path: Path, details: Dict[str, Any]) -> str:
    log = tmp_path / "step.log"
    logger = _logger(log)
    logger.log_action(
        unit_id="10",
        action_type="hazardous",
        phase="fight",
        player=1,
        success=True,
        step_increment=True,
        action_details=details,
    )
    logger._flush_buffer()
    return log.read_text(encoding="utf-8")


def test_tag_hold_still(tmp_path: Path) -> None:
    """ROUGE avant le fix : le contexte n'était comparé qu'à Desperate Escape, tout le reste
    retombait sur `[HAZARDOUS]` — et ces blessures se comptaient comme du 24.15."""
    content = _emit(tmp_path, _details(mw_dice=[3, 4]))
    assert "[HOLD STILL AND SAY AARGH]" in content, content
    assert "[HAZARDOUS" not in content, f"tag 24.15 usurpé : {content}"


def test_tag_exhortation(tmp_path: Path) -> None:
    content = _emit(tmp_path, _details(hazard_context=HAZARD_CONTEXT_EXHORTATION, mw_dice=None))
    assert "[EXHORTATION DE RAGE]" in content, content


def test_de_de_declenchement_exhortation(tmp_path: Path) -> None:
    """ROUGE avant le fix : le D6 d'Exhortation n'atteignait pas step.log — il vivait dans le
    texte libre du Game Log (`(D6=n)`), que le formateur ne recopie pas. `Trigger:` précède
    `MW:` (le seuil avant la quantité) et reste distinct de `Roll:`."""
    content = _emit(tmp_path, _details(
        mortal_wounds=2, hazard_context=HAZARD_CONTEXT_EXHORTATION, mw_dice=[2], trigger=5,
    ))
    assert "[EXHORTATION DE RAGE] Trigger:5 MW:2 [FROM:12]" in content, content
    assert "Roll:" not in content, content


def test_jet_de_declenchement_rate(tmp_path: Path) -> None:
    """Un D6 ≤ 3 laisse sa ligne : 0 blessure, le dé, et `[NO ALLOC]`."""
    content = _emit(tmp_path, _details(
        mortal_wounds=0, hazard_context=HAZARD_CONTEXT_EXHORTATION, mw_dice=None, trigger=2,
    ))
    assert "SUFFERS 0 Mortal Wounds [EXHORTATION DE RAGE] Trigger:2 [FROM:12] [NO ALLOC]" in content, content


def test_des_de_blessures_mortelles(tmp_path: Path) -> None:
    """Le total seul ne dit pas de combien de jets il vient, donc ne permet pas de le
    contrôler : deux crits à D6 doivent laisser leurs deux dés dans la ligne."""
    content = _emit(tmp_path, _details(mw_dice=[3, 4]))
    assert "MW:3,4" in content, content
    assert "Roll:" not in content, f"`Roll:` est le segment de 24.15, pas celui-ci : {content}"


def test_source_nommee(tmp_path: Path) -> None:
    """Ces blessures viennent d'un ADVERSAIRE : sans `[FROM:]`, l'analyzer crédite la victime
    de ses propres morts."""
    content = _emit(tmp_path, _details(mw_dice=[3, 4]))
    assert "[FROM:12]" in content, content


def test_sans_source_pas_de_segment(tmp_path: Path) -> None:
    """[HAZARDOUS] et [DESPERATE ESCAPE] sont auto-infligées : rien à nommer."""
    content = _emit(tmp_path, _details(hazard_context="Desperate Escape", source_id=None))
    assert "[FROM:" not in content, content
