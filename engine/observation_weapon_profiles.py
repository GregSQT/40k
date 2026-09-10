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
  `shooting_handlers`). [INDIRECT FIRE] 24.19 y est ENTRÉE le 2026-08-16 avec l'implémentation
  de 10.07 ; le paragraphe ci-dessous décrit l'état ANTÉRIEUR, où elle n'était pas
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

from collections import defaultdict
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
    # [INDIRECT FIRE] 24.19 / tir indirect 10.07. Entree le 2026-08-16, avec l implementation de
    # la regle : jusque-la elle etait DELIBEREMENT absente (un id pour une regle sans effet aurait
    # ete du bruit pur, et un test le verrouillait). L agent doit la percevoir parce qu il doit
    # POUVOIR CHOISIR le tir indirect (10.02) : un type de tir qu on ne voit pas est un type de
    # tir qu on ne joue jamais. L ajout ne coute AUCUN parametre — `OBS_ID_VOCAB_SIZE` est
    # pre-dimensionne a 128 et ne s ajuste pas au nombre de regles (cf. `observation_entities`).
    "INDIRECT_FIRE",
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
# ⚠️ Ces slots portent AUSSI le marqueur de groupe combi (cf. `COMBI_GROUP_MARKER_NAMES`), qui
# n'est pas une règle d'arme. Re-mesuré marqueur compris sur les 159 armes distinctes des 6
# armureries : le pire cas reste `Plasma Exterminator (Supercharge)`, 4 règles, et il EST un
# profil combi — donc 5 ids sur 6. La marge est d'un slot, et le débordement lève.
# ⚠️ Débordement = ERREUR (`observation_builder._fill_id_slots`), jamais troncature : une règle
# tronquée serait une règle que l'agent subit sans la percevoir.
WEAPON_RULE_ID_SLOTS = 6

# ---------------------------------------------------------------------------
# Marqueurs de GROUPE COMBI — l'exclusivité des profils d'une même arme physique
# ---------------------------------------------------------------------------
#
# LE DÉFAUT QU'ILS FERMENT. Deux profils d'une même arme physique (champ `COMBI_WEAPON`, ex.
# Plasma Incinerator Standard/Supercharge) sont deux entrées de la liste d'armes, donc deux
# profils DISTINCTS pour `collect_weapon_profiles` (§9.4), donc deux slots de l'observation. Rien
# ne disait qu'ils sont EXCLUSIFS : en tirer un consomme l'arme entière (renvoi « Multiple Weapon
# Profiles » de 04.01, appliqué par `shared_utils._pick_one_profile_per_weapon_group` et par le
# masque de `_open_shoot_weapon_sel_slots`). L'agent lisait donc DEUX armes là où il en joue une.
#
# MESURÉ sur `build_armageddon_engine(seed=0)` : sur les 20 couples escouade × registre, 6
# sur-comptent le volume de tir EN DÉS D'ATTAQUE (somme des profils observés contre volume
# exclusif réel, un profil par arme physique et par figurine) de +5,3 % à +28,6 % — et jamais
# en mêlée, où aucune arme du dépôt ne porte de `COMBI_WEAPON` (0 groupe sur les 6 armureries,
# contre 12 au tir).
#
# CE QUE L'INFORMATION N'EST PAS. Elle n'est PAS dérivable du reste de l'observation :
# `profile_identity` n'inclut pas `COMBI_WEAPON`, et aucun registre ne relie un profil à une
# figurine — un Intercessor portant bolt_rifle + bolt_pistol (deux armes physiques qui tirent
# TOUTES LES DEUX, 04.01 « You can select one or more ranged weapons that model has ») se
# présentait exactement comme un combi à deux profils.
#
# POURQUOI UN `obs_id` ET PAS UN BIT. Un bit « je suis exclusif » ne dirait pas AVEC QUI : une
# escouade porte jusqu'à 2 groupes combi distincts (MESURÉ sur tous les rosters de
# `config/agents/`, pire cas `Intercessor` + `Librarian` = grenade_launcher_intercessor et
# smite), et l'agent doit pouvoir apparier les profils deux à deux. Un id le fait pour ZÉRO
# scalaire d'observation et ZÉRO paramètre : il se pose dans les `WEAPON_RULE_ID_SLOTS` déjà
# réservés, et `OBS_ID_VOCAB_SIZE` (128) est pré-dimensionné.
#
# POURQUOI UN REGISTRE PYTHON. Les `obs_id` de règles viennent de `config/weapon_rules.json` et
# occupent 1..18 ; un marqueur n'est PAS une règle d'arme et n'a rien à faire dans ce fichier.
# La plage réservée ci-dessous en est DISJOINTE, et `observation_builder.weapon_profile_obs_ids`
# lève si les deux se recouvrent un jour.
COMBI_GROUP_OBS_ID_BASE = 64
#: Nombre de groupes combi distincts marquables dans UNE escouade. Un groupe marqué occupe au
#: moins 2 slots de profils (un groupe à profil unique n'a personne avec qui être exclusif, cf.
#: `assign_combi_group_markers`), donc `K_WEAPONS // 2 = 10` est la borne STRUCTURELLE — au-delà
#: il n'y a plus de slot de profil pour porter le groupe. Maximum MESURÉ : 2.
#: Débordement = ERREUR, jamais silence : un marqueur manquant redonnerait à l'agent le défaut
#: que ce bloc ferme, sans que rien ne le dise.
#: ⚠️ `encode_squad_weapon_profiles` numérote sur les profils OBSERVÉS : au plus `k_slots // 2`
#: groupes marqués par registre, donc au plus 10 pour les deux — la borne ci-dessus est
#: désormais tenue par construction et l'erreur est inatteignable depuis ce chemin. Elle reste
#: le contrat de `assign_combi_group_markers` pour tout appelant direct, et n'est pas retirée :
#: c'est ce contrat qui interdit de marquer moins de groupes que la réalité.
COMBI_GROUP_MARKER_COUNT = 10
#: Les marqueurs sont ANONYMES et locaux à l'escouade : `COMBI_GROUP_0` ne désigne pas
#: `plasma_pistol`, il désigne « le premier groupe exclusif de cette escouade, dans l'ordre
#: déterministe de `collect_weapon_profiles` ». C'est le seul sens utile — l'agent a besoin de
#: savoir QUELS SLOTS s'excluent, pas de reconnaître un nom d'arme (les caractéristiques du
#: profil le disent déjà, et un id par arme du dépôt serait un vocabulaire à maintenir).
COMBI_GROUP_MARKER_NAMES: Tuple[str, ...] = tuple(
    f"COMBI_GROUP_{i}" for i in range(COMBI_GROUP_MARKER_COUNT)
)
COMBI_GROUP_MARKER_OBS_IDS: Dict[str, int] = {
    name: COMBI_GROUP_OBS_ID_BASE + i for i, name in enumerate(COMBI_GROUP_MARKER_NAMES)
}

