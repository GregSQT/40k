// frontend/src/roster/spaceMarine/units/Terminator.ts

import { getWeapons } from "../armory";
import { SpaceMarineInfantryEliteMeleeElite } from "../classes/SpaceMarineInfantryEliteMeleeElite";

export class Terminator extends SpaceMarineInfantryEliteMeleeElite {
  static NAME = "Terminator";
  static DISPLAY_NAME = "Terminator";

  // BASE
  static MOVE = 5; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 80; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["storm_bolter"];
  static RNG_WEAPONS = getWeapons(Terminator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist_terminator"];
  static CC_WEAPONS = getWeapons(Terminator.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Elite"; // MeleeElite specialist - hunt elite targets

  static ICON = "/icons/Terminator.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Terminator.HP_MAX, startPos);
  }
}
