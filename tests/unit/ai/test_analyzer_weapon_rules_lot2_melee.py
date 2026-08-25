"""Tests lot2 mêlée : compteurs d'usage des 5 règles (TORRENT / IGNORES_COVER /
LETHAL_HITS / EXTRA_ATTACKS / ANTI-X) sur le chemin fight_handler.

Jumeau exact de test_analyzer_weapon_rules_lot2 (tir) : même invariant, même structure,
même format ROUGE→VERT, mais sur une ligne FOUGHT au lieu de SHOT.

Les 5 règles sont comptées par token dans action_desc (re.search), indépendamment du fait
que l'arme de mêlée déclare ou non la règle — sauf ANTI-X dont la vérification de seuil
compare le token avec la valeur déclarée dans l'armurerie.
"""
from __future__ import annotations

import ai.analyzer as an

from tests.unit.ai._fabriques import entete_step_log, weapon_rule_usage as _usage, EPISODE_TAIL

FIGHTER = (50, 50)
TARGET = (50, 51)
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

F, T = f"({FIGHTER[0]},{FIGHTER[1]})", f"({TARGET[0]},{TARGET[1]})"


def _fought_line(unit_type: str, weapon: str, detail: str) -> str:
    """Ligne FOUGHT complète avec [MODEL_TYPES:] pour une unité à figurine unique.

    Intentionnellement plus simple que `_fight_body_line` dans test_analyzer_weapon_rules_lot2.py :
    pas de [TARGET_MODELS:] ni [TARGET_DECL:1], et [FIGHT_SUBPHASE:fight] en 3e position.
    Ces deux fichiers testent des chemins indépendants du fight_handler — les tokens
    supplémentaires ne sont pas nécessaires ici et leur absence doit rester visible.
    """
    return (
        f"[10:00:02] E1 T1 P1 FIGHT : Unit 1{F} FOUGHT Unit 101{T} with [{weapon}]"
        f" - {detail}"
        f" [FIGHT_SUBPHASE:fight]"
        f" [MODELS: 1#0@({FIGHTER[0]},{FIGHTER[1]},z0)]"
        f" [SHOOTER_MODELS: 1#0]"
        f" [MODEL_TYPES: 1#0={unit_type}]"
        f" [R:+0.0] [SUCCESS]\n"
    )


def _log(fought_line: str, unit_type: str) -> str:
    units = (
        f"[10:00:00] Unit 1 ({unit_type}) P1: Starting position {F},"
        f" HP_MAX=4 base=round/6 [MODELS: 1#0@({FIGHTER[0]},{FIGHTER[1]},z0)]\n"
        f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {T},"
        f" HP_MAX=2 base=round/6 [MODELS: 101#0@({TARGET[0]},{TARGET[1]},z0)]\n"
    )
    body = fought_line + EPISODE_TAIL
    return entete_step_log(
        body,
        units=units,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
        objectives=OBJECTIVES,
    )


def _stats(tmp_path, fought_line: str, unit_type: str):
    log = tmp_path / "step.log"
    log.write_text(_log(fought_line, unit_type))
    return an.parse_step_log(str(log))


# ─────────────────────────────────────────────────────────────────────────────
# 1. EXTRA_ATTACKS usage
# ─────────────────────────────────────────────────────────────────────────────
# ApothecaryBiologis déclare « Relic Blade » avec EXTRA_ATTACKS.

_EA_LINE = _fought_line(
    "ApothecaryBiologis", "Relic Blade",
    "Hit 4(3+) - Wound 5(3+) [EXTRA ATTACKS] - Save 2(3+) - Dmg:3HP",
)


def test_extra_attacks_melee_usage_counter_incremented(tmp_path):
    stats = _stats(tmp_path, _EA_LINE, "ApothecaryBiologis")
    usage = _usage(stats, "EXTRA_ATTACKS")
    assert usage == {("EXTRA_ATTACKS", "Relic Blade (ApothecaryBiologis)"): 1}, usage


# ─────────────────────────────────────────────────────────────────────────────
# 2. LETHAL_HITS usage + validité
# ─────────────────────────────────────────────────────────────────────────────
# WarpSpiderExarchPowerblade déclare « Powerblades Array » avec LETHAL_HITS.

_LH_LINE = _fought_line(
    "WarpSpiderExarchPowerblade", "Powerblades Array",
    "Hit 6(3+) - Wound None(3+) [LETHAL HITS] - Save 5(4+) - Dmg:1HP",
)

_LH_LINE_BAD = _fought_line(
    "WarpSpiderExarchPowerblade", "Powerblades Array",
    "Hit 6(3+) - Wound 5(3+) [LETHAL HITS] - Save 5(4+) - Dmg:1HP",
)


def test_lethal_hits_melee_usage_counter_incremented(tmp_path):
    stats = _stats(tmp_path, _LH_LINE, "WarpSpiderExarchPowerblade")
    usage = _usage(stats, "LETHAL_HITS")
    assert usage == {("LETHAL_HITS", "Powerblades Array (WarpSpiderExarchPowerblade)"): 1}, usage


