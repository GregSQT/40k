"""10.07 tir indirect — contrôle analyzer : [COVER] obligatoire sur toute ligne [INDIRECT FIRE:X+].

Taux de fausse alarme mesuré AVANT livraison (cf. indirect_fire_10_07.md §3.7).
Aucun roster ArmageddonAgent ne porte d'arme INDIRECT FIRE : le contrôle est exercé sur journal
synthétique uniquement (injection de lignes + moteur réel via _engine_shoot_log).

Invariant vérifié : [COVER] présent sur toute ligne portant [INDIRECT FIRE:X+].

Non vérifié (voir check) : le seuil `eff` affiché est BS_après_couvert, pas max(BS, plancher).
Le moteur affiche `Hit 3(3+->4+) [INDIRECT FIRE:6+]` légalement (4 < 6 est normal).

Exception : [IGNORES COVER] → pas de jugement (pas de faux positif systématique).
"""
from __future__ import annotations

import pytest

from tests.unit.ai._fabriques import entete_step_log

SHOOTER = (50, 50)
TARGET = (50, 56)
S = f"({SHOOTER[0]},{SHOOTER[1]})"
T = f"({TARGET[0]},{TARGET[1]})"
OBJECTIVES = ";".join(f"(200,{r})" for r in range(150, 156))

_HEADER = entete_step_log(
    units=(
        f"[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position {S}, HP_MAX=2 base=round/6\n"
        f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {T}, HP_MAX=2 base=round/6\n"
    ),
    rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    objectives=OBJECTIVES,
    ez_vertical_inches=None,
)
_END = (
    "[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
    "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
    "Total=0, Duration=1.000s\n"
)

# Lignes synthétiques représentatives. Le segment Hit suit le format du moteur :
# `Hit {roll}({base}+->{eff}+)` quand COVER modifie le seuil, `Hit {roll}({eff}+)` sinon.
# [INDIRECT FIRE:X+] vient APRÈS [COVER] (cf. step_logger.py, ordre de construction).

# ── valides ──────────────────────────────────────────────────────────────────────────────────
# Le moteur affiche BS_après_couvert (4+) et non max(4,6)=6+ : eff < floor est LÉGAL.
# 6+ plancher, BS=3→4 après couvert (eff=4 < floor=6 — légal), roll manqué.
_VALID_6_MISS = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Bolt Rifle]"
    " - Hit 3(3+->4+) [COVER] [INDIRECT FIRE:6+] [R:+0.0] [FAILED]\n"
)
# 6+ plancher, roll=6 (critique) → touche avec Wound.
_VALID_6_HIT = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Bolt Rifle]"
    " - Hit 6(3+->4+) [COVER] [INDIRECT FIRE:6+] - Wound 5(4+) - Save 2(3+) - Dmg:1HP"
    " [R:+0.0] [SUCCESS]\n"
)
# 4+ plancher (spotter), BS=3→4 après couvert, eff=4 == floor=4.
_VALID_4_HIT = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Bolt Rifle]"
    " - Hit 4(3+->4+) [COVER] [INDIRECT FIRE:4+] - Wound 5(4+) - Save 2(3+) - Dmg:1HP"
    " [R:+0.0] [SUCCESS]\n"
)

# ── invalide ──────────────────────────────────────────────────────────────────────────────────
# [COVER] absent : invariant violé.
_INVALID_NO_COVER = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Bolt Rifle]"
    " - Hit 4(3+->6+) [INDIRECT FIRE:6+] [R:+0.0] [FAILED]\n"
)

# ── exceptions légitimes ──────────────────────────────────────────────────────────────────────
# [IGNORES COVER] : le couvert n'est pas accordé → le contrôle DOIT ignorer la ligne.
_IGNORES_COVER = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Bolt Rifle]"
    " - Hit 4(3+) [IGNORES COVER] [INDIRECT FIRE:6+] [R:+0.0] [FAILED]\n"
)
# Tir normal sans token indirect : le contrôle ne doit pas intervenir.
_NORMAL_SHOT = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Bolt Rifle]"
    " - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
)


def _stats(tmp_path, *lines: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_HEADER + "".join(lines) + _END)
    return an.parse_step_log(str(log))


# ── 1. Lignes valides : aucun mismatch, compteur CHECKED actif ───────────────────────────────

def test_tir_indirect_6plus_miss_conforme(tmp_path):
    stats = _stats(tmp_path, _VALID_6_MISS)
    assert stats["indirect_fire_mismatch"][1] == 0
    assert stats["indirect_fire_checked"][1] == 1, "contrôle doit avoir jugé la ligne"


