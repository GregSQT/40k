// frontend/src/roster/spaceMarine/units/Intercessor.ts
//

import { getWeapons } from "../armory";
import { SpaceMarineInfantryTroopMeleeElite } from "../classes/SpaceMarineInfantryTroopMeleeElite.ts";

export class SternguardVeteranSergeantPowerFist extends SpaceMarineInfantryTroopMeleeElite {
  static NAME = "SternguardVeteranSergeantPowerFist";
  static DISPLAY_NAME = "Sternguard Veteran (Sergeant, Power Fist)";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 38; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["sternguard_bolt_rifle", "sternguard_bolt_pistol"];
  static RNG_WEAPONS = getWeapons(SternguardVeteranSergeantPowerFist.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(SternguardVeteranSergeantPowerFist.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Elite"; // MeleeElite specialist - hunt elite targets

  static ICON = "/icons/SternguardVeteranSergeantPowerFist.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, SternguardVeteranSergeantPowerFist.HP_MAX, startPos);
  }
}
