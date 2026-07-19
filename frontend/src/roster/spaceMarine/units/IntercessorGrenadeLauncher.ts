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
  static VALUE = 16; // Unit value (W40K points cost) — Munitorum SM : INTERCESSOR SQUAD 80 pts /
                    // 5 modeles = 16 par modele. En 10e, l'equipement est gratuit : pas de
                    // surcout pour le lance-grenades.

  // WEAPONS
  static RNG_WEAPON_CODES = [
    "grenade_launcher_intercessor_frag",
    "grenade_launcher_intercessor_krak",
    "bolt_pistol",
  ];
  static RNG_WEAPONS = getWeapons(IntercessorGrenadeLauncher.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(IntercessorGrenadeLauncher.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "special_weapon", displayName: "Special Weapon" }];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "INFANTRY" },
    { keywordId: "BATTLELINE" },
    { keywordId: "EXPLOSIVES" },
    { keywordId: "IMPERIUM" },
    { keywordId: "TACTICUS" },
    { keywordId: "INTERCESSOR SQUAD" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ADEPTUS ASTARTES" }];

  static ICON = "/icons/IntercessorGrenadeLauncher.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 13; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Size of the icon
  static ILLUSTRATION_RATIO = 95; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, IntercessorGrenadeLauncher.HP_MAX, startPos);
  }
}
