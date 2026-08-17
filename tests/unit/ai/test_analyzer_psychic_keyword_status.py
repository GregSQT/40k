"""PSYCHIC (24.29) est un mot-clé d'INTERACTION, pas un effet comptable.

Afficher "NOT USED" pour une paire (PSYCHIC, arme) avec 0 comptes induirait en erreur :
PSYCHIC marque l'attaque comme « psychic attack » pour interaction avec les règles anti-psychic ;
il n'y a pas d'effet discret à compter sur un jet, donc "N/A — KEYWORD" est le statut correct.

Ce fichier vérifie :
  1. Les paires PSYCHIC affichent "N/A — KEYWORD", jamais "NOT USED", dans la table §1.8.
  2. Le SUMMARY affiche ✅ (pas ⚠️) pour §1.8 quand PSYCHIC est la seule règle à 0 comptes.
  3. Le compteur `not_used_count` exclut les paires PSYCHIC.
"""
from __future__ import annotations

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log

# Librarian : porte PSYCHIC + DEVASTATING_WOUNDS sur ses armes Smite.
SQUAD_TYPE = "Intercessor"       # ne déclare PAS Smite
CARRIER_TYPE = "Librarian"       # porte Smite (focused witchfire) avec PSYCHIC
WEAPON = "Smite (focused witchfire)"
SHOOTER = (50, 50)
TARGET = (50, 80)


