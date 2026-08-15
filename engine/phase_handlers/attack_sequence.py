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
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from shared.data_validation import require_key
from engine.utils.weapon_helpers import weapon_has_rule, weapon_rule_parameter
from engine.weapons.rules import MIN_ANTI_THRESHOLD


# 05.01 / 05.02 : un jet NON MODIFIE de 6 est critique, un jet non modifie de 1 echoue toujours.
CRITICAL_HIT_ROLL = 6
NATURAL_CRITICAL_WOUND_ROLL = 6
NATURAL_FAIL_ROLL = 1

# [ANTI-X Y+] 24.03 — familles supportees par les armories du projet. Le suffixe apres `ANTI_`
# est le KEYWORD que la cible doit avoir pour que la regle s applique.
ANTI_RULE_PREFIX = "ANTI_"
ANTI_RULE_IDS = ("ANTI_INFANTRY", "ANTI_VEHICLE", "ANTI_FLY", "ANTI_PSYKER", "ANTI_MONSTER")

#: 05.02 : `MIN_ANTI_THRESHOLD` vaut `NATURAL_FAIL_ROLL + 1` — la meme regle, dite deux fois si on
#: la reecrivait ici. Elle est DEFINIE avec la grammaire de declaration (`engine/weapons/rules`),
#: qui la fait respecter au chargement de l armurerie, et importee ici pour que la resolution et
#: le chargement ne puissent pas diverger.
assert MIN_ANTI_THRESHOLD == NATURAL_FAIL_ROLL + 1


def anti_threshold_of(weapon: Dict[str, Any], rule_id: str) -> int:
    """Seuil Y+ DECLARE par l instance `rule_id` de [ANTI-X Y+] 24.03, valide en DOMAINE.

    SEUL point de lecture du parametre Y d une regle [ANTI], pour les deux chemins qui en ont
    besoin : la resolution d attaque (`_anti_crit_wound_threshold`) et l observation
    (`observation_weapon_profiles.anti_rule_of`).

    DEUXIEME barriere, pas la premiere : `parse_weapon_rule` refuse deja le domaine au
    CHARGEMENT de l armurerie. Celle-ci couvre les dicts d arme qui n en viennent pas (charge
    API, fixtures), et elle est la derniere avant l usage.

    Ce qui ne peut PLUS etre la seule barriere : `ai/step_logger._anti_rule_token`. Il refuse le
    meme domaine, mais s execute dans `StepLogger.log_action`, dont le `except Exception` global
    transforme le refus en ligne MANQUANTE — une armurerie declarant `ANTI_INFANTRY:1` faisait
    disparaitre du step.log toutes les attaques de cette arme, sans `parse_errors` cote analyzer
    puisque la ligne n avait jamais existe.
    """
    threshold = weapon_rule_parameter(weapon, rule_id)
    if threshold is None:
        raise ValueError(
            f"[ANTI] rule {rule_id!r} sans parametre Y+ sur l arme "
            f"{weapon.get('display_name', weapon.get('NAME'))!r}"
        )
    if threshold < MIN_ANTI_THRESHOLD:
        raise ValueError(
            f"[ANTI] rule {rule_id!r}: seuil Y+ declare {threshold}, minimum "
            f"{MIN_ANTI_THRESHOLD} (05.02) — arme "
            f"{weapon.get('display_name', weapon.get('NAME'))!r}"
        )
    return threshold


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
    #: KEYWORD de l instance de [ANTI-X Y+] 24.03 qui s applique REELLEMENT a cette cible
    #: (None si l arme n en porte pas, ou si la cible n a aucun des keywords vises). Le seuil
    #: est deja dans `crit_wound_on` ; ce champ ne sert qu a NOMMER la regle dans le log —
    #: sans lui, le seuil de blessure critique change sans que rien ne dise pourquoi. Il est
    #: pose ici, et non recalcule par le log, pour qu il n existe qu UNE resolution de [ANTI].
    anti_keyword: Optional[str] = None
    #: Seuil Y+ DECLARE par cette instance de [ANTI-X Y+], AVANT le clamp de 05.02 que subit
    #: `crit_wound_on`. Les deux coincident pour tout Y+ valide (2..6) ; ils divergent sur une
    #: armurerie fautive (Y=7), et c est precisement ce cas que le journal doit rendre
    #: verifiable. Un log qui n ecrit que `crit_wound_on` fait controler le moteur avec le
    #: chiffre du moteur : le lecteur ne peut plus recouper le seuil avec la datasheet.
    anti_threshold: Optional[int] = None

    def __post_init__(self) -> None:
        # Les deux champs [ANTI] sont UN SEUL fait (l instance retenue par 24.02) : ils sont
        # poses ensemble par `build_weapon_attack_profile`. Un profil qui n en porte qu un est
        # une corruption, pas un cas a gerer — le log ecrirait `[ANTI-INFANTRY:None+]`, une
        # valeur par defaut deguisee en donnee (T1).
        if (self.anti_keyword is None) != (self.anti_threshold is None):
            raise ValueError(
                "WeaponAttackProfile: anti_keyword et anti_threshold vont ensemble, "
                f"got keyword={self.anti_keyword!r}, threshold={self.anti_threshold!r}"
            )