def test_lethal_hits_melee_no_validity_error_with_none_wound(tmp_path):
    stats = _stats(tmp_path, _LH_LINE, "WarpSpiderExarchPowerblade")
    assert stats["lethal_hits_wrong_wound_fight"][1] == 0, stats["lethal_hits_wrong_wound_fight"]


def test_lethal_hits_melee_validity_error_with_numeric_wound(tmp_path):
    stats = _stats(tmp_path, _LH_LINE_BAD, "WarpSpiderExarchPowerblade")
    assert stats["lethal_hits_wrong_wound_fight"][1] == 1, stats["lethal_hits_wrong_wound_fight"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. ANTI-X usage + validité
# ─────────────────────────────────────────────────────────────────────────────
# LieutenantCombiWeapon déclare « Paired Combat Blade » avec ANTI_INFANTRY:4.

_ANTI_LINE = _fought_line(
    "LieutenantCombiWeapon", "Paired Combat Blade",
    "Hit 4(3+) - Wound 5(3+) [ANTI-INFANTRY:4+] - Save 2(3+) - Dmg:1HP",
)

_ANTI_MISMATCH = _fought_line(
    "LieutenantCombiWeapon", "Paired Combat Blade",
    "Hit 4(3+) - Wound 3(3+) [ANTI-INFANTRY:3+] - Save 2(3+) - Dmg:1HP",
)


def test_anti_x_melee_usage_counter_incremented(tmp_path):
    stats = _stats(tmp_path, _ANTI_LINE, "LieutenantCombiWeapon")
    usage = _usage(stats, "ANTI_INFANTRY")
    assert usage == {("ANTI_INFANTRY", "Paired Combat Blade (LieutenantCombiWeapon)"): 1}, usage


def test_anti_x_melee_no_error_when_threshold_matches(tmp_path):
    stats = _stats(tmp_path, _ANTI_LINE, "LieutenantCombiWeapon")
    anti_errors = [e for e in stats["parse_errors"] if "ANTI-" in e.get("error", "")]
    assert anti_errors == [], anti_errors


def test_anti_x_melee_error_when_threshold_mismatch(tmp_path):
    stats = _stats(tmp_path, _ANTI_MISMATCH, "LieutenantCombiWeapon")
    anti_errors = [e for e in stats["parse_errors"] if "ANTI-" in e.get("error", "")]
    assert len(anti_errors) == 1, anti_errors
    assert "3+" in anti_errors[0]["error"] and "4+" in anti_errors[0]["error"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. TORRENT usage + validité
# ─────────────────────────────────────────────────────────────────────────────
# Relic Blade (ApothecaryBiologis) ne déclare pas TORRENT, mais le token dans
# action_desc suffit à incrémenter le compteur (comptage par trace, pas par déclaration).

_TORRENT_LINE = _fought_line(
    "ApothecaryBiologis", "Relic Blade",
    "Hit None(None+) [TORRENT] - Wound 4(4+) - Save 5(4+) - Dmg:3HP",
)

_TORRENT_LINE_BAD = _fought_line(
    "ApothecaryBiologis", "Relic Blade",
    "Hit 4(3+) [TORRENT] - Wound 4(4+) - Save 5(4+) - Dmg:3HP",
)


def test_torrent_melee_usage_counter_incremented(tmp_path):
    stats = _stats(tmp_path, _TORRENT_LINE, "ApothecaryBiologis")
    usage = _usage(stats, "TORRENT")
    assert usage == {("TORRENT", "Relic Blade (ApothecaryBiologis)"): 1}, usage


def test_torrent_melee_no_validity_error_with_none_hit(tmp_path):
    stats = _stats(tmp_path, _TORRENT_LINE, "ApothecaryBiologis")
    assert stats["torrent_wrong_hit_fight"][1] == 0, stats["torrent_wrong_hit_fight"]


def test_torrent_melee_validity_error_with_numeric_hit(tmp_path):
    stats = _stats(tmp_path, _TORRENT_LINE_BAD, "ApothecaryBiologis")
    assert stats["torrent_wrong_hit_fight"][1] == 1, stats["torrent_wrong_hit_fight"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. IGNORES_COVER usage
# ─────────────────────────────────────────────────────────────────────────────
# Aucune arme de mêlée du registre ne déclare IGNORES_COVER : le compteur suit
# le token, exactement comme TORRENT ci-dessus.

_IC_LINE = _fought_line(
    "ApothecaryBiologis", "Relic Blade",
    "Hit 4(3+) [IGNORES COVER] - Wound 4(4+) - Save 5(4+) - Dmg:3HP",
)


def test_ignores_cover_melee_usage_counter_incremented(tmp_path):
    stats = _stats(tmp_path, _IC_LINE, "ApothecaryBiologis")
    usage = _usage(stats, "IGNORES_COVER")
    assert usage == {("IGNORES_COVER", "Relic Blade (ApothecaryBiologis)"): 1}, usage
