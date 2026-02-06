// frontend/src/roster/tyranid/units/Hormagaunt.ts

import { TyranidInfantrySwarmMeleeSwarm } from "../classes/TyranidInfantrySwarmMeleeSwarm";
import { getWeapons } from "../armory";

export class Hormagaunt extends TyranidInfantrySwarmMeleeSwarm {
  static NAME = "Hormagaunt";
  // BASE
  static MOVE = 10;             // Move distance
  static T = 3;                // Toughness score
  static ARMOR_SAVE = 5;       // Armor save score
  static INVUL_SAVE = 7;       // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1;           // Max hit points
  static LD = 8;               // Leadership score
  static OC = 2;               // Operative Control
  static VALUE = 7;            // Unit value (W40K points cost)
  
  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(Hormagaunt.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["scything_talons"];
  static CC_WEAPONS = getWeapons(Hormagaunt.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm";      // Swarm: 1 wound, fragile
  static MOVE_TYPE = "Infantry";       // Fast infantry movement
  static TARGET_TYPE = "Swarm";        // MeleeSwarm specialist - mob assault

  static UNIT_RULES = [
    { ruleId: "charge_after_advance", displayName: "Bounding Leap" },
  ];

  static ICON = "/icons/Hormagaunt.webp"; // Path relative to public folder
  static ICON_SCALE = 1.2;     // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Hormagaunt.HP_MAX, startPos);
  }
}

