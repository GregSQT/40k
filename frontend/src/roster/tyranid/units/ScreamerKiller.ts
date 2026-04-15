// frontend/src/roster/tyranid/units/ScreamerKiller.ts

import { getWeapons } from "../armory";
import { EliteMeleeElite } from "../classes/EliteMeleeElite";

export class ScreamerKiller extends EliteMeleeElite {
  static NAME = "ScreamerKiller";
  static DISPLAY_NAME = "Screamer Killer";
  // BASE
  static MOVE = 8; // Move distance
  static T = 9; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 10; // Max hit points
  static LD = 8; // Leadership score
  static OC = 3; // Operative Control
  static VALUE = 175; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["bio_plasmic_screamer"];
  static RNG_WEAPONS = getWeapons(ScreamerKiller.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["screamer_killer_talons"];
  static CC_WEAPONS = getWeapons(ScreamerKiller.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "monster"}, { keywordId: "great devourer"}, { keywordId: "tyranids"}, { keywordId: "carnifex"}];
  

  static ICON = "/icons/ScreamerKiller.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 35; // Size of the base
  static ICON_SCALE = 2.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, ScreamerKiller.HP_MAX, startPos);
  }
}
