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
  static UNIT_KEYWORDS = [
    { keywordId: "infantry" },
    { keywordId: "grenades" },
    { keywordId: "imperium" },
    { keywordId: "tacticus" },
    { keywordId: "BLADEGUARD VETERAN SQUAD" },
  ];

  static ICON = "/icons/BladeguardVeteran.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Size of the icon
  static ILLUSTRATION_RATIO = 100; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, BladeguardVeteran.HP_MAX, startPos);
  }
}
