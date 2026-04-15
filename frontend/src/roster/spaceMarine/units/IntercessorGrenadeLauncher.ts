// frontend/src/roster/spaceMarine/units/IntercessorGrenadeLauncher.ts
//

import { getWeapons } from "../armory";
import { TroopRangeSwarm } from "../classes/TroopRangeSwarm";

export class IntercessorGrenadeLauncher extends TroopRangeSwarm {
  static NAME = "IntercessorGrenadeLauncher";
  static DISPLAY_NAME = "Intercessor (Grenade Launcher)";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 20; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = [
    "astartes_grenade_launcher_frag",
    "astartes_grenade_launcher_krak",
    "bolt_pistol",
  ];
  static RNG_WEAPONS = getWeapons(IntercessorGrenadeLauncher.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(IntercessorGrenadeLauncher.CC_WEAPON_CODES);

    // UNIT KEYWORDS
    static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "intercessor squad"}];


  static ICON = "/icons/IntercessorGrenadeLauncher.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 13; // Size of the base
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, IntercessorGrenadeLauncher.HP_MAX, startPos);
  }
}
