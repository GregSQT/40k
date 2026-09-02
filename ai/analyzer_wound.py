"""Contrôle du SEUIL DE BLESSURE journalisé (05.02), tir et mêlée.

Le journal écrit le seuil qu'il a réellement appliqué : ``Wound 4(4+)``. Rien ne le vérifiait.
Un seuil amélioré restait donc inexplicable — le +1 Force du Waaagh est journalisé
(``waaagh_melee_str=+1``) sans qu'aucun contrôle ne s'en serve, et une erreur de F ou de E
passait inaperçue puisque le moteur est seul juge de son propre affichage.

CE QUI EST MESURÉ. Le seuil ATTENDU est recalculé depuis la donnée :

    F de l'ARME de la figurine qui frappe   (`[SHOOTER_MODELS:]` + `[MODEL_TYPES:]` + registry)
  + bonus de Force en vigueur               (ligne `T{tour} EFFECTS:`, mêlée seulement — 08.04)
  vs
    E de la cible                           (19.02 : plus haute E des BODYGUARDS, jamais celle
                                              du leader rattaché)
  → `calculate_wound_target`                (la fonction du MOTEUR, jamais une copie)
  − bonus au JET (Oath of Moment)           (marqué `[OATH OF MOMENT]` sur la ligne, plancher 2+)

et comparé au seuil imprimé. Un écart est une contradiction entre ce que le moteur applique et
ce que ses propres données disent — pas une préférence de l'analyzer.

CE QUI EST DÉLIBÉRÉMENT ÉCARTÉ. Le contrôle ne se prononce PAS quand une donnée manque : arme
irrésolue, datasheet absente du registre, caractéristique symbolique, `[SHOOTER_MODELS:]` absent
d'un vieux journal. Ces lignes sont comptées à part (« non vérifiables ») et non en erreur : un
contrôle qui crie sur une donnée manquante finit ignoré, et c'est la panne dont il protège.
Elles restent VISIBLES — un compteur qui tombe à zéro parce qu'il ne regarde plus rien est le
défaut le plus coûteux de ce dépôt.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from ai.analyzer_core import ACTION_ABILITY_TOKENS
from shared.data_validation import require_key

#: `Wound 4(4+) [TOKEN…]` — le jet, le seuil appliqué, et les tokens ATTACHÉS à ce segment.
#: `Wound 4` sans parenthèse (blessure automatique, [LETHAL HITS] 24.23) ne correspond pas : il
#: n'y a pas de seuil à vérifier. La queue de tokens est ici et non dans une seconde regex parce
#: qu'un token appartient au segment qu'il SUIT (`RULE_TOKEN_SEGMENTS`, côté moteur) :
#:
#: ⚠️ Chercher un token n'importe où dans la ligne est FAUX : `[OATH OF MOMENT]` est aussi posé
#: sur la relance de TOUCHE (`Hit 4(3+) [REROLLED:2] [OATH OF MOMENT]`). Mesuré sur le journal :
#: 80 occurrences pour 60 lignes, donc des lignes qui le portent deux fois. Une ligne qui ne le
#: porte QUE côté touche (bonus de blessure nul) faisait alors abaisser le seuil attendu d'un
#: point — un faux « seuil de blessure faux » à chaque tir de ce genre.
#:
#: `ACTION_ABILITY_TOKENS` et non une copie : c'est la grammaire du journal, pas celle de ce
#: site (mêmes raisons que `move_line_re` / `attack_line_re`, dont les copies avaient divergé).
WOUND_SEGMENT_RE = re.compile(
    r"Wound\s+(\d+)\((\d+)\+\)(" + ACTION_ABILITY_TOKENS + r")"
)
OATH_MARKER = "[OATH OF MOMENT]"
LITANY_MARKER = "[LITANY OF HATE]"


def parse_wound_threshold(action_desc: str) -> Optional[int]:
    """Seuil imprimé sur la ligne, ou ``None`` si elle n'en porte pas."""
    m = WOUND_SEGMENT_RE.search(action_desc)
    return int(m.group(2)) if m else None


def wound_bonus_applies(action_desc: str) -> bool:
    """Le +1 au jet de blessure joue-t-il sur CETTE ligne ? (cf. `WOUND_SEGMENT_RE`)"""
    m = WOUND_SEGMENT_RE.search(action_desc)
    return bool(m) and OATH_MARKER in m.group(3)


