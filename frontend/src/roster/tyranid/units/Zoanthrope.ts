// frontend/src/roster/tyranid/units/Zoanthrope.ts
//

import { getWeapons } from "../armory";
import { TroopRangeElite } from "../classes/TroopRangeElite.ts";

export class Zoanthrope extends TroopRangeElite {
  static NAME = "Zoanthrope";
  static DISPLAY_NAME = "Zoanthrope";
  // BASE
  static MOVE = 5; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 5; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 7; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 30; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["warp_blast_witchfire", "warp_blast_focused_bolt"];
  static RNG_WEAPONS = getWeapons(Zoanthrope.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["chitinous_claws_and_teeth_zoanthrope"];
  static CC_WEAPONS = getWeapons(Zoanthrope.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "psyker"}, { keywordId: "fly"}, { keywordId: "great devourer"}, { keywordId: "synapse"}, { keywordId: "zoanthrope"}];


  static ICON = "/icons/Zoanthrope.webp"; // Path relative to public folder
  static ICON_SCALE = 1.8; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Zoanthrope.HP_MAX, startPos);
  }
}
