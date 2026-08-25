"""Lot 7 : verrous pour les règles câblées dans ce lot.

Couvre :
- unit.charge_impact     — corpus ABSENT_LOGGABLE → COUVERT (contrôle déjà en PROJ.1.3.charge_impact)
- PROJ.1.2.torrent       — 24.37 [TORRENT] tir : jet de touche numérique détecté
- PROJ.1.4.torrent       — 24.37 [TORRENT] mêlée : jet de touche numérique détecté
- PROJ.1.2.lethal_hits   — 24.23 [LETHAL HITS] tir : blessure auto avec jet numérique
- PROJ.1.4.lethal_hits   — 24.23 [LETHAL HITS] mêlée : blessure auto avec jet numérique
- PROJ.1.1.reserves_too_early — 20.03 ingress au round 1
- PROJ.1.2.blast         — 24.05 [BLAST] tir : valeur X incorrecte
"""

from __future__ import annotations

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log

OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))
EPISODE_END = (
    "[10:00:09] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 ZONES=rect b NW:Ctrl=none\n"
    "[10:00:10] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s\n"
)


def _parse(log_text: str, tmp_path):
    log = tmp_path / "step.log"
    log.write_text(log_text)
    return an.parse_step_log(str(log))


# ─── 1. unit.charge_impact — corpus uniquement, pas de nouveau contrôle ────

def test_corpus_charge_impact_couvert(tmp_path):
    """VERROU : PROJ.1.3.charge_impact est COUVERT ; unit.charge_impact l'est aussi via co_verified_by."""
    from ai.analyzer import load_rules_corpus
    corpus = load_rules_corpus()
    proj = next(r for r in corpus if r['id'] == 'PROJ.1.3.charge_impact')
    assert proj['status'] == 'COUVERT'
    unit_entry = next(r for r in corpus if r['id'] == 'unit.charge_impact')
    assert unit_entry['status'] == 'COUVERT'
    assert 'PROJ.1.3.charge_impact' in unit_entry.get('co_verified_by', [])


# ─── 2. TORRENT tir (PROJ.1.2.torrent) ──────────────────────────────────────

UNITS_TORRENT = (
    "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (50,50), HP_MAX=2"
    " base=round/6 [MODELS: 1#0@(50,50,z0)] [MODEL_TYPES: 1#0=SternguardVeteranBoltRifle]\n"
    "[10:00:00] Unit 101 (Boyz) P2: Starting position (90,50), HP_MAX=1"
    " base=round/6 [MODELS: 101#0@(90,50,z0)]\n"
)
DEPLOY_TORRENT = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [SUCCESS]\n"
)


def _torrent_shoot_log(hit_segment: str, tmp_path) -> dict:
    body = (
        DEPLOY_TORRENT
        + f"[10:00:03] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(90,50) with [Sternguard Bolt Rifle]"
        f" - {hit_segment} [TORRENT] - Wound 5(4+) - Save 2(3+) - Dmg:0HP"
        f" [MODELS: 1#0@(50,50,z0)] [TARGET_MODELS: 101#0@(90,50,z0)]"
        f" [SHOOTER_MODELS: 1#0] [TARGET_DECL:1] [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(
        body, units=UNITS_TORRENT, objectives=OBJECTIVES,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    )
    return _parse(log_text, tmp_path)


def test_torrent_tir_correct_pas_erreur(tmp_path):
    """VERROU : Hit None(None+) [TORRENT] → pas d'erreur torrent_wrong_hit."""
    stats = _torrent_shoot_log("Hit None(None+)", tmp_path)
    assert stats["torrent_wrong_hit"][1] == 0, "faux positif : touche auto correcte signalée en erreur"


def test_torrent_tir_numerique_detecte(tmp_path):
    """VERROU : Hit 5(3+) [TORRENT] → torrent_wrong_hit incrémenté."""
    stats = _torrent_shoot_log("Hit 5(3+)", tmp_path)
    assert stats["torrent_wrong_hit"][1] == 1, "mismatch TORRENT tir non détecté"
    assert stats["first_error_lines"]["torrent_wrong_hit"][1] is not None


# ─── 3. TORRENT mêlée (PROJ.1.4.torrent) ────────────────────────────────────

UNITS_TORRENT_MELEE = (
    "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (50,50), HP_MAX=2"
    " base=round/6 [MODELS: 1#0@(50,50,z0)] [MODEL_TYPES: 1#0=AssaultIntercessor]\n"
    "[10:00:00] Unit 101 (Boyz) P2: Starting position (50,51), HP_MAX=1"
    " base=round/6 [MODELS: 101#0@(50,51,z0)]\n"
)
DEPLOY_TORRENT_MELEE = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(50,51) DEPLOYED from (-1,-1) to (50,51) [R:+0.0] [SUCCESS]\n"
)


