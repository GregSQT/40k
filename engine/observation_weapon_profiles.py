"""Encodage des PROFILS D'ARMES pour l'observation squad (V11 §9.2.5 / audit obs §10 B3 & D).

Le vecteur squad (199-d avant cette tranche) ne contenait **aucun** profil d'arme ni bit de
règle : l'agent subissait [DEVASTATING WOUNDS], [MELTA], [RAPID FIRE]… sans en percevoir un
seul. Ce module est la source UNIQUE qui décrit une escouade offensivement, et il est consommé
à l'identique par le bloc « mon escouade » et par les slots ennemis (même layout, seul le
nombre de slots K diffère) — un encodeur par camp aurait dérivé.

Principes (décidés dans `V11_audit_observation.md` §9.3/§9.4/§11, appliqués ici) :

- **Granularité escouade, pas figurine.** Une escouade se résume à quelques profils DISTINCTS
  (mesuré sur les rosters d'entraînement réels : au plus 6 profils de tir et 5 de mêlée, persos
  attachés compris). Chaque profil porte son **nombre de porteurs VIVANTS** : sans ce compteur
  l'agent ne peut pas distinguer « 1 rokkit » de « 9 shootas » — le volume de feu est
  `porteurs × NB`.
- **Données BRUTES.** On expose les caractéristiques telles quelles (NB, ATK, STR, AP, DMG,
  portée) et les règles telles qu'elles sont déclarées. Aucune agrégation « puissance de feu »,
  aucune espérance de dégâts contre une cible fictive : ce sont exactement les features
  calculées que §9.1 a supprimées.
- **Seules les règles à EFFET RÉEL sont exposées.** La liste ci-dessous suit les règles résolues
  dans le chemin vif (`attack_sequence.py`, `shared_utils._manual_roll_intent`, `fight_handlers`,
  `shooting_handlers`). [INDIRECT FIRE] 24.19 en est ABSENTE **délibérément** : elle n'est pas
  implémentée (V11 §9.2.1), un bit pour elle serait du bruit pur.
  ✅ **Réserve LEVÉE le 2026-07-26 (tranche T-B).** Elle notait que [ASSAULT] 24.04 et
  [CLOSE_QUARTERS] 24.27 étaient exposées alors que le gate de tir squad/gym fermait le tir dès
  `has_advanced` ou `in_er` : leurs types de tir (10.05 / 10.06) n'existaient pas pour l'agent.
  `resolve_squad_shooting_type` les a ouverts — les deux bits décrivent désormais une capacité
  réellement exerçable. Voir `V11_entity_encoder_pointer.md` §1.2 et son journal.
- **Règles paramétrées = la valeur, pas un bit** (§9 « Décisions tranchées ») : [RAPID FIRE X],
  [SUSTAINED HITS X], [MELTA X], [CLEAVE X], [BLAST X] et le Y+ de [ANTI-X Y+] passent en
  continu. Le **keyword ciblé** par [ANTI-X] est exposé en one-hot : sans lui le seuil Y+ est
  ininterprétable, l'effet dépendant des keywords de la CIBLE (24.03, union 19.03).
- **Aucune troncature silencieuse.** Si une escouade porte plus de profils que de slots, le
  dépassement est LOGUÉ (`add_debug_file_log`), jamais absorbé.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from shared.data_validation import require_key
from engine.combat_utils import expected_dice_value
from engine.phase_handlers.attack_sequence import (
    ANTI_RULE_IDS,
    ANTI_RULE_PREFIX,
    anti_threshold_of,
)
from engine.utils.weapon_helpers import weapon_has_rule, weapon_rule_parameter


# Règles PARAMÉTRÉES résolues dans le vif → une dimension CONTINUE portant la valeur du
# paramètre. [BLAST] sous sa forme nue vaut 1 dé par tranche de 5 (24.05, cf.
# `_blast_extra_dice_per_five`) : c'est la valeur par défaut de la RÈGLE, pas un repli d'erreur.
WEAPON_RULE_PARAMS: Tuple[Tuple[str, int], ...] = (
    ("RAPID_FIRE", 0),
    ("SUSTAINED_HITS", 0),
    ("MELTA", 0),
    ("CLEAVE", 0),
    ("BLAST", 1),
)

# Règles BOOLÉENNES résolues dans le vif. Ce ne sont plus des DRAPEAUX POSITIONNELS mais un
# ENSEMBLE d'`obs_id` (cf. `WEAPON_RULE_ID_SLOTS` ci-dessous, qui porte le pourquoi). Ce tuple
# reste la liste du VOCABULAIRE observé — il dit quelles règles ont un id,
# `config/weapon_rules.json` dit lequel.
WEAPON_RULE_BITS: Tuple[str, ...] = (
    "DEVASTATING_WOUNDS",
    "LETHAL_HITS",
    "TORRENT",
    "TWIN_LINKED",
    "EXTRA_ATTACKS",
    "PRECISION",
    "PSYCHIC",
    "HAZARDOUS",
    "HEAVY",
    "IGNORES_COVER",
    "CLOSE_QUARTERS",
    "ASSAULT",
)

# Vocabulaire OBSERVÉ sous forme d'ids : les règles booléennes, plus l'IDENTITÉ de la règle
# [ANTI-X] portée (son seuil Y+ reste continu — c'est une valeur, pas une catégorie). Les règles
# PARAMÉTRÉES n'y sont pas : leur présence se lit sur leur dimension continue, un id ferait
# doublon.
WEAPON_RULE_OBS_VOCABULARY: Tuple[str, ...] = WEAPON_RULE_BITS + ANTI_RULE_IDS

# Slots d'ids par profil d'arme — LE point de bascule du chantier (V11 §0.48, arbitrage 2).
# POURQUOI des ids et plus des bits : un drapeau de règle coûtait 560 scalaires d'observation
# (28 entités × 20 profils), et il en coûtait 560 de plus à CHAQUE règle rendue vivante — la
# conformité aux règles et l'objectif « un seul retrain » se contredisaient directement. Un id
# ne coûte rien de plus qu'un slot déjà réservé, et le vocabulaire (`OBS_ID_VOCAB_SIZE`) est
# pré-dimensionné : rendre [INDIRECT FIRE] vivante ne touchera ni `obs_size` ni les poids.
#
# MESURÉ sur les 4 armureries (161 datasheets, 231 armes) : au
# plus 4 règles déclarées par arme, paramétrées comprises — donc au plus 4 ids. 6 laisse la même
# marge que les 8 slots de capacités d'unité face à leur maximum mesuré.
# ⚠️ Débordement = ERREUR (`observation_builder._fill_id_slots`), jamais troncature : une règle
# tronquée serait une règle que l'agent subit sans la percevoir.
WEAPON_RULE_ID_SLOTS = 6

# Layout d'UN profil (l'ordre ci-dessous EST l'ordre d'émission).
#   cont     : NB, ATK, STR, AP, DMG, portée, porteurs vivants, puis les paramètres de règles,
#              puis le seuil Y+ de [ANTI-X] (0 = aucune règle ANTI).
#   bin      : le mask du slot, et lui seul.
#   rule_ids : l'ensemble des `obs_id` de règles du profil, trié et paddé à 0.
PROFILE_STAT_CONT = 7
PROFILE_CONT_SIZE = PROFILE_STAT_CONT + len(WEAPON_RULE_PARAMS) + 1
PROFILE_BIN_SIZE = 1

# Clés d'accès aux listes d'armes, par registre.
RANGED_KEY = "RNG_WEAPONS"
MELEE_KEY = "CC_WEAPONS"


def _rule_entries(weapon: Dict[str, Any]) -> Tuple[Tuple[str, Optional[int]], ...]:
    """Règles déclarées par l'arme, sous forme canonique ((NOM, paramètre|None), …), triée.

    Gère les deux formes de `WEAPON_RULES` (chaîne nue, chaîne `NOM:param`) — même contrat que
    `weapon_has_rule`, dont c'est le pendant « liste ».

    2026-07-29 — la branche objet `ParsedWeaponRule` a été SUPPRIMÉE ici en même temps que dans
    `weapon_has_rule`, dont ce docstring revendique le contrat : la laisser aurait rendu cette
    revendication fausse. Le type n'est plus constructible hors du parseur d'armurerie, qui jette
    son résultat. Toute entrée non-chaîne tombe dans le `raise TypeError` ci-dessous.
    """
    rules = require_key(weapon, "WEAPON_RULES")
    if not isinstance(rules, list):
        raise TypeError(
            f"WEAPON_RULES must be a list, got {type(rules).__name__} "
            f"for weapon {weapon.get('display_name')}"
        )
    out: List[Tuple[str, Optional[int]]] = []
    for entry in rules:
        if isinstance(entry, str):
            head, _, tail = entry.partition(":")
            name = head.strip().upper()
            raw_param = tail.strip() if tail else None
        else:
            raise TypeError(
                f"Unsupported WEAPON_RULES entry type: {type(entry).__name__} ({entry!r})"
            )
        param: Optional[int]
        if raw_param in (None, ""):
            param = None
        else:
            try:
                param = int(raw_param)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid parameter for weapon rule {name!r}: {raw_param!r}"
                ) from exc
        out.append((name, param))
    return tuple(sorted(out, key=lambda item: (item[0], -1 if item[1] is None else item[1])))


def profile_identity(weapon: Dict[str, Any]) -> Tuple[Any, ...]:
    """Identité d'un profil d'arme : ses caractéristiques + ses règles.

    Deux armes de NOMS différents mais de profil identique sont le MÊME profil du point de vue
    de l'agent (c'est le profil qui décide de la résolution, pas le nom). Inversement, une arme
    « à profils multiples » est plusieurs entrées de la liste, donc plusieurs profils — aucun
    cas particulier n'est nécessaire (§9.4).
    """
    return (
        str(require_key(weapon, "NB")),
        int(require_key(weapon, "ATK")),
        int(require_key(weapon, "STR")),
        int(require_key(weapon, "AP")),
        str(require_key(weapon, "DMG")),
        int(weapon["RNG"]) if "RNG" in weapon else -1,  # get allowed : mêlée = pas de portée
        _rule_entries(weapon),
    )


def collect_weapon_profiles(
    models: Sequence[Dict[str, Any]],
    weapons_key: str,
) -> List[Tuple[Dict[str, Any], int]]:
    """Profils DISTINCTS portés par des figurines VIVANTES, avec leur nombre de porteurs.

    Retourne [(arme représentative, nb de porteurs vivants), …] dans un ordre DÉTERMINISTE :
    porteurs décroissants, puis identité de profil. Cet ordre est une donnée brute (un
    comptage), pas un modèle de combat : il ne suppose rien sur l'efficacité des armes, et il
    ne permute pas d'un step à l'autre tant que l'effectif ne change pas.
    """
    counts: Dict[Tuple[Any, ...], int] = {}
    sample: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for model in models:
        weapons = require_key(model, weapons_key)
        if not isinstance(weapons, list):
            raise TypeError(
                f"{weapons_key} must be a list, got {type(weapons).__name__} "
                f"for model {model.get('id')}"
            )
        # Une figurine peut décliner le MÊME profil deux fois (deux armes identiques) : elle
        # ne compte qu'une fois comme porteuse, le volume vient de NB.
        for key, weapon in {profile_identity(w): w for w in weapons}.items():
            counts[key] = counts.get(key, 0) + 1  # get allowed : accumulateur, 0 = 1re occurrence
            sample.setdefault(key, weapon)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], repr(item[0])))
    return [(sample[key], count) for key, count in ordered]


def encode_weapon_profile(
    cont: List[float],
    binv: List[float],
    rule_names: List[List[str]],
    weapon: Optional[Dict[str, Any]],
    carriers: int,
) -> None:
    """Émet UN profil (ou un slot vide, tout à zéro avec mask=0) dans les trois vecteurs.

    Les valeurs de dés (`NB`/`DMG` = "D3", "D6"…) passent par `expected_dice_value` : c'est la
    conversion déterministe déjà utilisée par le moteur, pas une estimation.

    `rule_names` reçoit UNE liste par slot : les NOMS des règles observées, jamais leurs ids. La
    traduction en `obs_id` et le remplissage des slots appartiennent à `observation_builder`
    (`_fill_id_slots`), seul écrivain d'ensembles d'ids — c'est lui qui porte le tri, le padding
    et les gardes de domaine et de débordement, pour les capacités comme pour les armes.
    """
    if weapon is None:
        cont.extend([0.0] * PROFILE_CONT_SIZE)
        binv.extend([0.0] * PROFILE_BIN_SIZE)
        rule_names.append([])
        return

    cont.append(expected_dice_value(require_key(weapon, "NB"), "obs_profile_nb"))
    cont.append(float(int(require_key(weapon, "ATK"))))
    cont.append(float(int(require_key(weapon, "STR"))))
    cont.append(float(int(require_key(weapon, "AP"))))
    cont.append(expected_dice_value(require_key(weapon, "DMG"), "obs_profile_dmg"))
    # Portée en subhex BRUTS, directement comparable à la distance bord-à-bord du bloc ennemi.
    # Une arme de mêlée n'a pas de portée : 0.0 est ici la lecture exacte (le registre mêlée est
    # un bloc séparé, il n'y a aucune ambiguïté avec « portée inconnue »).
    cont.append(float(int(weapon["RNG"])) if "RNG" in weapon else 0.0)  # get allowed
    cont.append(float(carriers))

    for rule_id, nude_value in WEAPON_RULE_PARAMS:
        if not weapon_has_rule(weapon, rule_id):
            cont.append(0.0)
            continue
        parameter = weapon_rule_parameter_or_nude(weapon, rule_id, nude_value)
        cont.append(float(parameter))

    anti_threshold, anti_keyword = anti_rule_of(weapon)
    cont.append(float(anti_threshold))

    binv.append(1.0)  # slot occupé — seul drapeau positionnel restant du profil

    names = [rule_id for rule_id in WEAPON_RULE_BITS if weapon_has_rule(weapon, rule_id)]
    if anti_keyword is not None:
        # 24.02 : plusieurs [ANTI] ne se cumulent pas — `anti_rule_of` a déjà retenu le MEILLEUR
        # seuil, et c'est cette règle-là, une seule, dont l'identité est observée.
        names.append(ANTI_RULE_PREFIX + anti_keyword)
    rule_names.append(names)


def weapon_rule_parameter_or_nude(
    weapon: Dict[str, Any], rule_id: str, nude_value: int
) -> int:
    """Paramètre d'une règle présente ; `nude_value` si la forme NUE est légale (BLAST).

    `nude_value == 0` signifie « cette règle EXIGE son paramètre » (RAPID FIRE X, MELTA X…) :
    l'absence de paramètre lève alors, via `weapon_rule_parameter`. Ce n'est donc pas un repli
    d'erreur — la forme nue de [BLAST] (1 dé par tranche de 5, 24.05) est une forme légale de
    la règle, et c'est la seule qui bénéficie d'une valeur implicite. Source du comportement
    « or default » : `weapon_rule_parameter_or` (weapon_helpers), utilisé par le résolveur.
    """
    if nude_value == 0:
        parameter = weapon_rule_parameter(weapon, rule_id)
        if parameter is None:
            raise ValueError(
                f"Weapon rule {rule_id!r} present without its required parameter "
                f"on weapon {weapon.get('display_name')!r}"
            )
        return parameter
    from engine.utils.weapon_helpers import weapon_rule_parameter_or

    resolved = weapon_rule_parameter_or(weapon, rule_id, nude_value)
    # `weapon_rule_parameter_or` renvoie son `default` quand la regle est absente ou nue ; ici la
    # regle est PRESENTE (verifie par l appelant) et `default` est un int -> None est impossible.
    if resolved is None:
        raise ValueError(
            f"Weapon rule {rule_id!r} resolved to None on weapon "
            f"{weapon.get('display_name')!r} despite a non-null default"
        )
    return int(resolved)


def anti_rule_of(weapon: Dict[str, Any]) -> Tuple[int, Optional[str]]:
    """Seuil Y+ et keyword ciblé de [ANTI-X Y+] 24.03, ou (0, None).

    24.02 (Duplicated abilities) : plusieurs [ANTI] sur la même arme ne se cumulent pas — on
    expose le MEILLEUR seuil (le plus bas), exactement comme le résolveur de la règle.
    """
    best_threshold: Optional[int] = None
    best_keyword: Optional[str] = None
    for rule_id in ANTI_RULE_IDS:
        if not weapon_has_rule(weapon, rule_id):
            continue
        # JUMEAU de `_anti_crit_wound_threshold` : MEME lecture, MEME domaine (Y+ >= 2, 05.02).
        # Deux lectures separees du meme parametre, c est le motif d echec n°1 de ce depot.
        threshold = anti_threshold_of(weapon, rule_id)
        if best_threshold is None or threshold < best_threshold:
            best_threshold = threshold
            best_keyword = rule_id[len(ANTI_RULE_PREFIX):]
    if best_threshold is None:
        return 0, None
    return best_threshold, best_keyword


def encode_squad_weapon_profiles(
    cont: List[float],
    binv: List[float],
    rule_names: List[List[str]],
    models: Sequence[Dict[str, Any]],
    k_ranged: int,
    k_melee: int,
    on_truncation: Optional[Any] = None,
) -> None:
    """Émet les K profils de tir puis les K profils de mêlée d'une escouade.

    `on_truncation(registre, nb_profils, k)` est appelé quand l'escouade porte plus de profils
    que de slots — la troncature doit être VISIBLE (§11 « troncature loguée, jamais silencieuse »).
    """
    for weapons_key, k_slots in ((RANGED_KEY, k_ranged), (MELEE_KEY, k_melee)):
        profiles = collect_weapon_profiles(models, weapons_key)
        if len(profiles) > k_slots and on_truncation is not None:
            on_truncation(weapons_key, len(profiles), k_slots)
        for slot in range(k_slots):
            if slot >= len(profiles):
                encode_weapon_profile(cont, binv, rule_names, None, 0)
                continue
            weapon, carriers = profiles[slot]
            encode_weapon_profile(cont, binv, rule_names, weapon, carriers)
