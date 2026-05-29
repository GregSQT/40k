// frontend/src/roster/tyranid/units/VonRyanLeaper.ts
//

import { getWeapons } from "../armory";
import { TroopMeleeTroop } from "../classes/TroopMeleeTroop";

export class VonRyanLeaper extends TroopMeleeTroop {
  static NAME = "VonRyanLeaper";
  static DISPLAY_NAME = "Von Ryan Leaper";
  // BASE
  static MOVE = 10; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 6; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 8; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 23; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(VonRyanLeaper.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["leaper_talons"];
  static CC_WEAPONS = getWeapons(VonRyanLeaper.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "infantry" },
    { keywordId: "great devourer" },
    { keywordId: "vanguard invider" },
    { keywordId: "von ryan leapers" },
  ];

  // ICON
  static ICON = "/icons/VonRyanLeapers.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 2.2; // Size of the icon
  static ILLUSTRATION_RATIO = 140; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, VonRyanLeaper.HP_MAX, startPos);
  }
}
