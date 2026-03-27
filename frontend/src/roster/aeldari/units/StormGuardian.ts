// frontend/src/roster/spaceMarine/units/StormGuardian.ts

import { getWeapons } from "../armory";
import { SwarmMeleeSwarm } from "../classes/SwarmMeleeSwarm";

export class StormGuardian extends SwarmMeleeSwarm {
  static NAME = "StormGuardian";
  static DISPLAY_NAME = "Storm Guardian";

  // BASE
  static MOVE = 7; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 10; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["shuriken_pistol"];
  static RNG_WEAPONS = getWeapons(StormGuardian.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_aspect_warrior"];
  static CC_WEAPONS = getWeapons(StormGuardian.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "guardians"}, { keywordId: "guardian defenders"}];
  

  static ICON = "/icons/StormGuardian.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, StormGuardian.HP_MAX, startPos);
  }
}
