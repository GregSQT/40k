// frontend/src/roster/tyranid/units/Barbgaunt.ts
//

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class Barbgaunt extends SwarmRangeSwarm {
  static NAME = "Barbgaunt";
  static DISPLAY_NAME = "Barbgaunt";
  // BASE
  static MOVE = 6; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 8; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 6; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["fleshborer"];
  static RNG_WEAPONS = getWeapons(Barbgaunt.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["flesh_hooks"];
  static CC_WEAPONS = getWeapons(Barbgaunt.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "infantry" },
    { keywordId: "battleline" },
    { keywordId: "great devourer" },
    { keywordId: "endless multitude" },
    { keywordId: "tyranids" },
    { keywordId: "termagant" },
  ];

  static ICON = "/icons/Barbgaunt.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 11; // Size of the base
  static MODEL_HEIGHT = 2.5;  // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.2; // Size of the icon
  static ILLUSTRATION_RATIO = 100; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, Barbgaunt.HP_MAX, startPos);
  }
}
