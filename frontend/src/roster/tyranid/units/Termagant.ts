// frontend/src/roster/tyranid/units/Termagant.ts
//
import { TyranidInfantrySwarmRangedSwarm } from "../classes/TyranidInfantrySwarmRangedSwarm";
import { getWeapons } from "../armory";

export class Termagant extends TyranidInfantrySwarmRangedSwarm {
  static NAME = "Termagant";
  // BASE
  static MOVE = 6;             // Move distance
  static T = 3;                // Toughness score
  static ARMOR_SAVE = 5;       // Armor save score
  static INVUL_SAVE = 7;       // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1;           // Max hit points
  static LD = 8;               // Leadership score
  static OC = 2;               // Operative Control
  static VALUE = 6;            // Unit value (W40K points cost)
  
  // WEAPONS
  static RNG_WEAPON_CODES = ["fleshborer"];
  static RNG_WEAPONS = getWeapons(Termagant.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["flesh_hooks"];
  static CC_WEAPONS = getWeapons(Termagant.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm";      // Swarm: 1 wound, fragile
  static MOVE_TYPE = "Infantry";       // Standard infantry movement
  static TARGET_TYPE = "Swarm";        // RangedSwarm specialist - anti-infantry

  static ICON = "/icons/Termagant.webp"; // Path relative to public folder
  static ICON_SCALE = 1.4;     // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Termagant.HP_MAX, startPos);
  }
}