def test_tir_indirect_6plus_hit_conforme(tmp_path):
    stats = _stats(tmp_path, _VALID_6_HIT)
    assert stats["indirect_fire_mismatch"][1] == 0
    assert stats["indirect_fire_checked"][1] == 1


def test_tir_indirect_4plus_spotter_conforme(tmp_path):
    stats = _stats(tmp_path, _VALID_4_HIT)
    assert stats["indirect_fire_mismatch"][1] == 0
    assert stats["indirect_fire_checked"][1] == 1


# ── 2. Ligne invalide : mismatch détecté + first_error_lines renseigné ───────────────────────

def test_mismatch_cover_absent(tmp_path):
    stats = _stats(tmp_path, _INVALID_NO_COVER)
    assert stats["indirect_fire_mismatch"][1] == 1
    first = stats["first_error_lines"]["indirect_fire_mismatch"][1]
    assert first is not None
    assert "[COVER] absent" in first["detail"], first


# ── 3. Exceptions légitimes : contrôle muet ──────────────────────────────────────────────────

def test_ignores_cover_est_ignore(tmp_path):
    """[IGNORES COVER] + [INDIRECT FIRE] : pas de jugement (pas de faux positif)."""
    stats = _stats(tmp_path, _IGNORES_COVER)
    assert stats["indirect_fire_mismatch"][1] == 0
    assert stats["indirect_fire_checked"][1] == 0, "[IGNORES COVER] doit court-circuiter le check"


def test_tir_normal_non_juge(tmp_path):
    """Pas de [INDIRECT FIRE:X+] → le contrôle ne s'active pas."""
    stats = _stats(tmp_path, _NORMAL_SHOT)
    assert stats["indirect_fire_checked"][1] == 0


# ── 4. Taux de fausse alarme — sortie moteur réelle ──────────────────────────────────────────
#
# Les tests ci-dessus exercent la LOGIQUE du contrôle sur des lignes construites à la main.
# Ce test mesure le taux de fausse alarme sur la SORTIE RÉELLE DU MOTEUR : si le moteur
# génère des lignes invalides pour un tir indirect légal, c'est un bug moteur, pas un faux
# positif du contrôle. On attend 0 mismatch / N lignes jugées.

def test_taux_fausse_alarme_moteur_reel_6plus(monkeypatch, tmp_path):
    """Sortie moteur pour [INDIRECT FIRE:6+] (sans spotter) → 0 faux positif."""
    from tests.unit.ai.test_step_log_weapon_rule_tokens import (
        _engine_shoot_log, _step_log_lines, _analyzer_stats,
    )
    gs, raw_log = _engine_shoot_log(
        monkeypatch, ["INDIRECT_FIRE"], [3, 4, 2], indirect=True
    )
    lines = _step_log_lines(tmp_path, gs, raw_log)
    stats = _analyzer_stats(tmp_path, lines)
    n_indirect = stats["indirect_fire_checked"][1] + stats["indirect_fire_checked"][2]
    assert n_indirect > 0, "aucun tir indirect jugé — le contrôle est mort"
    assert stats["indirect_fire_mismatch"][1] == 0, (
        f"FAUX POSITIF — sortie moteur légale détectée comme invalide : "
        f"{stats['first_error_lines']['indirect_fire_mismatch'][1]}"
    )
    assert stats["indirect_fire_mismatch"][2] == 0


def test_taux_fausse_alarme_moteur_reel_4plus_spotter(monkeypatch, tmp_path):
    """Sortie moteur pour [INDIRECT FIRE:4+] (avec spotter) → 0 faux positif."""
    from tests.unit.ai.test_step_log_weapon_rule_tokens import (
        _engine_shoot_log, _step_log_lines, _analyzer_stats,
    )
    gs, raw_log = _engine_shoot_log(
        monkeypatch, ["INDIRECT_FIRE"], [3, 4, 2], indirect=True, spotter=True
    )
    lines = _step_log_lines(tmp_path, gs, raw_log)
    stats = _analyzer_stats(tmp_path, lines)
    n_indirect = stats["indirect_fire_checked"][1] + stats["indirect_fire_checked"][2]
    assert n_indirect > 0, "aucun tir indirect jugé — le contrôle est mort"
    assert stats["indirect_fire_mismatch"][1] == 0, (
        f"FAUX POSITIF 4+ spotter : {stats['first_error_lines']['indirect_fire_mismatch'][1]}"
    )
    assert stats["indirect_fire_mismatch"][2] == 0
