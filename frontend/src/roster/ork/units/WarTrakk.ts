// frontend/src/roster/ork/units/WarTrakk.ts

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class WarTrakk extends SwarmRangeSwarm {
  static NAME = "WarTrakk";
  static DISPLAY_NAME = "WarTrakk";

  // BASE
  static MOVE = 12; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 6; // Armor invulnerable save score
  static HP_MAX = 7; // Max hit points
  static LD = 7; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 60; // Unit value (W40K points cost) — Munitorum Orks : WARTRAKK, 1 model 60 pts

  // WEAPONS
  static RNG_WEAPON_CODES = ["kustom_shoota_a2", "rokkit_launcha"];
  static RNG_WEAPONS = getWeapons(WarTrakk.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["choppa_a5"];
  static CC_WEAPONS = getWeapons(WarTrakk.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "reroll_charge", displayName: "Unstoppable Valour" }];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { reroll_charge: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "MOUNTED" },
    { keywordId: "SPEED FREEKS" },
    { keywordId: "WARTRAKK" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ORKS" }];

  static ICON = "/icons/WarTrakk.webp"; // Path relative to public folder
  static BASE_SHAPE = "oval"; // Shape of the base
  /** Diamètres sur la grille micro-hex (engine/hex_utils ``compute_occupied_hexes``), pas des mm. */
  static BASE_SIZE = [41, 27];
  static MODEL_HEIGHT = 4; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 2.2; // Size of the icon
  static ILLUSTRATION_RATIO = 120; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, WarTrakk.HP_MAX, startPos);
  }
}
