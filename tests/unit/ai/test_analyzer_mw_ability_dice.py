"""Grammaire 9 — le compte d'une ligne `SUFFERS N Mortal Wounds` de capacité suit ses dés.

Avant ce contrôle, l'analyzer CROYAIT le compte : `MW:` (Hold Still and Say Aargh) n'était lu
par personne, et le D6 d'Exhortation of Rage n'atteignait même pas step.log. Un moteur qui
aurait infligé 5 blessures pour `MW:1,2`, ou 3 blessures sur un `Trigger:2`, passait vert.

Ce que ce fichier verrouille (`mw_ability_dice_error`, exercé par `parse_step_log`) :
- Hold Still : N = somme des D6 de `MW:` ;
- Exhortation : `Trigger:` 1-3 → N = 0 sans `MW:` ; 4-5 → N = le D3 unique de `MW:` ; 6 → N = 3
  sans `MW:` (datasheet : « 4-5: D3 mortal wounds. 6: 3 mortal wounds ») ;
- la faute est comptée au camp de la SOURCE (`[FROM:]`), dont c'est la capacité, et entre dans
  `error_totals['fight']` ;
- sur un journal de grammaire < 9 les dés ne sont pas garantis : aucune faute n'est inventée.
"""
from __future__ import annotations

import pytest

from ai.analyzer_rules import mw_ability_dice_error
from tests.unit.ai._fabriques import entete_step_log
from tests.unit.ai._fabriques import analyzer_config as fab_config

_OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))


class _Registry:
    units = {
        "PainBoy": {"HP_MAX": 3, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        "Grunt": {"HP_MAX": 12, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
    }


# Unité 1 (P1) = source ; unité 101 (P2) = victime, assez de PV pour survivre à chaque ligne.
_UNITS = (
    "[10:00:00] Unit 1 (PainBoy) P1: Starting position (20,20), HP_MAX=3 base=round/1\n"
    "[10:00:00] Unit 101 (Grunt) P2: Starting position (21,21), HP_MAX=12 base=round/1\n"
)


def _line(n: int, tag: str, segs: str) -> str:
    # Grammaire ≥ 2 : toute ligne qui applique des dégâts nomme la figurine allouée.
    alloc = " [ALLOC_MODEL: 101#0]" if n > 0 else " [NO ALLOC]"
    return (
        f"[10:00:02] E1 T1 P1 FIGHT : Unit 101(21,21) SUFFERS {n} Mortal Wounds "
        f"{tag}{segs} [FROM:1]{alloc} [R:+0.0] [SUCCESS]\n"
    )


def _parse(tmp_path, monkeypatch, body: str, *, log_grammar: int | None = 9):
    import ai.analyzer as an
    import ai.analyzer_config as ac_mod

    cfg = fab_config(unit_registry=_Registry(), unit_weapons_cache={})
    monkeypatch.setattr(ac_mod, "load_analyzer_config", lambda: cfg)
    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        body,
        inches_to_subhex=1,
        board="cols=40 rows=40",
        objectives=_OBJECTIVES,
        units=_UNITS,
        log_grammar=log_grammar,
    ))
    return an.parse_step_log(str(log))


# ---------------------------------------------------------------------------
# Le prédicat, cas par cas
# ---------------------------------------------------------------------------

HOLD = "mortal_wounds_on_critical_wound"
EXH = "mortal_wounds_on_fight_activation"


@pytest.mark.parametrize("brut, desc", [
    (7, "SUFFERS 7 Mortal Wounds [HOLD STILL AND SAY AARGH] MW:3,4 [FROM:1]"),
    (1, "SUFFERS 1 Mortal Wounds [HOLD STILL AND SAY AARGH] MW:1 [FROM:1]"),
])
def test_hold_still_coherent(brut, desc):
    assert mw_ability_dice_error(HOLD, brut, desc) is None


@pytest.mark.parametrize("brut, desc", [
    (5, "SUFFERS 5 Mortal Wounds [HOLD STILL AND SAY AARGH] MW:1,2 [FROM:1]"),   # 5 ≠ 3
    (3, "SUFFERS 3 Mortal Wounds [HOLD STILL AND SAY AARGH] [FROM:1]"),          # dés absents
    (7, "SUFFERS 7 Mortal Wounds [HOLD STILL AND SAY AARGH] MW:7 [FROM:1]"),     # D6 > 6
])
def test_hold_still_incoherent(brut, desc):
    assert mw_ability_dice_error(HOLD, brut, desc) is not None


@pytest.mark.parametrize("brut, desc", [
    (0, "SUFFERS 0 Mortal Wounds [EXHORTATION DE RAGE] Trigger:2 [FROM:1] [NO ALLOC]"),
    (2, "SUFFERS 2 Mortal Wounds [EXHORTATION DE RAGE] Trigger:4 MW:2 [FROM:1]"),
    (1, "SUFFERS 1 Mortal Wounds [EXHORTATION DE RAGE] Trigger:5 MW:1 [FROM:1]"),
    (3, "SUFFERS 3 Mortal Wounds [EXHORTATION DE RAGE] Trigger:6 [FROM:1]"),
])
def test_exhortation_coherente(brut, desc):
    assert mw_ability_dice_error(EXH, brut, desc) is None


