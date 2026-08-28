"""Garde doc : metriques.md dit vrai sur les tags 00_critical/*.

Ce dépôt a été mordu trois fois par une doc qui recopie un schéma dérivé du code sans que rien
ne le signale (AI_OBSERVATION.md). Ce test ferme la boucle pour les métriques : un tag renommé
ou supprimé dans le code fait échouer ce fichier, exactement comme une régression de code.

Il ne vérifie PAS la prose — seulement que chaque tag **00_critical/x** documenté dans la
section « Dashboard 00_critical » est émis dans ai/*.py, et réciproquement.

Sources :
  - Code   : add_scalar string literals + DEPLOY_SPLIT_SERIES × DEPLOY_MODES dans ai/*.py
  - Doc    : **00_critical/...** dans la section Dashboard 00_critical de metriques.md
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
AI_DIR = REPO_ROOT / "ai"
DOC_PATH = REPO_ROOT / "Documentation" / "Reference" / "training" / "metriques.md"


# ---------------------------------------------------------------------------
# Extraction côté CODE
# ---------------------------------------------------------------------------

def _source() -> str:
    """Concaténation de tous les fichiers ai/*.py."""
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(AI_DIR.glob("*.py")))


def _deploy_prefixes(source: str) -> frozenset[str]:
    """Valeurs de DEPLOY_SPLIT_SERIES (préfixes de tags sans suffixe de mode)."""
    m = re.search(r"DEPLOY_SPLIT_SERIES\s*=\s*\{(.*?)\}", source, re.S)
    if not m:
        return frozenset()
    return frozenset(re.findall(r"""["'](00_critical/[^"']+)["']""", m.group(1)))


def _deploy_modes(source: str) -> frozenset[str]:
    """Éléments de DEPLOY_MODES (suffixes de mode)."""
    m = re.search(r"DEPLOY_MODES\s*=\s*\(([^)]+)\)", source)
    if not m:
        return frozenset()
    return frozenset(re.findall(r"""["']([^"']+)["']""", m.group(1)))


def _code_tags() -> frozenset[str]:
    """Tags 00_critical/* émis dans ai/*.py.

    Deux populations :
    1. Littéraux — toute chaîne "00_critical/..." dans le source (couvre add_scalar,
       _emit_windowed, etc.).
    2. Assemblés — DEPLOY_SPLIT_SERIES.values() × DEPLOY_MODES ; ces tags ne sont jamais des
       littéraux complets (le préfixe nu est dans la constante de classe, le suffixe de mode
       est ajouté à l'exécution).

    Les préfixes nus (sans suffixe) sont retirés des littéraux pour ne pas polluer le
    résultat avec des chaînes qui ne sont pas des tags TensorBoard complets.
    """
    source = _source()
    literals: frozenset[str] = frozenset(
        re.findall(r"""["'](00_critical/[A-Za-z0-9_./-]+)["']""", source)
    )
    prefixes = _deploy_prefixes(source)
    modes = _deploy_modes(source)
    assembled = frozenset(f"{p}_{m}" for p in prefixes for m in modes)
    return (literals - prefixes) | assembled


# ---------------------------------------------------------------------------
# Extraction côté DOC
# ---------------------------------------------------------------------------

def _doc_section() -> str:
    """Section 'Dashboard 00_critical' isolée depuis metriques.md."""
    text = DOC_PATH.read_text(encoding="utf-8")
    start = text.index("## Dashboard 00_critical")
    m_end = re.search(r"^## ", text[start + 1:], re.M)
    end = start + 1 + m_end.start() if m_end else len(text)
    return text[start:end]


def _expand_brace_tag(tag: str) -> list[str]:
    """Expande '00_critical/p_{a,b}' → ['00_critical/p_a', '00_critical/p_b']."""
    m = re.match(r"(00_critical/[^{]+)\{([^}]+)\}(.*)", tag)
    if not m:
        return [tag]
    prefix, parts, suffix = m.group(1), m.group(2).split(","), m.group(3)
    return [f"{prefix}{v.strip()}{suffix}" for v in parts]


def _doc_tags() -> frozenset[str]:
    """Tags **00_critical/...** documentés dans la section Dashboard de metriques.md."""
    section = _doc_section()
    raw = re.findall(r'\*\*(00_critical/[^*\s]+)\*\*', section)
    tags: set[str] = set()
    for tag in raw:
        tags.update(_expand_brace_tag(tag))
    return frozenset(tags)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_every_documented_tag_is_emitted():
    """Chaque **00_critical/x** du doc existe comme tag émis dans ai/*.py."""
    doc = _doc_tags()
    code = _code_tags()
    missing = doc - code
    assert not missing, (
        "tags documentés dans metriques.md mais absents de ai/*.py :\n"
        + "\n".join(f"  {t}" for t in sorted(missing))
    )


def test_every_emitted_tag_is_documented():
    """Chaque tag 00_critical/* émis dans ai/*.py est documenté dans metriques.md."""
    doc = _doc_tags()
    code = _code_tags()
    extra = code - doc
    assert not extra, (
        "tags émis dans ai/*.py mais absents de metriques.md (Dashboard 00_critical) :\n"
        + "\n".join(f"  {t}" for t in sorted(extra))
    )
