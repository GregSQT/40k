// frontend/src/roster/spaceMarine/units/Intercessor.ts
//

import { getWeapons } from "../armory";
import { TroopRangeSwarm } from "../classes/TroopRangeSwarm";

export class Intercessor extends TroopRangeSwarm {
  static NAME = "Intercessor";
  static DISPLAY_NAME = "Intercessor";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 16; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["bolt_rifle", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(Intercessor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(Intercessor.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    // Hail of Bolts : « ...when this unit is selected to shoot you can select one enemy unit
    // visible to this unit. While making attacks, this unit's bolt rifles that targeted that
    // selected unit have +2 A. » Dans ce moteur la cible de l'intent est la cible désignée.
    {
      ruleId: "weapon_attacks_bonus_vs_designated_target",
      displayName: "Hail of Bolts",
      rule_args: { weapon_code: "bolt_rifle", attacks_bonus: 2 },
    },
    {
      ruleId: "secure_objective_on_control",
      displayName: "Objective Secured",
    },
  ];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = {
    weapon_attacks_bonus_vs_designated_target: 2,
    secure_objective_on_control: 2,
  };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "INFANTRY" },
    { keywordId: "BATTLELINE" },
    { keywordId: "EXPLOSIVES" },
    { keywordId: "IMPERIUM" },
    { keywordId: "TACTICUS" },
    { keywordId: "INTERCESSOR SQUAD" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ADEPTUS ASTARTES" }];

  static ICON = "/icons/Intercessor.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 13; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Scale of the icon
  static ILLUSTRATION_RATIO = 95; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, Intercessor.HP_MAX, startPos);
  }
}
