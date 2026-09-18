"""Verrou : les RANGS et les COMPTES de types de décision écrits en prose disent vrai.

`AGENT_DECISION_TYPE_IDS` est un tuple ORDONNÉ : le rang d'un type y fixe sa colonne
`decision_ctx_bin`. Plusieurs documents citent ce rang (« 15e type de … ») et ce compte
(« 15 types déclarés et 9 réservés ») en les RECOPIANT — exactement le motif qui a déjà périmé
trois fois `observation_et_actions.md` (cf. l'en-tête de `test_squad_obs_structure_doc.py`).

Le déclencheur mesuré ici n'est pas l'oubli : c'est le MERGE. `suppress_target` (793080134) et
`consolidation_engaging` (0c92f4e2b) ont été écrits sur deux branches parallèles ; la résolution
de conflit de `bf49835087` a placé le premier en 14e et le second en 15e, alors que les six
documents rédigés pendant les deux chantiers disaient tous « 14e » — vrai à l'écriture, faux
après. Aucun test ne le voyait, et le décalage n'a été découvert qu'à cause d'un AUTRE test rouge.

Ce fichier lit le tuple dans le CODE et confronte chaque nombre écrit en prose. Il ne juge pas la
formulation : seulement les chiffres.

PORTÉE DÉLIBÉRÉMENT ÉTROITE. Les motifs ne reconnaissent que trois tournures, et pas leurs
voisines (« 12 types pour 16 colonnes réservées », « déclaré en 14e position ») : celles-là
décrivent des états PASSÉS que ce test n'a pas à arbitrer. Élargir un motif sans vérifier qu'il
n'attrape aucune ligne d'historique rendrait ce verrou faux, donc inutile.

CONSÉQUENCE À CONNAÎTRE : dans les fichiers de SOURCES, un rang ou un compte PÉRIMÉ ne peut plus
être cité littéralement, même entre guillemets pour dire qu'il était faux — ce test ne distingue
pas la citation de l'affirmation. Rencontré en écrivant l'entrée de roadmap de ce chantier, et
résolu en la formulant sans les chiffres (« un rang d'un cran trop bas »). C'est le prix d'un
verrou sans mécanisme d'exception ; un tel mécanisme serait la première chose qu'on oublierait
de retirer.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

from engine.observation_entities import (
    AGENT_DECISION_TYPE_IDS,
    AGENT_DECISION_TYPE_SLOTS,
)

ROOT = Path(__file__).resolve().parents[3]

#: Les documents qui citent le rang ou le compte. Liste FERMÉE : un document ajouté ici doit
#: d'abord être lu, pour la raison dite dans « PORTÉE » ci-dessus.
SOURCES: Tuple[str, ...] = (
    "engine/observation_entities.py",
    "Documentation/Reference/moteur/capacites.md",
    "Documentation/Reference/moteur/tour_de_jeu.md",
    "Documentation/Reference/training/observation_et_actions.md",
    "Documentation/Chantiers/v11/decisions_du_joueur.md",
    "Documentation/Roadmap/moteur.md",
    "Documentation/Roadmap/ROADMAP_INDEX.md",
)

#: « 15e type », « 15e de `AGENT_DECISION_TYPE_IDS` ». Le type concerné se lit sur la MÊME ligne,
#: avant le rang : sans lui, le rang ne veut rien dire et le test le refuse.
ORDINAL_RE = re.compile(r"(\d+)e (?:type|de `AGENT_DECISION_TYPE_IDS`)")
#: « 15 types déclarés », « 15 types actuels ». Exclut « N types pour … » (historique).
DECLARED_RE = re.compile(r"(?<![\d,.])(\d+) types (?:déclarés|actuels)")
#: « 9 réservés ». Exclut « N colonnes réservées » (historique) et la DÉCIMALE d'une mesure : sans
#: la sentinelle de gauche, « 12,11 réservés » (Gio de VRAM, ROADMAP_INDEX.md) se lisait « 11
#: réservés » et rendait ce test rouge à tort — constaté, pas supposé.
RESERVED_RE = re.compile(r"(?<![\d,.])(\d+) réservés")

DECLARED = len(AGENT_DECISION_TYPE_IDS)
RESERVED = AGENT_DECISION_TYPE_SLOTS - DECLARED


def _lines(source: str) -> List[Tuple[int, str]]:
    text = (ROOT / source).read_text(encoding="utf-8")
    return list(enumerate(text.splitlines(), start=1))


def _subject_before(line: str, end: int) -> str | None:
    """Le type nommé le PLUS PRÈS à gauche du rang, sur la même ligne."""
    before = line[:end]
    best: Tuple[int, str] | None = None
    for type_id in AGENT_DECISION_TYPE_IDS:
        pos = before.rfind(type_id)
        if pos != -1 and (best is None or pos > best[0]):
            best = (pos, type_id)
    return None if best is None else best[1]


def test_written_ordinals_match_the_tuple_order():
    """Chaque « Ne type » cite le rang réel du type nommé juste avant lui."""
    checked = []
    for source in SOURCES:
        for number, line in _lines(source):
            for match in ORDINAL_RE.finditer(line):
                written = int(match.group(1))
                subject = _subject_before(line, match.start())
                assert subject is not None, (
                    f"{source}:{number} annonce un « {written}e » sans nommer le type sur la même "
                    "ligne — un rang sans sujet n'est pas vérifiable ; nomme le type."
                )
                expected = AGENT_DECISION_TYPE_IDS.index(subject) + 1
                assert written == expected, (
                    f"{source}:{number} dit que `{subject}` est le {written}e type ; "
                    f"AGENT_DECISION_TYPE_IDS le place en {expected}e position."
                )
                checked.append((source, number, subject))
    assert len(checked) >= 4, (
        f"seulement {len(checked)} rang(s) confronté(s) : le motif ne mord plus rien, "
        "donc ce test est vert à vide. Vérifie ORDINAL_RE et SOURCES."
    )


def test_written_counts_match_the_tuple_and_the_slots():
    """« N types déclarés/actuels » et « N réservés » sont ceux que le code calcule."""
    declared_hits, reserved_hits = [], []
    for source in SOURCES:
        for number, line in _lines(source):
            for match in DECLARED_RE.finditer(line):
                written = int(match.group(1))
                assert written == DECLARED, (
                    f"{source}:{number} annonce {written} types déclarés ; "
                    f"AGENT_DECISION_TYPE_IDS en compte {DECLARED}."
                )
                declared_hits.append((source, number))
            for match in RESERVED_RE.finditer(line):
                written = int(match.group(1))
                assert written == RESERVED, (
                    f"{source}:{number} annonce {written} colonnes réservées ; "
                    f"AGENT_DECISION_TYPE_SLOTS ({AGENT_DECISION_TYPE_SLOTS}) moins les "
                    f"{DECLARED} types déclarés en laisse {RESERVED}."
                )
                reserved_hits.append((source, number))
    assert declared_hits, "aucun « N types déclarés/actuels » trouvé : test vert à vide."
    assert reserved_hits, "aucun « N réservés » trouvé : test vert à vide."


def test_the_slots_still_cover_the_declared_types():
    """Le compte dérivé n'est jamais négatif — sinon les deux tests ci-dessus mentiraient."""
    assert RESERVED >= 0, (
        f"{DECLARED} types déclarés pour {AGENT_DECISION_TYPE_SLOTS} colonnes : "
        "le garde d'engine/observation_entities.py aurait dû lever."
    )
