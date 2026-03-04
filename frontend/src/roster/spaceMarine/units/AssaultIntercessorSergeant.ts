// frontend/src/roster/spaceMarine/units/AssaultIntercessor.ts

import { getWeapons } from "../armory";
import { SpaceMarineInfantryTroopMeleeElite } from "../classes/SpaceMarineInfantryTroopMeleeElite";

export class AssaultIntercessorSergeant extends SpaceMarineInfantryTroopMeleeElite {
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

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "assault intercessor squad"}];

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // MeleeTroop specialist - backbone melee

  static ICON = "/icons/AssaultIntercessorSergeant.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, AssaultIntercessorSergeant.HP_MAX, startPos);
  }
}
