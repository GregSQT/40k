"""Sequence d attaque commune tir / melee (PDF 05 Attack sequence + PDF 24 Core abilities).

SOURCE DE VERITE : les PDF de `Documentation/40k_rules/`. Quand `config/weapon_rules.json`
diverge du PDF, le PDF fait foi (arbitrage utilisateur 2026-07-26).

Ce module porte UNE seule implementation des jets d attaque, consommee par les deux rollers
manuels du chemin vif :
  - tir   : `shared_utils._manual_roll_intent`
  - melee : `fight_handlers._manual_roll_fight_intent`

Il centralise la notion de touche/blessure CRITIQUE (05.01 / 05.02) et les regles d armes qui
s y accrochent : [TORRENT] 24.37, [SUSTAINED HITS] 24.36, [LETHAL HITS] 24.23,
[TWIN-LINKED] 24.38, [ANTI-X] 24.03, [DEVASTATING WOUNDS] 24.10.

Ce qui reste chez l appelant (car specifique a la phase) : le pool d attaques
([BLAST] 24.05, [RAPID FIRE] 24.30, [CLEAVE] 24.06, [EXTRA ATTACKS] 24.11), les modificateurs
du seuil de touche ([HEAVY] 24.16, couvert, [PSYCHIC] 24.29), l AP effectif, les degats et
l allocation.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from shared.data_validation import require_key
from engine.utils.weapon_helpers import weapon_has_rule, weapon_rule_parameter


# 05.01 / 05.02 : un jet NON MODIFIE de 6 est critique, un jet non modifie de 1 echoue toujours.
CRITICAL_HIT_ROLL = 6
NATURAL_CRITICAL_WOUND_ROLL = 6
NATURAL_FAIL_ROLL = 1

# [ANTI-X Y+] 24.03 — familles supportees par les armories du projet. Le suffixe apres `ANTI_`
# est le KEYWORD que la cible doit avoir pour que la regle s applique.
ANTI_RULE_PREFIX = "ANTI_"
ANTI_RULE_IDS = ("ANTI_INFANTRY", "ANTI_VEHICLE", "ANTI_FLY", "ANTI_PSYKER", "ANTI_MONSTER")


@dataclass(frozen=True)
class WeaponAttackProfile:
    """Regles d arme resolues pour UN couple (arme, unite cible), constantes sur l intent."""

    crit_hit_on: int = CRITICAL_HIT_ROLL
    crit_wound_on: int = NATURAL_CRITICAL_WOUND_ROLL
    sustained_hits: int = 0
    lethal_hits: bool = False
    devastating: bool = False
    twin_linked: bool = False
    torrent: bool = False


@dataclass(frozen=True)
class RerollProfile:
    """Rerolls d ABILITES (unite), independants des regles d arme. Un de ne se relance
    qu une fois (PDF 01 Core, Re-rolls) : ce module ne relance jamais deux fois le meme de."""

    hit_1: bool = False
    wound_1: bool = False
    wound_any_fail: bool = False
    save_1: bool = False


def unit_keywords_upper(unit: Optional[Dict[str, Any]]) -> frozenset:
    """Keywords d une unite (unite + faction), normalises MAJUSCULES sans espaces/tirets.

    Conforme 19.03 : sur une unite attachee, `unit_keywords` porte deja l UNION des keywords
    de ses composants (cf. `_fold_attached_characters`). Aucun repli masquant : une unite sans
    la cle keywords rend un ensemble vide (donnee absente == aucun keyword declare), ce qui est
    le comportement metier correct pour [ANTI] (la regle ne s applique pas).
    """
    if unit is None:
        return frozenset()
    out = set()
    for key in ("unit_keywords", "UNIT_KEYWORDS", "faction_keywords", "FACTION_KEYWORDS"):
        raw = unit.get(key)  # get allowed
        if not raw:
            continue
        for entry in raw:
            if isinstance(entry, dict):
                name = entry.get("keywordId", entry.get("keyword", ""))  # get allowed
            else:
                name = entry
            token = str(name).strip().upper().replace(" ", "_").replace("-", "_")
            if token:
                out.add(token)
    return frozenset(out)


def _anti_crit_wound_threshold(weapon: Dict[str, Any], target_keywords: frozenset) -> Optional[int]:
    """Seuil de blessure critique impose par [ANTI-X Y+] 24.03, ou None si non applicable.

    24.02 (Duplicated abilities) : plusieurs [ANTI] sur la meme arme ne se cumulent pas ; le
    joueur choisit l instance qui s applique. Choix optimal et deterministe retenu : le seuil
    le PLUS BAS parmi les instances dont le keyword X est porte par la cible.
    """
    best: Optional[int] = None
    for rule_id in ANTI_RULE_IDS:
        if not weapon_has_rule(weapon, rule_id):
            continue
        keyword = rule_id[len(ANTI_RULE_PREFIX):]
        if keyword not in target_keywords:
            continue
        threshold = weapon_rule_parameter(weapon, rule_id)
        if threshold is None:
            raise ValueError(f"[ANTI] rule {rule_id!r} sans parametre Y+ sur l arme {weapon!r}")
        best = threshold if best is None else min(best, threshold)
    return best


def build_weapon_attack_profile(
    weapon: Dict[str, Any], target_unit: Optional[Dict[str, Any]],
) -> WeaponAttackProfile:
    """Profil de regles d arme pour un intent (arme fixee, unite cible fixee)."""
    anti = _anti_crit_wound_threshold(weapon, unit_keywords_upper(target_unit))
    crit_wound_on = NATURAL_CRITICAL_WOUND_ROLL if anti is None else min(NATURAL_CRITICAL_WOUND_ROLL, anti)
    sustained = 0
    if weapon_has_rule(weapon, "SUSTAINED_HITS"):
        value = weapon_rule_parameter(weapon, "SUSTAINED_HITS")
        if value is None:
            raise ValueError(f"[SUSTAINED HITS] sans parametre X sur l arme {weapon!r}")
        sustained = int(value)
    return WeaponAttackProfile(
        crit_hit_on=CRITICAL_HIT_ROLL,
        crit_wound_on=crit_wound_on,
        sustained_hits=sustained,
        lethal_hits=weapon_has_rule(weapon, "LETHAL_HITS"),
        devastating=weapon_has_rule(weapon, "DEVASTATING_WOUNDS"),
        twin_linked=weapon_has_rule(weapon, "TWIN_LINKED"),
        torrent=weapon_has_rule(weapon, "TORRENT"),
    )


def lethal_hits_auto_wound_is_better(
    profile: WeaponAttackProfile, wound_target: int, save_threshold_value: int,
) -> bool:
    """[LETHAL HITS] 24.23 : « you can CHOOSE for that attack to automatically wound ».

    Le choix est reel : l auto-blessure interdit la blessure critique, donc neutralise
    [DEVASTATING WOUNDS] (Designer's Note du PDF). On tranche par esperance de degats, en
    unites de D (le D se simplifie, il est identique des deux cotes) :

      - auto-blessure : la blessure passe a coup sur, puis subit la sauvegarde
            EV = P(sauvegarde ratee)
      - jet de blessure : chance de critique (degats non sauvegardables si DEVASTATING),
        sinon blessure normale sauvegardable
            EV = P(crit) * V_crit + (P(blessure) - P(crit)) * P(sauvegarde ratee)

    `save_threshold_value` est le seuil de sauvegarde d affichage de l intent (7 = aucune
    sauvegarde possible). Sans DEVASTATING, V_crit == P(sauvegarde ratee) : l auto-blessure
    est alors toujours au moins aussi bonne (elle ne perd jamais de blessure) -> True.
    """
    faces = range(1, 7)
    # 05.04 : la sauvegarde reussit si le jet n est pas un 1 ET atteint le seuil (7 = aucune
    # sauvegarde possible). On compte les faces, pas de formule fermee : meme regle que
    # `_resolve_one_manual_wound`, donc aucune divergence possible.
    p_save_success = sum(
        1 for f in faces if f != NATURAL_FAIL_ROLL and f >= int(save_threshold_value)
    ) / 6.0
    p_fail_save = 1.0 - p_save_success
    p_crit = sum(1 for f in faces if f >= profile.crit_wound_on) / 6.0
    p_wound = sum(
        1 for f in faces
        if f >= profile.crit_wound_on or (f != NATURAL_FAIL_ROLL and f >= wound_target)
    ) / 6.0
    v_crit = 1.0 if profile.devastating else p_fail_save
    ev_auto = p_fail_save
    ev_roll = p_crit * v_crit + (p_wound - p_crit) * p_fail_save
    return ev_auto >= ev_roll


def roll_attack_pool(
    *,
    n_attacks: int,
    hit_target: int,
    wound_target: int,
    save_threshold_value: int,
    profile: WeaponAttackProfile,
    rerolls: RerollProfile,
    roll_d6: Callable[[], int],
) -> Dict[str, Any]:
    """Resout `n_attacks` attaques : touche -> blessure -> jet de sauvegarde BRUT.

    Ne compare PAS la sauvegarde et ne tire PAS les degats : cela reste a l allocation
    (05.03/05.04), par figurine choisie, chez l appelant.

    Retourne ``{"shot_records": [...], "pending_wounds": [...], "counts": {...}}``, structure
    identique a celle produite historiquement par les deux rollers.

    Ordre des des (stable, verrouille par les tests) : par attaque, touche -> [reroll touche]
    -> blessure -> [reroll blessure] -> sauvegarde -> [reroll sauvegarde].
    """
    shot_records: List[Dict[str, Any]] = []
    pending_wounds: List[Dict[str, Any]] = []
    attacks = hits = wounds = 0

    for _ in range(int(n_attacks)):
        attacks += 1
        if profile.torrent:
            # [TORRENT] 24.37 : l attaque touche automatiquement. Aucun de n est jete (donc
            # aucune touche critique : un auto-hit n est pas un « unmodified 6 »).
            hit_roll: Optional[int] = None
            is_critical_hit = False
        else:
            hit_roll = roll_d6()
            if hit_roll == NATURAL_FAIL_ROLL and rerolls.hit_1:
                hit_roll = roll_d6()
            is_critical_hit = hit_roll >= profile.crit_hit_on
            # 05.01 : 1 non modifie = echec ; critique = touche quoi qu il arrive.
            if not is_critical_hit and (hit_roll == NATURAL_FAIL_ROLL or hit_roll < hit_target):
                shot_records.append({
                    "attackRoll": hit_roll, "hitResult": "MISS", "hitTarget": hit_target,
                })
                continue

        # [SUSTAINED HITS X] 24.36 : une touche critique produit X touches ADDITIONNELLES.
        # Ces touches supplementaires ne sont pas des attaques : pas de jet de touche, donc
        # jamais critiques (elles ne peuvent pas redeclencher SUSTAINED ni LETHAL).
        extra_hits = profile.sustained_hits if is_critical_hit else 0
        for hit_index in range(1 + extra_hits):
            hits += 1
            critical_hit_here = is_critical_hit and hit_index == 0
            sustained_hit = hit_index > 0
            base_rec: Dict[str, Any] = {
                "attackRoll": None if (profile.torrent or sustained_hit) else hit_roll,
                "hitResult": "HIT",
                "hitTarget": None if profile.torrent else hit_target,
            }
            if profile.torrent:
                base_rec["autoHit"] = True
            if sustained_hit:
                base_rec["sustainedHit"] = True
            if critical_hit_here:
                base_rec["criticalHit"] = True

            auto_wound = (
                profile.lethal_hits and critical_hit_here
                and lethal_hits_auto_wound_is_better(profile, wound_target, save_threshold_value)
            )
            if auto_wound:
                # [LETHAL HITS] 24.23 : blessure automatique, AUCUN jet de blessure -> aucune
                # blessure critique possible (donc pas de DEVASTATING sur cette attaque).
                wound_roll: Optional[int] = None
                wound_success = True
                is_critical_wound = False
            else:
                wound_roll = roll_d6()
                is_critical_wound = wound_roll >= profile.crit_wound_on
                wound_success = is_critical_wound or (
                    wound_roll != NATURAL_FAIL_ROLL and wound_roll >= wound_target
                )
                # Un seul reroll par de : abilites d unite OU [TWIN-LINKED] 24.38, jamais les
                # deux. TWIN-LINKED relance les ECHECS seulement (relancer une blessure reussie
                # pour chercher un critique est perdant des que le seuil de blessure est >= 4+).
                may_reroll = (
                    (wound_roll == NATURAL_FAIL_ROLL and rerolls.wound_1)
                    or rerolls.wound_any_fail
                    or profile.twin_linked
                )
                if not wound_success and may_reroll:
                    wound_roll = roll_d6()
                    is_critical_wound = wound_roll >= profile.crit_wound_on
                    wound_success = is_critical_wound or (
                        wound_roll != NATURAL_FAIL_ROLL and wound_roll >= wound_target
                    )

            if not wound_success:
                base_rec.update({
                    "strengthRoll": wound_roll, "strengthResult": "FAILED",
                    "woundTarget": wound_target,
                })
                shot_records.append(base_rec)
                continue

            wounds += 1
            save_roll = roll_d6()
            if save_roll == NATURAL_FAIL_ROLL and rerolls.save_1:
                save_roll = roll_d6()
            base_rec.update({
                "strengthRoll": wound_roll, "strengthResult": "SUCCESS",
                "woundTarget": wound_target, "saveRoll": save_roll, "damageDealt": 0,
            })
            if auto_wound:
                base_rec["lethalHit"] = True
            # [DEVASTATING WOUNDS] 24.10 : la sequence de CETTE attaque s arrete sur une
            # blessure critique ; la cible subit D blessures mortelles, infligees APRES les
            # degats normaux (ordonnancement fait par l appelant a l allocation).
            devastating = bool(profile.devastating and is_critical_wound)
            if is_critical_wound:
                base_rec["criticalWound"] = True
            if devastating:
                base_rec["devastating"] = True
            shot_records.append(base_rec)
            pending_wounds.append({
                "save_roll": save_roll, "rec": base_rec, "devastating": devastating,
            })

    return {
        "shot_records": shot_records,
        "pending_wounds": pending_wounds,
        "counts": {"attacks": attacks, "hits": hits, "wounds": wounds},
    }


def count_selected_hazardous_weapons(
    weapons_by_model: Sequence[Sequence[Dict[str, Any]]],
) -> int:
    """[HAZARDOUS] 24.15 : nombre de jets de hasard = nombre d armes HAZARDOUS SELECTIONNEES
    dans l etape Select Weapons (04.01), toutes figurines de l unite confondues.

    `weapons_by_model` : une entree par figurine ayant tire/combattu, contenant les armes
    qu elle a effectivement selectionnees.
    """
    total = 0
    for weapons in weapons_by_model:
        for weapon in weapons:
            if weapon is None:
                continue
            if weapon_has_rule(weapon, "HAZARDOUS"):
                total += 1
    return total


def require_weapon_rules(weapon: Dict[str, Any]) -> List[Any]:
    """Acces strict a WEAPON_RULES (aucun repli) — utilitaire pour les appelants."""
    return require_key(weapon, "WEAPON_RULES")
