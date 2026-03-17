// frontend/src/roster/tyranid/units/Carnifex.ts

import { getWeapons } from "../armory";
import { TroopRangedElite } from "../classes/TroopRangedElite.ts";

export class RaptorMeltaGun extends TroopRangedElite {
  static NAME = "RaptorMeltaGun";
  static DISPLAY_NAME = "RaptorMeltaGun";
  // BASE
  static MOVE = 12; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 24; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["meltagun"];
  static RNG_WEAPONS = getWeapons(RaptorMeltaGun.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_a3"];
  static CC_WEAPONS = getWeapons(RaptorMeltaGun.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "fly"}, { keywordId: "jump_pack"}, { keywordId: "chaos"}, { keywordId: "raptor"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Monster movement (treated as infantry)
  static TARGET_TYPE = "Elite"; // RangedTroop specialist - meltagun vs elites

  static ICON = "/icons/RaptorMeltaGun.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, RaptorMeltaGun.HP_MAX, startPos);
  }
}
