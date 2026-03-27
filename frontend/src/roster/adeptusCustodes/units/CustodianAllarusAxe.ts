// frontend/src/roster/tyranid/units/CustodianAllarusAxe.ts

import { getWeapons } from "../armory";
import { EliteMeleeElite } from "../classes/EliteMeleeElite";

export class CustodianAllarusAxe extends EliteMeleeElite {
  static NAME = "CustodianAllarusAxe";
  static DISPLAY_NAME = "CustodianAllarusAxe";
  // BASE
  static MOVE = 5; // Move distance
  static T = 7; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 4; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 70; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["castellan_axe_ranged", "balistus_grenade_launcher"];
  static RNG_WEAPONS = getWeapons(CustodianAllarusAxe.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["castellan_axe_melee"];
  static CC_WEAPONS = getWeapons(CustodianAllarusAxe.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "imperium"}, { keywordId: "custodian allarus"}];
  

  static ICON = "/icons/CustodianAllarusAxe.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CustodianAllarusAxe.HP_MAX, startPos);
  }
}
