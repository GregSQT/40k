// frontend/src/roster/spaceMarine/units/CaptainRelicShield.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class ChaplainJumpPack extends LeaderEliteMeleeElite {
  static NAME = "ChaplainJumpPack";
  static DISPLAY_NAME = "Chaplain with Jump Pack";

  // BASE
  static MOVE = 12; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 4; // Max hit points
  static LD = 5; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 70; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["absolvor_pistol"];
  static RNG_WEAPONS = getWeapons(ChaplainJumpPack.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["crozius_arcanum"];
  static CC_WEAPONS = getWeapons(ChaplainJumpPack.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    { ruleId: "reroll_charge", displayName: "Unstoppable Valour" },
    { ruleId: "leader", displayName: "Leader" },
  ];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { reroll_charge: 2, leader: 0 };

  // CAN LEAD (bodyguard unit-name keywords this leader may attach to — rule 19.01)
  static CAN_LEAD = [
    "ASSAULT INTERCESSORS WITH JUMP PACKS",
    "VANGUARD VETERAN SQUAD WITH JUMP PACKS",
  ];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "INFANTRY" },
    { keywordId: "CHARACTER" },
    { keywordId: "JUMP PACK" },
    { keywordId: "FLY" },
    { keywordId: "IMPERIUM" },
    { keywordId: "CHAPELAIN WITH JUMP PACK" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ADEPTUS ASTARTES" }];

  static ICON = "/icons/ChaplainJumpPack.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Size of the icon
  static ILLUSTRATION_RATIO = 135; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, ChaplainJumpPack.HP_MAX, startPos);
  }
}
