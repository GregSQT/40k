// frontend/src/roster/tyranid/units/WingedTyranidPrime .ts
//

import { getWeapons } from "../armory";
import { TroopMeleeTroop } from "../classes/TroopMeleeTroop";

export class WingedTyranidPrime extends TroopMeleeTroop {
  static NAME = "WingedTyranidPrime";
  static DISPLAY_NAME = "Winged Tyranid Prime";
  // BASE
  static MOVE = 12; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 6; // Max hit points
  static LD = 7; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 65; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(WingedTyranidPrime.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["prime_talons"];
  static CC_WEAPONS = getWeapons(WingedTyranidPrime.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "infantry" },
    { keywordId: "character" },
    { keywordId: "fly" },
    { keywordId: "great devourer" },
    { keywordId: "synapse" },
    { keywordId: "vanguard invider" },
    { keywordId: "winged tyranid prime" },
  ];

  // ICON
  static ICON = "/icons/WingedTyranidPrime.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 24; // Size of the base
  static MODEL_HEIGHT = 4; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 2.2; // Size of the icon
  static ILLUSTRATION_RATIO = 150; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, WingedTyranidPrime.HP_MAX, startPos);
  }
}
