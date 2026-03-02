// frontend/src/roster/spaceMarine/units/Intercessor.ts
//

import { getWeapons } from "../armory";
import { SpaceMarineInfantryTroopRangedSwarm } from "../classes/SpaceMarineInfantryTroopRangedSwarm";

export class SternguardVeteranBoltRifle extends SpaceMarineInfantryTroopRangedSwarm {
  static NAME = "SternguardVeteranBoltRifle";
  static DISPLAY_NAME = "Sternguard Veteran (Bolt Rifle)";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 31; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["sternguard_bolt_rifle", "sternguard_bolt_pistol"];
  static RNG_WEAPONS = getWeapons(SternguardVeteranBoltRifle.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(SternguardVeteranBoltRifle.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // RangedSwarm specialist - bolt rifles vs hordes

  static ICON = "/icons/SternguardVeteranBoltRifle.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, SternguardVeteranBoltRifle.HP_MAX, startPos);
  }
}
