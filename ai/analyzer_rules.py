"""Couverture des règles — le corpus (`config/rules_corpus.json`) confronté au journal analysé.

CE QUE CE MODULE RÉPOND, et que le rapport ne savait pas dire : pour chaque règle, était-elle
APPLICABLE dans cette partie, a-t-elle été EXERCÉE, combien de fois, et avec combien d'erreurs.

Le manque était structurel. L'analyzer relit ce que le moteur a FAIT : il attrape ce qu'il fait
de trop — un déplacement trop long, un tir hors de portée — et rien de ce qu'il fait de trop peu.
Une règle que le moteur n'applique pas ne produit aucune ligne fautive, donc aucun compteur ne
bouge, donc le rapport affiche un vert franc. Mesuré le 2026-08-10 : « ✅ 1.1 Erreurs en phase de
move : 0 » pendant que le moteur violait 17.01 à chaque déplacement de véhicule non volant.

La réponse n'est pas de deviner ce que le moteur aurait dû faire, mais de DIRE ce qu'on n'a pas
vu et si c'était normal :

- règle **hors roster** — aucune unité jouée ne la porte : elle ne pouvait pas servir, ce n'est
  pas une anomalie et elle ne pèse sur rien ;
- règle **applicable et exercée** — le compte d'occasions jugées et le compte d'erreurs ;
- règle **applicable et JAMAIS exercée** — l'avertissement. C'est le signal du 17.01 : la
  situation s'est présentée des dizaines de fois et le contrôle n'a jamais rien eu à juger ;
- règle **non vérifiable** — le journal ne porte pas de quoi trancher. Elle est DITE, et n'entre
  dans aucun verdict vert.

CE QUI EST COMPTÉ COMME « EXERCÉE » : une OCCASION JUGÉE, pas une occurrence de la règle. Pour
09.05, c'est le nombre de mouvements normaux dont le budget et l'engagement ont réellement été
mesurés — pas le nombre de lignes `MOVED`, qui inclurait celles où la donnée manquait. Un
contrôle qui ne regarde rien affiche donc 0, et c'est exactement le signal recherché.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from shared.data_validation import require_key

_CORPUS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "rules_corpus.json"
)

_corpus_cache: Optional[List[Dict[str, Any]]] = None


def load_rules_corpus() -> List[Dict[str, Any]]:
    """Corpus de règles, lu une fois. Son absence est une rupture de contrat, pas un cas à replier :
    sans lui, le rapport ne peut plus dire ce qu'il ne couvre pas — et c'est précisément ce
    silence-là qu'il est censé faire disparaître."""
    global _corpus_cache
    if _corpus_cache is None:
        with open(_CORPUS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        rules = require_key(payload, "rules")
        seen: Dict[str, int] = {}
        for entry in rules:
            rid = require_key(entry, "id")
            if rid in seen:
                raise ValueError(f"rules_corpus.json : règle {rid!r} déclarée deux fois")
            seen[rid] = 1
        _corpus_cache = rules
    return _corpus_cache


def note_rule_usage(stats: Dict[str, Any], rule_id: str, player: int) -> None:
    """Une OCCASION de vérifier cette règle vient d'être jugée, pour ce joueur.

    À appeler là où le contrôle a réellement regardé — pas à l'entrée du handler. Un appel posé
    trop tôt transformerait « le contrôle n'a rien pu juger » en « la règle a été exercée », ce
    qui rendrait au rapport le silence qu'on essaie de lui retirer.
    """
    usage = require_key(stats, "rule_usage")
    if rule_id not in usage:
        raise KeyError(
            f"note_rule_usage : règle {rule_id!r} absente de config/rules_corpus.json. "
            "Un compteur d'exercice sans entrée de corpus n'est lu par personne."
        )
    usage[rule_id][int(player)] += 1


def new_rule_usage_counters() -> Dict[str, Dict[int, int]]:
    """Structure `rule_usage` DÉCLARÉE d'avance, une entrée par règle du corpus.

    Jamais créée à la volée : une clé de `stats` qui n'existe qu'au premier incrément est le
    défaut V17 (`unit_id_mismatches`), qui faisait lever tout consommateur du `stats` rendu.
    """
    return {require_key(entry, "id"): {1: 0, 2: 0} for entry in load_rules_corpus()}


def _counter_value(stats: Dict[str, Any], path: List[str]) -> int:
    """Somme P1 + P2 d'un compteur désigné par son chemin dans `stats`.

    Deux formes d'imbrication cohabitent dans `stats`, et les confondre lève plutôt que de rendre
    un faux : la forme courante finit sur ``{1: n, 2: n}``, et une poignée de compteurs mettent le
    JOUEUR EN PREMIER (``reactive_move_stats[1]['abnormal']``). Le corpus écrit alors ``"*"`` à la
    place du joueur — le chemin dit sa forme au lieu de la laisser deviner.
    """
    if "*" in path:
        total = 0
        for player in (1, 2):
            node: Any = stats
            for key in path:
                node = require_key(node, player if key == "*" else key)
            total += int(node)
        return total
    node = stats
    for key in path:
        node = require_key(node, key)
    return int(require_key(node, 1)) + int(require_key(node, 2))


def rule_error_count(stats: Dict[str, Any], entry: Dict[str, Any]) -> int:
    """Erreurs attribuées à cette règle. Chaque compteur n'appartient qu'à UNE règle : sans cette
    exclusivité, la somme par règle dépasserait le total de section et le rapport se
    contredirait — le défaut V16, par un autre bout."""
    return sum(_counter_value(stats, path) for path in require_key(entry, "controls"))


def rule_is_applicable(stats: Dict[str, Any], entry: Dict[str, Any]) -> Optional[bool]:
    """La règle POUVAIT-elle servir dans cette partie ? ``None`` = indécidable depuis le journal.

    Aucun prédicat n'est écrit à la main : chacun se dérive d'une grandeur que le journal porte
    déjà. C'est la condition pour que ce fichier ne pourrisse pas comme la matrice Markdown qu'il
    remplace — un prédicat inventé est une affirmation de plus à re-vérifier.
    """
    applicability = require_key(entry, "applicability")
    kind = require_key(applicability, "kind")
    if kind == "always":
        return True
    if kind == "action_seen":
        action = require_key(applicability, "action")
        return int(require_key(stats, "actions_by_type").get(action, 0)) > 0  # get allowed : type absent = jamais joué
    if kind == "unit_rule_in_roster":
        rule_id = require_key(applicability, "rule_id")
        carriers = require_key(stats, "rule_to_units").get(rule_id, set())  # get allowed : règle inconnue du registre
        return bool(set(require_key(stats, "unit_types_seen")) & set(carriers))
    raise ValueError(
        f"rules_corpus.json : applicabilité de type {kind!r} inconnue pour la règle "
        f"{entry.get('id')!r}"  # get allowed : message d'erreur
    )


#: Verdicts, du plus muet au plus parlant. L'ordre est celui du tri d'affichage : ce qui demande
#: une action vient en premier.
VERDICT_NEVER_EXERCISED = "JAMAIS EXERCÉE"
VERDICT_ERRORS = "ERREURS"
VERDICT_OK = "OK"
VERDICT_OUT_OF_ROSTER = "HORS ROSTER"
VERDICT_UNDECIDABLE = "INDÉCIDABLE"

_VERDICT_ORDER = {
    VERDICT_ERRORS: 0,
    VERDICT_NEVER_EXERCISED: 1,
    VERDICT_UNDECIDABLE: 2,
    VERDICT_OK: 3,
    VERDICT_OUT_OF_ROSTER: 4,
}


def coverage_rows(stats: Dict[str, Any], section: Optional[str] = None) -> List[Dict[str, Any]]:
    """Une ligne par règle du corpus : applicabilité, exercices, erreurs, verdict."""
    rows: List[Dict[str, Any]] = []
    usage = require_key(stats, "rule_usage")
    for entry in load_rules_corpus():
        if section is not None and require_key(entry, "section") != section:
            continue
        rule_id = require_key(entry, "id")
        applicable = rule_is_applicable(stats, entry)
        exercised = int(require_key(usage, rule_id)[1]) + int(require_key(usage, rule_id)[2])
        errors = rule_error_count(stats, entry)
        if applicable is None:
            verdict = VERDICT_UNDECIDABLE
        elif not applicable:
            verdict = VERDICT_OUT_OF_ROSTER
        elif errors > 0:
            verdict = VERDICT_ERRORS
        elif exercised == 0:
            # LE signal du chantier : la situation s'est présentée, le contrôle n'a rien jugé.
            verdict = VERDICT_NEVER_EXERCISED
        else:
            verdict = VERDICT_OK
        rows.append({
            "id": rule_id,
            "label": require_key(entry, "label"),
            "source": require_key(entry, "source"),
            "status": require_key(entry, "status"),
            "applicable": applicable,
            "exercised": exercised,
            "errors": errors,
            "verdict": verdict,
        })
    rows.sort(key=lambda r: (_VERDICT_ORDER[r["verdict"]], r["id"]))
    return rows


def section_error_sum(stats: Dict[str, Any], section: str) -> int:
    """Somme des erreurs de toutes les règles d'une section.

    Elle DOIT égaler le bucket correspondant d'`error_totals`. Ce n'est pas une vérification de
    confort : deux sommes d'erreurs ont déjà divergé en silence dans ce dépôt (V16), et une
    couverture par règle qui ne retombe pas sur le total de section est soit incomplète — un
    compteur n'appartient à aucune règle — soit doublée.
    """
    return sum(
        rule_error_count(stats, entry)
        for entry in load_rules_corpus()
        if require_key(entry, "section") == section
    )


#: Sections du rapport → bucket d'`error_totals` qui doit égaler leur somme par règle.
SECTION_TO_BUCKET = {"1.1": "move"}


def coverage_gaps(stats: Dict[str, Any]) -> List[Tuple[str, int, int]]:
    """Sections dont la somme par règle ne retombe PAS sur le bucket de la section.

    Rend ``(section, somme_par_règle, bucket)``. Une section absente de ce résultat est une
    section dont chaque erreur est attribuée à exactement une règle.
    """
    from ai.analyzer import error_totals

    totals = error_totals(stats)
    gaps: List[Tuple[str, int, int]] = []
    for section, bucket in SECTION_TO_BUCKET.items():
        by_rule = section_error_sum(stats, section)
        in_bucket = int(require_key(totals, bucket))
        if by_rule != in_bucket:
            gaps.append((section, by_rule, in_bucket))
    return gaps
