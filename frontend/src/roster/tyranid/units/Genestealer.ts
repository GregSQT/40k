// frontend/src/roster/tyranid/units/Genestealer.ts

import { getWeapons } from "../armory";
import { TyranidInfantryTroopMeleeTroop } from "../classes/TyranidInfantryTroopMeleeTroop";

export class Genestealer extends TyranidInfantryTroopMeleeTroop {
  static NAME = "Genestealer";
  // BASE
  static MOVE = 8; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 5; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score
  static HP_MAX = 2; // Max hit points
  static LD = 7; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 19; // Unit value

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(Genestealer.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["rending_claws"];
  static CC_WEAPONS = getWeapons(Genestealer.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // // Troop: 2 wounds, 3+ save / 5+ Invu
  static MOVE_TYPE = "Infantry"; // Fast infantry movement
  static TARGET_TYPE = "Troop"; // MeleeTroop specialist - mob assault

  static ICON = "/icons/Genestealer.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Genestealer.HP_MAX, startPos);
  }
}
