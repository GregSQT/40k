// frontend/src/roster/spaceMarine/units/EradicatorMeltaRifle.ts

import { getWeapons } from "../armory";
import { EliteRangeTroop } from "../classes/EliteRangeTroop";

export class LandSpeeder extends EliteRangeTroop {
  static NAME = "LandSpeeder";
  static DISPLAY_NAME = "Land Speeder";

  // BASE
  static MOVE = 14; // Move distance
  static T = 8; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 9; // Max hit points
  static LD = 6; // Leadership score
  static OC = 3; // Operative Control
  static VALUE = 28; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["heavy_flamer_vehicle", "multi_melta_vehicle", "stormfury_missile_launcher"];
  static RNG_WEAPONS = getWeapons(LandSpeeder.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_a4"];
  static CC_WEAPONS = getWeapons(LandSpeeder.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "VEHICLE" },
    { keywordId: "FLY" },
    { keywordId: "IMPERIUM" },
    { keywordId: "LAND SPEEDER" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ADEPTUS ASTARTES" }];
  
  static ICON = "/icons/LandSpeeder.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 2.0; // Size of the icon
  static ILLUSTRATION_RATIO = 100; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, LandSpeeder.HP_MAX, startPos);
  }
}
