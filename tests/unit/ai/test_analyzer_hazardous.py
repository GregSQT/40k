"""Tests TROU 1 : ligne `hazardous` (24.15) — lecteur de l'analyzer.

Comportements verrouillés :
- `hazardous_mortal_wounds[player]` est incrémenté du nombre de BM journalisées.
- `hazardous_no_hazardous_weapon[player]` est incrémenté si aucun type de l'escouade
  ne porte une arme HAZARDOUS dans la cache armurerie, ET que la ligne est en phase SHOOTING.
- `hazardous_no_hazardous_weapon_fight[player]` est incrémenté si la même erreur arrive
  en phase FIGHT.
- La présence d'une arme HAZARDOUS dans la cache supprime l'erreur.
- Sans ligne HAZARDOUS, les compteurs restent à 0.
"""
from __future__ import annotations

import pytest

from tests.unit.ai._fabriques import entete_step_log
from tests.unit.ai._fabriques import analyzer_config as fab_config

_OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))


class _Registry:
    """Registry minimal : HP_MAX/MOVE/MODEL_HEIGHT suffisent pour l'entête d'unité."""
    units = {
        "HazUnit": {
            "HP_MAX": 3,
            "MOVE": 6,
            "MODEL_HEIGHT": 1.0,
            "UNIT_RULES": [],
        },
    }

# Unité 1 (P1) déployée en (20,20) avec HP_MAX=3.
# Type "HazUnit" : inconnu de la config réelle → weapons_cache["HazUnit"] sera None.
_UNITS = (
    "[10:00:00] Unit 1 (HazUnit) P1: Starting position (20,20), HP_MAX=3 base=round/1\n"
    "[10:00:00] Unit 101 (HazUnit) P2: Starting position (21,21), HP_MAX=3 base=round/1\n"
)

# Grammaire : `Unit N(c,r) SUFFERS X Mortal Wounds [HAZARDOUS]` — §1.2 de analyzer_couverture.md.
# La ligne est émise dans la phase SHOOTING (après résolution des attaques de tir) ou FIGHT.
_HAZARDOUS_3_MW = (
    "[10:00:02] E1 T1 P1 SHOOTING : Unit 1(20,20) SUFFERS 3 Mortal Wounds [HAZARDOUS] "
    "[R:+0.0] [SUCCESS]\n"
)
_HAZARDOUS_FIGHT = (
    "[10:00:02] E1 T1 P1 FIGHT : Unit 1(20,20) SUFFERS 2 Mortal Wounds [HAZARDOUS] "
    "[R:+0.0] [SUCCESS]\n"
)

_END = (
    "[10:00:08] T1 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
    "[10:00:09] EPISODE END: Winner=2, Method=objectives, Actions=0, Steps=0, "
    "Total=0, Duration=1.000s\n"
)


def _parse(tmp_path, monkeypatch, body: str = "", weapons_cache=None):
    """Parse step.log en injectant une cache armurerie contrôlée.

    `parse_step_log` charge sa config via `from ai.analyzer_config import load_analyzer_config`
    (import local dans la fonction) : le monkeypatch cible le SYMBOLE dans le MODULE SOURCE,
    ce que la liaison locale re-lit à chaque appel.
    """
    import ai.analyzer as an
    import ai.analyzer_config as ac_mod

    cfg = fab_config(
        unit_registry=_Registry(),
        unit_weapons_cache=weapons_cache if weapons_cache is not None else {},
    )
    monkeypatch.setattr(ac_mod, "load_analyzer_config", lambda: cfg)

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        body,
        inches_to_subhex=1,
        board="cols=40 rows=40",
        objectives=_OBJECTIVES,
        units=_UNITS,
    ))
    return an.parse_step_log(str(log))


def test_hazardous_mortal_wounds_counter(tmp_path, monkeypatch):
    """VERROU : supprimer la branche HAZARDOUS de l'analyzer rend ce test ROUGE."""
    stats = _parse(tmp_path, monkeypatch, _HAZARDOUS_3_MW)
    assert stats["hazardous_mortal_wounds"][1] == 3, (
        "la ligne HAZARDOUS doit incrémenter hazardous_mortal_wounds du joueur 1 de 3"
    )
    assert stats["hazardous_mortal_wounds"][2] == 0


