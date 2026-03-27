// frontend/src/roster/tyranid/units/Obliterator.ts

import { getWeapons } from "../armory";
import { EliteRangeElite } from "../classes/EliteRangeElite.ts";

export class Obliterator extends EliteRangeElite {
  static NAME = "Obliterator";
  static DISPLAY_NAME = "Obliterator";
  // BASE
  static MOVE = 4; // Move distance
  static T = 7; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 5; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 90; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["fleshmetal_guns_focused_malice", "fleshmetal_guns_ruinous_salvo", "fleshmetal_guns_warp_hail"];
  static RNG_WEAPONS = getWeapons(Obliterator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["crushing_fists"];
  static CC_WEAPONS = getWeapons(Obliterator.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "chaos"}, { keywordId: "daemon"}, { keywordId: "obliterator"}];
  

  static ICON = "/icons/Obliterator.webp"; // Path relative to public folder
  static ICON_SCALE = 2.2; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Obliterator.HP_MAX, startPos);
  }
}
