"""La ligne d'effets est écrite AU CHANGEMENT, pas à la frontière de tour.

C'est le point qui décide de sa justesse. Le Waaagh! (24) se déclare en phase de COMMANDEMENT,
donc AU MILIEU du tour : une ligne écrite une fois par tour dirait « inactif » et ne serait
jamais corrigée — la capacité s'allume ensuite, et rien ne le dit. Le dépôt a déjà résolu ce
problème exact pour les points de victoire (`_log_objective_control_snapshot_if_changed`, dont le
commentaire explique que les VP bougent DANS les handlers, pas aux frontières).

La ligne porte aussi la CONTRIBUTION chiffrée de chaque effet, et non son seul nom : sans elle,
le lecteur devrait ré-encoder la règle (« waaagh ⇒ +1 »), donc en faire vivre une seconde
définition qui divergerait en silence le jour où la constante du moteur bouge.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ai.step_logger import StepLogger
from engine.w40k_core import W40KEngine


def _engine(tmp_path, turn: int = 1):
    logger = StepLogger(output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=1)
    eng = W40KEngine.__new__(W40KEngine)
    eng.step_logger = logger
    eng.game_state = {
        "turn": turn,
        "waaagh_called": {1: False, 2: False},
        "waaagh_active": {1: False, 2: False},
        "oath_target": {1: None, 2: None},
        "pending_oath_selection": None,
    }
    return eng, logger


def _effects_lines(tmp_path, logger) -> List[str]:
    logger._flush_buffer()
    return [l for l in (tmp_path / "step.log").read_text(encoding="utf-8").splitlines()
            if "EFFECTS:" in l]


def test_une_capacite_declaree_EN_COURS_de_tour_est_journalisee(tmp_path) -> None:
    """VERROU DU DÉFAUT ÉVITÉ : remplacer le test de changement par « une fois par tour » laisse
    la déclaration du Waaagh totalement muette (mesuré : 1 seule ligne, `P2 none`)."""
    eng, logger = _engine(tmp_path)
    eng._log_effects_snapshot_if_changed()
    eng.game_state["waaagh_active"][2] = True      # phase de commandement, milieu du tour
    eng._log_effects_snapshot_if_changed()
    eng._log_effects_snapshot_if_changed()          # inchangé : ne doit rien réécrire

    lines = _effects_lines(tmp_path, logger)
    assert len(lines) == 2, lines
    assert "P2 none" in lines[0], lines[0]
    assert "P2 waaagh=on" in lines[1], lines[1]


def test_les_deux_moities_du_waaagh_sont_chiffrees(tmp_path) -> None:
    """+1 Attaques ET +1 Force. Le second n'était représenté nulle part dans le journal."""
    eng, logger = _engine(tmp_path, turn=3)
    eng.game_state["waaagh_active"][1] = True
    eng._log_effects_snapshot_if_changed()

    line = _effects_lines(tmp_path, logger)[0]
    assert "T3 EFFECTS:" in line, line
    assert "waaagh_melee_atk=+1" in line, line
    assert "waaagh_melee_str=+1" in line, line
    assert "waaagh_invul=5" in line, line


def test_oath_passe_par_la_meme_ligne(tmp_path) -> None:
    """Une seule grammaire pour toutes les capacités : Oath était dérivé une SECONDE fois,
    indépendamment, sur les lignes de charge."""
    eng, logger = _engine(tmp_path)
    eng.game_state["oath_target"][1] = "104"
    eng._log_effects_snapshot_if_changed()

    line = _effects_lines(tmp_path, logger)[0]
    assert "P1 oath_target=104 oath_wound=+1" in line, line


def test_le_bonus_journalise_suit_la_constante_du_moteur(tmp_path) -> None:
    """La valeur écrite est celle que le moteur APPLIQUE, jamais une copie figée dans le log.

    Sans ce lien, deux définitions de la règle coexistent et la seconde diverge en silence.
    """
    import engine.game_state as gs_mod

    original = gs_mod.WAAAGH_MELEE_BONUS
    try:
        gs_mod.WAAAGH_MELEE_BONUS = 2
        eng, logger = _engine(tmp_path)
        eng.game_state["waaagh_active"][2] = True
        eng._log_effects_snapshot_if_changed()
        line = _effects_lines(tmp_path, logger)[0]
        assert "waaagh_melee_atk=+2" in line, line
    finally:
        gs_mod.WAAAGH_MELEE_BONUS = original
