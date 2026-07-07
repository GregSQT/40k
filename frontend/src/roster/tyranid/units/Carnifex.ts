// frontend/src/roster/tyranid/units/Carnifex.ts

import { getWeapons } from "../armory";
import { EliteMeleeElite } from "../classes/EliteMeleeElite";

export class Carnifex extends EliteMeleeElite {
  static NAME = "Carnifex";
  static DISPLAY_NAME = "Carnifex";
  // BASE
  static MOVE = 8; // Move distance
  static T = 9; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 8; // Max hit points
  static LD = 8; // Leadership score
  static OC = 3; // Operative Control
  static VALUE = 125; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["heavy_venom_cannon"];
  static RNG_WEAPONS = getWeapons(Carnifex.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["monstrous_scything_talons"];
  static CC_WEAPONS = getWeapons(Carnifex.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "monster" },
    { keywordId: "great devourer" },
    { keywordId: "tyranids" },
    { keywordId: "carnifex" },
  ];

  static ICON = "/icons/Carnifex.webp"; // Path relative to public folder
  static BASE_SHAPE = "oval"; // Shape of the base
  /** Diamètres sur la grille micro-hex (engine/hex_utils ``compute_occupied_hexes``), pas des mm. */
  static BASE_SIZE = [41, 27];
  static MODEL_HEIGHT = 4;  // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 2.6; // Size of the icon
  static ILLUSTRATION_RATIO = 130; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, Carnifex.HP_MAX, startPos);
  }
}