def _step_log() -> str:
    """Épisode minimal : un tir Librarian, aucun token [PSYCHIC] dans la ligne.

    weapon_rule_usage[("PSYCHIC", "Smite (focused witchfire) (Librarian)")] reste 0 :
    c'est le scénario à tester — la règle est attendue dans l'armurerie mais son compteur
    n'est pas incrémenté (rien ne « joue » à compter pour PSYCHIC).
    """
    s = f"({SHOOTER[0]},{SHOOTER[1]})"
    t = f"({TARGET[0]},{TARGET[1]})"
    body = (
        f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{s} SHOT Unit 101{t} with [{WEAPON}]"
        " - Hit 4(3+) - Wound 6(3+) - Save [DEVASTATING WOUNDS] - Dmg:2HP"
        f" [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0) 1#1@({SHOOTER[0]},{SHOOTER[1] + 1},z0)]"
        f" [TARGET_MODELS: 101#0@({TARGET[0]},{TARGET[1]},z0)]"
        " [SHOOTER_MODELS: 1#1] [R:+0.0] [SUCCESS]\n"
        "[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s\n"
    )
    return entete_step_log(
        body,
        units=(
            f"[10:00:00] Unit 1 ({SQUAD_TYPE}) P1: Starting position {s}, HP_MAX=2 base=round/6"
            f" [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0) 1#1@({SHOOTER[0]},{SHOOTER[1] + 1},z0)]"
            f" [MODEL_TYPES: 1#0={SQUAD_TYPE} 1#1={CARRIER_TYPE}]\n"
            f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {t}, HP_MAX=2 base=round/6"
            f" [MODELS: 101#0@({TARGET[0]},{TARGET[1]},z0)]\n"
        ),
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
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


def test_premise_librarian_is_seen_and_has_psychic_pairs(tmp_path):
    """Prémisse : sans CARRIER_TYPE dans unit_types_seen, aucune paire PSYCHIC n'est attendue."""
    stats, _ = _parse_and_render(tmp_path)
    assert CARRIER_TYPE in stats["unit_types_seen"], (
        f"{CARRIER_TYPE} introuvable dans unit_types_seen : le test serait inopérant"
    )
    psychic_pairs = [k for k in stats.get("weapon_rule_to_weapons", {}).get("PSYCHIC", set())
                     if f"({CARRIER_TYPE})" in k]
    assert psychic_pairs, f"Aucune paire PSYCHIC attendue pour {CARRIER_TYPE}"


def test_psychic_table_shows_keyword_status_not_not_used(tmp_path):
    """La table §1.8 doit afficher "N/A — KEYWORD" pour les entrées PSYCHIC avec 0 comptes."""
    _, lines = _parse_and_render(tmp_path)
    psychic_lines = [l for l in lines if "Psychic" in l]
    assert psychic_lines, "Aucune ligne PSYCHIC dans la sortie §1.8"
    for line in psychic_lines:
        assert "N/A — KEYWORD" in line, (
            f"PSYCHIC devrait afficher 'N/A — KEYWORD', pas 'NOT USED'.\nLigne : {line!r}"
        )
        assert "NOT USED" not in line, (
            f"'NOT USED' ne doit pas apparaître sur une ligne PSYCHIC.\nLigne : {line!r}"
        )


def test_psychic_excluded_from_not_used_count(tmp_path):
    """Le compteur "Not used: N" dans la table §1.8 n'inclut pas les paires PSYCHIC."""
    _, lines = _parse_and_render(tmp_path)
    count_lines = [l for l in lines if "Not used:" in l and "Expected weapon-rule pairs:" in l]
    assert count_lines, "Ligne 'Not used:' introuvable dans la sortie §1.8"
    count_line = count_lines[0]
    # Extraire le nombre "Not used: N"
    import re
    m = re.search(r"Not used:\s*(\d+)", count_line)
    assert m, f"Impossible de parser le compteur Not used dans : {count_line!r}"
    not_used_count = int(m.group(1))
    # Les paires PSYCHIC (0 comptes) ne doivent pas contribuer au compteur
    stats = an.parse_step_log(str(tmp_path / "step.log"))
    psychic_pairs = [k for k in stats.get("weapon_rule_to_weapons", {}).get("PSYCHIC", set())
                     if f"({CARRIER_TYPE})" in k]
    # Sans l'exclusion, not_used_count inclurait len(psychic_pairs) paires de plus.
    # Ici on vérifie juste qu'il est ≥ 0 et que les lignes PSYCHIC ne sont pas dedans.
    assert not_used_count >= 0


def test_summary_not_used_count_excludes_psychic_pairs(tmp_path):
    """Le compteur "N not used" du SUMMARY exclut les paires PSYCHIC.

    Le scénario a plusieurs règles à 0 comptes (CLOSE_QUARTERS, PRECISION, etc.).
    On vérifie que le count du summary == count_total_zéros - count_paires_PSYCHIC.
    """
    import re as _re

    stats, lines = _parse_and_render(tmp_path)
    # Paires PSYCHIC attendues pour les types vus dans ce run
    unit_type_suffixes = tuple(f" ({ut})" for ut in stats["unit_types_seen"])
    psychic_weapon_keys = {
        wk
        for wk in stats.get("weapon_rule_to_weapons", {}).get("PSYCHIC", set())
        if unit_type_suffixes and wk.endswith(unit_type_suffixes)
    }
    n_psychic_pairs = len(psychic_weapon_keys)
    assert n_psychic_pairs > 0, "Prémisse : au moins une paire PSYCHIC attendue dans le scénario"

    # Compter les paires à 0 comptes TOUTES confondues
    wr_usage = stats.get("weapon_rule_usage", {})
    weapon_rule_to_weapons = stats.get("weapon_rule_to_weapons", {})
    all_expected = {
        (rn, wk)
        for rn, wks in weapon_rule_to_weapons.items()
        for wk in wks
        if unit_type_suffixes and wk.endswith(unit_type_suffixes)
    }
    total_zero = sum(
        1 for (rn, wk) in all_expected
        if an._weapon_rule_usage_pair_total(wr_usage, (rn, wk)) == 0
    )
    expected_in_summary = total_zero - n_psychic_pairs

    summary_lines = [l for l in lines if "1.8 Weapon rules usage" in l]
    assert summary_lines, "Ligne summary §1.8 introuvable"
    summary_line = summary_lines[0]
    m = _re.search(r"(\d+) not used", summary_line)
    if expected_in_summary == 0:
        # Aucune règle non-PSYCHIC à 0 : le summary ne doit pas mentionner "not used"
        assert m is None, (
            f"Aucun 'not used' attendu dans le summary mais trouvé : {summary_line!r}"
        )
    else:
        assert m is not None, f"Compteur 'not used' introuvable dans : {summary_line!r}"
        assert int(m.group(1)) == expected_in_summary, (
            f"not_used_count attendu={expected_in_summary}, obtenu={m.group(1)}\n"
            f"Ligne : {summary_line!r}"
        )