def _effect_bonus(state: Any, player: int, key: str) -> int:
    """Bonus chiffré LU dans la ligne ``EFFECTS``. `+1` et `1` acceptés, absent = 0.

    Lu, jamais redeviné : coder la magnitude ici ferait vivre une seconde définition de la règle,
    qui divergerait en silence le jour où la constante du moteur bouge (même raisonnement que le
    bonus d'attaques du Waaagh dans `_cc_cap_for_line`).
    """
    effects = state.active_effects.get(int(player), {})  # get allowed : aucun effet en vigueur
    raw = effects.get(key)  # get allowed
    return int(str(raw).lstrip("+")) if raw is not None else 0


def attacker_weapon_strengths(
    state: Any,
    config: Any,
    weapon_display_name: str,
    attacker_unit_type: str,
    shooters: Tuple[str, ...],
    is_melee: bool,
) -> Optional[Tuple[int, ...]]:
    """F de CHAQUE profil d'arme que la ligne couvre, résolue PAR FIGURINE. ``None`` = irrésoluble.

    Une ligne n'a pas toujours UNE Force, et c'est le fait central de cette fonction : le moteur
    fusionne sur une seule ligne les armes de même signature d'attaque (« A / B »), et plusieurs
    figurines de datasheets différentes (règle 19) peuvent y frapper. La ligne porte alors
    plusieurs Forces RÉELLES — et le seuil imprimé, lui, est unique. C'est à
    `expected_wound_threshold` de dire si ces Forces convergent vers un seuil attendu unique ;
    en inventer une ici (le `max()`) rendrait un verdict sur une figurine qui n'existe pas.

    RÉSOLUTION PAR FIGURINE, comme le plafond d'attaques — cinq armes s'appellent « Close Combat
    Weapon », de F 3 à 6, et c'est la datasheet de la FIGURINE qui tranche — mais SANS ses étages
    d'agrégation (`resolve_weapon_characteristic`) : un plafond agrégé sur-autorise, une Force
    agrégée est inventée.

    Un même nom d'arme à DEUX Forces selon la figurine (« Close Combat Weapon » F3 au troupier,
    F4 au personnage rattaché) rend les DEUX, pour la même raison : ce sont deux Forces réelles
    de la ligne. Le verdict se joue sur le seuil, pas sur l'unicité de la Force.

    ``None`` (non vérifiable) dans les seuls cas où la donnée manque VRAIMENT : une figurine
    nommée dont on ignore la datasheet (hors `[MODEL_TYPES:]`, ou type hors registre), une
    figurine dont la datasheet ne connaît AUCUN profil de la ligne, ou un profil qu'AUCUNE
    d'elles ne connaît — arme absente, F symbolique du registre.
    """
    from ai.analyzer_perfig import resolve_weapon_characteristic, weapon_profile_names

    per_unit_key = "cc_str_by_weapon" if is_melee else "rng_str_by_weapon"
    if shooters:
        types = [state.model_types.get(mid) for mid in shooters]  # get allowed
    else:
        # Journal SANS `[SHOOTER_MODELS:]` : aucune figurine nommée, l'escouade est le seul
        # porteur connu. C'est le mode dégradé assumé des vieux journaux, pas un repli.
        types = [attacker_unit_type]
    strengths = set()
    # Profils que personne n'a encore résolus. Un profil ABSENT d'une datasheet est porté par une
    # autre figurine de la ligne — cas normal d'un composite inter-datasheets. Le trou, c'est un
    # profil qu'AUCUNE d'elles ne connaît, donc ce qui reste ici à la fin.
    missing = set(weapon_profile_names(weapon_display_name))
    for model_type in types:
        # Datasheet indisponible pour CETTE figurine (la docstring dit lesquels des deux manques) :
        # on décline la ligne entière plutôt que de retomber sur la datasheet d'ESCOUADE, ce qui
        # mesurerait la F6 d'un personnage rattaché à la F4 du troupier — le faux « seuil de
        # blessure faux » que la résolution per-figurine existe pour éviter.
        # Le cas « type inconnu » est testé ICI et non laissé au dictionnaire : faire porter la
        # décision par l'absence de la clé `None` la ferait dépendre d'une propriété que rien
        # n'écrit. Même forme qu'au jumeau `target_bodyguard_toughness` de ce fichier.
        limits = (
            config.unit_attack_limits.get(model_type)  # get allowed
            if model_type is not None else None
        )
        if limits is None:
            return None
        # ⚠️ `resolve_weapon_characteristic` et NON `resolve_weapon_value` : ce dernier résout des
        # PLAFONDS et agrège pour ça à DEUX étages — carte globale de toutes les datasheets, et
        # `max()` des composantes d'un profil composite. Sur-évaluer un plafond ne peut que
        # sur-autoriser ; sur-évaluer une FORCE rend une valeur qu'AUCUNE figurine ne porte, donc
        # un faux « seuil de blessure faux » au lieu d'un honnête « non vérifiable ». Passer `{}`
        # en carte globale ne fermait que le premier étage.
        connus = 0
        for profile, value in resolve_weapon_characteristic(
            weapon_display_name, require_key(limits, per_unit_key)
        ).items():
            if value is not None:
                connus += 1
                strengths.add(value)
                missing.discard(profile)
        if not connus:
            # Cette figurine a frappé avec l'arme de la ligne et sa datasheet n'en connaît AUCUN
            # profil : c'est un trou de donnée pour ELLE, pas une répartition entre porteurs. La
            # sauter reviendrait à rendre un verdict sur la seule autre figurine — le repli
            # d'escouade que ce module refuse, déguisé en per-figurine.
            return None
    return None if missing else tuple(sorted(strengths))