# Layout d'UN profil (l'ordre ci-dessous EST l'ordre d'émission).
#   cont     : NB, ATK, STR, AP, DMG, portée, porteurs vivants, puis les paramètres de règles,
#              puis le seuil Y+ de [ANTI-X] (0 = aucune règle ANTI).
#   bin      : cf. `PROFILE_BIN_FIELDS` ci-dessous.
#   rule_ids : l'ensemble des `obs_id` de règles du profil, trié et paddé à 0.
PROFILE_STAT_CONT = 7
PROFILE_CONT_SIZE = PROFILE_STAT_CONT + len(WEAPON_RULE_PARAMS) + 1

#: Drapeaux d'UN profil d'arme, dans l'ordre d'émission.
#:
#: `shoot_weapon_selected` — 1 sur le profil que l'agent VIENT de choisir pendant le split-fire
#: (P3-8), quand le point d'arrêt suivant lui demande la CIBLE de cette arme
#: (`pending_shoot_weapon_split` avec `pending_weapon` armé). Rien d'autre ne le disait, MESURÉ le
#: 2026-09-09 : deux états ne différant que par l'arme armée produisaient des observations
#: IDENTIQUES au moment du `SHOOT_SLOT`. La politique n'est pas récurrente (MaskablePPO), donc
#: elle ne se souvient pas du `SHOOT_WEAPON_SEL_SLOT` joué au step précédent : sans ce drapeau,
#: la cible se choisit sans savoir si l'arme qui va tirer est un fuseur ou un bolter. Jumeau
#: côté mêlée : `fight_target_selected` (`observation_entities`), qui marque la cible déjà fixée
#: quand c'est l'arme qui reste à choisir.
#:
#: ⚠️ Il n'est PAS écrit par cet encodeur, dont la sortie est MISE EN CACHE par (escouade,
#: figurines vivantes) — le point d'arrêt, lui, change sans que la composition bouge. C'est
#: `ObservationBuilder.build_squad_observation` qui le pose sur le tenseur d'observation, après
#: la copie hors cache, et uniquement sur la ligne de l'escouade OBSERVATRICE : sur toute autre
#: entité, alliée comme ennemie, la question n'a pas de référent et le drapeau reste à 0.
#:
#: `present` reste le DERNIER champ (convention uniforme §0.37) : `ai/spatial_extractor` lit le
#: masque de profil positionnellement (`wpn_bin[..., -1]`), et un ajout en tête le laisse juste.
PROFILE_BIN_FIELDS: Tuple[str, ...] = (
    "shoot_weapon_selected",
    "present",
)
PROFILE_BIN_SIZE = len(PROFILE_BIN_FIELDS)

