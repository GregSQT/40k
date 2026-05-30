// frontend/src/roster/tyranid/units/Neurogaunt.ts

import { getWeapons } from "../armory";
import { SwarmMeleeSwarm } from "../classes/SwarmMeleeSwarm";

export class Neurogaunt extends SwarmMeleeSwarm {
  static NAME = "Neurogaunt";
  static DISPLAY_NAME = "Neurogaunt";
  // BASE
  static MOVE = 6; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 6; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 8; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 4; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(Neurogaunt.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["chitinous_claws_and_teeth_neurogaunt"];
  static CC_WEAPONS = getWeapons(Neurogaunt.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "charge_after_advance", displayName: "Bounding Leap" }];
  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { charge_after_advance: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "infantry" },
    { keywordId: "great devourer" },
    { keywordId: "endless multitude" },
    { keywordId: "neurogaunt" },
  ];

  // ICON
  static ICON = "/icons/Neurogaunt.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 10; // Size of the base
  static ICON_SCALE = 1.2; // Size of the icon
  static ILLUSTRATION_RATIO = 80; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, Neurogaunt.HP_MAX, startPos);
  }
}