def target_bodyguard_toughness(state: Any, config: Any, target_id: str) -> Optional[int]:
    """E retenue contre la cible (19.02), ou ``None`` si la composition ne permet pas de trancher.

    Règle 19.02 : la plus haute E des figurines BODYGUARD (non-CHARACTER) ; une unité qui n'a que
    des leaders/supports utilise la plus haute des leurs. Miroir de
    `_target_highest_bodyguard_toughness` — le rôle est dérivé par le MOTEUR
    (`ai.analyzer_core._model_is_character`), pas par une table locale.

    ⚠️ LES SOCLES VIVANTS NE SONT PAS TOUJOURS CONNUS — mais depuis le 2026-08-12 c'est devenu
    l'exception. Sur un journal de grammaire 1, `_apply_damage_and_handle_death` efface
    `positions_by_model[cible]` à chaque perte, faute de savoir QUELLE figurine est morte : les
    garder ferait mesurer des socles retirés du plateau. Mesuré sur le journal du témoin :
    96 lignes sur 96 écartées pour cette seule raison — un contrôle qui ne juge rien.

    À partir de la grammaire 2, `[ALLOC_MODEL:]` nomme la figurine allouée : l'escouade garde ses
    socles, ce repli ne sert plus, et le contrôle rend un verdict. Mesuré sur le même journal de
    60 épisodes, avant/après : **496 lignes non vérifiables → 0** (201 au tir, 295 en mêlée), et
    aucun seuil faux découvert — le moteur avait raison, l'analyzer ne pouvait simplement pas
    le dire.

    On retombe donc sur le ROSTER complet (`[MODEL_TYPES:]`, jamais effacé), ce qui est EXACT
    tant qu'au moins un bodyguard est vivant : la plus haute E des bodyguards ne dépend pas de
    combien d'entre eux restent, et 19.02 ignore le leader de toute façon. Le seul cas
    ambigu — tous les bodyguards morts, il ne reste que le personnage, dont l'E s'applique alors —
    est DÉTECTÉ par l'effectif (`unit_models_alive`) et rendu non vérifiable. On ne devine pas.
    """
    from ai.analyzer_core import _model_is_character

    roster_fallback = False
    mids = list(state.positions_by_model.get(target_id, {}))  # get allowed : socles effacés
    if not mids:
        roster_fallback = True
        roster = [m for m in state.model_types if m.startswith(f"{target_id}#")]
        if not roster:
            return None
        n_characters = sum(
            1 for m in roster if _model_is_character(config, state.model_types.get(m))  # get allowed
        )
        n_alive = state.unit_models_alive.get(target_id)  # get allowed : effectif inconnu
        if n_alive is None or n_alive <= n_characters:
            return None  # plus aucun bodyguard garanti vivant : l'E dépend de qui reste
        mids = roster
    toughness: Dict[str, int] = {}
    for mid in mids:
        model_type = state.model_types.get(mid)  # get allowed
        if model_type is None:
            return None
        value = config.unit_toughness_by_type.get(model_type)  # get allowed : E symbolique
        if value is None:
            return None
        toughness[mid] = int(value)
    bodyguards = [
        m for m in mids
        if not _model_is_character(config, state.model_types.get(m))  # get allowed
    ]
    pool = bodyguards or mids
    if roster_fallback and len({toughness[m] for m in pool}) > 1:
        # Repli sur le ROSTER (socles vivants inconnus) ET bodyguards d'ENDURANCES DIFFÉRENTES :
        # le roster contient aussi les morts, donc le `max` pourrait être celui d'une figurine
        # déjà retirée alors que le moteur, lui, ne maxe que sur les vivantes. Indécidable avec
        # la donnée disponible — on le dit au lieu de trancher. Bodyguards homogènes (le cas
        # courant) → la mort d'un socle ne change pas le max, le repli reste exact.
        return None
    base_toughness = max(toughness[m] for m in pool)
    # `toughness_bonus_while_waaagh` (BannerNob) : +N à l'E de la cible quand le Waaagh est actif
    # pour le joueur cible. Miroir de `_target_highest_bodyguard_toughness` (engine). Le bonus est
    # accordé par une figurine vivante de la pool — on vérifie via `model_types`, jamais deviné.
    target_player = state.unit_player.get(target_id)
    if target_player is not None:
        waaagh_on = (
            state.active_effects.get(int(target_player), {}).get("waaagh") == "on"  # get allowed
        )
        if waaagh_on:
            # Cherche dans `mids` (tous les socles) et non dans `pool` (bodyguards) : le BannerNob
            # est un CHARACTER, donc absent de `pool` — or c'est LUI qui porte le bonus Waaagh.
            for m in mids:
                mt = state.model_types.get(m)  # get allowed
                bonus = config.toughness_bonus_waaagh_by_type.get(mt, 0)  # get allowed
                if bonus:
                    base_toughness += bonus
                    break
    return base_toughness


