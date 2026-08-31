// frontend/src/roster/ork/units/Warboss.ts

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class Warboss extends SwarmRangeSwarm {
  static NAME = "Warboss";
  static DISPLAY_NAME = "Warboss";

  // BASE
  static MOVE = 6; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score
  static HP_MAX = 6; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 85; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["kustom_shoota_a4"];
  static RNG_WEAPONS = getWeapons(Warboss.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["kustom_choppa"];
  static CC_WEAPONS = getWeapons(Warboss.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    { ruleId: "leader", displayName: "Leader" },
    // Might Is Right : « This unit's melee weapons have +1 to hit rolls. » Portée par le
    // Warboss, donc en vigueur sur TOUTE l'escouade qu'il mène (19.04).
    { ruleId: "hit_roll_bonus_fight", displayName: "Might Is Right" },
    // Da Biggest and da Best : « While the Waaagh! is active for this unit, this model's
    // melee weapons have +4 A. » Portée par CE MODÈLE uniquement (ce n'est pas une règle d'unité).
    {
      ruleId: "melee_attacks_bonus_while_waaagh",
      displayName: "Da Biggest and da Best",
      rule_args: { attacks_bonus: 4 },
    },
  ];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { leader: 2, hit_roll_bonus_fight: 2, melee_attacks_bonus_while_waaagh: 2 };

  // CAN LEAD (bodyguard unit-name keywords this leader may attach to — rule 19.01)
  static CAN_LEAD = ["BOYZ", "BREAKA BOYZ", "NOBZ"];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "INFANTRY" },
    { keywordId: "CHARACTER" },
    { keywordId: "EXPLOSIVES" },
    { keywordId: "WARBOSS" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ORKS" }];

  static ICON = "/icons/Warboss.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 20; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Size of the icon
  static ILLUSTRATION_RATIO = 160; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, Warboss.HP_MAX, startPos);
  }
}
