// frontend/src/roster/spaceMarine/units/CaptainCloseCombatBolter.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainCloseCombatBolter extends LeaderEliteMeleeElite {
  static NAME = "CaptainCloseCombatBolter";
  static DISPLAY_NAME = "Captain (Close Combat Weapon, Master-crafted Bolter)";

  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 5; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 70; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["master_crafted_bolter_captain", "bolt_pistol_captain"];
  static RNG_WEAPONS = getWeapons(CaptainCloseCombatBolter.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_captain"];
  static CC_WEAPONS = getWeapons(CaptainCloseCombatBolter.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "character"}, { keywordId: "grenade"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "captain"}];


  static ICON = "/icons/CaptainCloseCombatBolter.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainCloseCombatBolter.HP_MAX, startPos);
  }
}
