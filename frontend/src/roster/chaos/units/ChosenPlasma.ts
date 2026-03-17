// frontend/src/roster/tyranid/units/Carnifex.ts

import { getWeapons } from "../armory";
import { TroopRangedTroop } from "../classes/TroopRangedTroop";

export class ChosenPlasma extends TroopRangedTroop {
  static NAME = "ChosenPlasma";
  static DISPLAY_NAME = "ChosenPlasma";
  // BASE
  static MOVE = 6; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 6; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 7; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 5; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["plasma_pistol_standard", "plasma_pistol_supercharge"];
  static RNG_WEAPONS = getWeapons(ChosenPlasma.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(ChosenPlasma.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "grenades"}, { keywordId: "chaos"}, { keywordId: "chosen"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Monster movement (treated as infantry)
  static TARGET_TYPE = "Troop"; // RangedTroop specialist - bolt rifles vs hordes

  static ICON = "/icons/ChosenPlasma.webp"; // Path relative to public folder
  static ICON_SCALE = 1.5; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, ChosenPlasma.HP_MAX, startPos);
  }
}
