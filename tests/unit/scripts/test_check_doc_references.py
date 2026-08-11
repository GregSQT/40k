"""Verrous du contrôle documentaire.

Ce que ces tests protègent, et pourquoi chacun existe :

- la RÉSOLUTION des chemins relatifs. Le 2026-08-11, le contrôle rendait 18 renvois cassés sur
  `V11_phaseA.md` alors que les 9 cibles distinctes existaient toutes : la classe de caractères
  de la regex excluait le point, `../../engine/x.py` devenait `/engine/x.py`, et `ROOT / name`
  transformait ce fragment en chemin absolu inexistant.
- la DÉTECTION d'une valeur périmée. Un contrôle qui ne sait que confirmer ne prouve rien : il
  faut montrer qu'il vire au rouge quand le document ment.
- l'ASSERTION ORPHELINE. C'est la garde anti-vert-vacant : sans elle, reformuler la phrase suffit
  à désarmer le contrôle en silence, et on retrouve le défaut qu'il devait fermer.
- l'ABSENCE d'appariement en prose, et le rejet des faux positifs par la FORME. Un contrôle qui
  crie à tort finit désactivé ; ces deux cas sont ceux qui le faisaient crier.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "check_doc_references", ROOT / "scripts" / "check_doc_references.py"
)
assert _SPEC is not None and _SPEC.loader is not None
cdr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cdr)


def write(tmp_path: pathlib.Path, name: str, body: str) -> pathlib.Path:
    doc = tmp_path / name
    doc.write_text(body, encoding="utf-8")
    return doc


# --------------------------------------------------------------------------- résolution


def test_parent_relative_path_resolves() -> None:
    """`../../engine/…` depuis un doc de `1_Agent/` désigne bien le fichier du dépôt."""
    doc_dir = ROOT / "Documentation" / "Implémentation" / "1_Agent"
    assert cdr.resolve("../../../engine/w40k_core.py", doc_dir) == ROOT / "engine" / "w40k_core.py"


def test_parent_relative_path_is_captured_whole() -> None:
    """La regex capture le préfixe `../`, sinon la résolution reçoit un fragment absolu."""
    assert cdr.names_in("voir [x](../../../engine/w40k_core.py)") == ["../../../engine/w40k_core.py"]


def test_doc_relative_and_root_relative_both_resolve() -> None:
    """Les deux conventions du corpus coexistent et doivent être servies toutes les deux."""
    docs = ROOT / "Documentation" / "Implémentation"
    assert cdr.resolve("1_Agent/V11_phaseA.md", docs) is not None
    assert cdr.resolve("engine/w40k_core.py", docs) is not None


def test_absolute_path_that_does_not_exist_is_broken() -> None:
    """Un absolu faux reste faux : le réessayer depuis la racine masquerait un renvoi cassé."""
    assert cdr.resolve("/engine/w40k_core.py", ROOT) is None


# --------------------------------------------------------------------------- valeurs


def test_stale_value_is_detected(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "ROADMAP.md", "les **99** profils sont à 48 envs\n")
    _verified, broken = cdr.check_values(doc)
    assert any("VALEUR PÉRIMÉE" in entry and "99" in entry for entry in broken)


def test_true_value_is_confirmed(tmp_path: pathlib.Path) -> None:
    count = len(cdr.agent_profiles())
    doc = write(tmp_path, "ROADMAP.md", f"les **{count}** profils\n")
    verified, broken = cdr.check_values(doc)
    assert verified == 1
    assert not any("VALEUR PÉRIMÉE" in entry for entry in broken)


def test_orphan_assertion_is_reported(tmp_path: pathlib.Path) -> None:
    """Une phrase reformulée doit faire ROUGIR le contrôle, pas le rendre muet."""
    doc = write(tmp_path, "ROADMAP.md", "plus aucune des phrases surveillees ici\n")
    _verified, broken = cdr.check_values(doc)
    assert len(broken) == len(cdr.VALUE_CHECKS["ROADMAP.md"])
    assert all("ASSERTION ORPHELINE" in entry for entry in broken)


def test_profile_table_reads_thousands_separator(tmp_path: pathlib.Path) -> None:
    """« 10 000 » vaut dix mille : le lire comme 10 inventerait une valeur périmée."""
    episodes = cdr.agent_profiles()["x1"]["total_episodes"]
    final = cdr.agent_profiles()["x1"]["callback_params"]["bot_eval_final"]
    doc = write(tmp_path, "ROADMAP.md", f"| `x1` | {episodes:,} | {final} |\n".replace(",", " "))
    claims = dict(cdr.claim_profile_table(doc.read_text(encoding="utf-8")))
    assert claims["x1.total_episodes"] == episodes


# --------------------------------------------------------------------------- liens


def test_dead_link_is_detected(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "voir [ça](A_faire/ce_fichier_n_existe_pas.md)\n")
    _checked, _skipped, broken = cdr.check_links(doc)
    assert len(broken) == 1 and "LIEN MORT" in broken[0]


@pytest.mark.parametrize("target", ["fichier", '[^"\\\']+'])
def test_regex_noise_is_not_taken_for_a_link(tmp_path: pathlib.Path, target: str) -> None:
    """Écartés sur la FORME. Une liste d'exceptions nommées masquerait un vrai lien mort."""
    doc = write(tmp_path, "note.md", f"texte [x]({target}#L1)\n")
    checked, skipped, broken = cdr.check_links(doc)
    assert (checked, skipped, broken) == (0, 1, [])