@dataclass(frozen=True)
class RerollProfile:
    """Rerolls d ABILITES (unite), independants des regles d arme. Un de ne se relance
    qu une fois (PDF 01 Core, Re-rolls) : ce module ne relance jamais deux fois le meme de."""

    hit_1: bool = False
    #: « You can re-roll the Hit roll » (Oath of Moment) — relance de TOUT jet de touche raté,
    #: pas seulement des 1. Jumeau exact de `wound_any_fail` côté blessure, et construit sur le
    #: même patron : relance des ÉCHECS seulement, un seul dé de relance, priorité explicite
    #: entre les causes, `hitRerollCause` au record.
    #:
    #: Relancer une touche RÉUSSIE pour chercher un critique serait perdant (on échangerait une
    #: touche acquise contre P(touche)), et la règle dit « re-roll the Hit roll » dans le cadre
    #: 01 Core « Re-rolls », qui ne s'applique qu'à un jet dont on veut changer le résultat.
    hit_any_fail: bool = False
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


def _anti_crit_wound_threshold(
    weapon: Dict[str, Any], target_keywords: frozenset
) -> Optional[Tuple[int, str]]:
    """Seuil de blessure critique impose par [ANTI-X Y+] 24.03 ET son keyword, ou None.

    24.02 (Duplicated abilities) : plusieurs [ANTI] sur la meme arme ne se cumulent pas ; le
    joueur choisit l instance qui s applique. Choix optimal et deterministe retenu : le seuil
    le PLUS BAS parmi les instances dont le keyword X est porte par la cible.

    Le KEYWORD est rendu avec le seuil (et non deduit ailleurs) parce que le log doit nommer
    l instance retenue : une arme [ANTI-INFANTRY 4+][ANTI-VEHICLE 2+] tirant sur un vehicule
    n a qu UNE regle applicable, et c est cette boucle-ci qui sait laquelle.
    """
    best: Optional[Tuple[int, str]] = None
    for rule_id in ANTI_RULE_IDS:
        if not weapon_has_rule(weapon, rule_id):
            continue
        keyword = rule_id[len(ANTI_RULE_PREFIX):]
        if keyword not in target_keywords:
            continue
        threshold = anti_threshold_of(weapon, rule_id)
        if best is None or threshold < best[0]:
            best = (threshold, keyword)
    return best


def build_weapon_attack_profile(
    weapon: Dict[str, Any], target_unit: Optional[Dict[str, Any]],
) -> WeaponAttackProfile:
    """Profil de regles d arme pour un intent (arme fixee, unite cible fixee)."""
    anti = _anti_crit_wound_threshold(weapon, unit_keywords_upper(target_unit))
    crit_wound_on = (
        NATURAL_CRITICAL_WOUND_ROLL if anti is None
        else min(NATURAL_CRITICAL_WOUND_ROLL, anti[0])
    )
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
        anti_keyword=None if anti is None else anti[1],
        anti_threshold=None if anti is None else anti[0],
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


