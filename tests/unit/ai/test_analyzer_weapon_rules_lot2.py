"""Tests lot 2 : compteurs d'usage des 5 règles manquantes, fix threshold DW, Roll:1 HAZARDOUS.

Invariants vérifiés (ROUGE→VERT pour chaque correction) :

1. ANTI-X    — [ANTI-keyword:N+] dans le segment blessure → compteur incrémenté.
2. TORRENT   — [TORRENT] dans action_desc → compteur incrémenté ; Hit numérique → parse_error.
3. LETHAL HITS — [LETHAL HITS] dans action_desc → compteur ; Wound numérique → parse_error.
4. IGNORES_COVER — [IGNORES COVER] → compteur incrémenté.
5. EXTRA_ATTACKS — [EXTRA ATTACKS] → compteur incrémenté.
6. DW threshold — ANTI-X:N+ (N<6) change le seuil critique : wound=N + Save [DW] = CORRECT.
7. HAZARDOUS Roll:1 — [HAZARDOUS] Roll:1 sur ligne SHOT → hazardous_roll1_count incrémenté.
"""
from __future__ import annotations

import ai.analyzer as an

from tests.unit.ai._fabriques import entete_step_log, weapon_rule_usage as _usage

SHOOTER = (50, 50)
TARGET = (50, 80)    # 30 subhex = 6", hors zone d'engagement
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

S, T = f"({SHOOTER[0]},{SHOOTER[1]})", f"({TARGET[0]},{TARGET[1]})"


def _body_line(unit_type: str, weapon: str, detail: str, *, hazardous_roll: int | None = None) -> str:
    """Ligne SHOT complète avec [MODEL_TYPES:] pour résoudre l'arme."""
    hz = f" [HAZARDOUS] Roll:{hazardous_roll}" if hazardous_roll is not None else ""
    return (
        f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [{weapon}]"
        f" - {detail}{hz}"
        f" [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)]"
        f" [TARGET_MODELS: 101#0@({TARGET[0]},{TARGET[1]},z0)]"
        " [SHOOTER_MODELS: 1#0]"
        f" [MODEL_TYPES: 1#0={unit_type}]"
        " [R:+0.0] [SUCCESS]\n"
    )


def _log(*shot_lines: str, unit_type: str = "Intercessor") -> str:
    units = (
        f"[10:00:00] Unit 1 ({unit_type}) P1: Starting position {S}, HP_MAX=4 base=round/6"
        f" [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)]\n"
        f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {T}, HP_MAX=2 base=round/6"
        f" [MODELS: 101#0@({TARGET[0]},{TARGET[1]},z0)]\n"
    )
    body = "".join(shot_lines) + (
        "[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s\n"
    )
    # log_grammar non spécifié → grammaire 1 (défaut). Les compteurs TORRENT, LETHAL HITS,
    # ANTI-X, etc. utilisent re.search() direct, indépendant de la version de grammaire.
    return entete_step_log(body, units=units, rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
                           objectives=OBJECTIVES)


def _stats(tmp_path, *shot_lines: str, unit_type: str = "Intercessor"):
    log = tmp_path / "step.log"
    log.write_text(_log(*shot_lines, unit_type=unit_type))
    return an.parse_step_log(str(log))


# ─────────────────────────────────────────────────────────────────────────────
# 1. ANTI-X usage
# ─────────────────────────────────────────────────────────────────────────────
# LibrarianTerminator déclare « Combi Weapon » avec ANTI_INFANTRY:4.
# Le token [ANTI-INFANTRY:4+] dans le segment blessure doit incrémenter le compteur.

_ANTI_LINE = _body_line(
    "LibrarianTerminator", "Combi Weapon",
    "Hit 4(3+) - Wound 5(3+) [ANTI-INFANTRY:4+] - Save 5(4+) - Dmg:1HP",
)


def test_anti_x_usage_counter_incremented(tmp_path):
    stats = _stats(tmp_path, _ANTI_LINE, unit_type="LibrarianTerminator")
    usage = _usage(stats, "ANTI_INFANTRY")
    assert usage == {("ANTI_INFANTRY", "Combi Weapon (LibrarianTerminator)"): 1}, usage


def test_anti_x_threshold_validity_no_error_when_matches(tmp_path):
    """Token seuil=4, armurerie seuil=4 — aucune erreur de validité."""
    stats = _stats(tmp_path, _ANTI_LINE, unit_type="LibrarianTerminator")
    anti_errors = [e for e in stats["parse_errors"] if "ANTI-" in e.get("error", "")]
    assert anti_errors == [], anti_errors


