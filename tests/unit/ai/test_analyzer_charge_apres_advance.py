"""Charge après Advance (11.02 / Waaagh!) — un seul verdict pour CHARGED et FAILED CHARGE.

11 Charge phase : « rules that prevent a unit from being eligible to declare a charge: … It
made an advance or fall-back move this turn. » `Armageddon/Waaagh!.txt` : « units from your
army with this ability are eligible to declare a charge in a turn in which they Advanced. »

Ce que ce fichier verrouille (`_judge_charge_after_advance`, `ai/analyzer_phases/charge_handler.py`) :
- la DÉCLARATION précède le jet : un FAILED CHARGE après Advance est jugé comme un CHARGED —
  mesuré sur le run du 2026-09-11, 114 déclarations après Advance n'aboutissaient qu'en FAILED
  CHARGE et aucune n'était jugée (`PROJ.1.3.apres_advance` restait « JAMAIS EXERCÉE ») ;
- le Waaagh! se lit dans l'ÉTAT (`T{n} EFFECTS:` + mot-clé de faction du type), pas sur le
  marqueur `[WAAAGH!]` que le moteur écrit lui-même : le marqueur est contre-contrôlé ;
- la capacité de datasheet `charge_after_advance` blanchit aussi, et en premier ;
- une unité qui n'a pas avancé n'exerce pas ce contrôle.
"""
from __future__ import annotations

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log

OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

#: Boyz (ORKS, porte le Waaagh! par mot-clé), BloodClaw (capacité de datasheet
#: `charge_after_advance`), Intercessor (ni l'un ni l'autre). Tous les trois sont dans le registre.
_UNITS = (
    "[10:00:00] Unit 1 (Boyz) P1: Starting position (-1,-1), HP_MAX=1\n"
    "[10:00:00] Unit 2 (BloodClaw) P1: Starting position (-1,-1), HP_MAX=2\n"
    "[10:00:00] Unit 3 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2\n"
)

