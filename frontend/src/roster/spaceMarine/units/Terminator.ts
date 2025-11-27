// frontend/src/roster/spaceMarine/units/CaptainGravis.ts

import { SpaceMarineInfantryEliteMeleeElite } from "../Classes/SpaceMarineInfantryEliteMeleeElite";

export class Terminator extends SpaceMarineInfantryEliteMeleeElite {
  static NAME = "Terminator";

  // BASE
  static MOVE = 5;             // Move distance
  static T = 5;                // Toughness score
  static ARMOR_SAVE = 2;       // Armor save score
  static INVUL_SAVE = 4;       // Armor invulnerable save score
  static HP_MAX = 3;           // Max hit points
  static LD = 6;               // Leadership score
  static OC = 1;               // Operative Control
  static VALUE = 80;           // Unit value (W40K points cost)
  // RANGE WEAPON
  static RNG_RNG = 24;         // Range attack : range - 12
  static RNG_NB = 2;           // Range attack : number of attacks - 3
  static RNG_ATK = 3;          // Range attack : To Hit score
  static RNG_STR = 4;          // Range attack Strength
  static RNG_AP = 0;          // Range attack Armor penetration
  static RNG_DMG = 1;          // Range attack : damages
  // MELEE WEAPON
  static CC_NB = 3;            // Melee attack : number of attacks - 5
  static CC_RNG = 1;           // Melee attack : range
  static CC_ATK = 3;           // Melee attack : score
  static CC_STR = 8;           // Melee attack Strength
  static CC_AP = -2;           // Melee attack Armor penetration
  static CC_DMG = 2;           // Melee attack : damages

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry";        // Standard infantry movement
  static TARGET_TYPE = "Elite";         // MeleeElite specialist - hunt elite targets

  static ICON = "/icons/Terminator.webp"; // Path relative to public folder
  static ICON_SCALE = 1.8;     // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Terminator.HP_MAX, startPos);
  }
}

