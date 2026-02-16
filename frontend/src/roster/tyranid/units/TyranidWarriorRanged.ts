// frontend/src/roster/tyranid/units/TyranidWarriorRanged.ts
//

import { getWeapons } from "../armory";
import { TyranidInfantryTroopRangedTroop } from "../classes/TyranidInfantryTroopRangedTroop";

export class TyranidWarriorRanged extends TyranidInfantryTroopRangedTroop {
  static NAME = "Tyranid Warrior Ranged";
  // BASE
  static MOVE = 6; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 7; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 24; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["deathspitter"];
  static RNG_WEAPONS = getWeapons(TyranidWarriorRanged.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["rending_claws_warrior"];
  static CC_WEAPONS = getWeapons(TyranidWarriorRanged.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 3 wounds, 4+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // RangedTroop specialist - anti-infantry

  // UNIT RULES
  static UNIT_RULES = [
    {
      ruleId: "adaptable_predators",
      displayName: "Adaptable Predators",
      grants_rule_ids: ["shoot_after_flee", "charge_after_flee"],
    },
  ];

  // ICON
  static ICON = "/icons/WarriorRanged.webp"; // Path relative to public folder
  static ICON_SCALE = 2.2; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, TyranidWarriorRanged.HP_MAX, startPos);
  }
}
