"""Test que les abilities dynamiques (grant_weapon_rule_melee et cousines) ne produisent
pas de verdict INVALID dans §1.8 de l'analyzer.

Trois abilities accordent une règle d'arme à l'exécution, absente de la datasheet :
  - grant_weapon_rule_melee        → SUSTAINED_HITS (Bigboss / "Two-Handed Big Choppa")
  - grant_weapon_rule_melee_after_charge → LETHAL_HITS
  - once_per_battle_melee_buff     → DEVASTATING_WOUNDS

Sans correction, la paire (SUSTAINED_HITS, "Two-Handed Big Choppa (Bigboss)") est
classée INVALID parce que SUSTAINED_HITS n'est pas dans la datasheet de cette arme.
Avec la correction, le verdict attendu est CONDITIONAL.
"""
from __future__ import annotations

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log, EPISODE_TAIL

FIGHTER = (50, 50)
TARGET = (50, 51)
F = f"({FIGHTER[0]},{FIGHTER[1]})"
T = f"({TARGET[0]},{TARGET[1]})"
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

_FOUGHT_LINE = (
    f"[10:00:02] E1 T1 P1 FIGHT : Unit 1{F} FOUGHT Unit 101{T}"
    " with [Two-Handed Big Choppa]"
    " - Hit 6(3+) - Wound 6(3+) [SUSTAINED HITS] - Save 5(4+) - Dmg:2HP"
    " [FIGHT_SUBPHASE:fight]"
    f" [MODELS: 1#0@({FIGHTER[0]},{FIGHTER[1]},z0)]"
    " [SHOOTER_MODELS: 1#0]"
    " [MODEL_TYPES: 1#0=Bigboss]"
    " [R:+0.0] [SUCCESS]\n"
)


def _step_log() -> str:
    units = (
        f"[10:00:00] Unit 1 (Bigboss) P1: Starting position {F},"
        f" HP_MAX=4 base=round/6 [MODELS: 1#0@({FIGHTER[0]},{FIGHTER[1]},z0)]\n"
        f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {T},"
        f" HP_MAX=2 base=round/6 [MODELS: 101#0@({TARGET[0]},{TARGET[1]},z0)]\n"
    )
    return entete_step_log(
        _FOUGHT_LINE + EPISODE_TAIL,
        units=units,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=ork (ref) OPPONENT=sm (ref)",
        objectives=OBJECTIVES,
    )


def _parse_and_render(tmp_path):
    log = tmp_path / "step.log"
    log.write_text(_step_log())
    stats = an.parse_step_log(str(log))
    lines: list[str] = []
    an.print_statistics(
        stats,
        debug_section_filter="1.8",
        output_lines=lines,
        emit_console=False,
    )
    return stats, lines


def test_bigboss_in_unit_types_seen(tmp_path):
    """Prémisse : Bigboss est vu dans le run, sinon le test est inopérant."""
    stats, _ = _parse_and_render(tmp_path)
    assert "Bigboss" in stats["unit_types_seen"], (
        "Bigboss introuvable dans unit_types_seen — vérifier la ligne de déclaration d'unité"
    )


def test_sustained_hits_pair_in_weapon_rule_usage(tmp_path):
    """Prémisse : la paire est enregistrée dans weapon_rule_usage lors du parsing."""
    stats, _ = _parse_and_render(tmp_path)
    pair = ("SUSTAINED_HITS", "Two-Handed Big Choppa (Bigboss)")
    assert pair in stats["weapon_rule_usage"], (
        f"Paire {pair} absente de weapon_rule_usage — la ligne FOUGHT n'a pas été parsée"
    )


def test_sustained_hits_absent_from_static_weapon_rule_to_weapons(tmp_path):
    """Prémisse : SUSTAINED_HITS n'est pas déclaré statiquement sur l'arme — donc c'est un accordé."""
    stats, _ = _parse_and_render(tmp_path)
    weapon_key = "Two-Handed Big Choppa (Bigboss)"
    static_set = stats.get("weapon_rule_to_weapons", {}).get("SUSTAINED_HITS", set())
    assert weapon_key not in static_set, (
        "La datasheet déclare maintenant SUSTAINED_HITS statiquement — ce test n'est plus pertinent"
    )