def test_hazardous_no_weapon_flagged_when_cache_empty(tmp_path, monkeypatch):
    """Sans arme HAZARDOUS dans la cache, `hazardous_no_hazardous_weapon` est incrémenté.

    Cache vide → `weapons_cache.get("HazUnit")` = None → aucun profil connu → erreur.
    Ce comportement verrouille que le manque de donnée est signalé, pas ignoré.
    """
    stats = _parse(tmp_path, monkeypatch, _HAZARDOUS_3_MW, weapons_cache={})
    assert stats["hazardous_no_hazardous_weapon"][1] == 1, (
        "avec une cache vide, aucun type ne porte d'arme HAZARDOUS : l'erreur doit être signalée"
    )


def test_hazardous_no_error_when_weapon_in_cache(tmp_path, monkeypatch):
    """Avec arme HAZARDOUS dans la cache, `hazardous_no_hazardous_weapon` reste à 0."""
    cache = {
        "HazUnit": [{"name": "Plasma Gun", "rules": ["HAZARDOUS"], "is_melee": False}],
    }
    stats = _parse(tmp_path, monkeypatch, _HAZARDOUS_3_MW, weapons_cache=cache)
    assert stats["hazardous_no_hazardous_weapon"][1] == 0, (
        "HazUnit porte un Plasma Gun HAZARDOUS : l'erreur ne doit pas être signalée"
    )


def test_no_hazardous_no_counter(tmp_path, monkeypatch):
    """Sans ligne HAZARDOUS, les trois compteurs restent à 0."""
    stats = _parse(tmp_path, monkeypatch)
    assert stats["hazardous_mortal_wounds"] == {1: 0, 2: 0}
    assert stats["hazardous_no_hazardous_weapon"] == {1: 0, 2: 0}
    assert stats["hazardous_no_hazardous_weapon_fight"] == {1: 0, 2: 0}


def test_hazardous_fight_phase_goes_to_fight_counter(tmp_path, monkeypatch):
    """VERROU finding 1 : HAZARDOUS déclenché en FIGHT phase → compteur fight, pas shoot.

    Supprimer la branche `phase == 'fight'` dans analyzer_core rend ce test ROUGE.
    """
    stats = _parse(tmp_path, monkeypatch, _HAZARDOUS_FIGHT, weapons_cache={})
    assert stats["hazardous_no_hazardous_weapon_fight"][1] == 1, (
        "erreur HAZARDOUS en FIGHT doit incrémenter hazardous_no_hazardous_weapon_fight"
    )
    assert stats["hazardous_no_hazardous_weapon"][1] == 0, (
        "erreur HAZARDOUS en FIGHT ne doit PAS incrémenter hazardous_no_hazardous_weapon (shoot)"
    )


# PROJ.1.2 faux positifs — Desperate Escape 09.07 produit [DESPERATE ESCAPE], pas [HAZARDOUS].
# L'analyzer ne doit pas comptabiliser ces lignes comme des erreurs HAZARDOUS.
_DESPERATE_ESCAPE_MW = (
    "[10:00:02] E1 T1 P1 MOVE : Unit 1(20,20) SUFFERS 2 Mortal Wounds [DESPERATE ESCAPE] "
    "[R:+0.0] [SUCCESS]\n"
)


def test_desperate_escape_ne_compte_pas_en_hazardous_mw(tmp_path, monkeypatch):
    """VERROU : [DESPERATE ESCAPE] (09.07) ne doit PAS incrémenter hazardous_mortal_wounds.

    Avant le fix, roll_hazard_for_unit émettait [HAZARDOUS] même pour les Desperate Escape,
    générant 337 faux positifs PROJ.1.2 ('unité sans arme HAZARDOUS').
    """
    stats = _parse(tmp_path, monkeypatch, _DESPERATE_ESCAPE_MW, weapons_cache={})
    assert stats["hazardous_mortal_wounds"][1] == 0, (
        "[DESPERATE ESCAPE] ne doit pas incrémenter hazardous_mortal_wounds (24.15 uniquement)"
    )


def test_desperate_escape_ne_declenche_pas_erreur_armurerie(tmp_path, monkeypatch):
    """VERROU : [DESPERATE ESCAPE] ne doit pas déclencher hazardous_no_hazardous_weapon.

    Peu importe si l'unité a ou non une arme HAZARDOUS dans la cache — le Desperate Escape
    est la règle 09.07, sans rapport avec 24.15.
    """
    stats = _parse(tmp_path, monkeypatch, _DESPERATE_ESCAPE_MW, weapons_cache={})
    assert stats["hazardous_no_hazardous_weapon"][1] == 0, (
        "[DESPERATE ESCAPE] ne doit pas signaler d'erreur HAZARDOUS (arme absente de l'armurerie)"
    )
    assert stats["hazardous_no_hazardous_weapon_fight"][1] == 0


