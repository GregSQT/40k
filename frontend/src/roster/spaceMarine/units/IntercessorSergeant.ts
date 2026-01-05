// frontend/src/roster/spaceMarine/units/IntercessorSergeant.ts
//
import { SpaceMarineInfantryTroopRangedSwarm } from "../classes/SpaceMarineInfantryTroopRangedSwarm";
import { getWeapons } from "../armory";

export class IntercessorSergeant extends SpaceMarineInfantryTroopRangedSwarm {
  static NAME = "IntercessorSergeant";
  // BASE
  static MOVE = 6;             // Move distance
  static T = 4;                // Toughness score
  static ARMOR_SAVE = 3;       // Armor save score
  static INVUL_SAVE = 7;       // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2;           // Max hit points
  static LD = 6;               // Leadership score
  static OC = 2;               // Operative Control
  static VALUE = 19;           // Unit value (W40K points cost)
  
  // WEAPONS
  static RNG_WEAPON_CODES = ["bolt_rifle", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(IntercessorSergeant.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(IntercessorSergeant.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop";      // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry";       // Standard infantry movement
  static TARGET_TYPE = "Swarm";        // RangedSwarm specialist - bolt rifles vs hordes

  static ICON = "/icons/IntercessorSergeant.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6;     // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, IntercessorSergeant.HP_MAX, startPos);
  }
}