def test_live_link_is_verified(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "voir [le moteur](engine/w40k_core.py)\n")
    checked, _skipped, broken = cdr.check_links(doc)
    assert checked == 1 and not broken


# --------------------------------------------------------------------------- renvois


def test_prose_never_pairs_symbols(tmp_path: pathlib.Path) -> None:
    """Une phrase cite un fichier et, plus loin, des symboles étrangers : pas une erreur."""
    doc = write(tmp_path, "note.md", "la suite large (`pyright`, `check_ai_rules.py`, `biome`)\n")
    resolved, unverifiable, broken = cdr.check_references(doc)
    assert (resolved, unverifiable, broken) == (0, 1, [])


def test_table_cell_still_pairs_symbols(tmp_path: pathlib.Path) -> None:
    """Le tableau reste le lieu du renvoi PORTEUR : l'appariement doit y rester actif."""
    doc = write(tmp_path, "note.md", "| x | `engine/w40k_core.py` → `_get_unit_by_id` | y |\n")
    resolved, _unverifiable, broken = cdr.check_references(doc)
    assert resolved == 1 and not broken


def test_table_cell_with_absent_symbol_is_broken(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "| x | `engine/w40k_core.py` → `zzz_symbole_absent` | y |\n")
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert len(broken) == 1 and "AUCUN SYMBOLE" in broken[0]


def test_brace_enumeration_is_not_a_file(tmp_path: pathlib.Path) -> None:
    """`{move,charge}_handler.py` désigne un ensemble ; `_handler.py` n'existe pas."""
    doc = write(tmp_path, "note.md", "`ai/analyzer_phases/{move,charge}_handler.py` et le reste\n")
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert not broken


def test_missing_file_in_table_is_broken(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "| x | `engine/ce_module_n_existe_pas.py` | `truc` |\n")
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert len(broken) == 1 and "FICHIER INTROUVABLE" in broken[0]


# --------------------------------------------------------------------------- ancres


def test_line_anchor_is_reported(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "ROADMAP.md", "voir `engine/observation_entities.py:274`\n")
    assert len(cdr.check_anchors(doc)) == 1


def test_symbol_reference_is_not_an_anchor(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "ROADMAP.md", "voir `def compute_candidate_footprint` dans le moteur\n")
    assert cdr.check_anchors(doc) == []


# --------------------------------------------------------------------------- corpus réel


def test_a_dotted_call_is_not_a_file(tmp_path: pathlib.Path) -> None:
    """`hashlib.md5` n'est pas un fichier `hashlib.md` — mesuré comme fausse alerte réelle."""
    doc = write(tmp_path, "note.md", "| x | on dépose un `hashlib.md5` dans `config/` | y |\n")
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert not broken


def test_reference_documents_are_clean() -> None:
    """Les trois documents d'entrée passent le contrôle — c'est la ligne de base à tenir."""
    for name in ("analyzer_couverture.md", "ROADMAP.md", "Security.md"):
        path = ROOT / "Documentation" / "Implémentation" / name
        _resolved, _unverifiable, broken_refs = cdr.check_references(path)
        _checked, _skipped, broken_links = cdr.check_links(path)
        _verified, broken_values = cdr.check_values(path)
        broken = broken_refs + broken_links + broken_values + cdr.check_anchors(path)
        assert not broken, f"{name} : " + " | ".join(broken)