def _torrent_fight_log(hit_segment: str, tmp_path) -> dict:
    body = (
        DEPLOY_TORRENT_MELEE
        + f"[10:00:06] E1 T1 P1 FIGHT : Unit 1(50,50) FOUGHT Unit 101(50,51) with [Astartes Chainsword]"
        f" - {hit_segment} [TORRENT] - Wound 5(4+) - Save 2(3+) - Dmg:0HP"
        f" [MODELS: 1#0@(50,50,z0)] [TARGET_MODELS: 101#0@(50,51,z0)]"
        f" [SHOOTER_MODELS: 1#0] [TARGET_DECL:1] [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(
        body, units=UNITS_TORRENT_MELEE, objectives=OBJECTIVES,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    )
    return _parse(log_text, tmp_path)


def test_torrent_melee_correct_pas_erreur(tmp_path):
    """VERROU : Hit None(None+) [TORRENT] en mêlée → pas d'erreur torrent_wrong_hit_fight."""
    stats = _torrent_fight_log("Hit None(None+)", tmp_path)
    assert stats["torrent_wrong_hit_fight"][1] == 0, "faux positif mêlée TORRENT"


def test_torrent_melee_numerique_detecte(tmp_path):
    """VERROU : Hit 5(3+) [TORRENT] en mêlée → torrent_wrong_hit_fight incrémenté."""
    stats = _torrent_fight_log("Hit 5(3+)", tmp_path)
    assert stats["torrent_wrong_hit_fight"][1] == 1, "mismatch TORRENT mêlée non détecté"
    assert stats["first_error_lines"]["torrent_wrong_hit_fight"][1] is not None


# ─── 4. LETHAL HITS tir (PROJ.1.2.lethal_hits) ──────────────────────────────

def _lethal_shoot_log(wound_segment: str, tmp_path) -> dict:
    body = (
        DEPLOY_TORRENT
        + f"[10:00:03] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(90,50) with [Sternguard Bolt Rifle]"
        f" - Hit 6(3+) [LETHAL HITS] - {wound_segment} - Save 2(3+) - Dmg:0HP"
        f" [MODELS: 1#0@(50,50,z0)] [TARGET_MODELS: 101#0@(90,50,z0)]"
        f" [SHOOTER_MODELS: 1#0] [TARGET_DECL:1] [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(
        body, units=UNITS_TORRENT, objectives=OBJECTIVES,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    )
    return _parse(log_text, tmp_path)


def test_lethal_hits_tir_correct_pas_erreur(tmp_path):
    """VERROU : Wound None(4+) [LETHAL HITS] → pas d'erreur lethal_hits_wrong_wound."""
    stats = _lethal_shoot_log("Wound None(4+)", tmp_path)
    assert stats["lethal_hits_wrong_wound"][1] == 0, "faux positif LETHAL HITS tir"


def test_lethal_hits_tir_numerique_detecte(tmp_path):
    """VERROU : Wound 5(4+) [LETHAL HITS] → lethal_hits_wrong_wound incrémenté."""
    stats = _lethal_shoot_log("Wound 5(4+)", tmp_path)
    assert stats["lethal_hits_wrong_wound"][1] == 1, "mismatch LETHAL HITS tir non détecté"
    assert stats["first_error_lines"]["lethal_hits_wrong_wound"][1] is not None


# ─── 5. LETHAL HITS mêlée (PROJ.1.4.lethal_hits) ────────────────────────────

def _lethal_fight_log(wound_segment: str, tmp_path) -> dict:
    body = (
        DEPLOY_TORRENT_MELEE
        + f"[10:00:06] E1 T1 P1 FIGHT : Unit 1(50,50) FOUGHT Unit 101(50,51) with [Astartes Chainsword]"
        f" - Hit 6(3+) [LETHAL HITS] - {wound_segment} - Save 2(3+) - Dmg:0HP"
        f" [MODELS: 1#0@(50,50,z0)] [TARGET_MODELS: 101#0@(50,51,z0)]"
        f" [SHOOTER_MODELS: 1#0] [TARGET_DECL:1] [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(
        body, units=UNITS_TORRENT_MELEE, objectives=OBJECTIVES,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    )
    return _parse(log_text, tmp_path)


def test_lethal_hits_melee_correct_pas_erreur(tmp_path):
    """VERROU : Wound None(4+) [LETHAL HITS] en mêlée → pas d'erreur lethal_hits_wrong_wound_fight."""
    stats = _lethal_fight_log("Wound None(4+)", tmp_path)
    assert stats["lethal_hits_wrong_wound_fight"][1] == 0, "faux positif LETHAL HITS mêlée"


