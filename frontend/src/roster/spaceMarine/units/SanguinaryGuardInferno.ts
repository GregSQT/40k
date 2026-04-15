// frontend/src/roster/spaceMarine/units/SanguinaryGuardInferno.ts

import { getWeapons } from "../armory";
import { TroopMeleeTroop } from "../classes/TroopMeleeTroop";

export class SanguinaryGuardInferno extends TroopMeleeTroop {
  static NAME = "SanguinaryGuardInferno";
  static DISPLAY_NAME = "Sanguinary Guard (Inferno Pistol)";
  // BASE
  static MOVE = 12; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 50; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["inferno_pistol"];
  static RNG_WEAPONS = getWeapons(SanguinaryGuardInferno.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["encarmine_blade"];
  static CC_WEAPONS = getWeapons(SanguinaryGuardInferno.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "grenades"}, { keywordId: "jump_pack"}, { keywordId: "fly"}, { keywordId: "imperium"}, { keywordId: "sanguinary guard"}];


  static ICON = "/icons/SanguinaryGuardInferno.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, SanguinaryGuardInferno.HP_MAX, startPos);
  }
}
