// frontend/src/roster/spaceMarine/units/AssaultIntercessor.ts

import { getWeapons } from "../armory";
import { TroopMeleeSwarm } from "../classes/TroopMeleeSwarm";

export class AssaultIntercessor extends TroopMeleeSwarm {
  static NAME = "AssaultIntercessor";
  static DISPLAY_NAME = "Assault Intercessor";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 17; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["bolt_pistol"];
  static RNG_WEAPONS = getWeapons(AssaultIntercessor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["assault_intercessor_chainsword"];
  static CC_WEAPONS = getWeapons(AssaultIntercessor.CC_WEAPON_CODES);

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

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // MeleeTroop specialist - backbone melee

  static ICON = "/icons/AssaultIntercessor.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, AssaultIntercessor.HP_MAX, startPos);
  }
}
