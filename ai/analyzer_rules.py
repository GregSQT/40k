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

import re

import functools
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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


def special_rule_usage_is_valid(
    rule_id: str,
    unit_type: str,
    datasheets_present: Set[str],
    rule_to_units: Dict[str, Set[str]],
) -> bool:
    """L'usage relevé est-il porté par une figurine VIVANTE de l'escouade ? (19.04)

    `rule_to_units` est bâti sur les datasheets : il répond pour une escouade HOMOGÈNE. Il ne
    répond pas pour une escouade ATTACHÉE, et c'est le cas courant de ce roster — le journal
    nomme l'escouade de bloc (`VanguardVeteranSquadJumpPack`, `Boyz`) là où la capacité est
    déclarée par le character replié dedans (`ChaplainJumpPack`, `PainBoy`).

    Documentation/40k_rules/19 Attached units.pdf §19.04 : « abilities/rules that affect a unit
    (or models in it) apply to every model in an attached unit, UNTIL THE SOURCE of that
    ability/rule is destroyed » — le tableau du PDF donne les trois sources (leader/support,
    bodyguard, figurine précise) et la même échéance pour toutes : la mort du dernier socle.
    Le moteur l'applique par `compute_unit_rules_in_effect`
    (engine/phase_handlers/shared_utils.py), qui prend `native_alive` et
    `alive_attached_sources` : la propagation y est une fonction du VIVANT, pas de la liste de
    déploiement. `datasheets_present` est le pendant de ces deux paramètres côté analyzer.

    `datasheets_present` = datasheets des socles VIVANTS de CETTE escouade à l'instant du
    relevé, ou `{unit_type}` quand le journal ne déclare aucune composition (grammaire
    antérieure à `[MODEL_TYPES:]`) : le verdict retombe alors sur la seule datasheet
    d'escouade, comme avant l'existence de ce prédicat. Aucun contrôle relâché : une règle que
    ne porte AUCUNE datasheet vivante de l'escouade reste INVALID.

    La composition vient du JOURNAL (`[MODEL_TYPES:]`), pas de `CAN_LEAD` : ce dernier décrit
    les attachements LÉGAUX, donc un sur-ensemble qui blanchirait un usage réellement invalide.

    CE QUI N'EST PAS JUGÉ, et pourquoi : la règle déclarée par la datasheet de l'escouade
    elle-même reste toujours valide. Son échéance 19.04 est la mort du dernier socle du BLOC
    bodyguard, et le journal ne dit pas quel socle est natif — le moteur, lui, le sait
    (`native_alive`, engine/phase_handlers/shared_utils.py). Exiger `unit_type` parmi les
    datasheets vivantes serait PLUS STRICT que la règle : une escouade réduite à son sergent ou
    à sa variante d'arme spéciale (datasheets distinctes du type d'escouade, natives malgré
    tout) verrait ses propres capacités comptées INVALID. Ce prédicat ne tranche donc que la
    source ATTACHÉE, la seule que le journal permette de suivre.

    Marqueurs de RÔLE exclus de la propagation, exactement comme `strip_role_rules` les retire
    des règles de figurine avant l'union du moteur : ils qualifient la figurine (ordre
    d'allocation 05.04, T bodyguard 19.02), jamais l'escouade. La table lue est celle du
    moteur — un rôle ajouté là-bas ne peut pas diverger ici.
    """
    from engine.phase_handlers.shared_utils import ROLE_TIER

    carriers = rule_to_units.get(rule_id, set())  # get allowed : règle absente du registre
    if rule_id in ROLE_TIER:
        # Un rôle ne se propage à personne : seule la datasheet de l'escouade elle-même compte.
        return unit_type in carriers
    if unit_type in carriers:
        return True  # cf. « CE QUI N'EST PAS JUGÉ » ci-dessus
    return bool(carriers & datasheets_present)