@pytest.mark.parametrize("brut, desc", [
    (3, "SUFFERS 3 Mortal Wounds [EXHORTATION DE RAGE] Trigger:2 [FROM:1]"),       # raté mais blessures
    (0, "SUFFERS 0 Mortal Wounds [EXHORTATION DE RAGE] Trigger:5 [FROM:1]"),       # 4-5 sans D3
    (3, "SUFFERS 3 Mortal Wounds [EXHORTATION DE RAGE] Trigger:5 MW:2 [FROM:1]"),  # compte ≠ D3
    (2, "SUFFERS 2 Mortal Wounds [EXHORTATION DE RAGE] Trigger:6 [FROM:1]"),       # 6 → 3 attendu
    (3, "SUFFERS 3 Mortal Wounds [EXHORTATION DE RAGE] Trigger:6 MW:3 [FROM:1]"),  # 6 sans dé
    (2, "SUFFERS 2 Mortal Wounds [EXHORTATION DE RAGE] MW:2 [FROM:1]"),            # Trigger absent
    (2, "SUFFERS 2 Mortal Wounds [EXHORTATION DE RAGE] Trigger:4 MW:4 [FROM:1]"),  # D3 > 3
])
def test_exhortation_incoherente(brut, desc):
    assert mw_ability_dice_error(EXH, brut, desc) is not None


def test_capacite_inconnue_leve():
    with pytest.raises(KeyError):
        mw_ability_dice_error("deadly_demise", 1, "SUFFERS 1 Mortal Wounds")


# ---------------------------------------------------------------------------
# Le chemin de production : parse_step_log
# ---------------------------------------------------------------------------

def test_journal_coherent_ne_compte_aucune_faute(tmp_path, monkeypatch):
    body = (
        _line(3, "[HOLD STILL AND SAY AARGH]", " MW:1,2")
        + _line(2, "[EXHORTATION DE RAGE]", " Trigger:4 MW:2")
        + _line(0, "[EXHORTATION DE RAGE]", " Trigger:1")
    )
    stats = _parse(tmp_path, monkeypatch, body)
    assert not stats["parse_errors"], stats["parse_errors"]
    assert stats["mw_ability_dice_mismatch"] == {1: 0, 2: 0}


def test_compte_faux_est_une_faute_au_camp_de_la_source(tmp_path, monkeypatch):
    """ROUGE sans le contrôle : `MW:1,2` pour 5 blessures passait — l'analyzer croyait le 5."""
    body = _line(5, "[HOLD STILL AND SAY AARGH]", " MW:1,2")
    stats = _parse(tmp_path, monkeypatch, body)
    assert stats["mw_ability_dice_mismatch"] == {1: 1, 2: 0}, stats["mw_ability_dice_mismatch"]
    first = stats["first_error_lines"]["mw_ability_dice_mismatch"][1]
    assert first is not None and "5 ≠ somme" in first["line"], first
    from ai.analyzer import error_totals
    assert error_totals(stats)["fight"] >= 1, "la faute doit peser sur le total de mêlée"


def test_trigger_rate_avec_blessures_est_une_faute(tmp_path, monkeypatch):
    body = _line(3, "[EXHORTATION DE RAGE]", " Trigger:2")
    stats = _parse(tmp_path, monkeypatch, body)
    assert stats["mw_ability_dice_mismatch"][1] == 1


def test_jet_rate_compte_un_usage_mais_aucune_blessure(tmp_path, monkeypatch):
    """Un `Trigger:` raté est un EXERCICE de la règle (le dé a été jeté) sans dégât : l'usage §1.7
    est relevé, la victime garde ses points de vie."""
    body = _line(0, "[EXHORTATION DE RAGE]", " Trigger:3")
    stats = _parse(tmp_path, monkeypatch, body)
    assert stats["special_rule_usage"][("mortal_wounds_on_fight_activation", "PainBoy")][1] == 1
    assert not stats["current_episode_deaths"]
    assert stats["mw_ability_dice_mismatch"] == {1: 0, 2: 0}


def test_ancienne_grammaire_ne_juge_pas_les_des(tmp_path, monkeypatch):
    """Avant la grammaire 9 les dés n'étaient pas garantis : une ligne sans `Trigger:` ni `MW:`
    est un vieux format, pas une faute."""
    body = _line(2, "[EXHORTATION DE RAGE]", "")
    stats = _parse(tmp_path, monkeypatch, body, log_grammar=8)
    assert stats["mw_ability_dice_mismatch"] == {1: 0, 2: 0}
    stats = _parse(tmp_path, monkeypatch, body, log_grammar=9)
    assert stats["mw_ability_dice_mismatch"][1] == 1, "en grammaire 9 le segment est exigible"
