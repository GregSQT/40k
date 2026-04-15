// frontend/src/roster/spaceMarine/units/BloodClawPackLeader.ts

import { getWeapons } from "../armory";
import { TroopMeleeTroop } from "../classes/TroopMeleeTroop";

export class BloodClawPackLeader extends TroopMeleeTroop {
  static NAME = "BloodClawPackLeader";
  static DISPLAY_NAME = "Blood Claw (Pack Leader)";
  // BASE
  static MOVE = 7; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 18; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["plasma_pistol_standard", "plasma_pistol_supercharge"];
  static RNG_WEAPONS = getWeapons(BloodClawPackLeader.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_weapon_pack_leader"];
  static CC_WEAPONS = getWeapons(BloodClawPackLeader.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    {
      ruleId: "charge_after_advance",
      displayName: "Berserk Charge",
    },
  ];
  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { charge_after_advance: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "bloodclaws"}];


  static ICON = "/icons/BloodClawPackLeader.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 13; // Size of the base
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, BloodClawPackLeader.HP_MAX, startPos);
  }
}