def test_anti_x_threshold_validity_error_when_mismatch(tmp_path):
    """Token seuil=3, armurerie seuil=4 — parse_error attendu."""
    mismatch_line = _body_line(
        "LibrarianTerminator", "Combi Weapon",
        "Hit 4(3+) - Wound 3(3+) [ANTI-INFANTRY:3+] - Save 5(4+) - Dmg:1HP",
    )
    stats = _stats(tmp_path, mismatch_line, unit_type="LibrarianTerminator")
    anti_errors = [e for e in stats["parse_errors"] if "ANTI-" in e.get("error", "")]
    assert len(anti_errors) == 1, anti_errors
    assert "3+" in anti_errors[0]["error"] and "4+" in anti_errors[0]["error"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. TORRENT usage + validité
# ─────────────────────────────────────────────────────────────────────────────
# LandSpeederHeavyFlamer déclare « Heavy Flamer » avec TORRENT.

_TORRENT_LINE = _body_line(
    "LandSpeederHeavyFlamer", "Heavy Flamer",
    "Hit None(None+) [TORRENT] - Wound 4(4+) - Save 5(4+) - Dmg:1HP",
)


def test_torrent_usage_counter_incremented(tmp_path):
    stats = _stats(tmp_path, _TORRENT_LINE, unit_type="LandSpeederHeavyFlamer")
    usage = _usage(stats, "TORRENT")
    assert usage == {("TORRENT", "Heavy Flamer (LandSpeederHeavyFlamer)"): 1}, usage


def test_torrent_no_validity_error_with_none_hit(tmp_path):
    """Hit None(None+) avec TORRENT : aucune erreur de validité."""
    stats = _stats(tmp_path, _TORRENT_LINE, unit_type="LandSpeederHeavyFlamer")
    torrent_errors = [e for e in stats["parse_errors"] if "TORRENT" in e.get("error", "")]
    assert torrent_errors == [], torrent_errors


def test_torrent_validity_error_with_numeric_hit(tmp_path):
    """Hit numérique avec [TORRENT] : parse_error attendu (24.37 viole l'invariant)."""
    bad_line = _body_line(
        "LandSpeederHeavyFlamer", "Heavy Flamer",
        "Hit 4(3+) [TORRENT] - Wound 4(4+) - Save 5(4+) - Dmg:1HP",
    )
    stats = _stats(tmp_path, bad_line, unit_type="LandSpeederHeavyFlamer")
    torrent_errors = [e for e in stats["parse_errors"] if "TORRENT" in e.get("error", "")]
    assert len(torrent_errors) == 1, torrent_errors


# ─────────────────────────────────────────────────────────────────────────────
# 3. LETHAL HITS usage + validité
# ─────────────────────────────────────────────────────────────────────────────
# Zoanthrope déclare « Warp Blast (Focused Bolt) » avec LETHAL_HITS.

_LETHAL_LINE = _body_line(
    "Zoanthrope", "Warp Blast (Focused Bolt)",
    "Hit 6(3+) - Wound None(3+) [LETHAL HITS] - Save 5(4+) - Dmg:1HP",
)


def test_lethal_hits_usage_counter_incremented(tmp_path):
    stats = _stats(tmp_path, _LETHAL_LINE, unit_type="Zoanthrope")
    usage = _usage(stats, "LETHAL_HITS")
    assert usage == {("LETHAL_HITS", "Warp Blast (Focused Bolt) (Zoanthrope)"): 1}, usage


def test_lethal_hits_no_validity_error_with_none_wound(tmp_path):
    """Wound None(3+) avec [LETHAL HITS] : aucune erreur de validité."""
    stats = _stats(tmp_path, _LETHAL_LINE, unit_type="Zoanthrope")
    lh_errors = [e for e in stats["parse_errors"] if "LETHAL HITS" in e.get("error", "")]
    assert lh_errors == [], lh_errors


def test_lethal_hits_validity_error_with_numeric_wound(tmp_path):
    """Wound numérique avec [LETHAL HITS] : parse_error attendu (24.23 viole l'invariant)."""
    bad_line = _body_line(
        "Zoanthrope", "Warp Blast (Focused Bolt)",
        "Hit 6(3+) - Wound 5(3+) [LETHAL HITS] - Save 5(4+) - Dmg:1HP",
    )
    stats = _stats(tmp_path, bad_line, unit_type="Zoanthrope")
    lh_errors = [e for e in stats["parse_errors"] if "LETHAL HITS" in e.get("error", "")]
    assert len(lh_errors) == 1, lh_errors


# ─────────────────────────────────────────────────────────────────────────────
# 4. IGNORES_COVER usage
# ─────────────────────────────────────────────────────────────────────────────
# Incursor déclare « Oculus Bolt Carabine » avec IGNORES_COVER.

_IC_LINE = _body_line(
    "Incursor", "Oculus Bolt Carabine",
    "Hit 4(3+) [IGNORES COVER] - Wound 4(4+) - Save 5(4+) - Dmg:1HP",
)


def test_ignores_cover_usage_counter_incremented(tmp_path):
    stats = _stats(tmp_path, _IC_LINE, unit_type="Incursor")
    usage = _usage(stats, "IGNORES_COVER")
    assert usage == {("IGNORES_COVER", "Oculus Bolt Carabine (Incursor)"): 1}, usage


# ─────────────────────────────────────────────────────────────────────────────
# 5. EXTRA_ATTACKS usage
# ─────────────────────────────────────────────────────────────────────────────
# Shoota (Boyz) — weapon_rules sans EXTRA_ATTACKS. Le token sur la ligne
# incrémente quand même le compteur (attaque du pool extra).

_EA_LINE = _body_line(
    "Boyz", "Shoota",
    "Hit 4(3+) [EXTRA ATTACKS] - Wound 4(4+) - Save 5(4+) - Dmg:1HP",
)


def test_extra_attacks_usage_counter_incremented(tmp_path):
    stats = _stats(tmp_path, _EA_LINE, unit_type="Boyz")
    usage = _usage(stats, "EXTRA_ATTACKS")
    assert usage == {("EXTRA_ATTACKS", "Shoota (Boyz)"): 1}, usage


# ─────────────────────────────────────────────────────────────────────────────
# 6. DEVASTATING WOUNDS — fix du seuil critique (ANTI-X:N avec N < 6)
# ─────────────────────────────────────────────────────────────────────────────
# Combi Weapon (LibrarianTerminator) : ANTI_INFANTRY:4 + DEVASTATING_WOUNDS.
# Wound roll = 4, seuil critique déclaré = 4 → blessure critique → CORRECT.
# AVANT le fix : 4 < 6 → le elif prenait → devastating_wounds_incorrect += 1.
# APRÈS le fix : threshold=4, 4 >= 4 → devastating_wounds_correct += 1.

_DW_ANTI_LINE = _body_line(
    "LibrarianTerminator", "Combi Weapon",
    "Hit 4(3+) - Wound 4(3+) [ANTI-INFANTRY:4+] [DEVASTATING WOUNDS] - Save [DEVASTATING WOUNDS] - Dmg:2HP",
)


def test_dw_threshold_from_anti_token_correct(tmp_path):
    """Wound 4 avec seuil ANTI=4 → devastating_wounds_correct, pas incorrect."""
    stats = _stats(tmp_path, _DW_ANTI_LINE, unit_type="LibrarianTerminator")
    assert stats["devastating_wounds_correct"][1] == 1, stats["devastating_wounds_correct"]
    assert stats["devastating_wounds_incorrect"][1] == 0, stats["devastating_wounds_incorrect"]


def test_dw_threshold_without_anti_uses_6(tmp_path):
    """Sans ANTI token, seuil=6 : Wound 5 → incorrect (5 < 6 et pas de Save DW)."""
    line_wound5_no_anti = _body_line(
        "LibrarianTerminator", "Combi Weapon",
        "Hit 4(3+) - Wound 5(3+) [DEVASTATING WOUNDS] - Save 3(4+) - Dmg:2HP",
    )
    stats = _stats(tmp_path, line_wound5_no_anti, unit_type="LibrarianTerminator")
    # wound_roll=5 < default_threshold=6, save attempt found → incorrect
    assert stats["devastating_wounds_incorrect"][1] == 1, stats["devastating_wounds_incorrect"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. HAZARDOUS Roll:1 counter
# ─────────────────────────────────────────────────────────────────────────────
# AssaultIntercessorJumpPackPlasmaPistol — Plasma Pistol (Supercharge) est HAZARDOUS.

_HZ_LINE_ROLL1 = _body_line(
    "AssaultIntercessorJumpPackPlasmaPistol", "Plasma Pistol (Supercharge)",
    "Hit 4(3+) - Wound 4(4+) - Save 5(3+) - Dmg:1HP", hazardous_roll=1,
)

_HZ_LINE_ROLL3 = _body_line(
    "AssaultIntercessorJumpPackPlasmaPistol", "Plasma Pistol (Supercharge)",
    "Hit 4(3+) - Wound 4(4+) - Save 5(3+) - Dmg:1HP", hazardous_roll=3,
)


def test_hazardous_roll1_counter_incremented_on_roll1(tmp_path):
    stats = _stats(tmp_path, _HZ_LINE_ROLL1,
                   unit_type="AssaultIntercessorJumpPackPlasmaPistol")
    assert stats["hazardous_roll1_count"][1] == 1, stats["hazardous_roll1_count"]


def test_hazardous_roll1_counter_not_incremented_on_roll3(tmp_path):
    """Roll:3 ne doit pas incrémenter le compteur Roll:1."""
    stats = _stats(tmp_path, _HZ_LINE_ROLL3,
                   unit_type="AssaultIntercessorJumpPackPlasmaPistol")
    assert stats["hazardous_roll1_count"][1] == 0, stats["hazardous_roll1_count"]


def test_hazardous_both_rolls_in_one_episode(tmp_path):
    """Roll:1 et Roll:3 dans le même épisode — seul le Roll:1 est compté."""
    stats = _stats(tmp_path, _HZ_LINE_ROLL1, _HZ_LINE_ROLL3,
                   unit_type="AssaultIntercessorJumpPackPlasmaPistol")
    assert stats["hazardous_roll1_count"][1] == 1, stats["hazardous_roll1_count"]
