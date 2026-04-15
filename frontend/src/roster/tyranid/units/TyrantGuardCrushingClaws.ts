// frontend/src/roster/tyranid/units/TyrantGuardCrushingClaws.ts
//

import { getWeapons } from "../armory";
import { EliteMeleeElite } from "../classes/EliteMeleeElite";

export class TyrantGuardCrushingClaws extends EliteMeleeElite {
  static NAME = "TyrantGuardCrushingClaws";
  static DISPLAY_NAME = "TyrantGuard (Crushing Claws)";
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
  static RNG_WEAPONS = getWeapons(TyrantGuardCrushingClaws.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["crushing_claws"];
  static CC_WEAPONS = getWeapons(TyrantGuardCrushingClaws.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "great devourer"}, { keywordId: "tyrant guard"}];


  static ICON = "/icons/TyrantGuardCrushingClaws.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 20; // Size of the base
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, TyrantGuardCrushingClaws.HP_MAX, startPos);
  }
}
