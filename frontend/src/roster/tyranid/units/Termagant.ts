// frontend/src/roster/tyranid/units/Termagant.ts
//
import { TyranidInfantrySwarmRangedSwarm } from "../Classes/TyranidInfantrySwarmRangedSwarm";

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
  // RANGE WEAPON
  static RNG_RNG = 18;         // Range attack : range
  static RNG_NB = 1;           // Range attack : number of attacks
  static RNG_ATK = 4;          // Range attack : To Hit score
  static RNG_STR = 5;          // Range attack Strength
  static RNG_AP = 0;           // Range attack Armor penetration
  static RNG_DMG = 1;          // Range attack : damages
  // MELEE WEAPON
  static CC_NB = 1;            // Melee attack : number of attacks
  static CC_RNG = 1;           // Melee attack : range
  static CC_ATK = 4;           // Melee attack : score
  static CC_STR = 3;           // Melee attack Strength
  static CC_AP = 0;            // Melee attack Armor penetration
  static CC_DMG = 1;           // Melee attack : damages

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
