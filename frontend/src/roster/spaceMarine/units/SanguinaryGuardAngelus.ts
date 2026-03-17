// frontend/src/roster/spaceMarine/units/SanguinaryGuardAngelus.ts

import { getWeapons } from "../armory";
import { TroopMeleeTroop } from "../classes/TroopMeleeTroop";

export class SanguinaryGuardAngelus extends TroopMeleeTroop {
  static NAME = "SanguinaryGuardAngelus";
  static DISPLAY_NAME = "Sanguinary Guard (Bolter Angelus)";
  // BASE
  static MOVE = 12; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 50; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["angelus_boltgun"];
  static RNG_WEAPONS = getWeapons(SanguinaryGuardAngelus.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["encarmine_blade"];
  static CC_WEAPONS = getWeapons(SanguinaryGuardAngelus.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "grenades"}, { keywordId: "jump_pack"}, { keywordId: "fly"}, { keywordId: "imperium"}, { keywordId: "sanguinary guard"}];

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // MeleeTroop specialist - backbone melee

  static ICON = "/icons/SanguinaryGuardAngelus.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, SanguinaryGuardAngelus.HP_MAX, startPos);
  }
}
