// frontend/src/roster/spaceMarine/units/AssaultIntercessor.ts

import { getWeapons } from "../armory";
import { TroopMeleeElite } from "../classes/TroopMeleeElite";

export class AssaultIntercessorSergeant extends TroopMeleeElite {
  static NAME = "AssaultIntercessorSergeant";
  static DISPLAY_NAME = "Assault Intercessor (Sergeant)";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 22; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["plasma_pistol_standard", "plasma_pistol_supercharge"];
  static RNG_WEAPONS = getWeapons(AssaultIntercessorSergeant.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(AssaultIntercessorSergeant.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    {
      ruleId: "targeted_intercession",
      displayName: "Targeted Intercession",
      grants_rule_ids: [
        "targeted_intercession_reroll_1_towound",
        "targeted_intercession_reroll_towound_target_on_objective",
      ],
      usage: "and",
    },
  ];
  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = {
    targeted_intercession: 2,
    targeted_intercession_reroll_1_towound: 2,
    targeted_intercession_reroll_towound_target_on_objective: 2,
  };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "assault intercessor squad"}];


  static ICON = "/icons/AssaultIntercessorSergeant.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 13; // Size of the base
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, AssaultIntercessorSergeant.HP_MAX, startPos);
  }
}
