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

from shared.data_validation import require_key

#: `Wound 4(4+)` — le jet et le seuil appliqué. `Wound 4` sans parenthèse (blessure automatique,
#: [LETHAL HITS] 24.23) ne correspond pas : il n'y a pas de seuil à vérifier.
WOUND_SEGMENT_RE = re.compile(r"Wound\s+(\d+)\((\d+)\+\)")
#: Marqueur du +1 au JET (pas à la Force) — cf. `stamp_wound_bonus_ability` côté moteur.
OATH_MARKER = "[OATH OF MOMENT]"


def parse_wound_threshold(action_desc: str) -> Optional[int]:
    """Seuil imprimé sur la ligne, ou ``None`` si elle n'en porte pas."""
    m = WOUND_SEGMENT_RE.search(action_desc)
    return int(m.group(2)) if m else None


def _effect_bonus(state: Any, player: int, key: str) -> int:
    """Bonus chiffré LU dans la ligne ``EFFECTS``. `+1` et `1` acceptés, absent = 0.

    Lu, jamais redeviné : coder la magnitude ici ferait vivre une seconde définition de la règle,
    qui divergerait en silence le jour où la constante du moteur bouge (même raisonnement que le
    bonus d'attaques du Waaagh dans `_cc_cap_for_line`).
    """
    effects = state.active_effects.get(int(player), {})  # get allowed : aucun effet en vigueur
    raw = effects.get(key)  # get allowed
    return int(str(raw).lstrip("+")) if raw is not None else 0


def attacker_weapon_strength(
    state: Any,
    config: Any,
    weapon_display_name: str,
    attacker_unit_type: str,
    shooters: Tuple[str, ...],
    is_melee: bool,
) -> Optional[int]:
    """F de l'arme, résolue PAR FIGURINE. ``None`` = irrésoluble, donc non vérifiable.

    Même résolution que le plafond d'attaques (`resolve_weapon_value`) : cinq armes s'appellent
    « Close Combat Weapon », de F 3 à 6, et c'est la datasheet de la FIGURINE qui tranche.
    Plusieurs figurines sur la même ligne → la F doit être la MÊME pour toutes, sinon la ligne
    agrège deux profils et son seuil unique n'a pas de valeur attendue unique : non vérifiable.
    """
    from ai.analyzer_perfig import resolve_weapon_value

    per_unit_key = "cc_str_by_weapon" if is_melee else "rng_str_by_weapon"
    global_map = config.cc_str_by_weapon_global if is_melee else config.rng_str_by_weapon_global
    candidates = shooters or (None,)
    values = set()
    for mid in candidates:
        model_type = state.model_types.get(mid, attacker_unit_type) if mid else attacker_unit_type  # get allowed
        limits = config.unit_attack_limits.get(model_type)  # get allowed : type hors registre
        if limits is None:
            return None
        value = resolve_weapon_value(
            weapon_display_name, require_key(limits, per_unit_key), global_map
        )
        if value is None:
            return None
        values.add(value)
    if len(values) != 1:
        return None
    return values.pop()


def target_bodyguard_toughness(state: Any, config: Any, target_id: str) -> Optional[int]:
    """E retenue contre la cible (19.02), ou ``None`` si la composition ne permet pas de trancher.

    Règle 19.02 : la plus haute E des figurines BODYGUARD (non-CHARACTER) ; une unité qui n'a que
    des leaders/supports utilise la plus haute des leurs. Miroir de
    `_target_highest_bodyguard_toughness` — le rôle est dérivé par le MOTEUR
    (`ai.analyzer_core._model_is_character`), pas par une table locale.

    ⚠️ LES SOCLES VIVANTS NE SONT PAS TOUJOURS CONNUS. `_apply_damage_and_handle_death` efface
    `positions_by_model[cible]` à chaque perte, et délibérément : le journal ne dit pas QUELLE
    figurine est morte, donc les garder ferait mesurer des socles retirés du plateau. Mesuré sur
    le journal du témoin : 96 lignes sur 96 étaient écartées pour cette seule raison — un
    contrôle qui ne juge rien.

    On retombe donc sur le ROSTER complet (`[MODEL_TYPES:]`, jamais effacé), ce qui est EXACT
    tant qu'au moins un bodyguard est vivant : la plus haute E des bodyguards ne dépend pas de
    combien d'entre eux restent, et 19.02 ignore le leader de toute façon. Le seul cas
    ambigu — tous les bodyguards morts, il ne reste que le personnage, dont l'E s'applique alors —
    est DÉTECTÉ par l'effectif (`unit_models_alive`) et rendu non vérifiable. On ne devine pas.
    """
    from ai.analyzer_core import _model_is_character

    mids = list(state.positions_by_model.get(target_id, {}))  # get allowed : socles effacés
    if not mids:
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
    return max(toughness[m] for m in pool)


def expected_wound_threshold(
    state: Any,
    config: Any,
    action_desc: str,
    attacker_player: int,
    attacker_unit_type: str,
    weapon_display_name: str,
    target_id: str,
    shooters: Tuple[str, ...],
    is_melee: bool,
) -> Optional[int]:
    """Seuil que le moteur DEVRAIT imprimer, ou ``None`` si la ligne n'est pas vérifiable."""
    from engine.combat_utils import calculate_wound_target

    strength = attacker_weapon_strength(
        state, config, weapon_display_name, attacker_unit_type, shooters, is_melee
    )
    if strength is None:
        return None
    toughness = target_bodyguard_toughness(state, config, target_id)
    if toughness is None:
        return None
    # +1 Force du Waaagh : armes de MÊLÉE uniquement (08.04). Il n'a pas de jumeau au tir, et
    # l'appliquer là rendrait le contrôle faux exactement là où il doit être utile.
    if is_melee:
        strength += _effect_bonus(state, attacker_player, "waaagh_melee_str")
    threshold = calculate_wound_target(strength, toughness)
    # Oath of Moment : +1 au JET, donc seuil abaissé, plancher 2+ (`resolve_oath_effects`).
    if OATH_MARKER in action_desc:
        threshold = max(2, threshold - 1)
    return threshold


def check_wound_threshold(
    state: Any,
    config: Any,
    stats: Dict[str, Any],
    line: str,
    action_desc: str,
    attacker_player: int,
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
        state, config, action_desc, attacker_player, attacker_unit_type,
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
