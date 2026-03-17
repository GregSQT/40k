// frontend/src/roster/spaceMarine/units/HellblasterSergeant.ts
//

import { getWeapons } from "../armory.ts";
import { TroopRangeElite } from "../classes/TroopRangeElite.ts";

export class HellblasterSergeant extends TroopRangeElite {
  static NAME = "HellblasterSergeant";
  static DISPLAY_NAME = "Hellblaster (Sergeant)";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 26; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["plasma_incinerator_standard", "plasma_incineratorl_supercharge", "plasma_pistol_standard", "plasma_pistol_supercharge"];
  static RNG_WEAPONS = getWeapons(HellblasterSergeant.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(HellblasterSergeant.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
  ];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "hellblaster squad"}];

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Elite"; // RangedElite specialist - bolt rifles vs hordes

  static ICON = "/icons/HellblasterSergeant.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, HellblasterSergeant.HP_MAX, startPos);
  }
}
