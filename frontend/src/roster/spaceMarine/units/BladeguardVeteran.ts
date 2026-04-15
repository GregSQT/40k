// frontend/src/roster/spaceMarine/units/BladeguardVeteran.ts

import { getWeapons } from "../armory";
import { TroopMeleeTroop } from "../classes/TroopMeleeTroop";

export class BladeguardVeteran extends TroopMeleeTroop {
  static NAME = "BladeguardVeteran";
  static DISPLAY_NAME = "Bladeguard Veteran";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 32; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["heavy_bolt_pistol"];
  static RNG_WEAPONS = getWeapons(BladeguardVeteran.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["master_crafted_power_weapon"];
  static CC_WEAPONS = getWeapons(BladeguardVeteran.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "bladeguard veteran squad"}];


  static ICON = "/icons/BladeguardVeteran.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, BladeguardVeteran.HP_MAX, startPos);
  }
}