def expected_damage_per_attack(
    profile: WeaponAttackProfile,
    *,
    hit_target: int,
    wound_target: int,
    save_threshold_value: int,
    damage: float,
) -> float:
    """Espérance de dégâts d'UNE attaque, RÈGLES D'ARME COMPRISES.

    Source unique de l'espérance de dégâts « consciente des règles ». Elle vit ici, à côté de
    la boucle de résolution qu'elle modélise (`roll_attack_pool`) et de
    `lethal_hits_auto_wound_is_better`, pour qu'il n'existe pas une seconde définition qui
    dériverait — c'est la raison d'être du socle commun (§9.2.3).

    Comptage par FACES, jamais de formule fermée : mêmes prédicats que la résolution (05.01 un
    1 non modifié rate toujours ; 05.04 une sauvegarde de 1 échoue toujours), donc aucun écart
    possible entre ce que l'heuristique croit et ce que le moteur jouera.

    Règles modélisées : [TORRENT] (touche automatique, donc AUCUNE touche critique — pas de
    hit roll), [SUSTAINED HITS X], [LETHAL HITS] (avec l'arbitrage exact de
    `lethal_hits_auto_wound_is_better`), [TWIN-LINKED] (relance d'une blessure ratée, une seule
    fois), [DEVASTATING WOUNDS] (blessure critique non sauvegardable), [ANTI-X Y+] (déjà porté
    par `profile.crit_wound_on`).

    NON modélisées, volontairement : les règles qui agissent sur la TAILLE DU POOL d'attaques
    ([BLAST], [CLEAVE], [RAPID FIRE], [EXTRA ATTACKS]) — elles multiplient le nombre d'attaques,
    pas la valeur d'une attaque, et l'appelant les applique au niveau du pool ; et celles qui
    agissent sur l'ALLOCATION ([PRECISION]), qui ne change pas l'espérance de dégâts brute.
    """
    faces = range(1, 7)
    p_fail_save = sum(
        1 for f in faces if f == NATURAL_FAIL_ROLL or f < int(save_threshold_value)
    ) / 6.0

    p_crit_wound = sum(1 for f in faces if f >= profile.crit_wound_on) / 6.0
    p_normal_wound = sum(
        1 for f in faces
        if f != NATURAL_FAIL_ROLL and f >= int(wound_target) and f < profile.crit_wound_on
    ) / 6.0
    ev_wound_once = (
        p_crit_wound * (1.0 if profile.devastating else p_fail_save)
        + p_normal_wound * p_fail_save
    )
    ev_wound = ev_wound_once
    if profile.twin_linked:
        # 24.38 : relance d'un jet de blessure raté — une seule fois (01 Core, Re-rolls).
        ev_wound += (1.0 - p_crit_wound - p_normal_wound) * ev_wound_once

    if profile.torrent:
        # 24.37 : « does not make hit rolls » -> touche automatique, et donc aucune touche
        # critique : [SUSTAINED HITS] et [LETHAL HITS] ne se déclenchent pas.
        return ev_wound * float(damage)

    p_crit_hit = sum(1 for f in faces if f >= profile.crit_hit_on) / 6.0
    p_normal_hit = sum(
        1 for f in faces
        if f != NATURAL_FAIL_ROLL and f >= int(hit_target) and f < profile.crit_hit_on
    ) / 6.0

    ev_on_crit_hit = ev_wound
    if profile.lethal_hits and lethal_hits_auto_wound_is_better(
        profile, int(wound_target), int(save_threshold_value)
    ):
        ev_on_crit_hit = p_fail_save  # blessure automatique : plus de jet, donc plus de critique
    # [SUSTAINED HITS X] : X touches SUPPLÉMENTAIRES (normales) par touche critique.
    ev_on_crit_hit += profile.sustained_hits * ev_wound

    return (p_crit_hit * ev_on_crit_hit + p_normal_hit * ev_wound) * float(damage)