_PROFILE_BIN_INDEX: Dict[str, int] = {name: i for i, name in enumerate(PROFILE_BIN_FIELDS)}
_BIN_IDX_PRESENT: int = _PROFILE_BIN_INDEX["present"]


def profile_bin_index(field: str) -> int:
    """Index d'un drapeau de profil d'arme. Nom inconnu -> KeyError explicite."""
    if field not in _PROFILE_BIN_INDEX:
        raise KeyError(
            f"Drapeau de profil d'arme inconnu : {field!r}. Champs : {PROFILE_BIN_FIELDS}"
        )
    return _PROFILE_BIN_INDEX[field]

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


def combi_group_key(weapon: Dict[str, Any]) -> Optional[str]:
    """Clé de l'arme PHYSIQUE portée par ce profil (`COMBI_WEAPON`), ou None.

    JUMEAU de `shared_utils._weapon_group_key`, qui décide de l'exclusivité au masque et à la
    résolution : MÊME champ, MÊME lecture. La différence est le domaine, et elle est voulue — le
    moteur groupe des INDEX d'armes d'UNE figurine et invente donc une clé `__solo_<i>` pour les
    armes sans combi ; l'observation groupe des PROFILS d'escouade, où « pas de combi » n'a pas
    de partenaire possible et se lit None. Écrire ici un second `__solo_` aurait créé des groupes
    d'un seul membre indexés par un numéro de slot, qui n'ont aucun sens à l'échelle de
    l'escouade.

    Le profil reçu est le REPRÉSENTANT rendu par `collect_weapon_profiles` — c'est déjà sur lui
    que `shared_utils._open_shoot_weapon_sel_slots` lit `COMBI_WEAPON` pour n'ouvrir qu'un slot
    par arme physique.
    """
    # get allowed : une arme sans profil exclusif est une ABSENCE, pas une erreur.
    key = weapon.get("COMBI_WEAPON")
    return str(key) if key else None


def assign_combi_group_markers(
    profiles: Sequence[Tuple[Dict[str, Any], int]],
    marker_by_group: Dict[str, str],
) -> List[Optional[str]]:
    """Marqueur de groupe combi de chaque profil, aligné sur `profiles` (None = aucun).

    `marker_by_group` est l'état de numérotation de L'ESCOUADE, porté par l'appelant et partagé
    entre les deux registres : un marqueur donné ne désigne donc jamais deux armes physiques
    différentes dans la même escouade, tir et mêlée confondus. Le partager est ce qui rend
    l'affirmation « même marqueur ⇒ même arme » vraie sans restriction de registre.

    UN GROUPE À PROFIL UNIQUE N'EST PAS MARQUÉ. Le marqueur dit « ces slots sont des alternatives
    de la même arme » ; un groupe qui n'occupe qu'un slot dans cette escouade n'exclut rien et se
    joue exactement comme une arme solo (c'est aussi ce que fait le masque : `opened_combi`
    n'écarte un slot que s'il en a déjà ouvert un du même groupe). Lui donner un id serait un
    symbole que l'agent doit apprendre à ignorer.

    `profiles` est donc la liste des profils RÉELLEMENT ÉMIS, pas celle que porte l'escouade :
    `encode_squad_weapon_profiles` tronque avant d'appeler, sans quoi un groupe coupé par la
    troncature laisserait un marqueur sans partenaire dans l'observation — un « groupe à profil
    unique » déguisé, exactement ce que la règle ci-dessus refuse d'écrire.

    Le grain est l'ESCOUADE, comme tout ce module. L'exclusivité, elle, est PAR FIGURINE (04.01
    parle des armes « that model has ») : deux porteurs du même combi choisissent chacun le leur.
    Le marqueur est donc lu « chaque porteur de ces slots en joue UN », ce qui est exactement le
    volume que `_pick_one_profile_per_weapon_group` déclarera — et non « l'escouade n'en tire
    qu'un seul ». Le compteur de porteurs de chaque slot porte l'autre moitié de l'information.

    Débordement de la plage réservée = ERREUR, jamais troncature — même doctrine que
    `_fill_id_slots` : un marqueur silencieusement omis remettrait deux profils exclusifs sous
    l'apparence de deux armes indépendantes.
    """
    groups: Dict[str, List[int]] = defaultdict(list)
    for i, (weapon, _) in enumerate(profiles):
        key = combi_group_key(weapon)
        if key is not None:
            groups[key].append(i)
    out: List[Optional[str]] = [None] * len(profiles)
    for key, indices in groups.items():
        if len(indices) < 2:
            continue
        marker = marker_by_group.get(key)  # get allowed : absence = groupe pas encore numéroté
        if marker is None:
            if len(marker_by_group) >= COMBI_GROUP_MARKER_COUNT:
                raise ValueError(
                    f"{len(marker_by_group) + 1} groupes combi exclusifs dans une seule escouade "
                    f"pour {COMBI_GROUP_MARKER_COUNT} marqueurs reserves "
                    f"(observation_weapon_profiles.COMBI_GROUP_MARKER_COUNT). Groupes deja "
                    f"numerotes : {sorted(marker_by_group)}, en exces : {key!r}. Marquer moins "
                    f"que la realite rendrait deux profils exclusifs indiscernables de deux armes "
                    f"independantes — le defaut que ces marqueurs ferment."
                )
            marker = COMBI_GROUP_MARKER_NAMES[len(marker_by_group)]
            marker_by_group[key] = marker
        for i in indices:
            out[i] = marker
    return out


