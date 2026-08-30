// frontend/src/roster/spaceMarine/units/EradicatorMeltaRifle.ts

import { getWeapons } from "../armory";
import { EliteRangeTroop } from "../classes/EliteRangeTroop";

export class EradicatorHeavyBolterSergeant extends EliteRangeTroop {
  static NAME = "EradicatorHeavyBolterSergeant";
  static DISPLAY_NAME = "Eradicator Sergeant (Heavy Bolter)";

  // BASE
  static MOVE = 5; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 28; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["heavy_bolter"];
  static RNG_WEAPONS = getWeapons(EradicatorHeavyBolterSergeant.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(EradicatorHeavyBolterSergeant.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    // Overlapping Detonations : meme regle que le corps (union 19.04 ; le sergent porte aussi
    // le heavy_bolter donc la regle s applique directement a ses intents).
    {
      ruleId: "grant_weapon_rule_vs_designated_target",
      displayName: "Overlapping Detonations",
      rule_args: { weapon_code: "heavy_bolter" },
    },
  ];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { grant_weapon_rule_vs_designated_target: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "INFANTRY" },
    { keywordId: "IMPERIUM" },
    { keywordId: "GRAVIS" },
    { keywordId: "ERADICATOR SQUAD" },
    { keywordId: "ERADICATOR SQUAD WITH HEAVY BOLTER" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ADEPTUS ASTARTES" }];

  static ICON = "/icons/EradicatorHeavyBolterSergeant.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 2.0; // Size of the icon
  static ILLUSTRATION_RATIO = 120; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, EradicatorHeavyBolterSergeant.HP_MAX, startPos);
  }
}