def test_section_1_8_shows_conditional_not_invalid(tmp_path):
    """§1.8 doit afficher CONDITIONAL (pas INVALID) pour une règle accordée dynamiquement."""
    _, lines = _parse_and_render(tmp_path)
    # "SUSTAINED_HITS".capitalize() → "Sustained_hits" dans la colonne règle
    sustained_lines = [
        l for l in lines
        if "Two-Handed Big Choppa (Bigboss)" in l and "Sustained_hits" in l
    ]
    assert sustained_lines, (
        "Aucune ligne §1.8 pour 'Sustained_hits / Two-Handed Big Choppa (Bigboss)'"
    )
    for line in sustained_lines:
        assert "CONDITIONAL" in line, (
            f"Attendu CONDITIONAL dans la ligne §1.8, obtenu : {line!r}"
        )
        assert "INVALID" not in line, (
            f"INVALID ne doit pas apparaître pour une règle accordée dynamiquement : {line!r}"
        )


def test_error_totals_weapon_rules_invalid_excludes_conditional(tmp_path):
    """error_totals ne compte pas comme INVALID les paires issues d'abilities dynamiques."""
    stats, _ = _parse_and_render(tmp_path)
    totals = an.error_totals(stats)
    assert totals["weapon_rules_invalid"] == 0, (
        f"weapon_rules_invalid={totals['weapon_rules_invalid']} : "
        "la paire SUSTAINED_HITS/Bigboss accordée dynamiquement ne doit pas compter"
    )


def test_cross_pair_contamination_error_totals(tmp_path):
    """Bigboss dans le run ne doit pas exempter SUSTAINED_HITS sur une autre unité sans l'ability."""
    stats, _ = _parse_and_render(tmp_path)
    assert "Bigboss" in stats["unit_types_seen"]
    # Simuler un bug moteur : AssaultIntercessor (sans grant_weapon_rule_melee) génère SUSTAINED_HITS.
    other_pair = ("SUSTAINED_HITS", "Astartes Chainsword (AssaultIntercessor)")
    stats["weapon_rule_usage"][other_pair] = {1: 0, 2: 1}
    # Prémisse : non déclaré statiquement.
    assert "Astartes Chainsword (AssaultIntercessor)" not in stats.get("weapon_rule_to_weapons", {}).get("SUSTAINED_HITS", set())
    # AssaultIntercessor n'a pas l'ability → cette paire est un vrai INVALID.
    totals = an.error_totals(stats)
    assert totals["weapon_rules_invalid"] == 1, (
        f"weapon_rules_invalid={totals['weapon_rules_invalid']} : "
        "la paire Chainsword/AssaultIntercessor est INVALID, pas CONDITIONAL"
    )


def test_cross_pair_contamination_section_1_8(tmp_path):
    """§1.8 affiche INVALID (pas CONDITIONAL) pour une paire sans ability dynamique."""
    stats, _ = _parse_and_render(tmp_path)
    assert "Bigboss" in stats["unit_types_seen"]
    other_pair = ("SUSTAINED_HITS", "Astartes Chainsword (AssaultIntercessor)")
    stats["weapon_rule_usage"][other_pair] = {1: 0, 2: 1}
    lines: list[str] = []
    an.print_statistics(stats, debug_section_filter="1.8", output_lines=lines, emit_console=False)
    chainsword_sustained = [
        l for l in lines
        if "Astartes Chainsword (AssaultIntercessor)" in l and "Sustained_hits" in l
    ]
    assert chainsword_sustained, "Ligne §1.8 pour Astartes Chainsword/SUSTAINED_HITS introuvable"
    for line in chainsword_sustained:
        assert "INVALID" in line, (
            f"Attendu INVALID pour Chainsword/AssaultIntercessor, obtenu : {line!r}"
        )
        assert "CONDITIONAL" not in line, (
            f"CONDITIONAL ne doit pas apparaître pour une paire sans ability : {line!r}"
        )
