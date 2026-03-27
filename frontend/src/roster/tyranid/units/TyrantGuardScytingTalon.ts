// frontend/src/roster/tyranid/units/TyrantGuardScytingTalon.ts
//

import { getWeapons } from "../armory.ts";
import { EliteMeleeTroop } from "../classes/EliteMeleeTroop.ts";

export class TyrantGuardScytingTalon extends EliteMeleeTroop {
  static NAME = "TyrantGuardScytingTalon";
  static DISPLAY_NAME = "Tyrant Guard (Scyting Talon)";
  // BASE
  static MOVE = 6; // Move distance
  static T = 8; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 4; // Max hit points
  static LD = 8; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 32; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(TyrantGuardScytingTalon.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["scything_talons_tyrant_guard"];
  static CC_WEAPONS = getWeapons(TyrantGuardScytingTalon.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "great devourer"}, { keywordId: "tyrant guard"}];


  static ICON = "/icons/TyrantGuardScytingTalon.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, TyrantGuardScytingTalon.HP_MAX, startPos);
  }
}
