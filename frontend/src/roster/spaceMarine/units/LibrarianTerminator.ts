// frontend/src/roster/spaceMarine/units/LibrarianTerminator.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class LibrarianTerminator extends LeaderEliteMeleeElite {
  static NAME = "LibrarianTerminator";
  static DISPLAY_NAME = "Librarian Terminator";

  // BASE
  static MOVE = 5; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 5; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 75; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = [
    "combi_weapon_librarian",
    "smite_witchfire",
    "smite_focused_witchfire",
  ];
  static RNG_WEAPONS = getWeapons(LibrarianTerminator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["force_weapon"];
  static CC_WEAPONS = getWeapons(LibrarianTerminator.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "support", displayName: "Support" }];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { reroll_charge: 2, leader: 0 };

  // CAN LEAD (bodyguard unit-name keywords this leader may attach to — rule 19.01)
  static CAN_LEAD = ["terminator squad"];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "infantry" },
    { keywordId: "character" },
    { keywordId: "imperium" },
    { keywordId: "psyker" },
    { keywordId: "terminator" },
    { keywordId: "librarian" },
  ];

  static ICON = "/icons/LibrarianTerminator.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 20; // Size of the base
  static ICON_SCALE = 1.9; // Size of the icon
  static ILLUSTRATION_RATIO = 150; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, LibrarianTerminator.HP_MAX, startPos);
  }
}
