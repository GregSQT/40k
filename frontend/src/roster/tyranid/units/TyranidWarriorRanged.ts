// frontend/src/roster/tyranid/units/TyranidWarriorRanged.ts
//

import { getWeapons } from "../armory";
import { TroopRangeTroop } from "../classes/TroopRangeTroop";

export class TyranidWarriorRanged extends TroopRangeTroop {
  static NAME = "TyranidWarriorRanged";
  static DISPLAY_NAME = "Tyranid Warrior (Ranged)";
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
  static CC_WEAPON_CODES = ["rending_claws"];
  static CC_WEAPONS = getWeapons(TyranidWarriorRanged.CC_WEAPON_CODES);


  // UNIT RULES
  static UNIT_RULES = [
    {
      ruleId: "adaptable_predators",
      displayName: "Adaptable Predators",
      grants_rule_ids: [
        "adaptable_predators_shoot_after_flee",
        "adaptable_predators_charge_after_flee",
      ],
      usage: "and",
    },
  ];
  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = {
    adaptable_predators: 2,
    adaptable_predators_shoot_after_flee: 2,
    adaptable_predators_charge_after_flee: 2,
  };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "great devourer"}, { keywordId: "synapse"}, { keywordId: "tyranids"}, { keywordId: "tyranid warrior with ranged bio-weapon"}];

  // ICON
  static ICON = "/icons/TyranidWarriorRanged.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 20; // Size of the base
  static ICON_SCALE = 2.2; // Size of the icon
  static ILLUSTRATION_RATIO = 120; // Illustration size ratio in percent
  
  constructor(name: string, startPos: [number, number]) {
    super(name, TyranidWarriorRanged.HP_MAX, startPos);
  }
}
