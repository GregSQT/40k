// frontend/src/roster/tyranid/units/Carnifex.ts

import { getWeapons } from "../armory";
import { TyranidInfantryEliteMeleeElite } from "../classes/TyranidInfantryEliteMeleeElite";

export class Carnifex extends TyranidInfantryEliteMeleeElite {
  static NAME = "Carnifex";
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
  static RNG_WEAPON_CODES = ["venom_cannon"];
  static RNG_WEAPONS = getWeapons(Carnifex.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["monstrous_scything_talons"];
  static CC_WEAPONS = getWeapons(Carnifex.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 8 wounds, 2+ save - heavy armor
  static MOVE_TYPE = "Infantry"; // Monster movement (treated as infantry)
  static TARGET_TYPE = "Elite"; // MeleeElite specialist - monster vs elite

  static ICON = "/icons/Carnifex.webp"; // Path relative to public folder
  static ICON_SCALE = 2.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Carnifex.HP_MAX, startPos);
  }
}