def living_datasheets(
    state: Any, stats: Dict[str, Any], unit_id: str, unit_type: str,
    *, exclude_mids: "frozenset[str] | Set[str]" = frozenset(),
) -> Optional[Set[str]]:
    """Datasheets des socles VIVANTS de `unit_id`, ou `None` si la composition ne tranche pas.

    `exclude_mids` : socles à IGNORER bien que vivants. Sert au relevé de la ligne `RETURNED`
    elle-même : les socles qu'elle rend sont déjà recalés comme vivants quand l'usage est jugé,
    alors que la capacité s'est exercée sur la composition d'AVANT — un PainBoy mort qui se
    rendrait lui-même ressortirait VALIDE, c'est-à-dire que le seul cas illégal que la ligne
    doit rendre jugeable serait celui qu'elle ne signale jamais.

    `unit_model_hp[unit_id]` est l'effectif par socle tenu par `_resync_living_models` : un socle
    mort en sort, donc la datasheet qu'il portait disparaît d'ici avec lui — c'est l'échéance
    exacte de 19.04. `model_types` donne la datasheet de chaque socle, écrite une fois à l'entête.

    `None` = ABSTENTION, jamais une faute inventée. Deux cas :
      - un socle VIVANT dont la datasheet n'est pas déclarée. Depuis la grammaire 10, une
        figurine RENDUE (`apply_returned_models_placement`, id neuf `<escouade>#r<n>`) est
        déclarée par sa ligne `RETURNED` — 19.04 la réhabilite explicitement (« Should those
        models later be revived, those abilities will once more apply ») et le verdict se rend.
        Sur un journal antérieur (mesuré le 2026-09-11 : 6 ids `#r`, 0 déclaré) l'abstention
        demeure : les écarter aurait compté INVALID un usage parfaitement légal ;
      - aucun socle vivant connu alors que l'entête a déclaré une composition.

    `{unit_type}` quand l'entête ne déclare AUCUNE composition (grammaire antérieure à
    `[MODEL_TYPES:]`) : le verdict retombe sur la seule datasheet d'escouade, comme avant ce
    prédicat — le journal ne connaît alors aucun attachement.

    LIMITE CONNUE, qui ne peut que SOUS-compter les fautes : une ligne `DEAD model=` sans
    segment `[MODELS:]` ne fait pas sortir le socle avant la prochaine ligne qui en porte un.
    """
    return declared_datasheets(
        state, stats, unit_id, unit_type,
        (mid for mid in state.unit_model_hp.get(unit_id, {}) if mid not in exclude_mids),  # get allowed : unité jamais vue
    )


def declared_datasheets(
    state: Any, stats: Dict[str, Any], unit_id: str, unit_type: str, mids: Iterable[str],
) -> Optional[Set[str]]:
    """Datasheets des socles `mids` de `unit_id`, ou `None` si la composition ne tranche pas.

    Noyau de `living_datasheets`, qui lui passe les socles VIVANTS. Un relevé qui se juge sur
    d'autres socles (24.08 : la figurine qui vient d'être DÉTRUITE) passe les siens. Mêmes
    règles d'abstention et de repli sur `{unit_type}` — voir `living_datasheets`.
    """
    declared = require_key(stats, 'model_types_by_unit_id').get(unit_id)  # get allowed : entête sans [MODEL_TYPES:]
    if not declared:
        return {unit_type}
    model_types = state.model_types
    present: Set[str] = set()
    for mid in mids:
        mtype = model_types.get(mid)  # get allowed : socle sans datasheet = abstention
        if mtype is None:
            return None
        present.add(mtype)
    return present or None


