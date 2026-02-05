// frontend/src/roster/spaceMarine/units/CaptainGravis.ts

import { SpaceMarineInfantryLeaderEliteMeleeElite } from "../classes/SpaceMarineInfantryLeaderEliteMeleeElite";
import { getWeapons } from "../armory";

export class CaptainGravis extends SpaceMarineInfantryLeaderEliteMeleeElite {
  static NAME = "Captain Gravis";

  // BASE
  static MOVE = 5;             // Move distance
  static T = 6;                // Toughness score
  static ARMOR_SAVE = 3;       // Armor save score
  static INVUL_SAVE = 4;       // Armor invulnerable save score
  static HP_MAX = 6;           // Max hit points
  static LD = 6;               // Leadership score
  static OC = 1;               // Operative Control
  static VALUE = 80;           // Unit value (W40K points cost)
  
  // WEAPONS
  static RNG_WEAPON_CODES = ["master_crafted_boltgun"];
  static RNG_WEAPONS = getWeapons(CaptainGravis.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(CaptainGravis.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "LeaderElite"; // LeaderElite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry";        // Standard infantry movement
  static TARGET_TYPE = "Elite";         // MeleeElite specialist - hunt elite targets

  static ICON = "/icons/CaptainGravis.webp"; // Path relative to public folder
  static ICON_SCALE = 1.9;     // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainGravis.HP_MAX, startPos);
  }
}

