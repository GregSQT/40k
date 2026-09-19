// frontend/src/utils/replayShotDetails.ts
import type { ShootDetail } from "../../../shared/gameLogStructure.ts";
import type { ReplayAction } from "./replayParser";

/**
 * Projection d'une action de replay (issue de `step.log` par `replayParser`) vers le détail
 * par-attaque que le Game Log affiche — le MÊME `ShootDetail` que le moteur envoie au navigateur
 * en PvP.
 *
 * Deux fabriques et un seul fichier : le tir et la mêlée ne décrivent pas les mêmes dés (le tir
 * recalcule ses résultats depuis les seuils, la mêlée les lit dans la ligne), mais ils
 * remplissent le même contrat et divergeaient silencieusement — les littérales vivaient dans
 * `BoardReplay.tsx` sans type, si bien qu'une valeur étrangère au contrat (`"WOUND"` là où
 * `ShootDetail` n'admet que `"SUCCESS"` / `"FAILED"`) y passait inaperçue et faisait sauter toute
 * la section sauvegarde/dégâts de la ligne de mêlée. Le type est désormais porté ici.
 */

/** Ligne de TIR : `undefined` quand la ligne ne porte aucun jet de touche — il n'y a alors aucun
 *  détail à déplier (`[TORRENT]`, touche de `[SUSTAINED HITS]` : `Hit None(T+)` n'est pas lu). */
export function shootShotDetail(action: ReplayAction): ShootDetail | undefined {
  const hitRoll = action.hit_roll;
  if (hitRoll === undefined) {
    return undefined;
  }
  const woundRoll = action.wound_roll;
  const saveRoll = action.save_roll;
  const saveTarget = action.save_target || 0;
  const hitTarget = action.hit_target || 3;
  const woundTarget = action.wound_target || 4;
  return {
    shotNumber: 1,
    attackRoll: hitRoll,
    strengthRoll: woundRoll || 0,
    hitResult: hitRoll >= hitTarget ? "HIT" : "MISS",
    strengthResult: woundRoll && woundRoll >= woundTarget ? "SUCCESS" : "FAILED",
    saveRoll: saveRoll,
    saveTarget: saveTarget,
    saveSuccess: saveRoll !== undefined && saveTarget > 0 ? saveRoll >= saveTarget : false,
    damageDealt: action.damage || 0,
    // Capacités nommées : mêmes champs que le PvP reçoit du moteur, extraits des tokens de la
    // ligne par le parseur. Sans eux, le détail déplié du replay reste muet là où le PvP
    // affiche « [OATH OF MOMENT] ».
    hitAbility: action.hit_ability,
    woundAbility: action.wound_ability,
    woundBonusAbility: action.wound_bonus_ability,
    // Règles d'ARME par-dé. Le replay n'en voit que ce que `step.log` écrit ET que le parseur
    // atteint : la relance [TWIN-LINKED] et la sauvegarde sautée de [DEVASTATING WOUNDS].
    // [SUSTAINED HITS] et [TORRENT] produisent `Hit None(T+)`, que le parseur ne reconnaît pas —
    // la ligne n'a alors AUCUN détail déplié, donc aucun champ à remplir. ⚠️ [LETHAL HITS] EST
    // écrit dans step.log depuis le 2026-08-12 (`Wound None(T+) [LETHAL HITS]`), mais il bute sur
    // le MÊME mécanisme côté blessure. Seules les CRITIQUES ne sont écrites nulle part. Voir le
    // rapport de parité de Documentation/Reference/jeu/armes.md.
    woundRerollRule: action.wound_reroll_rule,
    devastating: action.devastating_wounds_applied,
    // Dé d'origine d'un jet relancé : le détail affiche « 1->3 », comme en PvP.
    attackRollInitial: action.hit_roll_initial,
    strengthRollInitial: action.wound_roll_initial,
    saveRollInitial: action.save_roll_initial,
    // Feel No Pain 24.12 : les trois champs que le PvP reçoit du moteur, lus ici dans le token du
    // journal. Sans eux, la ligne montrait les dégâts APRÈS FNP sans dire qu'un dé avait été jeté.
    fnpSaves: action.fnp_saves,
    fnpAttempts: action.fnp_attempts,
    fnpThreshold: action.fnp_threshold,
  };
}

/** Ligne de MÊLÉE : JUMEAU de `shootShotDetail`, au seul écart que la ligne impose.
 *
 *  Les résultats sont LUS (`hit_result` / `wound_result`) et non recalculés — mais le
 *  vocabulaire du journal (`"WOUND"` / `"FAIL"`) n'est pas celui du contrat d'affichage
 *  (`"SUCCESS"` / `"FAILED"`) : la traduction est faite ici, et son absence rendait
 *  `Bless: ✗` sur une blessure réussie puis sautait la sauvegarde, les dégâts et le marqueur
 *  Feel No Pain de TOUTE ligne de mêlée. */
export function fightShotDetail(action: ReplayAction): ShootDetail | undefined {
  if (action.hit_roll === undefined) {
    return undefined;
  }
  return {
    shotNumber: 1,
    attackRoll: action.hit_roll,
    strengthRoll: action.wound_roll || 0,
    hitResult: action.hit_result === "HIT" ? "HIT" : "MISS",
    strengthResult: action.wound_result === "WOUND" ? "SUCCESS" : "FAILED",
    saveRoll: action.save_roll,
    saveTarget: action.save_target,
    saveSuccess:
      action.save_roll !== undefined && action.save_target
        ? action.save_roll >= action.save_target
        : false,
    damageDealt: action.damage || 0,
    // JUMEAU du tir ci-dessus : la mêlée nomme les mêmes capacités et les mêmes règles d'arme
    // par-dé (le socle de résolution est partagé).
    hitAbility: action.hit_ability,
    woundAbility: action.wound_ability,
    woundBonusAbility: action.wound_bonus_ability,
    woundRerollRule: action.wound_reroll_rule,
    // 24.10 : le parseur pose `devastating_wounds_applied` sur les DEUX branches (`Save
    // [DEVASTATING WOUNDS]` est écrit par un site unique côté moteur). Sans ce report, la ligne
    // de mêlée affichait ses dégâts sans jamais nommer la règle qui avait arrêté la séquence.
    devastating: action.devastating_wounds_applied,
    attackRollInitial: action.hit_roll_initial,
    strengthRollInitial: action.wound_roll_initial,
    saveRollInitial: action.save_roll_initial,
    fnpSaves: action.fnp_saves,
    fnpAttempts: action.fnp_attempts,
    fnpThreshold: action.fnp_threshold,
  };
}
