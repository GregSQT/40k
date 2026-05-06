// frontend/src/roster/tyranid/units/Neurotyrant.ts

import { getWeapons } from "../armory";
import { EliteMeleeElite } from "../classes/EliteMeleeElite";

export class Neurotyrant extends EliteMeleeElite {
  static NAME = "Neurotyrant";
  static DISPLAY_NAME = "Neurotyrant";
  // BASE
  static MOVE = 6; // Move distance
  static T = 8; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 9; // Max hit points
  static LD = 7; // Leadership score
  static OC = 3; // Operative Control
  static VALUE = 95; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["psychic_scream"];
  static RNG_WEAPONS = getWeapons(Neurotyrant.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["neurotyrant_claws_and_lashers"];
  static CC_WEAPONS = getWeapons(Neurotyrant.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "monster" },
    { keywordId: "character" },
    { keywordId: "fly" },
    { keywordId: "psyker" },
    { keywordId: "great devourer" },
    { keywordId: "synapse" },
    { keywordId: "tyranids" },
    { keywordId: "neurotyrant" },
  ];

  static ICON = "/icons/Neurotyrant.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 20; // Size of the base
  static ICON_SCALE = 2.6; // Size of the icon
  static ILLUSTRATION_RATIO = 130; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, Neurotyrant.HP_MAX, startPos);
  }
}
