// frontend/src/roster/spaceMarine/units/GreyHunter.ts
//

import { getWeapons } from "../armory";
import { TroopRangeSwarm } from "../classes/TroopRangeSwarm";

export class GreyHunter extends TroopRangeSwarm {
  static NAME = "GreyHunter";
  static DISPLAY_NAME = "Grey Hunter";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 16; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["boltgun", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(GreyHunter.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["astartes_chainsword"];
  static CC_WEAPONS = getWeapons(GreyHunter.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    {
      ruleId: "cunning_hunters",
      displayName: "Cunning Hunters",
      grants_rule_ids: [
        "cunning_hunters_shoot_after_advance",
        "cunning_hunters_shoot_after_flee",
      ],
      usage: "and",
    },
  ];
  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = {
    cunning_hunters: 2,
    cunning_hunters_shoot_after_advance: 2,
    cunning_hunters_shoot_after_flee: 2,
  };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "grey hunters"}];

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Swarm"; // RangedSwarm specialist - bolt rifles vs hordes

  static ICON = "/icons/GreyHunter.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, GreyHunter.HP_MAX, startPos);
  }
}
