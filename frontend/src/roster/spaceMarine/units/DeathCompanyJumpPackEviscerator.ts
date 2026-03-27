// frontend/src/roster/spaceMarine/units/DeathCompanyJumpPackEviscerator.ts

import { getWeapons } from "../armory";
import { TroopMeleeTroop } from "../classes/TroopMeleeTroop";

export class DeathCompanyJumpPackEviscerator extends TroopMeleeTroop {
  static NAME = "DeathCompanyJumpPackEviscerator";
  static DISPLAY_NAME = "Death Company Jump Pack (Eviscerator)";
  // BASE
  static MOVE = 12; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 17; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(DeathCompanyJumpPackEviscerator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["eviscerator"];
  static CC_WEAPONS = getWeapons(DeathCompanyJumpPackEviscerator.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "grenades"}, { keywordId: "jump_pack"}, { keywordId: "fly"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "death company"}, { keywordId: "death company marine"}, { keywordId: "death company with jump packs"}];


  static ICON = "/icons/DeathCompanyJumpPackEviscerator.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, DeathCompanyJumpPackEviscerator.HP_MAX, startPos);
  }
}
