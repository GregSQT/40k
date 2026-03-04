/*  EXAMPLE for HeavyIntercessor
1 : Rempalce HeavyIntercessor by the name of the unit
2 : Replace SpaceMarineInfantryEliteRangedTroop by the class of the unit
3 : Update the values of the unit
4 : Update the weapons of the unit
5 : Update the armory.ts if the weapon is a new one. example: frontend/src/roster/spaceMarine/armory.ts
6 : Update the weapon_rules.json if the weapon rule is a new one. example: config/weapon_rules.json
7 : Update the unit rules of the unit
8 : Update the unit rules if the rule is a new one. example: config/unit_rules.json
9 : Update the unit keywords of the unit
10 : Update the AI classification of the unit
11 : Update the icon of the unit
12 : Update the scale of the icon
13 : Update the frontend unit registry.json if the unit is a new one : frontend/public/config/unit_registry.json
14 : Update the backend unit registry.json if the unit is a new one : config/unit_registry.json
*/
// frontend/src/roster/spaceMarine/units/HeavyIntercessor.ts

import { getWeapons } from "../armory";
import { SpaceMarineInfantryEliteRangedTroop } from "../classes/SpaceMarineInfantryEliteRangedTroop.ts";

export class HeavyIntercessor extends SpaceMarineInfantryEliteRangedTroop {
  static NAME = "HeavyIntercessor";
  static DISPLAY_NAME = "Heavy Intercessor";
  // BASE
  static MOVE = 5; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 19; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["heavy_bolt_rifle", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(HeavyIntercessor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(HeavyIntercessor.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 3+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // RangedTroop specialist - bolt rifles vs hordes

  static ICON = "/icons/HeavyIntercessor.webp"; // Path relative to public folder
  static ICON_SCALE = 1.8; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, HeavyIntercessor.HP_MAX, startPos);
  }
}
