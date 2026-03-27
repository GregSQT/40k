// frontend/src/roster/spaceMarine/units/DeathwingTerminatorPlasmaCannon.ts

import { getWeapons } from "../armory";
import { EliteRangeElite } from "../classes/EliteRangeElite.ts";

export class DeathwingTerminatorPlasmaCannon extends EliteRangeElite {
  static NAME = "DeathwingTerminatorPlasmaCannon";
  static DISPLAY_NAME = "Deathwing Terminator (Plasma Cannon)";

  // BASE
  static MOVE = 5; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 38; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["plasma_cannon_standard", "plasma_cannon_supercharge"];
  static RNG_WEAPONS = getWeapons(DeathwingTerminatorPlasmaCannon.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(DeathwingTerminatorPlasmaCannon.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "terminator"}, { keywordId: "deathwing"}, { keywordId: "deathwing terminator squad"}];
 

  static ICON = "/icons/DeathwingTerminatorPlasmaCannon.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, DeathwingTerminatorPlasmaCannon.HP_MAX, startPos);
  }
}
