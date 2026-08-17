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

import functools
from typing import Any, Dict, List, Optional, Set, Tuple

from shared.data_validation import require_key

@functools.lru_cache(maxsize=None)
def load_rules_corpus() -> List[Dict[str, Any]]:
    """Corpus de règles. Son absence est une rupture de contrat, pas un cas à replier : sans lui,
    le rapport ne peut plus dire ce qu'il ne couvre pas — et c'est précisément ce silence-là qu'il
    est censé faire disparaître.

    Lu par le `ConfigLoader` du dépôt, comme `weapon_rules.json` et `unit_rules.json`, et pas par
    un `open()` local : celui-ci ouvrait en `utf-8` là où tout `config/` est lu en `utf-8-sig`
    (un BOM aurait fait lever le seul fichier du répertoire à ne pas le tolérer), tenait un second
    cache invisible du rechargement à chaud, et recalculait la racine du projet depuis `__file__`.
    """
    from config_loader import get_config_loader

    payload = get_config_loader().load_config("rules_corpus", force_reload=False)
    rules = require_key(payload, "rules")
    seen: Set[str] = set()
    for entry in rules:
        rid = require_key(entry, "id")
        if rid in seen:
            raise ValueError(f"rules_corpus.json : règle {rid!r} déclarée deux fois")
        seen.add(rid)
    return rules


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

    Trois formes d'imbrication cohabitent dans `stats` :
    - forme courante ``{1: n, 2: n}`` en fin de chemin : le ``"*"`` est ajouté implicitement ;
    - joueur EN PREMIER (``reactive_move_stats[1]['abnormal']``) : écrire ``"*"`` à la position
      du joueur — même notion, même traversée ;
    - scalaire sans split joueur (``state_resync['dead_missed']``) : écrire ``"#"`` en fin de
      chemin. La valeur est traversée sans boucle joueur et rendue telle quelle.
    """
    if "#" in path:
        if path[-1] != "#":
            raise ValueError(f"'#' doit être en position terminale du chemin, reçu : {path}")
        if len(path) < 2:
            raise ValueError(f"chemin '#' sans clé avant le marqueur : {path}")
        node: Any = stats
        for key in path[:-1]:
            node = require_key(node, key)
        return int(node)
    slots = path if "*" in path else [*path, "*"]
    total = 0
    for player in (1, 2):
        node = stats
        for key in slots:
            node = require_key(node, player if key == "*" else key)
        total += int(node)
    return total


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


#: Verdicts DANS L'ORDRE D'AFFICHAGE : ce qui demande une action vient en premier, ce qui ne
#: demande rien en dernier. L'ordre EST la liste — une seconde table de rangs se re-numéroterait
#: à chaque insertion, et un verdict ajouté d'un seul côté sortirait en KeyError au tri.
VERDICTS = ("ERREURS", "JAMAIS EXERCÉE", "INDÉCIDABLE", "OK", "HORS ROSTER")
VERDICT_ERRORS, VERDICT_NEVER_EXERCISED, VERDICT_UNDECIDABLE, VERDICT_OK, VERDICT_OUT_OF_ROSTER = VERDICTS


def coverage_rows(stats: Dict[str, Any], section: Optional[str] = None) -> List[Dict[str, Any]]:
    """Une ligne par règle du corpus : applicabilité, exercices, erreurs, verdict."""
    rows: List[Dict[str, Any]] = []
    for entry in load_rules_corpus():
        if section is not None and require_key(entry, "section") != section:
            continue
        rule_id = require_key(entry, "id")
        exercised = _counter_value(stats, ["rule_usage", rule_id])
        errors = rule_error_count(stats, entry)
        # L'OBSERVATION PRIME SUR LA PRÉDICTION. Le prédicat d'applicabilité est une déduction ;
        # un exercice ou une faute sont des FAITS. Une règle qu'on a jugée, ou qui a produit une
        # erreur, était applicable — le prédicat ne tranche donc que les cas où l'on n'a rien
        # observé. Sans cette priorité, le rapport pouvait affirmer le contraire de ce qu'il
        # venait de mesurer : « HORS ROSTER » au-dessus d'un compteur d'erreur non nul, ou des
        # exercices > 0 rendus avec un tiret. Les deux ont été mesurés en revue le 2026-08-10, et
        # ils venaient tous deux de prédicats qui ne découpent pas comme les sites de mesure.
        applicable = True if (exercised > 0 or errors > 0) else rule_is_applicable(stats, entry)
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
            "status": require_key(entry, "status"),
            "applicable": applicable,
            "exercised": exercised,
            "errors": errors,
            "verdict": verdict,
        })
    rows.sort(key=lambda r: (VERDICTS.index(r["verdict"]), r["id"]))
    return rows


def _section_error_sum(stats: Dict[str, Any], section: str) -> int:
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
SECTION_TO_BUCKET = {
    "1.1": "move",
    "1.2": "shooting",
    "1.3": "charge",
    "1.4": "fight",
    "2.1": "dead_units",
    "2.3": "damage",
    "2.8": "state_resync",
}


def coverage_gaps(
    stats: Dict[str, Any], section: Optional[str] = None
) -> List[Tuple[str, int, int]]:
    """Sections dont la somme par règle ne retombe PAS sur le bucket de la section.

    Rend ``(section, somme_par_règle, bucket)``. Une section absente de ce résultat est une
    section dont chaque erreur est attribuée à exactement une règle.

    ``section`` borne le calcul à celle qu'on rend. Sans ce paramètre, l'appelant recevait toutes
    les sections puis jetait les autres : le rendu de chacune resommait alors le corpus entier, et
    « quelle section m'intéresse » vivait dans deux fichiers.
    """
    from ai.analyzer import error_totals

    totals = error_totals(stats)
    gaps: List[Tuple[str, int, int]] = []
    for _section, bucket in SECTION_TO_BUCKET.items():
        if section is not None and _section != section:
            continue
        by_rule = _section_error_sum(stats, _section)
        in_bucket = int(require_key(totals, bucket))
        if by_rule != in_bucket:
            gaps.append((_section, by_rule, in_bucket))
    return gaps
