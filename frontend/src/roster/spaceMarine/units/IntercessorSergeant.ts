// frontend/src/roster/spaceMarine/units/IntercessorSergeant.ts
//

import { getWeapons } from "../armory";
import { SpaceMarineInfantryTroopRangedSwarm } from "../classes/SpaceMarineInfantryTroopRangedSwarm";

export class IntercessorSergeant extends SpaceMarineInfantryTroopRangedSwarm {
  static NAME = "IntercessorSergeant";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 21; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["plasma_pistol_standard", "plasma_pistol_supercharge"];
  static RNG_WEAPONS = getWeapons(IntercessorSergeant.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["intercessor_sergeant_power_fist"];
  static CC_WEAPONS = getWeapons(IntercessorSergeant.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Swarm"; // RangedSwarm specialist - bolt rifles vs hordes

  static ICON = "/icons/IntercessorSergeant.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, IntercessorSergeant.HP_MAX, startPos);
  }
}
