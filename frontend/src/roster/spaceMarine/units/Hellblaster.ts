// frontend/src/roster/spaceMarine/units/GreyHunter.ts
//

import { getWeapons } from "../armory.ts";
import { SpaceMarineInfantryTroopRangedElite } from "../classes/SpaceMarineInfantryTroopRangedElite.ts";

export class Hellblaster extends SpaceMarineInfantryTroopRangedElite {
  static NAME = "Hellblaster";
  static DISPLAY_NAME = "Hellblaster";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 21; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["plasma_incinerator_standard", "plasma_incineratorl_supercharge", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(Hellblaster.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(Hellblaster.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
  ];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "hellblaster squad"}];

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Elite"; // RangedElite specialist - bolt rifles vs hordes

  static ICON = "/icons/Hellblaster.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Hellblaster.HP_MAX, startPos);
  }
}
