// frontend/src/roster/tyranid/units/Hormagaunt.ts

import { getWeapons } from "../armory";
import { SwarmMeleeSwarm } from "../classes/SwarmMeleeSwarm";

export class Hormagaunt extends SwarmMeleeSwarm {
  static NAME = "Hormagaunt";
  static DISPLAY_NAME = "Hormagaunt";
  // BASE
  static MOVE = 10; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 5; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 8; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 7; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(Hormagaunt.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["scything_talons"];
  static CC_WEAPONS = getWeapons(Hormagaunt.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "charge_after_advance", displayName: "Bounding Leap" }];
  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { charge_after_advance: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "great devourer"}, { keywordId: "endless multitude"}, { keywordId: "tyranids"}, { keywordId: "hormagaunt"}];


  // ICON
  static ICON = "/icons/Hormagaunt2.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 11; // Size of the base
  static ICON_SCALE = 1.2; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Hormagaunt.HP_MAX, startPos);
  }
}
