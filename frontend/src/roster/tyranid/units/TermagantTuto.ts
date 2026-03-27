// frontend/src/roster/tyranid/units/Termagant.ts
//

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class TermagantTuto extends SwarmRangeSwarm {
  static NAME = "TermagantTuto";
  static DISPLAY_NAME = "Termagant";
  // BASE
  static MOVE = 6; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 5; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 8; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 6; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["fleshborer"];
  static RNG_WEAPONS = getWeapons(TermagantTuto.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["flesh_hooks"];
  static CC_WEAPONS = getWeapons(TermagantTuto.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "great devourer"}, { keywordId: "endless multitude"}, { keywordId: "tyranids"}, { keywordId: "termagant"}];


  static ICON = "/icons/Termagant.webp"; // Path relative to public folder
  static ICON_SCALE = 1.2; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, TermagantTuto.HP_MAX, startPos);
  }
}
