// frontend/src/roster/spaceMarine/units/LibrarianTerminator.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class Librarian extends LeaderEliteMeleeElite {
  static NAME = "Librarian";
  static DISPLAY_NAME = "Librarian";

  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 4; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 75; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["bolt_pistol", "smite_witchfire", "smite_focused_witchfire"];
  static RNG_WEAPONS = getWeapons(Librarian.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["force_weapon"];
  static CC_WEAPONS = getWeapons(Librarian.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "leader", displayName: "Leader" }];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { reroll_charge: 2, leader: 0 };

  // CAN LEAD (bodyguard unit-name keywords this leader may attach to — rule 19.01)
  static CAN_LEAD = [
    "ASSAULT INTERCESSOR SQUAD",
    "DESOLATION SQUAD",
    "DEVASTATOR SQUAD",
    "HELLBLASTER SQUAD",
    "INFERNUS SQUAD",
    "INTERCESSOR SQUAD",
    "STERNGUARD VETERAN SQUAD",
    "TACTICAL SQUAD",
  ];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "INFANTRY" },
    { keywordId: "CHARACTER" },
    { keywordId: "EXPLOSIVES" },
    { keywordId: "PSYKER" },
    { keywordId: "IMPERIUM" },
    { keywordId: "TACTICUS" },
    { keywordId: "LIBRARIAN" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ADEPTUS ASTARTES" }];

  static ICON = "/icons/Librarian.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.9; // Size of the icon
  static ILLUSTRATION_RATIO = 150; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, Librarian.HP_MAX, startPos);
  }
}