def encode_weapon_profile(
    cont: List[float],
    binv: List[float],
    rule_names: List[List[str]],
    weapon: Optional[Dict[str, Any]],
    carriers: int,
    combi_marker: Optional[str],
) -> None:
    """Émet UN profil (ou un slot vide, tout à zéro avec mask=0) dans les trois vecteurs.

    Les valeurs de dés (`NB`/`DMG` = "D3", "D6"…) passent par `expected_dice_value` : c'est la
    conversion déterministe déjà utilisée par le moteur, pas une estimation.

    `rule_names` reçoit UNE liste par slot : les NOMS des règles observées, jamais leurs ids. La
    traduction en `obs_id` et le remplissage des slots appartiennent à `observation_builder`
    (`_fill_id_slots`), seul écrivain d'ensembles d'ids — c'est lui qui porte le tri, le padding
    et les gardes de domaine et de débordement, pour les capacités comme pour les armes.

    `combi_marker` (None = aucun) entre dans cette MÊME liste de noms : c'est un `obs_id` de plus
    dans les slots déjà réservés, et il en hérite donc les quatre propriétés d'un coup. Il est
    EXPLICITE et sans valeur par défaut — un appelant qui l'oublierait rendrait muette
    l'exclusivité des profils sans qu'aucune erreur ne le dise.
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

    # Drapeaux du profil : seul `present` se déduit d'ici. `shoot_weapon_selected` dépend du
    # point d'arrêt courant et NON de la composition de l'escouade — il est posé par
    # `ObservationBuilder`, hors du cache de profils (cf. `PROFILE_BIN_FIELDS`).
    slot_bin = [0.0] * PROFILE_BIN_SIZE
    slot_bin[_BIN_IDX_PRESENT] = 1.0  # slot occupé
    binv.extend(slot_bin)

    names = [rule_id for rule_id in WEAPON_RULE_BITS if weapon_has_rule(weapon, rule_id)]
    if combi_marker is not None:
        names.append(combi_marker)
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
    # Numérotation des groupes combi PARTAGÉE par les deux registres (cf.
    # `assign_combi_group_markers`) : un marqueur ne peut pas désigner une arme au tir et une
    # autre en mêlée dans la même escouade.
    marker_by_group: Dict[str, str] = {}
    for weapons_key, k_slots in ((RANGED_KEY, k_ranged), (MELEE_KEY, k_melee)):
        profiles = collect_weapon_profiles(models, weapons_key)
        if len(profiles) > k_slots and on_truncation is not None:
            on_truncation(weapons_key, len(profiles), k_slots)
        # Les marqueurs sont numérotés sur les profils RÉELLEMENT OBSERVÉS, jamais sur la liste
        # complète. L'ordre de `collect_weapon_profiles` est celui des porteurs décroissants, il
        # ne garde donc pas les deux profils d'une même arme physique ensemble : la troncature
        # peut couper un groupe en deux (MESURÉ : 12 profils de tir, groupe porté par 3 figurines
        # au slot 0 et par 1 au rang 11). Marquer avant de tronquer laissait le slot survivant
        # affirmer « je suis exclusif » avec un partenaire absent de l'observation — le symbole
        # muet que `assign_combi_group_markers` refuse d'écrire pour un groupe à profil unique.
        # Sur la tranche observée, c'est cette même règle (« moins de 2 occurrences, pas de
        # marqueur ») qui retire l'orphelin, sans cas particulier.
        observed = profiles[:k_slots]
        markers = assign_combi_group_markers(observed, marker_by_group)
        for slot in range(k_slots):
            if slot >= len(observed):
                encode_weapon_profile(cont, binv, rule_names, None, 0, None)
                continue
            weapon, carriers = observed[slot]
            encode_weapon_profile(cont, binv, rule_names, weapon, carriers, markers[slot])
