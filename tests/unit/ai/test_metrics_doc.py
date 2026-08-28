"""Garde doc → code : metriques.md ne cite aucun tag absent de ai/*.py.

SENS UNIQUE (doc → code) seulement.

La direction inverse (code → doc) est VOLONTAIREMENT ABSENTE — statiquement
indécidable :
  - ai/metrics_tracker.py contient des add_scalar dont le tag est construit par
    f-string (ex. ``f'bot_eval/vs_{bot_name}'``, ``f'actions/share_{family}'``,
    ``f'reserves/{_metric}_{_side}'``) — aucune extraction statique ne les couvre.
  - ai/training_callbacks.py accède directement à metrics_tracker.writer.add_scalar
    sans passer par les méthodes du tracker — ces appels sont invisibles à
    toute analyse du module tracker seul.
Mesure du 2026-08-28 : training_callbacks.py écrit via metrics_tracker.writer aux
lignes ≈958, 2149, 2231, dont certains à tag construit par f-string.
Même doctrine que le « NON VÉRIFIABLE, et assumé » de scripts/check_doc_references.py.

PREUVE PAR MUTATION :
  Renommer un tag documenté dans metriques.md (ex. ``02_combat/k_units_killed_ratio``
  → ``02_combat/k_units_killed_WRONG``) → ce test passe ROUGE.
  Restaurer le tag → VERT.
  Purger __pycache__ si la mutation est de même longueur que l'original (sinon Python
  exécute le .pyc muté et le test reste vert à tort — trap documenté dans
  feedback_mutation_pyc_trap.md).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
AI_DIR = REPO_ROOT / "ai"
TRACKER_PATH = AI_DIR / "metrics_tracker.py"
DOC_PATH = REPO_ROOT / "Documentation" / "Reference" / "training" / "metriques.md"


# ---------------------------------------------------------------------------
# Extraction côté CODE
# ---------------------------------------------------------------------------

def _ai_source() -> str:
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


def _reserves_tags(source: str) -> frozenset[str]:
    """Tags ``reserves/{metric}_{side}`` assemblés par double boucle for.

    La template ``f'reserves/{_metric}_{_side}'`` dans ai/metrics_tracker.py itère
    sur un tuple de métriques et le couple ('agent', 'opponent'). Ce test extrait les
    deux tuples par regex et génère les 12 combinaisons (6 métriques × 2 camps).
    """
    if "f'reserves/{_metric}_{_side}'" not in source:
        return frozenset()
    # Tuple externe (_metric) : se termine juste avant "for _side in".
    m_loop = re.search(
        r"for _metric in \(([\s\S]*?)\):\s*for _side in \(([^)]+)\)",
        source,
    )
    if not m_loop:
        return frozenset()
    metrics = [
        v.strip().strip("'\"")
        for v in m_loop.group(1).split(",")
        if v.strip().strip("'\"")
    ]
    sides = [
        v.strip().strip("'\"")
        for v in m_loop.group(2).split(",")
        if v.strip().strip("'\"")
    ]
    return frozenset(f"reserves/{m}_{s}" for m in metrics for s in sides)


def _bot_eval_vs_tags(ai_source: str) -> frozenset[str]:
    """Tags ``bot_eval/vs_{key}`` déduits de la template f-string dans le code.

    La template ``f'bot_eval/vs_{bot_name}'`` itère sur les clés de bots ;
    les clés sont lues depuis ai/bot_registry.py.
    """
    if "f'bot_eval/vs_{bot_name}'" not in ai_source:
        return frozenset()
    registry = (AI_DIR / "bot_registry.py").read_text(encoding="utf-8")
    # Identifiants minuscules avec underscores optionnels — couvre toutes les clés de bots.
    keys = set(re.findall(r"""["']([a-z][a-z_]*)["']""", registry))
    return frozenset(f"bot_eval/vs_{k}" for k in keys if k)


def _code_tags() -> frozenset[str]:
    """Tags émis dans ai/*.py, via quatre populations.

    1. Littéraux — toute chaîne quotée contenant un '/' (namespace/tag).
    2. Assemblés DEPLOY — DEPLOY_SPLIT_SERIES × DEPLOY_MODES.
    3. Assemblés reserves — ``reserves/{metric}_{side}`` depuis la double boucle.
    4. Assemblés bot_eval — ``bot_eval/vs_{key}`` depuis la template f-string.

    Les préfixes nus (sans suffixe de mode) sont exclus pour ne pas polluer le résultat.
    """
    source = _ai_source()
    literals: frozenset[str] = frozenset(
        re.findall(r"""["']([A-Za-z0-9_]+(?:/[A-Za-z0-9_./-]+)+)["']""", source)
    )
    prefixes = _deploy_prefixes(source)
    modes = _deploy_modes(source)
    assembled_deploy = frozenset(f"{p}_{m}" for p in prefixes for m in modes)
    return (
        (literals - prefixes)
        | assembled_deploy
        | _reserves_tags(source)
        | _bot_eval_vs_tags(source)
    )


# ---------------------------------------------------------------------------
# Extraction côté DOC
# ---------------------------------------------------------------------------

def _expand_brace_tag(tag: str) -> list[str]:
    """Expande ``prefix_{a,b}suffix`` → ``['prefix_asuffix', 'prefix_bsuffix']``."""
    m = re.match(r"([^{]+)\{([^}]+)\}(.*)", tag)
    if not m:
        return [tag]
    prefix, parts, suffix = m.group(1), m.group(2).split(","), m.group(3)
    return [f"{prefix}{v.strip()}{suffix}" for v in parts]


_KNOWN_NAMESPACES: frozenset[str] = frozenset({
    "00_critical", "01_VP", "02_combat", "03_move", "04_shoot", "05_charge",
    "06_fight", "bot_eval", "game_critical", "game_tactical", "game_detailed",
    "combat", "seat_aware", "perf", "forcing", "reserves", "actions", "abilities",
})


def _is_metric_tag(s: str) -> bool:
    """True si ``s`` ressemble à un tag TensorBoard du projet, pas un chemin ou une commande."""
    # Templates avec placeholders non expansés ou caractères parasites.
    if any(c in s for c in ("<", ">", "{", "|", ";", "(", ")", " ", ":")):
        return False
    parts = s.split("/")
    if len(parts) < 2 or not parts[-1]:
        return False
    # Espace de noms SB3 natif — jamais émis par notre code.
    if parts[0] == "train":
        return False
    # L'espace de noms doit être connu (évite et/ou, i_/g_, chemins de fichiers…).
    if parts[0] not in _KNOWN_NAMESPACES:
        return False
    return True


def _doc_tags() -> frozenset[str]:
    """Tags cités dans metriques.md, deux méthodes complémentaires.

    1. Backticks avec '/' dans tout le document — couvre les sections Namespaces,
       Panel de bots, Dashboard 00_critical (descriptions de lignes) et Métriques par
       domaine. Les tags ``train/`` (SB3 natif) et les chemins de fichiers sont filtrés.

    2. Notation bold dans la section Dashboard 00_critical — les 20 tags principaux
       du tableau y apparaissent en gras (``**00_critical/...**``), pas en backticks ;
       les deux méthodes se complètent.
    """
    text = DOC_PATH.read_text(encoding="utf-8")
    tags: set[str] = set()

    # --- 1. Backticks (une seule ligne — les blocs ``` traversent les sauts de ligne).
    for raw in re.findall(r"`([^\n`]+/[^\n`]+)`", text):
        for expanded in _expand_brace_tag(raw.strip()):
            if _is_metric_tag(expanded):
                tags.add(expanded)

    # --- 2. Bold dans la section Dashboard 00_critical.
    start = text.find("## Dashboard 00_critical")
    if start == -1:
        return frozenset(tags)
    m_end = re.search(r"^## ", text[start + 1:], re.M)
    dashboard = text[start: start + 1 + m_end.start()] if m_end else text[start:]
    for raw in re.findall(r"\*\*(00_critical/[^*\s]+)\*\*", dashboard):
        for expanded in _expand_brace_tag(raw):
            tags.add(expanded)

    return frozenset(tags)


# ---------------------------------------------------------------------------
# Test — sens UNIQUE doc → code
# ---------------------------------------------------------------------------

def test_every_documented_tag_exists_in_code() -> None:
    """Chaque tag cité dans metriques.md existe dans ai/*.py.

    Échec → tag renommé ou supprimé dans le code sans mise à jour du document
    (ou ajouté dans le document sans être émis).

    La direction inverse (code → doc) n'est PAS testée ici — voir module docstring.
    """
    doc = _doc_tags()
    code = _code_tags()
    missing = doc - code
    assert not missing, (
        "Tags cités dans metriques.md absents de ai/*.py\n"
        "(renommé/supprimé dans le code sans mise à jour du doc) :\n"
        + "\n".join(f"  {t}" for t in sorted(missing))
    )