_DEPLOY = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2(50,60) DEPLOYED from (-1,-1) to (50,60) [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 3(50,70) DEPLOYED from (-1,-1) to (50,70) [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [SUCCESS]\n"
)
_WAAAGH_ON = "[10:00:01] T1 EFFECTS: P1 waaagh=on waaagh_melee_atk=+1 | P2 none\n"
_WAAAGH_OFF = "[10:00:01] T1 EFFECTS: P1 none | P2 none\n"


def _advance(uid: int, row: int) -> str:
    return (
        f"[10:00:02] E1 T1 P1 MOVE : Unit {uid}(55,{row}) ADVANCED from (50,{row}) to (55,{row}) "
        f"[Roll: 3] [R:+0.0] [MODELS: {uid}#0@(55,{row})] [SUCCESS]\n"
    )


def _charged(uid: int, row: int, token: str = "") -> str:
    return (
        f"[10:00:03] E1 T1 P1 CHARGE : Unit {uid}(55,{row}) CHARGED{token} Unit 101(90,50) "
        f"from (55,{row}) to (70,{row}) [Roll:7] [R:+0.0] [MODELS: {uid}#0@(70,{row})] [SUCCESS]\n"
    )


def _failed(uid: int, row: int) -> str:
    return (
        f"[10:00:03] E1 T1 P1 CHARGE : Unit {uid} FAILED CHARGE to unit 101(90,50) "
        f"[Roll: 4] [R:+0.0] [MODELS: {uid}#0@(55,{row})] [SUCCESS]\n"
    )


def _stats(tmp_path, body: str, *, effects: str = _WAAAGH_OFF) -> dict:
    log = tmp_path / "charge.log"
    log.write_text(entete_step_log(
        _DEPLOY + effects + body,
        inches_to_subhex=5,
        objectives=OBJECTIVES,
        units=_UNITS,
        ez_vertical_inches=None,
    ))
    return an.parse_step_log(str(log))


# ---------------------------------------------------------------------------
# FAILED CHARGE après Advance — la branche qui ne jugeait rien
# ---------------------------------------------------------------------------

def test_un_failed_charge_apres_advance_sans_capacite_est_une_faute(tmp_path):
    """ROUGE avant le fix : la branche FAILED CHARGE ne contrôlait que les bornes du jet — ni
    exercice ni faute, quel que soit le journal."""
    stats = _stats(tmp_path, _advance(3, 70) + _failed(3, 70))
    assert stats["rule_usage"]["PROJ.1.3.apres_advance"][1] == 1, "occasion non jugée"
    assert stats["charge_invalid"][1]["advanced"] == 1, "faute non comptée"
    assert stats["first_error_lines"]["charge_invalid"][1] is not None


def test_un_failed_charge_apres_advance_sous_waaagh_est_legal(tmp_path):
    """Boyz, Waaagh! actif pour P1 : la déclaration est légale, l'usage du Waaagh! est relevé."""
    stats = _stats(tmp_path, _advance(1, 50) + _failed(1, 50), effects=_WAAAGH_ON)
    assert stats["rule_usage"]["PROJ.1.3.apres_advance"][1] == 1
    assert stats["charge_invalid"][1]["advanced"] == 0, "faute inventée sur un coup légal"
    assert stats["special_rule_usage"][("waaagh", "Boyz")][1] == 1
    assert not stats["parse_errors"], stats["parse_errors"]


def test_un_failed_charge_apres_advance_avec_capacite_de_datasheet_est_legal(tmp_path):
    """BloodClaw porte `charge_after_advance` : légal sans Waaagh!, et c'est CETTE capacité qui
    est relevée — la datasheet prime sur la faction, dans l'ordre du moteur."""
    stats = _stats(tmp_path, _advance(2, 60) + _failed(2, 60), effects=_WAAAGH_ON)
    assert stats["charge_invalid"][1]["advanced"] == 0
    assert stats["special_rule_usage"][("charge_after_advance", "BloodClaw")][1] == 1
    assert ("waaagh", "BloodClaw") not in stats["special_rule_usage"] or (
        stats["special_rule_usage"][("waaagh", "BloodClaw")][1] == 0
    )


def test_un_failed_charge_sans_advance_n_exerce_pas_le_controle(tmp_path):
    """VERT VACANT : sans Advance, rien à juger — ni exercice ni faute."""
    stats = _stats(tmp_path, _failed(3, 70))
    assert stats["rule_usage"]["PROJ.1.3.apres_advance"][1] == 0
    assert stats["charge_invalid"][1]["advanced"] == 0


# ---------------------------------------------------------------------------
# CHARGED — même verdict, re-dérivé de l'état et non du marqueur
# ---------------------------------------------------------------------------

def test_un_charged_apres_advance_sous_waaagh_est_legal_par_l_etat(tmp_path):
    """Le marqueur `[WAAAGH!]` n'est plus le témoin : c'est `T1 EFFECTS: P1 waaagh=on` + le
    mot-clé ORKS des Boyz qui blanchissent. Avec ou sans marqueur, même verdict."""
    for token in (" [WAAAGH!]", ""):
        stats = _stats(tmp_path, _advance(1, 50) + _charged(1, 50, token), effects=_WAAAGH_ON)
        assert stats["charge_invalid"][1]["total"] == 1, "prémisse : la charge doit être vue"
        assert stats["charge_invalid"][1]["advanced"] == 0, f"faute inventée (token={token!r})"
        assert stats["special_rule_usage"][("waaagh", "Boyz")][1] == 1
        assert not stats["parse_errors"], stats["parse_errors"]


def test_le_marqueur_waaagh_sans_waaagh_actif_est_une_faute_et_une_incoherence(tmp_path):
    """ROUGE avant le fix : le marqueur blanchissait à lui seul — un Intercessor `[WAAAGH!]`
    passait pour légal. L'état ne connaît aucun Waaagh! : la déclaration est fautive ET la ligne
    contredit `T1 EFFECTS:` (deux sorties du moteur qui divergent → parse_error)."""
    stats = _stats(tmp_path, _advance(3, 70) + _charged(3, 70, " [WAAAGH!]"))
    assert stats["charge_invalid"][1]["advanced"] == 1
    assert any("[WAAAGH!]" in e["error"] for e in stats["parse_errors"]), stats["parse_errors"]


def test_un_non_ork_sous_waaagh_actif_reste_fautif(tmp_path):
    """« units from your army WITH THIS ABILITY » : le Waaagh! de P1 ne blanchit pas un
    Intercessor de P1 — le mot-clé de faction décide, pas le camp."""
    stats = _stats(tmp_path, _advance(3, 70) + _failed(3, 70), effects=_WAAAGH_ON)
    assert stats["charge_invalid"][1]["advanced"] == 1