def expected_wound_threshold(
    state: Any,
    config: Any,
    action_desc: str,
    attacker_player: int,
    attacker_unit_id: str,
    attacker_unit_type: str,
    weapon_display_name: str,
    target_id: str,
    shooters: Tuple[str, ...],
    is_melee: bool,
) -> Optional[int]:
    """Seuil que le moteur DEVRAIT imprimer, ou ``None`` si la ligne n'est pas vérifiable.

    UNE ligne, PLUSIEURS profils d'arme (cf. `attacker_weapon_strengths`) : le seuil attendu est
    calculé pour CHACUN, avec sa vraie Force, et n'est rendu que s'ils tombent tous sur la même
    valeur. Sinon le seuil unique imprimé n'a pas d'attendu unique — non vérifiable, et le dire
    vaut mieux que trancher pour l'un des profils.

    Ce n'est pas un contrôle qui s'aveugle : la clé de fusion du moteur est bâtie sur le seuil
    AFFICHÉ, donc deux profils fusionnés blessent déjà la cible pareil et convergent tant que le
    moteur a raison — la ligne garde son verdict. Ils ne divergent que si l'Endurance retenue par
    le moteur n'est pas celle que la donnée dit (mesuré : 2 750 quadruplets (Fa, Fb, E moteur,
    E réelle) où la fusion est possible et les attendus diffèrent). Ce cas-là est précisément
    celui où choisir une Force — l'ancien `max()` — rendait un verdict sur un profil inventé.
    """
    from engine.combat_utils import calculate_wound_target

    strengths = attacker_weapon_strengths(
        state, config, weapon_display_name, attacker_unit_type, shooters, is_melee
    )
    if strengths is None:
        return None
    toughness = target_bodyguard_toughness(state, config, target_id)
    if toughness is None:
        return None
    # +1 Force du Waaagh : armes de MÊLÉE uniquement (08.04). Il n'a pas de jumeau au tir, et
    # l'appliquer là rendrait le contrôle faux exactement là où il doit être utile.
    bonus = _effect_bonus(state, attacker_player, "waaagh_melee_str") if is_melee else 0
    # Oath of Moment : +1 au JET, donc seuil abaissé, plancher 2+ (`resolve_oath_effects`).
    # Le token doit suivre le segment `Wound …` — ailleurs sur la ligne, il décrit la touche.
    # Appliqué PAR PROFIL, avant l'unanimité : le plancher 2+ rapproche deux seuils voisins, et
    # ce qui doit être unique, c'est la valeur IMPRIMABLE — pas une étape de son calcul.
    oath = wound_bonus_applies(action_desc)
    # Magnitude du bonus de blessure Oath : lue dans la snapshot `oath_wound` (EFFECTS), jamais
    # recodée. Minimum 1 : journaux antérieurs au 2026-08-10 n'émettaient pas la clé → 0 lu → 1.
    oath_mag = max(1, _effect_bonus(state, attacker_player, "oath_wound")) if oath else 0
    # Litany of Hate (`wound_roll_bonus_fight`, Primitive A, chantier 06) : SECOND +1 au même
    # jet, mêlée seulement, qui se CUMULE avec Oath. Sans lui, chaque ligne de mêlée d'une
    # escouade menée par un Chaplain sortirait en « seuil de blessure faux » alors que le moteur
    # a raison — un faux positif systématique, le défaut que ce contrôle existe pour éviter.
    #
    # Détection duale : datasheet d'abord (Chaplain directement dans l'escouade via
    # positions_by_model), puis token `[LITANY OF HATE]` pour le ChaplainJumpPack attaché sous
    # son propre unit_id (ses socles ne sont pas dans positions_by_model du squad mené, donc
    # `unit_effect_in_force` retourne False pour lui).
    #
    # LE ROSTER EST INTERROGÉ D'ABORD (court-circuit) : aucune datasheet vue ne porte la capacité
    # ⇒ le bonus vaut 0 sans examiner ni l'état ni la ligne.
    litany_mag = 0
    if is_melee and config.rule_to_units.get("wound_roll_bonus_fight"):  # get allowed
        from ai.analyzer_perfig import unit_effect_in_force
        in_squad = unit_effect_in_force(state, config, attacker_unit_id, "wound_roll_bonus_fight")
        litany_mag = 1 if in_squad or LITANY_MARKER in action_desc else 0
    cap_val = config.bonus_malus_cap
    total_bonus = oath_mag + litany_mag
    if cap_val and total_bonus > cap_val:
        total_bonus = cap_val
    thresholds = set()
    for strength in strengths:
        threshold = calculate_wound_target(strength + bonus, toughness)
        thresholds.add(max(2, threshold - total_bonus) if total_bonus else threshold)
    return thresholds.pop() if len(thresholds) == 1 else None


