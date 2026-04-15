// frontend/src/roster/spaceMarine/units/DeathCompanyMarineEviscerator.ts

import { getWeapons } from "../armory";
import { TroopMeleeSwarm } from "../classes/TroopMeleeSwarm";

export class DeathCompanyMarineEviscerator extends TroopMeleeSwarm {
  static NAME = "DeathCompanyMarineEviscerator";
  static DISPLAY_NAME = "Death Company Marine (Eviscerator)";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 17; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(DeathCompanyMarineEviscerator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["eviscerator"];
  static CC_WEAPONS = getWeapons(DeathCompanyMarineEviscerator.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "death company"}, { keywordId: "death company marine"}];


  static ICON = "/icons/DeathCompanyMarineEviscerator.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 13; // Size of the base
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, DeathCompanyMarineEviscerator.HP_MAX, startPos);
  }
}
