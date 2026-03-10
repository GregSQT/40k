// frontend/src/roster/spaceMarine/units/TerminatorAssaultCannon.ts

import { getWeapons } from "../armory";
import { SpaceMarineInfantryEliteRangedTroop } from "../classes/SpaceMarineInfantryEliteRangedTroop";

export class EradicatorMeltaRifle extends SpaceMarineInfantryEliteRangedTroop {
  static NAME = "EradicatorMeltaRifle";
  static DISPLAY_NAME = "Eradicator (Melta Rifle)";

  // BASE
  static MOVE = 5; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 28; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["melta_rifle"];
  static RNG_WEAPONS = getWeapons(EradicatorMeltaRifle.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(EradicatorMeltaRifle.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "grenade"}, { keywordId: "imperium"}, { keywordId: "gravis"}, { keywordId: "eradicator squad"}];
 
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Elite"; // RangedElite specialist - hunt elite targets

  static ICON = "/icons/EradicatorMeltaRifle.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, EradicatorMeltaRifle.HP_MAX, startPos);
  }
}