def note_special_rule_usage(
    stats: Dict[str, Any],
    state: Any,
    config: Any,
    rule_id: str,
    unit_id: str,
    unit_type: str,
    player: int,
    *,
    exclude_mids: "frozenset[str] | Set[str]" = frozenset(),
    judged_mids: Optional[Iterable[str]] = None,
) -> None:
    """Relève un usage de règle §1.7 ET tranche sa validité 19.04 À CET INSTANT.

    `exclude_mids` : cf. `living_datasheets` — les socles rendus par la ligne `RETURNED` dont
    l'usage est relevé, pour juger la restitution sur la composition d'AVANT.

    `judged_mids` : socles sur lesquels le verdict se rend À LA PLACE des socles vivants. Sert à
    24.08 Deadly Demise, exercée par une figurine qui vient d'être DÉTRUITE : la composition
    vivante ne peut ni la voir (si c'était le dernier socle) ni l'isoler (un WeirdBoy encore vivant
    blanchirait l'explosion d'un Boy de son escouade). La validité est alors « le socle détruit
    portait la règle ». Vide = abstention (journal sans DEAD préalable), jamais une faute inventée.

    SITE UNIQUE d'écriture de `special_rule_usage`. Le verdict ne peut pas se rendre a
    posteriori sur la clé `(règle, type d'escouade)` : cette clé ignore QUELLE escouade a
    utilisé la règle et QUAND. Deux escouades du même type n'ont pas la même composition
    (mesuré sur le run du 2026-09-11 : `Unit 4 (Intercessor)` porte un `Librarian`, `Unit 5
    (Intercessor)` un `CaptainRelicShield` et un `Ancient`), et une escouade n'a pas la même
    composition au tour 5 qu'au déploiement — 19.04 s'arrête à la mort de la source.

    LIMITE CONNUE : la dernière clause de 19.04 (« if that last model was destroyed as the
    result of an attack, the ability applies until the attacking unit has resolved all of its
    attacks ») n'est pas modélisée ici — l'analyzer ne suit pas les allocations d'attaque en
    cours. Un usage relevé dans cette fenêtre de sursis serait compté INVALID à tort. Mesuré
    sur le run du 2026-09-11 : 0 relevé sur 94 tombe après la mort de son porteur.
    """
    require_key(stats, 'special_rule_usage')[(rule_id, unit_type)][int(player)] += 1
    present = (
        living_datasheets(state, stats, unit_id, unit_type, exclude_mids=exclude_mids)
        if judged_mids is None
        else declared_datasheets(state, stats, unit_id, unit_type, judged_mids)
    )
    if present is None:
        return  # composition non concluante : on s'abstient plutôt que d'inventer une faute
    if not special_rule_usage_is_valid(rule_id, unit_type, present, config.rule_to_units):
        require_key(stats, 'special_rule_usage_invalid')[(rule_id, unit_type)][int(player)] += 1


def new_rule_usage_counters() -> Dict[str, Dict[int, int]]:
    """Structure `rule_usage` DÉCLARÉE d'avance, une entrée par règle du corpus.

    Jamais créée à la volée : une clé de `stats` qui n'existe qu'au premier incrément est le
    défaut V17 (`unit_id_mismatches`), qui faisait lever tout consommateur du `stats` rendu.
    """
    return {require_key(entry, "id"): {1: 0, 2: 0} for entry in load_rules_corpus()}


_MW_DICE_RE = re.compile(r'\bMW:([0-9,]+)')
_MW_TRIGGER_RE = re.compile(r'\bTrigger:(\d+)')


def _mw_dice_error_sum_of_d6(brut: int, dice: Optional[List[int]], trigger: Optional[int]) -> Optional[str]:
    """Hold Still and Say Aargh (`mortal_wounds_on_critical_wound`) : « inflicts D6 mortal
    wounds » par blessure critique — `MW:` porte un D6 par critique, et N est leur somme."""
    if dice is None:
        return "segment MW: absent (un D6 par blessure critique attendu)"
    if any(d < 1 or d > 6 for d in dice):
        return f"MW:{dice} hors 1-6"
    if sum(dice) != brut:
        return f"compte {brut} ≠ somme des dés MW:{dice} = {sum(dice)}"
    return None