def check_wound_threshold(
    state: Any,
    config: Any,
    stats: Dict[str, Any],
    line: str,
    action_desc: str,
    attacker_player: int,
    attacker_unit_id: str,
    attacker_unit_type: str,
    weapon_display_name: str,
    target_id: str,
    shooters: Tuple[str, ...],
    is_melee: bool,
) -> None:
    """Compare le seuil imprimé au seuil attendu. Compte l'écart, ou l'inverifiabilité."""
    logged = parse_wound_threshold(action_desc)
    if logged is None:
        return
    key = "fight_wound_threshold" if is_melee else "shoot_wound_threshold"
    expected = expected_wound_threshold(
        state, config, action_desc, attacker_player, attacker_unit_id, attacker_unit_type,
        weapon_display_name, target_id, shooters, is_melee,
    )
    if expected is None:
        stats[f"{key}_unverifiable"][attacker_player] += 1
        return
    if expected == logged:
        return
    stats[f"{key}_mismatch"][attacker_player] += 1
    first = stats["first_error_lines"][f"{key}_mismatch"]
    if first[attacker_player] is None:
        first[attacker_player] = {
            "episode": state.current_episode_num,
            "line": line.strip(),
            "detail": f"seuil imprimé {logged}+ vs attendu {expected}+",
        }
