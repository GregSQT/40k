// frontend/src/roster/tyranid/units/CustodianGuardBlade.ts

import { getWeapons } from "../armory";
import { EliteMeleeTroop } from "../classes/EliteMeleeTroop";

export class CustodianGuardBlade extends EliteMeleeTroop {
  static NAME = "CustodianGuardBlade";
  static DISPLAY_NAME = "CustodianGuardBlade";
  // BASE
  static MOVE = 6; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 4; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 56; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["sentinel_blade_ranged"];
  static RNG_WEAPONS = getWeapons(CustodianGuardBlade.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["sentinel_blade_melee"];
  static CC_WEAPONS = getWeapons(CustodianGuardBlade.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "imperium"}, { keywordId: "custodian guard"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 8 wounds, 2+ save - heavy armor
  static MOVE_TYPE = "Infantry"; // Monster movement (treated as infantry)
  static TARGET_TYPE = "Troop"; // MeleeTroop specialist - monster vs troop

  static ICON = "/icons/CustodianGuardBlade.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CustodianGuardBlade.HP_MAX, startPos);
  }
}