def _mw_dice_error_threshold_d3(brut: int, dice: Optional[List[int]], trigger: Optional[int]) -> Optional[str]:
    """Exhortation of Rage (`mortal_wounds_on_fight_activation`) : « roll one D6 … 4-5: D3
    mortal wounds. 6: 3 mortal wounds » — `Trigger:` porte le D6 ; sur 1-3 le compte est 0 et
    `MW:` absent, sur 4-5 `MW:` porte le D3 dont N est la valeur, sur 6 N vaut 3 sans dé."""
    if trigger is None:
        return "segment Trigger: absent (D6 de déclenchement attendu)"
    if trigger < 1 or trigger > 6:
        return f"Trigger:{trigger} hors 1-6"
    if trigger <= 3:
        if brut != 0 or dice is not None:
            return f"Trigger:{trigger} (1-3) mais compte {brut} / MW:{dice} — aucune blessure attendue"
        return None
    if trigger == 6:
        if brut != 3 or dice is not None:
            return f"Trigger:6 mais compte {brut} / MW:{dice} — 3 blessures sans dé attendues"
        return None
    if dice is None or len(dice) != 1 or dice[0] < 1 or dice[0] > 3:
        return f"Trigger:{trigger} (4-5) mais MW:{dice} — un seul D3 attendu"
    if brut != dice[0]:
        return f"Trigger:{trigger} (4-5) : compte {brut} ≠ D3 MW:{dice[0]}"
    return None


#: Contrôle des dés PAR capacité 06.02 (`rule_id` de datasheet → prédicat de cohérence). C'est
#: l'INVENTAIRE des capacités dont l'analyzer sait lire les dés ; `analyzer_core` le confronte à
#: l'import à sa propre table tag → `rule_id` (`_MW_ABILITY_RULE_IDS`), si bien qu'une capacité
#: ajoutée d'un côté sans l'autre lève au chargement du module, pas à la première ligne lue.
MW_ABILITY_DICE_CHECKS: Dict[str, Any] = {
    "mortal_wounds_on_critical_wound": _mw_dice_error_sum_of_d6,
    "mortal_wounds_on_fight_activation": _mw_dice_error_threshold_d3,
}


def mw_ability_dice_error(rule_id: str, brut: int, action_desc: str) -> Optional[str]:
    """Le compte BRUT d'une ligne `SUFFERS N Mortal Wounds` de capacité suit-il ses dés ?

    Grammaire 9 : la ligne porte les dés qui ont produit son compte, et c'est ce qui rend le
    compte CONTRÔLABLE au lieu d'être cru. Une forme par capacité — cf. `MW_ABILITY_DICE_CHECKS`
    (dés qui se SOMMENT, ou D6 de déclenchement à seuil puis D3).

    Rend le libellé de la faute, ou ``None`` si la ligne est cohérente. Le compte comparé est
    le BRUT du journal (avant `[FNP:n]`) : les dés disent ce qui a été infligé, le FNP ce qui a
    été sauvé ensuite.
    """
    check = MW_ABILITY_DICE_CHECKS.get(rule_id)  # get allowed : absence = erreur explicite ci-dessous
    if check is None:
        raise KeyError(f"mw_ability_dice_error: capacité 06.02 inconnue {rule_id!r}")
    dice_match = _MW_DICE_RE.search(action_desc)
    dice = [int(d) for d in dice_match.group(1).split(',') if d] if dice_match else None
    trigger_match = _MW_TRIGGER_RE.search(action_desc)
    trigger = int(trigger_match.group(1)) if trigger_match else None
    return check(brut, dice, trigger)