def test_lethal_hits_melee_numerique_detecte(tmp_path):
    """VERROU : Wound 5(4+) [LETHAL HITS] en mêlée → lethal_hits_wrong_wound_fight incrémenté."""
    stats = _lethal_fight_log("Wound 5(4+)", tmp_path)
    assert stats["lethal_hits_wrong_wound_fight"][1] == 1, "mismatch LETHAL HITS mêlée non détecté"
    assert stats["first_error_lines"]["lethal_hits_wrong_wound_fight"][1] is not None


# ─── 6. Réserves trop tôt (PROJ.1.1.reserves_too_early / 20.03) ─────────────

UNITS_RESERVES = (
    "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2"
    " base=round/6 [MODELS: 1#0@(-1,-1,z0)] [MODEL_TYPES: 1#0=AssaultIntercessor]\n"
    "[10:00:00] Unit 101 (Boyz) P2: Starting position (-1,-1), HP_MAX=1"
    " base=round/6 [MODELS: 101#0@(-1,-1,z0)]\n"
)


def _reserves_log(ingress_turn: int, tmp_path) -> dict:
    body = (
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(-1,-1) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [SUCCESS]\n"
        f"[10:00:02] E1 T{ingress_turn} P1 MOVE : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(
        body, units=UNITS_RESERVES, objectives=OBJECTIVES,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    )
    return _parse(log_text, tmp_path)


def test_reserves_too_early_round1_detecte(tmp_path):
    """VERROU : ingress en T1 (round 1) → reserves_too_early incrémenté."""
    stats = _reserves_log(1, tmp_path)
    assert stats["reserves_too_early"][1] == 1, "ingress round 1 non détecté"
    assert stats["first_error_lines"]["reserves_too_early"][1] is not None


def test_reserves_round2_pas_erreur(tmp_path):
    """VERROU : ingress en T2 (round 2) → pas d'erreur reserves_too_early."""
    stats = _reserves_log(2, tmp_path)
    assert stats["reserves_too_early"][1] == 0, "faux positif réserves round 2"


# ─── 7. BLAST valeur X incorrecte (PROJ.1.2.blast / 24.05) ─────────────────

# DeathwingTerminatorPlasmaCannon porte Plasma Cannon (Standard) avec BLAST:1.
# [BLAST:99] dans la ligne → logged_value(99) != declared(1) → blast_x_mismatch.
UNITS_BLAST = (
    "[10:00:00] Unit 1 (DeathwingTerminatorPlasmaCannon) P1: Starting position (50,50), HP_MAX=3"
    " base=round/6 [MODELS: 1#0@(50,50,z0)] [MODEL_TYPES: 1#0=DeathwingTerminatorPlasmaCannon]\n"
    "[10:00:00] Unit 101 (Boyz) P2: Starting position (90,50), HP_MAX=1"
    " base=round/6 [MODELS: 101#0@(90,50,z0) 101#1@(91,50,z0) 101#2@(92,50,z0)"
    " 101#3@(93,50,z0) 101#4@(94,50,z0)]\n"
)
DEPLOY_BLAST = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(90,50) DEPLOYED from (-1,-1) to (90,50) [R:+0.0] [SUCCESS]\n"
)


def _blast_log(blast_x: int, tmp_path) -> dict:
    target_models = " ".join(
        f"101#{i}@({90 + i},50,z0)" for i in range(5)
    )
    body = (
        DEPLOY_BLAST
        + f"[10:00:03] E1 T1 P1 SHOOT : Unit 1(50,50) SHOT Unit 101(90,50) with [Plasma Cannon (Standard)]"
        f" - Hit 4(3+) - Wound 5(3+) - Save 2(3+) - Dmg:1HP [BLAST:{blast_x}]"
        f" [MODELS: 1#0@(50,50,z0)] [TARGET_MODELS: {target_models}]"
        f" [SHOOTER_MODELS: 1#0] [TARGET_DECL:5] [R:+0.0] [SUCCESS]\n"
        + EPISODE_END
    )
    log_text = entete_step_log(
        body, units=UNITS_BLAST, objectives=OBJECTIVES,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    )
    return _parse(log_text, tmp_path)


def test_blast_valeur_correcte_pas_erreur(tmp_path):
    """VERROU : [BLAST:1] avec X=1 déclaré dans l'armurerie → pas d'erreur blast_x_mismatch."""
    stats = _blast_log(1, tmp_path)
    assert stats["blast_x_mismatch"][1] == 0, "faux positif BLAST valeur correcte"


def test_blast_valeur_incorrecte_detectee(tmp_path):
    """VERROU : [BLAST:99] avec X=1 attendu → blast_x_mismatch incrémenté."""
    stats = _blast_log(99, tmp_path)
    assert stats["blast_x_mismatch"][1] == 1, "mismatch BLAST non détecté"
    assert stats["first_error_lines"]["blast_x_mismatch"][1] is not None
