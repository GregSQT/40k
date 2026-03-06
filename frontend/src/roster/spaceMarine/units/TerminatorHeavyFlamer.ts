// frontend/src/roster/spaceMarine/units/TerminatorHeavyFlamer.ts

import { getWeapons } from "../armory";
import { SpaceMarineInfantryEliteRangedTroop } from "../classes/SpaceMarineInfantryEliteRangedTroop";

export class TerminatorHeavyFlamer extends SpaceMarineInfantryEliteRangedTroop {
  static NAME = "TerminatorHeavyFlamer";
  static DISPLAY_NAME = "Terminator (Assault Cannon)";

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
  static RNG_WEAPON_CODES = ["heavy_flamer"];
  static RNG_WEAPONS = getWeapons(TerminatorHeavyFlamer.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(TerminatorHeavyFlamer.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "terminator"}, { keywordId: "terminator squad"}];
 
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Swarm"; // RangedSwarm specialist - anti-infantry

  static ICON = "/icons/TerminatorHeavyFlamer.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, TerminatorHeavyFlamer.HP_MAX, startPos);
  }
}