def check_anti_x_threshold(
    rules_list: List[Any],
    anti_kw: str,
    anti_tok_thresh: int,
    anti_rule_name: str,
    stats: Dict[str, Any],
    state: Any,
    turn: Any,
    phase: Any,
    line_str: str,
    weapon_key: str,
    suffix: str = "",
) -> None:
    """Valide que le seuil [ANTI-X:N+] du token correspond au seuil déclaré dans l'armurerie.

    Factorisé depuis shoot_handler / fight_handler pour éviter la divergence tir/mêlée.
    `suffix` vaut "" (tir) ou " (mêlée)".
    """
    _anti_decl_thresh: Optional[int] = None
    for _r in rules_list:
        _rn, _, _rp = str(_r).partition(":")
        if _rn.strip().upper() == anti_rule_name and _rp:
            try:
                _anti_decl_thresh = int(_rp.strip())
            except (TypeError, ValueError):
                pass
            break
    if _anti_decl_thresh is not None and anti_tok_thresh != _anti_decl_thresh:
        stats["parse_errors"].append({
            "episode": state.current_episode_num,
            "turn": turn,
            "phase": phase,
            "line": line_str,
            "error": (
                f"[ANTI-{anti_kw}:{anti_tok_thresh}+]{suffix} : seuil log "
                f"≠ seuil armurerie ({_anti_decl_thresh}+)"
            ),
        })


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
    return sum(_counter_value(stats, path) for path in (entry.get("controls") or []))


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
    if kind == "weapon_rule_in_roster":
        # JUMEAU du précédent, côté ARMES, et dérivé de la même façon : aucun prédicat écrit à la
        # main, juste le croisement de l'armurerie avec les types réellement vus dans le journal.
        # Le `profile` est OBLIGATOIRE parce qu'un token ne vaut pas des deux côtés : mesuré le
        # 2026-09-07, HAZARDOUS est porté par 21 armes de tir et zéro arme de mêlée, LETHAL_HITS
        # par 3 de tir et 1 de mêlée. Sans lui, `PROJ.1.4.hazardous` (mêlée) serait déclarée
        # applicable au motif qu'un pistolet plasma porte le token — un avertissement faux, celui
        # que ce prédicat existe pour retirer.
        rule_id = require_key(applicability, "rule_id")
        profile = require_key(applicability, "profile")
        if profile not in ("ranged", "melee"):
            raise ValueError(
                f"rules_corpus.json : profil d'arme {profile!r} inconnu pour la règle "
                f"{entry.get('id')!r} — attendu 'ranged' ou 'melee'"  # get allowed : message d'erreur
            )
        by_profile = require_key(stats, "weapon_rule_to_units").get(rule_id, {})  # get allowed : token porté par aucune arme
        carriers = by_profile.get(profile, set())  # get allowed : token absent de ce profil
        return bool(set(require_key(stats, "unit_types_seen")) & set(carriers))
    if kind == "indecidable":
        # Règle non vérifiable depuis le journal : ni NON applicable, ni applicable sans preuve.
        # Verdict → INDÉCIDABLE (ni vert vacant ni hors roster). Utilisé pour les règles des
        # matrices PDF/armes/unités dont le journal ne porte pas les données nécessaires.
        return None
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
            # `exercised == 0 and errors > 0` n'est PAS impossible, contrairement à ce que cette
            # note affirmait : il suffit qu'un site d'erreur soit atteignable là où le site
            # d'exercice ne l'est pas. Trois chemins l'ont produit et sont fermés le 2026-09-07 —
            # un garde de phase sur le seul exercice (`PROJ.1.2.advance_post_tir`), un garde
            # `unit_player is not None` sur les seuls exercices §2.8, et les règles PDF de
            # double-activation (10.02 / 12.07) qui n'avaient aucun site d'exercice.
            # L'état reste DÉLIBÉRÉMENT rendu en « ERREURS » plutôt que sous un verdict
            # d'instrumentation : ce serait masquer une faute réelle derrière un défaut d'outil,
            # à rebours du principe posé juste au-dessus (une erreur est un FAIT, elle prime).
            # Le défaut d'instrumentation se voit ailleurs, et plus tôt :
            # `test_toute_regle_applicable_a_controles_est_instrumentee` refuse en CI toute règle
            # « always » à contrôles sans site d'exercice, et
            # `test_aucun_site_note_rule_usage_n_a_d_identifiant_indechiffrable` refuse un site
            # dont l'identifiant échappe à la lecture statique.
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
