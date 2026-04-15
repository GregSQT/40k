// frontend/src/roster/spaceMarine/units/DeathwingTerminatorPlasmaCannon.ts

import { getWeapons } from "../armory.ts";
import { EliteRangeElite } from "../classes/EliteRangeElite.ts";

export class DreadnoughtBallistus extends EliteRangeElite {
  static NAME = "DreadnoughtBallistus";
  static DISPLAY_NAME = "Dreadnought Ballistus";

  // BASE
  static MOVE = 8; // Move distance
  static T = 10; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 12; // Max hit points
  static LD = 6; // Leadership score
  static OC = 4; // Operative Control
  static VALUE = 160; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["ballistus_missile_launcher_frag", "ballistus_missile_launcher_krak", "ballistus_lascannon", "twin_storm_bolter"];
  static RNG_WEAPONS = getWeapons(DreadnoughtBallistus.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["redemptor_fist"];
  static CC_WEAPONS = getWeapons(DreadnoughtBallistus.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "vehicle"}, { keywordId: "walker"}, { keywordId: "imperium"}, { keywordId: "dreadnought"}, { keywordId: "ballistus dreadnought"}];
 

  static ICON = "/icons/DreadnoughtBallistus.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 35; // Size of the base
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, DreadnoughtBallistus.HP_MAX, startPos);
  }
}