def _evaluate_roll(roll: int, crit_on: int, target: int) -> Tuple[bool, bool]:
    """Verdict d'UN de : `(critique, reussite)`. 05.01 — un 1 non modifie echoue toujours,
    un critique reussit toujours.

    Ecrit quatre fois a l'identique dans `roll_attack_pool` (touche et blessure, avant et apres
    relance) : c'est la forme ou les deux blocs de relance divergeaient le plus facilement du
    jet initial qu'ils recalculent.
    """
    is_critical = roll >= crit_on
    return is_critical, is_critical or (roll != NATURAL_FAIL_ROLL and roll >= target)


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
        # Declaree AVANT la branche [TORRENT] : une arme a touche automatique ne jette aucun de,
        # donc ne relance rien, et le record de touche plus bas lit cette variable dans les DEUX
        # branches. La laisser dans la seule branche « avec jet » la rendait non liee sur TORRENT.
        hit_reroll_cause: Optional[str] = None
        # Borne pour l'analyse statique, PAS pour la lecture : contrairement a
        # `hit_reroll_cause` (lu ligne ~350 dans la branche TORRENT), celui-ci n'est lu que sous
        # le garde de cause. INVARIANT tenu par construction et valable pour les trois des :
        # une cause de relance n'est jamais posee sans que le de d'origine le soit dans la meme
        # foulee, donc `*RollInitial` n'est jamais emis a None — la clef est absente ou entiere,
        # jamais `null` (cf. `shared/gameLogStructure.ts`, ou elle est `number?`).
        hit_roll_initial: Optional[int] = None
        if profile.torrent:
            # [TORRENT] 24.37 : l attaque touche automatiquement. Aucun de n est jete (donc
            # aucune touche critique : un auto-hit n est pas un « unmodified 6 »).
            hit_roll: Optional[int] = None
            is_critical_hit = False
        else:
            hit_roll = roll_d6()
            is_critical_hit, hit_success = _evaluate_roll(
                hit_roll, profile.crit_hit_on, hit_target
            )
            # Un seul reroll par de (01 Core, Re-rolls) : `hit_1` relance les seuls 1,
            # `hit_any_fail` (Oath of Moment) relance TOUT echec. Meme forme que la blessure
            # ci-dessous, priorite explicite comprise — sans quoi la cause enregistree ne serait
            # pas celle qui a ouvert la relance.
            if not hit_success and (
                (hit_roll == NATURAL_FAIL_ROLL and rerolls.hit_1) or rerolls.hit_any_fail
            ):
                hit_reroll_cause = (
                    "hit_1" if (hit_roll == NATURAL_FAIL_ROLL and rerolls.hit_1)
                    else "hit_any_fail"
                )
                # Jet AVANT relance, conserve : sans lui le log ne peut afficher que le second de
                # (« Hit 3 » sur un 1 relance), et le joueur ne voit pas ce que la relance a change.
                hit_roll_initial = hit_roll
                hit_roll = roll_d6()
                is_critical_hit, hit_success = _evaluate_roll(
                    hit_roll, profile.crit_hit_on, hit_target
                )
            # 05.01 : 1 non modifie = echec ; critique = touche quoi qu il arrive.
            if not hit_success:
                miss_rec: Dict[str, Any] = {
                    "attackRoll": hit_roll, "hitResult": "MISS", "hitTarget": hit_target,
                }
                if hit_reroll_cause is not None:
                    miss_rec["hitRerollCause"] = hit_reroll_cause
                    miss_rec["attackRollInitial"] = hit_roll_initial
                shot_records.append(miss_rec)
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
            # Cause de la relance de touche, quand il y en a eu une. Sur la touche RÉELLE
            # seulement : une touche [SUSTAINED HITS] n'a pas de jet, donc pas de relance.
            # Sans cette trace, le log dit que la relance était POSSIBLE, jamais qu'elle a EU
            # LIEU — et l'analyzer ne peut pas distinguer les deux (jumeau de `woundRerollCause`).
            if hit_reroll_cause is not None and not sustained_hit:
                base_rec["hitRerollCause"] = hit_reroll_cause
                base_rec["attackRollInitial"] = hit_roll_initial

            auto_wound = (
                profile.lethal_hits and critical_hit_here
                and lethal_hits_auto_wound_is_better(profile, wound_target, save_threshold_value)
            )
            # Cause de la relance de blessure, quand il y en a une : `wound_1` /
            # `wound_any_fail` (abilites d UNITE) ou `twin_linked` (regle d ARME). L appelant en
            # tire le nom d abilite affiche dans le log — sans cette trace, il sait seulement
            # que la relance etait POSSIBLE, jamais qu elle a EU LIEU. Cf. V11 §0hist.38.
            wound_reroll_cause: Optional[str] = None
            wound_roll_initial: Optional[int] = None
            if auto_wound:
                # [LETHAL HITS] 24.23 : blessure automatique, AUCUN jet de blessure -> aucune
                # blessure critique possible (donc pas de DEVASTATING sur cette attaque).
                wound_roll: Optional[int] = None
                wound_success = True
                is_critical_wound = False
            else:
                wound_roll = roll_d6()
                is_critical_wound, wound_success = _evaluate_roll(
                    wound_roll, profile.crit_wound_on, wound_target
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
                    # Meme ordre de priorite que `may_reroll` ci-dessus : le miroir exact, pour
                    # que la cause enregistree soit bien celle qui a ouvert la relance.
                    if wound_roll == NATURAL_FAIL_ROLL and rerolls.wound_1:
                        wound_reroll_cause = "wound_1"
                    elif rerolls.wound_any_fail:
                        wound_reroll_cause = "wound_any_fail"
                    else:
                        wound_reroll_cause = "twin_linked"
                    wound_roll_initial = wound_roll
                    wound_roll = roll_d6()
                    is_critical_wound, wound_success = _evaluate_roll(
                        wound_roll, profile.crit_wound_on, wound_target
                    )

            if wound_reroll_cause is not None:
                base_rec["woundRerollCause"] = wound_reroll_cause
                base_rec["strengthRollInitial"] = wound_roll_initial

            if not wound_success:
                base_rec.update({
                    "strengthRoll": wound_roll, "strengthResult": "FAILED",
                    "woundTarget": wound_target,
                })
                shot_records.append(base_rec)
                continue

            wounds += 1
            # [DEVASTATING WOUNDS] 24.10 : la sequence de CETTE attaque s arrete sur une
            # blessure critique ; la cible subit D blessures mortelles, infligees APRES les
            # degats normaux (ordonnancement fait par l appelant a l allocation).
            devastating = bool(profile.devastating and is_critical_wound)
            # « No saving throw can be MADE against a critical wound » : la sauvegarde n est
            # pas faite du tout — aucun de tire, aucune relance, aucun `saveRoll` au record.
            # Avant le 2026-07-29 le de etait tire PUIS jete : sans effet sur le jeu, mais il
            # laissait dans le record une valeur que le log affichait (`Save 6(2+)` sur une
            # blessure mortelle), ce que le controle de conformite de l analyzer classe en
            # `devastating_wounds_incorrect`. Cf. V11 §0hist.38.
            save_roll: Optional[int] = None
            save_roll_initial: Optional[int] = None
            if not devastating:
                save_roll = roll_d6()
                if save_roll == NATURAL_FAIL_ROLL and rerolls.save_1:
                    # Vaut TOUJOURS NATURAL_FAIL_ROLL — `save_1` ne relance que les 1, la ou la
                    # touche et la blessure relancent aussi des echecs quelconques. Conserve
                    # quand meme : la sauvegarde est la seule jambe SANS enum de cause (il n'y a
                    # qu'un declencheur), donc ce champ est le seul temoin de la relance.
                    save_roll_initial = save_roll
                    save_roll = roll_d6()
            base_rec.update({
                "strengthRoll": wound_roll, "strengthResult": "SUCCESS",
                "woundTarget": wound_target, "damageDealt": 0,
            })
            if not devastating:
                base_rec["saveRoll"] = save_roll
                if save_roll_initial is not None:
                    base_rec["saveRollInitial"] = save_roll_initial
            if auto_wound:
                base_rec["lethalHit"] = True
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
