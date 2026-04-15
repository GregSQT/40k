// frontend/src/roster/spaceMarine/units/GuardianDefender.ts

import { getWeapons } from "../armory";
import { SwarmRangeTroop } from "../classes/SwarmRangeTroop";

export class GuardianDefender extends SwarmRangeTroop {
  static NAME = "GuardianDefender";
  static DISPLAY_NAME = "Aggressor (Bolt Storm)";

  // BASE
  static MOVE = 7; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 7; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 10; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["shuriken_catapult"];
  static RNG_WEAPONS = getWeapons(GuardianDefender.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(GuardianDefender.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "guardians"}, { keywordId: "guardian defenders"}];
  

  static ICON = "/icons/GuardianDefender.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 11; // Size of the base
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, GuardianDefender.HP_MAX, startPos);
  }
}
